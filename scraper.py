"""
HLTV scraper — optimized for Render + debugging issues with stuck requests.
"""

import os
import re
import random
import time
import logging
import statistics as _stats

from typing import Optional
from datetime import date, timedelta
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HLTV_BASE = "https://www.hltv.org"

# -----------------------------------------------------------------------------
# ENVIRONMENT DETECTION
# -----------------------------------------------------------------------------

ON_RENDER = "RENDER" in os.environ or "RENDER_GIT_BRANCH" in os.environ

if ON_RENDER:
    FETCH_TIMEOUT = 15
    MAX_RETRIES = 2
    logger.info("[scraper] Running on Render")
    PROXY = os.getenv("RENDER_PROXY")  # Using Render proxy support
else:
    FETCH_TIMEOUT = 30
    MAX_RETRIES = 3
    PROXY = None

# -----------------------------------------------------------------------------
# curl_cffi IMPORT
# -----------------------------------------------------------------------------

try:
    from curl_cffi import requests as _cffi_req
    _CFFI_OK = True
except ImportError:
    import requests as _cffi_req
    _CFFI_OK = False
    logger.warning("curl_cffi not installed")

# -----------------------------------------------------------------------------
# PROFILES
# -----------------------------------------------------------------------------

_PROFILES = [
    "chrome116",
    "safari17_0",
    "chrome107",
    "chrome110",
    "chrome99"
]

MAX_PROFILE_ROTATIONS = 3 if ON_RENDER else len(_PROFILES)

_profile_idx = 0

# -----------------------------------------------------------------------------
# GLOBALS
# -----------------------------------------------------------------------------

_HLTV_SESSION: Optional["_cffi_req.Session"] = None
_HLTV_SESSION_WARMED = False
_HLTV_SESSION_PROFILE = _PROFILES[0]

# Timeout adjustments to prevent stuck situations
_FETCH_RETRY_DELAYS = [1.0, 2.0, 3.0]

# -----------------------------------------------------------------------------
# CLOUDFLARE DETECTION FIXES
# -----------------------------------------------------------------------------

def _is_cloudflare_challenge(resp) -> bool:
    """Enhanced Cloudflare challenge detection."""
    if resp.status_code in (403, 429, 503):
        return True

    markers = [
        "just a moment", "__cf_bm", "cf_clearance", "checking your browser", "cf.challenge-compat"
    ]
    return any(marker in resp.text.lower() for marker in markers)

# -----------------------------------------------------------------------------
# SESSION MANAGEMENT FIXES
# -----------------------------------------------------------------------------

def _get_hltv_session():
    global _HLTV_SESSION, _HLTV_SESSION_PROFILE

    if _HLTV_SESSION is None:
        session_profile = _PROFILES[_profile_idx]
        _HLTV_SESSION = _cffi_req.Session(impersonate=session_profile)
        logger.info(f"[session] Created session for profile={session_profile}")

    return _HLTV_SESSION

# Rotate session profile and handle complete reset

def _rotate_session():
    global _HLTV_SESSION, _profile_idx

    _profile_idx = (_profile_idx + 1) % len(_PROFILES)
    next_profile = _PROFILES[_profile_idx]

    _HLTV_SESSION = _cffi_req.Session(impersonate=next_profile)
    logger.warning(f"[session] Rotated session to {next_profile}")

# -----------------------------------------------------------------------------
# FETCH FUNCTION IMPROVEMENTS
# -----------------------------------------------------------------------------

def _fetch(url: str) -> Optional[str]:
    profiles_tried = 0
    while profiles_tried < MAX_PROFILE_ROTATIONS:
        session = _get_hltv_session()
        try:
            proxies = {"http": PROXY, "https": PROXY} if PROXY else None
            resp = session.get(url, timeout=FETCH_TIMEOUT, proxies=proxies)
            logger.info(f"[fetch] Response status: {resp.status_code}")

            if resp.status_code == 200 and not _is_cloudflare_challenge(resp):
                logger.info(f"[fetch] Successfully fetched data: {len(resp.text):,} bytes")
                return resp.text
            
        except Exception as e:
            logger.error(f"[fetch] Exception occurred: {e}")
        
        profiles_tried += 1
        _rotate_session()
        time.sleep(0.5)

    logger.error(f"[fetch] All profiles failed to fetch URL: {url}")
    return None

# -----------------------------------------------------------------------------
# TEST
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    test_player = "donk"
    data = _fetch(f"{HLTV_BASE}/search?query={test_player}")
    if data:
        print("Fetch success!")
    else:
        print("Failed to fetch data.")