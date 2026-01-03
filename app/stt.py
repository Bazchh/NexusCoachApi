from __future__ import annotations

import tempfile
from typing import Optional

from openai import OpenAI

from app.config import OPENAI_API_KEY, STT_PROVIDER, WHISPER_MODEL
from app.errors import AppError
from app.i18n import msg

_whisper_model = None


def transcribe_audio(content: bytes, locale: Optional[str]) -> str:
    provider = STT_PROVIDER.lower()
    if provider == "openai":
        return _transcribe_openai(content, locale)
    if provider == "local":
        return _transcribe_local(content, locale)
    raise AppError(
        code="STT_FAILED",
        user_message=msg(locale, "stt_failed"),
        status_code=500,
    )


def _transcribe_openai(content: bytes, locale: Optional[str]) -> str:
    if not OPENAI_API_KEY:
        raise AppError(
            code="STT_FAILED",
            user_message=msg(locale, "stt_failed"),
            status_code=500,
        )
    client = OpenAI(api_key=OPENAI_API_KEY)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        tmp.write(content)
        tmp.flush()
        with open(tmp.name, "rb") as audio_file:
            kwargs = {"model": WHISPER_MODEL, "file": audio_file}
            language = _locale_to_language(locale)
            if language:
                kwargs["language"] = language
            response = client.audio.transcriptions.create(**kwargs)
    text = response.text.strip()
    if not text:
        raise AppError(
            code="STT_UNCLEAR",
            user_message=msg(locale, "stt_unclear"),
            status_code=400,
        )
    return text


def _transcribe_local(content: bytes, locale: Optional[str]) -> str:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise AppError(
            code="STT_FAILED",
            user_message=msg(locale, "stt_failed"),
            status_code=500,
        ) from exc

    global _whisper_model
    if _whisper_model is None:
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        tmp.write(content)
        tmp.flush()
        segments, _ = _whisper_model.transcribe(
            tmp.name, language=_locale_to_language(locale)
        )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    if not text:
        raise AppError(
            code="STT_UNCLEAR",
            user_message=msg(locale, "stt_unclear"),
            status_code=400,
        )
    return text


def _locale_to_language(locale: Optional[str]) -> Optional[str]:
    if not locale:
        return None
    if locale.lower().startswith("pt"):
        return "pt"
    return None
