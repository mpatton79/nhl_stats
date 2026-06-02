import streamlit as st

import db
from utils import fmt_season

st.set_page_config(page_title="Standings · NHL Stats", page_icon="🏒", layout="wide")
st.title("Standings")

season_list = db.seasons("v_standings")
season = st.selectbox(
    "Season",
    season_list,
    format_func=fmt_season,
)

df = db.query(
    """
    SELECT
        division,
        team_abbrev        AS Team,
        games_played       AS GP,
        wins               AS W,
        losses             AS L,
        ot_losses          AS OTL,
        points             AS Pts,
        ROUND(points_pct * 100, 1) AS "Pts%",
        goals_for          AS GF,
        goals_against      AS GA,
        goal_diff          AS Diff,
        home_wins || '-' || home_losses AS Home,
        road_wins || '-' || road_losses AS Road,
        streak_code || streak_count::VARCHAR AS Streak
    FROM v_standings
    WHERE season = ?
    ORDER BY division, points DESC
    """,
    [season],
)

if df.empty:
    st.info("No standings data for this season.")
else:
    tab_all, tab_east, tab_west = st.tabs(["All", "Eastern", "Western"])

    conferences = {
        "Eastern": ["Atlantic", "Metropolitan"],
        "Western": ["Central", "Pacific"],
    }

    def render_standings(frame):
        for div, grp in frame.groupby("division", sort=False):
            st.subheader(div)
            st.dataframe(
                grp.drop(columns=["division"]).reset_index(drop=True),
                use_container_width=True,
                hide_index=True,
            )

    with tab_all:
        render_standings(df)

    with tab_east:
        east = df[df["division"].isin(conferences["Eastern"])]
        render_standings(east)

    with tab_west:
        west = df[df["division"].isin(conferences["Western"])]
        render_standings(west)
