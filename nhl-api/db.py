import os
from pathlib import Path

import duckdb

_DEFAULT_DB = Path(__file__).parent.parent / "nhl-data-lake" / "db" / "nhl.duckdb"
DB_PATH = Path(os.getenv("NHL_DB_PATH", str(_DEFAULT_DB)))


def get_db():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        yield con
    finally:
        con.close()
