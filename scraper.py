import re
import os
import time
import random
import logging
import statistics as _stats
import functools

from bs4 import BeautifulSoup

# =========================================================
# REALTIME PRINTS FOR RENDER
# =========================================================

print = functools.partial(print, flush=True)

# =========================================================
# REQUESTS
# =========================================================

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

# =========================================================
# PARSER
# =========================================================

PARSER = "html.parser"

# =========================================================
# LOGGING
# =========================================================

logger = logging.getLogger(__name__)

HLTV_BASE = "https://www.hltv.org"

CS2_ID_THRESHOLD = 2366000

SCRAPERAPI_KEY = os.environ.get(
    "SCRAPERAPI_KEY"
)

# =========================================================
# SETTINGS
# =========================================================

FETCH_TIMEOUT = 25

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

    print(
        f"ROTATING PROFILE -> {profile}"
    )

    try:

        _SESSION = requests.Session(
            impersonate=profile
        )

    except:

        _SESSION = requests.Session()

# =========================================================
# FETCH ENGINE
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
        ),

        "Referer": HLTV_BASE
    }

    # =====================================================
    # SCRAPERAPI
    # =====================================================

    if (
        SCRAPERAPI_KEY
        and "search" not in url
    ):

        try:

            proxy_url = (
                "http://api.scraperapi.com"
                f"?api_key={SCRAPERAPI_KEY}"
                f"&url={url}"
            )

            print(
                f"SCRAPERAPI FETCH: {url}"
            )

            r = requests.get(
                proxy_url,
                timeout=60
            )

            print(
                f"SCRAPERAPI STATUS: "
                f"{r.status_code}"
            )

            if (
                r.status_code == 200
                and len(r.text) > 1000
            ):

                return r.text

        except Exception as e:

            print(
                f"SCRAPERAPI ERROR: {e}"
            )

    # =====================================================
    # DIRECT FETCH
    # =====================================================

    for attempt in range(3):

        try:

            print(f"FETCHING: {url}")

            r = _SESSION.get(
                url,
                headers=headers,
                timeout=FETCH_TIMEOUT
            )

            print(
                f"STATUS: {r.status_code}"
            )

            if (
                "Just a moment" in r.text
                or "Checking your browser" in r.text
                or "__cf_bm" in r.text
            ):

                print(
                    "CLOUDFLARE DETECTED"
                )

                _rotate_session()

                time.sleep(2)

                continue

            if (
                r.status_code == 200
                and len(r.text) > 1000
            ):

                return r.text

            if r.status_code in [403, 429]:

                print(
                    f"BLOCKED: "
                    f"{r.status_code}"
                )

                _rotate_session()

            time.sleep(1)

        except Exception as e:

            print(
                f"FETCH ERROR: {e}"
            )

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

    STATIC = {

        "donk": (
            "21167",
            "donk",
            "donk"
        ),

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

    if key in STATIC:
        return STATIC[key]

    url = (
        f"{HLTV_BASE}/search"
        f"?query={name}"
    )

    html = _fetch(url)

    if not html:

        print("SEARCH FAILED")

        return None

    matches = re.findall(
        r'/player/(\d+)/([\w-]+)',
        html
    )

    if not matches:

        print(
            "NO PLAYER MATCHES FOUND"
        )

        return None

    pid, slug = matches[0]

    return (

        pid,

        slug,

        slug.replace(
            "-",
            " "
        ).title()

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

        print("NO RESULTS HTML")

        return []

    matches = re.findall(
        r'/matches/(\d+)/([\w-]+)',
        html
    )

    seen = set()

    final = []

    for mid, slug in matches:

        try:

            if (
                int(mid) >= CS2_ID_THRESHOLD
                and mid not in seen
            ):

                seen.add(mid)

                final.append(
                    (mid, slug)
                )

        except:
            pass

    print(
        f"MATCH IDS FOUND: "
        f"{len(final)}"
    )

    return final[:max_matches]

# =========================================================
# NEW RESILIENT PARSER
# =========================================================

def _parse_match_kills(
    html,
    player_slug
):

    maps_data = []

    try:

        soup = BeautifulSoup(
            html,
            PARSER
        )

    except Exception as e:

        print(
            f"SOUP ERROR: {e}"
        )

        return {
            "maps": []
        }

    # =====================================================
    # FIND ALL ROWS
    # =====================================================

    rows = soup.find_all("tr")

    print(
        f"TOTAL ROWS: "
        f"{len(rows)}"
    )

    slug_lower = player_slug.lower()

    # =====================================================
    # LOOP ROWS
    # =====================================================

    for tr in rows:

        try:

            row_text = tr.get_text(
                " ",
                strip=True
            )

            row_lower = row_text.lower()

            # =================================================
            # PLAYER MATCH
            # =================================================

            if slug_lower not in row_lower:
                continue

            print(
                f"PLAYER ROW:"
            )

            print(row_text)

            # =================================================
            # EXTRACT KILLS
            # =================================================

            kills = None

            kd_match = re.search(
                r'(\d+)\s*-\s*\d+',
                row_text
            )

            if kd_match:

                kills = int(
                    kd_match.group(1)
                )

            # =================================================
            # FALLBACK KILLS
            # =================================================

            if kills is None:

                nums = re.findall(
                    r'\d+',
                    row_text
                )

                nums = [

                    int(x)

                    for x in nums

                    if 5 <= int(x) <= 45

                ]

                if nums:

                    kills = max(nums)

            if kills is None:
                continue

            # =================================================
            # HEADSHOTS
            # =================================================

            hs = 0

            hs_match = re.search(
                r'\((\d+)\)',
                row_text
            )

            if hs_match:

                hs = int(
                    hs_match.group(1)
                )

            # =================================================
            # RATING
            # =================================================

            rating = 0

            rating_matches = re.findall(
                r'(\d\.\d{2})',
                row_text
            )

            if rating_matches:

                try:

                    rating = float(
                        rating_matches[-1]
                    )

                except:
                    pass

            print(
                f"K={kills} "
                f"HS={hs} "
                f"R={rating}"
            )

            maps_data.append({

                "kills": kills,

                "hs": hs,

                "rating": rating

            })

        except Exception as e:

            print(
                f"ROW ERROR: {e}"
            )

    print(
        f"TOTAL MAPS PARSED: "
        f"{len(maps_data)}"
    )

    return {
        "maps": maps_data[:20]
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

        print("PLAYER NOT FOUND")

        return None

    pid, slug, display = result

    print(
        f"STARTING SCAN: "
        f"{display}"
    )

    # =====================================================
    # GET MATCHES
    # =====================================================

    match_ids = get_player_match_ids(
        pid,
        max_matches=10
    )

    if not match_ids:

        print(
            "NO MATCH IDS FOUND"
        )

        return None

    all_maps = []

    # =====================================================
    # LOOP MATCHES
    # =====================================================

    for mid, mslug in match_ids:

        try:

            url = (
                f"{HLTV_BASE}/matches/"
                f"{mid}/{mslug}"
            )

            print(
                f"CHECKING MATCH:"
            )

            print(url)

            html = _fetch(url)

            if not html:

                print("NO MATCH HTML")

                continue

            parsed = _parse_match_kills(
                html,
                slug
            )

            maps = parsed.get(
                "maps",
                []
            )

            print(
                f"MAPS FOUND: "
                f"{len(maps)}"
            )

            if maps:

                all_maps.extend(
                    maps[:2]
                )

                print(
                    f"SUCCESS:"
                    f" {mslug}"
                )

            time.sleep(
                random.uniform(
                    0.4,
                    1.0
                )
            )

        except Exception as e:

            print(
                f"MATCH ERROR: {e}"
            )

    print(
        f"TOTAL MAPS COLLECTED:"
        f" {len(all_maps)}"
    )

    # =====================================================
    # NO MAPS
    # =====================================================

    if not all_maps:

        print(
            "FAIL: Could not "
            "extract data "
            "from the recent series."
        )

        return None

    # =====================================================
    # BUILD STATS
    # =====================================================

    kills = [
        m["kills"]
        for m in all_maps
        if m.get("kills") is not None
    ]

    hs_list = [
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
        _stats.mean(hs_list),
        2
    ) if hs_list else 0

    avg_rating = round(
        _stats.mean(ratings),
        2
    ) if ratings else 0

    print(
        f"FINAL AVG: {avg}"
    )

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
