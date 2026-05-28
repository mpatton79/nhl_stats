"""
Shared HTTP helpers — retries, rate limiting, caching to raw JSON.
"""

import json
import time
import logging
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import REQUEST_TIMEOUT, REQUEST_DELAY, MAX_RETRIES

logger = logging.getLogger(__name__)


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "nhl-data-lake/1.0 (personal analytics project)",
        "Accept": "application/json",
    })
    return session


_SESSION = _build_session()


def get_json(url: str, params: dict = None) -> dict | list | None:
    """Fetch JSON from *url*, respecting the rate-limit delay."""
    try:
        resp = _SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        time.sleep(REQUEST_DELAY)
        return resp.json()
    except requests.HTTPError as e:
        logger.warning("HTTP %s for %s", e.response.status_code, url)
        return None
    except Exception as e:
        logger.error("Request failed for %s: %s", url, e)
        return None


def fetch_and_cache(url: str, cache_path: Path, params: dict = None, force: bool = False) -> dict | list | None:
    """
    Fetch *url* and save raw JSON to *cache_path*.
    Returns cached data if file already exists (unless force=True).
    """
    if cache_path.exists() and not force:
        with open(cache_path) as f:
            return json.load(f)

    data = get_json(url, params=params)
    if data is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(data, f)
    return data
