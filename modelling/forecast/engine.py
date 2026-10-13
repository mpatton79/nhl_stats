"""
Rating engine for pre-game xG forecasts.

Expected value — for home team H vs away team A:

    xG_H = league_avg × off_H × def_A × home_factor
    xG_A = league_avg × off_A × def_H × away_factor

  off_T  = T's recency-weighted xG for  / league average   (1.10 = creates 10% more)
  def_T  = T's recency-weighted xG against / league average (1.10 = allows 10% more)

Ratings use exponential decay by games played (HALF_LIFE_GAMES), are shrunk
toward league average by PRIOR_GAMES of weight, and are venue-adjusted (each
game's xG is divided by that game's home/away factor before it's averaged).

Spread — every completed game leaves a residual  actual xG / expected xG  for
each team. A forecast draws from the team's own residual history, weighted by
the same recency decay (weighted bootstrap), and multiplies by the expected
value. Teams with too little history fall back to the league residual pool.

Win probability — each paired xG draw becomes a goal total via a Poisson draw
(goals from many small-probability shots are close to Poisson with mean xG);
ties count as a 50/50 overtime or shootout.

The engine is online: it walks games in date order, predicts each one from
state built only on earlier games, then updates. Backtests are therefore
out-of-sample by construction.
"""

from collections import deque
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from .config import (GAME_TYPES, HALF_LIFE_GAMES, LEAGUE_HALF_LIFE_GAMES, PRIOR_GAMES,
                     RESIDUAL_MAX_AGE, RESIDUAL_MIN_GAMES, TEAM_ALIASES)

_TYPES = ", ".join(str(t) for t in GAME_TYPES)


