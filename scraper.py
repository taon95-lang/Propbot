import re
import os
import time
import statistics as _stats
import functools
import random

from bs4 import BeautifulSoup

# =========================================================
# REALTIME PRINTS
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
# SETTINGS
# =========================================================

HLTV_BASE = "https://www.hltv.org"

SCRAPERAPI_KEY = os.environ.get(
    "SCRAPERAPI_KEY"
)

FETCH_TIMEOUT = 30

# =========================================================
# FETCH
# =========================================================

def _fetch(url):

    print(f"FETCHING: {url}")

    # =====================================================
    # SCRAPERAPI FIRST
    # =====================================================

    if SCRAPERAPI_KEY:

        try:

            proxy_url = (
                "http://api.scraperapi.com"
                f"?api_key={SCRAPERAPI_KEY}"
                f"&url={url}"
                "&render=true"
                "&country_code=us"
            )

            r = requests.get(
                proxy_url,
                timeout=60
            )

            print(
                f"STATUS: {r.status_code}"
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
    # DIRECT FALLBACK
    # =====================================================

    try:

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

        r = requests.get(
            url,
            headers=headers,
            timeout=FETCH_TIMEOUT
        )

        print(
            f"DIRECT STATUS: {r.status_code}"
        )

        if (
            r.status_code == 200
            and len(r.text) > 1000
        ):

            return r.text

    except Exception as e:

        print(
            f"DIRECT FETCH ERROR: {e}"
        )

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

        "jl": (
            "14108",
            "jl",
            "jL"
        ),

        "sh1ro": (
            "16920",
            "sh1ro",
            "sh1ro"
        )
    }

    if key in STATIC:

        return STATIC[key]

    url = (
        f"{HLTV_BASE}/search"
        f"?query={name}"
    )

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

        slug.replace(
            "-",
            " "
        ).title()

    )

# =========================================================
# GET PLAYER INFO
# =========================================================

def get_player_info(
    player_name,
    line=0.0,
    opponent="N/A"
):

    result = search_player(
        player_name
    )

    if not result:

        return None

    pid, slug, display = result

    print(
        f"STARTING SCAN: "
        f"{display}"
    )

    # =====================================================
    # HLTV STATS PAGE
    # =====================================================

    url = (
        f"{HLTV_BASE}/stats/players/matches/"
        f"{pid}/{slug}"
    )

    html = _fetch(url)

    if not html:

        return None

    # =====================================================
    # PARSE
    # =====================================================

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    rows = soup.find_all("tr")

    print(
        f"TOTAL ROWS: {len(rows)}"
    )

    maps = []

    # =====================================================
    # EXTRACT MAPS
    # =====================================================

    for tr in rows:

        txt = tr.get_text(
            " ",
            strip=True
        )

        # =================================================
        # FIND KD
        # =================================================

        kd_match = re.search(
            r'(\d+)\s*-\s*(\d+)',
            txt
        )

        if not kd_match:
            continue

        try:

            kills = int(
                kd_match.group(1)
            )

        except:
            continue

        # =================================================
        # HEADSHOTS
        # =================================================

        hs = 0

        hs_match = re.search(
            r'\((\d+)\)',
            txt
        )

        if hs_match:

            try:

                hs = int(
                    hs_match.group(1)
                )

            except:
                pass

        # =================================================
        # RATING
        # =================================================

        rating = 0

        rating_match = re.findall(
            r'(\d\.\d{2})',
            txt
        )

        if rating_match:

            try:

                rating = float(
                    rating_match[-1]
                )

            except:
                pass

        maps.append({

            "kills": kills,

            "hs": hs,

            "rating": rating

        })

        # =================================================
        # LIMIT SAMPLE
        # =================================================

        if len(maps) >= 20:
            break

    print(
        f"MAPS EXTRACTED: {len(maps)}"
    )

    # =====================================================
    # NO DATA
    # =====================================================

    if not maps:

        return None

    # =====================================================
    # BUILD STATS
    # =====================================================

    kills = [
        m["kills"]
        for m in maps
    ]

    hs_list = [
        m["hs"]
        for m in maps
    ]

    ratings = [
        m["rating"]
        for m in maps
    ]

    avg = round(
        _stats.mean(kills),
        2
    )

    avg_hs = round(
        _stats.mean(hs_list),
        2
    )

    avg_rating = round(
        _stats.mean(ratings),
        2
    )

    line_float = float(line)

    hits = len([

        k for k in kills

        if k > line_float

    ])

    hit_rate = round(

        (
            hits / len(kills)
        ) * 100,

        1

    ) if kills else 0

    edge = round(
        avg - line_float,
        2
    )

    # =====================================================
    # BET LOGIC
    # =====================================================

    if hit_rate >= 60:

        bet = "OVER"

    elif hit_rate <= 40:

        bet = "UNDER"

    else:

        bet = "NO BET"

    print(
        f"FINAL AVG: {avg}"
    )

    # =====================================================
    # FINAL RETURN
    # =====================================================

    return {

        "player": display,

        "avg": avg,

        "avg_hs": avg_hs,

        "avg_rating": avg_rating,

        "sample": len(kills),

        "maps": maps,

        "hit_rate": hit_rate,

        "edge": edge,

        "Bet recommendation": bet,

        "Recent totals": kills

    }

# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    data = get_player_info(
        "jl",
        28.5,
        "magic"
    )

    print(data)
