import html
import time
from datetime import date

import streamlit as st

import db
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
forecasts = db.game_forecasts(selected_date)
actuals = db.game_actual_xg(selected_date)

if not games:
    st.info("No games scheduled today.")
else:
    cols = st.columns(3)
    for i, raw in enumerate(games):
        g = game_display(raw)
        fc = forecasts.get(raw["id"])
        ax = actuals.get(raw["id"])
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
                def team_card(logo, abbrev, score, record, xg=None, win=None, actual=None, attempts=None):
                    center = "text-align:center"
                    if logo:
                        st.markdown(f"<div style='{center}'><img src='{logo}' width='60'></div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='{center}'><b>{abbrev}</b></div>", unsafe_allow_html=True)
                    if is_live or is_final:
                        st.markdown(f"<div style='{center};font-size:2.5rem;font-weight:bold'>{score}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='{center}'><small>{html.escape(str(record))}</small></div>", unsafe_allow_html=True)
                    if actual is not None:
                        st.markdown(f"<div style='{center}'><b>{actual:.2f} xG</b> <small>· {attempts} attempts</small></div>", unsafe_allow_html=True)
                    if xg is not None:
                        pct = f"{win:.0%} to win"
                        pct = f"<b>{pct}</b>" if win >= 0.5 and actual is None else pct
                        proj = f"proj. {xg:.2f}" if actual is not None else f"{xg:.2f} xG"
                        st.markdown(f"<div style='{center}'><small>{proj} · {pct}</small></div>", unsafe_allow_html=True)

                with left:
                    team_card(g.get("away_logo",""), g["away_abbrev"], g["away_score"], g["away_record"],
                              fc and fc["away_xg"], fc and 1 - fc["p_home_win"],
                              ax and ax["away_xg"], ax and ax["away_attempts"])
                with right:
                    team_card(g.get("home_logo",""), g["home_abbrev"], g["home_score"], g["home_record"],
                              fc and fc["home_xg"], fc and fc["p_home_win"],
                              ax and ax["home_xg"], ax and ax["home_attempts"])

                if fc or ax:
                    notes = []
                    if ax:
                        notes.append(
                            "**Actual xG** adds up the shot model's goal probability for each "
                            "unblocked shot attempt (goals, saves and misses). Blocked, empty-net, "
                            "shootout and penalty shots aren't counted, so attempts won't match "
                            "official shots on goal."
                        )
                    if fc:
                        notes.append(
                            f"**{'Proj.' if ax else 'Forecast'}** xG and win probability come from the "
                            f"pre-game forecast made {fc['forecast_date']:%b %d}, using games through "
                            f"{date.fromisoformat(str(fc['ratings_through'])[:10]):%b %d}. "
                            f"80% xG range: {g['away_abbrev']} {fc['away_xg_p10']:.1f}–{fc['away_xg_p90']:.1f}, "
                            f"{g['home_abbrev']} {fc['home_xg_p10']:.1f}–{fc['home_xg_p90']:.1f}."
                        )
                    label = "Actual xG · pre-game forecast" if ax and fc else "Actual xG" if ax else "Pre-game forecast"
                    st.caption(label, help="\n\n".join(notes))

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
