-- ═══════════════════════════════════════════════════════════════
--  NHL Data Lake — Example DuckDB Queries
--  Run with:  duckdb db/nhl.duckdb  then paste any query below
--             or in Python:  con = duckdb.connect("db/nhl.duckdb")
-- ═══════════════════════════════════════════════════════════════


-- ── Points leaders per season ─────────────────────────────────
SELECT season, player_name, team_abbrev, position,
       games_played, goals, assists, points, points_per_game
FROM v_skater_stats
WHERE season = '20232024'
ORDER BY points DESC
LIMIT 20;


-- ── Points leaders across ALL 10 seasons (career totals) ──────
SELECT
    player_id,
    player_name,
    SUM(games_played) AS gp,
    SUM(goals)        AS g,
    SUM(assists)      AS a,
    SUM(points)       AS pts,
    ROUND(SUM(points)::DOUBLE / SUM(games_played), 3) AS pts_per_gp
FROM v_skater_stats
GROUP BY player_id, player_name
HAVING SUM(games_played) >= 200
ORDER BY pts DESC
LIMIT 20;


-- ── Best save percentages (min 30 games) ──────────────────────
SELECT season, player_name, team_abbrev,
       games_played, wins, losses, gaa, save_pct, shutouts
FROM v_goalie_stats
WHERE games_played >= 30
ORDER BY save_pct DESC
LIMIT 20;


-- ── Team records per season ────────────────────────────────────
SELECT season, team_abbrev, team_name,
       wins, losses, ot_losses, points, points_pct,
       goals_for, goals_against, goal_diff
FROM v_standings
WHERE season = '20232024'
ORDER BY points DESC;


-- ── Head-to-head record between two teams ─────────────────────
SELECT
    CASE WHEN home_team = 'TOR' THEN 'TOR' ELSE 'BOS' END AS team,
    COUNT(*) FILTER (WHERE winner = 'TOR' AND (home_team='TOR' OR away_team='TOR')) AS tor_wins,
    COUNT(*) FILTER (WHERE winner = 'BOS' AND (home_team='BOS' OR away_team='BOS')) AS bos_wins
FROM v_games
WHERE (home_team = 'TOR' AND away_team = 'BOS')
   OR (home_team = 'BOS' AND away_team = 'TOR')
GROUP BY 1;


-- ── Overtime / shootout game frequency by season ─────────────
SELECT season,
       COUNT(*) AS total_games,
       COUNT(*) FILTER (WHERE period_type = 'OT') AS ot_games,
       COUNT(*) FILTER (WHERE period_type = 'SO') AS so_games,
       ROUND(COUNT(*) FILTER (WHERE period_type IN ('OT','SO'))::DOUBLE / COUNT(*) * 100, 1) AS pct_extra_time
FROM v_games
GROUP BY season
ORDER BY season;


-- ── Shot heatmap data — where are goals scored from? ──────────
SELECT
    ROUND(x_coord / 5) * 5 AS x_bucket,
    ROUND(y_coord / 5) * 5 AS y_bucket,
    COUNT(*) AS goals
FROM v_goals
WHERE x_coord IS NOT NULL AND y_coord IS NOT NULL
  AND season = '20232024'
GROUP BY 1, 2
ORDER BY goals DESC;


-- ── Top snipers: goals per shot attempt ───────────────────────
SELECT player_name, team_abbrev, season,
       goals, shots, shooting_pct
FROM v_skater_stats
WHERE games_played >= 50 AND shots >= 100
ORDER BY shooting_pct DESC
LIMIT 20;


-- ── Penalty minutes leaders ───────────────────────────────────
SELECT player_name, team_abbrev,
       SUM(games_played) AS gp,
       SUM(pim) AS total_pim,
       ROUND(SUM(pim)::DOUBLE / SUM(games_played), 2) AS pim_per_game
FROM v_skater_stats
GROUP BY player_name, team_abbrev
HAVING SUM(games_played) >= 100
ORDER BY total_pim DESC
LIMIT 20;


-- ── Player nationality breakdown ──────────────────────────────
SELECT birth_country,
       COUNT(DISTINCT player_id) AS players
FROM v_skater_stats
GROUP BY birth_country
ORDER BY players DESC;


-- ── Team scoring depth: how many players scored 20+ goals? ───
SELECT season, team_abbrev,
       COUNT(*) AS players_with_20_plus_goals
FROM v_skater_stats
WHERE goals >= 20
GROUP BY season, team_abbrev
ORDER BY season, players_with_20_plus_goals DESC;


-- ── Draft success: points per pick round ─────────────────────
SELECT
    p.draft_round,
    COUNT(DISTINCT s.player_id) AS players,
    ROUND(AVG(s.points), 1) AS avg_pts_per_season,
    MAX(s.points) AS best_season
FROM v_skater_stats s
JOIN raw_players p USING (player_id)
WHERE p.draft_round IS NOT NULL
  AND s.games_played >= 40
GROUP BY p.draft_round
ORDER BY p.draft_round;
