"""
Shared feature pipeline for the xG model — used by both training and scoring
so the two can never drift apart.

  load_shots()  — pull unblocked shot attempts from DuckDB, with sequence
                  features (previous event, previous attempt, running score)
                  computed over the FULL play stream before any filtering.
  engineer()    — vectorised geometry / strength / context features.
  model_frame() — apply the modelling filters and the categorical contract.
"""

import duckdb
import numpy as np
import pandas as pd

from .config import (CATEGORIES, NET_X, REBOUND_SECONDS, RUSH_SECONDS, REGULAR,
                     SEASON_BASE_YEAR)

_SHOT_ATTEMPTS = "('shot-on-goal', 'missed-shot', 'goal', 'blocked-shot')"
_UNBLOCKED     = "('shot-on-goal', 'missed-shot', 'goal')"


def load_shots(con: duckdb.DuckDBPyConnection, seasons: list[str],
               game_types: tuple[int, ...] = (REGULAR,)) -> pd.DataFrame:
    """Unblocked shot attempts for *seasons*, with sequence context attached."""
    season_list = ", ".join(str(int(s)) for s in seasons)
    type_list   = ", ".join(str(int(t)) for t in game_types)

    sql = f"""
    WITH ev AS (
        SELECT
            ROW_NUMBER() OVER () AS rid,
            p.game_id, CAST(p.season AS VARCHAR) AS season, p.game_date,
            p.period, p.sort_order, p.event_id, p.event_type,
            p.team_abbrev AS owner_id,               -- eventOwnerTeamId
            p.home_team_id, p.away_team_id,
            p.x_coord AS x, p.y_coord AS y, p.zone_code, p.shot_type,
            CAST(COALESCE(p.shooting_player_id, p.scoring_player_id) AS BIGINT) AS shooter_id,
            p.goalie_player_id, p.situation_code,
            CAST(split_part(p.time_in_period, ':', 1) AS INT) * 60
              + CAST(split_part(p.time_in_period, ':', 2) AS INT) AS secs,
            -- Team that took the attempt. Blocked shots are owned by the blocking team.
            CASE
                WHEN p.event_type = 'blocked-shot' THEN
                    CASE WHEN p.team_abbrev = p.home_team_id THEN p.away_team_id ELSE p.home_team_id END
                WHEN p.event_type IN {_UNBLOCKED} THEN p.team_abbrev
            END AS shot_team_id
        FROM raw_plays p
        JOIN raw_games g ON g.game_id = p.game_id
        WHERE p.season IN ({season_list})
          AND g.game_type IN ({type_list})
          AND p.period_type <> 'SO'                  -- shootouts are not game play
    ),
    seq AS (
        SELECT *,
            LAG(event_type)                       OVER w_evt AS prev_event_type,
            LAG(owner_id)                         OVER w_evt AS prev_owner_id,
            LAG(COALESCE(shot_team_id, owner_id)) OVER w_evt AS prev_actor_id,
            LAG(x)                                OVER w_evt AS prev_x,
            LAG(y)                                OVER w_evt AS prev_y,
            LAG(zone_code)                        OVER w_evt AS prev_zone_code,
            LAG(secs)                             OVER w_evt AS prev_secs,
            COALESCE(SUM(CASE WHEN event_type = 'goal' AND owner_id = home_team_id THEN 1 ELSE 0 END)
                     OVER w_cum, 0) AS home_goals_before,
            COALESCE(SUM(CASE WHEN event_type = 'goal' AND owner_id = away_team_id THEN 1 ELSE 0 END)
                     OVER w_cum, 0) AS away_goals_before
        FROM ev
        WINDOW
            w_evt AS (PARTITION BY game_id, period ORDER BY sort_order, event_id),
            w_cum AS (PARTITION BY game_id ORDER BY period, sort_order, event_id
                      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
    ),
    att AS (                                         -- previous attempt by the same team
        SELECT rid,
            LAG(secs) OVER w_att AS prev_att_secs,
            LAG(x)    OVER w_att AS prev_att_x,
            LAG(y)    OVER w_att AS prev_att_y
        FROM ev
        WHERE event_type IN {_SHOT_ATTEMPTS}
        WINDOW w_att AS (PARTITION BY game_id, period, shot_team_id ORDER BY sort_order, event_id)
    )
    SELECT s.* EXCLUDE (rid), a.prev_att_secs, a.prev_att_x, a.prev_att_y,
           pl.shoots_catches AS shot_hand
    FROM seq s
    JOIN att a USING (rid)
    LEFT JOIN raw_players pl ON pl.player_id = s.shooter_id
    WHERE s.event_type IN {_UNBLOCKED}
    """
    return con.execute(sql).df()


