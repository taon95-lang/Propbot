import re
import requests
import logging

from bs4 import BeautifulSoup

# =====================================================
# LOGGER
# =====================================================

logger = logging.getLogger(__name__)

# =====================================================
# HLTV
# =====================================================

HLTV_BASE = "https://www.hltv.org"

# =====================================================
# SEARCH PLAYER
# =====================================================

def search_player(name, team_hint=None):

    search_url = (
        f"{HLTV_BASE}/search?term={name}"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/122 Safari/537.36"
        )
    }

    try:

        r = requests.get(
            search_url,
            headers=headers,
            timeout=20
        )

        text = r.text

        matches = re.findall(
            r'/player/(\d+)/([\w-]+)',
            text
        )

        if not matches:

            return None

        pid, slug = matches[0]

        display = (
            slug
            .replace("-", " ")
            .title()
        )

        return (
            pid,
            slug,
            display
        )

    except Exception as e:

        print("SEARCH ERROR:", e)

        return None

# =====================================================
# GET PLAYER DATA
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
    # TEMP SAMPLE DATA
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

# =====================================================
# TEAM DEFENSE PLACEHOLDER
# =====================================================

def get_team_conceded(team_name):

    return 0.95
