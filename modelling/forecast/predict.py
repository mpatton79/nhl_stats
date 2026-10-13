"""
Forecast xG for games that haven't been played yet.

    cd modelling
    python -m forecast.predict                    # all remaining games from today
    python -m forecast.predict --days 7           # only the next 7 days
    python -m forecast.predict --date 2026-10-15  # forecast as of another date

Ratings are built from every completed game with xG, then frozen: a game three
weeks out uses today's ratings, so nearer games are more reliable. Output goes
to nhl-data-lake/data/lake/xg_forecast/forecast_date=<date>/xg_forecast.parquet
(one partition per run date, so past forecasts are kept for later checking) and
is exposed in DuckDB as v_game_xg_forecast (latest run only) after build_db.
"""

import argparse
import logging
from datetime import date, timedelta

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .config import DB_PATH, FORECAST_DIR, N_DRAWS, QUANTILES, SEED
from .engine import RatingEngine, load_completed, load_upcoming, win_probability

logger = logging.getLogger(__name__)


def forecast(completed: pd.DataFrame, upcoming: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Build ratings from *completed*, then forecast every game in *upcoming*."""
    engine = RatingEngine()
    engine.seed(completed.head(200))
    for g in completed.itertuples(index=False):
        exp = engine.expect(g.home_team, g.away_team)
        engine.update(g.home_team, g.away_team, g.home_xg, g.away_xg, exp)

    ratings_through = str(completed["game_date"].max())
    rng = np.random.default_rng(SEED)
    rows = []
    for g in upcoming.itertuples(index=False):
        exp = engine.expect(g.home_team, g.away_team)
        home = engine.sample(g.home_team, exp["home_xg"], N_DRAWS, rng)
        away = engine.sample(g.away_team, exp["away_xg"], N_DRAWS, rng)
        row = {
            "forecast_date": as_of.isoformat(),
            "ratings_through": ratings_through,
            "game_id": g.game_id, "season": g.season, "game_date": g.game_date,
            "start_time_utc": g.start_time_utc, "game_type": g.game_type,
            "home_team": g.home_team, "away_team": g.away_team,
            "home_xg": exp["home_xg"], "away_xg": exp["away_xg"],
        }
        for side, draws in (("home", home), ("away", away)):
            for q, v in zip(QUANTILES, np.quantile(draws, QUANTILES)):
                row[f"{side}_xg_p{int(q * 100)}"] = v
        row["p_home_xg_higher"] = float((home > away).mean())
        row["p_home_win"] = win_probability(home, away, rng)
        row.update({
            "home_off_rating": exp["home_off"], "home_def_rating": exp["home_def"],
            "away_off_rating": exp["away_off"], "away_def_rating": exp["away_def"],
            "league_avg_xg": exp["league_avg"], "home_factor": exp["home_factor"],
        })
        rows.append(row)
    return pd.DataFrame(rows)


def run(as_of: date | None = None, days: int | None = None) -> pd.DataFrame:
    as_of = as_of or date.today()
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        completed = load_completed(con)
        upcoming = load_upcoming(con, as_of)
    if days is not None:
        cutoff = as_of + timedelta(days=days)
        upcoming = upcoming[pd.to_datetime(upcoming["game_date"]).dt.date < cutoff]
    if upcoming.empty:
        logger.info("No upcoming games to forecast from %s", as_of)
        return upcoming

    out = forecast(completed, upcoming, as_of)
    dest = FORECAST_DIR / f"forecast_date={as_of.isoformat()}"
    dest.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(out, preserve_index=False), dest / "xg_forecast.parquet")
    logger.info("Forecast %d games (%s → %s); ratings through %s",
                len(out), out["game_date"].min(), out["game_date"].max(), out["ratings_through"].iloc[0])
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Forecast xG for upcoming games")
    parser.add_argument("--date", type=date.fromisoformat, help="Forecast as of this date (default: today)")
    parser.add_argument("--days", type=int, help="Only forecast games within this many days")
    args = parser.parse_args()

    out = run(as_of=args.date, days=args.days)
    if not out.empty:
        cols = ["game_date", "away_team", "home_team", "away_xg", "home_xg",
                "away_xg_p10", "away_xg_p90", "home_xg_p10", "home_xg_p90", "p_home_xg_higher", "p_home_win"]
        print(out[cols].head(12).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
