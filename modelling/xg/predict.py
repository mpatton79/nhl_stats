"""
Score shots with the saved xG model and write predictions to the data lake.

    cd modelling
    python -m xg.predict                  # current season (default; run daily)
    python -m xg.predict --season 20242025
    python -m xg.predict --all            # backfill every season in the lake

Output: nhl-data-lake/data/lake/xg/season=<season>/shot_xg.parquet, exposed in
DuckDB as raw_shot_xg / v_shot_xg after build_db. Each run rewrites the whole
season partition, so it is idempotent. Play-by-play only lands for games on or
before yesterday, so a daily run picks up yesterday's games.

Regular season and playoff shots are scored; the model is trained on regular
season only. Seasons the model was trained on are flagged in_sample = true.
"""

import argparse
import logging

import duckdb
import joblib
import pyarrow as pa
import pyarrow.parquet as pq

from .config import DB_PATH, MODEL_PATH, PLAYOFFS, REGULAR, XG_DIR
from .features import engineer, load_shots, model_frame

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = [
    "game_id", "season", "game_date", "period", "sort_order", "event_id", "game_seconds",
    "event_type", "shot_team_id", "is_home", "shooter_id", "goalie_player_id",
    "x_norm", "y_norm", "shot_distance", "shot_angle", "shot_type", "strength_state",
    "score_diff", "is_rebound", "is_rush", "is_goal", "xg",
]


def load_model() -> dict:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"No model at {MODEL_PATH} — run `python -m xg.train` first")
    return joblib.load(MODEL_PATH)


def score_season(con: duckdb.DuckDBPyConnection, season: str, bundle: dict) -> int:
    """Score one season and write its partition. Returns the number of shots scored."""
    shots = model_frame(engineer(load_shots(con, [season], game_types=(REGULAR, PLAYOFFS))))
    if shots.empty:
        logger.info("No scorable shots for %s", season)
        return 0

    shots["xg"] = bundle["model"].predict_proba(shots[bundle["features"]])[:, 1]
    out = shots[OUTPUT_COLUMNS].copy()
    for col in ("shot_type", "strength_state"):
        out[col] = out[col].astype(str).replace("nan", None)
    out["model_version"] = bundle["version"]
    out["in_sample"] = season in bundle["trained_seasons"]

    dest = XG_DIR / f"season={season}"
    dest.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(out, preserve_index=False), dest / "shot_xg.parquet")
    logger.info("Wrote xG for %s: %d shots, %d goals, %.1f xG",
                season, len(out), int(out["is_goal"].sum()), out["xg"].sum())
    return len(out)


def run(seasons: list[str] | None = None, all_seasons: bool = False) -> None:
    """Score *seasons* (default: the latest season with play-by-play)."""
    bundle = load_model()
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        available = [str(s) for (s,) in
                     con.execute("SELECT DISTINCT season FROM raw_plays ORDER BY season").fetchall()]
        if all_seasons:
            targets = available
        elif seasons:
            targets = seasons
        else:
            targets = available[-1:]
        for season in targets:
            score_season(con, season, bundle)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Score shots with the xG model")
    parser.add_argument("--season", action="append", help="Season to score, e.g. 20252026 (repeatable)")
    parser.add_argument("--all", action="store_true", help="Score every season in the lake")
    args = parser.parse_args()
    run(seasons=args.season, all_seasons=args.all)


if __name__ == "__main__":
    main()
