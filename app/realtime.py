"""The server-side control connection to Recall's OpenAI WebRTC call."""

import asyncio
import json
import re
from uuid import uuid4

import aiohttp


class RealtimeError(Exception):
    """A provider failure whose message is safe to show without meeting content."""


class RealtimeConnection:
    def __init__(self, api_key: str, call_id: str):
        if not re.fullmatch(r"rtc_[A-Za-z0-9_-]+", call_id):
            raise ValueError("Recall returned an invalid OpenAI call ID.")
        self._api_key = api_key
        self._call_id = call_id
        self._http = None
        self._socket = None
        self._send_lock = asyncio.Lock()
        self._optional_cancellations: set[str] = set()

    async def __aenter__(self):
        self._http = aiohttp.ClientSession(trust_env=False)
        try:
            self._socket = await self._http.ws_connect(
                "wss://api.openai.com/v1/realtime",
                params={"call_id": self._call_id},
                headers={"Authorization": f"Bearer {self._api_key}"},
                heartbeat=20,
                max_msg_size=4 * 1024 * 1024,
                timeout=aiohttp.ClientWSTimeout(ws_close=5),
            )
        except (aiohttp.ClientError, TimeoutError):
            await self._http.close()
            raise RealtimeError(
                "Could not attach to OpenAI. Check that the local key belongs to the same "
                "OpenAI project as the key saved in Recall, and that the call is still active."
            ) from None
        except BaseException:
            # __aexit__ is not called when cancellation interrupts attachment.
            await self._http.close()
            raise
        return self

    async def __aexit__(self, *_):
        if self._socket is not None:
            await self._socket.close()
        if self._http is not None:
            await self._http.close()

    async def send(self, event_type: str, **fields) -> str:
        event_id = f"evt_{uuid4().hex}"
        async with self._send_lock:
            await self._socket.send_json({"type": event_type, "event_id": event_id, **fields})
        return event_id

    async def cancel(self, response_id: str) -> None:
        event_id = await self.send("response.cancel", response_id=response_id)
        self._optional_cancellations.add(event_id)

    async def clear_audio(self) -> None:
        # On WebRTC this also truncates unheard audio in the server conversation.
        await self.send("output_audio_buffer.clear")

    async def events(self):
        async for message in self._socket:
            if message.type == aiohttp.WSMsgType.TEXT:
                try:
                    event = json.loads(message.data)
                except ValueError:
                    raise RealtimeError("OpenAI returned an invalid control event.") from None
                if not isinstance(event, dict):
                    raise RealtimeError("OpenAI returned an invalid control event.")
                if event.get("type") == "error":
                    error = event.get("error", {})
                    event_id = error.get("event_id")
                    if (error.get("code") == "response_cancel_not_active"
                            and event_id in self._optional_cancellations):
                        self._optional_cancellations.discard(event_id)
                        continue
                    raise RealtimeError("OpenAI rejected a session or response request. Check the model and session settings.")
                yield event
            elif message.type == aiohttp.WSMsgType.ERROR:
                raise RealtimeError("The OpenAI control connection failed.")

    async def configure(self, session: dict) -> None:
        settings = {key: value for key, value in session.items() if key != "model"}
        await self.send("session.update", session=settings)
        async with asyncio.timeout(20):
            async for event in self.events():
                if event.get("type") == "session.updated":
                    return
        raise RealtimeError("OpenAI did not confirm the session configuration.")
