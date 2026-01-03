from __future__ import annotations

import json
import logging
from typing import Any

import psycopg

from app.config import POSTGRES_DSN
from app.store import Session

logger = logging.getLogger("nexuscoach")
_tables_ready = False


def _ensure_tables(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        create table if not exists session_logs (
            session_id text primary key,
            locale text,
            state jsonb,
            history jsonb,
            feedback jsonb,
            ended_at timestamptz default now()
        )
        """
    )
    conn.execute(
        """
        create table if not exists advice_bank (
            id bigserial primary key,
            champion text,
            lane text,
            enemy text,
            intent text,
            game_phase text,
            status text,
            reply_text text not null,
            positive_count int default 0,
            negative_count int default 0,
            score int default 0,
            last_seen timestamptz default now()
        )
        """
    )
    conn.execute(
        """
        create unique index if not exists advice_unique
        on advice_bank (champion, lane, enemy, intent, game_phase, status, reply_text)
        """
    )


def persist_session_end(session: Session, feedback: dict[str, Any] | None) -> None:
    if not POSTGRES_DSN:
        return
    global _tables_ready
    try:
        with psycopg.connect(POSTGRES_DSN) as conn:
            if not _tables_ready:
                _ensure_tables(conn)
                _tables_ready = True
            conn.execute(
                """
                insert into session_logs (session_id, locale, state, history, feedback)
                values (%s, %s, %s, %s, %s)
                on conflict (session_id)
                do update set
                    locale = excluded.locale,
                    state = excluded.state,
                    history = excluded.history,
                    feedback = excluded.feedback,
                    ended_at = now()
                """,
                (
                    session.session_id,
                    session.locale,
                    json.dumps(session.state),
                    json.dumps(session.history),
                    json.dumps(feedback) if feedback else None,
                ),
            )
            if feedback:
                _update_advice_from_session(conn, session, feedback)
            conn.commit()
    except Exception:
        logger.exception("postgres_persist_failed")


def _update_advice_from_session(
    conn: psycopg.Connection, session: Session, feedback: dict[str, Any]
) -> None:
    rating = feedback.get("rating")
    if rating not in {"good", "bad"}:
        return
    positive = 1 if rating == "good" else 0
    negative = 1 if rating == "bad" else 0
    score = 1 if rating == "good" else -1

    for item in session.history:
        context = item.get("context") or {}
        intent = item.get("intent")
        reply = item.get("reply")
        if not reply:
            continue
        conn.execute(
            """
            insert into advice_bank
                (champion, lane, enemy, intent, game_phase, status, reply_text,
                 positive_count, negative_count, score)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (champion, lane, enemy, intent, game_phase, status, reply_text)
            do update set
                positive_count = advice_bank.positive_count + excluded.positive_count,
                negative_count = advice_bank.negative_count + excluded.negative_count,
                score = advice_bank.score + excluded.score,
                last_seen = now()
            """,
            (
                context.get("champion") or session.state.get("champion"),
                context.get("lane") or session.state.get("lane"),
                context.get("enemy") or session.state.get("enemy"),
                intent,
                context.get("game_phase") or session.state.get("game_phase"),
                context.get("status") or session.state.get("status"),
                reply,
                positive,
                negative,
                score,
            ),
        )


def retrieve_advice(state: dict[str, Any], intent: str, limit: int = 3) -> list[str]:
    if not POSTGRES_DSN:
        return []
    try:
        with psycopg.connect(POSTGRES_DSN) as conn:
            rows = conn.execute(
                """
                select reply_text,
                       (case when champion = %s then 3 else 0 end) +
                       (case when lane = %s then 2 else 0 end) +
                       (case when enemy = %s then 2 else 0 end) +
                       (case when intent = %s then 2 else 0 end) +
                       (case when game_phase = %s then 1 else 0 end) +
                       (case when status = %s then 1 else 0 end) +
                       score as rank_score,
                       score,
                       last_seen
                from advice_bank
                order by rank_score desc, score desc, last_seen desc
                limit %s
                """,
                (
                    state.get("champion"),
                    state.get("lane"),
                    state.get("enemy"),
                    intent,
                    state.get("game_phase"),
                    state.get("status"),
                    limit,
                ),
            ).fetchall()
            return [row[0] for row in rows if row and row[0]]
    except Exception:
        logger.exception("advice_retrieve_failed")
        return []
