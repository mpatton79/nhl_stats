"""
Ingest NHL Edge per-skater stats via the CAT skater detail endpoint.

Endpoint:
  GET /v1/cat/edge/skater-detail/{player-id}/{season}/{game-type}

Produces 3 parquet files:
  skater_edge_stats.parquet    — one row per player/season (flat metrics)
  skater_sog_summary.parquet   — long by player/season/location_code
  skater_sog_details.parquet   — long by player/season/shot area

Player IDs are read from skater_stats.parquet (already ingested).
Edge stats are only available from ~2019-20 onward.
"""

import logging

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import NHL_WEB_API, SEASONS, RAW_DIR, LAKE_DIR
from ingest.http_client import fetch_and_cache

logger = logging.getLogger(__name__)

RAW_DIR_SKATER  = RAW_DIR  / "skater_edge_stats"
LAKE_DIR_SKATER = LAKE_DIR / "skater_edge_stats"

GAME_TYPE = 2
EDGE_STATS_FIRST_SEASON = "20212022"  # edge stats not available before this


def _load_player_ids_by_season(seasons: list[str]) -> dict[str, list[int]]:
    """Return {season: [player_id, ...]} using skater_stats.parquet where available,
    falling back to rosters.parquet (non-goalies) for any uncovered seasons."""
    result: dict[str, list[int]] = {}

    # Primary: skater_stats has exact per-season player lists
    skater_parquet = LAKE_DIR / "players" / "skater_stats.parquet"
    if skater_parquet.exists():
        df = pd.read_parquet(skater_parquet, columns=["season", "player_id"])
        df = df[df["season"].isin(seasons)].dropna(subset=["player_id"])
        for season, grp in df.groupby("season"):
            result[season] = grp["player_id"].astype(int).tolist()

    # Fallback: rosters covers all seasons and runs before this step
    missing = [s for s in seasons if s not in result]
    if missing:
        roster_parquet = LAKE_DIR / "rosters" / "rosters.parquet"
        if roster_parquet.exists():
            df = pd.read_parquet(roster_parquet, columns=["season", "player_id", "position_type"])
            df = df[df["season"].isin(missing) & (df["position_type"] != "G")]
            df = df.dropna(subset=["player_id"])
            for season, grp in df.groupby("season"):
                result[season] = grp["player_id"].astype(int).unique().tolist()
                logger.info("Season %s: using roster fallback (%d players)", season, len(result[season]))
        else:
            logger.warning("rosters.parquet not found — skipping seasons: %s", missing)

    return result


def fetch_skater_edge(player_id: int, season: str) -> dict | None:
    url   = f"{NHL_WEB_API}/cat/edge/skater-detail/{player_id}/{season}/{GAME_TYPE}"
    cache = RAW_DIR_SKATER / season / f"{player_id}.json"
    return fetch_and_cache(url, cache)


