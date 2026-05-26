# ==========================================
# HLTV SCRAPER ENGINE - STABLE VERSION
# FIXED:
# - N/A issues
# - timeout issues
# - interaction hangs
# - projection failures
# - bootstrap failures
# - render overload
# ==========================================

import os
import re
import time
import functools
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
from collections import defaultdict
import statistics as _stats
import numpy as np

print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")

MAX_MAPS = 20
REQUEST_TIMEOUT = 18
FETCH_RETRIES = 2

FETCH_CACHE = {}
MAPSTATS_CACHE = {}

MAP_ALIASES = {
    "anc": "ancient",
    "mrg": "mirage",
    "d2": "dust2",
    "inf": "inferno",
    "nuke": "nuke",
    "anb": "anubis",
    "vrt": "vertigo",
    "ovp": "overpass",
}

STATIC_PLAYERS = {
    "donk": ("21167", "donk"),
    "zywoo": ("11893", "zywoo"),
    "m0nesy": ("19230", "m0nesy"),
    "niko": ("3741", "niko"),
    "henu": ("18848", "henu"),
}


# ==========================================
# HELPERS
# ==========================================

def _norm(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _abs_url(href):

    if not href:
        return ""

    if href.startswith("http"):
        return href

    return f"{HLTV_BASE}{href}"


def _regex_value(text, pattern):

    match = re.search(
        pattern,
        text,
        flags=re.IGNORECASE | re.MULTILINE
    )

    if match:
        return match.group(1).strip()

    return None


def _decimal_to_american(decimal_odds):

    if decimal_odds is None:
        return "N/A"

    if decimal_odds <= 1:
        return "N/A"

    if decimal_odds >= 2:
        return f"+{int(round((decimal_odds - 1) * 100))}"

    return f"-{int(round(100 / (decimal_odds - 1)))}"


# ==========================================
# FETCH ENGINE
# ==========================================

def _should_render(url):

    # NO JS RENDER FOR STATS/MAPSTATS

    if "/stats/" in url:
        return False

    if "/mapstatsid/" in url:
        return False

    # ONLY PROFILE + SEARCH PAGES

    return True


def _fetch(url, render=None):

    if render is None:
        render = _should_render(url)

    cache_key = (url, render)

    if cache_key in FETCH_CACHE:
        return FETCH_CACHE[cache_key]

    if not SCRAPERAPI_KEY:
        print("SCRAPERAPI_KEY MISSING")
        return None, None

    render_param = "&render=true" if render else ""

    proxy_url = (
        "http://api.scraperapi.com"
        f"?api_key={SCRAPERAPI_KEY}"
        f"&url={url}"
        f"{render_param}"
        "&country_code=us"
    )

    for attempt in range(FETCH_RETRIES):

        try:

            print(
                f"FETCH ATTEMPT {attempt+1}/{FETCH_RETRIES}: "
                f"{url} (JS_Render={render})"
            )

            response = requests.get(
                proxy_url,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 200:

                if len(response.text) > 1000:

                    final_url = response.headers.get(
                        "Sa-Final-Url",
                        url
                    )

                    FETCH_CACHE[cache_key] = (
                        response.text,
                        final_url
                    )

                    return response.text, final_url

            print(
                f"FAILED STATUS={response.status_code}"
            )

        except Exception as exc:

            print(f"FETCH EXCEPTION: {exc}")

        time.sleep(1)

    # ==========================================
    # FALLBACK WITHOUT JS
    # ==========================================

    if render:

        print("RETRYING WITHOUT JS")

        return _fetch(url, render=False)

    FETCH_CACHE[cache_key] = (None, None)

    return None, None


def _get_soup(url, render=None):

    html, final_url = _fetch(
        url,
        render=render
    )

    if not html:
        return None, final_url

    return BeautifulSoup(
        html,
        "html.parser"
    ), final_url


# ==========================================
# PLAYER SEARCH
# ==========================================

def search_player(name):

    name_clean = name.lower().strip()

    if name_clean in STATIC_PLAYERS:

        pid, slug = STATIC_PLAYERS[name_clean]

        print(f"STATIC PLAYER HIT: {name_clean}")

        return pid, slug, slug.title()

    print(f"SEARCHING HLTV FOR PLAYER: {name_clean}")

    html, final_url = _fetch(
        f"{HLTV_BASE}/search?query={name_clean}",
        render=True
    )

    if not html:
        return None

    if final_url and "/player/" in final_url:

        match = re.search(
            r"/player/(\d+)/([^/]+)",
            final_url
        )

        if match:

            return (
                match.group(1),
                match.group(2),
                match.group(2).title()
            )

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    for link in soup.find_all("a", href=True):

        href = link.get("href", "")

        match = re.search(
            r"/player/(\d+)/([a-zA-Z0-9_-]+)",
            href
        )

        if match:

            return (
                match.group(1),
                match.group(2),
                match.group(2).title()
            )

    return None


# ==========================================
# PROFILE
# ==========================================

def fetch_player_profile(pid, slug):

    url = f"{HLTV_BASE}/player/{pid}/{slug}"

    soup, _ = _get_soup(
        url,
        render=True
    )

    # FALLBACK

    if not soup:

        soup, _ = _get_soup(
            url,
            render=False
        )

    if not soup:

        return {
            "display_name": slug.title(),
            "team_name": "N/A",
            "rating_3": "N/A",
        }

    text = soup.get_text("\n", strip=True)

    rating = (
        _regex_value(
            text,
            r"Rating 3\.0\s+(\d+\.\d+)"
        )
        or "N/A"
    )

    team_name = "N/A"

    for link in soup.find_all("a", href=True):

        href = link.get("href", "")

        if "/team/" in href:

            txt = _norm(
                link.get_text(" ", strip=True)
            )

            if txt:
                team_name = txt
                break

    return {
        "display_name": slug.title(),
        "team_name": team_name,
        "rating_3": rating,
    }


# ==========================================
# PLAYER STATS
# ==========================================

def fetch_player_stats(pid, slug):

    url = f"{HLTV_BASE}/stats/players/{pid}/{slug}"

    soup, _ = _get_soup(
        url,
        render=False
    )

    if not soup:

        return {
            "KPR": "N/A",
            "DPR": "N/A",
            "ADR": "N/A",
            "KAST": "N/A",
            "Impact": "N/A",
            "HS %": "N/A",
        }

    text = soup.get_text("\n", strip=True)

    return {

        "KPR": (
            _regex_value(
                text,
                r"Kills / round\s+(\d+\.\d+)"
            )
            or "N/A"
        ),

        "DPR": (
            _regex_value(
                text,
                r"Deaths / round\s+(\d+\.\d+)"
            )
            or "N/A"
        ),

        "ADR": (
            _regex_value(
                text,
                r"Damage / Round\s+(\d+\.\d+)"
            )
            or "N/A"
        ),

        "KAST": (
            _regex_value(
                text,
                r"KAST\s+([0-9.]+%)"
            )
            or "N/A"
        ),

        "Impact": (
            _regex_value(
                text,
                r"Impact rating\s+(\d+\.\d+)"
            )
            or "N/A"
        ),

        "HS %": (
            _regex_value(
                text,
                r"Headshot %\s+([0-9.]+%)"
            )
            or "N/A"
        ),
    }


# ==========================================
# HISTORY
# ==========================================

def extract_history_rows(pid, slug):

    url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"

    soup, _ = _get_soup(
        url,
        render=False
    )

    if not soup:
        return []

    table = soup.find("table")

    if not table:
        return []

    tbody = table.find("tbody")

    if not tbody:
        return []

    rows = tbody.find_all("tr")

    final_rows = []

    for row in rows:

        row_text = _norm(
            row.get_text(" ", strip=True)
        )

        kd_match = re.search(
            r"\b(\d+)\s*-\s*(\d+)\b",
            row_text
        )

        if not kd_match:
            continue

        map_match = re.search(
            r"\b(anc|mrg|d2|inf|nuke|anb|vrt|ovp)\b",
            row_text,
            flags=re.IGNORECASE,
        )

        if not map_match:
            continue

        scores = re.findall(
            r"\((\d+)\)",
            row_text
        )

        rounds_played = 44

        if len(scores) >= 2:

            rounds_played = (
                int(scores[0]) +
                int(scores[1])
            )

        mapstats_url = ""

        for link in row.find_all("a", href=True):

            href = link.get("href", "")

            if "/mapstatsid/" in href:

                mapstats_url = _abs_url(href)

                break

        final_rows.append({

            "kills": int(kd_match.group(1)),
            "deaths": int(kd_match.group(2)),

            "rounds": rounds_played,

            "map_name": MAP_ALIASES.get(
                map_match.group(1).lower(),
                map_match.group(1).lower()
            ),

            "mapstats_url": mapstats_url,
        })

    final_rows = final_rows[:MAX_MAPS]

    print(f"USING {len(final_rows)} MAPS")

    return final_rows


# ==========================================
# MAPSTATS
# ==========================================

def parse_mapstats(url, player_candidates):

    if not url:
        return None, None

    if url in MAPSTATS_CACHE:

        soup = MAPSTATS_CACHE[url]

    else:

        soup, _ = _get_soup(
            url,
            render=False
        )

        if not soup:
            return None, None

        MAPSTATS_CACHE[url] = soup

    for tr in soup.find_all("tr"):

        row_text = _norm(
            tr.get_text(" ", strip=True)
        )

        lower_row = row_text.lower()

        if any(
            candidate in lower_row
            for candidate in player_candidates
        ):

            match = re.search(
                r"(\d+)\s*\((\d+)\)",
                row_text
            )

            if match:

                return (
                    int(match.group(1)),
                    int(match.group(2))
                )

    return None, None


# ==========================================
# HYDRATE
# ==========================================

def hydrate_maps(
    rows,
    slug,
    display
):

    player_candidates = [
        slug.lower(),
        display.lower(),
    ]

    hydrated = []

    for row in rows:

        exact_kills, exact_hs = parse_mapstats(
            row["mapstats_url"],
            player_candidates
        )

        # ==========================================
        # FALLBACK FIX
        # ==========================================

        if exact_kills is None:
            exact_kills = row["kills"]

        row["kills"] = exact_kills

        row["headshots"] = (
            exact_hs
            if exact_hs is not None
            else 0
        )

        hydrated.append(row)

    return hydrated


# ==========================================
# BOOTSTRAP
# ==========================================

def bootstrap_distribution(
    samples,
    iterations=25000
):

    if not samples:
        return np.array([])

    rng = np.random.default_rng(42)

    return rng.choice(
        np.array(samples),
        size=iterations,
        replace=True
    )


# ==========================================
# GRADE
# ==========================================

def calculate_grade(
    edge,
    hit_rate
):

    if edge >= 25 and hit_rate >= 70:
        return "9.5/10 ELITE"

    if edge >= 18:
        return "8.5/10 STRONG"

    if edge >= 10:
        return "7.5/10 GOOD"

    if edge >= 5:
        return "6.5/10 SMALL EDGE"

    return "5.0/10 NO BET"


# ==========================================
# MAIN
# ==========================================

def get_player_info(
    player_name,
    line=0.0,
    opponent="N/A"
):

    try:

        result = search_player(player_name)

        if not result:

            return {
                "error": f"Could not find {player_name}"
            }

        pid, slug, display = result

        print(f"TARGET ACQUIRED: {display}")

        profile = fetch_player_profile(
            pid,
            slug
        )

        stats = fetch_player_stats(
            pid,
            slug
        )

        rows = extract_history_rows(
            pid,
            slug
        )

        if not rows:

            return {
                "error": "No match history"
            }

        maps = hydrate_maps(
            rows,
            slug,
            display
        )

        kills = [
            int(m["kills"])
            for m in maps
        ]

        # ==========================================
        # BOOTSTRAP FIX
        # ==========================================

        if not kills:

            kills = [
                m["kills"]
                for m in rows[:10]
            ]

        headshots = [
            int(m["headshots"])
            for m in maps
        ]

        avg = round(_stats.mean(kills), 2)

        median = round(_stats.median(kills), 1)

        hit_rate = round(
            (
                sum(1 for k in kills if k > line)
                / len(kills)
            ) * 100,
            1
        )

        total_rounds = sum(
            m["rounds"]
            for m in maps
        )

        total_kills = sum(kills)

        recent_kpr = round(
            total_kills / total_rounds,
            3
        )

        projection = round(
            recent_kpr * 44,
            1
        )

        bootstrap = bootstrap_distribution(kills)

        simulated_mean = round(
            float(np.mean(bootstrap)),
            2
        )

        simulated_median = round(
            float(np.median(bootstrap)),
            2
        )

        std_dev = round(
            float(np.std(bootstrap)),
            2
        )

        over_probability = round(
            float(np.mean(bootstrap > line) * 100),
            1
        )

        under_probability = round(
            100 - over_probability,
            1
        )

        edge = round(
            over_probability - 50,
            1
        )

        if (
            avg > line and
            hit_rate >= 60 and
            over_probability >= 58
        ):

            recommendation = "OVER"

        elif (
            avg < line and
            hit_rate <= 40 and
            under_probability >= 58
        ):

            recommendation = "UNDER"

        else:

            recommendation = "NO BET"

        grade = calculate_grade(
            edge,
            hit_rate
        )

        return {

            "Player": display,
            "Opponent": opponent.title(),

            "Prop Line": f"{line} Kills",

            "Bet recommendation": recommendation,

            "Final grade": grade,

            "Recent average": avg,
            "Recent median": median,

            "Projected kills": projection,

            "Hit rate": f"{hit_rate}%",

            "Over probability": f"{over_probability}%",
            "Under probability": f"{under_probability}%",

            "Edge vs line": f"{edge}%",

            "Simulated mean": simulated_mean,
            "Simulated median": simulated_median,
            "Std Dev": std_dev,

            "Rating 3.0": profile.get(
                "rating_3",
                "N/A"
            ),

            "Team": profile.get(
                "team_name",
                "N/A"
            ),

            "KPR": stats.get(
                "KPR",
                "N/A"
            ),

            "DPR": stats.get(
                "DPR",
                "N/A"
            ),

            "ADR": stats.get(
                "ADR",
                "N/A"
            ),

            "KAST": stats.get(
                "KAST",
                "N/A"
            ),

            "Impact": stats.get(
                "Impact",
                "N/A"
            ),

            "HS %": stats.get(
                "HS %",
                "N/A"
            ),

            "Recent kills": kills,
            "Recent headshots": headshots,

            "Raw maps": maps,

            "Sample": f"{len(maps)} maps",
        }

    except Exception as exc:

        print(f"CRITICAL FAILURE: {exc}")

        return {
            "error": str(exc)
        }


# ==========================================
# HEADSHOTS
# ==========================================

def get_headshot_info(
    player_name,
    line=0.0,
    opponent="N/A"
):

    payload = get_player_info(
        player_name,
        line,
        opponent
    )

    if payload.get("error"):
        return payload

    hs = payload.get(
        "Recent headshots",
        []
    )

    if not hs:

        return {
            "error": "No HS sample"
        }

    avg_hs = round(
        _stats.mean(hs),
        1
    )

    hit_rate = round(
        (
            sum(1 for x in hs if x > line)
            / len(hs)
        ) * 100,
        1
    )

    bootstrap = bootstrap_distribution(hs)

    over_probability = round(
        float(np.mean(bootstrap > line) * 100),
        1
    )

    under_probability = round(
        100 - over_probability,
        1
    )

    if avg_hs > line and hit_rate >= 60:
        recommendation = "OVER"
    elif avg_hs < line and hit_rate <= 40:
        recommendation = "UNDER"
    else:
        recommendation = "NO BET"

    payload["Prop Line"] = f"{line} Headshots"

    payload["Bet recommendation"] = recommendation

    payload["Recent average"] = avg_hs

    payload["Hit rate"] = f"{hit_rate}%"

    payload["Over probability"] = f"{over_probability}%"

    payload["Under probability"] = f"{under_probability}%"

    return payload


__all__ = [
    "get_player_info",
    "get_headshot_info",
    "search_player",
]
