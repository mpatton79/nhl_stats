"""
xG model configuration — paths, season splits, and the feature contract
shared by training and scoring.
"""

import os
from pathlib import Path

ROOT      = Path(__file__).resolve().parents[2]          # repo root
LAKE_ROOT = ROOT / "nhl-data-lake"
DB_PATH   = Path(os.getenv("NHL_DB_PATH", str(LAKE_ROOT / "db" / "nhl.duckdb")))
LAKE_DIR  = LAKE_ROOT / "data" / "lake"
XG_DIR    = LAKE_DIR / "xg"                               # predictions, partitioned by season

MODELS_DIR  = Path(__file__).resolve().parents[1] / "models"
MODEL_PATH  = MODELS_DIR / "xg_model.joblib"
METRICS_PATH = MODELS_DIR / "metrics.json"

# ── Season split (by season, never random rows — avoids within-game leakage) ──
TRAIN_SEASONS = [f"{y}{y+1}" for y in range(2017, 2024)]  # 2017-18 .. 2023-24
VALID_SEASON  = "20242025"                                 # early stopping / model selection
TEST_SEASON   = "20252026"                                 # untouched until final evaluation

REGULAR, PLAYOFFS = 2, 3

# season_idx = start year - SEASON_BASE_YEAR. Captures scorekeeping drift (e.g. the
# wrist→snap relabelling and rising rebound counts since 2022). Trees can't
# extrapolate, so an unseen season is scored like the latest trained season.
SEASON_BASE_YEAR = 2017

# Net is at x = 89 after normalising every shot to attack toward +x.
NET_X = 89.0
REBOUND_SECONDS = 3   # shot attempt by same team within this many seconds → rebound
RUSH_SECONDS    = 4   # previous event in N/D zone within this many seconds → rush

# ── Feature contract ──────────────────────────────────────────────────────────
SHOT_TYPES = ["wrist", "snap", "slap", "tip-in", "backhand", "wrap-around",
              "deflected", "between-legs", "poke", "bat", "cradle"]
PREV_EVENT_TYPES = ["none", "faceoff", "shot-on-goal", "missed-shot", "blocked-shot",
                    "goal", "hit", "giveaway", "takeaway", "penalty"]
ZONES = ["O", "N", "D"]
STRENGTHS = ["EV", "PP", "SH"]

CATEGORIES = {
    "shot_type":       SHOT_TYPES,
    "prev_event_type": PREV_EVENT_TYPES,
    "prev_zone_rel":   ZONES,
    "strength_state":  STRENGTHS,
}

NUMERIC_FEATURES = [
    "shot_distance", "shot_angle", "x_norm", "y_norm", "shot_zone", "off_wing",
    "is_rebound", "time_since_prev_attempt", "rebound_angle_change",
    "time_since_prev_event", "prev_same_team", "prev_event_distance",
    "speed_from_prev", "is_rush",
    "shooter_skaters", "defending_skaters", "extra_attacker",
    "score_diff", "is_home", "period", "game_seconds", "season_idx",
]
CATEGORICAL_FEATURES = list(CATEGORIES)
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

BASELINE_FEATURES = ["shot_distance", "shot_angle"]   # logistic regression baseline

TARGET = "is_goal"
