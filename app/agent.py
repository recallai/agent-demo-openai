"""Compose one native OpenAI call, its meeting tools, and its control session."""

import asyncio
import logging
from collections.abc import Callable

from app.config import Settings
from app.instructions import INSTRUCTIONS, INTRO_CHAT_MESSAGE
from app.meeting_agent import MeetingAgent
from app.meeting_tools import MeetingState, MeetingTools
from app.realtime import RealtimeConnection
from app.recall_client import RecallClient, RecallError
from app.tool_schema import TOOL_SCHEMAS

logger = logging.getLogger("meeting-demo")


def session_settings(settings: Settings) -> dict:
    """Disable automatic responses from the moment Recall connects meeting audio."""
    session = {
        "type": "realtime",
        "model": settings.model,
        "instructions": INSTRUCTIONS,
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                "transcription": {"model": "gpt-4o-mini-transcribe", "language": "en"},
                "turn_detection": {
                    "type": "semantic_vad", "create_response": False, "interrupt_response": False,
                },
            },
            "output": {"voice": settings.voice},
        },
        "tools": TOOL_SCHEMAS,
        "tool_choice": "auto",
        "truncation": "disabled",
        "max_output_tokens": 2048,
    }
    if settings.reasoning_effort:
        session["reasoning"] = {"effort": settings.reasoning_effort}
    return session


async def run_agent(
    client: RecallClient, bot_id: str, settings: Settings, state: MeetingState,
    started_at_ms: int, on_ready: Callable[[], None],
) -> None:
    # Look up the OpenAI call ID in customer logs during startup only.
    async with asyncio.timeout(settings.connect_timeout) as deadline:
        while (call_id := await client.find_openai_call(bot_id, started_at_ms)) is None:
            await asyncio.sleep(2)
        async with RealtimeConnection(settings.openai_api_key, call_id) as connection:
            await connection.configure(session_settings(settings))

            async def silence_output():
                await controller.silence()

            tools = MeetingTools(client, bot_id, state, silence_output)
            controller = MeetingAgent(connection, tools, state)
            try:
                await client.send_chat_message(bot_id, INTRO_CHAT_MESSAGE)
            except RecallError:
                logger.warning("Could not post the introduction; not retrying")
            # Discovery, attachment, and configuration share the startup deadline.
            # Give the ready conversation its full configured session duration.
            deadline.reschedule(asyncio.get_running_loop().time() + settings.session_timeout)
            on_ready()
            await controller.run()
