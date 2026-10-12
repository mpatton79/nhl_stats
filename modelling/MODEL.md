# Expected Goals (xG) Model

## Overview
This model estimates the probability that an unblocked shot becomes a goal (expected goals, or xG). It's trained on NHL play-by-play from the data lake and scores new games as they come in during the season.

There are three stages:
1. **Preprocessing.** Build one row per unblocked shot with geometry, sequence, strength and game-state features.
2. **Training.** Binary classification (goal vs. no goal). A logistic regression baseline is compared against LightGBM.
3. **Scoring pipeline.** The saved model scores out-of-sample shots from recent games and writes them back to the data lake.

All three stages share a single feature module, so training and scoring can't drift apart.

```
modelling/
├── MODEL.md
├── requirements.txt
├── models/                 # gitignored: xg_model.joblib + metrics.json (regenerate with xg.train)
└── xg/
    ├── config.py           # paths, season split, feature contract
    ├── features.py         # load_shots() → engineer() → model_frame()   (shared)
    ├── train.py            # python -m xg.train
    └── predict.py          # python -m xg.predict [--season S | --all]
```

### Usage
```bash
pip install -r modelling/requirements.txt     # macOS: brew install libomp (for LightGBM)
cd modelling
python -m xg.train                            # train, evaluate, save model + metrics
python -m xg.predict --all                    # one-off backfill of every season
```
After that, the data-lake pipeline runs an `xg` step automatically, between `skater_edge_stats` and `build_db`. That step re-scores the current season, and the step is skipped if no model has been trained.

---

## Stage 1: Preprocessing (`xg/features.py`)

### Source data and filters
Shots come from `raw_plays` for **regular-season** games in training. Scoring covers both regular season and playoffs. The filters:

| Filter | Why |
|---|---|
| `event_type IN (shot-on-goal, missed-shot, goal)` | Unblocked attempts only (Fenwick) |
| `period_type <> 'SO'` | Shootout attempts aren't game play (~7.7K events, including 2.4K "goals") |
| Defending goalie in net (from `situation_code`) | Empty-net goals are near-certain and would distort the model. `goalie_player_id` isn't reliable for missed shots. |
| Both teams have ≥ 3 skaters | Drops penalty shots (`1010` / `0101`) |
| Coordinates present, `zone_code = 'O'` | ~550 shots have no coordinates |
| Valid 4-digit `situation_code` | ~0.5% of shots are missing one |

### Sequence features are computed before filtering
Previous-event and rebound features are computed in DuckDB with `LAG()` over the **full** play stream, before any rows are dropped. They're partitioned by `game_id` and period and ordered by the API's `sortOrder`. Two details matter here:
- `event_id` is **not** chronological. About 23% of consecutive pairs are out of order, so it's only used as a tiebreaker.
- A blocked shot is owned by the *blocking* team, so the attempt is credited to the other team.

