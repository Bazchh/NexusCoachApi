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
    # Tabela de correções aprendidas do feedback
    conn.execute(
        """
        create table if not exists corrections (
            id bigserial primary key,
            champion text,
            ability text,
            topic text,
            wrong_info text not null,
            correct_info text not null,
            source_session text,
            confidence int default 1,
            created_at timestamptz default now()
        )
        """
    )
    conn.execute(
        """
        create index if not exists corrections_champion_idx on corrections (lower(champion))
        """
    )
    conn.execute(
        """
        create index if not exists corrections_topic_idx on corrections (lower(topic))
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
                # Extrai correção se feedback negativo com comentário
                if feedback.get("rating") == "bad" and feedback.get("comment"):
                    extract_correction_from_feedback(
                        conn=conn,
                        session_id=session.session_id,
                        feedback_comment=feedback["comment"],
                        history=session.history,
                        state=session.state,
                    )
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
    global _tables_ready
    try:
        with psycopg.connect(POSTGRES_DSN) as conn:
            if not _tables_ready:
                _ensure_tables(conn)
                conn.commit()
                _tables_ready = True
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


def _write_correction(
    conn: psycopg.Connection,
    champion: str | None,
    ability: str | None,
    topic: str | None,
    wrong_info: str,
    correct_info: str,
    source_session: str | None,
) -> None:
    existing = conn.execute(
        """
        select id, confidence from corrections
        where lower(coalesce(champion, '')) = lower(coalesce(%s, ''))
          and lower(coalesce(ability, '')) = lower(coalesce(%s, ''))
          and lower(coalesce(topic, '')) = lower(coalesce(%s, ''))
          and lower(correct_info) = lower(%s)
        limit 1
        """,
        (champion, ability, topic, correct_info),
    ).fetchone()

    if existing:
        conn.execute(
            "update corrections set confidence = confidence + 1 where id = %s",
            (existing[0],),
        )
        return

    conn.execute(
        """
        insert into corrections (champion, ability, topic, wrong_info, correct_info, source_session)
        values (%s, %s, %s, %s, %s, %s)
        """,
        (champion, ability, topic, wrong_info, correct_info, source_session),
    )


def save_correction(
    champion: str | None,
    ability: str | None,
    topic: str | None,
    wrong_info: str,
    correct_info: str,
    source_session: str | None = None,
    conn: psycopg.Connection | None = None,
) -> bool:
    """Salva uma correção no banco de dados."""
    if not POSTGRES_DSN:
        return False
    try:
        if conn is None:
            with psycopg.connect(POSTGRES_DSN) as local_conn:
                _ensure_tables(local_conn)
                _write_correction(
                    local_conn,
                    champion,
                    ability,
                    topic,
                    wrong_info,
                    correct_info,
                    source_session,
                )
                local_conn.commit()
            return True

        _ensure_tables(conn)
        _write_correction(
            conn,
            champion,
            ability,
            topic,
            wrong_info,
            correct_info,
            source_session,
        )
        return True
    except Exception:
        logger.exception("save_correction_failed")
        return False


def retrieve_corrections(
    champions: list[str] | None = None,
    topics: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Recupera correções relevantes para incluir no prompt."""
    if not POSTGRES_DSN:
        return []
    global _tables_ready
    try:
        with psycopg.connect(POSTGRES_DSN) as conn:
            if not _tables_ready:
                _ensure_tables(conn)
                conn.commit()
                _tables_ready = True
            # Busca correções que matcham os campeões ou tópicos
            conditions = []
            params: list[Any] = []

            if champions:
                placeholders = ", ".join(["%s"] * len(champions))
                conditions.append(f"lower(champion) in ({placeholders})")
                params.extend([c.lower() for c in champions])

            if topics:
                placeholders = ", ".join(["%s"] * len(topics))
                conditions.append(f"lower(topic) in ({placeholders})")
                params.extend([t.lower() for t in topics])

            where_clause = ""
            if conditions:
                where_clause = "where " + " or ".join(conditions)

            params.append(limit)

            rows = conn.execute(
                f"""
                select champion, ability, topic, wrong_info, correct_info, confidence
                from corrections
                {where_clause}
                order by confidence desc, created_at desc
                limit %s
                """,
                params,
            ).fetchall()

            return [
                {
                    "champion": row[0],
                    "ability": row[1],
                    "topic": row[2],
                    "wrong_info": row[3],
                    "correct_info": row[4],
                    "confidence": row[5],
                }
                for row in rows
            ]
    except Exception:
        logger.exception("retrieve_corrections_failed")
        return []


def extract_correction_from_feedback(
    session_id: str,
    feedback_comment: str,
    history: list[dict[str, Any]],
    state: dict[str, Any],
    conn: psycopg.Connection | None = None,
) -> bool:
    """
    Extrai correção de um comentário de feedback usando LLM.
    Chamado automaticamente quando feedback é 'bad' com comentário.
    """
    if not feedback_comment or len(feedback_comment.strip()) < 10:
        return False

    # Importa aqui para evitar circular import
    from app.config import GEMINI_API_KEY, GEMINI_MODEL, LLM_PROVIDER

    if LLM_PROVIDER != "gemini" or not GEMINI_API_KEY:
        return False

    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError:
        return False

    # Monta contexto da última interação
    last_reply = ""
    for item in reversed(history):
        if item.get("reply"):
            last_reply = item["reply"]
            break

    champion = state.get("champion", "")
    enemy = state.get("enemy", "")

    prompt = f"""Analise este feedback negativo de um usuário sobre uma dica de Wild Rift e extraia a correção se houver.

Dica que o coach deu: "{last_reply}"

Feedback do usuário: "{feedback_comment}"

Campeão do usuário: {champion}
Inimigo: {enemy}

Se o feedback contém uma CORREÇÃO sobre mecânica do jogo (ex: "a skill atravessa minions", "o cooldown é 10s", etc), responda APENAS em JSON:
{{"champion": "nome ou null", "ability": "nome da skill ou null", "topic": "tema geral ou null", "wrong_info": "o que estava errado", "correct_info": "informação correta"}}

Se o feedback é apenas reclamação geral sem correção específica, responda:
{{"no_correction": true}}

Responda APENAS o JSON, nada mais."""

    try:
        logger.info("extract_correction: creating client...")
        client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options={"timeout": 30000},
        )
        logger.info("extract_correction: calling generate_content...")
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=200,
            ),
        )
        logger.info(f"extract_correction: got response: {response.text[:100] if response and response.text else 'None'}")

        if not response or not response.text:
            return False

        # Parse JSON da resposta
        import re
        text = response.text.strip()
        # Remove markdown se houver
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)

        data = json.loads(text)

        if data.get("no_correction"):
            return False

        # Salva a correção
        return save_correction(
            champion=data.get("champion"),
            ability=data.get("ability"),
            topic=data.get("topic"),
            wrong_info=data.get("wrong_info", ""),
            correct_info=data.get("correct_info", ""),
            source_session=session_id,
            conn=conn,
        )
    except Exception:
        logger.exception("extract_correction_failed")
        return False
