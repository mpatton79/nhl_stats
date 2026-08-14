"""
Ingest play-by-play event data for all finished games.

Endpoint:
  GET /v1/gamecenter/{game_id}/play-by-play

Each game produces ~200-500 events covering: goals, shots, penalties,
faceoffs, hits, blocked shots, giveaways, takeaways, stoppages, period ends.

NOTE: This is the heaviest ingest step — one API call per game.
      For 10 seasons (~13,000 games) expect 1-2 hours at the polite rate limit.
      Raw JSON is cached so re-runs are instant.
"""

import logging

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import NHL_WEB_API, RAW_DIR, LAKE_DIR
from ingest.http_client import fetch_and_cache

logger = logging.getLogger(__name__)

RAW_PLAYS  = RAW_DIR  / "plays"
LAKE_PLAYS = LAKE_DIR / "plays"

# Event types we care about (others like PERIOD_START, STOPPAGE are noise)
TRACKED_EVENTS = {
    "shot-on-goal", "goal", "missed-shot", "blocked-shot",
    "penalty", "hit", "faceoff", "giveaway", "takeaway",
}


def _safe_coord(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None

def _safe_team_abbrev(val) -> int:
    if val == '':
        return -1
    else:
        return val


def parse_plays(game_id: int, season: str, data: dict) -> list[dict]:
    rows = []
    if not data:
        return rows

    home = data.get("homeTeam", {}).get("abbrev", "")
    away = data.get("awayTeam", {}).get("abbrev", "")
    game_date = data.get("gameDate", "")

    for play in data.get("plays", []):
        type_code = play.get("typeDescKey", "")
        if type_code not in TRACKED_EVENTS:
            continue

        details  = play.get("details", {}) or {}
        pd_desc  = play.get("periodDescriptor", {}) or {}
        situation = play.get("situationCode", "")

        row = {
            "game_id":        game_id,
            "season":         season,
            "game_date":      game_date,
            "home_team":      home,
            "away_team":      away,
            "event_id":       play.get("eventId"),
            "period":         pd_desc.get("number"),
            "period_type":    pd_desc.get("periodType", ""),
            "time_in_period": play.get("timeInPeriod", ""),
            "time_remaining": play.get("timeRemaining", ""),
            "event_type":     type_code,
            "team_abbrev":    _safe_team_abbrev(details.get("eventOwnerTeamId", "")),   # may be ID; enriched below
            "x_coord":        _safe_coord(details.get("xCoord")),
            "y_coord":        _safe_coord(details.get("yCoord")),
            "zone_code":      details.get("zoneCode", ""),           # O, N, D
            "shot_type":      details.get("shotType", ""),
            "scoring_player_id":   details.get("scoringPlayerId"),
            "assist1_player_id":   details.get("assist1PlayerId"),
            "assist2_player_id":   details.get("assist2PlayerId"),
            "goalie_player_id":    details.get("goalieInNetId"),
            "shooting_player_id":  details.get("shootingPlayerId"),
            "blocking_player_id":  details.get("blockingPlayerId"),
            "hitter_player_id":    details.get("hittingPlayerId"),
            "hittee_player_id":    details.get("hitteePlayerId"),
            "winning_player_id":   details.get("winningPlayerId"),
            "losing_player_id":    details.get("losingPlayerId"),
            "committed_by_player_id":  details.get("committedByPlayerId"),
            "drawn_by_player_id":      details.get("drawnByPlayerId"),
            "penalty_type":    details.get("typeCode", ""),
            "penalty_minutes": details.get("duration"),
            "home_score":      details.get("homeScore"),
            "away_score":      details.get("awayScore"),
            "situation_code":  situation,
            # Strength: parse from situationCode (e.g. 1551 = 5v5, 1541 = 5v4 PP)
            "home_skaters":    int(situation[1]) if situation and len(situation) >= 2 else None,
            "away_skaters":    int(situation[2]) if situation and len(situation) >= 3 else None,
        }
        rows.append(row)
    return rows


def run(game_ids_and_seasons: list[tuple[int, str]] | None = None, seasons: list[str] | None = None):
    """
    Ingest play-by-play for the provided games.

    If game_ids_and_seasons is None, reads the games.parquet to get all
    finished game IDs automatically. Pass seasons to restrict to specific seasons.
    """
    RAW_PLAYS.mkdir(parents=True, exist_ok=True)
    LAKE_PLAYS.mkdir(parents=True, exist_ok=True)

    if game_ids_and_seasons is None:
        games_parquet = LAKE_DIR / "games" / "games.parquet"
        if not games_parquet.exists():
            logger.error("games.parquet not found — run ingest/games.py first")
            return
        df_games = pd.read_parquet(games_parquet)
        finished = df_games[df_games["game_state"].isin(["OFF", "FINAL"])]
        if seasons:
            finished = finished[finished["season"].isin(seasons)]
        game_ids_and_seasons = list(zip(finished["game_id"], finished["season"]))

    logger.info("Fetching play-by-play for %d games", len(game_ids_and_seasons))

    all_plays = []
    for game_id, season in game_ids_and_seasons:
        url   = f"{NHL_WEB_API}/gamecenter/{game_id}/play-by-play"
        cache = RAW_PLAYS / season / f"{game_id}.json"
        data  = fetch_and_cache(url, cache)
        if data:
            all_plays.extend(parse_plays(game_id, season, data))

    if all_plays:
        df = pd.DataFrame(all_plays)
        # Partition by season for faster querying
        for season, grp in df.groupby("season"):
            out = LAKE_PLAYS / f"season={season}"
            out.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pandas(grp), out / "plays.parquet")
            logger.info("Wrote plays season=%s (%d rows)", season, len(grp))

    logger.info("Play-by-play ingest complete — %d total events", len(all_plays))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
