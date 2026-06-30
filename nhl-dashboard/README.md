# nhl-dashboard

A Streamlit web dashboard for exploring NHL data — live scores, standings, player stats, advanced edge analytics, playoff brackets, and individual player bios.

## Pages

| Page | Description |
|---|---|
| Games | Live and historical scores with boxscore drill-down; auto-refreshes every 30s for today |
| Standings | Division and league-wide standings with team logos |
| Players | Skater stats with season/team/position filters, player search, and bio drill-down |
| Edge Stats | NHL Edge advanced metrics (speed, puck possession, rush attempts) |
| Playoff Bracket | Interactive bracket view by year with team filter |
| Player Bio | Headshot, bio details, and career stats for a selected player |

## Prerequisites

- Python 3.11+
- The [nhl-data-lake](../nhl-data-lake/) database must be built at `../nhl-data-lake/db/nhl.duckdb` (or set `NHL_DB_PATH`)

## Setup

```bash
cd nhl-dashboard
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Launch

```bash
streamlit run main.py
```

The app opens at [http://localhost:8501](http://localhost:8501).

## Configuration

| Env var | Default | Description |
|---|---|---|
| `NHL_DB_PATH` | `../nhl-data-lake/db/nhl.duckdb` | Path to the DuckDB database |
