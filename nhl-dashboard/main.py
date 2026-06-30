import streamlit as st

st.set_page_config(page_title="NHL Stats", page_icon="🏒", layout="wide")

pg = st.navigation([
    st.Page("app.py",                      title="Games",           icon="🏒"),
    st.Page("pages/1_Standings.py",        title="Standings",       icon="📊"),
    st.Page("pages/2_Players.py",          title="Players",         icon="🏃"),
    st.Page("pages/3_Edge_Stats.py",       title="Edge Stats",      icon="⚡"),
    st.Page("pages/4_Playoff_Bracket.py",  title="Playoff Bracket", icon="🏆"),
    st.Page("pages/5_Player_Bio.py",       title="Player Bio",      icon="👤", url_path="player-bio"),
])
pg.run()
