import re
import os
import time
import random
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
except ImportError:
    import requests

# =========================================================
# PARSER
# =========================================================

try:
    import lxml
    PARSER = "lxml"
except:
    PARSER = "html.parser"

# =========================================================
# SETTINGS
# =========================================================

HLTV_BASE = "https://www.hltv.org"

SCRAPERAPI_KEY = os.environ.get(
    "SCRAPERAPI_KEY"
)

FETCH_TIMEOUT = 40

# =========================================================
# FETCH ENGINE
# =========================================================

def _fetch(url):

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
    # SCRAPER API
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
    # DIRECT FALLBACK
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

        print(f"DIRECT FETCH ERROR: {e}")

    return None

# =========================================================
# PLAYER SEARCH
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

        "jl": (
            "14108",
            "jl",
            "jL"
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
        )
    }

    if key in STATIC:

        pid, slug, display = STATIC[key]

        return pid, slug, display

    search_url = (
        f"{HLTV_BASE}/search?query={name}"
    )

    html = _fetch(search_url)

    if not html:

        print("SEARCH FAILED")

        return None

    matches = re.findall(
        r'/player/(\d+)/([\w-]+)',
        html
    )

    if not matches:

        print("NO PLAYER FOUND")

        return None

    pid, slug = matches[0]

    return (
        pid,
        slug,
        slug.replace("-", " ").title()
    )

# =========================================================
# PARSE MATCH KILLS
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

        print(f"BS4 ERROR: {e}")

        return {
            "maps": []
        }

    # =====================================================
    # FIND ROWS
    # =====================================================

    rows = soup.find_all("tr")

    print(f"TOTAL ROWS: {len(rows)}")

    for tr in rows:

        try:

            row_text = tr.get_text(
                " ",
                strip=True
            )

            row_lower = row_text.lower()

            # =================================================
            # PLAYER CHECK
            # =================================================

            if player_slug.lower() not in row_lower:
                continue

            print(f"PLAYER ROW: {row_text}")

            # =================================================
            # FIND K-D
            # =================================================

            kd_matches = re.findall(
                r'(\d+)\s*-\s*(\d+)',
                row_text
            )

            if not kd_matches:
                continue

            kills = int(
                kd_matches[0][0]
            )

            deaths = int(
                kd_matches[0][1]
            )

            print(
                f"KILLS={kills} "
                f"DEATHS={deaths}"
            )

            # =================================================
            # SAFETY FILTER
            # =================================================

            if kills < 8 or kills > 45:
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

                try:

                    hs = int(
                        hs_match.group(1)
                    )

                except:
                    hs = 0

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
                    rating = 0

            maps_data.append({

                "kills": kills,

                "hs": hs,

                "rating": rating

            })

        except Exception as e:

            print(
                f"PARSER ERROR: {e}"
            )

    print(
        f"MAPS EXTRACTED: "
        f"{len(maps_data)}"
    )

    return {

        "maps": maps_data[:20]

    }

# =========================================================
# MAIN SCAN ENGINE
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

        return "FAIL: Player not found."

    pid, slug, display = result

    print(f"STARTING SCAN: {display}")

    stats_url = (
        f"{HLTV_BASE}/stats/players/matches/"
        f"{pid}/{slug}"
    )

    html = _fetch(stats_url)

    if not html:

        return (
            "FAIL: Stats page "
            "blocked by Cloudflare."
        )

    parsed = _parse_match_kills(
        html,
        slug
    )

    maps = parsed.get(
        "maps",
        []
    )

    if not maps:

        return (
            "FAIL: No valid maps found."
        )

    # =====================================================
    # LAST 10 MAPS ONLY
    # =====================================================

    maps = maps[:10]

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

    # =====================================================
    # RETURN
    # =====================================================

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

    data = get_player_info(
        "jl",
        28.5,
        "magic"
    )

    print(data)
