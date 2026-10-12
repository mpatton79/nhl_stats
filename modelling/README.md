# modelling

An expected-goals (xG) model for NHL shots. It estimates the probability that an unblocked shot becomes a goal, using play-by-play data from the [nhl-data-lake](../nhl-data-lake/). Predictions are written back to the lake and can be queried in DuckDB as `v_shot_xg`.

See [MODEL.md](MODEL.md) for the full design: features, filters, data conventions, the season split and results.

## Pipeline

```
raw_plays ──► load_shots ──► engineer ──► model_frame ──┬──► train.py   ──► models/xg_model.joblib
 (DuckDB)     (SQL + LAG)    (features)   (filters)      │                   models/metrics.json
                                                         └──► predict.py ──► data/lake/xg/season=*/shot_xg.parquet
                                                                                  └──► v_shot_xg (after build_db)
```

| File | Purpose |
|---|---|
| `xg/config.py` | Paths, season split, and the feature list |
| `xg/features.py` | Shot loading and feature engineering, shared by training and scoring |
| `xg/train.py` | Trains a logistic baseline and LightGBM, evaluates them on the test season, and saves the model |
| `xg/predict.py` | Scores shots with the saved model and writes the predictions to the lake |

## Prerequisites

- Python 3.11+
- A built data lake with plays, games and players: `python run_pipeline.py` in `nhl-data-lake/`
- On macOS, LightGBM needs OpenMP: `brew install libomp`

```bash
pip install -r modelling/requirements.txt
```

## Usage

Run all commands from the `modelling/` directory.

**Train** (about 5–10 minutes). This writes `models/xg_model.joblib` and `models/metrics.json` and prints test-season metrics:
```bash
python -m xg.train
```

**Score:**
```bash
python -m xg.predict                     # current season
python -m xg.predict --season 20242025   # a specific season (repeatable)
python -m xg.predict --all               # every season in the lake
```
Each run overwrites that season's output, so it's safe to re-run.

**Daily updates.** The data-lake pipeline has an `xg` step that re-scores the current season before `build_db`. It's skipped if no model has been trained yet.
```bash
cd ../nhl-data-lake
python run_pipeline.py              # full run, includes xg
python run_pipeline.py --only xg    # just re-score
```

**Query the results:**
```sql
SELECT team, COUNT(*) AS shots, SUM(is_goal) AS goals, ROUND(SUM(xg), 1) AS xg
FROM v_shot_xg
WHERE season = 20262027
GROUP BY team
ORDER BY xg DESC;
```

## Output columns (`v_shot_xg`)

| Column | Description |
|---|---|
| `xg` | Probability the shot is a goal |
| `is_goal` | 1 if the shot was a goal |
| `game_id`, `season`, `game_date`, `period`, `game_seconds`, `sort_order` | Where and when the shot happened |
| `team`, `shooter_name`, `shooter_id`, `goalie_player_id`, `is_home` | Who took the shot and who was in goal |
| `x_norm`, `y_norm`, `shot_distance`, `shot_angle`, `shot_type` | Shot location (normalized so the net is at x = 89) and type |
| `strength_state`, `score_diff`, `is_rebound`, `is_rush` | Game context |
| `model_version`, `in_sample` | Which model produced the row, and whether that model was trained on this season |

Empty-net shots, shootouts and penalty shots aren't scored. For seasons the model was trained on (`in_sample = true`), the xG values are fitted rather than true predictions.

## Retraining

Retrain at least once a season, for example after the regular season ends:

1. In `xg/config.py`, move the season split forward one year: add the oldest validation season to `TRAIN_SEASONS`, and set `VALID_SEASON` and `TEST_SEASON` to the two most recent completed seasons.
2. Run `python -m xg.train`.
3. Run `python -m xg.predict --all` to re-score history with the new model.

## Configuration

| Env var | Default | Description |
|---|---|---|
| `NHL_DB_PATH` | `../nhl-data-lake/db/nhl.duckdb` | Path to the DuckDB database |

Model files in `models/` are not tracked by git, so run `python -m xg.train` on each new machine.
