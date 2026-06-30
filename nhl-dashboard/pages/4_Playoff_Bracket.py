from datetime import date, datetime

import streamlit as st

from nhl_client import _get, get_series_games

st.title("Playoff Bracket")

# ── Year selector ─────────────────────────────────────────────────────────────
current_year = date.today().year
years = list(range(current_year, 2012, -1))
year_col, _ = st.columns([1, 4])
with year_col:
    year = st.selectbox("Year", years, index=0)


@st.cache_data(ttl=300)
def get_bracket(yr: int) -> dict:
    return _get(f"/playoff-bracket/{yr}")


data = get_bracket(year)
series_list = data.get("series", [])

if not series_list:
    st.info(f"No playoff bracket data available for {year}.")
    st.stop()

# ── Team filter ────────────────────────────────────────────────────────────────
teams: dict[int, dict] = {}
for s in series_list:
    for key in ("topSeedTeam", "bottomSeedTeam"):
        t = s.get(key, {})
        if t.get("id"):
            teams[t["id"]] = {
                "name":   t.get("commonName", {}).get("default", ""),
                "abbrev": t.get("abbrev", ""),
                "logo":   t.get("logo", ""),
            }

sorted_ids = sorted(teams, key=lambda tid: teams[tid]["name"])

team_col, logo_col, _ = st.columns([2, 1, 2])
with team_col:
    selected_team = st.selectbox(
        "Filter by team",
        [None] + sorted_ids,
        format_func=lambda tid: "All Teams" if tid is None else teams[tid]["name"],
    )
with logo_col:
    st.write("")
    if selected_team:
        st.image(teams[selected_team]["logo"], width=40)

# ── Group series by round (unfiltered — preserve East/West ordering) ───────────
rounds: dict[int, list] = {}
for s in series_list:
    rounds.setdefault(s["playoffRound"], []).append(s)

def team_matches(s: dict) -> bool:
    if selected_team is None:
        return True
    ids = {s.get("topSeedTeam", {}).get("id"), s.get("bottomSeedTeam", {}).get("id")}
    return selected_team in ids

ROUND_LABELS = {
    1: "First Round",
    2: "Second Round",
    3: "Conference Finals",
    4: "Stanley Cup Final",
}


def render_series(s: dict, yr: int):
    top       = s.get("topSeedTeam", {})
    bot       = s.get("bottomSeedTeam", {})
    winner_id = s.get("winningTeamId")
    top_wins  = s.get("topSeedWins", 0)
    bot_wins  = s.get("bottomSeedWins", 0)
    total     = top_wins + bot_wins

    with st.container(border=True):
        for team, wins in [(top, top_wins), (bot, bot_wins)]:
            is_winner = team.get("id") == winner_id
            eliminated = winner_id and not is_winner
            name = team.get("commonName", {}).get("default", "TBD")
            logo = team.get("logo", "")

            logo_col, name_col, wins_col = st.columns([1, 5, 1])
            with logo_col:
                if logo:
                    st.image(logo, width=28)
            with name_col:
                if eliminated:
                    st.markdown(f"<span style='opacity:0.4'>{name}</span>", unsafe_allow_html=True)
                elif is_winner:
                    st.markdown(f"**{name}**")
                else:
                    st.write(name)
            with wins_col:
                if is_winner:
                    st.markdown(f"**{wins}**")
                else:
                    st.write(str(wins))

        if total > 0 and top.get("abbrev") and bot.get("id"):
            with st.expander(f"Games ({total})"):
                games = get_series_games(top["abbrev"], bot["id"], yr)
                for i, g in enumerate(games, 1):
                    away = g.get("awayTeam", {})
                    home = g.get("homeTeam", {})
                    away_abbrev = away.get("abbrev", "")
                    home_abbrev = home.get("abbrev", "")
                    away_score  = away.get("score")
                    home_score  = home.get("score")
                    game_date   = g.get("gameDate", "")
                    period_type = g.get("gameOutcome", {}).get("lastPeriodType", "REG")

                    suffix = "/OT" if period_type == "OT" else "/SO" if period_type == "SO" else ""

                    try:
                        date_str = datetime.strptime(game_date, "%Y-%m-%d").strftime("%b %-d")
                    except Exception:
                        date_str = game_date

                    if away_score is not None and home_score is not None:
                        if away_score > home_score:
                            score_str = f"**{away_abbrev} {away_score}**, {home_abbrev} {home_score}{suffix}"
                        else:
                            score_str = f"{away_abbrev} {away_score}, **{home_abbrev} {home_score}**{suffix}"
                    else:
                        score_str = f"{away_abbrev} @ {home_abbrev}"

                    st.markdown(f"Gm {i} · {date_str} · {score_str}")


# ── Render rounds ─────────────────────────────────────────────────────────────
for round_num in sorted(rounds.keys()):
    all_series = rounds[round_num]

    if round_num == 4:
        if not team_matches(all_series[0]):
            continue
        st.subheader(ROUND_LABELS.get(round_num, f"Round {round_num}"))
        _, mid, _ = st.columns([1, 2, 1])
        with mid:
            render_series(all_series[0], year)
    else:
        mid = len(all_series) // 2
        east = [s for s in all_series[:mid] if team_matches(s)]
        west = [s for s in all_series[mid:] if team_matches(s)]

        if not east and not west:
            continue

        st.subheader(ROUND_LABELS.get(round_num, f"Round {round_num}"))

        if east and west:
            col_east, col_west = st.columns(2)
            with col_east:
                st.caption("Eastern Conference")
                for s in east:
                    render_series(s, year)
            with col_west:
                st.caption("Western Conference")
                for s in west:
                    render_series(s, year)
        elif east:
            col, _ = st.columns(2)
            with col:
                st.caption("Eastern Conference")
                for s in east:
                    render_series(s, year)
        else:
            _, col = st.columns(2)
            with col:
                st.caption("Western Conference")
                for s in west:
                    render_series(s, year)

    st.divider()
