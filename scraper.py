import re
import os
import time
import statistics as _stats
import functools
import random

from bs4 import BeautifulSoup

# =========================================================
# REALTIME PRINTS FOR RENDER
# =========================================================

print = functools.partial(
    print,
    flush=True
)

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

PARSER = "html.parser"

HLTV_BASE = "https://www.hltv.org"

SCRAPERAPI_KEY = os.environ.get(
    "SCRAPERAPI_KEY"
)

# =========================================================
# FETCH ENGINE
# =========================================================

def _fetch(
    url,
    render=False
):

    headers = {

        "User-Agent": random.choice([

            (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/123.0.0.0 "
                "Safari/537.36"
            ),

            (
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/122.0.0.0 "
                "Safari/537.36"
            )

        ]),

        "Accept": (
            "text/html,"
            "application/xhtml+xml,"
            "application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),

        "Accept-Language": "en-US,en;q=0.9",

        "Referer": HLTV_BASE,

        "Cache-Control": "no-cache"
    }

    # =====================================================
    # SCRAPERAPI FETCH
    # =====================================================

    if SCRAPERAPI_KEY:

        try:

            render_param = (
                "&render=true"
                if render
                else ""
            )

            proxy_url = (

                "http://api.scraperapi.com"

                f"?api_key={SCRAPERAPI_KEY}"

                f"&keep_headers=true"

                f"&country_code=us"

                f"{render_param}"

                f"&url={url}"

            )

            print(
                f"FETCHING: {url}"
            )

            r = requests.get(

                proxy_url,

                headers=headers,

                timeout=90

            )

            print(
                f"STATUS: {r.status_code}"
            )

            if (

                r.status_code == 200

                and len(r.text) > 5000

                and "Just a moment" not in r.text

                and "Cloudflare" not in r.text

            ):

                return r.text

        except Exception as e:

            print(
                f"FETCH ERROR: {e}"
            )

    # =====================================================
    # DIRECT FETCH FALLBACK
    # =====================================================

    try:

        r = requests.get(

            url,

            headers=headers,

            timeout=30

        )

        if (

            r.status_code == 200

            and len(r.text) > 5000

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

def search_player(
    name: str
):

    if not name:
        return None

    key = name.lower().strip()

    STATIC = {

        "donk": (
            "21167",
            "donk"
        ),

        "zywoo": (
            "11893",
            "zywoo"
        ),

        "m0nesy": (
            "19230",
            "m0nesy"
        ),

        "niko": (
            "3741",
            "niko"
        ),

        "jl": (
            "14108",
            "jl"
        ),

        "sh1ro": (
            "16920",
            "sh1ro"
        )
    }

    if key in STATIC:

        pid, slug = STATIC[key]

        return (
            pid,
            slug,
            slug.upper()
        )

    html = _fetch(

        f"{HLTV_BASE}/search?query={key}"

    )

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

        slug.replace(
            "-",
            " "
        ).title()

    )

# =========================================================
# PARSE STATS PAGE
# =========================================================

def _extract_series_data(
    soup
):

    rows = soup.find_all("tr")

    print(
        f"TOTAL ROWS: {len(rows)}"
    )

    all_maps = []

    for row in rows:

        try:

            text = row.get_text(
                " ",
                strip=True
            )

            kd_match = re.search(

                r'(\d+)\s*-\s*(\d+)',

                text

            )

            if not kd_match:
                continue

            kills = int(
                kd_match.group(1)
            )

            if kills < 5 or kills > 45:
                continue

            hs = 0

            hs_match = re.search(

                r'\((\d+)\)',

                text

            )

            if hs_match:

                try:

                    hs = int(
                        hs_match.group(1)
                    )

                except:
                    pass

            rating = 0

            rating_match = re.findall(

                r'(\d\.\d{2})',

                text

            )

            if rating_match:

                try:

                    rating = float(
                        rating_match[-1]
                    )

                except:
                    pass

            all_maps.append({

                "kills": kills,

                "hs": hs,

                "rating": rating

            })

        except:
            pass

    print(
        f"MAPS EXTRACTED: "
        f"{len(all_maps)}"
    )

    return all_maps

# =========================================================
# MAIN ENGINE
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

        return (
            "FAIL: Player "
            "not found."
        )

    pid, slug, display = result

    print(
        f"STARTING SCAN: "
        f"{display}"
    )

    stats_url = (

        f"{HLTV_BASE}"

        f"/stats/players/matches/"

        f"{pid}/{slug}"

    )

    html = _fetch(
        stats_url,
        render=True
    )

    if not html:

        return (
            "FAIL: Stats page "
            "blocked by Cloudflare."
        )

    try:

        soup = BeautifulSoup(
            html,
            PARSER
        )

    except Exception as e:

        print(
            f"SOUP ERROR: {e}"
        )

        return (
            "FAIL: BeautifulSoup "
            "parser crashed."
        )

    maps = _extract_series_data(
        soup
    )

    if not maps:

        return (
            "FAIL: No valid "
            "map stats found."
        )

    maps = maps[:20]

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

    hit_rate = 0

    if line:

        hit_rate = round(

            (
                sum(
                    1
                    for x in kills
                    if x > float(line)
                )
                / len(kills)
            ) * 100,

            1
        )

    print(
        f"FINAL AVG: {avg}"
    )

    return {

        "player": display,

        "avg": avg,

        "avg_hs": avg_hs,

        "avg_rating": avg_rating,

        "sample": len(kills),

        "maps": maps,

        "hit_rate": hit_rate

    }

# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    data = get_player_info(
        "donk",
        32.5,
        "vitality"
    )

    print(data)
