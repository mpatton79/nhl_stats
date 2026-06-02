import os
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

_DEFAULT_DB = Path(__file__).parent.parent / "nhl-data-lake" / "db" / "nhl.duckdb"
DB_PATH = Path(os.getenv("NHL_DB_PATH", str(_DEFAULT_DB)))


@st.cache_resource
def _conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=True)


@st.cache_data(ttl=300)
def query(sql: str, params: list | None = None) -> pd.DataFrame:
    return _conn().execute(sql, params or []).fetchdf()


def seasons(view: str = "v_skater_stats") -> list[str]:
    df = query(f"SELECT DISTINCT season FROM {view} ORDER BY season DESC")
    return df["season"].tolist()
