import streamlit as st

import db
from utils import fmt_season

st.title("Player Stats")

season_list = db.seasons("v_skater_stats")

col1, col2, col3, col4 = st.columns(4)

with col1:
    season = st.selectbox("Season", season_list, format_func=fmt_season)

teams_df = db.query(
    "SELECT DISTINCT team_abbrev FROM v_skater_stats WHERE season = ? ORDER BY team_abbrev",
    [season],
)
team_options = ["All"] + teams_df["team_abbrev"].tolist()

players_df = db.query(
    "SELECT DISTINCT player_name FROM v_skater_stats WHERE season = ? ORDER BY player_name",
    [season],
)

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

selected_players = st.multiselect(
    "Players", players_df["player_name"].tolist(), placeholder="Search players..."
)

where = ["season = ?"]
params: list = [season]

if team != "All":
    where.append("CONTAINS(team_abbrev, ?)")
    params.append(team)

if position != "All":
    where.append("position = ?")
    params.append(position)

if selected_players:
    where.append(f"player_name IN ({','.join('?' * len(selected_players))})")
    params.extend(selected_players)

df = db.query(
    f"""
    SELECT
        player_id,
        player_name                                    AS Player,
        REPLACE(team_abbrev, ',', ' / ')               AS Team,
        'https://assets.nhle.com/logos/nhl/svg/' || SPLIT_PART(team_abbrev, ',', 1) || '_light.svg' AS Logo,
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
        FLOOR(toi_per_game / 60)::INTEGER || ':' || LPAD((toi_per_game % 60)::INTEGER::VARCHAR, 2, '0') AS "TOI/GP",
        ROUND(points_per_game, 2)   AS "P/GP"
    FROM v_skater_stats
    WHERE {' AND '.join(where)}
    ORDER BY {sort_by} DESC NULLS LAST
    LIMIT 100
    """,
    params,
)

st.caption(f"{len(df)} players shown (max 100) · Check a box to view player bio and stats history")
event = st.dataframe(
    df.drop(columns=["player_id"]),
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "Logo": st.column_config.ImageColumn("", width="small"),
    },
)

if event.selection.rows:
    idx = event.selection.rows[0]
    st.session_state["bio_player_id"] = int(df.iloc[idx]["player_id"])
    st.switch_page("pages/5_Player_Bio.py")
