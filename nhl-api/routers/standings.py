import json

import duckdb
from fastapi import APIRouter, Depends, Query

from db import get_db

router = APIRouter()


@router.get("/")
def get_standings(
    season: str | None = Query(None, description="Season e.g. 20232024"),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
):
    where, params = [], []

    if season:
        where.append("season = ?")
        params.append(season)

    sql = "SELECT * FROM v_standings"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY points DESC"

    return json.loads(con.execute(sql, params).fetchdf().to_json(orient="records"))
