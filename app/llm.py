from __future__ import annotations

import logging
from typing import Any

from app.config import GEMINI_API_KEY, GEMINI_MODEL, LLM_PROVIDER
from app import game_data
from app import nlu
from app import db

try:
    from google import genai
    from google.genai import types as genai_types
    _genai_available = True
except ImportError:  # pragma: no cover - optional dependency
    genai = None
    genai_types = None
    _genai_available = False

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
    if not GEMINI_API_KEY or not _genai_available:
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
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.5,
                top_p=0.9,
                max_output_tokens=180,
            ),
        )
    except Exception:
        logger.exception("gemini_request_failed")
        return None

    if not response or not response.text:
        return None
    return response.text.strip() or None


def _build_game_data_block(
    champion: str,
    enemy: str,
    lane: str,
    enemies: list[dict[str, Any]] | None = None,
) -> str:
    """Constrói bloco de dados do jogo para o prompt."""
    lines = []

    # Dados do campeão do jogador
    if champion and champion != "unknown":
        champ_info = game_data.get_champion_info(champion)
        if champ_info:
            roles = ", ".join(champ_info.get("roles") or [])
            lanes = ", ".join(champ_info.get("lanes") or [])
            difficulty = champ_info.get("difficulty", 0)

            lines.append(f"Your champion ({champion}):")
            if roles:
                lines.append(f"  - Roles: {roles}")
            if lanes:
                lines.append(f"  - Best lanes: {lanes}")
            if difficulty:
                lines.append(f"  - Difficulty: {difficulty}/10")

        abilities = game_data.get_champion_abilities(champion)
        if abilities:
            lines.append("  - Abilities:")
            for ability in abilities[:4]:
                name = ability.get("name") or ""
                desc = ability.get("description") or ""
                short = desc.replace("\n", " " ).strip()
                if len(short) > 120:
                    short = short[:117].rstrip() + "..."
                if name and short:
                    lines.append(f"    - {name}: {short}")
                elif name:
                    lines.append(f"    - {name}")

        # Winrate do campeão
        champ_wr = game_data.get_champion_winrate(champion, lane if lane != "unknown" else None)
        if champ_wr:
            lines.append(f"  - Win rate ({champ_wr['position']}): {champ_wr['win_rate']:.1f}%")
            tier = champ_wr.get("tier", 5)
            tier_name = {1: "S+", 2: "S", 3: "A", 4: "B", 5: "C"}.get(tier, "?")
            lines.append(f"  - Tier: {tier_name}")

    # Se temos múltiplos inimigos, usar análise de composição
    if enemies and len(enemies) > 1:
        lines.append("\nEnemy team composition:")
        for enemy_data in enemies:
            enemy_name = enemy_data.get("champion", "")
            enemy_status = enemy_data.get("status", "even")
            is_laner = enemy_data.get("is_laner", False)

            enemy_info = game_data.get_champion_info(enemy_name)
            if enemy_info:
                roles = ", ".join(enemy_info.get("roles") or [])
                damage = enemy_info.get("damage", 5)

                status_label = ""
                if enemy_status == "ahead":
                    status_label = " [FED - THREAT]"
                elif enemy_status == "behind":
                    status_label = " [behind]"

                laner_label = " (your lane)" if is_laner else ""
                lines.append(f"  - {enemy_name}{laner_label}{status_label}: {roles}")

        # Análise de composição
        comp_analysis = nlu.analyze_team_composition(enemies)

        # Resumo de dano do time
        phys = comp_analysis.get("damage_physical", 0)
        magic = comp_analysis.get("damage_magic", 0)
        if phys > magic:
            lines.append(f"\nTeam damage: Mostly PHYSICAL ({phys} vs {magic} magic)")
        elif magic > phys:
            lines.append(f"\nTeam damage: Mostly MAGIC ({magic} vs {phys} physical)")
        else:
            lines.append(f"\nTeam damage: Mixed ({phys} physical, {magic} magic)")

        # Características importantes
        traits = []
        if comp_analysis.get("has_healer"):
            traits.append("HAS HEALER (need anti-heal)")
        if comp_analysis.get("has_tank"):
            traits.append("HAS TANK (need armor pen)")
        if comp_analysis.get("has_assassin"):
            traits.append("HAS ASSASSIN (be careful)")
        if traits:
            lines.append(f"Team traits: {', '.join(traits)}")

        # Threats (inimigos fed)
        threats = comp_analysis.get("threats", [])
        if threats:
            threat_names = [t["champion"] for t in threats]
            lines.append(f"Main threats: {', '.join(threat_names)}")

        # Recomendações de itens baseadas na composição
        recommended = comp_analysis.get("recommended_defenses", [])
        if recommended:
            suggested_items = []
            if "anti_heal" in recommended:
                anti_heal = game_data.get_counter_items(needs_anti_heal=True)
                if anti_heal:
                    suggested_items.append(f"Anti-heal: {anti_heal[0]['name']}")
            if "armor_pen" in recommended:
                armor_pen = game_data.get_counter_items(needs_armor_pen=True)
                if armor_pen:
                    suggested_items.append(f"Armor pen: {armor_pen[0]['name']}")
            if "magic_resist" in recommended:
                mr_items = game_data.get_counter_items(needs_magic_resist=True)
                if mr_items:
                    suggested_items.append(f"Magic resist: {mr_items[0]['name']}")
            if "armor" in recommended:
                armor_items = game_data.get_counter_items(needs_armor=True)
                if armor_items:
                    suggested_items.append(f"Armor: {armor_items[0]['name']}")

            if suggested_items:
                lines.append("\nRecommended items for this game:")
                for item in suggested_items[:4]:
                    lines.append(f"  - {item}")

    # Fallback: inimigo único (laning phase)
    elif enemy and enemy != "unknown":
        enemy_info = game_data.get_champion_info(enemy)
        if enemy_info:
            roles = ", ".join(enemy_info.get("roles") or [])
            damage = enemy_info.get("damage", 0)

            lines.append(f"\nLane opponent ({enemy}):")
            if roles:
                lines.append(f"  - Roles: {roles}")
            if damage:
                damage_type = "high damage" if damage >= 7 else "moderate damage" if damage >= 4 else "low damage"
                lines.append(f"  - Threat: {damage_type}")

        enemy_abilities = game_data.get_champion_abilities(enemy)
        if enemy_abilities:
            lines.append("  - Enemy abilities:")
            for ability in enemy_abilities[:4]:
                name = ability.get("name") or ""
                desc = ability.get("description") or ""
                short = desc.replace("\n", " " ).strip()
                if len(short) > 120:
                    short = short[:117].rstrip() + "..."
                if name and short:
                    lines.append(f"    - {name}: {short}")
                elif name:
                    lines.append(f"    - {name}")

        # Winrate do inimigo
        enemy_wr = game_data.get_champion_winrate(enemy, lane if lane != "unknown" else None)
        if enemy_wr:
            lines.append(f"  - Win rate: {enemy_wr['win_rate']:.1f}%")

        # Dicas de matchup
        if champion and champion != "unknown":
            tips = game_data.get_matchup_tips(champion, enemy, lane if lane != "unknown" else None)
            if tips:
                lines.append("Matchup tips:")
                for tip in (tips.get("tips") or [])[:2]:
                    lines.append(f"  - {tip}")
                if tips.get("counter_items"):
                    items = ", ".join(tips["counter_items"][:3])
                    lines.append(f"  - Counter items: {items}")

        # Sugestões de itens baseadas no inimigo único
        if enemy_info:
            enemy_roles = enemy_info.get("roles") or []
            survivability = enemy_info.get("survivability", 0)

            suggested_items = []
            if any(r in enemy_roles for r in ["fighter"]) or survivability >= 5:
                anti_heal = game_data.get_counter_items(needs_anti_heal=True)
                if anti_heal:
                    suggested_items.append(f"Anti-heal: {anti_heal[0]['name']}")
            if survivability >= 6:
                armor_pen = game_data.get_counter_items(needs_armor_pen=True)
                if armor_pen:
                    suggested_items.append(f"Armor pen: {armor_pen[0]['name']}")
            if "mage" in enemy_roles:
                mr_items = game_data.get_counter_items(needs_magic_resist=True)
                if mr_items:
                    suggested_items.append(f"Magic resist: {mr_items[0]['name']}")

            if suggested_items:
                lines.append("Suggested counter items:")
                for item in suggested_items[:3]:
                    lines.append(f"  - {item}")

    return "\n".join(lines) if lines else "No game data available"


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
    enemies = state.get("enemies") or []  # Lista de múltiplos inimigos
    phase = state.get("game_phase") or "unknown"
    status = state.get("status") or "unknown"
    gold = state.get("gold")
    last_reply = state.get("last_reply") or ""

    # Busca correções aprendidas do banco
    relevant_champions = []
    if champion and champion != "unknown":
        relevant_champions.append(champion)
    if enemy and enemy != "unknown":
        relevant_champions.append(enemy)
    for e in enemies:
        if e.get("champion"):
            relevant_champions.append(e["champion"])

    corrections = db.retrieve_corrections(
        champions=relevant_champions if relevant_champions else None,
        limit=5,
    )

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

    # Monta bloco de correções aprendidas
    corrections_lines = []
    for corr in corrections:
        champ = corr.get("champion") or "general"
        ability = corr.get("ability")
        wrong = corr.get("wrong_info", "")
        correct = corr.get("correct_info", "")
        conf = corr.get("confidence", 1)

        if ability:
            corrections_lines.append(
                f"- {champ} ({ability}): NOT \"{wrong}\" → CORRECT: \"{correct}\" [conf:{conf}]"
            )
        else:
            corrections_lines.append(
                f"- {champ}: NOT \"{wrong}\" → CORRECT: \"{correct}\" [conf:{conf}]"
            )
    corrections_block = "\n".join(corrections_lines) if corrections_lines else "none"

    # Busca dados do jogo (com suporte a múltiplos inimigos)
    game_data_block = _build_game_data_block(champion, enemy, lane, enemies)

    # Formata lista de inimigos para contexto
    if enemies and len(enemies) > 1:
        enemies_str = ", ".join(
            f"{e['champion']}{'(fed)' if e.get('status')=='ahead' else ''}"
            for e in enemies
        )
    else:
        enemies_str = enemy

    return (
        "You are NexusCoach, an in-game Wild Rift MOBILE voice coach. "
        "Be short, tactical, friendly and PRACTICAL. "
        "Use the game data below to give accurate advice. "
        "Consider the FULL enemy team composition when giving item/strategy advice. "
        "\n"
        "IMPORTANT RULES:\n"
        "- This is MOBILE Wild Rift, NOT PC League of Legends.\n"
        "- If ability data is available in Game Data, it is the source of truth.\n"
        "- If ability data is missing, do NOT invent ability mechanics.\n"
        "- NEVER use keyboard keys like Q, W, E, R to refer to abilities.\n"
        "- Instead, describe abilities by their VISUAL EFFECT or NAME.\n"
        "  Examples: 'his shadow clone', 'the spinning slash', 'the hook', 'her charm', 'the dash'.\n"
        "- When giving tips, explain HOW to do it, not just WHAT to do.\n"
        "  Bad: 'Bait his combo then punish'\n"
        "  Good: 'Stay behind minions - when he throws his shadow at you, sidestep and attack while it recharges'\n"
        "- Be specific about timing, positioning, or visual cues when possible.\n"
        "- If context is missing, ask one short question.\n"
        "- Keep answers under 3 sentences.\n"
        f"{language_line}\n\n"
        "Context:\n"
        f"- Champion: {champion}\n"
        f"- Lane: {lane}\n"
        f"- Enemies: {enemies_str}\n"
        f"- Phase: {phase}\n"
        f"- Status: {status}\n"
        f"- Gold: {gold if gold is not None else 'unknown'}\n"
        f"- Your items: {self_items}\n"
        f"- Enemy items: {enemy_items}\n"
        f"- Intent hint: {intent}\n"
        f"- Last coach tip: {last_reply or 'none'}\n\n"
        "Game Data (from Wild Rift stats):\n"
        f"{game_data_block}\n\n"
        "Useful tips from memory:\n"
        f"{advice_block}\n\n"
        "LEARNED CORRECTIONS (from user feedback - ALWAYS respect these):\n"
        f"{corrections_block}\n\n"
        "Recent conversation:\n"
        f"{history_block}\n\n"
        "User message:\n"
        f"{user_text}\n"
    )
