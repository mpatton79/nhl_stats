"""
Ingest NHL Edge team stats: skating distance, skating speed, zone time,
shot speed, and shot location.

All detail endpoints require a numeric team-id (as string):
  GET /v1/edge/team-skating-distance-detail/{team-id}/{season}/{game-type}
  GET /v1/edge/team-skating-speed-detail/{team-id}/{season}/{game-type}
  GET /v1/edge/team-zone-time-details/{team-id}/{season}/{game-type}
  GET /v1/edge/team-shot-speed-detail/{team-id}/{season}/{game-type}
  GET /v1/edge/team-shot-location-detail/{team-id}/{season}/{game-type}

Produces 6 parquet files:
  team_skating_distance.parquet  — long by strength_code × position_code
  team_skating_speed.parquet     — long by position_code
  team_zone_time.parquet         — one row per team/season
  team_shot_speed.parquet        — one row per team/season
  team_shot_location_totals.parquet   — long by location_code × position
  team_shot_location_details.parquet  — long by shot area

Note: Edge stats are only available from ~2019-20 onward.
"""

import logging

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import NHL_WEB_API, SEASONS, RAW_DIR, LAKE_DIR
from ingest.http_client import fetch_and_cache

logger = logging.getLogger(__name__)

RAW_EDGE  = RAW_DIR  / "edge_stats"
LAKE_EDGE = LAKE_DIR / "edge_stats"

GAME_TYPE = 2  # regular season
EDGE_STATS_FIRST_SEASON = "20212022"  # edge stats not available before this

_HARDCODED_TEAM_IDS: dict[str, str] = {
    "ANA": "24", "BOS": "6",  "BUF": "7",  "CAR": "12", "CBJ": "29",
    "CGY": "20", "CHI": "16", "COL": "21", "DAL": "25", "DET": "17",
    "EDM": "22", "FLA": "13", "LAK": "26", "MIN": "30", "MTL": "8",
    "NJD": "1",  "NSH": "18", "NYI": "2",  "NYR": "3",  "OTT": "9",
    "PHI": "4",  "PIT": "5",  "SEA": "55", "SJS": "28", "STL": "19",
    "TBL": "14", "TOR": "10", "UTA": "59", "VAN": "23", "VGK": "54",
    "WPG": "52", "WSH": "15",
}


def _load_team_ids() -> dict[str, str]:
    teams_parquet = LAKE_DIR / "teams" / "teams.parquet"
    if teams_parquet.exists():
        df = pd.read_parquet(teams_parquet).dropna(subset=["team_id"])
        if not df.empty:
            return dict(zip(df["abbrev"], df["team_id"].astype(int).astype(str)))
    logger.warning("Could not load team IDs from teams.parquet — using hardcoded values")
    return _HARDCODED_TEAM_IDS


def _fetch(endpoint: str, team_id: str, season: str, cache_path) -> dict | None:
    url = f"{NHL_WEB_API}/edge/{endpoint}/{team_id}/{season}/{GAME_TYPE}"
    return fetch_and_cache(url, cache_path)


# ── Fetch functions ───────────────────────────────────────────────────────────

def fetch_skating_distance(abbrev: str, team_id: str, season: str) -> dict | None:
    return _fetch("team-skating-distance-detail", team_id, season,
                  RAW_EDGE / "skating_distance" / season / f"{abbrev}.json")

def fetch_skating_speed(abbrev: str, team_id: str, season: str) -> dict | None:
    return _fetch("team-skating-speed-detail", team_id, season,
                  RAW_EDGE / "skating_speed" / season / f"{abbrev}.json")

def fetch_zone_time(abbrev: str, team_id: str, season: str) -> dict | None:
    return _fetch("team-zone-time-details", team_id, season,
                  RAW_EDGE / "zone_time" / season / f"{abbrev}.json")

def fetch_shot_speed(abbrev: str, team_id: str, season: str) -> dict | None:
    return _fetch("team-shot-speed-detail", team_id, season,
                  RAW_EDGE / "shot_speed" / season / f"{abbrev}.json")

def fetch_shot_location(abbrev: str, team_id: str, season: str) -> dict | None:
    return _fetch("team-shot-location-detail", team_id, season,
                  RAW_EDGE / "shot_location" / season / f"{abbrev}.json")


# ── Parse functions ───────────────────────────────────────────────────────────

