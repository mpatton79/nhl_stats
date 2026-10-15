import os
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

_DEFAULT_DB = Path(__file__).parent.parent / "nhl-data-lake" / "db" / "nhl.duckdb"
DB_PATH = Path(os.getenv("NHL_DB_PATH", str(_DEFAULT_DB)))


@st.cache_resource
def _conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=True)


@st.cache_data(ttl=300)
def query(sql: str, params: list | None = None) -> pd.DataFrame:
    return _conn().execute(sql, params or []).fetchdf()


def game_forecasts(game_date) -> dict[int, dict]:
    """Pre-game xG forecasts for *game_date*, keyed by game_id.

    Reads the forecast history (raw_xg_forecast) and keeps each game's latest
    forecast made on or before its game date, so finished games keep the
    forecast they had going in. Empty if no forecasts have been built yet.
    """
    try:
        df = query(
            """
            SELECT * FROM raw_xg_forecast
            WHERE CAST(game_date AS DATE) = ?
              AND CAST(forecast_date AS DATE) <= CAST(game_date AS DATE)
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY game_id ORDER BY CAST(forecast_date AS DATE) DESC) = 1
            """,
            [game_date],
        )
    except duckdb.Error:
        return {}
    return {int(r["game_id"]): r for r in df.to_dict(orient="records")}


def game_actual_xg(game_date) -> dict[int, dict]:
    """Actual xG and unblocked shot attempts per team for *game_date*, keyed by game_id.

    Sums the shot model's goal probabilities (raw_shot_xg), so only games whose
    play-by-play has been ingested appear: completed games through yesterday,
    once the pipeline has run. Empty if shot xG hasn't been built yet.
    """
    try:
        df = query(
            """
            SELECT game_id,
                   COALESCE(SUM(CASE WHEN is_home = 1 THEN xg END), 0) AS home_xg,
                   COALESCE(SUM(CASE WHEN is_home = 0 THEN xg END), 0) AS away_xg,
                   COUNT(CASE WHEN is_home = 1 THEN 1 END)             AS home_attempts,
                   COUNT(CASE WHEN is_home = 0 THEN 1 END)             AS away_attempts
            FROM raw_shot_xg
            WHERE CAST(game_date AS DATE) = ?
            GROUP BY game_id
            """,
            [game_date],
        )
    except duckdb.Error:
        return {}
    return {int(r["game_id"]): r for r in df.to_dict(orient="records")}


def seasons(view: str = "v_skater_stats") -> list[str]:
    df = query(f"SELECT DISTINCT season FROM {view} ORDER BY season DESC")
    return df["season"].tolist()
