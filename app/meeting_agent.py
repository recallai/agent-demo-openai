"""Admit addressed audio turns and execute completed OpenAI tool requests."""

import asyncio
import json
from uuid import uuid4

from app.instructions import INSTRUCTIONS
from app.meeting_tools import MeetingState, MeetingTools
from app.realtime import RealtimeConnection, RealtimeError
from app.request_filter import ADDRESS, CONTROL_REQUEST, RESUME
from app.tool_execution import ToolExecutor
from app.tool_schema import CONTROL_TOOLS


class MeetingAgent:
    def __init__(self, connection: RealtimeConnection, tools: MeetingTools, state: MeetingState):
        self.connection = connection
        self.tools = tools
        self.state = state
        self.executor = ToolExecutor(tools)
        self.finished = asyncio.Event()
        self._context: dict[str, None] = {}
        self._handled_inputs: set[str] = set()
        self._handled_responses: set[str] = set()
        self._speech_starts: dict[str, int] = {}
        self._latest_audio_ms = -1
        self._last_admitted_ms = -1
        self._resume_after_ms = -1
        self._turn = 0
        self._current_input: str | None = None
        self._active_response: str | None = None
        self._audio_playing = False
        self._pending_response = False
        self._needs_response = False
        self._turn_silent = False
        self._work_task: asyncio.Task | None = None
        self._work_error: Exception | None = None
        self._resume_pending = False

    async def silence(self) -> None:
        # Cancelling speech must never cancel an HTTP action already in flight.
        had_response = self._active_response is not None
        if had_response:
            await self.connection.cancel(self._active_response)
        if had_response or self._audio_playing:
            await self.connection.clear_audio()
            self._audio_playing = False

    async def _discard_input(self, item_id: str) -> None:
        self._context.pop(item_id, None)
        await self.connection.send("conversation.item.delete", item_id=item_id)

    async def _on_input(self, event: dict) -> None:
        item_id = event["item_id"]
        if item_id in self._handled_inputs:
            return
        self._handled_inputs.add(item_id)
        started = self._speech_starts.pop(item_id, None)
        transcript = event.get("transcript", "")
        address = ADDRESS.match(transcript)
        request = transcript[address.end():].strip() if address else ""
        stale = started is None or started <= max(self._resume_after_ms, self._last_admitted_ms)
        if not request or stale or self.state.is_leaving:
            await self._discard_input(item_id)
            return
        if not self.state.is_listening:
            await self._discard_input(item_id)
            if RESUME.fullmatch(request):
                self._turn += 1
                self._needs_response = False
                self._resume_pending = True
                if not self._working():
                    self._start_work(self._resume_listening())
            return
        self._last_admitted_ms = started
        self._context[item_id] = None
        self._current_input = item_id
        self._turn += 1
        self._turn_silent = self.state.is_muted or bool(CONTROL_REQUEST.match(request))
        self._needs_response = True
        await self.silence()
        await self._respond_if_ready()

    def _working(self) -> bool:
        return self._work_task is not None and not self._work_task.done()

    def _start_work(self, coroutine) -> None:
        self._work_task = asyncio.create_task(coroutine)

        def completed(task):
            if not task.cancelled() and (error := task.exception()) is not None:
                self._work_error = error
                self.finished.set()

        self._work_task.add_done_callback(completed)

    async def _resume_listening(self) -> None:
        self._resume_pending = False
        self._resume_after_ms = self._latest_audio_ms
        await self.tools.start_listening()
        self._work_task = None
        await self._respond_if_ready()

    async def _respond_if_ready(self) -> None:
        if (not self._needs_response or self._pending_response or self._active_response
                or self._working() or not self.state.is_listening or self.state.is_leaving):
            return
        self._needs_response = False
        self._pending_response = True
        silent = self.state.is_muted or self._turn_silent
        state_description = (
            "Speech is muted; perform requested tools silently. Do not post an ordinary answer to chat."
            if self.state.is_muted else "Speech is enabled."
        )
        await self.connection.send("response.create", response={
            "input": [{"type": "item_reference", "id": item_id} for item_id in self._context],
            "instructions": f"{INSTRUCTIONS}\nCurrent state: listening enabled. {state_description}",
            "output_modalities": ["text" if silent else "audio"],
            "metadata": {"turn": str(self._turn), "silent": str(silent).lower(),
                         "input_id": self._current_input or ""},
        })

    @staticmethod
    def _response_turn(response: dict) -> int:
        try:
            return int(response.get("metadata", {}).get("turn", -1))
        except (TypeError, ValueError):
            return -1

    async def _on_response_created(self, response: dict) -> None:
        self._pending_response = False
        self._active_response = response["id"]
        if self._response_turn(response) != self._turn or not self.state.is_listening:
            await self.silence()

    async def _on_response_done(self, response: dict) -> None:
        response_id = response["id"]
        if response_id in self._handled_responses:
            return
        self._handled_responses.add(response_id)
        if self._active_response == response_id:
            self._active_response = None
        turn = self._response_turn(response)
        current = turn == self._turn and self.state.is_listening and not self.state.is_leaving
        completed = response.get("status") == "completed"
        silent = response.get("metadata", {}).get("silent") == "true"
        output = response.get("output", [])
        calls = [item for item in output if item.get("type") == "function_call"]
        # WebRTC clear truncates interrupted speech at actual playback. Retain its
        # item reference, but never retain a text-only answer that nobody heard.
        for item in output:
            if item.get("type") == "message" and not silent:
                self._context[item["id"]] = None
        if current and completed and calls:
            for call in calls:
                self._context[call["id"]] = None
            self._start_work(self._execute_tools(calls, turn))
            return
        if current and completed and silent and not calls:
            input_id = response.get("metadata", {}).get("input_id")
            if input_id and input_id in self._context:
                await self._discard_input(input_id)
        if current and response.get("status") in {"failed", "incomplete"}:
            await self.tools._post_status("OpenAI could not complete this request. No unfinished actions were executed.")
        await self._respond_if_ready()

    async def _execute_tools(self, calls: list[dict], turn: int) -> None:
        continue_turn = True
        for call in calls:
            if (not continue_turn or turn != self._turn
                    or not self.state.is_listening or self.state.is_leaving):
                result = {"ok": False, "message": "An earlier action failed, or the request was superseded/paused; action not executed."}
            else:
                result = await self.executor.execute(call, turn)
            if call.get("name") in CONTROL_TOOLS and turn == self._turn:
                self._turn_silent = True
                if call["name"] == "start_listening" and result.get("ok"):
                    self._resume_after_ms = self._latest_audio_ms
            continue_turn = continue_turn and result.get("ok", False) and not result.get("repeat")
            if self.state.is_leaving:
                # Recall may close OpenAI immediately; there is nobody left to
                # receive a tool result or continuation on this control channel.
                self.finished.set()
                return
            item_id = f"item_{uuid4().hex[:24]}"
            await self.connection.send("conversation.item.create", item={
                "id": item_id, "type": "function_call_output", "call_id": call["call_id"],
                "output": json.dumps(result),
            })
            self._context[item_id] = None
        if turn == self._turn and continue_turn and self.state.is_listening:
            self._needs_response = True
        if self._resume_pending:
            await self._resume_listening()
            return
        self._work_task = None
        await self._respond_if_ready()

    async def _read_events(self) -> None:
        async for event in self.connection.events():
            kind = event.get("type")
            if kind == "input_audio_buffer.speech_started":
                self._speech_starts[event["item_id"]] = event["audio_start_ms"]
                self._latest_audio_ms = max(self._latest_audio_ms, event["audio_start_ms"])
            elif kind == "input_audio_buffer.speech_stopped":
                self._latest_audio_ms = max(self._latest_audio_ms, event["audio_end_ms"])
            elif kind == "conversation.item.input_audio_transcription.completed":
                await self._on_input(event)
            elif kind == "conversation.item.input_audio_transcription.failed":
                item_id = event["item_id"]
                if item_id not in self._handled_inputs:
                    self._handled_inputs.add(item_id)
                    self._speech_starts.pop(item_id, None)
                    await self._discard_input(item_id)
            elif kind == "response.created":
                await self._on_response_created(event["response"])
            elif kind == "response.done":
                await self._on_response_done(event["response"])
            elif kind == "output_audio_buffer.started":
                self._audio_playing = True
                if self.state.is_muted or not self.state.is_listening:
                    await self.silence()
            elif kind in {"output_audio_buffer.stopped", "output_audio_buffer.cleared"}:
                self._audio_playing = False

    async def run(self) -> None:
        reader = asyncio.create_task(self._read_events())
        stopped = asyncio.create_task(self.finished.wait())
        try:
            done, _ = await asyncio.wait((reader, stopped), return_when=asyncio.FIRST_COMPLETED)
            if reader in done:
                await reader
        finally:
            reader.cancel()
            stopped.cancel()
            await asyncio.gather(reader, stopped, return_exceptions=True)
            # Settle actions that may already have reached Recall before shutdown.
            if self._work_task is not None:
                await asyncio.gather(self._work_task, return_exceptions=True)
        # Recall can close OpenAI before its leave HTTP response arrives. Decide
        # whether EOF was expected only after that action has settled.
        if self.state.is_leaving:
            return
        if self.state.leave_attempted:
            raise RealtimeError(
                "The OpenAI call closed before Recall confirmed bot departure. "
                "Check the meeting before trying again."
            )
        if self._work_error:
            raise self._work_error
        raise RealtimeError("The OpenAI call closed. The demo will remove its meeting bot.")
