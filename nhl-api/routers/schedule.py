import json

import duckdb
from fastapi import APIRouter, Depends, Query

from db import get_db

router = APIRouter()


@router.get("/")
def get_schedule(
    team: str | None = Query(None, description="Team abbreviation e.g. BOS"),
    season: str | None = Query(None, description="Season e.g. 20232024"),
    game_type: str | None = Query(None, description="regular or playoffs"),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
):
    where, params = [], []

    if team:
        where.append("(home_team = ? OR away_team = ?)")
        params += [team.upper(), team.upper()]
    if season:
        where.append("season = ?")
        params.append(season)
    if game_type:
        where.append("game_type = ?")
        params.append("Regular" if game_type.lower() == "regular" else "Playoffs")

    sql = "SELECT * FROM v_games"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY game_date"

    return json.loads(con.execute(sql, params).fetchdf().to_json(orient="records"))
