from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.config import MAX_HISTORY, REDIS_URL, SESSION_TTL_SECONDS

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency
    redis = None

logger = logging.getLogger("nexuscoach")


@dataclass
class Session:
    session_id: str
    state: dict[str, Any]
    locale: str
    history: list[dict[str, Any]]


class BaseStore:
    def create_session(self, initial_state: dict[str, Any], locale: str) -> Session:
        raise NotImplementedError

    def get_session(self, session_id: str) -> Session | None:
        raise NotImplementedError

    def update_session(self, session_id: str, updates: dict[str, Any]) -> Session | None:
        raise NotImplementedError

    def append_history(self, session_id: str, item: dict[str, Any]) -> Session | None:
        raise NotImplementedError

    def end_session(self, session_id: str) -> Session | None:
        raise NotImplementedError


class MemoryStore(BaseStore):
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create_session(self, initial_state: dict[str, Any], locale: str) -> Session:
        session_id = str(uuid4())
        state = {
            "game_phase": "early",
            "status": "even",
            "timestamp": None,
        }
        state.update(initial_state)
        session = Session(session_id=session_id, state=state, locale=locale, history=[])
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def update_session(self, session_id: str, updates: dict[str, Any]) -> Session | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session.state.update(updates)
        return session

    def append_history(self, session_id: str, item: dict[str, Any]) -> Session | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session.history.append(item)
        if len(session.history) > MAX_HISTORY:
            session.history = session.history[-MAX_HISTORY:]
        return session

    def end_session(self, session_id: str) -> Session | None:
        return self._sessions.pop(session_id, None)


class RedisStore(BaseStore):
    def __init__(self, client: "redis.Redis") -> None:
        self._client = client

    def create_session(self, initial_state: dict[str, Any], locale: str) -> Session:
        session_id = str(uuid4())
        state = {
            "game_phase": "early",
            "status": "even",
            "timestamp": None,
        }
        state.update(initial_state)
        session = Session(session_id=session_id, state=state, locale=locale, history=[])
        self._set_session(session)
        return session

    def get_session(self, session_id: str) -> Session | None:
        payload = self._client.get(self._key(session_id))
        if not payload:
            return None
        return self._decode(payload)

    def update_session(self, session_id: str, updates: dict[str, Any]) -> Session | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        session.state.update(updates)
        self._set_session(session)
        return session

    def append_history(self, session_id: str, item: dict[str, Any]) -> Session | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        session.history.append(item)
        if len(session.history) > MAX_HISTORY:
            session.history = session.history[-MAX_HISTORY:]
        self._set_session(session)
        return session

    def end_session(self, session_id: str) -> Session | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        self._client.delete(self._key(session_id))
        return session

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}"

    def _set_session(self, session: Session) -> None:
        payload = json.dumps(
            {
                "session_id": session.session_id,
                "state": session.state,
                "locale": session.locale,
                "history": session.history,
            }
        )
        self._client.setex(self._key(session.session_id), SESSION_TTL_SECONDS, payload)

    def _decode(self, payload: bytes) -> Session:
        data = json.loads(payload)
        return Session(
            session_id=data["session_id"],
            state=data["state"],
            locale=data.get("locale", "pt-BR"),
            history=data.get("history", []),
        )


_store: BaseStore | None = None


def get_store() -> BaseStore:
    global _store
    if _store is not None:
        return _store
    if REDIS_URL and redis is not None:
        try:
            client = redis.Redis.from_url(REDIS_URL)
            client.ping()
            _store = RedisStore(client)
            return _store
        except Exception:
            logger.warning("redis_unavailable_fallback_to_memory")
    _store = MemoryStore()
    return _store