def parse_skater_edge(player_id: int, season: str, data: dict) -> dict:
    p   = data.get("player", {})
    ss  = data.get("skatingSpeed", {})
    zt  = data.get("zoneTimeDetails", {})
    td  = data.get("totalDistanceSkated", {})
    tss = data.get("topShotSpeed", {})

    return {
        "season":                         season,
        "player_id":                      player_id,
        "team_abbrev":                    p.get("team", {}).get("abbrev"),
        "position":                       p.get("position"),
        "games_played":                   p.get("gamesPlayed"),
        "goals":                          p.get("goals"),
        "assists":                        p.get("assists"),
        "points":                         p.get("points"),
        # shot speed
        "top_shot_speed_imperial":        tss.get("imperial"),
        "top_shot_speed_percentile":      tss.get("percentile"),
        "top_shot_speed_league_avg":      tss.get("leagueAvg", {}).get("imperial"),
        # skating speed
        "max_skating_speed_imperial":     ss.get("speedMax", {}).get("imperial"),
        "max_skating_speed_percentile":   ss.get("speedMax", {}).get("percentile"),
        "max_skating_speed_league_avg":   ss.get("speedMax", {}).get("leagueAvg", {}).get("imperial"),
        "bursts_over_20":                 ss.get("burstsOver20", {}).get("value"),
        "bursts_over_20_percentile":      ss.get("burstsOver20", {}).get("percentile"),
        "bursts_over_20_league_avg":      ss.get("burstsOver20", {}).get("leagueAvg", {}).get("value"),
        # skating distance
        "total_distance_imperial":        td.get("imperial"),
        "total_distance_percentile":      td.get("percentile"),
        "total_distance_league_avg":      td.get("leagueAvg", {}).get("imperial"),
        # zone time
        "offensive_zone_pctg":            zt.get("offensiveZonePctg"),
        "offensive_zone_percentile":      zt.get("offensiveZonePercentile"),
        "offensive_zone_league_avg":      zt.get("offensiveZoneLeagueAvg"),
        "neutral_zone_pctg":              zt.get("neutralZonePctg"),
        "neutral_zone_percentile":        zt.get("neutralZonePercentile"),
        "neutral_zone_league_avg":        zt.get("neutralZoneLeagueAvg"),
        "defensive_zone_pctg":            zt.get("defensiveZonePctg"),
        "defensive_zone_percentile":      zt.get("defensiveZonePercentile"),
        "defensive_zone_league_avg":      zt.get("defensiveZoneLeagueAvg"),
    }


def parse_sog_summary(player_id: int, season: str, data: dict) -> list[dict]:
    rows = []
    for r in data.get("sogSummary", []):
        rows.append({
            "season":                    season,
            "player_id":                 player_id,
            "location_code":             r.get("locationCode"),
            "shots":                     r.get("shots"),
            "shots_percentile":          r.get("shotsPercentile"),
            "shots_league_avg":          r.get("shotsLeagueAvg"),
            "goals":                     r.get("goals"),
            "goals_percentile":          r.get("goalsPercentile"),
            "goals_league_avg":          r.get("goalsLeagueAvg"),
            "shooting_pctg":             r.get("shootingPctg"),
            "shooting_pctg_percentile":  r.get("shootingPctgPercentile"),
            "shooting_pctg_league_avg":  r.get("shootingPctgLeagueAvg"),
        })
    return rows


def parse_sog_details(player_id: int, season: str, data: dict) -> list[dict]:
    rows = []
    for r in data.get("sogDetails", []):
        rows.append({
            "season":           season,
            "player_id":        player_id,
            "area":             r.get("area"),
            "shots":            r.get("shots"),
            "shots_percentile": r.get("shotsPercentile"),
        })
    return rows


def run(seasons: list[str] | None = None):
    _seasons = [s for s in (seasons or SEASONS) if s >= EDGE_STATS_FIRST_SEASON]
    RAW_DIR_SKATER.mkdir(parents=True, exist_ok=True)
    LAKE_DIR_SKATER.mkdir(parents=True, exist_ok=True)

    players_by_season = _load_player_ids_by_season(_seasons)
    if not players_by_season:
        return

    all_stats, all_sog_summary, all_sog_details = [], [], []

    for season in _seasons:
        player_ids = players_by_season.get(season, [])
        logger.info("Skater edge stats — %s (%d players)", season, len(player_ids))
        for player_id in player_ids:
            data = fetch_skater_edge(player_id, season)
            if not data:
                continue
            all_stats.append(parse_skater_edge(player_id, season, data))
            all_sog_summary.extend(parse_sog_summary(player_id, season, data))
            all_sog_details.extend(parse_sog_details(player_id, season, data))

    for rows, filename in [
        (all_stats,       "skater_edge_stats.parquet"),
        (all_sog_summary, "skater_sog_summary.parquet"),
        (all_sog_details, "skater_sog_details.parquet"),
    ]:
        if rows:
            df = pd.DataFrame(rows)
            pq.write_table(pa.Table.from_pandas(df), LAKE_DIR_SKATER / filename)
            logger.info("Wrote %s (%d rows)", filename, len(df))
        else:
            logger.info("No data collected for %s", filename)


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
