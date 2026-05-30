import json

import duckdb
from fastapi import APIRouter, Depends, Path, Query

from db import get_db

router = APIRouter()


@router.get("/{team}")
def get_roster(
    team: str = Path(..., description="Team abbreviation e.g. BOS"),
    season: str | None = Query(None, description="Season e.g. 20232024"),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
):
    where = ["team_abbrev = ?"]
    params = [team.upper()]

    if season:
        where.append("season = ?")
        params.append(season)

    sql = (
        "SELECT * FROM raw_rosters"
        " WHERE " + " AND ".join(where) +
        " ORDER BY position_type, last_name"
    )

    return json.loads(con.execute(sql, params).fetchdf().to_json(orient="records"))
