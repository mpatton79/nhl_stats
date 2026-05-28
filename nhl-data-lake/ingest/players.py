"""
Ingest player career stats, season summaries, and profiles.

Endpoints:
  GET /stats/rest/en/skater/summary          — skater season stats
  GET /stats/rest/en/goalie/summary          — goalie season stats
  GET /v1/player/{player_id}/landing         — player profile + career stats
"""

import logging

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import NHL_WEB_API, NHL_STATS_API, SEASONS, RAW_DIR, LAKE_DIR
from ingest.http_client import fetch_and_cache, get_json

logger = logging.getLogger(__name__)

RAW_PLAYERS  = RAW_DIR  / "players"
LAKE_PLAYERS = LAKE_DIR / "players"


# ── Skater season stats ───────────────────────────────────────────────────────

def fetch_skater_stats(season: str) -> list[dict]:
    """Fetch all skater summary stats for a season (regular season)."""
    url    = f"{NHL_STATS_API}/skater/summary"
    cache  = RAW_PLAYERS / f"skaters_{season}.json"
    params = {
        "cayenneExp": f"seasonId={season} and gameTypeId=2",
        "limit":      -1,
        "sort":       "points",
        "dir":        "DESC",
    }
    data = fetch_and_cache(url, cache, params=params)
    if not data:
        return []

    rows = []
    for r in data.get("data", []):
        rows.append({
            "season":               season,
            "player_id":            r.get("playerId"),
            "player_name":          r.get("skaterFullName", ""),
            "team_abbrev":          r.get("teamAbbrevs", ""),
            "position":             r.get("positionCode", ""),
            "games_played":         r.get("gamesPlayed", 0),
            "goals":                r.get("goals", 0),
            "assists":              r.get("assists", 0),
            "points":               r.get("points", 0),
            "plus_minus":           r.get("plusMinus", 0),
            "pim":                  r.get("penaltyMinutes", 0),
            "pp_goals":             r.get("ppGoals", 0),
            "pp_points":            r.get("ppPoints", 0),
            "sh_goals":             r.get("shGoals", 0),
            "sh_points":            r.get("shPoints", 0),
            "gw_goals":             r.get("gameWinningGoals", 0),
            "ot_goals":             r.get("otGoals", 0),
            "shots":                r.get("shots", 0),
            "shooting_pct":         r.get("shootingPct", 0.0),
            "toi_per_game":         r.get("timeOnIcePerGame", ""),
            "faceoff_win_pct":      r.get("faceoffWinPct", 0.0),
        })
    return rows


# ── Goalie season stats ───────────────────────────────────────────────────────

def fetch_goalie_stats(season: str) -> list[dict]:
    """Fetch all goalie summary stats for a season."""
    url    = f"{NHL_STATS_API}/goalie/summary"
    cache  = RAW_PLAYERS / f"goalies_{season}.json"
    params = {
        "cayenneExp": f"seasonId={season} and gameTypeId=2",
        "limit":      -1,
        "sort":       "wins",
        "dir":        "DESC",
    }
    data = fetch_and_cache(url, cache, params=params)
    if not data:
        return []

    rows = []
    for r in data.get("data", []):
        rows.append({
            "season":            season,
            "player_id":         r.get("playerId"),
            "player_name":       r.get("goalieFullName", ""),
            "team_abbrev":       r.get("teamAbbrevs", ""),
            "games_played":      r.get("gamesPlayed", 0),
            "games_started":     r.get("gamesStarted", 0),
            "wins":              r.get("wins", 0),
            "losses":            r.get("losses", 0),
            "ot_losses":         r.get("otLosses", 0),
            "goals_against":     r.get("goalsAgainst", 0),
            "gaa":               r.get("goalsAgainstAverage", 0.0),
            "shots_against":     r.get("shotsAgainst", 0),
            "saves":             r.get("saves", 0),
            "save_pct":          r.get("savePct", 0.0),
            "shutouts":          r.get("shutouts", 0),
            "toi":               r.get("timeOnIce", ""),
        })
    return rows


# ── Player profiles ───────────────────────────────────────────────────────────

def fetch_player_profile(player_id: int) -> dict | None:
    """Fetch a player's profile page (bio + career stats)."""
    url   = f"{NHL_WEB_API}/player/{player_id}/landing"
    cache = RAW_PLAYERS / "profiles" / f"{player_id}.json"
    return fetch_and_cache(url, cache)


def build_player_index(skater_rows: list[dict], goalie_rows: list[dict]) -> list[dict]:
    """Extract unique player IDs from ingested stats."""
    seen, players = set(), []
    for r in skater_rows + goalie_rows:
        pid = r.get("player_id")
        if pid and pid not in seen:
            seen.add(pid)
            players.append({"player_id": pid, "player_name": r.get("player_name", "")})
    return players


def run():
    RAW_PLAYERS.mkdir(parents=True, exist_ok=True)
    (RAW_PLAYERS / "profiles").mkdir(parents=True, exist_ok=True)
    LAKE_PLAYERS.mkdir(parents=True, exist_ok=True)

    all_skaters, all_goalies = [], []

    for season in SEASONS:
        logger.info("Skater stats %s", season)
        rows = fetch_skater_stats(season)
        all_skaters.extend(rows)

        logger.info("Goalie stats %s", season)
        rows = fetch_goalie_stats(season)
        all_goalies.extend(rows)

    if all_skaters:
        df = pd.DataFrame(all_skaters)
        pq.write_table(pa.Table.from_pandas(df), LAKE_PLAYERS / "skater_stats.parquet")
        logger.info("Wrote skater_stats.parquet (%d rows)", len(df))

    if all_goalies:
        df = pd.DataFrame(all_goalies)
        pq.write_table(pa.Table.from_pandas(df), LAKE_PLAYERS / "goalie_stats.parquet")
        logger.info("Wrote goalie_stats.parquet (%d rows)", len(df))

    # ── Player profiles ───────────────────────────────────────────────────────
    player_index = build_player_index(all_skaters, all_goalies)
    logger.info("Fetching profiles for %d unique players", len(player_index))

    profiles = []
    for p in player_index:
        pid  = p["player_id"]
        data = fetch_player_profile(pid)
        if not data:
            continue
        profiles.append({
            "player_id":        pid,
            "first_name":       data.get("firstName", {}).get("default", ""),
            "last_name":        data.get("lastName", {}).get("default", ""),
            "jersey_number":    data.get("sweaterNumber"),
            "position":         data.get("position", ""),
            "shoots_catches":   data.get("shootsCatches", ""),
            "height_inches":    data.get("heightInInches"),
            "weight_lbs":       data.get("weightInPounds"),
            "birth_date":       data.get("birthDate", ""),
            "birth_city":       data.get("birthCity", {}).get("default", ""),
            "birth_country":    data.get("birthCountry", ""),
            "nationality":      data.get("nationality", ""),
            "draft_year":       data.get("draftDetails", {}).get("year"),
            "draft_round":      data.get("draftDetails", {}).get("round"),
            "draft_pick":       data.get("draftDetails", {}).get("pickInRound"),
            "draft_team":       data.get("draftDetails", {}).get("teamAbbrev", ""),
            "headshot_url":     data.get("headshot", ""),
            "active":           data.get("isActive", False),
        })

    if profiles:
        df = pd.DataFrame(profiles).drop_duplicates("player_id")
        pq.write_table(pa.Table.from_pandas(df), LAKE_PLAYERS / "players.parquet")
        logger.info("Wrote players.parquet (%d rows)", len(df))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