### Features
| Group | Features |
|---|---|
| Geometry | `shot_distance`, `shot_angle` (`atan2`, correct behind the net), `x_norm`, `y_norm`, `shot_zone` (depth 10/20/30 + lateral 1/2/3) |
| Shooter | `shot_type` (categorical), `off_wing` (shot side ≠ handedness) |
| Rebound | `is_rebound` (same-team attempt ≤ 3 s earlier), `time_since_prev_attempt`, `rebound_angle_change` |
| Previous event | `prev_event_type`, `time_since_prev_event`, `prev_same_team`, `prev_zone_rel` (zone relative to the shooter), `prev_event_distance`, `speed_from_prev`, `is_rush` (previous event in N/D zone ≤ 4 s earlier) |
| Strength | `strength_state` (EV/PP/SH), `shooter_skaters`, `defending_skaters`, `extra_attacker` (own goalie pulled) |
| Game state | `score_diff` (shooter's goal differential before the shot, clipped to ±4), `is_home`, `period`, `game_seconds` |
| Era | `season_idx` (see *Scorekeeping drift* below) |

### Conventions (verified against the data)
- **`situation_code`** is laid out `[away goalie][away skaters][home skaters][home goalie]`. For example, `1560` means the home goalie is pulled with 6 home skaters.
- **Normalization:** every shot is rotated so it attacks the net at `x = +89`. When `x < 0`, *both* x and y are flipped. Flipping only x mirrors the wing and angle for half the shots.
- **Wing:** facing the net, **y > 0 is the shooter's left**. Left-handed defensemen take 73% of their point shots from y > 0, and right-handed ones take 79% from y < 0.

### Fixes from the original plan
| Original | Problem | Now |
|---|---|---|
| `groupby(['team','period']).shift(1)` | No `game_id` and no sort, so "previous shot" crossed games | `LAG()` by game and period, ordered by `sortOrder` |
| Rebounds computed after filtering | Rebounds off blocked shots were missed | Computed on the full stream |
| `zone_x_mult` flipped x only | Wing, angle and off-wing were mirrored for ~50% of shots | x and y flipped together |
| `y < 0 → 'L'` | Backwards | `y_norm > 0 → 'L'` |
| `range()` lateral bands | Gap at y = -15, and slow on floats | `np.select` with contiguous bands |
| `atan(y / (89-|x|))` | Wrong behind the net, `ZeroDivisionError` | `atan2` |
| `00:20:00` fill for missing previous shot | Negative time deltas | NaN (LightGBM handles missing values) |
| `add_shot_counts` never called | `goal` / `fenwick` stayed 0 | Vectorized `is_goal` target |
| `.apply(axis=1)` × 6 | Slow on ~1M rows | Fully vectorized. A season loads and engineers in about a second. |
| `OR event_type = 'goal'` zone clause | Pulled in empty-net goals from the N/D zones | Empty nets excluded, offensive zone only |

### Data-lake fixes made alongside
- `ingest/plays.py` had `home_skaters` and `away_skaters` **swapped**. That's fixed, and all plays have been re-parsed.
- Plays now store `sort_order`, `home_team_id` and `away_team_id`. `raw_teams` only lists the current 32 teams, so joining through it lost ~105K Arizona and old-Utah events.

---

## Stage 2: Training (`xg/train.py`)

**Target:** `is_goal` (binary). The model outputs xG = P(goal | unblocked shot).

**Split by season, never random rows.** Random rows leak information within a game.

| Set | Seasons | Use |
|---|---|---|
| Train | 2017-18 … 2023-24 | Fit |
| Valid | 2024-25 | LightGBM early stopping |
| Test | 2025-26 | Untouched until final evaluation |

**Models**
1. **Baseline:** logistic regression on `shot_distance` and `shot_angle`. This is the bar to beat.
2. **LightGBM** on all features: early-stopped on the validation season, then refit on train + valid at that size and scored on test.
3. **Production model:** refit on every labelled season (2017–2026) with the same number of trees, then saved to `models/xg_model.joblib`.

**Metrics** (written to `models/metrics.json`): log loss, Brier score, ROC AUC, decile calibration, and team-level summed xG vs. goals.

### Results: test season 2025-26 (107,315 shots, 7,568 goals)
| Model | Log loss | Brier | AUC | Σ xG | Team xG–goals r | Team MAE |
|---|---|---|---|---|---|---|
| Logistic (distance + angle) | 0.2384 | 0.0636 | 0.703 | 7,668 | 0.656 | 14.5 |
| **LightGBM** | **0.2216** | **0.0602** | **0.770** | 7,905 | **0.819** | **14.4** |

Calibration is close across the deciles. The top decile runs slightly hot (0.248 predicted vs. 0.231 actual). The most important features by gain are distance, angle, shot type, time since the previous event, lateral position, time since the previous attempt, and `season_idx`.

### Scorekeeping drift
The NHL's event recording has shifted in recent seasons:
- **Shot type relabelling.** Wrist shots fell from ~53% to 43% of shots, and snap shots rose from 14% to 25%, in 2024-26.
- **More rebounds recorded.** The rebound rate went from ~6.3% (2017–22) to 9.1% (2025-26).

Without correction, the model over-predicted 2025-26 by 7.3%. I tested four mitigations:

| Variant | Log loss | AUC | Σ xG / goals |
|---|---|---|---|
| No correction | 0.2279 | 0.748 | 1.073 |
| Recency sample weights | 0.2249 | 0.758 | 1.055 |
| **`season_idx` feature** | **0.2219** | **0.770** | 1.044 |
| Merge wrist + snap | 0.2285 | 0.745 | 1.041 |

`season_idx` (season start year − 2017) won. Trees can't extrapolate, so an unseen season is scored like the most recent trained season, which is the right behavior when scorekeeping drifts. Season-level bias is still about ±4%, roughly the size of normal year-to-year swings in the league goal rate.

---

## Stage 3: Scoring pipeline (`xg/predict.py`)

- Loads `models/xg_model.joblib` and runs the **same** `load_shots → engineer → model_frame` path used in training.
- Scores regular-season and playoff shots, and writes `nhl-data-lake/data/lake/xg/season=<S>/shot_xg.parquet`.
- Each run rewrites the season's partition, so re-running is idempotent.
- Rows record `model_version` and `in_sample`. `in_sample` is true for seasons the production model was trained on, so treat those xG values as fitted, not predicted.
- `build_db` exposes the output as `raw_shot_xg` and **`v_shot_xg`**, which adds the team abbreviation and shooter name.
- **Daily cadence:** play-by-play only lands for games on or before yesterday, so the pipeline's `xg` step re-scores the current season each run and picks up yesterday's games.

```sql
-- Team xG vs goals this season
SELECT team, COUNT(*) shots, SUM(is_goal) goals, ROUND(SUM(xg), 1) xg
FROM v_shot_xg WHERE season = 20262027
GROUP BY team ORDER BY xg DESC;
```

### Retraining
Retrain at least once a season (for example after the regular season ends) so `season_idx` and the trained seasons include the latest year. To do this, add the completed season to `TEST_SEASON` / `VALID_SEASON` / `TRAIN_SEASONS` in `xg/config.py`, run `python -m xg.train`, then `python -m xg.predict --all`.

## Future ideas
- Shooter and goalie quality effects, using only prior seasons to avoid leakage
- A separate playoff check (the model is currently trained on regular season only)
- An xG view in the dashboard (shot map coloured by xG, team and player xG tables)
