# forecast

Forecasts expected goals (xG) for NHL games that haven't been played yet. For every upcoming game it gives:

- each team's expected xG
- a range of likely outcomes (10th to 90th percentile)
- the probability that the home team generates more xG than the away team

It builds on the shot-level xG from [`../xg`](../README.md).

## How it works

**1. Expected value: team ratings.** Each team gets an offense rating (xG created) and a defense rating (xG allowed), both relative to the league average. For home team H vs. away team A:

```
xG_H = league_avg × offense_H × defense_A × home_factor
xG_A = league_avg × offense_A × defense_H × away_factor
```

For example, take a league average of 2.83, a home team that creates 17% more than average (1.17) and a visitor that allows 10% more than average (1.10). That gives 2.83 × 1.17 × 1.10 × 1.04 (home ice) ≈ **3.79 xG** for the home team.

How the ratings are calculated:
- **Recency weighting:** a game N games ago counts 0.5^(N/20), so the half-life is 20 games.
- **Home ice is removed first:** each game's xG is divided by its home or away factor before averaging, so a team's rating doesn't depend on how many of its recent games were at home.
- **Shrinkage toward average:** ratings are pulled toward league average by 10 games' worth of weight. This keeps early-season and new-team ratings sensible.
- **Relocations:** Arizona's history carries over to Utah.

**2. Spread: weighted bootstrap.** After each completed game, the engine records how far each team landed from its forecast as a ratio (actual ÷ expected). To forecast a game, it draws 4,000 of those ratios from the team's own past games, with the same recency weights, and multiplies them by the expected value. The draws produce the percentiles and the head-to-head probability.

**3. Online by construction.** The engine walks through games in date order. It predicts each game using only earlier games, then updates. This means the backtest uses the same code as live forecasting. Live forecasts freeze ratings at the latest completed game, so a game three weeks out uses today's ratings.

## Usage

Run commands from `modelling/`. You need shot-level xG in the lake first: run `python -m xg.predict` or the pipeline's `xg` step.

**Forecast upcoming games:**
```bash
python -m forecast.predict                    # every remaining game from today
python -m forecast.predict --days 7           # only the next week
python -m forecast.predict --date 2026-10-15  # as of another date
```
This prints the next few games and writes `nhl-data-lake/data/lake/xg_forecast/forecast_date=<date>/xg_forecast.parquet`. Each run date gets its own folder, so older forecasts are kept and can be checked later.

**In the daily pipeline.** The `forecast` step runs after `xg` and before `build_db`:
```bash
cd ../nhl-data-lake
python run_pipeline.py                  # full run
python run_pipeline.py --only forecast  # just re-forecast
```

**Query it (after `build_db`):**
```sql
-- Tonight's games
SELECT away_team, home_team,
       ROUND(away_xg, 2) AS away_xg, ROUND(home_xg, 2) AS home_xg,
       ROUND(p_home_xg_higher, 2) AS p_home
FROM v_game_xg_forecast
WHERE game_date = CURRENT_DATE
ORDER BY start_time_utc;
```
`v_game_xg_forecast` shows the latest run only. `raw_xg_forecast` keeps every run.

**Backtest and tune:**
```bash
python -m forecast.backtest          # evaluate on 2024-25 and 2025-26
python -m forecast.backtest --grid   # try half-life / shrinkage combinations on 2024-25
```

## Output columns

| Column | Description |
|---|---|
| `home_xg`, `away_xg` | Expected xG |
| `home_xg_p10` … `home_xg_p90` (and `away_`) | Range of likely outcomes: 10th, 25th, 50th, 75th and 90th percentiles |
| `p_home_xg_higher` | Probability the home team generates more xG |
| `home_off_rating`, `home_def_rating` (and `away_`) | Ratings relative to league average (1.10 = 10% above) |
| `league_avg_xg`, `home_factor` | League average xG per team-game, and the home-ice multiplier |
| `forecast_date`, `ratings_through` | When the forecast ran, and the last completed game it used |
| `game_id`, `season`, `game_date`, `start_time_utc`, `game_type`, `home_team`, `away_team` | Game details |

## Backtest results

Each team-game is predicted from earlier games only. Errors are in xG per team-game.

| | 2024-25 (tuning) | 2025-26 (held out) |
|---|---|---|
| Error: league average for every game | 0.834 | 0.834 |
| Error: team's own offense only | 0.811 | 0.810 |
| Error: offense × opponent's defense | 0.786 | 0.794 |
| **Error: full model (adds home ice)** | **0.780** | **0.789** |
| 50% range contains the actual result | 48% | 51% |
| 80% range contains the actual result | 78% | 79% |
| Home-team-wins-xG probability, Brier score (model / constant guess) | 0.222 / 0.246 | 0.227 / 0.248 |

**How to read these:**
- **Single games are noisy.** A team's xG swings by about ±0.85 from game to game, so even a good model only beats the league average by 5–7%. The forecast's value is in getting the average and the range right, and the ranges are well calibrated.
- **Probabilities are slightly overconfident in the 60–80% band.** Games forecast at about 75% came true about 68% of the time. Games at 80%+ are accurate (85% forecast, 84% actual).
- **The two teams are sampled independently.** That's reasonable because their residuals are nearly uncorrelated (r = -0.05).

## Configuration

Settings are in `config.py`. The defaults were tuned on 2024-25; the results above are flat for half-lives of 20–30 games and shrinkage of 5–10 games.

| Setting | Default | Meaning |
|---|---|---|
| `HALF_LIFE_GAMES` | 20 | Recency decay for ratings and bootstrap weights |
| `PRIOR_GAMES` | 10 | Weight of the shrinkage toward league average |
| `LEAGUE_HALF_LIFE_GAMES` | 1300 | Decay for league average and home/away factors (about one season) |
| `N_DRAWS` | 4000 | Bootstrap draws per team per game |
| `RESIDUAL_MIN_GAMES` | 10 | Below this many past games, sample from the league-wide pool instead |
| `TEAM_ALIASES` | `{"ARI": "UTA"}` | Relocated franchises that keep their history |
