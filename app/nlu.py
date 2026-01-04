from __future__ import annotations

import re
import unicodedata
from typing import Any


INTENTS = {
    "build": ["item", "build", "proximo", "prox", "comprar", "next", "buy"],
    "all_in": ["all-in", "all in", "allin"],
    "objective": ["dragao", "arauto", "baron", "objetivo", "dragon", "herald", "objective"],
    "status": ["na frente", "atras", "empatado", "even", "ahead", "behind"],
    "macro": ["macro", "split", "agrupo", "group", "teamfight", "tf", "team fight"],
    "follow_up": ["e agora", "agora o que", "continuo", "seguinte", "what now", "and now"],
    "matchup": ["contra", "versus", "vs", "matchup", "enfrentando", "against"],
}

# Lista de campeões conhecidos do Wild Rift (nomes em inglês, minúsculos)
KNOWN_CHAMPIONS = {
    # Fighters
    "darius", "garen", "fiora", "camille", "jax", "irelia", "riven", "renekton",
    "sett", "wukong", "xin zhao", "jarvan", "lee sin", "vi", "olaf", "tryndamere",
    "yasuo", "yone", "pantheon", "jayce", "kayn", "aatrox", "warwick", "volibear",
    "hecarim", "nocturne", "shyvana", "mundo", "nasus", "yorick", "gwen", "urgot",
    # Tanks
    "malphite", "ornn", "sion", "maokai", "nautilus", "leona", "alistar", "braum",
    "thresh", "blitzcrank", "amumu", "rammus", "gragas", "sejuani", "zac", "shen",
    "poppy", "singed", "tahm kench", "rell",
    # Assassins
    "zed", "talon", "akali", "katarina", "fizz", "ekko", "diana", "kassadin",
    "khazix", "rengar", "evelynn", "pyke", "qiyana", "leblanc", "ahri",
    # Mages
    "lux", "ahri", "orianna", "syndra", "veigar", "brand", "zyra", "annie",
    "malzahar", "viktor", "xerath", "ziggs", "velkoz", "twisted fate", "ryze",
    "cassiopeia", "aurelion sol", "seraphine", "karma", "morgana", "lulu",
    "nami", "soraka", "sona", "janna", "yuumi", "vex", "zoe", "neeko", "hwei",
    # Marksmen (ADC)
    "jinx", "caitlyn", "vayne", "kaisa", "ezreal", "lucian", "draven", "ashe",
    "miss fortune", "tristana", "twitch", "jhin", "xayah", "varus", "corki",
    "kogmaw", "sivir", "kalista", "samira", "aphelios", "zeri", "nilah", "smolder",
    # Supports
    "thresh", "lulu", "nami", "soraka", "sona", "janna", "yuumi", "braum",
    "leona", "nautilus", "alistar", "blitzcrank", "rakan", "pyke", "senna",
    "seraphine", "karma", "morgana", "zyra", "brand", "lux", "xerath",
}

