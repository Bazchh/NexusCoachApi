from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value


REDIS_URL = _env("REDIS_URL")
POSTGRES_DSN = _env("POSTGRES_DSN")

STT_PROVIDER = _env("STT_PROVIDER", "openai")
OPENAI_API_KEY = _env("OPENAI_API_KEY")
WHISPER_MODEL = _env("WHISPER_MODEL", "whisper-1")

LLM_PROVIDER = _env("LLM_PROVIDER", "rules")
GEMINI_API_KEY = _env("GEMINI_API_KEY")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-1.5-flash")

MAX_HISTORY = int(_env("MAX_HISTORY", "20") or "20")
SESSION_TTL_SECONDS = int(_env("SESSION_TTL_SECONDS", "21600") or "21600")
