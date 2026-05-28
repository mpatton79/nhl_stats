"""
NHL Data Lake — configuration and shared constants.
"""

# ── API base URLs ─────────────────────────────────────────────────────────────
NHL_WEB_API   = "https://api-web.nhle.com/v1"
NHL_STATS_API = "https://api.nhle.com/stats/rest/en"

# ── Seasons to ingest (last 10 completed + current) ──────────────────────────
# Format: YYYYYYYY  e.g. 20142015 = 2014-15 season
SEASONS = [
    "20142015",
    "20152016",
    "20162017",
    "20172018",
    "20182019",
    "20192020",
    "20202021",
    "20212022",
    "20222023",
    "20232024",
    "20242025",
]

# 2 = regular season, 3 = playoffs
GAME_TYPES = {"regular": 2, "playoffs": 3}

# ── Filesystem layout ─────────────────────────────────────────────────────────
from pathlib import Path

ROOT        = Path(__file__).parent
RAW_DIR     = ROOT / "data" / "raw"
LAKE_DIR    = ROOT / "data" / "lake"
DB_PATH     = ROOT / "db" / "nhl.duckdb"

# ── HTTP ──────────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 30   # seconds
REQUEST_DELAY     = 0.3  # seconds between calls — be a polite API citizen
MAX_RETRIES       = 3
