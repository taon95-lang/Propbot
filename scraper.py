"""
HLTV scraper — uses curl_cffi Chrome impersonation against accessible HLTV endpoints.
Production-safe version for Render + GitHub deployment.
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
    FETCH_TIMEOUT = 10
    MAX_RETRIES = 2
    logger.info("[scraper] Running on Render")
else:
    FETCH_TIMEOUT = 25
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

MAX_PROFILE_ROTATIONS = 2 if ON_RENDER else len(_PROFILES)

_profile_idx = 0

# -----------------------------------------------------------------------------
# GLOBALS
# -----------------------------------------------------------------------------

_HLTV_SESSION: Optional["_cffi_req.Session"] = None
_HLTV_SESSION_WARMED = False
_HLTV_SESSION_PROFILE = _PROFILES[0]

_STATS_SESSION_WARMED = False

_MAPSTATS_CIRCUIT_BLOCKED = False
_MAPSTATS_CIRCUIT_BLOCKED_AT = 0

_MAPSTATS_CIRCUIT_BLOCK_TTL = 300

_FETCH_RETRY_DELAYS = [1.0, 2.0, 4.0]

_MAPSTATS_HTML_CACHE = {}

# -----------------------------------------------------------------------------
# CIRCUIT BREAKERS
# -----------------------------------------------------------------------------

def _is_mapstats_url(url: str) -> bool:
    return "/stats/matches/mapstatsid/" in url


def _is_stats_blocked(url: str) -> bool:
    global _MAPSTATS_CIRCUIT_BLOCKED
    global _MAPSTATS_CIRCUIT_BLOCKED_AT

    if not _is_mapstats_url(url):
        return False

    if not _MAPSTATS_CIRCUIT_BLOCKED:
        return False

    elapsed = time.time() - _MAPSTATS_CIRCUIT_BLOCKED_AT

    if elapsed > _MAPSTATS_CIRCUIT_BLOCK_TTL:
        _MAPSTATS_CIRCUIT_BLOCKED = False
        return False

    return True


def _trip_stats_circuit(url: str):
    global _MAPSTATS_CIRCUIT_BLOCKED
    global _MAPSTATS_CIRCUIT_BLOCKED_AT

    if _is_mapstats_url(url):
        _MAPSTATS_CIRCUIT_BLOCKED = True
        _MAPSTATS_CIRCUIT_BLOCKED_AT = time.time()

        logger.warning(
            f"[circuit] mapstats blocked for 5 minutes: {url}"
        )

# -----------------------------------------------------------------------------
# SESSION MANAGEMENT
# -----------------------------------------------------------------------------

def _make_session(profile: str):

    try:
        sess = _cffi_req.Session(
            impersonate=profile
        )

        logger.info(
            f"[session] created profile={profile}"
        )

        return sess

    except Exception as e:

        logger.warning(
            f"[session] failed {profile}: {e}"
        )

        return None


def _get_hltv_session():

    global _HLTV_SESSION
    global _HLTV_SESSION_PROFILE

    if not _CFFI_OK:
        return None

    if _HLTV_SESSION is None:

        _HLTV_SESSION_PROFILE = _PROFILES[_profile_idx]

        _HLTV_SESSION = _make_session(
            _HLTV_SESSION_PROFILE
        )

    return _HLTV_SESSION


def _rotate_session():

    global _HLTV_SESSION
    global _HLTV_SESSION_WARMED
    global _STATS_SESSION_WARMED
    global _MAPSTATS_CIRCUIT_BLOCKED
    global _HLTV_SESSION_PROFILE
    global _profile_idx

    _profile_idx = (
        (_profile_idx + 1) % len(_PROFILES)
    )

    new_profile = _PROFILES[_profile_idx]

    logger.warning(
        f"[session] rotating -> {new_profile}"
    )

    _HLTV_SESSION = _make_session(
        new_profile
    )

    _HLTV_SESSION_PROFILE = new_profile

    _HLTV_SESSION_WARMED = False
    _STATS_SESSION_WARMED = False
    _MAPSTATS_CIRCUIT_BLOCKED = False

    return _HLTV_SESSION

# -----------------------------------------------------------------------------
# CLOUDFLARE DETECTION
# -----------------------------------------------------------------------------

def _is_cloudflare_challenge(resp) -> bool:

    if resp.status_code in (403, 429, 503):
        return True

    text = resp.text.lower()

    markers = [
        "just a moment",
        "__cf_bm",
        "cf_clearance",
        "checking your browser",
        "cf.challenge"
    ]

    return any(m in text for m in markers)

# -----------------------------------------------------------------------------
# SESSION WARMING
# -----------------------------------------------------------------------------

def _warm_hltv_session():

    global _HLTV_SESSION_WARMED

    if _HLTV_SESSION_WARMED:
        return

    if not _CFFI_OK:
        return

    for _ in range(len(_PROFILES)):

        sess = _get_hltv_session()

        if sess is None:
            return

        try:

            r = sess.get(
                HLTV_BASE + "/",
                timeout=15
            )

            logger.info(
                f"[warmup] status={r.status_code}"
            )

            if (
                r.status_code == 200
                and not _is_cloudflare_challenge(r)
            ):

                _HLTV_SESSION_WARMED = True

                time.sleep(0.5)

                return

            _rotate_session()

        except Exception as e:

            logger.warning(
                f"[warmup] failed: {e}"
            )

            _rotate_session()

# -----------------------------------------------------------------------------
# FETCH
# -----------------------------------------------------------------------------

def _fetch(
    url: str,
    max_retries: Optional[int] = None
) -> Optional[str]:

    if max_retries is None:
        max_retries = MAX_RETRIES

    if not _CFFI_OK:
        return None

    if _is_stats_blocked(url):
        return None

    _warm_hltv_session()

    profiles_tried = 0

    while profiles_tried <= MAX_PROFILE_ROTATIONS:

        sess = _get_hltv_session()

        if sess is None:
            return None

        got_403 = False

        for attempt in range(max_retries):

            try:

                logger.info(
                    f"[fetch] GET {url}"
                )

                resp = sess.get(
                    url,
                    timeout=FETCH_TIMEOUT
                )

                logger.info(
                    f"[fetch] status={resp.status_code}"
                )

                if (
                    resp.status_code == 200
                    and not _is_cloudflare_challenge(resp)
                    and len(resp.text) > 3000
                ):

                    return resp.text

                if resp.status_code == 403:

                    got_403 = True

                    break

                time.sleep(
                    random.uniform(1, 2)
                )

            except Exception as e:

                logger.warning(
                    f"[fetch] error: {e}"
                )

                time.sleep(
                    random.uniform(1, 2)
                )

        if got_403:

            profiles_tried += 1

            if profiles_tried <= MAX_PROFILE_ROTATIONS:

                _rotate_session()

                time.sleep(1)

            continue

        break

    if "/stats/" in url:
        _trip_stats_circuit(url)

    return None

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

    rows = soup.find_all("tr")

    maps = []

    for tr in rows:

        txt = tr.get_text(
            " ",
            strip=True
        )

        norm = re.sub(
            r"[^a-z0-9]",
            "",
            txt.lower()
        )

        if slug_norm not in norm:
            continue

        kd = re.search(
            r"(\\d+)\\s*-\\s*(\\d+)",
            txt
        )

        if kd:

            kills = int(
                kd.group(1)
            )

            maps.append({
                "kills": kills
            })

    return {
        "maps": maps[:2]
    }

# -----------------------------------------------------------------------------
# PLAYER SEARCH
# -----------------------------------------------------------------------------

def search_player(name: str):

    key = name.lower().strip()

    if key == "donk":
        return ("21167", "donk", "donk")

    url = f"{HLTV_BASE}/search?query={name}"

    html = _fetch(url)

    if not html:
        return None

    matches = re.findall(
        r"/player/(\\d+)/([\\w-]+)",
        html
    )

    if not matches:
        return None

    pid, slug = matches[0]

    display = slug.replace(
        "-",
        " "
    ).title()

    return pid, slug, display

# -----------------------------------------------------------------------------
# MATCH IDS
# -----------------------------------------------------------------------------

def get_player_match_ids(
    player_id: str,
    max_matches: int = 10
):

    url = f"{HLTV_BASE}/results?player={player_id}"

    html = _fetch(url)

    if not html:
        return []

    seen = {}

    for mid, slug in re.findall(
        r"/matches/(\\d+)/([a-z0-9-]+)",
        html
    ):

        if mid not in seen:
            seen[mid] = slug

    return list(seen.items())[:max_matches]

# -----------------------------------------------------------------------------
# PLAYER INFO
# -----------------------------------------------------------------------------

def get_player_info(
    player_name: str,
    stat_type: str = "Kills"
):

    result = search_player(player_name)

    if not result:
        raise RuntimeError(
            f"Player not found: {player_name}"
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

        maps = parsed.get("maps", [])[:2]

        for m in maps:

            map_kills.append({
                "kills": m.get("kills"),
                "match_id": match_id,
            })

    if len(map_kills) < 2:

        raise RuntimeError(
            f"No recent maps found for {display}"
        )

    values = [
        m["kills"]
        for m in map_kills
        if m.get("kills") is not None
    ]

    mean = _stats.mean(values)

    std = (
        _stats.stdev(values)
        if len(values) > 1
        else 2.0
    )

    return {
        "player": display,
        "player_id": pid,
        "mean": round(mean, 2),
        "std": round(std, 2),
        "sample_size": len(values),
        "source": "HLTV"
    }

# -----------------------------------------------------------------------------
# TEST
# -----------------------------------------------------------------------------

if __name__ == "__main__":

    print(
        get_player_info("donk")
    )
