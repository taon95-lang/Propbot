import re
import os
import time
import random
import logging
import statistics as _stats

from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as requests
except:
    import requests

logger = logging.getLogger(__name__)

HLTV_BASE = "https://www.hltv.org"

# =========================================================
# SETTINGS
# =========================================================

FETCH_TIMEOUT = 20

_PROFILES = [
    "chrome116",
    "chrome110",
    "chrome107",
    "chrome99",
]

_profile_idx = 0

# =========================================================
# SESSION
# =========================================================

try:
    _SESSION = requests.Session(
        impersonate=_PROFILES[_profile_idx]
    )
except:
    _SESSION = requests.Session()

# =========================================================
# ROTATE SESSION
# =========================================================

def _rotate_session():

    global _SESSION
    global _profile_idx

    _profile_idx = (
        _profile_idx + 1
    ) % len(_PROFILES)

    profile = _PROFILES[_profile_idx]

    print(f"ROTATING PROFILE -> {profile}")

    try:

        _SESSION = requests.Session(
            impersonate=profile
        )

    except:

        _SESSION = requests.Session()

# =========================================================
# FETCH
# =========================================================

def _fetch(url):

    global _SESSION

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0.0.0 "
            "Safari/537.36"
        )
    }

    for attempt in range(3):

        try:

            print(f"FETCHING: {url}")

            r = _SESSION.get(
                url,
                headers=headers,
                timeout=FETCH_TIMEOUT
            )

            print(f"STATUS: {r.status_code}")

            # =====================================================
            # CLOUDLFARE FIX
            # =====================================================

            if (
                "Just a moment" in r.text
                or "Checking your browser" in r.text
            ):

                print("CLOUDFLARE DETECTED")

                _rotate_session()

                time.sleep(2)

                continue

            # =====================================================
            # SUCCESS
            # =====================================================

            if (
                r.status_code == 200
                and len(r.text) > 1000
            ):

                return r.text

            # =====================================================
            # ROTATE ON 403
            # =====================================================

            if r.status_code == 403:

                print("403 BLOCKED")

                _rotate_session()

            time.sleep(1)

        except Exception as e:

            print(f"FETCH ERROR: {e}")

            _rotate_session()

            time.sleep(1)

    return None

# =========================================================
# SEARCH PLAYER
# =========================================================

def search_player(name: str):

    if not name:
        return None

    key = name.lower().strip()

    # =====================================================
    # STATIC PLAYER CACHE
    # =====================================================

    STATIC_IDS = {

        "donk": ("21167", "donk", "donk"),

        "zywoo": (
            "11893",
            "zywoo",
            "ZywOo"
        ),

        "m0nesy": (
            "19230",
            "m0nesy",
            "m0NESY"
        ),

        "niko": (
            "3741",
            "niko",
            "NiKo"
        ),

        "sh1ro": (
            "16920",
            "sh1ro",
            "sh1ro"
        ),
    }

    if key in STATIC_IDS:
        return STATIC_IDS[key]

    url = f"{HLTV_BASE}/search?query={name}"

    html = _fetch(url)

    if not html:
        return None

    matches = re.findall(
        r'/player/(\d+)/([\w-]+)',
        html
    )

    if not matches:
        return None

    pid, slug = matches[0]

    return (
        pid,
        slug,
        slug.replace("-", " ").title()
    )

# =========================================================
# GET PLAYER MATCH IDS
# =========================================================

def get_player_match_ids(
    player_id,
    max_matches=10
):

    url = (
        f"{HLTV_BASE}/results"
        f"?player={player_id}"
    )

    html = _fetch(url)

    if not html:
        return []

    matches = re.findall(
        r'/matches/(\d+)/([\w-]+)',
        html
    )

    seen = set()

    final = []

    for mid, slug in matches:

        if mid not in seen:

            seen.add(mid)

            final.append(
                (mid, slug)
            )

    return final[:max_matches]

# =========================================================
# PARSE MATCH KILLS
# =========================================================

