"""A local meeting-URL form and the lifecycle of its native OpenAI demo sessions."""

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from app.agent import run_agent, session_settings
from app.config import ROOT, Settings, bounded_integer
from app.meeting_tools import MeetingState
from app.realtime import RealtimeError
from app.recall_client import RecallClient, RecallError

logger = logging.getLogger("meeting-demo")


@dataclass
class DemoSession:
    meeting_url: str
    id: str = field(default_factory=lambda: uuid4().hex)
    bot_id: str | None = None
    status: str = "connecting"
    message: str = "Requesting the agent. Admit openai demo if prompted."
    state: MeetingState = field(default_factory=MeetingState)
    task: asyncio.Task | None = None


sessions: dict[str, DemoSession] = {}


async def run_session(session: DemoSession, settings: Settings, client: RecallClient) -> None:
    started_at_ms = int(time.time() * 1000)
    final_status = "closed"
    final_message = "The agent has left the meeting."

    def ready():
        session.status = "ready"
        session.message = "Ready. Unmute your microphone and start a request with 'Assistant'."

    async with client:
        try:
            session.bot_id = await client.create_bot(session.meeting_url, session_settings(settings))
            await run_agent(client, session.bot_id, settings, session.state, started_at_ms, ready)
        except asyncio.CancelledError:
            final_message = "The demo server is stopping."
            raise
        except TimeoutError:
            was_ready = session.status == "ready"
            final_status = "closed" if was_ready else "failed"
            final_message = (
                "The configured demo time limit was reached."
                if was_ready else
                "OpenAI did not connect before the startup deadline. Check meeting admission, "
                "the saved OpenAI key, and native OpenAI/log access in your Recall workspace."
            )
        except (ValueError, RecallError, RealtimeError) as error:
            final_status = "failed"
            final_message = str(error)
        except Exception as error:  # noqa: BLE001 -- session boundary must report failure and clean up
            final_status = "failed"
            final_message = "The agent connection failed. Check the local server and provider settings."
            logger.error("Demo session failed (%s)", type(error).__name__)
        finally:
            # Keep polling and duplicate protection active until departure settles.
            session.status = "closing"
            session.message = "Ending the agent session."
            if session.bot_id and not session.state.leave_attempted:
                session.state.leave_attempted = True
                try:
                    await client.leave_call(session.bot_id)
                    session.state.is_leaving = True
                except RecallError:
                    logger.warning("Could not confirm bot departure; check the meeting")
                    final_message += " Bot departure is unconfirmed; check the meeting."
            elif session.bot_id and not session.state.is_leaving:
                final_message += " Bot departure is unconfirmed; check the meeting."
            session.message = final_message
            session.status = final_status


@asynccontextmanager
async def lifespan(_app):
    try:
        yield
    finally:
        tasks = [session.task for session in sessions.values() if session.task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


class MeetingRequest(BaseModel):
    meeting_url: str

    @field_validator("meeting_url")
    @classmethod
    def validate_meeting_url(cls, value: str) -> str:
        url = value.strip()
        error = "Enter a direct HTTPS meeting link from Zoom, Google Meet, Microsoft Teams, or Webex."
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise ValueError(error) from None

        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or "\\" in url
            or any(char.isspace() or ord(char) < 32 for char in url)
        ):
            raise ValueError(error)

        host = parsed.hostname or ""
        if host == "meet.google.com":
            # Preserve the existing room key for duplicate submissions.
            if (
                parsed.netloc == host
                and not parsed.fragment
                and re.fullmatch(r"/[a-z]{3}-[a-z]{4}-[a-z]{3}/?", parsed.path)
            ):
                return f"https://meet.google.com{parsed.path.rstrip('/')}"
            return url
        if host in {"teams.microsoft.com", "teams.cloud.microsoft", "teams.live.com"} or any(
            host == domain or host.endswith("." + domain)
            for domain in ("zoom.us", "zoom.com", "zoom-x.de", "webex.com")
        ):
            return url
        raise ValueError(error)


@app.get("/")
async def index():
    return FileResponse(ROOT / "app" / "templates" / "index.html")


@app.post("/api/bots", status_code=202)
async def create_meeting_agent(body: MeetingRequest, request: Request):
    origin = request.headers.get("origin")
    if origin and origin != f"http://{request.url.netloc}":
        raise HTTPException(403, "Use the local demo page to launch an agent.")
    if any(session.meeting_url == body.meeting_url and session.status in {"connecting", "ready", "closing"}
           for session in sessions.values()):
        raise HTTPException(409, "An agent for this meeting is already starting, active, or shutting down.")
    try:
        settings = Settings.from_env()
        client = RecallClient(settings.recall_api_key, settings.recall_base_url)
        if not settings.model or not settings.voice:
            raise ValueError("Set REALTIME_MODEL and REALTIME_VOICE in .env.")
    except ValueError as error:
        raise HTTPException(503, str(error)) from None
    # Keep only recent completed sessions; this app does not persist meeting data.
    for session_id, existing in list(sessions.items()):
        if len(sessions) < 50:
            break
        if existing.task is not None and existing.task.done():
            del sessions[session_id]
    if len(sessions) >= 50:
        raise HTTPException(409, "Stop an existing demo before launching another.")
    session = DemoSession(meeting_url=body.meeting_url)
    sessions[session.id] = session
    session.task = asyncio.create_task(run_session(session, settings, client))
    return {"session_id": session.id, "message": session.message}


@app.get("/api/sessions/{session_id}")
async def session_status(session_id: str):
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "This demo session is no longer available.")
    return {"status": session.status, "message": session.message, "bot_id": session.bot_id}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    uvicorn.run(app, host="127.0.0.1", port=bounded_integer("LAUNCHER_PORT", 8003, 1024, 65535),
                access_log=False)
