import html
import time
from datetime import date

import streamlit as st

from nhl_client import (game_display, get_game_boxscore, get_games_for_date,
                        parse_player_stats, parse_team_stats)


st.title("🏒 NHL Stats Dashboard")

today = date.today()
col_date, col_refresh, col_status = st.columns([2, 1, 3])
with col_date:
    selected_date = st.date_input("Date", value=today)
with col_refresh:
    st.write("")  # vertical alignment
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
with col_status:
    st.write("")
    if selected_date == today:
        st.caption("Auto-refreshes every 30 seconds")

st.subheader(f"Games — {selected_date.strftime('%B %d, %Y')}")

games = get_games_for_date(selected_date)

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
                left, right = st.columns(2)
                def team_card(logo, abbrev, score, record):
                    center = "text-align:center"
                    if logo:
                        st.markdown(f"<div style='{center}'><img src='{logo}' width='60'></div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='{center}'><b>{abbrev}</b></div>", unsafe_allow_html=True)
                    if is_live or is_final:
                        st.markdown(f"<div style='{center};font-size:2.5rem;font-weight:bold'>{score}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='{center}'><small>{html.escape(str(record))}</small></div>", unsafe_allow_html=True)

                with left:
                    team_card(g.get("away_logo",""), g["away_abbrev"], g["away_score"], g["away_record"])
                with right:
                    team_card(g.get("home_logo",""), g["home_abbrev"], g["home_score"], g["home_record"])

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
                            width="stretch",
                        )

                        st.markdown("**Players**")
                        away_tab, home_tab = st.tabs(
                            [g["away_abbrev"], g["home_abbrev"]]
                        )
                        with away_tab:
                            st.dataframe(
                                parse_player_stats(boxscore, "awayTeam"),
                                hide_index=True,
                                width="stretch",
                            )
                        with home_tab:
                            st.dataframe(
                                parse_player_stats(boxscore, "homeTeam"),
                                hide_index=True,
                                width="stretch",
                            )

if selected_date == today:
    time.sleep(30)
    st.rerun()
