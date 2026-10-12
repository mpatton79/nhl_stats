"""
Out-of-sample backtest of the pre-game xG forecast.

    cd modelling
    python -m forecast.backtest            # evaluate config defaults on tune + test seasons
    python -m forecast.backtest --grid     # tune half-life / prior on the tune season

Every game is predicted from ratings built only on earlier games, then folded
in. Regular-season games in the evaluated seasons are scored against:
  - league average           (no team information)
  - team offense only        (a team's own recency-weighted xG for)
  - offense × opp. defence   (no home ice)
  - full model               (offense × opp. defence × home/away factor)
Intervals are checked for coverage (an 80% interval should contain the
actual result ~80% of the time), and P(home xG > away xG) by Brier score.
"""

import argparse
import json

import duckdb
import numpy as np
import pandas as pd

from xg.config import MODELS_DIR

from .config import (DB_PATH, HALF_LIFE_GAMES, N_DRAWS, PRIOR_GAMES, QUANTILES, REGULAR,
                     SEED, TEST_SEASON, TUNE_SEASON)
from .engine import RatingEngine, load_completed

BACKTEST_PATH = MODELS_DIR / "forecast_backtest.json"


def run(games: pd.DataFrame, seasons: list[str], half_life: float, prior: float,
        sample: bool = True) -> pd.DataFrame:
    """Walk every game; return one row per team-game in *seasons* (regular season)."""
    engine = RatingEngine(half_life=half_life, prior=prior)
    engine.seed(games.head(200))
    rng = np.random.default_rng(SEED)
    rows = []

    for g in games.itertuples(index=False):
        exp = engine.expect(g.home_team, g.away_team)
        if g.season in seasons and g.game_type == REGULAR:
            if sample:
                home_draws = engine.sample(g.home_team, exp["home_xg"], N_DRAWS, rng)
                away_draws = engine.sample(g.away_team, exp["away_xg"], N_DRAWS, rng)
                p_home = float((home_draws > away_draws).mean())
            for side, other, actual, draws in (("home", "away", g.home_xg, home_draws if sample else None),
                                                ("away", "home", g.away_xg, away_draws if sample else None)):
                avg = exp["league_avg"]
                row = {
                    "season": g.season, "game_id": g.game_id, "side": side, "actual": actual,
                    "league_avg": avg,
                    "offense_only": avg * exp[f"{side}_off"],
                    "off_x_def": avg * exp[f"{side}_off"] * exp[f"{other}_def"],
                    "full_model": exp[f"{side}_xg"],
                }
                if sample:
                    row.update({f"q{int(q * 100)}": v for q, v in zip(QUANTILES, np.quantile(draws, QUANTILES))})
                    row["p_win_xg"] = p_home if side == "home" else 1 - p_home
                    row["won_xg"] = float(actual > (g.away_xg if side == "home" else g.home_xg))
                rows.append(row)
        engine.update(g.home_team, g.away_team, g.home_xg, g.away_xg, exp)

    return pd.DataFrame(rows)


METHODS = ["league_avg", "offense_only", "off_x_def", "full_model"]


def summarise(df: pd.DataFrame) -> dict:
    out = {"team_games": len(df), "mean_actual_xg": round(df["actual"].mean(), 3)}
    for m in METHODS:
        err = df["actual"] - df[m]
        out[m] = {"rmse": round(float(np.sqrt((err ** 2).mean())), 4),
                  "mae": round(float(err.abs().mean()), 4),
                  "bias": round(float(df[m].sum() / df["actual"].sum()), 3)}
    if "q10" in df:
        out["coverage_50"] = round(float(df["actual"].between(df["q25"], df["q75"]).mean()), 3)
        out["coverage_80"] = round(float(df["actual"].between(df["q10"], df["q90"]).mean()), 3)
        home = df[df["side"] == "home"]
        base = home["won_xg"].mean()
        out["p_home_xg_higher"] = {
            "brier": round(float(((home["p_win_xg"] - home["won_xg"]) ** 2).mean()), 4),
            "brier_constant": round(float(((base - home["won_xg"]) ** 2).mean()), 4),
            "mean_p": round(float(home["p_win_xg"].mean()), 3),
            "actual_rate": round(float(base), 3),
        }
    return out


def _print(season: str, s: dict):
    print(f"\n── {season}: {s['team_games']:,} team-games, mean xG {s['mean_actual_xg']} ──")
    print(f"  {'method':<16}{'RMSE':>8}{'MAE':>8}{'Σpred/Σactual':>15}")
    for m in METHODS:
        print(f"  {m:<16}{s[m]['rmse']:>8.4f}{s[m]['mae']:>8.4f}{s[m]['bias']:>15.3f}")
    if "coverage_80" in s:
        p = s["p_home_xg_higher"]
        print(f"  interval coverage: 50% → {s['coverage_50']:.3f}   80% → {s['coverage_80']:.3f}")
        print(f"  P(home xG > away xG): Brier {p['brier']} vs constant {p['brier_constant']} "
              f"(mean p {p['mean_p']}, actual {p['actual_rate']})")


def main():
    parser = argparse.ArgumentParser(description="Backtest pre-game xG forecasts")
    parser.add_argument("--grid", action="store_true", help=f"Tune half-life/prior on {TUNE_SEASON}")
    parser.add_argument("--half-life", type=float, default=HALF_LIFE_GAMES)
    parser.add_argument("--prior", type=float, default=PRIOR_GAMES)
    args = parser.parse_args()

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        games = load_completed(con)

    if args.grid:
        rows = []
        for hl in (10, 15, 20, 30, 40):
            for k in (0, 3, 5, 10, 20):
                df = run(games, [TUNE_SEASON], hl, k, sample=False)
                err = df["actual"] - df["full_model"]
                rows.append((hl, k, float(np.sqrt((err ** 2).mean()))))
        grid = pd.DataFrame(rows, columns=["half_life", "prior", "rmse"])
        print(f"Full-model RMSE on {TUNE_SEASON} (rows: half-life in games, cols: prior games)")
        print(grid.pivot(index="half_life", columns="prior", values="rmse").round(4).to_string())
        return

    df = run(games, [TUNE_SEASON, TEST_SEASON], args.half_life, args.prior)
    report = {"half_life": args.half_life, "prior": args.prior}
    for season in (TUNE_SEASON, TEST_SEASON):
        report[season] = summarise(df[df["season"] == season])
        _print(season, report[season])

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    BACKTEST_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nSaved → {BACKTEST_PATH}")


if __name__ == "__main__":
    main()
