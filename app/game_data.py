"""
Módulo para sincronização de dados de Wild Rift.
Fontes:
- API Tencent China: Campeões e Winrates
- wr-database: Stats base dos campeões
- wr-meta.com: Itens (via scraping)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import psycopg
from urllib.request import urlopen, Request

from app.config import POSTGRES_DSN

logger = logging.getLogger("nexuscoach")

# URLs das APIs
TENCENT_HERO_LIST = "https://game.gtimg.cn/images/lgamem/act/lrlib/js/heroList/hero_list.js"
TENCENT_WINRATES = "https://mlol.qt.qq.com/go/lgame_battle_info/hero_rank_list_v2"
WR_DATABASE_CHAMPIONS = "https://wr-database.vercel.app/api/champions"
WR_DATABASE_CHAMPION_DETAIL = "https://wr-database.vercel.app/api/champions/{}"
WR_META_ITEMS = "https://wr-meta.com/items/"
TENCENT_HERO_DETAIL_CANDIDATES = [
    "https://game.gtimg.cn/images/lgamem/act/lrlib/js/hero/{}.js",
    "https://game.gtimg.cn/images/lgamem/act/lrlib/js/hero/hero_{}.js",
    "https://game.gtimg.cn/images/lol/act/img/js/hero/{}.js",
]

# Mapeamento de roles chinês -> português
ROLE_MAP = {
    "战士": "fighter",
    "法师": "mage",
    "刺客": "assassin",
    "坦克": "tank",
    "射手": "marksman",
    "辅助": "support",
}

# Mapeamento de lanes chinês -> inglês
LANE_MAP = {
    "单人路": "baron",
    "中路": "mid",
    "打野": "jungle",
    "射手": "duo",
    "辅助": "support",
}

# Mapeamento de posição (API winrates) -> lane
POSITION_MAP = {
    "1": "mid",
    "2": "baron",
    "3": "jungle",
    "4": "duo",
    "5": "support",
}


def _fetch_json(url: str) -> Any:
    """Busca JSON de uma URL."""
    req = Request(url, headers={"User-Agent": "NexusCoach/1.0"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "NexusCoach/1.0"})
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8")


def _fetch_json_loose(url: str) -> Any | None:
    try:
        return _fetch_json(url)
    except Exception:
        pass
    try:
        text = _fetch_text(url)
    except Exception:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def _ensure_game_tables(conn: psycopg.Connection) -> None:
    """Cria tabelas para dados do jogo."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS champions (
            hero_id TEXT PRIMARY KEY,
            name_cn TEXT,
            name_en TEXT,
            title TEXT,
            alias TEXT,
            roles TEXT[],
            lanes TEXT[],
            difficulty INT,
            damage INT,
            survivability INT,
            utility INT,
            icon_url TEXT,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS champion_stats (
            hero_id TEXT PRIMARY KEY REFERENCES champions(hero_id),
            health_base NUMERIC,
            health_scale NUMERIC,
            mana_base NUMERIC,
            mana_scale NUMERIC,
            armor_base NUMERIC,
            armor_scale NUMERIC,
            magic_resist_base NUMERIC,
            magic_resist_scale NUMERIC,
            attack_base NUMERIC,
            attack_scale NUMERIC,
            attack_speed_base NUMERIC,
            attack_speed_scale NUMERIC,
            move_speed INT,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS champion_abilities (
            id BIGSERIAL PRIMARY KEY,
            hero_id TEXT REFERENCES champions(hero_id),
            champion_name TEXT,
            ability_key TEXT,
            ability_name TEXT,
            description TEXT,
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(hero_id, ability_key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS champion_winrates (
            id BIGSERIAL PRIMARY KEY,
            hero_id TEXT REFERENCES champions(hero_id),
            position TEXT,
            win_rate NUMERIC,
            pick_rate NUMERIC,
            ban_rate NUMERIC,
            strength_tier INT,
            stat_date DATE,
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(hero_id, position, stat_date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matchup_tips (
            id BIGSERIAL PRIMARY KEY,
            champion TEXT NOT NULL,
            enemy TEXT NOT NULL,
            lane TEXT,
            difficulty INT,
            tips TEXT[],
            counter_items TEXT[],
            power_spikes TEXT[],
            positive_count INT DEFAULT 0,
            negative_count INT DEFAULT 0,
            score INT DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(champion, enemy, lane)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            item_id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            name_normalized TEXT,
            category TEXT,
            gold_cost INT,
            stats JSONB,
            passive_name TEXT,
            passive_desc TEXT,
            tags TEXT[],
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    conn.commit()


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).replace("&nbsp;", " ").strip()


def _extract_abilities(champ: dict[str, Any]) -> list[dict[str, str]]:
    abilities: list[dict[str, str]] = []

    passive = champ.get("passive")
    if isinstance(passive, dict):
        name = passive.get("name") or passive.get("abilityName") or ""
        desc = (
            passive.get("description")
            or passive.get("tooltip")
            or passive.get("desc")
            or ""
        )
        if name or desc:
            abilities.append(
                {
                    "key": "passive",
                    "name": _strip_html(name),
                    "description": _strip_html(desc),
                }
            )
    else:
        name = champ.get("passiveName") or champ.get("passive_name") or ""
        desc = champ.get("passiveDesc") or champ.get("passive_description") or ""
        if name or desc:
            abilities.append(
                {
                    "key": "passive",
                    "name": _strip_html(name),
                    "description": _strip_html(desc),
                }
            )

    spells = champ.get("spells") or champ.get("abilities") or champ.get("skills")
    if isinstance(spells, dict):
        spells = spells.get("spells") or spells.get("skills") or spells.get("abilities")
    if isinstance(spells, list):
        keys = ["q", "w", "e", "r"]
        for idx, spell in enumerate(spells):
            if not isinstance(spell, dict):
                continue
            key = keys[idx] if idx < len(keys) else f"skill_{idx + 1}"
            name = (
                spell.get("name")
                or spell.get("abilityName")
                or spell.get("spellName")
                or ""
            )
            desc = (
                spell.get("description")
                or spell.get("tooltip")
                or spell.get("desc")
                or spell.get("spellDesc")
                or ""
            )
            if name or desc:
                abilities.append(
                    {
                        "key": key,
                        "name": _strip_html(name),
                        "description": _strip_html(desc),
                    }
                )

    return abilities


def _find_abilities_root(node: Any) -> dict[str, Any] | None:
    if isinstance(node, dict):
        for key in (
            "spells",
            "skills",
            "abilities",
            "passive",
            "passiveName",
            "passiveDesc",
        ):
            if key in node:
                return node
        for value in node.values():
            found = _find_abilities_root(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_abilities_root(item)
            if found:
                return found
    return None


def _unwrap_champion_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    for key in ("champion", "champion_data", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def _fetch_champion_detail(champ: dict[str, Any]) -> dict[str, Any] | None:
    identifiers: list[str] = []
    slug = champ.get("id") or champ.get("slug") or champ.get("alias")
    if isinstance(slug, str) and slug:
        identifiers.append(slug)
    hero_id = champ.get("heroId") or champ.get("hero_id")
    if hero_id:
        identifiers.append(str(hero_id))

    for identifier in identifiers:
        try:
            payload = _fetch_json(WR_DATABASE_CHAMPION_DETAIL.format(identifier))
        except Exception:
            continue
        detail = _unwrap_champion_payload(payload)
        if detail:
            return detail

    return None


def _fetch_tencent_hero_detail(hero_id: str) -> dict[str, Any] | None:
    for template in TENCENT_HERO_DETAIL_CANDIDATES:
        url = template.format(hero_id)
        payload = _fetch_json_loose(url)
        if isinstance(payload, dict):
            return payload
    return None


def sync_champions_from_tencent() -> dict[str, str]:
    """
    Sincroniza lista de campeões da API Tencent.
    Retorna mapeamento hero_id -> name_en.
    """
    if not POSTGRES_DSN:
        logger.warning("POSTGRES_DSN not configured, skipping sync")
        return {}

    logger.info("Fetching champions from Tencent API...")
    data = _fetch_json(TENCENT_HERO_LIST)
    hero_list = data.get("heroList", {})

    hero_map = {}

    with psycopg.connect(POSTGRES_DSN) as conn:
        _ensure_game_tables(conn)

        for hero_id, hero in hero_list.items():
            # Parse roles
            roles_cn = hero.get("roles", [])
            roles = [ROLE_MAP.get(r, r.lower()) for r in roles_cn]

            # Parse lanes
            lanes_str = hero.get("lane", "")
            lanes_cn = [l.strip() for l in lanes_str.split(";") if l.strip()]
            lanes = [LANE_MAP.get(l, l.lower()) for l in lanes_cn]

            # Alias como nome em inglês (romanizado)
            alias = hero.get("alias", "")
            name_en = alias.replace("·", " ").title() if alias else ""

            hero_map[hero_id] = name_en or hero.get("name", "")

            conn.execute(
                """
                INSERT INTO champions (
                    hero_id, name_cn, name_en, title, alias, roles, lanes,
                    difficulty, damage, survivability, utility, icon_url
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (hero_id) DO UPDATE SET
                    name_cn = EXCLUDED.name_cn,
                    name_en = EXCLUDED.name_en,
                    title = EXCLUDED.title,
                    alias = EXCLUDED.alias,
                    roles = EXCLUDED.roles,
                    lanes = EXCLUDED.lanes,
                    difficulty = EXCLUDED.difficulty,
                    damage = EXCLUDED.damage,
                    survivability = EXCLUDED.survivability,
                    utility = EXCLUDED.utility,
                    icon_url = EXCLUDED.icon_url,
                    updated_at = NOW()
                """,
                (
                    hero_id,
                    hero.get("name"),
                    name_en,
                    hero.get("title"),
                    alias,
                    roles,
                    lanes,
                    int(hero.get("difficultyL", 0)),
                    int(hero.get("damage", 0)),
                    int(hero.get("surviveL", 0)),
                    int(hero.get("assistL", 0)),
                    hero.get("avatar"),
                ),
            )

        conn.commit()
        logger.info(f"Synced {len(hero_list)} champions from Tencent")

    return hero_map


def sync_champion_stats() -> int:
    """
    Sincroniza stats base dos campeões do wr-database.
    Retorna quantidade de campeões atualizados.
    """
    if not POSTGRES_DSN:
        return 0

    logger.info("Fetching champion stats from wr-database...")
    data = _fetch_json(WR_DATABASE_CHAMPIONS)
    champions = data.get("champions_data", [])

    count = 0
    with psycopg.connect(POSTGRES_DSN) as conn:
        _ensure_game_tables(conn)

        for champ in champions:
            hero_id = champ.get("heroId")
            if not hero_id or hero_id == 10666:  # placeholder
                continue

            hero_id_str = str(hero_id)

            # Verifica se o campeão existe na tabela champions
            exists = conn.execute(
                "SELECT 1 FROM champions WHERE hero_id = %s", (hero_id_str,)
            ).fetchone()

            if not exists:
                # Insere campeão básico se não existir
                conn.execute(
                    """
                    INSERT INTO champions (hero_id, name_en, alias)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (hero_id) DO NOTHING
                    """,
                    (hero_id_str, champ.get("name", ""), champ.get("id", "")),
                )

            mana_base = champ.get("manaBase")
            if mana_base is False:
                mana_base = None

            conn.execute(
                """
                INSERT INTO champion_stats (
                    hero_id, health_base, health_scale, mana_base, mana_scale,
                    armor_base, armor_scale, magic_resist_base, magic_resist_scale,
                    attack_base, attack_scale, attack_speed_base, attack_speed_scale,
                    move_speed
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (hero_id) DO UPDATE SET
                    health_base = EXCLUDED.health_base,
                    health_scale = EXCLUDED.health_scale,
                    mana_base = EXCLUDED.mana_base,
                    mana_scale = EXCLUDED.mana_scale,
                    armor_base = EXCLUDED.armor_base,
                    armor_scale = EXCLUDED.armor_scale,
                    magic_resist_base = EXCLUDED.magic_resist_base,
                    magic_resist_scale = EXCLUDED.magic_resist_scale,
                    attack_base = EXCLUDED.attack_base,
                    attack_scale = EXCLUDED.attack_scale,
                    attack_speed_base = EXCLUDED.attack_speed_base,
                    attack_speed_scale = EXCLUDED.attack_speed_scale,
                    move_speed = EXCLUDED.move_speed,
                    updated_at = NOW()
                """,
                (
                    hero_id_str,
                    champ.get("healthBase"),
                    champ.get("healthScale"),
                    mana_base,
                    champ.get("manaScale"),
                    champ.get("armorBase"),
                    champ.get("armorScale"),
                    champ.get("magresBase"),
                    champ.get("magresScale"),
                    champ.get("attackBase"),
                    champ.get("attackScale"),
                    champ.get("asBase"),
                    champ.get("asScale"),
                    champ.get("moveSpeed"),
                ),
            )
            count += 1

        conn.commit()
        logger.info(f"Synced stats for {count} champions")

    return count


def sync_champion_abilities() -> int:
    """
    Sync abilities from the most up-to-date champion dataset.
    """
    if not POSTGRES_DSN:
        return 0

    logger.info("Fetching champion abilities from wr-database...")
    data = _fetch_json(WR_DATABASE_CHAMPIONS)
    champions = data.get("champions_data", [])

    count = 0
    with psycopg.connect(POSTGRES_DSN) as conn:
        _ensure_game_tables(conn)

        for champ in champions:
            hero_id = champ.get("heroId")
            if not hero_id or hero_id == 10666:
                continue

            hero_id_str = str(hero_id)
            champ_name = champ.get("name") or champ.get("id") or ""
            detail = _fetch_champion_detail(champ)
            source = detail or champ
            if detail:
                champ_name = (
                    detail.get("name")
                    or detail.get("id")
                    or detail.get("slug")
                    or champ_name
                )
            abilities = _extract_abilities(source)
            if not abilities:
                tencent_detail = _fetch_tencent_hero_detail(hero_id_str)
                if tencent_detail:
                    root = _find_abilities_root(tencent_detail) or tencent_detail
                    abilities = _extract_abilities(root)
            if not abilities:
                continue

            conn.execute(
                "DELETE FROM champion_abilities WHERE hero_id = %s",
                (hero_id_str,),
            )
            for ability in abilities:
                conn.execute(
                    """
                    INSERT INTO champion_abilities
                        (hero_id, champion_name, ability_key, ability_name, description)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (hero_id, ability_key) DO UPDATE SET
                        champion_name = EXCLUDED.champion_name,
                        ability_name = EXCLUDED.ability_name,
                        description = EXCLUDED.description,
                        updated_at = NOW()
                    """,
                    (
                        hero_id_str,
                        champ_name,
                        ability["key"],
                        ability["name"],
                        ability["description"],
                    ),
                )
                count += 1

        conn.commit()
        logger.info("Synced %s champion abilities", count)

    return count


def sync_winrates() -> int:
    """
    Sincroniza winrates da API Tencent.
    Retorna quantidade de registros inseridos.
    """
    if not POSTGRES_DSN:
        return 0

    logger.info("Fetching winrates from Tencent API...")
    data = _fetch_json(TENCENT_WINRATES)

    if data.get("result") != 0:
        logger.error("Failed to fetch winrates: %s", data)
        return 0

    positions_data = data.get("data", {}).get("0", {})
    count = 0

    with psycopg.connect(POSTGRES_DSN) as conn:
        _ensure_game_tables(conn)

        for pos_key, heroes in positions_data.items():
            position = POSITION_MAP.get(pos_key, pos_key)

            for hero in heroes:
                hero_id = hero.get("hero_id")
                if not hero_id:
                    continue

                # Parse date
                date_str = hero.get("dtstatdate", "")
                if len(date_str) == 8:
                    stat_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                else:
                    stat_date = None

                conn.execute(
                    """
                    INSERT INTO champion_winrates (
                        hero_id, position, win_rate, pick_rate, ban_rate,
                        strength_tier, stat_date
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (hero_id, position, stat_date) DO UPDATE SET
                        win_rate = EXCLUDED.win_rate,
                        pick_rate = EXCLUDED.pick_rate,
                        ban_rate = EXCLUDED.ban_rate,
                        strength_tier = EXCLUDED.strength_tier,
                        updated_at = NOW()
                    """,
                    (
                        hero_id,
                        position,
                        float(hero.get("win_rate", 0)),
                        float(hero.get("appear_rate", 0)),
                        float(hero.get("forbid_rate", 0)),
                        int(hero.get("strength_level", 5)),
                        stat_date,
                    ),
                )
                count += 1

        conn.commit()
        logger.info(f"Synced {count} winrate records")

    return count


def _fetch_html(url: str) -> str:
    """Busca HTML de uma URL."""
    req = Request(url, headers={"User-Agent": "NexusCoach/1.0"})
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8")


def _parse_item_stats(stats_text: str) -> dict[str, Any]:
    """Parseia texto de stats de item para dict."""
    stats = {}
    # Padrões comuns: +55 AD, +250 HP, +25% Crit, etc.
    patterns = [
        (r"\+(\d+)\s*AD", "attack_damage"),
        (r"\+(\d+)\s*AP", "ability_power"),
        (r"\+(\d+)\s*HP", "health"),
        (r"\+(\d+)\s*Mana", "mana"),
        (r"\+(\d+)\s*Armor", "armor"),
        (r"\+(\d+)\s*MR", "magic_resist"),
        (r"\+(\d+)%?\s*AS", "attack_speed"),
        (r"\+(\d+)%?\s*Crit", "crit_chance"),
        (r"\+(\d+)\s*Haste", "ability_haste"),
        (r"\+(\d+)%?\s*MPen", "magic_pen"),
        (r"\+(\d+)%?\s*Omnivamp", "omnivamp"),
        (r"\+(\d+)%?\s*HSS", "heal_shield_power"),
    ]
    for pattern, key in patterns:
        match = re.search(pattern, stats_text, re.IGNORECASE)
        if match:
            stats[key] = int(match.group(1))
    return stats


def _categorize_item(name: str, stats: dict, passive: str) -> tuple[str, list[str]]:
    """Determina categoria e tags de um item."""
    tags = []
    category = "general"

    # Determinar categoria principal
    if stats.get("attack_damage"):
        category = "physical"
        tags.append("ad")
    elif stats.get("ability_power"):
        category = "magic"
        tags.append("ap")
    elif stats.get("armor") or stats.get("magic_resist") or stats.get("health", 0) > 300:
        category = "defense"
        tags.append("tank")

    # Tags adicionais baseadas em stats
    if stats.get("crit_chance"):
        tags.append("crit")
    if stats.get("attack_speed"):
        tags.append("attack_speed")
    if stats.get("ability_haste"):
        tags.append("cdr")
    if stats.get("mana"):
        tags.append("mana")
    if stats.get("omnivamp") or "vamp" in passive.lower():
        tags.append("sustain")

    # Tags baseadas em passiva
    passive_lower = passive.lower()
    if "grievous" in passive_lower or "anti-heal" in passive_lower:
        tags.append("anti_heal")
    if "armor pen" in passive_lower or "penetration" in passive_lower:
        tags.append("armor_pen")
    if "shield" in passive_lower:
        tags.append("shield")
    if "slow" in passive_lower:
        tags.append("slow")
    if "execute" in passive_lower:
        tags.append("execute")

    return category, tags


def sync_items_from_wrmeta() -> int:
    """
    Sincroniza itens do wr-meta.com via scraping.
    Retorna quantidade de itens sincronizados.
    """
    if not POSTGRES_DSN:
        logger.warning("POSTGRES_DSN not configured, skipping items sync")
        return 0

    logger.info("Fetching items from wr-meta.com...")

    try:
        html = _fetch_html(WR_META_ITEMS)
    except Exception:
        logger.exception("Failed to fetch items page")
        return 0

    # Pattern para extrair dados de itens
    # Procura por blocos de item com nome, gold, stats e passiva
    item_pattern = re.compile(
        r'<h[23][^>]*>([^<]+)</h[23]>'  # Nome do item
        r'.*?'
        r'(\d{2,4})\s*(?:Gold|gold|G)'  # Custo em gold
        r'.*?'
        r'((?:\+\d+[^<]{1,30})+)'  # Stats
        r'.*?'
        r'(?:Passive|PASSIVE|passive)[:\s]*([^<]+)',  # Passiva
        re.DOTALL | re.IGNORECASE
    )

    # Pattern alternativo mais simples
    simple_pattern = re.compile(
        r'<strong>([^<]+)</strong>\s*'
        r'.*?(\d{2,4})\s*Gold'
        r'.*?Stats:\s*([^<]+)'
        r'.*?(?:Passive:?\s*)?([^<]{10,200})',
        re.DOTALL | re.IGNORECASE
    )

    count = 0

    # Lista de itens conhecidos do wr-meta (extraídos manualmente como fallback)
    known_items = [
        # Physical Damage
        {"name": "Bloodthirster", "gold": 3000, "stats": "+55 AD, +250 HP, +25% Crit", "passive": "8% Physical Vamp, crits grant extra vamp", "category": "physical"},
        {"name": "Guardian Angel", "gold": 3400, "stats": "+40 AD, +40 Armor", "passive": "Resurrect on death, restore 50% HP", "category": "physical"},
        {"name": "Blade of the Ruined King", "gold": 3000, "stats": "+25 AD, +35% AS", "passive": "Attacks deal 7% current enemy health damage", "category": "physical"},
        {"name": "Infinity Edge", "gold": 3400, "stats": "+60 AD, +25% Crit", "passive": "Crits deal 205% damage", "category": "physical"},
        {"name": "Mortal Reminder", "gold": 3300, "stats": "+25 AD, +25% Crit, +15% AS", "passive": "30% armor pen, grievous wounds on crit", "category": "physical"},
        {"name": "Black Cleaver", "gold": 3000, "stats": "+400 HP, +40 AD, +20 Haste", "passive": "Armor reduction stacking up to 24%", "category": "physical"},
        {"name": "Trinity Force", "gold": 3333, "stats": "+250 HP, +30 AD, +30% AS, +25 Haste", "passive": "Spellblade bonus damage after abilities", "category": "physical"},
        {"name": "Youmuu's Ghostblade", "gold": 3200, "stats": "+55 AD, +15 Haste", "passive": "Momentum grants MS and armor pen", "category": "physical"},
        {"name": "Phantom Dancer", "gold": 2800, "stats": "+20 AD, +25% Crit, +40% AS", "passive": "MS and AS boost after champion hit", "category": "physical"},
        {"name": "Essence Reaver", "gold": 3000, "stats": "+35 AD, +25% Crit, +20 Haste", "passive": "Spellblade, 3% missing mana restore", "category": "physical"},
        {"name": "Divine Sunderer", "gold": 3400, "stats": "+425 HP, +25 AD, +25 Haste", "passive": "Spellblade deals % max health damage", "category": "physical"},
        {"name": "Serpent's Fang", "gold": 2800, "stats": "+50 AD, +10 Haste", "passive": "15 armor pen, reduces enemy shields", "category": "physical"},
        {"name": "Chempunk Chainsword", "gold": 2800, "stats": "+250 HP, +45 AD, +15 Haste", "passive": "Physical damage applies 50% grievous wounds", "category": "physical"},
        {"name": "The Collector", "gold": 2900, "stats": "+45 AD, +25% Crit", "passive": "Executes low-health enemies", "category": "physical"},
        {"name": "Sterak's Gage", "gold": 3200, "stats": "+400 HP", "passive": "50% base AD bonus, lifeline shield at 35% HP", "category": "physical"},
        {"name": "Titanic Hydra", "gold": 3000, "stats": "+450 HP", "passive": "Cleave deals bonus damage based on HP", "category": "physical"},
        {"name": "Hullbreaker", "gold": 3100, "stats": "+400 HP, +50 AD", "passive": "Enhanced damage vs structures", "category": "physical"},

        # Magic Damage
        {"name": "Luden's Echo", "gold": 3000, "stats": "+85 AP, +300 Mana, +20 Haste", "passive": "Discord buildup, AoE burst damage", "category": "magic"},
        {"name": "Morellonomicon", "gold": 2500, "stats": "+150 HP, +70 AP, +20 Haste", "passive": "Magic damage applies 50% grievous wounds", "category": "magic"},
        {"name": "Rabadon's Deathcap", "gold": 3400, "stats": "+100 AP", "passive": "20-45% AP amplification", "category": "magic"},
        {"name": "Rylai's Crystal Scepter", "gold": 2700, "stats": "+300 HP, +65 AP", "passive": "Abilities slow 30%", "category": "magic"},
        {"name": "Liandry's Torment", "gold": 3000, "stats": "+250 HP, +75 AP", "passive": "Damage-over-time burn", "category": "magic"},
        {"name": "Rod of Ages", "gold": 2800, "stats": "+250 HP, +60 AP, +300 Mana", "passive": "Stacking stats over time", "category": "magic"},
        {"name": "Lich Bane", "gold": 2950, "stats": "+80 AP, +10 Haste", "passive": "Spellblade bonus magic damage", "category": "magic"},
        {"name": "Archangel's Staff", "gold": 2950, "stats": "+35 AP, +500 Mana, +20 Haste", "passive": "Converts mana to AP", "category": "magic"},
        {"name": "Riftmaker", "gold": 3300, "stats": "+150 HP, +80 AP, +15 Haste, +11% Omnivamp", "passive": "Damage scales to true damage", "category": "magic"},
        {"name": "Horizon Focus", "gold": 3100, "stats": "+90 AP, +20 Haste", "passive": "Long-range damage amplification", "category": "magic"},
        {"name": "Cosmic Drive", "gold": 2800, "stats": "+75 AP, +30 Haste", "passive": "Ability damage grants movement speed", "category": "magic"},
        {"name": "Crown of the Shattered Queen", "gold": 3000, "stats": "+60 AP, +200 Mana, +20 Haste", "passive": "Spell shield and damage reduction", "category": "magic"},
        {"name": "Nashor's Tooth", "gold": 3000, "stats": "+45% AS, +20 Haste", "passive": "On-hit magic damage", "category": "magic"},

        # Defense
        {"name": "Thornmail", "gold": 2700, "stats": "+200 HP, +75 Armor", "passive": "Reflects damage, applies grievous wounds", "category": "defense"},
        {"name": "Randuin's Omen", "gold": 2800, "stats": "+400 HP, +55 Armor", "passive": "Reduces crit damage, active slow", "category": "defense"},
        {"name": "Dead Man's Plate", "gold": 2800, "stats": "+300 HP, +50 Armor", "passive": "Movement builds momentum for damage", "category": "defense"},
        {"name": "Sunfire Aegis", "gold": 2700, "stats": "+350 HP, +40 Armor, +40 MR", "passive": "Immolate burns nearby enemies", "category": "defense"},
        {"name": "Force of Nature", "gold": 2800, "stats": "+350 HP, +60 MR", "passive": "Movement speed, magic damage reduction", "category": "defense"},
        {"name": "Spirit Visage", "gold": 2800, "stats": "+350 HP, +45 MR, +10 Haste", "passive": "Increases all healing by 25%", "category": "defense"},
        {"name": "Warmog's Armor", "gold": 2850, "stats": "+700 HP, +10 Haste", "passive": "Regenerate HP out of combat", "category": "defense"},
        {"name": "Frozen Heart", "gold": 2700, "stats": "+70 Armor, +300 Mana, +20 Haste", "passive": "Reduces nearby enemy attack speed", "category": "defense"},
        {"name": "Gargoyle Enchant", "gold": 1000, "stats": "", "passive": "Shield based on bonus HP", "category": "boots"},
        {"name": "Stasis Enchant", "gold": 1000, "stats": "", "passive": "Become invulnerable for 2.5s", "category": "boots"},
        {"name": "Protobelt Enchant", "gold": 1000, "stats": "", "passive": "Dash forward and fire bolts", "category": "boots"},
        {"name": "Redemption Enchant", "gold": 1000, "stats": "", "passive": "Heal allies in area", "category": "boots"},
        {"name": "Locket Enchant", "gold": 1000, "stats": "", "passive": "Shield nearby allies", "category": "boots"},
        {"name": "Quicksilver Enchant", "gold": 1000, "stats": "", "passive": "Remove all CC", "category": "boots"},
        {"name": "Glorious Enchant", "gold": 1000, "stats": "", "passive": "Gain massive movement speed", "category": "boots"},
        {"name": "Shadows Enchant", "gold": 1000, "stats": "", "passive": "Become invisible briefly", "category": "boots"},

        # Boots
        {"name": "Boots of Speed", "gold": 500, "stats": "+25 MS", "passive": "Basic movement speed", "category": "boots"},
        {"name": "Plated Steelcaps", "gold": 1000, "stats": "+40 Armor, +40 MS", "passive": "Reduces auto attack damage", "category": "boots"},
        {"name": "Mercury's Treads", "gold": 1000, "stats": "+40 MR, +40 MS", "passive": "Tenacity reduces CC duration", "category": "boots"},
        {"name": "Ionian Boots of Lucidity", "gold": 950, "stats": "+15 Haste, +40 MS", "passive": "Reduces summoner spell cooldowns", "category": "boots"},
        {"name": "Gluttonous Greaves", "gold": 1000, "stats": "+8% Omnivamp, +40 MS", "passive": "Sustain from all damage", "category": "boots"},
        {"name": "Boots of Swiftness", "gold": 900, "stats": "+55 MS", "passive": "Slow resistance", "category": "boots"},

        # Support
        {"name": "Ardent Censer", "gold": 2700, "stats": "+250 HP, +35 AP, +20 Haste", "passive": "Heals/shields grant AS to allies", "category": "support"},
        {"name": "Staff of Flowing Water", "gold": 2500, "stats": "+100 HP, +45 AP, +20 Haste", "passive": "Heals/shields grant haste", "category": "support"},
        {"name": "Harmonic Echo", "gold": 2600, "stats": "+100 HP, +40 AP, +300 Mana", "passive": "Healing chains to nearby allies", "category": "support"},
    ]

    with psycopg.connect(POSTGRES_DSN) as conn:
        _ensure_game_tables(conn)

        for item in known_items:
            stats = _parse_item_stats(item["stats"])
            category, tags = _categorize_item(item["name"], stats, item["passive"])

            # Usar categoria do item se disponível, senão usar a detectada
            final_category = item.get("category", category)

            # Normalizar nome para busca
            name_normalized = item["name"].lower().replace("'", "").replace(" ", "_")

            conn.execute(
                """
                INSERT INTO items (name, name_normalized, category, gold_cost, stats, passive_name, passive_desc, tags)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    name_normalized = EXCLUDED.name_normalized,
                    category = EXCLUDED.category,
                    gold_cost = EXCLUDED.gold_cost,
                    stats = EXCLUDED.stats,
                    passive_desc = EXCLUDED.passive_desc,
                    tags = EXCLUDED.tags,
                    updated_at = NOW()
                """,
                (
                    item["name"],
                    name_normalized,
                    final_category,
                    item["gold"],
                    json.dumps(stats),
                    None,  # passive_name extraído separadamente se necessário
                    item["passive"],
                    tags,
                ),
            )
            count += 1

        conn.commit()
        logger.info(f"Synced {count} items")

    return count


def sync_all() -> dict[str, int]:
    """Sincroniza todos os dados do jogo."""
    results = {
        "champions": 0,
        "stats": 0,
        "winrates": 0,
        "items": 0,
        "abilities": 0,
    }

    try:
        hero_map = sync_champions_from_tencent()
        results["champions"] = len(hero_map)
    except Exception:
        logger.exception("Failed to sync champions")

    try:
        results["stats"] = sync_champion_stats()
    except Exception:
        logger.exception("Failed to sync champion stats")

    try:
        results["winrates"] = sync_winrates()
    except Exception:
        logger.exception("Failed to sync winrates")

    try:
        results["abilities"] = sync_champion_abilities()
    except Exception:
        logger.exception("Failed to sync champion abilities")

    try:
        results["items"] = sync_items_from_wrmeta()
    except Exception:
        logger.exception("Failed to sync items")

    return results


def get_champion_info(champion_name: str) -> dict[str, Any] | None:
    """Busca informações de um campeão pelo nome."""
    if not POSTGRES_DSN:
        return None

    try:
        with psycopg.connect(POSTGRES_DSN) as conn:
            row = conn.execute(
                """
                SELECT c.hero_id, c.name_cn, c.name_en, c.roles, c.lanes,
                       c.difficulty, c.damage, c.survivability, c.utility,
                       s.health_base, s.armor_base, s.attack_base, s.move_speed
                FROM champions c
                LEFT JOIN champion_stats s ON c.hero_id = s.hero_id
                WHERE LOWER(c.name_en) = LOWER(%s)
                   OR LOWER(c.alias) = LOWER(%s)
                   OR LOWER(c.name_cn) = %s
                LIMIT 1
                """,
                (champion_name, champion_name, champion_name),
            ).fetchone()

            if not row:
                return None

            return {
                "hero_id": row[0],
                "name_cn": row[1],
                "name_en": row[2],
                "roles": row[3],
                "lanes": row[4],
                "difficulty": row[5],
                "damage": row[6],
                "survivability": row[7],
                "utility": row[8],
                "stats": {
                    "health": row[9],
                    "armor": row[10],
                    "attack": row[11],
                    "move_speed": row[12],
                },
            }
    except Exception:
        logger.exception("Failed to get champion info")
        return None


def get_champion_abilities(champion_name: str) -> list[dict[str, Any]]:
    """Fetch champion abilities by name."""
    if not POSTGRES_DSN:
        return []

    try:
        with psycopg.connect(POSTGRES_DSN) as conn:
            hero_row = conn.execute(
                """
                SELECT hero_id FROM champions
                WHERE LOWER(name_en) = LOWER(%s)
                   OR LOWER(alias) = LOWER(%s)
                   OR LOWER(name_cn) = %s
                LIMIT 1
                """,
                (champion_name, champion_name, champion_name),
            ).fetchone()
            if not hero_row:
                return []

            hero_id = hero_row[0]
            rows = conn.execute(
                """
                SELECT ability_key, ability_name, description
                FROM champion_abilities
                WHERE hero_id = %s
                ORDER BY
                    CASE ability_key
                        WHEN 'passive' THEN 0
                        WHEN 'q' THEN 1
                        WHEN 'w' THEN 2
                        WHEN 'e' THEN 3
                        WHEN 'r' THEN 4
                        ELSE 5
                    END
                """,
                (hero_id,),
            ).fetchall()
            return [
                {
                    "key": row[0],
                    "name": row[1],
                    "description": row[2],
                }
                for row in rows
            ]
    except Exception:
        logger.exception("Failed to get champion abilities")
        return []


def get_champion_winrate(champion_name: str, position: str | None = None) -> dict[str, Any] | None:
    """Busca winrate de um campeão."""
    if not POSTGRES_DSN:
        return None

    try:
        with psycopg.connect(POSTGRES_DSN) as conn:
            # Primeiro busca o hero_id
            hero_row = conn.execute(
                """
                SELECT hero_id FROM champions
                WHERE LOWER(name_en) = LOWER(%s)
                   OR LOWER(alias) = LOWER(%s)
                LIMIT 1
                """,
                (champion_name, champion_name),
            ).fetchone()

            if not hero_row:
                return None

            hero_id = hero_row[0]

            # Busca winrate
            if position:
                row = conn.execute(
                    """
                    SELECT position, win_rate, pick_rate, ban_rate, strength_tier
                    FROM champion_winrates
                    WHERE hero_id = %s AND position = %s
                    ORDER BY stat_date DESC
                    LIMIT 1
                    """,
                    (hero_id, position),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT position, win_rate, pick_rate, ban_rate, strength_tier
                    FROM champion_winrates
                    WHERE hero_id = %s
                    ORDER BY pick_rate DESC, stat_date DESC
                    LIMIT 1
                    """,
                    (hero_id,),
                ).fetchone()

            if not row:
                return None

            return {
                "position": row[0],
                "win_rate": float(row[1]) * 100,
                "pick_rate": float(row[2]) * 100,
                "ban_rate": float(row[3]) * 100,
                "tier": row[4],
            }
    except Exception:
        logger.exception("Failed to get champion winrate")
        return None


def get_matchup_tips(champion: str, enemy: str, lane: str | None = None) -> dict[str, Any] | None:
    """Busca dicas de matchup."""
    if not POSTGRES_DSN:
        return None

    try:
        with psycopg.connect(POSTGRES_DSN) as conn:
            if lane:
                row = conn.execute(
                    """
                    SELECT difficulty, tips, counter_items, power_spikes, score
                    FROM matchup_tips
                    WHERE LOWER(champion) = LOWER(%s)
                      AND LOWER(enemy) = LOWER(%s)
                      AND LOWER(lane) = LOWER(%s)
                    LIMIT 1
                    """,
                    (champion, enemy, lane),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT difficulty, tips, counter_items, power_spikes, score
                    FROM matchup_tips
                    WHERE LOWER(champion) = LOWER(%s)
                      AND LOWER(enemy) = LOWER(%s)
                    ORDER BY score DESC
                    LIMIT 1
                    """,
                    (champion, enemy),
                ).fetchone()

            if not row:
                return None

            return {
                "difficulty": row[0],
                "tips": row[1] or [],
                "counter_items": row[2] or [],
                "power_spikes": row[3] or [],
                "score": row[4],
            }
    except Exception:
        logger.exception("Failed to get matchup tips")
        return None


def get_item_info(item_name: str) -> dict[str, Any] | None:
    """Busca informações de um item pelo nome."""
    if not POSTGRES_DSN:
        return None

    try:
        with psycopg.connect(POSTGRES_DSN) as conn:
            row = conn.execute(
                """
                SELECT name, category, gold_cost, stats, passive_desc, tags
                FROM items
                WHERE LOWER(name) = LOWER(%s)
                   OR name_normalized = %s
                   OR name ILIKE %s
                LIMIT 1
                """,
                (item_name, item_name.lower().replace(" ", "_").replace("'", ""),
                 f"%{item_name}%"),
            ).fetchone()

            if not row:
                return None

            return {
                "name": row[0],
                "category": row[1],
                "gold_cost": row[2],
                "stats": row[3] or {},
                "passive": row[4],
                "tags": row[5] or [],
            }
    except Exception:
        logger.exception("Failed to get item info")
        return None


def get_counter_items(
    enemy_type: str | None = None,
    needs_anti_heal: bool = False,
    needs_armor_pen: bool = False,
    needs_magic_resist: bool = False,
    needs_armor: bool = False,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """
    Sugere itens baseado no contexto.

    Args:
        enemy_type: Tipo de inimigo (tank, assassin, mage, etc.)
        needs_anti_heal: Se precisa de grievous wounds
        needs_armor_pen: Se precisa de penetração de armadura
        needs_magic_resist: Se precisa de resistência mágica
        needs_armor: Se precisa de armadura
        category: Categoria de item preferida (physical, magic, defense)
    """
    if not POSTGRES_DSN:
        return []

    try:
        with psycopg.connect(POSTGRES_DSN) as conn:
            conditions = []
            params = []

            if needs_anti_heal:
                conditions.append("'anti_heal' = ANY(tags)")
            if needs_armor_pen:
                conditions.append("'armor_pen' = ANY(tags)")
            if needs_magic_resist:
                conditions.append("(stats->>'magic_resist')::int > 0")
            if needs_armor:
                conditions.append("(stats->>'armor')::int > 0")
            if category:
                conditions.append("category = %s")
                params.append(category)

            where_clause = " OR ".join(conditions) if conditions else "1=1"

            rows = conn.execute(
                f"""
                SELECT name, category, gold_cost, stats, passive_desc, tags
                FROM items
                WHERE {where_clause}
                ORDER BY gold_cost DESC
                LIMIT 5
                """,
                params,
            ).fetchall()

            return [
                {
                    "name": row[0],
                    "category": row[1],
                    "gold_cost": row[2],
                    "stats": row[3] or {},
                    "passive": row[4],
                    "tags": row[5] or [],
                }
                for row in rows
            ]
    except Exception:
        logger.exception("Failed to get counter items")
        return []


def get_items_by_category(category: str, limit: int = 5) -> list[dict[str, Any]]:
    """Busca itens por categoria."""
    if not POSTGRES_DSN:
        return []

    try:
        with psycopg.connect(POSTGRES_DSN) as conn:
            rows = conn.execute(
                """
                SELECT name, category, gold_cost, stats, passive_desc, tags
                FROM items
                WHERE category = %s
                ORDER BY gold_cost DESC
                LIMIT %s
                """,
                (category, limit),
            ).fetchall()

            return [
                {
                    "name": row[0],
                    "category": row[1],
                    "gold_cost": row[2],
                    "stats": row[3] or {},
                    "passive": row[4],
                    "tags": row[5] or [],
                }
                for row in rows
            ]
    except Exception:
        logger.exception("Failed to get items by category")
        return []
