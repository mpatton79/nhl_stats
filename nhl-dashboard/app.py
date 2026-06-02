import time
from datetime import date

import streamlit as st

from nhl_client import (game_display, get_game_boxscore, get_todays_games,
                        parse_player_stats, parse_team_stats)

st.set_page_config(page_title="NHL Stats", page_icon="🏒", layout="wide")

st.title("🏒 NHL Stats Dashboard")
st.subheader(f"Today's Games — {date.today().strftime('%B %d, %Y')}")

col_refresh, col_status = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Refresh now"):
        st.cache_data.clear()
        st.rerun()
with col_status:
    st.caption("Auto-refreshes every 30 seconds")

games = get_todays_games()

if not games:
    st.info("No games scheduled today.")
else:
    cols = st.columns(3)
    for i, raw in enumerate(games):
        g = game_display(raw)
        with cols[i % 3]:
            with st.container(border=True):
                is_live = g["state"] == "LIVE"
                is_final = g["state"] in ("OFF", "FINAL")
                is_playoff = g["game_type"] == 3

                # Series status for playoffs
                if is_playoff and g["series_status"]:
                    st.caption(g["series_status"])

                # Teams + scores
                left, mid, right = st.columns([2, 1, 2])
                with left:
                    if g.get("away_logo"):
                        st.image(g["away_logo"], width=60)
                    st.markdown(f"**{g['away_abbrev']}**")
                    st.caption(g["away_record"])
                with mid:
                    if is_live or is_final:
                        st.markdown(f"### {g['away_score']} — {g['home_score']}")
                    else:
                        st.markdown("### @")
                with right:
                    if g.get("home_logo"):
                        st.image(g["home_logo"], width=60)
                    st.markdown(f"**{g['home_abbrev']}**")
                    st.caption(g["home_record"])

                # Status
                if is_live:
                    st.markdown(f"🔴 **{g['state_str']}**")
                else:
                    st.caption(g["state_str"])

                st.caption(g["venue"])

                # Game stats expander (live + final only)
                if is_live or is_final:
                    with st.expander("Game Stats"):
                        boxscore = get_game_boxscore(raw["id"])

                        st.markdown("**Team Stats**")
                        st.dataframe(
                            parse_team_stats(boxscore),
                            hide_index=True,
                            use_container_width=True,
                        )

                        st.markdown("**Players**")
                        away_tab, home_tab = st.tabs(
                            [g["away_abbrev"], g["home_abbrev"]]
                        )
                        with away_tab:
                            st.dataframe(
                                parse_player_stats(boxscore, "awayTeam"),
                                hide_index=True,
                                use_container_width=True,
                            )
                        with home_tab:
                            st.dataframe(
                                parse_player_stats(boxscore, "homeTeam"),
                                hide_index=True,
                                use_container_width=True,
                            )

time.sleep(30)
st.rerun()
