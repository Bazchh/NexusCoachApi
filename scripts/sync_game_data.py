from __future__ import annotations

import logging

import psycopg

from app import db, game_data
from app.config import POSTGRES_DSN


def main() -> None:
    if not POSTGRES_DSN:
        raise SystemExit("POSTGRES_DSN not configured in .env")

    logging.basicConfig(level=logging.INFO)

    with psycopg.connect(POSTGRES_DSN) as conn:
        db._ensure_tables(conn)

    results = game_data.sync_all()
    print(results)


if __name__ == "__main__":
    main()
