from __future__ import annotations

from typing import Any

from app.i18n import msg
from app.llm import generate_reply as llm_generate_reply


def generate_reply(
    state: dict[str, Any],
    intent: str,
    history: list[dict[str, Any]],
    advice: list[str],
    locale: str | None,
    user_text: str,
) -> str:
    champion = state.get("champion", "")
    enemy = state.get("enemy", "")
    lane = state.get("lane", "")
    phase = state.get("game_phase", "early")
    status = state.get("status", "even")
    gold = state.get("gold")
    last_reply = state.get("last_reply")
    last_enemy_item = state.get("last_enemy_item")
    last_self_item = state.get("last_self_item")

    context_bits = []
    if gold is not None:
        context_bits.append(f"{gold} gold" if locale and locale.startswith("en") else f"{gold} de ouro")
    if status in {"ahead", "behind", "even"}:
        if locale and locale.startswith("en"):
            context_bits.append(status)
        else:
            context_bits.append(
                "na frente" if status == "ahead" else "atrás" if status == "behind" else "empatado"
            )
    if phase in {"early", "mid", "late"}:
        context_bits.append(phase)
    context_hint = ""
    if context_bits:
        context_hint = " (" + ", ".join(context_bits) + ")"

    llm_reply = llm_generate_reply(
        state=state,
        intent=intent,
        history=history,
        advice=advice,
        locale=locale,
        user_text=user_text,
    )
    if llm_reply:
        return llm_reply

    if intent == "build":
        return msg(locale, "build_defensive")
    if intent == "all_in":
        if phase == "early":
            return msg(locale, "all_in_early")
        return msg(locale, "all_in_advantage")
    if intent == "objective":
        return msg(locale, "objective")
    if intent == "macro":
        return msg(locale, "macro")
    if intent == "follow_up" and last_reply:
        return msg(locale, "follow_up", last_reply=last_reply)

    if last_enemy_item and intent in {"build", "general"}:
        champ = last_enemy_item.get("champion")
        item = last_enemy_item.get("item")
        if champ and item:
            return msg(locale, "enemy_item", champion=champ, item=item)

    if last_self_item and intent in {"build", "general"}:
        return msg(locale, "self_item", item=last_self_item)

    if advice:
        return advice[0]

    if champion and enemy and lane:
        return msg(
            locale,
            "matchup",
            champion=champion,
            enemy=enemy,
            lane=lane,
            context=context_hint,
        )

    if last_reply:
        return msg(locale, "continue_strategy", last_reply=last_reply)

    return msg(locale, "need_context")
