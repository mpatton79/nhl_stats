# 🏒 NHL Data Lake

A local data lake of NHL statistics built on the free, unofficial NHL API.  
Data is stored as **Parquet files** and queried with **DuckDB** — no server required.

---

## What's collected

| Dataset | Source Endpoint | Coverage |
|---|---|---|
| Teams & standings | `/v1/standings/*` | 10 seasons |
| Team stats | `/stats/rest/en/team/summary` | 10 seasons |
| Rosters | `/v1/roster/{team}/{season}` | 10 seasons × 32 teams |
| Player profiles | `/v1/player/{id}/landing` | All active players |
| Skater stats | `/stats/rest/en/skater/summary` | 10 seasons |
| Goalie stats | `/stats/rest/en/goalie/summary` | 10 seasons |
| Game results | `/v1/club-schedule-season/{team}/{season}` | 10 seasons |
| Per-game player stats | `/v1/gamecenter/{id}/boxscore` | All finished games |
| Play-by-play events | `/v1/gamecenter/{id}/play-by-play` | All finished games |

---

## Project layout

```
nhl-data-lake/
├── config.py                  # Seasons, base URLs, paths
├── run_pipeline.py            # Master runner
├── requirements.txt
│
├── ingest/
│   ├── http_client.py         # Shared HTTP + caching
│   ├── teams.py               # Teams, standings, team stats
│   ├── rosters.py             # Rosters per team/season
│   ├── players.py             # Skater/goalie stats + profiles
│   ├── games.py               # Schedules + boxscores
│   └── plays.py               # Play-by-play events
│
├── data/
│   ├── raw/                   # Cached raw JSON (never deleted)
│   │   ├── games/
│   │   ├── players/
│   │   ├── plays/
│   │   ├── rosters/
│   │   └── teams/
│   └── lake/                  # Cleaned Parquet files
│       ├── games/
│       │   ├── games.parquet
│       │   └── player_game_stats.parquet
│       ├── players/
│       │   ├── players.parquet
│       │   ├── skater_stats.parquet
│       │   └── goalie_stats.parquet
│       ├── plays/
│       │   ├── season=20142015/plays.parquet
│       │   └── ...            # Hive-partitioned by season
│       ├── rosters/
│       │   └── rosters.parquet
│       └── teams/
│           ├── teams.parquet
│           ├── standings.parquet
│           └── team_stats.parquet
│
├── db/
│   ├── build_db.py            # Creates nhl.duckdb with views
│   └── nhl.duckdb             # Generated — query this
│
└── queries/
    └── examples.sql           # Ready-to-run analytical queries
```

---

## Quick start

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Run the pipeline

```bash
# Full run (all data, all seasons) — takes 1-2 hours for play-by-play
python run_pipeline.py

# Faster first run — skip play-by-play (~5-10 minutes)
python run_pipeline.py --skip-plays

# Run a single step
python run_pipeline.py --only teams
python run_pipeline.py --only players

# Resume from a specific step
python run_pipeline.py --from-step plays

# Ingest a single season only
python run_pipeline.py --season 20252026

# Single season, single step
python run_pipeline.py --only games --season 20252026
```

### 3. Query the data

**Interactive SQL shell:**
```bash
duckdb db/nhl.duckdb
```

**Python:**
```python
import duckdb

con = duckdb.connect("db/nhl.duckdb")

# Top scorers 2023-24
df = con.execute("""
    SELECT player_name, team_abbrev, goals, assists, points
    FROM v_skater_stats
    WHERE season = '20232024'
    ORDER BY points DESC
    LIMIT 10
""").df()

print(df)
```

**Pandas + Parquet directly:**
```python
import pandas as pd

df = pd.read_parquet("data/lake/players/skater_stats.parquet")
print(df.head())
```

---

## DuckDB views

After running `build_db.py`, these views are available:

| View | Description |
|---|---|
| `v_skater_stats` | Skater season stats joined with player bio |
| `v_goalie_stats` | Goalie season stats joined with player bio |
| `v_games` | Game results with winner column |
| `v_standings` | Standings with points % and goal diff |
| `v_shots` | All shot events with coordinates |
| `v_goals` | Goal events with scorer/assist player names |

Raw tables are also available as `raw_*` views (e.g. `raw_plays`, `raw_players`).

---

## Example queries

See [`queries/examples.sql`](queries/examples.sql) for ready-to-run queries including:

- Points leaders per season / career totals
- Best goalie save percentages
- Head-to-head team records
- Shot heatmap coordinates
- Draft pick ROI by round
- Penalty minutes leaders
- OT/SO game frequency by season

---

## Incremental updates

Raw JSON is cached on disk. Re-running any ingest script will skip already-cached files.  
To force a refresh of specific data, delete the relevant file from `data/raw/` and re-run.

To add the current season's new games:

```bash
python run_pipeline.py --from-step games
```

---

## API notes

- **No authentication required.** Both `api-web.nhle.com` and `api.nhle.com` are public.
- The pipeline includes a 300ms delay between requests to be a polite API consumer.
- The unofficial API has no SLA — endpoints may change without notice. Check [NHL API Reference](https://github.com/Zmalski/NHL-API-Reference) for updates.
- Play-by-play is the largest dataset: ~200-500 events × ~1,300 games/season × 10 seasons ≈ **3-6M rows**.

---

## Estimated data sizes

| Dataset | Estimated rows | Parquet size |
|---|---|---|
| Games | ~13,000 | ~2 MB |
| Player game stats | ~500,000 | ~50 MB |
| Skater stats (seasonal) | ~8,000 | ~2 MB |
| Goalie stats (seasonal) | ~1,200 | ~0.5 MB |
| Rosters | ~25,000 | ~5 MB |
| **Play-by-play** | **~4,000,000** | **~400 MB** |
