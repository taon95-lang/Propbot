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

# ==========================================
# HLTV SCRAPER ENGINE - OPTIMIZED + FIXED
# ==========================================

HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")

# ==========================================
# PERFORMANCE SETTINGS
# ==========================================

MAX_SERIES = 10          # last 10 series
MAX_MAPS = 20            # maps 1-2 only
REQUEST_TIMEOUT = 35
FETCH_RETRIES = 3

# ==========================================
# MAPS
# ==========================================

MAP_ALIASES = {
    "anc": "ancient",
    "mrg": "mirage",
    "d2": "dust2",
    "inf": "inferno",
    "nuke": "nuke",
    "anb": "anubis",
    "vrt": "vertigo",
    "ovp": "overpass",
    "ancient": "ancient",
    "mirage": "mirage",
    "dust2": "dust2",
    "inferno": "inferno",
    "anubis": "anubis",
    "vertigo": "vertigo",
    "overpass": "overpass",
}

# ==========================================
# CACHE
# ==========================================

FETCH_CACHE: Dict[Tuple[str, bool], Tuple[Optional[str], Optional[str]]] = {}
MAPSTATS_CACHE: Dict[str, BeautifulSoup] = {}

# ==========================================
# HELPERS
# ==========================================

def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _split_lines(soup: BeautifulSoup) -> List[str]:
    text = soup.get_text("\n", strip=True)
    return [_norm(line) for line in text.splitlines() if _norm(line)]


def _abs_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return f"{HLTV_BASE}{href}"


def _regex_value(text: str, pattern: str) -> Optional[str]:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None


def _decimal_to_american(decimal_odds: Optional[float]) -> str:
    if decimal_odds is None or decimal_odds <= 1:
        return "N/A"

    if decimal_odds >= 2:
        return f"+{int(round((decimal_odds - 1) * 100))}"

    return f"-{int(round(100 / (decimal_odds - 1)))}"


# ==========================================
# FETCH ENGINE
# ==========================================

def _should_render(url: str) -> bool:
    """
    IMPORTANT:
    Disable JS render for mapstats pages.
    Massive speed improvement.
    """

    if "/stats/matches/mapstatsid/" in url:
        return False

    if "/stats/players/matches/" in url:
        return False

    if "/stats/players/" in url:
        return False

    return True


