import re
import random
import time
import logging
import os
import requests

from datetime import date, timedelta
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as sess_req
    CFFI_OK = True
except ImportError:
    CFFI_OK = False

# =====================================================
# LOGGER
# =====================================================

logger = logging.getLogger(__name__)

# =====================================================
# HLTV CONFIG
# =====================================================

HLTV_BASE = "https://www.hltv.org"

PROFILES = [
    "chrome116",
    "safari17_0",
    "chrome107",
    "chrome110",
    "chrome99"
]

# =====================================================
# SESSION STATE
# =====================================================

class HLTVState:

    session = None
    profile_idx = 0
    warmed = False
    stats_blocked_until = 0
    mapstats_blocked_until = 0

state = HLTVState()

# =====================================================
# ROTATE SESSION
# =====================================================

def _rotate():

    if not CFFI_OK:
        return None

    state.profile_idx = (
        (state.profile_idx + 1)
        % len(PROFILES)
    )

    state.session = sess_req.Session(
        impersonate=PROFILES[state.profile_idx]
    )

    state.warmed = False

    return state.session

# =====================================================
# FETCH HTML
# =====================================================

def _fetch(url, referer=None):

    # =============================================
    # CURL_CFFI
    # =============================================

    if CFFI_OK:

        if not state.session:
            _rotate()

        for _ in range(len(PROFILES)):

            try:

                if not state.warmed:

                    state.session.get(
                        HLTV_BASE + "/",
                        timeout=10
                    )

                    state.warmed = True

                headers = {
                    "Referer": (
                        referer
                        or HLTV_BASE + "/"
                    )
                }

                r = state.session.get(
                    url,
                    timeout=20,
                    headers=headers
                )

                if (
                    r.status_code == 200
                    and "Just a moment"
                    not in r.text
                ):

                    return r.text

                if r.status_code == 403:

                    _rotate()

                    continue

            except:

                _rotate()

    # =============================================
    # SCRAPERAPI FALLBACK
    # =============================================

    scraper_key = os.getenv(
        "SCRAPERAPI_KEY"
    )

    if scraper_key:

        try:

            params = {
                "api_key": scraper_key,
                "url": url
            }

            r = requests.get(
                "https://api.scraperapi.com/",
                params=params,
                timeout=30
            )

            if r.status_code == 200:
                return r.text

        except:
            pass

    # =============================================
    # NORMAL REQUEST FALLBACK
    # =============================================

    try:

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/122 Safari/537.36"
            )
        }

        r = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        if r.status_code == 200:
            return r.text

    except:
        pass

    return None

# =====================================================
# SEARCH PLAYER
# =====================================================

def get_player_data(name, team_hint=None):

    # =============================================
    # SEARCH PLAYER
    # =============================================

    player = search_player(name)

    if not player:
        return None

    pid, slug, display = player

    # =============================================
    # TEMP TEST DATA
    # =============================================

    sample_maps = [

        {
            "kills": 34,
            "hs": 15,
            "rating": 1.32
        },

        {
            "kills": 29,
            "hs": 11,
            "rating": 1.15
        },

        {
            "kills": 31,
            "hs": 14,
            "rating": 1.21
        },

        {
            "kills": 38,
            "hs": 17,
            "rating": 1.44
        },

        {
            "kills": 27,
            "hs": 10,
            "rating": 1.08
        },

        {
            "kills": 36,
            "hs": 16,
            "rating": 1.36
        },

        {
            "kills": 33,
            "hs": 13,
            "rating": 1.28
        },

        {
            "kills": 30,
            "hs": 12,
            "rating": 1.19
        },

        {
            "kills": 41,
            "hs": 19,
            "rating": 1.51
        },

        {
            "kills": 28,
            "hs": 11,
            "rating": 1.10
        }
    ]

    # =============================================
    # CALCULATIONS
    # =============================================

    valid_kills = [
        m["kills"]
        for m in sample_maps
    ]

    avg = round(
        sum(valid_kills)
        / len(valid_kills),
        2
    )

    # =============================================
    # RETURN
    # =============================================

    return {

        "player": display,

        "avg": avg,

        "sample": len(valid_kills),

        "maps": sample_maps
    }
def get_team_conceded(team_name):

    return 0.95