def parse_skating_distance(abbrev: str, team_id: str, season: str, data: dict) -> list[dict]:
    rows = []
    for r in data.get("skatingDistanceDetails", []):
        rows.append({
            "season":                    season,
            "team_id":                   team_id,
            "team_abbrev":               abbrev,
            "strength_code":             r.get("strengthCode"),
            "position_code":             r.get("positionCode"),
            "distance_total_imperial":   r.get("distanceTotal", {}).get("imperial"),
            "distance_total_rank":       r.get("distanceTotal", {}).get("rank"),
            "distance_total_league_avg": r.get("distanceTotal", {}).get("leagueAvg", {}).get("imperial"),
            "distance_per60_imperial":   r.get("distancePer60", {}).get("imperial"),
            "distance_per60_rank":       r.get("distancePer60", {}).get("rank"),
            "distance_per60_league_avg": r.get("distancePer60", {}).get("leagueAvg", {}).get("imperial"),
            "distance_max_game_imperial":r.get("distanceMaxGame", {}).get("imperial"),
            "distance_max_game_rank":    r.get("distanceMaxGame", {}).get("rank"),
            "distance_max_period_imperial": r.get("distanceMaxPeriod", {}).get("imperial"),
            "distance_max_period_rank":  r.get("distanceMaxPeriod", {}).get("rank"),
        })
    return rows


def parse_skating_speed(abbrev: str, team_id: str, season: str, data: dict) -> list[dict]:
    rows = []
    for r in data.get("skatingSpeedDetails", []):
        rows.append({
            "season":                       season,
            "team_id":                      team_id,
            "team_abbrev":                  abbrev,
            "position_code":                r.get("positionCode"),
            "max_speed_imperial":           r.get("maxSkatingSpeed", {}).get("imperial"),
            "max_speed_rank":               r.get("maxSkatingSpeed", {}).get("rank"),
            "max_speed_league_avg":         r.get("maxSkatingSpeed", {}).get("leagueAvg", {}).get("imperial"),
            "bursts_over_22":               r.get("burstsOver22", {}).get("value"),
            "bursts_over_22_rank":          r.get("burstsOver22", {}).get("rank"),
            "bursts_over_22_league_avg":    r.get("burstsOver22", {}).get("leagueAvg"),
            "bursts_20_to_22":              r.get("bursts20To22", {}).get("value"),
            "bursts_18_to_20":              r.get("bursts18To20", {}).get("value"),
        })
    return rows


def parse_zone_time(abbrev: str, team_id: str, season: str, data: dict) -> list[dict]:
    sd = data.get("shotDifferential", {})
    rows = []
    for zt in data.get("zoneTimeDetails", []):
        rows.append({
            "season":                         season,
            "team_id":                        team_id,
            "team_abbrev":                    abbrev,
            "strength_code":                  zt.get("strengthCode"),
            "offensive_zone_pctg":            zt.get("offensiveZonePctg"),
            "offensive_zone_rank":            zt.get("offensiveZoneRank"),
            "offensive_zone_league_avg":      zt.get("offensiveZoneLeagueAvg"),
            "neutral_zone_pctg":              zt.get("neutralZonePctg"),
            "neutral_zone_rank":              zt.get("neutralZoneRank"),
            "neutral_zone_league_avg":        zt.get("neutralZoneLeagueAvg"),
            "defensive_zone_pctg":            zt.get("defensiveZonePctg"),
            "defensive_zone_rank":            zt.get("defensiveZoneRank"),
            "defensive_zone_league_avg":      zt.get("defensiveZoneLeagueAvg"),
            "shot_attempt_differential":      sd.get("shotAttemptDifferential"),
            "shot_attempt_differential_rank": sd.get("shotAttemptDifferentialRank"),
            "sog_differential":               sd.get("sogDifferential"),
            "sog_differential_rank":          sd.get("sogDifferentialRank"),
        })
    return rows


def parse_shot_speed(abbrev: str, team_id: str, season: str, data: dict) -> list[dict]:
    rows = []
    for s in data.get("shotSpeedDetails", []):
        rows.append({
            "season":                    season,
            "team_id":                   team_id,
            "team_abbrev":               abbrev,
            "position":                  s.get("position"),
            "top_shot_speed_imperial":   s.get("topShotSpeed", {}).get("imperial"),
            "top_shot_speed_rank":       s.get("topShotSpeed", {}).get("rank"),
            "top_shot_speed_league_avg": s.get("topShotSpeed", {}).get("leagueAvg", {}).get("imperial"),
            "avg_shot_speed_imperial":   s.get("avgShotSpeed", {}).get("imperial"),
            "avg_shot_speed_rank":       s.get("avgShotSpeed", {}).get("rank"),
            "avg_shot_speed_league_avg": s.get("avgShotSpeed", {}).get("leagueAvg", {}).get("imperial"),
            "shots_over_100mph":         s.get("shotAttemptsOver100", {}).get("value"),
            "shots_over_100mph_rank":    s.get("shotAttemptsOver100", {}).get("rank"),
            "shots_90_to_100mph":        s.get("shotAttempts90To100", {}).get("value"),
            "shots_90_to_100mph_rank":   s.get("shotAttempts90To100", {}).get("rank"),
            "shots_80_to_90mph":         s.get("shotAttempts80To90", {}).get("value"),
            "shots_70_to_80mph":         s.get("shotAttempts70To80", {}).get("value"),
        })
    return rows


