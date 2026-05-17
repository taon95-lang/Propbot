import re
import os
import time
import functools
import statistics as _stats

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
except:
    import requests

# =========================================================
# SETTINGS
# =========================================================

HLTV_BASE = "https://www.hltv.org"

SCRAPERAPI_KEY = os.environ.get(
    "SCRAPERAPI_KEY"
)

FETCH_TIMEOUT = 40

# =========================================================
# FETCH
# =========================================================

def _fetch(url):

    headers = {

        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120 Safari/537.36"
        )
    }

    # =====================================================
    # SCRAPERAPI
    # =====================================================

    if SCRAPERAPI_KEY:

        try:

            proxy_url = (
                "http://api.scraperapi.com"
                f"?api_key={SCRAPERAPI_KEY}"
                f"&url={url}"
                f"&render=true"
                f"&country_code=us"
            )

            print(f"FETCHING: {url}")

            r = requests.get(
                proxy_url,
                headers=headers,
                timeout=FETCH_TIMEOUT
            )

            print(f"STATUS: {r.status_code}")

            if (
                r.status_code == 200
                and len(r.text) > 1000
            ):

                return r.text

        except Exception as e:

            print(f"FETCH ERROR: {e}")

    # =====================================================
    # DIRECT
    # =====================================================

    try:

        r = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        if r.status_code == 200:
            return r.text

    except Exception as e:

        print(f"DIRECT ERROR: {e}")

    return None

# =========================================================
# SEARCH PLAYER
# =========================================================

def search_player(name):

    key = name.lower().strip()

    STATIC = {

        "donk": (
            "21167",
            "donk",
            "donk"
        ),

        "jl": (
            "14108",
            "jl",
            "jL"
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
        )
    }

    if key in STATIC:
        return STATIC[key]

    html = _fetch(
        f"{HLTV_BASE}/search?query={name}"
    )

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
        slug
    )

# =========================================================
# REAL HLTV STATS PARSER
# =========================================================

def _extract_maps_from_stats_page(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    rows = soup.find_all("tr")

    print(f"TOTAL ROWS: {len(rows)}")

    maps = []

    for row in rows:

        try:

            txt = row.get_text(
                " ",
                strip=True
            )

            # =================================================
            # FIND KD
            # =================================================

            kd = re.findall(
                r'(\d+)\s*-\s*(\d+)',
                txt
            )

            if not kd:
                continue

            # =================================================
            # USE FIRST KD
            # =================================================

            kills = int(kd[0][0])

            deaths = int(kd[0][1])

            # realistic filter
            if kills < 8 or kills > 45:
                continue

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
                    rating = 0

            # =================================================
            # HS
            # =================================================

            hs = 0

            hs_match = re.findall(
                r'\((\d+)\)',
                txt
            )

            if hs_match:

                try:

                    hs = int(
                        hs_match[0]
                    )

                except:
                    hs = 0

            maps.append({

                "kills": kills,

                "deaths": deaths,

                "hs": hs,

                "rating": rating

            })

            print(
                f"MAP: "
                f"K={kills} "
                f"D={deaths} "
                f"HS={hs} "
                f"R={rating}"
            )

        except Exception as e:

            print(f"ROW ERROR: {e}")

    return maps[:10]

# =========================================================
# MAIN ENGINE
# =========================================================

def get_player_info(
    player_name,
    line=0,
    opponent="N/A"
):

    result = search_player(
        player_name
    )

    if not result:

        return (
            "FAIL: Player not found."
        )

    pid, slug, display = result

    print(f"STARTING SCAN: {display}")

    url = (
        f"{HLTV_BASE}/stats/players/matches/"
        f"{pid}/{slug}"
    )

    html = _fetch(url)

    if not html:

        return (
            "FAIL: Could not "
            "load HLTV stats page."
        )

    maps = _extract_maps_from_stats_page(
        html
    )

    if not maps:

        return (
            "FAIL: No valid maps found."
        )

    # =====================================================
    # STATS
    # =====================================================

    kills = [
        x["kills"]
        for x in maps
    ]

    hs = [
        x["hs"]
        for x in maps
    ]

    ratings = [
        x["rating"]
        for x in maps
    ]

    avg = round(
        _stats.mean(kills),
        2
    )

    avg_hs = round(
        _stats.mean(hs),
        2
    )

    avg_rating = round(
        _stats.mean(ratings),
        2
    )

    hits = len([

        x for x in kills

        if x > line

    ])

    hit_rate = round(

        (
            hits / len(kills)
        ) * 100,

        1

    )

    edge = round(
        avg - line,
        2
    )

    # =====================================================
    # BET LOGIC
    # =====================================================

    if avg >= line + 2:

        recommendation = "OVER"

    elif avg <= line - 2:

        recommendation = "UNDER"

    else:

        recommendation = "NO BET"

    print(f"FINAL AVG: {avg}")

    return {

        "Player": display,

        "Opponent": opponent,

        "Line": line,

        "Avg Kills": avg,

        "Edge": edge,

        "Hit Rate": f"{hit_rate}%",

        "Avg HS": avg_hs,

        "Avg Rating": avg_rating,

        "Sample": len(kills),

        "Bet recommendation": recommendation,

        "Recent Maps": ", ".join(
            str(x)
            for x in kills
        ),

        "Recent totals": kills
    }

# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    print(
        get_player_info(
            "jl",
            28.5,
            "magic"
        )
    )
