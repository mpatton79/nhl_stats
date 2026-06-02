import streamlit as st

import db
from utils import fmt_season

st.set_page_config(page_title="Players · NHL Stats", page_icon="🏒", layout="wide")
st.title("Player Stats")

season_list = db.seasons("v_skater_stats")

col1, col2, col3, col4 = st.columns(4)

with col1:
    season = st.selectbox("Season", season_list, format_func=fmt_season)

# Load teams for this season
teams_df = db.query(
    "SELECT DISTINCT team_abbrev FROM v_skater_stats WHERE season = ? ORDER BY team_abbrev",
    [season],
)
team_options = ["All"] + teams_df["team_abbrev"].tolist()

with col2:
    team = st.selectbox("Team", team_options)

with col3:
    position = st.selectbox("Position", ["All", "C", "L", "R", "D"])

with col4:
    sort_by = st.selectbox(
        "Sort by",
        ["points", "goals", "assists", "plus_minus", "shots", "shooting_pct", "toi_per_game"],
        format_func=lambda x: x.replace("_", " ").title(),
    )

where = ["season = ?"]
params: list = [season]

if team != "All":
    where.append("CONTAINS(team_abbrev, ?)")
    params.append(team)

if position != "All":
    where.append("position = ?")
    params.append(position)

df = db.query(
    f"""
    SELECT
        player_name                                    AS Player,
        REPLACE(team_abbrev, ',', ' / ')               AS Team,
        position            AS Pos,
        games_played        AS GP,
        goals               AS G,
        assists             AS A,
        points              AS Pts,
        plus_minus          AS "+/-",
        pim                 AS PIM,
        pp_goals            AS PPG,
        sh_goals            AS SHG,
        shots               AS SOG,
        ROUND(shooting_pct, 1)      AS "S%",
        toi_per_game        AS TOI,
        ROUND(points_per_game, 2)   AS "P/GP"
    FROM v_skater_stats
    WHERE {' AND '.join(where)}
    ORDER BY {sort_by} DESC NULLS LAST
    LIMIT 100
    """,
    params,
)

st.caption(f"{len(df)} players shown (max 100)")
st.dataframe(df, use_container_width=True, hide_index=True)
