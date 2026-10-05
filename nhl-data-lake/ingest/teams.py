"""
Ingest team metadata, season standings, and per-season team stats.

Endpoints used:
  GET /v1/standings/{date}                  — current standings
  GET /stats/rest/en/team/summary           — team stats by season
  GET /v1/standings-season                  — list of standings seasons
"""

import json
import logging
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import NHL_WEB_API, NHL_STATS_API, SEASONS, RAW_DIR, LAKE_DIR
from ingest.http_client import fetch_and_cache, get_json

logger = logging.getLogger(__name__)

RAW_TEAMS  = RAW_DIR  / "teams"
LAKE_TEAMS = LAKE_DIR / "teams"


def fetch_team_list() -> list[dict]:
    """Fetch the master list of NHL franchises."""
    url   = f"{NHL_WEB_API}/standings/now"
    cache = RAW_TEAMS / "standings_now.json"
    data  = fetch_and_cache(url, cache, force=True)  # live resource — always refresh
    if not data:
        return []

    teams = {}
    for record in data.get("standings", []):
        t = record.get("teamCommonName", {})
        abbr = record.get("teamAbbrev", {}).get("default", "")
        tid  = record.get("teamId") or record.get("franchiseId")
        if abbr and abbr not in teams:
            teams[abbr] = {
                "team_id":    tid,
                "abbrev":     abbr,
                "full_name":  record.get("teamName", {}).get("default", ""),
                "conference": record.get("conferenceName", ""),
                "division":   record.get("divisionName", ""),
                "logo_url":   record.get("teamLogo", ""),
            }
    logger.info("Found %d teams", len(teams))
    return list(teams.values())


def _fetch_standings_season_dates() -> dict[str, str]:
    """Return a mapping of season id → standingsEnd date from the API."""
    url   = f"{NHL_WEB_API}/standings-season"
    cache = RAW_TEAMS / "standings_seasons.json"
    data  = fetch_and_cache(url, cache, force=True)  # live resource — always refresh
    if not data:
        return {}
    return {
        str(s.get("id")): s.get("standingsEnd", "")
        for s in data.get("seasons", [])
        if s.get("id") and s.get("standingsEnd")
    }


def fetch_standings_for_season(season: str, end_date: str, force: bool = False) -> list[dict]:
    """Fetch end-of-season standings for a given season using its standingsEnd date."""
    url   = f"{NHL_WEB_API}/standings/{end_date}"
    cache = RAW_TEAMS / f"standings_{season}.json"
    data  = fetch_and_cache(url, cache, force=force)
    if not data:
        return []

    rows = []
    for r in data.get("standings", []):
        rows.append({
            "season":           season,
            "team_abbrev":      r.get("teamAbbrev", {}).get("default", ""),
            "team_name":        r.get("teamName", {}).get("default", ""),
            "conference":       r.get("conferenceName", ""),
            "division":         r.get("divisionName", ""),
            "wins":             r.get("wins", 0),
            "losses":           r.get("losses", 0),
            "ot_losses":        r.get("otLosses", 0),
            "points":           r.get("points", 0),
            "games_played":     r.get("gamesPlayed", 0),
            "goals_for":        r.get("goalFor", 0),
            "goals_against":    r.get("goalAgainst", 0),
            "goal_diff":        r.get("goalDifferential", 0),
            "home_wins":        r.get("homeWins", 0),
            "home_losses":      r.get("homeLosses", 0),
            "road_wins":        r.get("roadWins", 0),
            "road_losses":      r.get("roadLosses", 0),
            "streak_code":      r.get("streakCode", ""),
            "streak_count":     r.get("streakCount", 0),
            "wildcard_seq":     r.get("wildcardSequence", 0),
            "division_seq":     r.get("divisionSequence", 0),
            "conference_seq":   r.get("conferenceSequence", 0),
        })
    return rows


