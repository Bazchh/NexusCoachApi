from __future__ import annotations

from typing import Any


_MESSAGES: dict[str, dict[str, str]] = {
    "pt": {
        "session_not_found": "Sessão encerrada. Toque em Iniciar Partida para continuar.",
        "session_already_ended": "Sessão já encerrada.",
        "stt_unclear": "Não entendi. Pode repetir?",
        "stt_failed": "Não consegui ouvir agora. Tente novamente.",
        "internal_error": "Tente novamente em instantes.",
        "build_defensive": "Sugestão rápida: foque em item defensivo se estiver atrás.",
        "all_in_early": "Evite all-in cedo. Busque trocas curtas e seguras.",
        "all_in_advantage": "Se tiver vantagem de ouro e ult, pode forçar o all-in.",
        "objective": "Objetivo só com prioridade de rota e visão no rio.",
        "macro": "Se estiver forte no 1v1, split pode ser melhor que agrupar.",
        "follow_up": "Continuando a dica anterior: {last_reply}",
        "matchup": "Matchup {champion} vs {enemy} na {lane}{context}: jogue com calma e evite trocas longas no early.",
        "need_context": "Diga campeão, rota e matchup para eu ajudar melhor.",
        "continue_strategy": "Continuando a estratégia anterior: {last_reply}",
        "enemy_item": "Ok, {champion} com {item}. Se estiver te castigando, priorize defesa antes de dano.",
        "self_item": "Beleza, registrei {item}. Se quiser ajuste, diga seu ouro e o estado da rota.",
    },
    "en": {
        "session_not_found": "Session ended. Tap Start Match to continue.",
        "session_already_ended": "Session already ended.",
        "stt_unclear": "I didn't catch that. Please repeat.",
        "stt_failed": "I couldn't hear you. Try again.",
        "internal_error": "Try again in a moment.",
        "build_defensive": "Quick tip: prioritize defense if you're behind.",
        "all_in_early": "Avoid early all-ins. Take short, safe trades.",
        "all_in_advantage": "If you have a gold lead and ult, you can force the all-in.",
        "objective": "Go for objectives only with lane priority and river vision.",
        "macro": "If you're strong in the 1v1, split can be better than grouping.",
        "follow_up": "Continuing the previous tip: {last_reply}",
        "matchup": "Matchup {champion} vs {enemy} in {lane}{context}: play calm and avoid long trades early.",
        "need_context": "Tell me your champion, lane, and matchup so I can help.",
        "continue_strategy": "Continuing the previous strategy: {last_reply}",
        "enemy_item": "Got it, {champion} has {item}. If it's hurting you, prioritize defense.",
        "self_item": "Noted your {item}. If you want adjustments, tell me your gold and lane state.",
    },
}


def msg(locale: str | None, key: str, **kwargs: Any) -> str:
    lang = _pick_lang(locale)
    template = _MESSAGES.get(lang, _MESSAGES["pt"]).get(key, key)
    return template.format(**kwargs)


def _pick_lang(locale: str | None) -> str:
    if not locale:
        return "pt"
    locale = locale.lower()
    if locale.startswith("en"):
        return "en"
    return "pt"
