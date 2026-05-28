"""
NHL Data Lake — master ingestion pipeline.

Usage:
    python run_pipeline.py              # full run (all steps)
    python run_pipeline.py --skip-plays # skip play-by-play (fastest for first test)
    python run_pipeline.py --only teams # run a single step

Steps (run in order):
    teams → rosters → players → games → plays → build_db
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Make project root importable
sys.path.insert(0, str(Path(__file__).parent))

from ingest import teams, rosters, players, games, plays
from db.build_db import build_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


STEPS = ["teams", "rosters", "players", "games", "plays", "build_db"]


def run_step(name: str, skip_plays: bool = False):
    t0 = time.time()
    logger.info("═══ Starting step: %s ═══", name.upper())

    if name == "teams":
        teams.run()
    elif name == "rosters":
        rosters.run()
    elif name == "players":
        players.run()
    elif name == "games":
        games.run(with_boxscores=True)
    elif name == "plays":
        if skip_plays:
            logger.info("Skipping play-by-play (--skip-plays flag set)")
        else:
            plays.run()
    elif name == "build_db":
        build_db()

    elapsed = time.time() - t0
    logger.info("═══ Finished %s in %.1fs ═══\n", name.upper(), elapsed)


def main():
    parser = argparse.ArgumentParser(description="NHL Data Lake pipeline runner")
    parser.add_argument("--only",       metavar="STEP",  help=f"Run only this step: {STEPS}")
    parser.add_argument("--skip-plays", action="store_true", help="Skip play-by-play ingest")
    parser.add_argument("--from-step",  metavar="STEP",  help="Start from this step")
    args = parser.parse_args()

    if args.only:
        if args.only not in STEPS:
            print(f"Unknown step '{args.only}'. Choose from: {', '.join(STEPS)}")
            sys.exit(1)
        run_step(args.only, skip_plays=args.skip_plays)
        return

    start_idx = 0
    if args.from_step:
        if args.from_step not in STEPS:
            print(f"Unknown step '{args.from_step}'. Choose from: {', '.join(STEPS)}")
            sys.exit(1)
        start_idx = STEPS.index(args.from_step)

    total_start = time.time()
    for step in STEPS[start_idx:]:
        run_step(step, skip_plays=args.skip_plays)

    total = time.time() - total_start
    logger.info("✓ Full pipeline complete in %.1fs", total)


if __name__ == "__main__":
    main()