def parse_shot_location_totals(abbrev: str, team_id: str, season: str, data: dict) -> list[dict]:
    rows = []
    for r in data.get("shotLocationTotals", []):
        rows.append({
            "season":                      season,
            "team_id":                     team_id,
            "team_abbrev":                 abbrev,
            "location_code":               r.get("locationCode"),
            "position":                    r.get("position"),
            "sog":                         r.get("sog"),
            "sog_rank":                    r.get("sogRank"),
            "sog_league_avg":              r.get("sogLeagueAvg"),
            "goals":                       r.get("goals"),
            "goals_rank":                  r.get("goalsRank"),
            "goals_league_avg":            r.get("goalsLeagueAvg"),
            "shooting_pctg":               r.get("shootingPctg"),
            "shooting_pctg_rank":          r.get("shootingPctgRank"),
            "shooting_pctg_league_avg":    r.get("shootingPctgLeagueAvg"),
        })
    return rows


def parse_shot_location_details(abbrev: str, team_id: str, season: str, data: dict) -> list[dict]:
    rows = []
    for r in data.get("shotLocationDetails", []):
        rows.append({
            "season":             season,
            "team_id":            team_id,
            "team_abbrev":        abbrev,
            "area":               r.get("area"),
            "sog":                r.get("sog"),
            "sog_rank":           r.get("sogRank"),
            "goals":              r.get("goals"),
            "goals_rank":         r.get("goalsRank"),
            "shooting_pctg":      r.get("shootingPctg"),
            "shooting_pctg_rank": r.get("shootingPctgRank"),
        })
    return rows


# ── Runner ────────────────────────────────────────────────────────────────────

def run(seasons: list[str] | None = None):
    _seasons = [s for s in (seasons or SEASONS) if s >= EDGE_STATS_FIRST_SEASON]
    RAW_EDGE.mkdir(parents=True, exist_ok=True)
    LAKE_EDGE.mkdir(parents=True, exist_ok=True)

    team_ids = _load_team_ids()
    if not team_ids:
        return

    buckets: dict[str, list] = {
        "skating_distance":      [],
        "skating_speed":         [],
        "zone_time":             [],
        "shot_speed":            [],
        "shot_location_totals":  [],
        "shot_location_details": [],
    }

    for season in _seasons:
        for abbrev, team_id in team_ids.items():
            logger.info("Edge stats %s %s", abbrev, season)

            data = fetch_skating_distance(abbrev, team_id, season)
            if data:
                buckets["skating_distance"].extend(parse_skating_distance(abbrev, team_id, season, data))

            data = fetch_skating_speed(abbrev, team_id, season)
            if data:
                buckets["skating_speed"].extend(parse_skating_speed(abbrev, team_id, season, data))

            data = fetch_zone_time(abbrev, team_id, season)
            if data:
                buckets["zone_time"].extend(parse_zone_time(abbrev, team_id, season, data))

            data = fetch_shot_speed(abbrev, team_id, season)
            if data:
                buckets["shot_speed"].extend(parse_shot_speed(abbrev, team_id, season, data))

            data = fetch_shot_location(abbrev, team_id, season)
            if data:
                buckets["shot_location_totals"].extend(parse_shot_location_totals(abbrev, team_id, season, data))
                buckets["shot_location_details"].extend(parse_shot_location_details(abbrev, team_id, season, data))

    output_files = {
        "skating_distance":      "team_skating_distance.parquet",
        "skating_speed":         "team_skating_speed.parquet",
        "zone_time":             "team_zone_time.parquet",
        "shot_speed":            "team_shot_speed.parquet",
        "shot_location_totals":  "team_shot_location_totals.parquet",
        "shot_location_details": "team_shot_location_details.parquet",
    }

    for key, filename in output_files.items():
        rows = buckets[key]
        if rows:
            df = pd.DataFrame(rows)
            pq.write_table(pa.Table.from_pandas(df), LAKE_EDGE / filename)
            logger.info("Wrote %s (%d rows)", filename, len(df))
        else:
            logger.info("No data collected for %s", key)


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