def fetch_team_stats_for_season(season: str, force: bool = False) -> list[dict]:
    """Fetch aggregated team stats from the stats REST API."""
    url   = f"{NHL_STATS_API}/team/summary"
    cache = RAW_TEAMS / f"team_stats_{season}.json"
    params = {
        "cayenneExp": f"seasonId={season} and gameTypeId=2",
        "limit":      -1,
    }
    data = fetch_and_cache(url, cache, params=params, force=force)
    if not data:
        return []

    rows = []
    for r in data.get("data", []):
        rows.append({
            "season":               season,
            "team_id":              r.get("teamId"),
            "team_abbrev":          r.get("teamAbbrevName", ""),
            "team_name":            r.get("teamFullName", ""),
            "games_played":         r.get("gamesPlayed", 0),
            "wins":                 r.get("wins", 0),
            "losses":               r.get("losses", 0),
            "ot_losses":            r.get("otLosses", 0),
            "points":               r.get("points", 0),
            "goals_for":            r.get("goalsFor", 0),
            "goals_against":        r.get("goalsAgainst", 0),
            "goals_for_per_game":   r.get("goalsForPerGame", 0.0),
            "goals_against_per_game": r.get("goalsAgainstPerGame", 0.0),
            "pp_pct":               r.get("powerPlayPct", 0.0),
            "pk_pct":               r.get("penaltyKillPct", 0.0),
            "shots_for_per_game":   r.get("shotsForPerGame", 0.0),
            "shots_against_per_game": r.get("shotsAgainstPerGame", 0.0),
            "faceoff_win_pct":      r.get("faceoffWinPct", 0.0),
        })
    return rows


def run(seasons: list[str] | None = None):
    """Full teams ingestion pipeline."""
    _seasons = seasons or SEASONS
    LAKE_TEAMS.mkdir(parents=True, exist_ok=True)
    RAW_TEAMS.mkdir(parents=True, exist_ok=True)

    # The latest season is in progress: its standings/stats change daily, so the
    # raw cache for it must always be refreshed. Completed seasons never change,
    # so they stay cached (fast, and polite to the API).
    current_season = _seasons[-1]

    # 1. Team reference table
    # standings_now has abbrev but no teamId; stats API has teamId but no abbrev.
    # Fetch stats for the most recent season first to build a name→id lookup.
    _recent_stats = fetch_team_stats_for_season(current_season, force=True)
    _name_to_id = {r["team_name"]: r["team_id"] for r in _recent_stats if r.get("team_id")}

    teams = fetch_team_list()
    for t in teams:
        if not t["team_id"]:
            t["team_id"] = _name_to_id.get(t["full_name"])
    if teams:
        df = pd.DataFrame(teams)
        pq.write_table(pa.Table.from_pandas(df), LAKE_TEAMS / "teams.parquet")
        logger.info("Wrote teams.parquet (%d rows)", len(df))

    # 2. Standings per season
    season_dates = _fetch_standings_season_dates()
    all_standings = []
    for season in _seasons:
        end_date = season_dates.get(season)
        if not end_date:
            logger.warning("No standings end date found for season %s, skipping", season)
            continue
        logger.info("Fetching standings for %s (end date: %s)", season, end_date)
        all_standings.extend(
            fetch_standings_for_season(season, end_date, force=(season == current_season))
        )

    if all_standings:
        df = pd.DataFrame(all_standings)
        pq.write_table(
            pa.Table.from_pandas(df),
            LAKE_TEAMS / "standings.parquet",
        )
        logger.info("Wrote standings.parquet (%d rows)", len(df))

    # 3. Team stats per season
    all_stats = []
    for season in _seasons:
        logger.info("Fetching team stats for %s", season)
        all_stats.extend(fetch_team_stats_for_season(season, force=(season == current_season)))

    if all_stats:
        df = pd.DataFrame(all_stats)
        pq.write_table(
            pa.Table.from_pandas(df),
            LAKE_TEAMS / "team_stats.parquet",
        )
        logger.info("Wrote team_stats.parquet (%d rows)", len(df))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
