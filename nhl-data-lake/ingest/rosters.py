"""
Ingest team rosters for each season.

Endpoint:
  GET /v1/roster/{team_abbrev}/{season}
"""

import logging

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import NHL_WEB_API, SEASONS, RAW_DIR, LAKE_DIR
from ingest.http_client import fetch_and_cache, get_json

logger = logging.getLogger(__name__)

RAW_ROSTERS  = RAW_DIR  / "rosters"
LAKE_ROSTERS = LAKE_DIR / "rosters"

# All 32 current NHL team abbreviations
ALL_TEAMS = [
    "ANA", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL",
    "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NJD",
    "NSH", "NYI", "NYR", "OTT", "PHI", "PIT", "SEA", "SJS",
    "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WPG", "WSH",
]


def _parse_player(p: dict, team: str, season: str, position_type: str) -> dict:
    return {
        "season":         season,
        "team_abbrev":    team,
        "player_id":      p.get("id"),
        "first_name":     p.get("firstName", {}).get("default", ""),
        "last_name":      p.get("lastName", {}).get("default", ""),
        "jersey_number":  p.get("sweaterNumber"),
        "position_code":  p.get("positionCode", ""),
        "position_type":  position_type,
        "shoots_catches": p.get("shootsCatches", ""),
        "height_inches":  p.get("heightInInches"),
        "weight_lbs":     p.get("weightInPounds"),
        "birth_date":     p.get("birthDate", ""),
        "birth_country":  p.get("birthCountry", ""),
        "headshot_url":   p.get("headshot", ""),
    }


def fetch_roster(team: str, season: str) -> list[dict]:
    url   = f"{NHL_WEB_API}/roster/{team}/{season}"
    cache = RAW_ROSTERS / season / f"{team}.json"
    data  = fetch_and_cache(url, cache)
    if not data:
        return []

    rows = []
    for pos_type, key in [("F", "forwards"), ("D", "defensemen"), ("G", "goalies")]:
        for p in data.get(key, []):
            rows.append(_parse_player(p, team, season, pos_type))
    return rows


def run(seasons: list[str] | None = None):
    _seasons = seasons or SEASONS
    RAW_ROSTERS.mkdir(parents=True, exist_ok=True)
    LAKE_ROSTERS.mkdir(parents=True, exist_ok=True)

    all_rows = []
    for season in _seasons:
        for team in ALL_TEAMS:
            logger.info("Roster %s %s", team, season)
            rows = fetch_roster(team, season)
            all_rows.extend(rows)

    if all_rows:
        df = pd.DataFrame(all_rows).drop_duplicates(subset=["season", "team_abbrev", "player_id"])
        pq.write_table(
            pa.Table.from_pandas(df),
            LAKE_ROSTERS / "rosters.parquet",
        )
        logger.info("Wrote rosters.parquet (%d rows)", len(df))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
