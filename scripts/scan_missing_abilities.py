from __future__ import annotations

import logging
import sys
from pathlib import Path

import psycopg

# Allow running from scripts/ without installing the package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import POSTGRES_DSN


def main() -> None:
    if not POSTGRES_DSN:
        raise SystemExit("POSTGRES_DSN not configured in .env")

    logging.basicConfig(level=logging.INFO)

    with psycopg.connect(POSTGRES_DSN) as conn:
        rows = conn.execute(
            """
            SELECT c.hero_id, COALESCE(c.name_en, c.alias, c.name_cn) AS name
            FROM champions c
            LEFT JOIN champion_abilities a ON a.hero_id = c.hero_id
            WHERE a.hero_id IS NULL
            ORDER BY name
            """
        ).fetchall()

    print(f"Champions missing abilities: {len(rows)}")
    for hero_id, name in rows:
        print(f"- {name} ({hero_id})")


if __name__ == "__main__":
    main()
