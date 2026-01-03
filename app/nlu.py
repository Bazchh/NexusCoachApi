from __future__ import annotations

import re
import unicodedata
from typing import Any


INTENTS = {
    "build": ["item", "build", "proximo", "prox", "comprar", "next", "buy"],
    "all_in": ["all-in", "all in", "allin"],
    "objective": ["dragao", "arauto", "baron", "objetivo", "dragon", "herald", "objective"],
    "status": ["na frente", "atras", "empatado", "even", "ahead", "behind"],
    "macro": ["macro", "split", "agrupo", "group"],
    "follow_up": ["e agora", "agora o que", "continuo", "seguinte", "what now", "and now"],
}


def infer_intent(text: str) -> str:
    text_lower = text.lower()
    for intent, keywords in INTENTS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return intent
    return "general"


def extract_state_hints(text: str) -> dict[str, Any]:
    text_lower = _normalize(text)
    hints: dict[str, Any] = {}

    gold = _extract_gold(text_lower)
    if gold is not None:
        hints["gold"] = gold

    status = _extract_status(text_lower)
    if status:
        hints["status"] = status

    phase = _extract_phase(text_lower)
    if phase:
        hints["game_phase"] = phase

    lane = _extract_lane(text_lower)
    if lane:
        hints["lane"] = lane

    return hints


def extract_item_hints(text: str) -> dict[str, Any]:
    normalized = _normalize(text)
    prefix_match = _extract_self_prefix_item(normalized)
    if prefix_match:
        return {
            "self_item": {
                "item": prefix_match["item"],
                "status": prefix_match["status"],
            }
        }

    match = _extract_item_match(normalized)
    if not match:
        return {}

    subject = match["subject"]
    verb = match["verb"]
    item = match["item"].strip()
    status = "building" if "fazendo" in verb or "fechando" in verb or "comprando" in verb else "has"

    if _is_self_subject(subject):
        return {
            "self_item": {
                "item": item,
                "status": status,
            }
        }

    return {
        "enemy_item": {
            "champion": subject,
            "item": item,
            "status": status,
        }
    }


def _extract_gold(text: str) -> int | None:
    patterns = [
        r"(\\d{3,5})\\s*(gold|ouro|g)\\b",
        r"tenho\\s*(\\d{3,5})\\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def _extract_status(text: str) -> str | None:
    if "na frente" in text or "vantagem" in text:
        return "ahead"
    if "atras" in text or "desvantagem" in text:
        return "behind"
    if "empatado" in text or "even" in text:
        return "even"
    if "ahead" in text:
        return "ahead"
    if "behind" in text:
        return "behind"
    return None


def _extract_phase(text: str) -> str | None:
    if "early" in text or "inicio" in text or "comeco" in text:
        return "early"
    if "mid" in text or "meio" in text:
        return "mid"
    if "late" in text or "fim" in text:
        return "late"
    return None


def _extract_lane(text: str) -> str | None:
    if "top" in text:
        return "top"
    if "mid" in text or "meio" in text:
        return "mid"
    if "bot" in text or "bottom" in text or "dragao" in text:
        return "bot"
    if "jg" in text or "jungle" in text or "selva" in text:
        return "jungle"
    if "sup" in text or "support" in text:
        return "support"
    return None


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return normalized.lower()


def _extract_item_match(text: str) -> dict[str, str] | None:
    pattern = (
        r"(?P<subject>[a-z]+)\\s+"
        r"(?P<verb>fez|fechei|fechou|comprou|tenho|tem|ta com|to com|estou com|"
        r"ta fazendo|to fazendo|estou fazendo|fazendo|fechando|comprando|buildando|"
        r"has|have|built|building|buying|is building|is buying)\\s+"
        r"(?P<item>.+)$"
    )
    match = re.search(pattern, text)
    if not match:
        return None
    return {
        "subject": match.group("subject").strip(),
        "verb": match.group("verb").strip(),
        "item": match.group("item").strip(),
    }


def _extract_self_prefix_item(text: str) -> dict[str, str] | None:
    prefixes = [
        ("to com ", "has"),
        ("estou com ", "has"),
        ("tenho ", "has"),
        ("i have ", "has"),
        ("im with ", "has"),
        ("i'm with ", "has"),
        ("to fazendo ", "building"),
        ("estou fazendo ", "building"),
        ("im building ", "building"),
        ("i'm building ", "building"),
        ("fazendo ", "building"),
        ("fechando ", "building"),
        ("comprando ", "building"),
        ("building ", "building"),
        ("buying ", "building"),
    ]
    for prefix, status in prefixes:
        if text.startswith(prefix):
            item = text[len(prefix) :].strip()
            if not item or re.search(r"\\b\\d+\\b", item) or "gold" in item or "ouro" in item:
                return None
            return {"item": item, "status": status}
    return None


def _is_self_subject(subject: str) -> bool:
    return subject in {"eu", "meu", "minha", "to", "estou", "i", "my"}
