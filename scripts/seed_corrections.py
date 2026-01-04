from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow running from scripts/ without installing the package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import db

logger = logging.getLogger("nexuscoach")


def apply() -> None:
    """
    Seeds corrections for known Wild Rift reworks.
    Keep this list small and factual.
    """
    saved = db.save_correction(
        champion="Aurelion Sol",
        ability=None,
        topic="kit",
        wrong_info="Aurelion Sol has orbiting stars around his body.",
        correct_info=(
            "In Wild Rift, Aurelion Sol was reworked and no longer has orbiting stars. "
            "The current kit is centered on a channeled breath (Breath of Light), "
            "flight while channeling (Astral Flight), a singularity zone (Singularity), "
            "and a falling impact ultimate (The Skies Descend). "
            "Do not mention orbiting stars."
        ),
        source_session=None,
    )
    if saved:
        logger.info("seed_corrections: Aurelion Sol correction applied")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    apply()
