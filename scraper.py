"""
HLTV scraper — optimized for Render + Cloudflare handling + Discord bot support.
Includes:
- profile rotation
- Render-safe timeouts
- Cloudflare detection
- search_player fix
- session recovery
- debugging logs
- fetch retry handling
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
    FETCH_TIMEOUT = 8
    MAX_RETRIES = 2
    logger.info("[scraper] Running on Render")
else:
    FETCH_TIMEOUT = 20
    MAX_RETRIES = 3

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

_HLTV_SESSION: Optional[object] = None
_HLTV_SESSION_WARMED = False
_HLTV_SESSION_PROFILE = _PROFILES[0]

_FETCH_RETRY_DELAYS = [1.0, 2.0, 3.0]

# -----------------------------------------------------------------------------
# PLAYER CACHE
# -----------------------------------------------------------------------------

_PLAYER_ID_CACHE = {
    "donk": ("21167", "donk", "donk"),
    "zywoo": ("11893", "zywoo", "ZywOo"),
    "m0nesy": ("19230", "m0nesy", "m0NESY"),
    "niko": ("3741", "niko", "NiKo"),
}

# -----------------------------------------------------------------------------
# CLOUDFLARE DETECTION
# -----------------------------------------------------------------------------

def _is_cloudflare_challenge(resp) -> bool:
    """Detect Cloudflare blocks/challenges."""

    if resp.status_code in (403, 429, 503):
        return True

    body = resp.text.lower()

    markers = [
        "just a moment",
        "__cf_bm",
        "cf_clearance",
        "checking your browser",
        "cf.challenge",
        "attention required",
        "cloudflare"
    ]

    return any(marker in body for marker in markers)

# -----------------------------------------------------------------------------
# SESSION MANAGEMENT
# -----------------------------------------------------------------------------

def _make_session(profile: str):
    """Create session safely."""

    try:
        session = _cffi_req.Session(
            impersonate=profile
        )

        logger.info(f"[session] Created profile={profile}")

        return session

    except Exception as e:
        logger.error(f"[session] Failed creating {profile}: {e}")
        return None

# -----------------------------------------------------------------------------

def _get_hltv_session():

    global _HLTV_SESSION
    global _HLTV_SESSION_PROFILE

    if _HLTV_SESSION is None:

        session_profile = _PROFILES[_profile_idx]

        _HLTV_SESSION = _make_session(session_profile)

        _HLTV_SESSION_PROFILE = session_profile

    return _HLTV_SESSION

# -----------------------------------------------------------------------------

def _rotate_session():

    global _HLTV_SESSION
    global _profile_idx
    global _HLTV_SESSION_PROFILE
    global _HLTV_SESSION_WARMED

    _profile_idx = (_profile_idx + 1) % len(_PROFILES)

    next_profile = _PROFILES[_profile_idx]

    logger.warning(f"[session] Rotating to {next_profile}")

    _HLTV_SESSION = _make_session(next_profile)

    _HLTV_SESSION_PROFILE = next_profile

    _HLTV_SESSION_WARMED = False

    return _HLTV_SESSION

# -----------------------------------------------------------------------------
# SESSION WARMUP
# -----------------------------------------------------------------------------

def _warm_hltv_session():

    global _HLTV_SESSION_WARMED

    if _HLTV_SESSION_WARMED:
        return

    session = _get_hltv_session()

    if session is None:
        return

    try:

        logger.info("[warmup] Visiting homepage")

        resp = session.get(
            HLTV_BASE + "/",
            timeout=FETCH_TIMEOUT
        )

        if resp.status_code == 200 and not _is_cloudflare_challenge(resp):

            logger.info("[warmup] Success")

            _HLTV_SESSION_WARMED = True

            time.sleep(0.5)

        else:

            logger.warning(
                f"[warmup] Failed status={resp.status_code}"
            )

    except Exception as e:

        logger.error(f"[warmup] Exception: {e}")

# -----------------------------------------------------------------------------
# FETCH FUNCTION
# -----------------------------------------------------------------------------

def _fetch(url: str) -> Optional[str]:

    if not _CFFI_OK:
        logger.error("[fetch] curl_cffi unavailable")
        return None

    _warm_hltv_session()

    profiles_tried = 0

    while profiles_tried < MAX_PROFILE_ROTATIONS:

        session = _get_hltv_session()

        if session is None:
            return None

        for attempt in range(MAX_RETRIES):

            try:

                logger.info(
                    f"[fetch] GET {url} "
                    f"profile={_HLTV_SESSION_PROFILE} "
                    f"attempt={attempt+1}"
                )

                print("REQUEST START")

                resp = session.get(
                    url,
                    timeout=FETCH_TIMEOUT,
                    headers={
                        "User-Agent":
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    }
                )

                print("REQUEST DONE")

                logger.info(
                    f"[fetch] status={resp.status_code}"
                )

                if (
                    resp.status_code == 200
                    and not _is_cloudflare_challenge(resp)
                    and len(resp.text) > 1000
                ):

                    logger.info(
                        f"[fetch] SUCCESS len={len(resp.text)}"
                    )

                    return resp.text

                logger.warning(
                    f"[fetch] blocked status={resp.status_code}"
                )

            except Exception as e:

                logger.error(
                    f"[fetch] exception={type(e).__name__}: {e}"
                )

            delay = _FETCH_RETRY_DELAYS[
                min(attempt, len(_FETCH_RETRY_DELAYS)-1)
            ]

            time.sleep(delay)

        profiles_tried += 1

        _rotate_session()

        time.sleep(0.5)

    logger.error(f"[fetch] FAILED {url}")

    return None

# -----------------------------------------------------------------------------
# PLAYER SEARCH
# IMPORTANT: MUST BE TOP LEVEL
# -----------------------------------------------------------------------------

def search_player(name: str):

    key = re.sub(r"[^a-z0-9]", "", name.lower())

    if key in _PLAYER_ID_CACHE:
        return _PLAYER_ID_CACHE[key]

    url = f"{HLTV_BASE}/search?query={name}"

    html = _fetch(url)

    if not html:
        return None

    matches = re.findall(
        r'/player/(\d+)/([\w-]+)',
        html
    )

    if not matches:
        logger.warning(f"[search] No player found for {name}")
        return None

    pid, slug = matches[0]

    display = slug.replace("-", " ").title()

    result = (pid, slug, display)

    _PLAYER_ID_CACHE[key] = result

    logger.info(f"[search] Found player={display}")

    return result

# -----------------------------------------------------------------------------
# GET PLAYER MATCH IDS
# -----------------------------------------------------------------------------

def get_player_match_ids(
    player_id: str,
    max_matches: int = 10
):

    url = f"{HLTV_BASE}/results?player={player_id}"

    html = _fetch(url)

    if not html:
        return []

    found = re.findall(
        r'/matches/(\d+)/([a-z0-9-]+)',
        html
    )

    unique_matches = []

    seen = set()

    for match_id, slug in found:

        if match_id not in seen:

            seen.add(match_id)

            unique_matches.append(
                (match_id, slug)
            )

    return unique_matches[:max_matches]

# -----------------------------------------------------------------------------
# MATCH PARSER
# -----------------------------------------------------------------------------

def _parse_match_kills(
    html: str,
    player_slug: str
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    slug_norm = re.sub(
        r"[^a-z0-9]",
        "",
        player_slug.lower()
    )

    maps = []

    rows = soup.find_all("tr")

    for row in rows:

        row_text = row.get_text(
            " ",
            strip=True
        )

        norm = re.sub(
            r"[^a-z0-9]",
            "",
            row_text.lower()
        )

        if slug_norm not in norm:
            continue

        kd_match = re.search(
            r'(\d+)\s*[-–]\s*(\d+)',
            row_text
        )

        if kd_match:

            kills = int(
                kd_match.group(1)
            )

            maps.append({
                "kills": kills
            })

    return {
        "maps": maps[:2]
    }

# -----------------------------------------------------------------------------
# GET PLAYER INFO
# -----------------------------------------------------------------------------

def get_player_info(
    player_name: str
):

    result = search_player(player_name)

    if not result:
        raise RuntimeError(
            f"Player '{player_name}' not found"
        )

    pid, slug, display = result

    match_ids = get_player_match_ids(
        pid,
        max_matches=10
    )

    map_kills = []

    for match_id, match_slug in match_ids:

        match_url = (
            f"{HLTV_BASE}/matches/"
            f"{match_id}/{match_slug}"
        )

        html = _fetch(match_url)

        if not html:
            continue

        parsed = _parse_match_kills(
            html,
            slug
        )

        if not parsed:
            continue

        maps = parsed.get(
            "maps",
            []
        )[:2]

        for m in maps:

            kills = m.get("kills")

            if kills is None:
                continue

            map_kills.append(kills)

    if len(map_kills) < 2:

        raise RuntimeError(
            f"No recent data found for {display}"
        )

    mean = _stats.mean(map_kills)

    std = (
        _stats.stdev(map_kills)
        if len(map_kills) > 1
        else 2.0
    )

    return {
        "player": display,
        "mean": round(mean, 2),
        "std": round(std, 2),
        "sample_size": len(map_kills),
        "recent_maps": map_kills
    }

# -----------------------------------------------------------------------------
# TEST
# -----------------------------------------------------------------------------

if __name__ == "__main__":

    print("Testing HLTV scraper...")

    try:

        result = search_player("donk")

        print(result)

        info = get_player_info("donk")

        print(info)

    except Exception as e:

        print(f"ERROR: {e}")
