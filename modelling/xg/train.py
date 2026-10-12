"""
Train the xG model.

    cd modelling && python -m xg.train

1. Load regular-season unblocked shots for train / valid / test seasons.
2. Baseline: logistic regression on distance + angle.
3. LightGBM on the full feature set, early-stopped on the validation season.
4. Evaluate both on the untouched test season (log loss, Brier, AUC,
   calibration, team-level xG vs goals).
5. Refit the production LightGBM on every season with the chosen iteration
   count and save it, with metrics, to modelling/models/.
"""

import json
import logging
from datetime import datetime, timezone

import duckdb
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config import (BASELINE_FEATURES, CATEGORIES, DB_PATH, FEATURES, METRICS_PATH,
                     MODEL_PATH, MODELS_DIR, TARGET, TEST_SEASON, TRAIN_SEASONS, VALID_SEASON)
from .features import engineer, load_shots, model_frame

logger = logging.getLogger(__name__)

LGBM_PARAMS = dict(
    objective="binary",
    learning_rate=0.03,
    num_leaves=31,
    min_child_samples=200,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    n_estimators=5000,
    verbose=-1,
)


def evaluate(y: pd.Series, p: np.ndarray, frame: pd.DataFrame) -> dict:
    """Probabilistic metrics, decile calibration, and team-level xG vs goals."""
    deciles = pd.qcut(p, 10, labels=False, duplicates="drop")
    calib = (pd.DataFrame({"p": p, "y": y.to_numpy(), "bin": deciles})
             .groupby("bin").agg(mean_xg=("p", "mean"), goal_rate=("y", "mean"), n=("y", "size")))
    teams = (pd.DataFrame({"team": frame["shot_team_id"], "xg": p, "goals": y.to_numpy()})
             .groupby("team")[["xg", "goals"]].sum())
    return {
        "n_shots":   int(len(y)),
        "goals":     int(y.sum()),
        "sum_xg":    round(float(p.sum()), 1),
        "log_loss":  round(log_loss(y, p), 5),
        "brier":     round(brier_score_loss(y, p), 5),
        "roc_auc":   round(roc_auc_score(y, p), 4),
        "team_xg_vs_goals_corr": round(float(teams["xg"].corr(teams["goals"])), 3),
        "team_xg_mae":           round(float((teams["xg"] - teams["goals"]).abs().mean()), 2),
        "calibration": calib.round(4).reset_index().to_dict(orient="records"),
    }


def _print_report(name: str, m: dict):
    print(f"\n── {name} ─────────────────────────────")
    print(f"  shots {m['n_shots']:,}  goals {m['goals']:,}  sum xG {m['sum_xg']:,}")
    print(f"  log loss {m['log_loss']}  Brier {m['brier']}  AUC {m['roc_auc']}")
    print(f"  team xG vs goals: r = {m['team_xg_vs_goals_corr']}, MAE = {m['team_xg_mae']} goals")
    print("  calibration (decile: mean xG → goal rate):")
    for row in m["calibration"]:
        print(f"    {int(row['bin']):>2}: {row['mean_xg']:.4f} → {row['goal_rate']:.4f}  (n={row['n']:,})")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    seasons = TRAIN_SEASONS + [VALID_SEASON, TEST_SEASON]

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        logger.info("Loading shots for %s..%s", seasons[0], seasons[-1])
        df = model_frame(engineer(load_shots(con, seasons)))
    logger.info("Model frame: %d shots, goal rate %.4f", len(df), df[TARGET].mean())

    train = df[df["season"].isin(TRAIN_SEASONS)]
    valid = df[df["season"] == VALID_SEASON]
    test  = df[df["season"] == TEST_SEASON]
    fit   = pd.concat([train, valid])

    # ── Baseline: logistic regression on distance + angle ─────────────────────
    baseline = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    baseline.fit(fit[BASELINE_FEATURES], fit[TARGET])
    base_test = evaluate(test[TARGET], baseline.predict_proba(test[BASELINE_FEATURES])[:, 1], test)

    # ── LightGBM, early-stopped on the validation season ──────────────────────
    model = lgb.LGBMClassifier(**LGBM_PARAMS)
    model.fit(train[FEATURES], train[TARGET],
              eval_X=valid[FEATURES], eval_y=valid[TARGET], eval_metric="binary_logloss",
              callbacks=[lgb.early_stopping(200, verbose=False)])
    best_iter = model.best_iteration_
    logger.info("Best iteration: %d", best_iter)
    lgbm_valid = evaluate(valid[TARGET], model.predict_proba(valid[FEATURES])[:, 1], valid)

    # Refit on train+valid at the chosen size, then score the untouched test season
    eval_model = lgb.LGBMClassifier(**{**LGBM_PARAMS, "n_estimators": best_iter})
    eval_model.fit(fit[FEATURES], fit[TARGET])
    lgbm_test = evaluate(test[TARGET], eval_model.predict_proba(test[FEATURES])[:, 1], test)

    importance = (pd.Series(eval_model.booster_.feature_importance("gain"), index=FEATURES)
                  .sort_values(ascending=False))
    importance = (importance / importance.sum()).round(4)

    # ── Production model: every labelled season ──────────────────────────────
    prod = lgb.LGBMClassifier(**{**LGBM_PARAMS, "n_estimators": best_iter})
    prod.fit(df[FEATURES], df[TARGET])

    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model":           prod,
        "baseline":        baseline,
        "features":        FEATURES,
        "categories":      CATEGORIES,
        "trained_seasons": sorted(df["season"].unique().tolist()),
        "best_iteration":  best_iter,
        "version":         version,
    }, MODEL_PATH)

    metrics = {
        "version": version,
        "split": {"train": TRAIN_SEASONS, "valid": VALID_SEASON, "test": TEST_SEASON},
        "best_iteration": best_iter,
        "baseline_logistic_test": base_test,
        "lightgbm_valid": lgbm_valid,
        "lightgbm_test": lgbm_test,
        "feature_importance_gain": importance.to_dict(),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))

    _print_report(f"Baseline logistic (distance + angle) — test {TEST_SEASON}", base_test)
    _print_report(f"LightGBM — test {TEST_SEASON}", lgbm_test)
    print("\n── Feature importance (share of gain) ──")
    for feat, share in importance.head(15).items():
        print(f"  {feat:<26} {share:.3f}")
    print(f"\nSaved model  → {MODEL_PATH}\nSaved metrics → {METRICS_PATH}  (version {version})")


if __name__ == "__main__":
    main()
