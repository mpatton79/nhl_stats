"""
Forecast configuration. Defaults were chosen on the 2024-25 backtest season
(see README.md); 2025-26 is the held-out check.
"""

from xg.config import DB_PATH, LAKE_DIR, PLAYOFFS, REGULAR  # noqa: F401  (shared paths)

FORECAST_DIR = LAKE_DIR / "xg_forecast"     # partitioned by forecast_date

GAME_TYPES = (REGULAR, PLAYOFFS)

# ── Team ratings ──────────────────────────────────────────────────────────────
HALF_LIFE_GAMES = 20     # a team's game N games ago counts 0.5^(N/20)
PRIOR_GAMES     = 10     # shrink ratings toward league average by this many games' weight
LEAGUE_HALF_LIFE_GAMES = 1300   # ~one season; league average and home/away factors

# Relocated franchises keep their rating history.
TEAM_ALIASES = {"ARI": "UTA"}

# ── Bootstrap ─────────────────────────────────────────────────────────────────
N_DRAWS          = 4000
RESIDUAL_MIN_GAMES = 10    # fewer team residuals than this → sample from the league pool
RESIDUAL_MAX_AGE = 8 * HALF_LIFE_GAMES   # older residuals carry < 0.4% weight; drop them
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
SEED = 20261012

# ── Backtest ──────────────────────────────────────────────────────────────────
TUNE_SEASON = "20242025"
TEST_SEASON = "20252026"
