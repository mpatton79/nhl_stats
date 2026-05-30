"""
NHL Data Lake — configuration and shared constants.
"""

# ── API base URLs ─────────────────────────────────────────────────────────────
NHL_WEB_API   = "https://api-web.nhle.com/v1"
NHL_STATS_API = "https://api.nhle.com/stats/rest/en"

# ── Seasons to ingest (current season + 10-season lookback) ──────────────────
# Format: YYYYYYYY  e.g. 20142015 = 2014-15 season
# NHL seasons start in October, so months Jan-Aug belong to a season that
# started the prior calendar year.
from datetime import date as _date

def _current_season_start() -> int:
    today = _date.today()
    return today.year if today.month >= 9 else today.year - 1

_start = _current_season_start()
SEASONS = [f"{y}{y+1}" for y in range(_start - 10, _start + 1)]

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
