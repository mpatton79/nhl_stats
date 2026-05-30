import json

import duckdb
from fastapi import APIRouter, Depends, Query

from db import get_db

router = APIRouter()

_SKATER_SORT = {"points", "goals", "assists", "games_played", "plus_minus", "shooting_pct", "toi_per_game"}
_GOALIE_SORT = {"wins", "gaa", "save_pct", "shutouts", "games_played", "goals_against"}


@router.get("/skaters")
def get_skater_stats(
    season: str | None = Query(None, description="Season e.g. 20232024"),
    team: str | None = Query(None, description="Team abbreviation e.g. BOS"),
    player_name: str | None = Query(None, description="Partial name search"),
    sort_by: str = Query("points", description="Column to sort by"),
    limit: int = Query(50, ge=1, le=500),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
):
    sort_col = sort_by if sort_by in _SKATER_SORT else "points"
    where, params = [], []

    if season:
        where.append("season = ?")
        params.append(season)
    if team:
        where.append("team_abbrev = ?")
        params.append(team.upper())
    if player_name:
        where.append("lower(player_name) LIKE ?")
        params.append(f"%{player_name.lower()}%")

    sql = "SELECT * FROM v_skater_stats"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {sort_col} DESC NULLS LAST LIMIT ?"
    params.append(limit)

    return json.loads(con.execute(sql, params).fetchdf().to_json(orient="records"))


@router.get("/goalies")
def get_goalie_stats(
    season: str | None = Query(None, description="Season e.g. 20232024"),
    team: str | None = Query(None, description="Team abbreviation e.g. BOS"),
    player_name: str | None = Query(None, description="Partial name search"),
    sort_by: str = Query("wins", description="Column to sort by"),
    limit: int = Query(50, ge=1, le=500),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
):
    sort_col = sort_by if sort_by in _GOALIE_SORT else "wins"
    where, params = [], []

    if season:
        where.append("season = ?")
        params.append(season)
    if team:
        where.append("team_abbrev = ?")
        params.append(team.upper())
    if player_name:
        where.append("lower(player_name) LIKE ?")
        params.append(f"%{player_name.lower()}%")

    sql = "SELECT * FROM v_goalie_stats"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {sort_col} DESC NULLS LAST LIMIT ?"
    params.append(limit)

    return json.loads(con.execute(sql, params).fetchdf().to_json(orient="records"))
