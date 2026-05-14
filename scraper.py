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
            # CLOUDFLARE FIX
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

    print(f"MATCH IDS FOUND: {len(final)}")

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

    maps = []

    slug_norm = re.sub(
        r"[^a-z0-9]",
        "",
        player_slug.lower()
    )

    rows = soup.find_all("tr")

    print(f"TOTAL ROWS FOUND: {len(rows)}")

    for tr in rows:

        row_text = tr.get_text(
            " ",
            strip=True
        )

        row_lower = row_text.lower()

        row_norm = re.sub(
            r"[^a-z0-9]",
            "",
            row_lower
        )

        # =================================================
        # PLAYER CHECK
        # =================================================

        if slug_norm not in row_norm:
            continue

        print(f"PLAYER ROW FOUND: {row_text}")

        # =================================================
        # FIND NUMBERS
        # =================================================

        numbers = re.findall(
            r'\d+',
            row_text
        )

        print(f"NUMBERS FOUND: {numbers}")

        if len(numbers) < 2:
            continue

        # =================================================
        # TRY K-D FORMAT
        # =================================================

        kd_match = re.search(
            r'(\d+)\s*-\s*(\d+)',
            row_text
        )

        kills = None

        if kd_match:

            kills = int(
                kd_match.group(1)
            )

            print(f"KILLS PARSED: {kills}")

        else:

            possible = [

                int(x)

                for x in numbers

                if int(x) <= 40

            ]

            if possible:

                kills = max(possible)

                print(f"FALLBACK KILLS: {kills}")

        if kills is None:
            continue

        # =================================================
        # HEADSHOTS
        # =================================================

        hs = None

        hs_match = re.search(
            r'\((\d+)\)',
            row_text
        )

        if hs_match:

            try:

                hs = int(
                    hs_match.group(1)
                )

                print(f"HS PARSED: {hs}")

            except:
                pass

        # =================================================
        # RATING
        # =================================================

        rating = None

        rating_match = re.findall(
            r'(\d\.\d{2})',
            row_text
        )

        if rating_match:

            try:

                rating = float(
                    rating_match[-1]
                )

                print(f"RATING PARSED: {rating}")

            except:
                pass

        maps.append({

            "kills": kills,

            "hs": hs,

            "rating": rating

        })

    print(f"TOTAL MAPS PARSED: {len(maps)}")

    return {
        "maps": maps[:20]
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

    all_maps = []

    # =====================================================
    # LOOP MATCHES
    # =====================================================

    for match_id, match_slug in match_ids:

        try:

            match_url = (
                f"{HLTV_BASE}/matches/"
                f"{match_id}/{match_slug}"
            )

            print(f"CHECKING MATCH: {match_url}")

            html = _fetch(
                match_url
            )

            if not html:

                print("NO HTML RETURNED")

                continue

            # =================================================
            # PARSE MATCH
            # =================================================

            parsed = _parse_match_kills(
                html,
                slug
            )

            if not parsed:

                print("NO PARSED DATA")

                continue

            maps = parsed.get(
                "maps",
                []
            )

            print(f"MAPS RETURNED: {len(maps)}")

            # =================================================
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

    print(f"TOTAL MAPS COLLECTED: {len(all_maps)}")

    # =====================================================
    # NO DATA
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

    # =====================================================
    # BUILD STATS
    # =====================================================

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
