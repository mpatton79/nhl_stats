from datetime import date

import streamlit as st

import db
from utils import fmt_season

player_id = st.session_state.get("bio_player_id")
if not player_id:
    st.info("Select a player from the Players page.")
    st.stop()

bio_df = db.query("SELECT * FROM raw_players WHERE player_id = ?", [player_id])
if bio_df.empty:
    st.error("Player not found.")
    st.stop()

bio = bio_df.iloc[0]

if st.button("← Back to Players"):
    st.switch_page("pages/2_Players.py")

st.divider()

# ── Header ────────────────────────────────────────────────────────────────────
headshot_col, info_col = st.columns([1, 3])

with headshot_col:
    if bio.get("headshot_url"):
        st.image(bio["headshot_url"], width=160)

with info_col:
    num = f"#{int(bio['jersey_number'])}" if bio.get("jersey_number") and str(bio["jersey_number"]) != "nan" else ""
    st.title(f"{bio['first_name']} {bio['last_name']}")
    st.subheader(f"{num}  ·  {bio.get('position', '')}  ·  {bio.get('shoots_catches', '')}H")

    h = bio.get("height_inches")
    height_str = f"{int(h) // 12}'{int(h) % 12}\"" if h and str(h) != "nan" else "—"

    w = bio.get("weight_lbs")
    weight_str = f"{int(w)} lbs" if w and str(w) != "nan" else "—"

    bd = bio.get("birth_date", "")
    try:
        age = (date.today() - date.fromisoformat(str(bd))).days // 365
        birth_str = f"{bd}  (age {age})"
    except Exception:
        birth_str = str(bd) if bd else "—"

    city    = bio.get("birth_city", "") or ""
    country = bio.get("birth_country", "") or ""
    birthplace = ", ".join(filter(None, [city, country])) or "—"

    dy = bio.get("draft_year")
    if dy and str(dy) != "nan":
        draft_str = f"{int(dy)}, Rd {int(bio['draft_round'])} Pk {int(bio['draft_pick'])} ({bio.get('draft_team', '')})"
    else:
        draft_str = "Undrafted"

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Height:** {height_str}")
        st.markdown(f"**Weight:** {weight_str}")
        st.markdown(f"**Born:** {birth_str}")
    with c2:
        st.markdown(f"**Birthplace:** {birthplace}")
        st.markdown(f"**Draft:** {draft_str}")

# ── Career stats ──────────────────────────────────────────────────────────────
st.divider()
st.subheader("Recent Career Stats")

career_df = db.query(
    """
    SELECT
        season,
        REPLACE(team_abbrev, ',', ' / ')    AS Team,
        games_played    AS GP,
        goals           AS G,
        assists         AS A,
        points          AS Pts,
        plus_minus      AS "+/-",
        pim             AS PIM,
        pp_goals        AS PPG,
        sh_goals        AS SHG,
        shots           AS SOG,
        ROUND(shooting_pct, 1)  AS "S%",
        FLOOR(toi_per_game / 60)::INTEGER || ':' || LPAD((toi_per_game % 60)::INTEGER::VARCHAR, 2, '0') AS "TOI/GP",
        ROUND(points_per_game, 2) AS "P/GP"
    FROM v_skater_stats
    WHERE player_id = ?
    ORDER BY season DESC
    """,
    [player_id],
)

if career_df.empty:
    st.info("No career stats available.")
else:
    career_df["season"] = career_df["season"].apply(fmt_season)
    st.dataframe(career_df, width="stretch", hide_index=True)