def _fetch(url: str, render: Optional[bool] = None) -> Tuple[Optional[str], Optional[str]]:

    if render is None:
        render = _should_render(url)

    cache_key = (url, render)

    if cache_key in FETCH_CACHE:
        return FETCH_CACHE[cache_key]

    if not SCRAPERAPI_KEY:
        print("CRITICAL: SCRAPERAPI_KEY missing")
        return None, None

    for attempt in range(FETCH_RETRIES):

        render_param = "&render=true" if render else ""

        proxy_url = (
            "http://api.scraperapi.com"
            f"?api_key={SCRAPERAPI_KEY}"
            f"&url={url}"
            f"{render_param}"
            "&country_code=us"
        )

        try:

            print(
                f"FETCH ATTEMPT {attempt + 1}/{FETCH_RETRIES}: "
                f"{url} (JS_Render={render})"
            )

            response = requests.get(
                proxy_url,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 200 and len(response.text) > 1000:

                final_url = response.headers.get("Sa-Final-Url", url)

                FETCH_CACHE[cache_key] = (
                    response.text,
                    final_url
                )

                return response.text, final_url

            print(
                f"FAILED STATUS={response.status_code} "
                f"LEN={len(response.text)}"
            )

        except Exception as exc:
            print(f"FETCH EXCEPTION: {exc}")

        time.sleep(1.5)

    FETCH_CACHE[cache_key] = (None, None)

    return None, None


def _get_soup(url: str, render: Optional[bool] = None):

    html, final_url = _fetch(url, render=render)

    if not html:
        return None, final_url

    return BeautifulSoup(html, "html.parser"), final_url


# ==========================================
# PLAYER SEARCH
# ==========================================

STATIC_PLAYERS = {
    "donk": ("21167", "donk"),
    "zywoo": ("11893", "zywoo"),
    "m0nesy": ("19230", "m0nesy"),
    "niko": ("3741", "niko"),
    "jl": ("19206", "jl"),
    "xertion": ("20312", "xertion"),
    "henu": ("18848", "henu"),
}


def search_player(name: str):

    name_clean = name.lower().strip()

    if name_clean in STATIC_PLAYERS:

        pid, slug = STATIC_PLAYERS[name_clean]

        print(f"STATIC PLAYER HIT: {name_clean} -> {pid}")

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
            pid = match.group(1)
            slug = match.group(2)

            return pid, slug, slug.title()

    soup = BeautifulSoup(html, "html.parser")

    for link in soup.find_all("a", href=True):

        href = link.get("href", "")

        match = re.search(
            r"/player/(\d+)/([a-zA-Z0-9_-]+)",
            href
        )

        if match:

            pid = match.group(1)
            slug = match.group(2)

            return pid, slug, slug.title()

    return None


# ==========================================
# PROFILE
# ==========================================

def fetch_player_profile(pid: str, slug: str):

    url = f"{HLTV_BASE}/player/{pid}/{slug}"

    soup, _ = _get_soup(url, render=True)

    if not soup:
        return {}

    lines = _split_lines(soup)
    text = "\n".join(lines)

    rating = (
        _regex_value(text, r"Rating 3\.0\s+(\d+\.\d+)")
        or "N/A"
    )

    display = slug.replace("-", " ").title()

    team_name = "N/A"

    for link in soup.find_all("a", href=True):

        href = link.get("href", "")

        if "/team/" in href:

            txt = _norm(link.get_text(" ", strip=True))

            if txt:
                team_name = txt
                break

    return {
        "display_name": display,
        "team_name": team_name,
        "rating_3": rating,
        "profile_soup": soup,
        "profile_url": url,
    }


# ==========================================
# PLAYER STATS
# ==========================================

def fetch_player_stats(pid: str, slug: str):

    url = f"{HLTV_BASE}/stats/players/{pid}/{slug}"

    soup, _ = _get_soup(url, render=False)

    if not soup:
        return {}

    text = soup.get_text("\n", strip=True)

    return {
        "KPR": _regex_value(text, r"Kills / round\s+(\d+\.\d+)") or "N/A",
        "DPR": _regex_value(text, r"Deaths / round\s+(\d+\.\d+)") or "N/A",
        "ADR": _regex_value(text, r"Damage / Round\s+(\d+\.\d+)") or "N/A",
        "KAST": _regex_value(text, r"KAST\s+([0-9.]+%)") or "N/A",
        "Impact": _regex_value(text, r"Impact rating\s+(\d+\.\d+)") or "N/A",
        "HS %": _regex_value(text, r"Headshot %\s+([0-9.]+%)") or "N/A",
    }


# ==========================================
# HISTORY
# ==========================================

def _extract_history_rows(pid: str, slug: str):

    url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"

    soup, _ = _get_soup(url, render=False)

    if not soup:
        return []

    table = soup.find("table")

    if not table:
        return []

    tbody = table.find("tbody")

    if not tbody:
        return []

    rows = tbody.find_all("tr")

    print(f"PROCESSING {len(rows)} TOTAL ROWS")

    valid_rows = []

    for row in rows:

        row_text = _norm(row.get_text(" ", strip=True))

        kd_match = re.search(r"\b(\d+)\s*-\s*(\d+)\b", row_text)

        if not kd_match:
            continue

        map_match = re.search(
            r"\b(anc|mrg|d2|inf|nuke|anb|vrt|ovp)\b",
            row_text,
            flags=re.IGNORECASE,
        )

        if not map_match:
            continue

        team_scores = re.findall(r"\((\d+)\)", row_text)

        rounds_played = None

        if len(team_scores) >= 2:
            rounds_played = (
                int(team_scores[0]) +
                int(team_scores[1])
            )

        mapstats_url = ""

        for link in row.find_all("a", href=True):

            href = link.get("href", "")

            if "/stats/matches/mapstatsid/" in href:
                mapstats_url = _abs_url(href)
                break

        valid_rows.append({
            "kills": int(kd_match.group(1)),
            "deaths": int(kd_match.group(2)),
            "rounds": rounds_played,
            "map_name": MAP_ALIASES.get(
                map_match.group(1).lower(),
                map_match.group(1).lower()
            ),
            "mapstats_url": mapstats_url,
            "row_text": row_text,
        })

    # ==========================================
    # IMPORTANT FIX
    # ONLY KEEP 20 MAPS
    # ==========================================

    valid_rows = valid_rows[:MAX_MAPS]

    print(f"USING {len(valid_rows)} RECENT MAPS")

    return valid_rows


# ==========================================
# MAPSTATS PARSER
# ==========================================

def _parse_mapstats_headshots(
    mapstats_url: str,
    player_candidates: List[str]
):

    if not mapstats_url:
        return None, None

    if mapstats_url in MAPSTATS_CACHE:
        soup = MAPSTATS_CACHE[mapstats_url]
    else:

        soup, _ = _get_soup(
            mapstats_url,
            render=False
        )

        if not soup:
            return None, None

        MAPSTATS_CACHE[mapstats_url] = soup

    for tr in soup.find_all("tr"):

        row_text = _norm(tr.get_text(" ", strip=True))

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

                kills = int(match.group(1))
                hs = int(match.group(2))

                return kills, hs

    return None, None


# ==========================================
# MAP HYDRATION
# ==========================================

def hydrate_maps(
    history_rows,
    player_slug,
    display_name
):

    all_maps = []

    player_candidates = [
        player_slug.lower(),
        display_name.lower(),
    ]

    processed = 0

    for row in history_rows:

        if processed >= MAX_MAPS:
            break

        exact_kills, exact_hs = _parse_mapstats_headshots(
            row["mapstats_url"],
            player_candidates
        )

        if exact_kills is not None:
            row["kills"] = exact_kills

        row["headshots"] = exact_hs

        all_maps.append(row)

        processed += 1

    print(f"HYDRATED {processed} MAPS")

    return all_maps


# ==========================================
# CALCULATIONS
# ==========================================

def bootstrap_distribution(samples, iterations=25000):

    if not samples:
        return np.array([])

    rng = np.random.default_rng(42)

    return rng.choice(
        np.array(samples),
        size=iterations,
        replace=True
    )


def calculate_grade(
    line,
    avg,
    hit_rate,
    over_probability
):

    edge = over_probability - 50

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
    player_name: str,
    line: float = 0.0,
    opponent: str = "N/A"
):

    try:

        # ==========================================
        # SEARCH
        # ==========================================

        result = search_player(player_name)

        if not result:
            return {
                "error": f"Could not find {player_name}"
            }

        pid, slug, display = result

        print(f"TARGET ACQUIRED: {display} ({pid})")

        # ==========================================
        # PROFILE
        # ==========================================

        profile = fetch_player_profile(pid, slug)

        stats = fetch_player_stats(pid, slug)

        # ==========================================
        # HISTORY
        # ==========================================

        history_rows = _extract_history_rows(pid, slug)

        if len(history_rows) < 5:

            return {
                "error": "Not enough recent maps"
            }

        # ==========================================
        # HYDRATE
        # ==========================================

        maps = hydrate_maps(
            history_rows,
            slug,
            display
        )

        if not maps:
            return {
                "error": "Could not hydrate mapstats"
            }

        # ==========================================
        # KILLS
        # ==========================================

        kills = [
            int(m["kills"])
            for m in maps
        ]

        headshots = [
            int(m["headshots"])
            for m in maps
            if isinstance(m.get("headshots"), int)
        ]

        avg_kills = round(_stats.mean(kills), 2)

        median_kills = round(_stats.median(kills), 1)

        hit_rate = round(
            (
                sum(1 for k in kills if k > line)
                / len(kills)
            ) * 100,
            1
        )

        # ==========================================
        # PROJECTION
        # ==========================================

        total_rounds = sum(
            m["rounds"]
            for m in maps
            if isinstance(m.get("rounds"), int)
        )

        total_kills = sum(kills)

        recent_kpr = (
            round(total_kills / total_rounds, 3)
            if total_rounds > 0
            else None
        )

        expected_kills = (
            round(recent_kpr * 44, 1)
            if recent_kpr
            else "N/A"
        )

        # ==========================================
        # SIMULATION
        # ==========================================

        bootstrap = bootstrap_distribution(kills)

        over_probability = round(
            float(np.mean(bootstrap > line) * 100),
            1
        )

        under_probability = round(
            100 - over_probability,
            1
        )

        # ==========================================
        # RECOMMENDATION
        # ==========================================

        if (
            avg_kills > line and
            hit_rate >= 60 and
            over_probability >= 58
        ):
            recommendation = "OVER"

        elif (
            avg_kills < line and
            hit_rate <= 40 and
            under_probability >= 58
        ):
            recommendation = "UNDER"

        else:
            recommendation = "NO BET"

        # ==========================================
        # GRADE
        # ==========================================

        grade = calculate_grade(
            line,
            avg_kills,
            hit_rate,
            over_probability
        )

        # ==========================================
        # RETURN
        # ==========================================

        return {

            "Player": display,
            "Team": profile.get("team_name", "N/A"),
            "Opponent": opponent.title(),
            "Prop Line": f"{line} Kills",

            "Bet recommendation": recommendation,
            "Final grade": grade,

            "Recent average": avg_kills,
            "Recent median": median_kills,
            "Hit rate": f"{hit_rate}%",

            "Over probability": f"{over_probability}%",
            "Under probability": f"{under_probability}%",

            "Projected kills": expected_kills,

            "Rating 3.0": profile.get("rating_3", "N/A"),

            "KPR": stats.get("KPR", "N/A"),
            "DPR": stats.get("DPR", "N/A"),
            "ADR": stats.get("ADR", "N/A"),
            "KAST": stats.get("KAST", "N/A"),
            "Impact": stats.get("Impact", "N/A"),
            "HS %": stats.get("HS %", "N/A"),

            "Recent kills": kills,
            "Recent headshots": headshots,

            "Raw maps": maps,

            "Sample": f"{len(maps)} recent maps",
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
    player_name: str,
    line: float = 0.0,
    opponent: str = "N/A"
):

    payload = get_player_info(
        player_name,
        line,
        opponent
    )

    if payload.get("error"):
        return payload

    hs = payload.get("Recent headshots", [])

    if not hs:
        payload["error"] = "No HS sample"
        return payload

    avg_hs = round(_stats.mean(hs), 1)

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
