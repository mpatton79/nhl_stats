# nhl_stats

A Python project that uses the NHL Stats API to pull, store, and analyze NHL data in various ways. Whether you're a casual hockey fan curious about your favorite team or a serious stats nerd diving deep into advanced metrics, this project has something for you.

## Modules

| Module | Description |
|---|---|
| [nhl-data-lake](nhl-data-lake/README.md) | Local data lake of NHL statistics stored as Parquet files and queried with DuckDB |
| [nhl-api](nhl-api/) | FastAPI backend serving schedule, standings, roster, and player stats from the data lake |
| [nhl-dashboard](nhl-dashboard/) | Streamlit web dashboard with live scores, standings, player stats, edge analytics, playoff bracket, and player bio pages |
| [modelling](modelling/README.md) | Expected-goals (xG) model — LightGBM trained on play-by-play, scored daily into the data lake (`v_shot_xg`) — plus pre-game xG forecasts (`v_game_xg_forecast`) |

## Authors

- **Matt Patton** (mpatton79) — primary author
- **Claude Sonnet 4.6** (Anthropic) — co-author