def engineer(df: pd.DataFrame) -> pd.DataFrame:
    """Add model features. Vectorised; safe on any output of load_shots()."""
    df = df.copy()
    # DuckDB returns nullable (pd.NA) numeric dtypes; use plain floats so NaN
    # propagates through numpy ops instead of raising.
    for col in df.columns:
        if isinstance(df[col].dtype, pd.api.extensions.ExtensionDtype) and \
                pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].astype("float64")

    # ── Strength / goalie state from situationCode ────────────────────────────
    # Layout: [away goalie][away skaters][home skaters][home goalie]
    sc = df["situation_code"].fillna("").astype(str)
    df["valid_situation"] = sc.str.fullmatch(r"\d{4}")
    sc = sc.where(df["valid_situation"], "0000")
    away_g, away_sk = sc.str[0] == "1", sc.str[1].astype(int)
    home_sk, home_g = sc.str[2].astype(int), sc.str[3] == "1"

    is_home = (df["shot_team_id"] == df["home_team_id"]).to_numpy()
    df["is_home"]           = is_home.astype(int)
    df["shooter_skaters"]   = np.where(is_home, home_sk, away_sk)
    df["defending_skaters"] = np.where(is_home, away_sk, home_sk)
    df["empty_net"]         = (~np.where(is_home, away_g, home_g)).astype(int)
    df["extra_attacker"]    = (~np.where(is_home, home_g, away_g)).astype(int)  # own goalie pulled
    diff = df["shooter_skaters"] - df["defending_skaters"]
    # A pulled goalie inflates the skater count; it isn't a power play.
    diff = diff - df["extra_attacker"]
    df["strength_state"] = np.select([diff > 0, diff < 0], ["PP", "SH"], "EV")

    # ── Score state (shooting team's goal differential before the shot) ───────
    own = np.where(is_home, df["home_goals_before"], df["away_goals_before"])
    opp = np.where(is_home, df["away_goals_before"], df["home_goals_before"])
    df["score_diff"] = np.clip(own - opp, -4, 4)

    # ── Geometry: normalise so every shot attacks the net at +x ───────────────
    # Applied to x AND y (rotating the rink 180°), otherwise wing/angle are
    # mirrored for every shot taken toward the -x end.
    sign = np.where(df["x"] < 0, -1.0, 1.0)
    xn, yn = df["x"] * sign, df["y"] * sign
    df["x_norm"], df["y_norm"] = xn, yn
    dx = NET_X - xn
    df["shot_distance"] = np.hypot(dx, yn)
    signed_angle = np.degrees(np.arctan2(yn, dx))   # atan2: correct behind the net too
    df["shot_angle"] = np.abs(signed_angle)

    # Coarse zone grid: depth band (10/20/30) + lateral band (1/2/3); 0 = outside grid
    depth = np.select([(xn >= 25) & (xn < 47), (xn >= 47) & (xn < 68), (xn >= 68) & (xn <= NET_X)],
                      [10, 20, 30], 0)
    lateral = np.select([yn < -14, yn.abs() <= 14, yn > 14], [1, 2, 3], 0)
    df["shot_zone"] = np.where(depth > 0, depth + lateral, 0)

    # Wing from the shooter's view facing the net: y > 0 is the shooter's LEFT.
    # (Verified on the data: L-shot defencemen take 73% of point shots from y > 0.)
    df["shot_wing"] = np.select([yn > 0, yn < 0], ["L", "R"], "C")
    hand = df["shot_hand"].where(df["shot_hand"].isin(["L", "R"]))
    df["off_wing"] = np.where(hand.isna() | (df["shot_wing"] == "C"), np.nan,
                              (df["shot_wing"] != hand).astype(float))

    # ── Previous attempt by the same team (rebounds) ──────────────────────────
    df["time_since_prev_attempt"] = df["secs"] - df["prev_att_secs"]
    df["is_rebound"] = (df["time_since_prev_attempt"] <= REBOUND_SECONDS).astype(int)
    prev_att_angle = np.degrees(np.arctan2(df["prev_att_y"] * sign, NET_X - df["prev_att_x"] * sign))
    df["rebound_angle_change"] = np.where(
        df["is_rebound"] == 1, np.abs(signed_angle - prev_att_angle), 0.0)

    # ── Previous event (any team) ─────────────────────────────────────────────
    df["prev_event_type"] = df["prev_event_type"].fillna("none")
    df["time_since_prev_event"] = df["secs"] - df["prev_secs"]
    df["prev_same_team"] = np.where(df["prev_actor_id"].isna(), np.nan,
                                    (df["prev_actor_id"] == df["shot_team_id"]).astype(float))
    # zone_code is relative to the event owner — re-express relative to the shooting team
    same_owner = df["prev_owner_id"] == df["shot_team_id"]
    flipped = df["prev_zone_code"].map({"O": "D", "D": "O", "N": "N"})
    df["prev_zone_rel"] = df["prev_zone_code"].where(same_owner, flipped)
    pxn, pyn = df["prev_x"] * sign, df["prev_y"] * sign
    df["prev_event_distance"] = np.hypot(xn - pxn, yn - pyn)
    df["speed_from_prev"] = df["prev_event_distance"] / df["time_since_prev_event"].clip(lower=1)
    df["is_rush"] = ((df["time_since_prev_event"] <= RUSH_SECONDS)
                     & df["prev_zone_rel"].isin(["N", "D"])).astype(int)

    # ── Game clock / target ───────────────────────────────────────────────────
    df["game_seconds"] = (df["period"] - 1) * 1200 + df["secs"]
    df["season_idx"] = df["season"].astype(str).str[:4].astype(int) - SEASON_BASE_YEAR
    df["is_goal"] = (df["event_type"] == "goal").astype(int)

    for col, cats in CATEGORIES.items():
        df[col] = pd.Categorical(df[col], categories=cats)
    return df


def model_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Rows the model is defined on (applied identically at train and score time)."""
    mask = (
        df["valid_situation"]
        & (df["empty_net"] == 0)                    # empty-net goals are near-certain; out of scope
        & (df["shooter_skaters"] >= 3)              # drops penalty shots (1-on-0 situations)
        & (df["defending_skaters"] >= 3)
        & df["x"].notna() & df["y"].notna()
        & (df["zone_code"] == "O")
        & ((df["shot_team_id"] == df["home_team_id"]) | (df["shot_team_id"] == df["away_team_id"]))
    )
    return df.loc[mask].reset_index(drop=True)
