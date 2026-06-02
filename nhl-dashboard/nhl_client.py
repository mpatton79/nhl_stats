from datetime import date, datetime, timezone, timedelta

import pandas as pd
import requests
import streamlit as st

_BASE = "https://api-web.nhle.com/v1"
_TIMEOUT = 10


def _get(path: str) -> dict:
    resp = requests.get(f"{_BASE}{path}", timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=30)
def get_game_boxscore(game_id: int) -> dict:
    return _get(f"/gamecenter/{game_id}/boxscore")


def parse_team_stats(boxscore: dict) -> pd.DataFrame:
    rows = []
    for side in ("awayTeam", "homeTeam"):
        team = boxscore.get(side, {})
        pgs = boxscore.get("playerByGameStats", {}).get(side, {})
        skaters = pgs.get("forwards", []) + pgs.get("defense", [])
        rows.append({
            "Team":     team.get("abbrev", side),
            "SOG":      team.get("sog", 0),
            "Hits":     sum(s.get("hits", 0) for s in skaters),
            "Blocks":   sum(s.get("blockedShots", 0) for s in skaters),
            "PP Goals": sum(s.get("powerPlayGoals", 0) for s in skaters),
        })
    return pd.DataFrame(rows)


def parse_player_stats(boxscore: dict, side: str) -> pd.DataFrame:
    pgs = boxscore.get("playerByGameStats", {}).get(side, {})
    skaters = pgs.get("forwards", []) + pgs.get("defense", [])
    rows = []
    for s in skaters:
        rows.append({
            "Player": s.get("name", {}).get("default", ""),
            "Pos":    s.get("position", ""),
            "G":      s.get("goals", 0),
            "A":      s.get("assists", 0),
            "Pts":    s.get("points", 0),
            "SOG":    s.get("sog", 0),
            "TOI":    s.get("toi", ""),
        })
    return pd.DataFrame(rows).sort_values("Pts", ascending=False)


@st.cache_data(ttl=30)
def get_todays_games() -> list[dict]:
    today = date.today().strftime("%Y-%m-%d")
    return _get(f"/score/{today}").get("games", [])


def game_display(game: dict) -> dict:
    """Flatten a raw game dict into display-ready fields."""
    home = game.get("homeTeam", {})
    away = game.get("awayTeam", {})
    state = game.get("gameState", "")

    # Parse start time to Eastern
    start_utc = game.get("startTimeUTC", "")
    start_et = ""
    if start_utc:
        dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
        offset = game.get("easternUTCOffset", "-05:00")
        sign = 1 if offset[0] == "+" else -1
        h, m = map(int, offset[1:].split(":"))
        et = dt + timedelta(hours=sign * h, minutes=sign * m)
        start_et = et.strftime("%-I:%M %p ET")

    if state == "LIVE":
        pd_desc = game.get("periodDescriptor", {})
        period = pd_desc.get("number", "")
        p_type = pd_desc.get("periodType", "REG")
        clock = game.get("clock", {}).get("timeRemaining", "")
        if p_type == "OT":
            state_str = f"LIVE · OT {clock}"
        elif p_type == "SO":
            state_str = "LIVE · SO"
        else:
            state_str = f"LIVE · P{period} {clock}"
    elif state in ("OFF", "FINAL"):
        pd_desc = game.get("periodDescriptor", {})
        p_type = pd_desc.get("periodType", "REG")
        suffix = " (OT)" if p_type == "OT" else " (SO)" if p_type == "SO" else ""
        state_str = f"Final{suffix}"
    else:
        state_str = start_et or "Scheduled"

    return {
        "away_abbrev":   away.get("abbrev", ""),
        "home_abbrev":   home.get("abbrev", ""),
        "away_score":    away.get("score", ""),
        "home_score":    home.get("score", ""),
        "away_record":   away.get("record", ""),
        "home_record":   home.get("record", ""),
        "away_logo":     away.get("logo", ""),
        "home_logo":     home.get("logo", ""),
        "state":         state,
        "state_str":     state_str,
        "venue":         game.get("venue", {}).get("default", ""),
        "game_type":     game.get("gameType", 2),
        "series_status": game.get("seriesStatus", {}).get("seriesAbbrev", ""),
    }
