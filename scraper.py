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

        print(f"SEARCHING PLAYER: {name}")
        print(f"SEARCH URL: {search_url}")

        r = requests.get(
            search_url,
            headers=headers,
            timeout=20
        )

        print("STATUS:", r.status_code)

        text = r.text

        print(text[:500])

        # =========================================
        # FIND PLAYER LINKS
        # =========================================

        matches = re.findall(
            r'/player/(\d+)/([\w-]+)',
            text
        )

        print("MATCHES:", matches[:5])

        if not matches:

            print("NO PLAYER MATCHES")

            return None

        pid, slug = matches[0]

        display = (
            slug
            .replace("-", " ")
            .title()
        )

        print(
            f"FOUND PLAYER: "
            f"{display} ({pid})"
        )

        # RETURN:
        # (player_id, slug, display)

        return (
            pid,
            slug,
            display
        )

    except Exception as e:

        print("SEARCH ERROR:", e)

        return None

# =====================================================
# PARSE MAP STATS
# =====================================================

def parse_map_stats(html, player_slug):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    slug_norm = re.sub(
        r"[^a-z0-9]",
        "",
        player_slug.lower()
    )

    for tr in soup.find_all("tr"):

        row_text = tr.get_text().lower()

        clean_row = re.sub(
            r"[^a-z0-9]",
            "",
            row_text
        )

        if slug_norm not in clean_row:
            continue

        cells = [
            c.get_text(strip=True)
            for c in tr.find_all("td")
        ]

        stats = {
            "kills": None,
            "hs": None,
            "deaths": None,
            "rating": None
        }

        for c in cells:

            # =====================================
            # KILLS + HS
            # Example:
            # 21 (11)
            # =====================================

            khs = re.search(
                r"(\d+)\s*\((\d+)\)",
                c
            )

            if khs:

                stats["kills"] = int(
                    khs.group(1)
                )

                stats["hs"] = int(
                    khs.group(2)
                )

            # =====================================
            # KD
            # =====================================

            kd = re.search(
                r"^(\d+)\s*[-–]\s*(\d+)$",
                c
            )

            if kd and not stats["kills"]:

                stats["kills"] = int(
                    kd.group(1)
                )

                stats["deaths"] = int(
                    kd.group(2)
                )

            # =====================================
            # RATING
            # =====================================

            rat = re.match(
                r"^(\d\.\d{2})$",
                c
            )

            if rat:

                stats["rating"] = float(
                    rat.group(1)
                )

        return stats

    return None

# =====================================================
# PLAYER DATA
# =====================================================

def get_player_data(name, team_hint=None):

    player = search_player(name)

    if not player:
        return None

    pid, slug, display = player

    # =============================================
    # RECENT RESULTS
    # =============================================

    res_html = _fetch(
        f"{HLTV_BASE}/results?player={pid}"
    )

    if not res_html:
        return None

    mids = re.findall(
        r'/matches/(\d{7,})/([\w-]+)',
        res_html
    )[:15]

    all_maps = []

    # =============================================
    # LAST 10 BO3S
    # =============================================

    for mid, mslug in list(
        dict.fromkeys(mids)
    )[:10]:

        match_url = (
            f"{HLTV_BASE}/matches/"
            f"{mid}/{mslug}"
        )

        m_html = _fetch(match_url)

        if not m_html:
            continue

        if "best of 3" not in m_html.lower():
            continue

        # =========================================
        # MAP 1 + 2 ONLY
        # =========================================

        ms_ids = re.findall(
            r'/stats/matches/mapstatsid/(\d+)/',
            m_html
        )[:2]

        for msid in ms_ids:

            stats_url = (
                f"{HLTV_BASE}/stats/matches/"
                f"mapstatsid/{msid}/proxy"
            )

            ms_html = _fetch(
                stats_url,
                referer=match_url
            )

            if not ms_html:
                continue

            m_data = parse_map_stats(
                ms_html,
                slug
            )

            if m_data:

                m_data.update({
                    "match_id": mid,
                    "map_id": msid
                })

                all_maps.append(m_data)

        if len(all_maps) >= 20:
            break

    # =============================================
    # VALID KILLS
    # =============================================

    valid_kills = [
        m["kills"]
        for m in all_maps
        if m["kills"] is not None
    ]

    if not valid_kills:
        return None

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
        "maps": all_maps
    }

# =====================================================
# TEAM DEFENSE PLACEHOLDER
# =====================================================

def get_team_conceded(team_name):

    return 0.95k
