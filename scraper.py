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

            if r.status_code == 200:

                if "Just a moment" in r.text:
                    print("Cloudflare page detected")
                    time.sleep(2)
                    continue

                return r.text

            time.sleep(1)

        except Exception as e:

            print(f"FETCH ERROR: {e}")

            time.sleep(1)

    return None

# =========================================================
# SEARCH PLAYER
# =========================================================

def search_player(name: str):

    if not name:
        return None

    key = name.lower().strip()

    if key == "donk":
        return ("21167", "donk", "donk")

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

def get_player_match_ids(player_id, max_matches=10):

    url = f"{HLTV_BASE}/results?player={player_id}"

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

def _parse_match_kills(html, player_slug):

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

        kd = re.search(
            r'(\d+)\s*-\s*(\d+)',
            txt
        )

        if kd:

            kills = int(
                kd.group(1)
            )

            hs_match = re.search(
                r'\((\d+)\)',
                txt
            )

            hs = None

            if hs_match:
                hs = int(
                    hs_match.group(1)
                )

            rating_match = re.search(
                r'(\d\.\d{2})',
                txt
            )

            rating = None

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

def get_player_info(player_name, opponent=None):

    result = search_player(
        player_name
    )

    if not result:
        return None

    pid, slug, display = result

    print(f"FOUND PLAYER: {display}")

    match_ids = get_player_match_ids(
        pid,
        max_matches=10
    )

    print(f"MATCHES FOUND: {len(match_ids)}")

    all_maps = []

    for match_id, match_slug in match_ids:

        try:

            url = (
                f"{HLTV_BASE}/matches/"
                f"{match_id}/{match_slug}"
            )

            html = _fetch(url)

            if not html:
                continue

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

            for m in maps:

                if m.get("kills") is not None:

                    all_maps.append({
                        "kills": m.get("kills"),
                        "hs": m.get("hs"),
                        "rating": m.get("rating")
                    })

            time.sleep(
                random.uniform(0.5, 1.0)
            )

        except Exception as e:

            print(
                f"MATCH PARSE ERROR: {e}"
            )

    if not all_maps:

        return {
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