# Variações de nomes (aliases)
CHAMPION_ALIASES = {
    "mf": "miss fortune",
    "tf": "twisted fate",
    "asol": "aurelion sol",
    "tk": "tahm kench",
    "j4": "jarvan",
    "jarvan iv": "jarvan",
    "lee": "lee sin",
    "xin": "xin zhao",
    "kha": "khazix",
    "kha'zix": "khazix",
    "kog": "kogmaw",
    "kog'maw": "kogmaw",
    "vel": "velkoz",
    "vel'koz": "velkoz",
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

    # Extrai campeões mencionados
    champions_data = extract_champions(text)
    if champions_data.get("player_champion"):
        hints["champion"] = champions_data["player_champion"]
    if champions_data.get("enemies"):
        hints["enemies"] = champions_data["enemies"]
        # Mantém compatibilidade com "enemy" singular (primeiro da lista ou laner)
        laner = next((e for e in champions_data["enemies"] if e.get("is_laner")), None)
        if laner:
            hints["enemy"] = laner["champion"]
        elif champions_data["enemies"]:
            hints["enemy"] = champions_data["enemies"][0]["champion"]

    return hints


def extract_champions(text: str) -> dict[str, Any]:
    """
    Extrai campeões mencionados no texto.
    Retorna dict com:
    - player_champion: campeão do jogador (se identificado)
    - enemies: lista de inimigos com status
    """
    text_lower = _normalize(text)
    result: dict[str, Any] = {
        "player_champion": None,
        "enemies": [],
    }

    # Encontra todos os campeões mencionados
    found_champions = _find_all_champions(text_lower)
    if not found_champions:
        return result

    # Padrões para identificar o campeão do jogador
    player_patterns = [
        r"(?:estou|to|sou|jogo|jogando|vou)\s+(?:de|com)\s+(\w+)",
        r"(?:meu|minha)\s+(\w+)",
        r"(\w+)\s+(?:aqui|main|otp)",
        r"(?:i am|i'm|im|playing)\s+(\w+)",
    ]

    for pattern in player_patterns:
        match = re.search(pattern, text_lower)
        if match:
            potential = match.group(1)
            champion = _resolve_champion(potential)
            if champion and champion in found_champions:
                result["player_champion"] = champion
                found_champions.remove(champion)
                break

    # Padrões para identificar inimigos e seus status
    enemy_patterns = [
        # "contra um jax no top"
        (r"contra\s+(?:um|uma|o|a)?\s*(\w+)", "laner"),
        # "tem uma caitlyn forte"
        (r"(?:tem|ha|existe)\s+(?:um|uma|o|a)?\s*(\w+)\s+(?:forte|fed|feedado)", "fed"),
        # "caitlyn e nami fortes"
        (r"(\w+)\s+(?:e|and)\s+(\w+)\s+(?:fortes|feds|feedados|strong)", "fed_pair"),
        # "malzahar também está forte"
        (r"(\w+)\s+(?:tambem|also)\s+(?:esta|está|is|ta)\s+(?:forte|fed)", "fed"),
        # "caitlyn está forte"
        (r"(\w+)\s+(?:esta|está|is|ta)\s+(?:forte|fed|feedado|strong|ahead)", "fed"),
        # "jax fraco/behind"
        (r"(\w+)\s+(?:esta|está|is|ta)\s+(?:fraco|weak|behind|atras)", "behind"),
        # "amassei o jax"
        (r"(?:amassei|ganhei|venci|matei|destrui)\s+(?:o|a|do|da)?\s*(\w+)", "behind"),
    ]

    enemies_with_status: list[dict[str, Any]] = []
    processed_enemies: set[str] = set()

    for pattern, status_type in enemy_patterns:
        for match in re.finditer(pattern, text_lower):
            if status_type == "fed_pair":
                # Captura par de campeões
                for group_idx in [1, 2]:
                    potential = match.group(group_idx)
                    champion = _resolve_champion(potential)
                    if champion and champion not in processed_enemies and champion != result["player_champion"]:
                        enemies_with_status.append({
                            "champion": champion,
                            "status": "ahead",
                            "is_laner": False,
                        })
                        processed_enemies.add(champion)
            else:
                potential = match.group(1)
                champion = _resolve_champion(potential)
                if champion and champion not in processed_enemies and champion != result["player_champion"]:
                    status = "even"
                    is_laner = False
                    if status_type == "laner":
                        is_laner = True
                        status = "even"
                    elif status_type == "fed":
                        status = "ahead"
                    elif status_type == "behind":
                        status = "behind"

                    enemies_with_status.append({
                        "champion": champion,
                        "status": status,
                        "is_laner": is_laner,
                    })
                    processed_enemies.add(champion)

    # Adiciona campeões restantes que foram encontrados mas não processados
    for champion in found_champions:
        if champion not in processed_enemies and champion != result["player_champion"]:
            enemies_with_status.append({
                "champion": champion,
                "status": "even",
                "is_laner": False,
            })

    result["enemies"] = enemies_with_status
    return result


def _find_all_champions(text: str) -> list[str]:
    """Encontra todos os campeões mencionados no texto."""
    found = []
    text_words = set(text.split())

    # Verifica aliases primeiro
    for alias, champion in CHAMPION_ALIASES.items():
        if alias in text or alias in text_words:
            if champion not in found:
                found.append(champion)

    # Verifica campeões conhecidos (nomes completos primeiro, depois palavras únicas)
    # Ordena por tamanho decrescente para pegar "miss fortune" antes de "miss"
    sorted_champions = sorted(KNOWN_CHAMPIONS, key=len, reverse=True)
    for champion in sorted_champions:
        if champion in text and champion not in found:
            found.append(champion)

    return found


def _resolve_champion(name: str) -> str | None:
    """Resolve um nome para o nome canônico do campeão."""
    name_lower = name.lower().strip()

    # Verifica alias
    if name_lower in CHAMPION_ALIASES:
        return CHAMPION_ALIASES[name_lower]

    # Verifica nome direto
    if name_lower in KNOWN_CHAMPIONS:
        return name_lower

    # Verifica se é parte de um nome composto
    for champion in KNOWN_CHAMPIONS:
        if champion.startswith(name_lower) or name_lower in champion.split():
            return champion

    return None


def analyze_team_composition(enemies: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Analisa a composição do time inimigo.
    Retorna análise com tipos de dano, ameaças principais, etc.
    """
    from app import game_data

    analysis = {
        "damage_physical": 0,
        "damage_magic": 0,
        "has_healer": False,
        "has_tank": False,
        "has_assassin": False,
        "threats": [],  # Inimigos fed
        "total_survivability": 0,
        "recommended_defenses": [],
    }

    for enemy in enemies:
        champion_name = enemy.get("champion", "")
        status = enemy.get("status", "even")

        # Busca info do campeão
        info = game_data.get_champion_info(champion_name)
        if not info:
            continue

        roles = info.get("roles") or []
        damage = info.get("damage", 5)
        survivability = info.get("survivability", 5)

        # Contabiliza tipo de dano
        if any(r in roles for r in ["marksman", "fighter"]):
            analysis["damage_physical"] += damage
        if any(r in roles for r in ["mage", "assassin"]):
            analysis["damage_magic"] += damage

        # Identifica características
        if "support" in roles:
            # Verifica se é healer
            if champion_name.lower() in {"nami", "soraka", "sona", "yuumi", "senna", "seraphine"}:
                analysis["has_healer"] = True
        if "tank" in roles or survivability >= 7:
            analysis["has_tank"] = True
        if "assassin" in roles:
            analysis["has_assassin"] = True

        analysis["total_survivability"] += survivability

        # Marca como threat se está fed
        if status == "ahead":
            analysis["threats"].append({
                "champion": champion_name,
                "roles": roles,
                "damage_type": "magic" if "mage" in roles else "physical",
            })

    # Recomendações de defesa
    if analysis["damage_magic"] > analysis["damage_physical"]:
        analysis["recommended_defenses"].append("magic_resist")
    elif analysis["damage_physical"] > analysis["damage_magic"]:
        analysis["recommended_defenses"].append("armor")
    else:
        analysis["recommended_defenses"].extend(["armor", "magic_resist"])

    if analysis["has_healer"]:
        analysis["recommended_defenses"].append("anti_heal")

    if analysis["has_tank"]:
        analysis["recommended_defenses"].append("armor_pen")

    return analysis


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