def _parse_match_kills(
    html,
    player_slug
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

    for tr in rows:

        txt = tr.get_text(
            " ",
            strip=True
        ).lower()

        txt_norm = re.sub(
            r"[^a-z0-9]",
            "",
            txt
        )

        if slug_norm not in txt_norm:
            continue

        # =====================================================
        # KILLS
        # =====================================================

        kd = re.search(
            r'(\d+)\s*-\s*(\d+)',
            txt
        )

        if not kd:
            continue

        kills = int(
            kd.group(1)
        )

        # =====================================================
        # HEADSHOTS
        # =====================================================

        hs_match = re.search(
            r'\((\d+)\)',
            txt
        )

        hs = None

        if hs_match:

            try:

                hs = int(
                    hs_match.group(1)
                )

            except:
                pass

        # =====================================================
        # RATING
        # =====================================================

        rating = None

        rating_match = re.search(
            r'(\d\.\d{2})',
            txt
        )

        if rating_match:

            try:

                rating = float(
                    rating_match.group(1)
                )

            except:
                pass

        maps.append({

            "kills": kills,

            "hs": hs,

            "rating": rating

        })

    return {
        "maps": maps[:2]
    }

# =========================================================
# GET PLAYER INFO
# =========================================================

def get_player_info(
    player_name,
    opponent=None
):

    result = search_player(
        player_name
    )

    if not result:
        return None

    pid, slug, display = result

    print(f"FOUND PLAYER: {display}")

    # =====================================================
    # STEP 1
    # GET MATCH IDS
    # =====================================================

    match_ids = get_player_match_ids(
        pid,
        max_matches=10
    )

    print(
        f"MATCHES FOUND: "
        f"{len(match_ids)}"
    )

    # =====================================================
    # STEP 2
    # LOOP THROUGH MATCHES
    # =====================================================

    all_maps = []

    for match_id, match_slug in match_ids:

        try:

            match_url = (
                f"{HLTV_BASE}/matches/"
                f"{match_id}/{match_slug}"
            )

            html = _fetch(
                match_url
            )

            if not html:
                continue

            # =================================================
            # STEP 3
            # PARSE MATCH
            # =================================================

            parsed = _parse_match_kills(
                html,
                slug
            )

            if not parsed:
                continue

            maps = parsed.get(
                "maps",
                []
            )

            # =================================================
            # STEP 4
            # SAVE MAPS
            # =================================================

            for m in maps:

                kills = m.get("kills")

                if kills is None:
                    continue

                all_maps.append({

                    "kills": kills,

                    "hs": m.get("hs"),

                    "rating": m.get("rating")

                })

            # =================================================
            # STEP 5
            # RANDOM DELAY
            # =================================================

            time.sleep(
                random.uniform(
                    0.5,
                    1.2
                )
            )

        except Exception as e:

            print(
                f"MATCH ERROR: {e}"
            )

    # =====================================================
    # STEP 6
    # BUILD FINAL STATS
    # =====================================================

    if not all_maps:

        return {

            "player": display,

            "avg": 0,

            "avg_hs": 0,

            "avg_rating": 0,

            "sample": 0,

            "maps": []

        }

    kills = [

        m["kills"]

        for m in all_maps

        if m.get("kills") is not None
    ]

    hs = [

        m["hs"]

        for m in all_maps

        if m.get("hs") is not None
    ]

    ratings = [

        m["rating"]

        for m in all_maps

        if m.get("rating") is not None
    ]

    avg = round(
        _stats.mean(kills),
        2
    ) if kills else 0

    avg_hs = round(
        _stats.mean(hs),
        2
    ) if hs else 0

    avg_rating = round(
        _stats.mean(ratings),
        2
    ) if ratings else 0

    return {

        "player": display,

        "avg": avg,

        "avg_hs": avg_hs,

        "avg_rating": avg_rating,

        "sample": len(kills),

        "maps": all_maps

    }

# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    data = get_player_info(
        "donk"
    )

    print(data)
