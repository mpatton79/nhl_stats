"""
Build the DuckDB database on top of the Parquet lake.

This script:
  1. Creates the DuckDB file at db/nhl.duckdb
  2. Registers each Parquet file (or directory) as a view
  3. Creates convenience views with pre-joined, enriched data
  4. Prints a summary of row counts

Run this after all ingest scripts have completed.
"""

import logging
from pathlib import Path

import duckdb

from config import DB_PATH, LAKE_DIR

logger = logging.getLogger(__name__)


def build_db(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    _register_raw_tables(con)
    _create_views(con)
    _print_summary(con)
    return con


def _parquet(relative_path: str) -> str:
    """Return a glob path for a parquet file or partitioned directory."""
    p = LAKE_DIR / relative_path
    if p.is_dir():
        return f"read_parquet('{p}/**/*.parquet', hive_partitioning=true)"
    return f"read_parquet('{p}')"


def _register_raw_tables(con: duckdb.DuckDBPyConnection):
    """Register base Parquet files as views."""
    tables = {
        "raw_teams":            "teams/teams.parquet",
        "raw_standings":        "teams/standings.parquet",
        "raw_team_stats":       "teams/team_stats.parquet",
        "raw_rosters":          "rosters/rosters.parquet",
        "raw_players":          "players/players.parquet",
        "raw_skater_stats":     "players/skater_stats.parquet",
        "raw_goalie_stats":     "players/goalie_stats.parquet",
        "raw_games":            "games/games.parquet",
        "raw_player_game_stats":"games/player_game_stats.parquet",
        "raw_plays":            "plays",
        "raw_team_skating_distance":      "edge_stats/team_skating_distance.parquet",
        "raw_team_skating_speed":         "edge_stats/team_skating_speed.parquet",
        "raw_team_zone_time":             "edge_stats/team_zone_time.parquet",
        "raw_team_shot_speed":            "edge_stats/team_shot_speed.parquet",
        "raw_team_shot_location_totals":  "edge_stats/team_shot_location_totals.parquet",
        "raw_team_shot_location_details":  "edge_stats/team_shot_location_details.parquet",
        "raw_skater_edge_stats":           "skater_edge_stats/skater_edge_stats.parquet",
        "raw_skater_sog_summary":          "skater_edge_stats/skater_sog_summary.parquet",
        "raw_skater_sog_details":          "skater_edge_stats/skater_sog_details.parquet",
    }

    for view_name, rel_path in tables.items():
        full = LAKE_DIR / rel_path
        if not full.exists():
            logger.warning("Skipping %s — %s not found", view_name, full)
            continue
        try:
            sql = f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM {_parquet(rel_path)}"
            con.execute(sql)
            logger.info("Registered view: %s", view_name)
        except Exception as e:
            logger.warning("Could not register %s: %s", view_name, e)


def _create_views(con: duckdb.DuckDBPyConnection):
    """Create enriched analytical views."""

    views = {}

    # ── Skater season stats enriched with player bio ──────────────────────────
    views["v_skater_stats"] = """
        SELECT
            s.season,
            s.player_id,
            p.first_name || ' ' || p.last_name AS player_name,
            p.birth_country,
            p.nationality,
            p.draft_year,
            p.draft_round,
            s.team_abbrev,
            s.position,
            s.games_played,
            s.goals,
            s.assists,
            s.points,
            s.plus_minus,
            s.pim,
            s.pp_goals,
            s.pp_points,
            s.sh_goals,
            s.gw_goals,
            s.shots,
            s.shooting_pct,
            s.toi_per_game,
            s.faceoff_win_pct,
            ROUND(s.goals::DOUBLE / NULLIF(s.games_played, 0), 3)   AS goals_per_game,
            ROUND(s.points::DOUBLE / NULLIF(s.games_played, 0), 3)  AS points_per_game
        FROM raw_skater_stats s
        LEFT JOIN raw_players p USING (player_id)
    """

    # ── Goalie season stats enriched with player bio ──────────────────────────
    views["v_goalie_stats"] = """
        SELECT
            g.season,
            g.player_id,
            p.first_name || ' ' || p.last_name AS player_name,
            p.birth_country,
            g.team_abbrev,
            g.games_played,
            g.games_started,
            g.wins,
            g.losses,
            g.ot_losses,
            g.goals_against,
            g.gaa,
            g.saves,
            g.save_pct,
            g.shutouts,
            g.toi
        FROM raw_goalie_stats g
        LEFT JOIN raw_players p USING (player_id)
    """

    # ── Game results ──────────────────────────────────────────────────────────
    views["v_games"] = """
        SELECT
            game_id,
            season,
            CASE game_type WHEN 2 THEN 'Regular' WHEN 3 THEN 'Playoffs' ELSE 'Other' END AS game_type,
            game_date::DATE AS game_date,
            venue,
            home_team,
            away_team,
            home_score,
            away_score,
            CASE
                WHEN home_score > away_score THEN home_team
                WHEN away_score > home_score THEN away_team
                ELSE 'TIE'
            END AS winner,
            ABS(home_score - away_score) AS goal_diff,
            period_type  -- OT, SO etc.
        FROM raw_games
        WHERE game_state IN ('OFF', 'FINAL')
    """

    # ── Standings enriched ────────────────────────────────────────────────────
    views["v_standings"] = """
        SELECT
            s.*,
            ROUND(s.points::DOUBLE / NULLIF(s.games_played * 2, 0), 3) AS points_pct,
            s.goals_for - s.goals_against AS goal_diff
        FROM raw_standings s
    """

    # ── Skater edge stats enriched with player bio ────────────────────────────
    views["v_skater_edge_stats"] = """
        SELECT
            stats.season,
            stats.player_id,
            player.last_name,
            player.first_name,
            stats.team_abbrev,
            stats.position,
            stats.games_played,
            stats.goals,
            stats.assists,
            stats.points,
            stats.top_shot_speed_imperial,
            stats.top_shot_speed_percentile,
            stats.max_skating_speed_imperial,
            stats.max_skating_speed_percentile,
            stats.total_distance_imperial,
            stats.total_distance_percentile
        FROM raw_skater_edge_stats stats
        LEFT JOIN raw_players player USING (player_id)
    """

    # ── Shot map (goals + shots on goal with coordinates) ────────────────────
    views["v_shots"] = """
        SELECT
            game_id, season, game_date, home_team, away_team,
            period, period_type, time_in_period,
            event_type,
            team_abbrev,
            x_coord, y_coord, zone_code, shot_type,
            shooting_player_id,
            scoring_player_id,
            goalie_player_id,
            home_score, away_score,
            situation_code, home_skaters, away_skaters
        FROM raw_plays
        WHERE event_type IN ('shot-on-goal', 'goal', 'missed-shot', 'blocked-shot')
    """

    # ── Scoring plays only ────────────────────────────────────────────────────
    views["v_goals"] = """
        SELECT
            g.game_id, g.season, g.game_date,
            g.period, g.period_type, g.time_in_period,
            g.team_abbrev,
            g.scoring_player_id,
            scorer.first_name || ' ' || scorer.last_name AS scorer_name,
            g.assist1_player_id,
            a1.first_name || ' ' || a1.last_name AS assist1_name,
            g.assist2_player_id,
            a2.first_name || ' ' || a2.last_name AS assist2_name,
            g.goalie_player_id,
            gl.first_name || ' ' || gl.last_name AS goalie_name,
            g.x_coord, g.y_coord, g.zone_code, g.shot_type,
            g.home_score, g.away_score,
            g.situation_code
        FROM raw_plays g
        LEFT JOIN raw_players scorer ON scorer.player_id = g.scoring_player_id
        LEFT JOIN raw_players a1     ON a1.player_id     = g.assist1_player_id
        LEFT JOIN raw_players a2     ON a2.player_id     = g.assist2_player_id
        LEFT JOIN raw_players gl     ON gl.player_id     = g.goalie_player_id
        WHERE g.event_type = 'goal'
    """

    for name, sql in views.items():
        try:
            con.execute(f"CREATE OR REPLACE VIEW {name} AS {sql}")
            logger.info("Created view: %s", name)
        except Exception as e:
            logger.warning("Could not create view %s: %s", name, e)


def _print_summary(con: duckdb.DuckDBPyConnection):
    tables = [
        ("raw_teams", "Teams"),
        ("raw_standings", "Standings rows"),
        ("raw_players", "Players"),
        ("raw_skater_stats", "Skater season rows"),
        ("raw_goalie_stats", "Goalie season rows"),
        ("raw_games", "Games"),
        ("raw_rosters", "Roster rows"),
        ("raw_plays", "Play events"),
    ]
    print("\n── NHL Data Lake Summary ─────────────────────────")
    for view, label in tables:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
            print(f"  {label:<30} {n:>10,}")
        except Exception:
            print(f"  {label:<30} {'(not loaded)':>10}")
    print("──────────────────────────────────────────────────\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    con = build_db()
    con.close()
    print(f"Database written to: {DB_PATH}")