def _alias(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("home_team", "away_team"):
        df[col] = df[col].replace(TEAM_ALIASES)
    return df


def load_completed(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per completed game that has xG, in chronological order."""
    df = con.execute(f"""
        SELECT g.game_id, CAST(g.season AS VARCHAR) AS season, g.game_date, g.start_time_utc,
               g.game_type, g.home_team, g.away_team,
               SUM(CASE WHEN x.is_home = 1 THEN x.xg ELSE 0 END) AS home_xg,
               SUM(CASE WHEN x.is_home = 0 THEN x.xg ELSE 0 END) AS away_xg,
               g.home_score, g.away_score
        FROM raw_games g
        JOIN raw_shot_xg x ON x.game_id = g.game_id
        WHERE g.game_type IN ({_TYPES}) AND g.game_state IN ('OFF', 'FINAL')
        GROUP BY ALL
        ORDER BY g.game_date, g.start_time_utc, g.game_id
    """).df()
    return _alias(df)


def load_upcoming(con: duckdb.DuckDBPyConnection, today: date) -> pd.DataFrame:
    """Scheduled games from *today* on that haven't finished."""
    df = con.execute(f"""
        SELECT game_id, CAST(season AS VARCHAR) AS season, game_date, start_time_utc,
               game_type, home_team, away_team
        FROM raw_games
        WHERE game_type IN ({_TYPES})
          AND game_state NOT IN ('OFF', 'FINAL')
          AND CAST(game_date AS DATE) >= ?
        ORDER BY game_date, start_time_utc, game_id
    """, [today]).df()
    return _alias(df)


class _Team:
    __slots__ = ("off_sum", "def_sum", "weight", "games", "resid")

    def __init__(self):
        self.off_sum = self.def_sum = self.weight = 0.0
        self.games = 0
        self.resid: deque[tuple[int, float]] = deque(maxlen=RESIDUAL_MAX_AGE)


class RatingEngine:
    def __init__(self, half_life: float = HALF_LIFE_GAMES, prior: float = PRIOR_GAMES,
                 league_half_life: float = LEAGUE_HALF_LIFE_GAMES):
        self.half_life = half_life
        self.prior = prior
        self.decay = 0.5 ** (1 / half_life)
        self.league_decay = 0.5 ** (1 / league_half_life)
        self.teams: dict[str, _Team] = {}
        self.home_sum = self.home_n = self.away_sum = self.away_n = 0.0
        self.league_resid: deque[float] = deque(maxlen=2000)

    # ── League state ──────────────────────────────────────────────────────────
    def seed(self, games: pd.DataFrame, weight: float = 50.0):
        """Start league averages from the opening games so the first predictions are sane."""
        self.home_sum, self.home_n = games["home_xg"].mean() * weight, weight
        self.away_sum, self.away_n = games["away_xg"].mean() * weight, weight

    def league(self) -> tuple[float, float, float]:
        """(league average xG per team-game, home factor, away factor)."""
        avg = (self.home_sum + self.away_sum) / (self.home_n + self.away_n)
        return avg, (self.home_sum / self.home_n) / avg, (self.away_sum / self.away_n) / avg

    def _team(self, name: str) -> _Team:
        return self.teams.setdefault(name, _Team())

    def ratings(self, name: str, league_avg: float) -> tuple[float, float]:
        """(offense, defence) as multiples of league average, shrunk toward 1.0."""
        t = self._team(name)
        denom = (t.weight + self.prior) * league_avg
        if denom == 0:
            return 1.0, 1.0
        prior_mass = self.prior * league_avg
        return (t.off_sum + prior_mass) / denom, (t.def_sum + prior_mass) / denom

    # ── Predict / update ──────────────────────────────────────────────────────
    def expect(self, home: str, away: str) -> dict:
        avg, hf, af = self.league()
        h_off, h_def = self.ratings(home, avg)
        a_off, a_def = self.ratings(away, avg)
        return {
            "league_avg": avg, "home_factor": hf, "away_factor": af,
            "home_off": h_off, "home_def": h_def, "away_off": a_off, "away_def": a_def,
            "home_xg": avg * h_off * a_def * hf,
            "away_xg": avg * a_off * h_def * af,
        }

    def update(self, home: str, away: str, home_xg: float, away_xg: float, exp: dict):
        """Fold a completed game into team and league state (call after expect())."""
        hf, af = exp["home_factor"], exp["away_factor"]
        h, a = self._team(home), self._team(away)

        for team, actual, expected in ((h, home_xg, exp["home_xg"]), (a, away_xg, exp["away_xg"])):
            if expected > 0:
                team.resid.append((team.games, actual / expected))
                self.league_resid.append(actual / expected)

        # Venue-adjusted: remove the home/away effect before averaging.
        for team, xgf, xga, own_f, opp_f in ((h, home_xg, away_xg, hf, af),
                                            (a, away_xg, home_xg, af, hf)):
            team.off_sum = self.decay * team.off_sum + xgf / own_f
            team.def_sum = self.decay * team.def_sum + xga / opp_f
            team.weight  = self.decay * team.weight + 1.0
            team.games  += 1

        d = self.league_decay
        self.home_sum, self.home_n = d * self.home_sum + home_xg, d * self.home_n + 1
        self.away_sum, self.away_n = d * self.away_sum + away_xg, d * self.away_n + 1

    # ── Weighted bootstrap ────────────────────────────────────────────────────
    def sample(self, team: str, expected: float, n: int, rng: np.random.Generator) -> np.ndarray:
        """Draw *n* xG outcomes: expected × residuals resampled with recency weights."""
        t = self._team(team)
        if len(t.resid) >= RESIDUAL_MIN_GAMES:
            idx, resid = map(np.asarray, zip(*t.resid))
            w = 0.5 ** ((t.games - 1 - idx) / self.half_life)
            draws = rng.choice(resid, size=n, p=w / w.sum())
        elif self.league_resid:
            draws = rng.choice(np.asarray(self.league_resid), size=n)
        else:                                   # very first games of history
            draws = np.ones(n)
        return expected * draws


def win_probability(home_draws: np.ndarray, away_draws: np.ndarray,
                    rng: np.random.Generator) -> float:
    """P(home team wins), simulating goals from paired xG draws. Ties → 50/50."""
    home_goals, away_goals = rng.poisson(home_draws), rng.poisson(away_draws)
    return float(((home_goals > away_goals) + 0.5 * (home_goals == away_goals)).mean())
