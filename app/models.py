from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class InitialContext(BaseModel):
    champion: str
    lane: str
    enemy: Optional[str] = None


class SessionStartRequest(BaseModel):
    device_id: str
    locale: str = Field(default="pt-BR")
    initial_context: InitialContext


class SessionStartResponse(BaseModel):
    session_id: str
    state: dict[str, Any]


class TurnRequest(BaseModel):
    session_id: str
    text: str
    timestamp: Optional[datetime] = None
    client_state_hint: Optional[dict[str, Any]] = None


class TurnResponse(BaseModel):
    reply_text: str
    updated_state: dict[str, Any]
    suggested_tts: dict[str, Any] = Field(default_factory=dict)


class Feedback(BaseModel):
    rating: Literal["good", "bad"]
    comment: Optional[str] = None


class SessionEndRequest(BaseModel):
    session_id: str
    feedback: Optional[Feedback] = None


class ErrorPayload(BaseModel):
    code: str
    user_message: str
    correlation_id: str


class EnvelopeOk(BaseModel):
    ok: bool = True
    data: dict[str, Any]


class EnvelopeError(BaseModel):
    ok: bool = False
    error: ErrorPayload
