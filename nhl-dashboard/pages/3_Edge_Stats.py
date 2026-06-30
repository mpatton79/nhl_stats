import streamlit as st

import db
from utils import fmt_season

st.title("Edge Stats")

season_list = db.seasons("v_skater_edge_stats")

col1, col2, col3, col4 = st.columns(4)

with col1:
    season = st.selectbox("Season", season_list, format_func=fmt_season)

teams_df = db.query(
    "SELECT DISTINCT team_abbrev FROM v_skater_edge_stats WHERE season = ? ORDER BY team_abbrev",
    [season],
)
team_options = ["All"] + teams_df["team_abbrev"].tolist()

with col2:
    team = st.selectbox("Team", team_options)

with col3:
    position = st.multiselect("Position", ["C", "L", "R", "D"], placeholder="All")

with col4:
    sort_by = st.selectbox(
        "Sort by",
        [
            "top_shot_speed_imperial",
            "max_skating_speed_imperial",
            "total_distance_imperial",
            "top_shot_speed_percentile",
            "max_skating_speed_percentile",
            "total_distance_percentile",
            "points",
        ],
        format_func=lambda x: x.replace("_imperial", " (mph/mi)")
                                .replace("_percentile", " (percentile)")
                                .replace("_", " ").title(),
    )

where = ["season = ?"]
params: list = [season]

if team != "All":
    where.append("team_abbrev = ?")
    params.append(team)

if position:
    where.append(f"position IN ({','.join('?' * len(position))})")
    params.extend(position)

df = db.query(
    f"""
    SELECT
        first_name || ' ' || last_name   AS Player,
        team_abbrev                       AS Team,
        'https://assets.nhle.com/logos/nhl/svg/' || team_abbrev || '_light.svg' AS Logo,
        position                          AS Pos,
        games_played                      AS GP,
        goals                             AS G,
        assists                           AS A,
        points                            AS Pts,
        ROUND(top_shot_speed_imperial, 1) AS "Top Shot Spd (mph)",
        ROUND(top_shot_speed_percentile * 100, 1) AS "Shot Spd Pctile",
        ROUND(max_skating_speed_imperial, 1) AS "Max Skate Spd (mph)",
        ROUND(max_skating_speed_percentile * 100, 1) AS "Skate Spd Pctile",
        ROUND(total_distance_imperial, 1) AS "Total Dist (mi)",
        ROUND(total_distance_percentile * 100, 1) AS "Dist Pctile"
    FROM v_skater_edge_stats
    WHERE {' AND '.join(where)}
    ORDER BY {sort_by} DESC NULLS LAST
    LIMIT 100
    """,
    params,
)

st.caption(f"{len(df)} players shown (max 100)")
st.dataframe(
    df,
    width="stretch",
    hide_index=True,
    column_config={
        "Logo": st.column_config.ImageColumn("", width="small"),
    },
)
