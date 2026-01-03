from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app import db, nlu, strategy, store, stt
from app.errors import AppError
from app.i18n import msg
from app.models import (
    EnvelopeError,
    EnvelopeOk,
    ErrorPayload,
    SessionEndRequest,
    SessionStartRequest,
    TurnRequest,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nexuscoach")

app = FastAPI(title="NexusCoach API", version="0.1.0")
session_store = store.get_store()


def envelope_ok(data: dict[str, Any]) -> JSONResponse:
    payload = EnvelopeOk(data=data)
    return JSONResponse(status_code=200, content=payload.model_dump())


def envelope_error(code: str, user_message: str, status_code: int) -> JSONResponse:
    correlation_id = str(uuid4())
    payload = EnvelopeError(
        error=ErrorPayload(
            code=code,
            user_message=user_message,
            correlation_id=correlation_id,
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    logger.warning("app_error code=%s", exc.code)
    return envelope_error(exc.code, exc.user_message, exc.status_code)


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error")
    return envelope_error("INTERNAL_ERROR", msg(None, "internal_error"), 500)


@app.post("/session/start")
async def session_start(request: SessionStartRequest) -> JSONResponse:
    session = session_store.create_session(
        initial_state=request.initial_context.model_dump(),
        locale=request.locale,
    )
    return envelope_ok({"session_id": session.session_id, "state": session.state})


@app.post("/turn")
async def turn(request: TurnRequest) -> JSONResponse:
    session = session_store.get_session(request.session_id)
    if session is None:
        raise AppError(
            code="SESSION_NOT_FOUND",
            user_message=msg(None, "session_not_found"),
            status_code=404,
        )

    response = _process_turn(
        session=session,
        text=request.text,
        timestamp=request.timestamp,
        client_state_hint=request.client_state_hint,
    )
    return envelope_ok(response)


@app.post("/turn/audio")
async def turn_audio(
    session_id: str = Form(...),
    audio: UploadFile = File(...),
    locale: str | None = Form(None),
) -> JSONResponse:
    session = session_store.get_session(session_id)
    if session is None:
        raise AppError(
            code="SESSION_NOT_FOUND",
            user_message=msg(None, "session_not_found"),
            status_code=404,
        )
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise AppError(
            code="STT_UNCLEAR",
            user_message=msg(locale or session.locale, "stt_unclear"),
            status_code=400,
        )
    text = stt.transcribe_audio(audio_bytes, locale or session.locale)
    response = _process_turn(session=session, text=text, timestamp=None, client_state_hint=None)
    return envelope_ok(response)


@app.post("/session/end")
async def session_end(request: SessionEndRequest) -> JSONResponse:
    feedback = request.feedback.model_dump() if request.feedback else None
    session = session_store.end_session(request.session_id)
    if session is None:
        raise AppError(
            code="SESSION_NOT_FOUND",
            user_message=msg(None, "session_already_ended"),
            status_code=404,
        )
    db.persist_session_end(session, feedback)
    return envelope_ok({"ok": True})


def _process_turn(
    session: store.Session,
    text: str,
    timestamp: datetime | None,
    client_state_hint: dict[str, Any] | None,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if client_state_hint:
        updates.update(client_state_hint)

    text_clean = text.strip()
    if not text_clean:
        raise AppError(
            code="STT_UNCLEAR",
            user_message=msg(session.locale, "stt_unclear"),
            status_code=400,
        )

    updates.update(nlu.extract_state_hints(text_clean))
    item_hints = nlu.extract_item_hints(text_clean)
    if item_hints:
        updates.update(_merge_item_hints(session.state, item_hints))
    updates["last_user_text"] = text_clean
    updates["timestamp"] = (timestamp or datetime.now(tz=timezone.utc)).isoformat()

    updated_session = session_store.update_session(session.session_id, updates)
    if updated_session is None:
        raise AppError(
            code="SESSION_NOT_FOUND",
            user_message=msg(session.locale, "session_not_found"),
            status_code=404,
        )

    intent = nlu.infer_intent(text_clean)
    advice = db.retrieve_advice(updated_session.state, intent)
    reply = strategy.generate_reply(
        updated_session.state,
        intent,
        updated_session.history,
        advice,
        updated_session.locale,
        text_clean,
    )
    session_store.update_session(
        session.session_id,
        {"last_intent": intent, "last_reply": reply},
    )
    session_store.append_history(
        session.session_id,
        {
            "text": text_clean,
            "reply": reply,
            "intent": intent,
            "context": {
                "champion": updated_session.state.get("champion"),
                "lane": updated_session.state.get("lane"),
                "enemy": updated_session.state.get("enemy"),
                "game_phase": updated_session.state.get("game_phase"),
                "status": updated_session.state.get("status"),
                "gold": updated_session.state.get("gold"),
            },
            "timestamp": updates["timestamp"],
        },
    )

    refreshed = session_store.get_session(session.session_id) or updated_session
    return {
        "reply_text": reply,
        "updated_state": refreshed.state,
        "suggested_tts": {"rate": 1.0, "voice": refreshed.locale},
    }


def _merge_item_hints(
    state: dict[str, Any], item_hints: dict[str, Any]
) -> dict[str, Any]:
    updates: dict[str, Any] = {}

    if "self_item" in item_hints:
        entry = item_hints["self_item"]
        item = entry.get("item")
        if item:
            self_items = list(state.get("self_items", []))
            if entry.get("status") == "has" and item not in self_items:
                self_items.append(item)
            updates["self_items"] = self_items
            if entry.get("status") == "building":
                updates["self_building"] = item
            updates["last_self_item"] = item

    if "enemy_item" in item_hints:
        entry = item_hints["enemy_item"]
        champion = entry.get("champion")
        item = entry.get("item")
        if champion and item:
            enemy_items = dict(state.get("enemy_items", {}))
            current = list(enemy_items.get(champion, []))
            if entry.get("status") == "has" and item not in current:
                current.append(item)
            enemy_items[champion] = current
            updates["enemy_items"] = enemy_items

            if entry.get("status") == "building":
                enemy_building = dict(state.get("enemy_building", {}))
                enemy_building[champion] = item
                updates["enemy_building"] = enemy_building

            updates["last_enemy_item"] = {"champion": champion, "item": item}

    return updates
