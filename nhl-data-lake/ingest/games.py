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


def fetch_season_schedule(team: str, season: str, force: bool = False) -> list[dict]:
    """Fetch every game for a team in a season."""
    url   = f"{NHL_WEB_API}/club-schedule-season/{team}/{season}"
    cache = RAW_GAMES / "schedules" / season / f"{team}.json"
    data  = fetch_and_cache(url, cache, force=force)
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


def _saves_shots(val) -> tuple[int | None, int | None]:
    """Split a goalie split like "14/15" (saves/shots) into (14, 15)."""
    try:
        saves, shots = str(val).split("/")
        return int(saves), int(shots)
    except (ValueError, AttributeError):
        return None, None


def parse_boxscore(game_id: int, season: str, data: dict) -> list[dict]:
    """Flatten player stats out of a boxscore response.

    Player stats live under playerByGameStats.{homeTeam,awayTeam}.{forwards,defense,goalies}.
    """
    rows = []
    if not data:
        return rows

    game_date = data.get("gameDate", "")
    by_side   = data.get("playerByGameStats", {})

    for side in ("homeTeam", "awayTeam"):
        abbr  = data.get(side, {}).get("abbrev", "")
        group = by_side.get(side, {})
        players = group.get("forwards", []) + group.get("defense", []) + group.get("goalies", [])
        for p in players:
            base = {
                "game_id":     game_id,
                "season":      season,
                "game_date":   game_date,
                "team_abbrev": abbr,
                "is_home":     side == "homeTeam",
                "player_id":   p.get("playerId"),
                "name":        p.get("name", {}).get("default", ""),
                "position":    p.get("position", ""),     # C/L/R, D, or G
                "toi":         p.get("toi", ""),
                "pim":         p.get("pim", 0),
            }
            if p.get("position") == "G":
                ev_saves, ev_shots = _saves_shots(p.get("evenStrengthShotsAgainst"))
                pp_saves, pp_shots = _saves_shots(p.get("powerPlayShotsAgainst"))
                sh_saves, sh_shots = _saves_shots(p.get("shorthandedShotsAgainst"))
                base.update({
                    "is_starter":         p.get("starter", False),
                    "decision":           p.get("decision"),   # W / L / O, or None if no decision
                    "shots_against":      p.get("shotsAgainst", 0),
                    "saves":              p.get("saves", 0),
                    "goals_against":      p.get("goalsAgainst", 0),
                    "save_pct":           p.get("savePctg"),
                    "even_shots_against": ev_shots,
                    "even_saves":         ev_saves,
                    "pp_shots_against":   pp_shots,
                    "pp_saves":           pp_saves,
                    "sh_shots_against":   sh_shots,
                    "sh_saves":           sh_saves,
                })
            else:
                base.update({
                    "goals":           p.get("goals", 0),
                    "assists":         p.get("assists", 0),
                    "points":          p.get("points", 0),
                    "plus_minus":      p.get("plusMinus", 0),
                    "shots":           p.get("sog", 0),
                    "hits":            p.get("hits", 0),
                    "blocked":         p.get("blockedShots", 0),
                    "pp_goals":        p.get("powerPlayGoals", 0),
                    "giveaways":       p.get("giveaways", 0),
                    "takeaways":       p.get("takeaways", 0),
                    "shifts":          p.get("shifts", 0),
                    "faceoff_win_pct": p.get("faceoffWinningPctg"),
                })
            rows.append(base)
    return rows


def run(with_boxscores: bool = True, seasons: list[str] | None = None):
    """
    Ingest game schedules for all seasons.
    If with_boxscores=True, also fetch per-game player stats.
    """
    _seasons = seasons or SEASONS
    LAKE_GAMES.mkdir(parents=True, exist_ok=True)
    (RAW_GAMES / "schedules").mkdir(parents=True, exist_ok=True)
    (RAW_GAMES / "boxscores").mkdir(parents=True, exist_ok=True)

    # ── 1. Schedules ──────────────────────────────────────────────────────────
    # The current season is in progress: scores and game states change daily, so
    # always re-pull it. Completed seasons never change and stay cached.
    current_season = SEASONS[-1]
    all_games: dict[int, dict] = {}
    for season in _seasons:
        for team in ALL_TEAMS:
            logger.info("Schedule %s %s", team, season)
            for g in fetch_season_schedule(team, season, force=(season == current_season)):
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
