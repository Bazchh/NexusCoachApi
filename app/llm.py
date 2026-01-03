from __future__ import annotations

import logging
from typing import Any

from app.config import GEMINI_API_KEY, GEMINI_MODEL, LLM_PROVIDER

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - optional dependency
    genai = None

logger = logging.getLogger("nexuscoach")


def generate_reply(
    *,
    state: dict[str, Any],
    intent: str,
    history: list[dict[str, Any]],
    advice: list[str],
    locale: str | None,
    user_text: str,
) -> str | None:
    if LLM_PROVIDER != "gemini":
        return None
    if not GEMINI_API_KEY or genai is None:
        return None

    prompt = _build_prompt(
        state=state,
        intent=intent,
        history=history,
        advice=advice,
        locale=locale,
        user_text=user_text,
    )

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(model_name=GEMINI_MODEL)
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.5,
                "top_p": 0.9,
                "max_output_tokens": 180,
            },
        )
    except Exception:
        logger.exception("gemini_request_failed")
        return None

    if not response or not getattr(response, "text", None):
        return None
    return response.text.strip() or None


def _build_prompt(
    *,
    state: dict[str, Any],
    intent: str,
    history: list[dict[str, Any]],
    advice: list[str],
    locale: str | None,
    user_text: str,
) -> str:
    locale = locale or "pt-BR"
    is_en = locale.lower().startswith("en")
    language_line = (
        "Reply in English (en-US)."
        if is_en
        else "Responda em português (pt-BR)."
    )

    champion = state.get("champion") or "unknown"
    lane = state.get("lane") or "unknown"
    enemy = state.get("enemy") or "unknown"
    phase = state.get("game_phase") or "unknown"
    status = state.get("status") or "unknown"
    gold = state.get("gold")
    last_reply = state.get("last_reply") or ""

    self_items = ", ".join(state.get("self_items", [])) or "none"
    enemy_items_map = state.get("enemy_items", {}) or {}
    enemy_items = (
        "; ".join(
            f"{champ}: {', '.join(items)}"
            for champ, items in enemy_items_map.items()
            if items
        )
        or "none"
    )

    history_lines = []
    for item in history[-4:]:
        text = item.get("text")
        reply = item.get("reply")
        if text:
            history_lines.append(f"User: {text}")
        if reply:
            history_lines.append(f"Coach: {reply}")
    history_block = "\n".join(history_lines) or "none"

    advice_block = "\n".join(f"- {item}" for item in advice[:3]) or "none"

    return (
        "You are NexusCoach, an in-game Wild Rift voice coach. "
        "Be short, tactical, and friendly. "
        "Avoid technical explanations. "
        "If context is missing, ask one short question. "
        "Keep answers under 3 sentences.\n"
        f"{language_line}\n\n"
        "Context:\n"
        f"- Champion: {champion}\n"
        f"- Lane: {lane}\n"
        f"- Matchup: {enemy}\n"
        f"- Phase: {phase}\n"
        f"- Status: {status}\n"
        f"- Gold: {gold if gold is not None else 'unknown'}\n"
        f"- Your items: {self_items}\n"
        f"- Enemy items: {enemy_items}\n"
        f"- Intent hint: {intent}\n"
        f"- Last coach tip: {last_reply or 'none'}\n\n"
        "Useful tips from memory:\n"
        f"{advice_block}\n\n"
        "Recent conversation:\n"
        f"{history_block}\n\n"
        "User message:\n"
        f"{user_text}\n"
    )
