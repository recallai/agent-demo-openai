"""Load the small set of settings used by the launcher and Realtime session."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
BOT_NAME = "openai demo"
load_dotenv(ROOT / ".env")


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} in .env before starting the demo.")
    return value


def bounded_integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        if minimum <= value <= maximum:
            return value
    except ValueError:
        pass
    raise ValueError(f"{name} must be between {minimum} and {maximum}.")


@dataclass(frozen=True, repr=False)
class Settings:
    recall_api_key: str
    recall_base_url: str
    openai_api_key: str
    model: str
    voice: str
    reasoning_effort: str | None
    connect_timeout: int
    session_timeout: int

    @classmethod
    def from_env(cls) -> "Settings":
        effort = os.getenv("REALTIME_REASONING_EFFORT", "low").strip().lower()
        if effort not in {"default", "minimal", "low", "medium", "high", "xhigh"}:
            raise ValueError("REALTIME_REASONING_EFFORT must be default, minimal, low, medium, high, or xhigh.")
        return cls(
            recall_api_key=require_env("RECALL_API_KEY"),
            recall_base_url=require_env("RECALL_API_BASE_URL"),
            openai_api_key=require_env("OPENAI_API_KEY"),
            model=os.getenv("REALTIME_MODEL", "gpt-realtime-2.1").strip(),
            voice=os.getenv("REALTIME_VOICE", "marin").strip(),
            reasoning_effort=None if effort == "default" else effort,
            connect_timeout=bounded_integer("CONNECT_TIMEOUT_SECONDS", 300, 30, 600),
            session_timeout=bounded_integer("SESSION_TIMEOUT_SECONDS", 600, 30, 3600),
        )
