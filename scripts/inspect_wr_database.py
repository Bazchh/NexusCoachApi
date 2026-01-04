from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running from scripts/ without installing the package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.game_data import (
    WR_DATABASE_CHAMPIONS,
    WR_DATABASE_CHAMPION_DETAIL,
    _fetch_json,
    _unwrap_champion_payload,
)


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _find_sample(champs: list[dict]) -> dict | None:
    for champ in champs:
        hero_id = champ.get("heroId") or champ.get("hero_id")
        champ_id = champ.get("id")
        if hero_id and hero_id != 10666 and champ_id and champ_id != "placeholder":
            return champ
    return None


def main() -> None:
    _print_header("Lista de campeoes (wr-database)")
    data = _fetch_json(WR_DATABASE_CHAMPIONS)
    champs = data.get("champions_data", [])
    if not champs:
        print("Nenhum campeao encontrado.")
        return

    champ = _find_sample(champs)
    if not champ:
        print("Nao encontrei um campeao valido na lista.")
        return

    print("Chaves do campeao de exemplo:")
    print(sorted(champ.keys()))
    print("IDs possiveis:")
    for key in ("id", "slug", "alias", "heroId", "name"):
        print(f"- {key}: {champ.get(key)}")

    champ_id = champ.get("id")
    hero_id = champ.get("heroId") or champ.get("hero_id")
    champ_name = str(champ.get("name") or "").strip()
    name_slug = champ_name.lower().replace(" ", "-") if champ_name else ""

    candidates = [
        WR_DATABASE_CHAMPION_DETAIL.format(champ_id),
        WR_DATABASE_CHAMPION_DETAIL.format(hero_id),
        WR_DATABASE_CHAMPION_DETAIL.format(name_slug),
        f"https://wr-database.vercel.app/api/champion/{champ_id}",
        f"https://wr-database.vercel.app/api/champion/{hero_id}",
        f"https://wr-database.vercel.app/api/champion/{name_slug}",
        f"https://wr-database.vercel.app/api/characters/{champ_id}",
        f"https://wr-database.vercel.app/api/character/{champ_id}",
        f"https://wr-database.vercel.app/api/hero/{champ_id}",
    ]

    seen = set()
    urls = [url for url in candidates if url and not (url in seen or seen.add(url))]

    _print_header("Detalhe do campeao")
    for url in urls:
        try:
            payload = _fetch_json(url)
        except Exception as exc:
            print(f"Falha ao buscar {url}: {exc}")
            continue

        print(f"Sucesso em {url}")
        if isinstance(payload, dict):
            print("Chaves do payload:", sorted(payload.keys()))
        detail = _unwrap_champion_payload(payload)
        if not detail:
            print("Payload nao possui bloco de campeao.")
            continue

        print("Chaves do bloco do campeao:")
        print(sorted(detail.keys()))
        for key in ("passive", "spells", "skills", "abilities"):
            value = detail.get(key)
            print(f"- {key}: {type(value).__name__}")
        break


if __name__ == "__main__":
    main()
