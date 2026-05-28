"""
Ingest game schedule + results for each season.

Endpoints:
  GET /v1/schedule/{date}                    — day schedule (used to walk season)
  GET /v1/club-schedule-season/{team}/{season} — full team season schedule
  GET /v1/gamecenter/{game_id}/boxscore       — boxscore per game
"""

import logging
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import NHL_WEB_API, SEASONS, RAW_DIR, LAKE_DIR
from ingest.http_client import fetch_and_cache, get_json
from ingest.rosters import ALL_TEAMS

logger = logging.getLogger(__name__)

RAW_GAMES  = RAW_DIR  / "games"
LAKE_GAMES = LAKE_DIR / "games"


def fetch_season_schedule(team: str, season: str) -> list[dict]:
    """Fetch every game for a team in a season."""
    url   = f"{NHL_WEB_API}/club-schedule-season/{team}/{season}"
    cache = RAW_GAMES / "schedules" / season / f"{team}.json"
    data  = fetch_and_cache(url, cache)
    if not data:
        return []

    rows = []
    for g in data.get("games", []):
        rows.append({
            "game_id":       g.get("id"),
            "season":        season,
            "game_type":     g.get("gameType"),       # 2=regular, 3=playoffs
            "game_date":     g.get("gameDate", ""),
            "start_time_utc": g.get("startTimeUTC", ""),
            "venue":         g.get("venue", {}).get("default", ""),
            "home_team":     g.get("homeTeam", {}).get("abbrev", ""),
            "away_team":     g.get("awayTeam", {}).get("abbrev", ""),
            "home_score":    g.get("homeTeam", {}).get("score"),
            "away_score":    g.get("awayTeam", {}).get("score"),
            "game_state":    g.get("gameState", ""),   # OFF = final
            "period":        g.get("periodDescriptor", {}).get("number"),
            "period_type":   g.get("periodDescriptor", {}).get("periodType", ""),
        })
    return rows


def fetch_boxscore(game_id: int, season: str) -> dict | None:
    """Fetch the full boxscore for a single game."""
    url   = f"{NHL_WEB_API}/gamecenter/{game_id}/boxscore"
    cache = RAW_GAMES / "boxscores" / season / f"{game_id}.json"
    return fetch_and_cache(url, cache)


def parse_boxscore(game_id: int, season: str, data: dict) -> list[dict]:
    """Flatten player stats out of a boxscore response."""
    rows = []
    if not data:
        return rows

    game_date = data.get("gameDate", "")
    home_abbr = data.get("homeTeam", {}).get("abbrev", "")
    away_abbr = data.get("awayTeam", {}).get("abbrev", "")

    for side, abbr in [("homeTeam", home_abbr), ("awayTeam", away_abbr)]:
        team_data = data.get(side, {})
        players   = team_data.get("skaters", []) + team_data.get("goalies", [])
        for p in players:
            base = {
                "game_id":     game_id,
                "season":      season,
                "game_date":   game_date,
                "team_abbrev": abbr,
                "player_id":   p.get("playerId") or p.get("id"),
                "name":        p.get("name", {}).get("default", ""),
                "position":    p.get("position", ""),
                "is_starter":  p.get("starter", False),
                "toi":         p.get("toi", ""),
            }
            if p.get("position") == "G":
                base.update({
                    "shots_against": p.get("shotsAgainst", 0),
                    "saves":         p.get("saves", 0),
                    "goals_against": p.get("goalsAgainst", 0),
                    "save_pct":      p.get("savePctg", 0.0),
                    "even_shots_against":  p.get("evenShotsAgainst", 0),
                    "even_saves":          p.get("evenSaves", 0),
                    "pp_shots_against":    p.get("powerPlayShotsAgainst", 0),
                    "pp_saves":            p.get("powerPlaySaves", 0),
                })
            else:
                base.update({
                    "goals":      p.get("goals", 0),
                    "assists":    p.get("assists", 0),
                    "points":     p.get("points", 0),
                    "plus_minus": p.get("plusMinus", 0),
                    "pim":        p.get("pim", 0),
                    "shots":      p.get("shots", 0),
                    "hits":       p.get("hits", 0),
                    "blocked":    p.get("blockedShots", 0),
                    "pp_goals":   p.get("powerPlayGoals", 0),
                    "pp_points":  p.get("powerPlayPoints", 0),
                    "sh_goals":   p.get("shorthandedGoals", 0),
                    "faceoff_wins":   p.get("faceoffWins", 0),
                    "faceoff_taken":  p.get("faceoffTaken", 0),
                })
            rows.append(base)
    return rows


def run(with_boxscores: bool = True):
    """
    Ingest game schedules for all seasons.
    If with_boxscores=True, also fetch per-game player stats.
    """
    LAKE_GAMES.mkdir(parents=True, exist_ok=True)
    (RAW_GAMES / "schedules").mkdir(parents=True, exist_ok=True)
    (RAW_GAMES / "boxscores").mkdir(parents=True, exist_ok=True)

    # ── 1. Schedules ──────────────────────────────────────────────────────────
    all_games: dict[int, dict] = {}
    for season in SEASONS:
        for team in ALL_TEAMS:
            logger.info("Schedule %s %s", team, season)
            for g in fetch_season_schedule(team, season):
                all_games[g["game_id"]] = g  # deduplicate by game_id

    if all_games:
        df = pd.DataFrame(list(all_games.values()))
        pq.write_table(
            pa.Table.from_pandas(df),
            LAKE_GAMES / "games.parquet",
        )
        logger.info("Wrote games.parquet (%d rows)", len(df))

    if not with_boxscores:
        return

    # ── 2. Boxscores ──────────────────────────────────────────────────────────
    finished_games = [
        g for g in all_games.values()
        if g.get("game_state") in ("OFF", "FINAL")
    ]
    logger.info("Fetching boxscores for %d finished games", len(finished_games))

    all_player_stats = []
    for g in finished_games:
        gid    = g["game_id"]
        season = g["season"]
        data   = fetch_boxscore(gid, season)
        if data:
            all_player_stats.extend(parse_boxscore(gid, season, data))

    if all_player_stats:
        df = pd.DataFrame(all_player_stats)
        pq.write_table(
            pa.Table.from_pandas(df),
            LAKE_GAMES / "player_game_stats.parquet",
        )
        logger.info("Wrote player_game_stats.parquet (%d rows)", len(df))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
