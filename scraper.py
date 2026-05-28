import os
import re
import time
import math
import functools
from datetime import date, datetime, timedelta
from statistics import mean, median
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

try:
    import numpy as np
except Exception:
    np = None

print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except Exception:
    import requests

HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")

REQUEST_TIMEOUT = 22
FETCH_RETRIES = 5
MAX_RECENT_MAPS = 40
MAX_RECENT_SERIES = 10

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

FETCH_CACHE: Dict[Tuple[str, bool], Tuple[Optional[str], Optional[str]]] = {}
SOUP_CACHE: Dict[Tuple[str, bool], Tuple[Optional[BeautifulSoup], Optional[str], Optional[str]]] = {}

MAP_ALIASES = {
    "anc": "Ancient",
    "anb": "Anubis",
    "azk": "Aztec",
    "blz": "Blitz",
    "cob": "Cobblestone",
    "dee": "Deep",
    "dmm": "Demor",
    "dck": "Duostand",
    "ivy": "Ivy",
    "fun": "Arena",
    "gin": "Inferno",
    "its": "Inferno",
    "mir": "Mirage",
    "nuke": "Nuke",
    "ovp": "Overpass",
    "stf": "Stfi",
    "sin": "Seven",
    "gla": "Glacial",
    "dust": "Dust2",
    "vertigo": "Vertigo",
    "tuscan": "Tuscan",
    "tuska": "Tuscan",
    "split": "Split",
    "train": "Train",
    "vert": "Vertigo",
}

# Static player mapping for common players
STATIC_PLAYERS = {}


def _should_render(url: str) -> bool:
    """Determine if URL needs JavaScript rendering"""
    # HLTV pages generally don't need rendering, but add check if needed
    return False


def _slugify(name: str) -> str:
    """Normalize player names for matching on HLTV's index."""
    return re.sub(r"[^\w]+", "", name).lower()


def _safe_int(val: Any) -> Optional[int]:
    try:
        if val is None or val == "N/A":
            return None
        return int(str(val).split()[0])
    except Exception:
        return None


def _safe_float(val: Any) -> Optional[float]:
    try:
        if val is None or val == "N/A":
            return None
        s = str(val)
        if s.endswith("%"):
            return float(s[:-1])
        return float(s)
    except Exception:
        return None


def _safe_pct_value(val: str) -> Optional[float]:
    try:
        if not val:
            return None
        # percent values come as "xx.x%" or "xx.x%/yy.y%"
        if "/" in val:
            val = val.split("/")[0]
        val = val.strip("%")
        return float(val)
    except Exception:
        return None


def _normalize_team(name: str) -> str:
    name = name or ""
    name = name.strip().lower()
    return name


def _fetch(url: str, render: Optional[bool] = None) -> Tuple[Optional[str], Optional[str]]:
    if render is None:
        render = _should_render(url)

    cache_key = (url, render)
    if cache_key in FETCH_CACHE:
        return FETCH_CACHE[cache_key]

    encoded = quote_plus(url, safe=":/?=&")
    target = url
    if SCRAPERAPI_KEY:
        target = (
            "http://api.scraperapi.com"
            f"?api_key={SCRAPERAPI_KEY}"
            f"&url={encoded}"
            f"{'&render=true' if render else ''}"
            "&country_code=us"
            "&keep_headers=true"
        )

    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            resp = requests.get(target, timeout=REQUEST_TIMEOUT, headers=DEFAULT_HEADERS)
            if getattr(resp, "status_code", 0) == 403:
                # HLTV is blocking us
                raise Exception(f"HLTV request blocked (HTTP 403) for {url}")
            if getattr(resp, "status_code", 0) == 200 and getattr(resp, "text", None):
                final_url = resp.headers.get("Sa-Final-Url") or url
                FETCH_CACHE[cache_key] = (resp.text, final_url)
                return resp.text, final_url
            print(f"FETCH FAILED {attempt}/{FETCH_RETRIES}: {url} -> {getattr(resp, 'status_code', 'ERR')}")
        except Exception as exc:
            print(f"FETCH EXCEPTION {attempt}/{FETCH_RETRIES}: {url} -> {exc}")
        time.sleep(1)

    if SCRAPERAPI_KEY and render:
        return _fetch(url, render=False)

    FETCH_CACHE[cache_key] = (None, None)
    return None, None


def _get_soup(url: str, render: Optional[bool] = None) -> Tuple[Optional[BeautifulSoup], Optional[str], Optional[str]]:
    if render is None:
        render = _should_render(url)

    cache_key = (url, render)
    if cache_key in SOUP_CACHE:
        return SOUP_CACHE[cache_key]

    html, final_url = _fetch(url, render=render)
    if not html:
        SOUP_CACHE[cache_key] = (None, final_url, None)
        return None, final_url, None

    soup = BeautifulSoup(html, "html.parser")
    SOUP_CACHE[cache_key] = (soup, final_url, html)
    return soup, final_url, html


def _lines_from_soup(soup: Optional[BeautifulSoup]) -> List[str]:
    if not soup:
        return []
    raw = soup.get_text("\n", strip=True)
    return [_norm(line) for line in raw.splitlines() if _norm(line)]


def _norm(s: str) -> str:
    return s.strip() if s else ""


def _find_label(
    lines: List[str], label: str, occurrence: int = 1, exact: bool = False
) -> List[int]:
    hits = []
    for idx, line in enumerate(lines):
        cur = line.lower().strip()
        if (cur == label) if exact else (label in cur):
            hits.append(idx)
    return hits


def _value_after(
    lines: List[str],
    label: str,
    pattern: str,
    occurrence: int = 1,
    lookahead: int = 8,
    exact: bool = True,
) -> Optional[str]:
    hits = _find_label(lines, label, exact=exact)
    if not hits or occurrence - 1 >= len(hits):
        return None
    idx = hits[occurrence - 1]
    for offset in range(1, lookahead + 1):
        if idx + offset < len(lines):
            if re.match(pattern, lines[idx + offset]):
                return lines[idx + offset]
    return None


def _find_element_by_text(soup: BeautifulSoup, tag: str, text: str) -> Optional[BeautifulSoup]:
    try:
        return soup.find(tag, text=re.compile(text, flags=re.IGNORECASE))
    except Exception:
        return None


def search_player(name: str) -> Optional[Tuple[str, str, str]]:
    key = _slugify(name)
    if key in STATIC_PLAYERS:
        pid, slug = STATIC_PLAYERS[key]
        return pid, slug, slug

    query = quote_plus(name)
    soup, _, _ = _get_soup(f"{HLTV_BASE}/search?query={query}")
    if not soup:
        return None

    results = soup.select("a[href*='/player/'], a[href*='/player/']")
    if not results:
        return None

    for a in results:
        href = a.get("href", "")
        m = re.match(r"/player/(\d+)/(.*)", href)
        if m:
            pid, slug = m.group(1), m.group(2)
            # Found first occurrence
            return pid, slug, slug
    return None


def fetch_player_profile(pid: str, slug: str) -> Dict[str, Any]:
    soup, _, _ = _get_soup(f"{HLTV_BASE}/player/{pid}/{slug}", render=True)
    if not soup:
        soup, _, _ = _get_soup(f"{HLTV_BASE}/player/{pid}/{slug}", render=False)

    if not soup:
        return {
            "display_name": slug,
            "team_name": "N/A",
            "team_id": None,
            "team_slug": None,
            "team_ranking": "N/A",
            "rating_3": "N/A",
            "profile_buckets": {},
        }

    display_name = soup.select_one(".player-name")
    display_name = display_name.text.strip() if display_name else slug

    team_tag = soup.select_one(".player-team a")
    team_name = team_tag.text if team_tag else "N/A"
    team_slug = team_tag["href"].split("/")[-1] if team_tag else None
    team_id = re.search(r"/teams/(\d+)", team_tag["href"]).group(1) if team_tag else None

    team_rank = soup.select_one(".player-team a + span")
    team_rank = team_rank.text if team_rank else "N/A"

    rating_3 = soup.select_one(".player-ratings .rating")
    rating_3 = rating_3.text.strip() if rating_3 else "N/A"
    try:
        rating_3 = float(rating_3)
    except Exception:
        rating_3 = None

    buckets = {}
    for bucket in soup.select(".playerProfile .stats .buckets .bucket"):
        title = bucket.select_one(".name")
        if not title:
            continue
        title = title.text.strip()
        stat = bucket.select_one(".value")
        stat_val = stat.text if stat else "N/A"
        buckets[title] = stat_val

    return {
        "display_name": display_name,
        "team_name": team_name,
        "team_id": team_id,
        "team_slug": team_slug,
        "team_ranking": team_rank,
        "rating_3": rating_3,
        "profile_buckets": buckets,
    }


def fetch_player_stats(pid: str, slug: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
    url = f"{HLTV_BASE}/stats/players/{pid}/{slug}/"
    params = []
    if start_date:
        params.append(f"startDate={start_date}")
    if end_date:
        params.append(f"endDate={end_date}")
    if params:
        url = f"{url}?{'&'.join(params)}"
    soup, _, _ = _get_soup(url)
    if not soup:
        return []
    rows = []
    table = soup.select_one("table.player-ratings-table")
    if not table:
        return []
    for tr in table.select("tbody tr"):
        cols = tr.select("td")
        if not cols or len(cols) < 9:
            continue
        row = {
            "date": cols[0].text.strip(),
            "event": cols[1].text.strip(),
            "opponent": cols[2].text.strip(),
            "map": cols[3].text.strip(),
            "score": cols[4].text.strip(),
            "kast": cols[5].text.strip(),
            "rating": cols[6].text.strip(),
            "impact": cols[7].text.strip(),
            "adr": cols[8].text.strip(),
        }
        rows.append(row)
    return rows


def extract_history_rows(pid: str, slug: str) -> List[Dict[str, Any]]:
    soup, _, _ = _get_soup(f"{HLTV_BASE}/stats/players/{pid}/{slug}/matches")
    if not soup:
        return []
    rows = []
    for tr in soup.select("table.matches tr"):
        cols = [td.text.strip() for td in tr.select("td")]
        if not cols or len(cols) < 11:
            continue
        rows.append({
            "date": cols[0],
            "event": cols[1],
            "match": cols[2],
            "team": cols[3],
            "opp": cols[4],
            "maps": cols[5],
            "result": cols[6],
            "rounds": cols[7],
            "kills": cols[8],
            "assists": cols[9],
            "deaths": cols[10],
            "adr": cols[11],
            "kast": cols[12] if len(cols) > 12 else None,
            "hltv_score": cols[13] if len(cols) > 13 else None,
            "headshots": cols[14] if len(cols) > 14 else None,
        })
    return rows


def hydrate_maps(rows: List[Dict[str, Any]], slug: str, display_name: str) -> List[Dict[str, Any]]:
    for row in rows:
        team = row["team"] or ""
        opp = row["opp"] or ""
        row["Team"] = team
        row["Opponent"] = opp
        row["Match"] = row.get("match", "")
        row["Maps"] = row.get("maps", "")
        row["Team ranking"] = row.get("team", "")
        row["Opponent ranking"] = row.get("opp", "")
        row["Kills"] = row.get("kills", "")
        row["Assists"] = row.get("assists", "")
        row["Deaths"] = row.get("deaths", "")
        row["KAST"] = row.get("kast", "")
        row["ADR"] = row.get("adr", "")
        row["Rating 2.0"] = ""
        row["Rating 3.0"] = ""
        row["Impact"] = ""
        row["HPots"] = ""
        row["CT or T side"] = row.get("Maps", "")
        row["Result"] = row.get("result", "")
        row["Date"] = row.get("date", "")
        row["Opp"] = opp
        row["HS%"] = None
    return rows


def pair_recent_series(rows: List[Dict[str, Any]], max_series: Optional[int] = None) -> List[Dict[str, Any]]:
    series = []
    for row in rows:
        series.append(row)
        if row.get("maps", "").startswith("best of"):
            if max_series and len(series) >= max_series:
                break
    return series


def _sample_stats(samples: List[int], line: float) -> Dict[str, Any]:
    if not samples:
        return {"avg": None, "median": None, "sd": None, "over_probability": None, "under_probability": None, "hit_rate": None}
    avg = mean(samples)
    med = median(samples)
    if len(samples) > 1:
        try:
            import statistics
            sd = statistics.pstdev(samples)
        except Exception:
            sd = None
    else:
        sd = None
    # approximate probabilities
    over = sum(1 for s in samples if s >= line) / len(samples) * 100
    under = sum(1 for s in samples if s < line) / len(samples) * 100
    # hit rate defined as probability that actual stat >= line if going over, or complement if going under
    hit_rate = over if avg >= line else (100 - over)
    return {
        "avg": round(avg, 2) if avg is not None else None,
        "median": round(med, 2) if med is not None else None,
        "sd": round(sd, 2) if sd is not None else None,
        "over_probability": round(over, 2),
        "under_probability": round(under, 2),
        "hit_rate": round(hit_rate, 2),
    }


def _grade(edge: float, hit_rate: float) -> str:
    # Example grading system
    if edge is None or hit_rate is None:
        return "N/A"
    score = edge * hit_rate / 100
    if score >= 25:
        return "A"
    if score >= 15:
        return "B"
    if score >= 10:
        return "C"
    if score >= 5:
        return "D"
    return "E"


def _opponent_strength_model(payload: Dict[str, Any]) -> Dict[str, Any]:
    target_team = payload.get("Team", "")
    target_rank = payload.get("Team ranking", "")
    opponent_team = payload.get("Opponent", "")
    opponent_rank = payload.get("Opponent ranking", "")

    strength = "N/A"
    note = "N/A"
    if target_rank and opponent_rank:
        try:
            rank_val = float(target_rank)
            opp_rank_val = float(opponent_rank)
            if rank_val <= opp_rank_val:
                strength = "Strong favorite"
                note = "Team is ranked equal or higher than opponent."
            else:
                diff = rank_val - opp_rank_val
                if diff < 5:
                    strength = "Moderate favorite"
                    note = "Team has slightly higher rank."
                elif diff < 15:
                    strength = "Slight favorite"
                    note = "Team has moderately higher rank."
                else:
                    strength = "Weak favorite"
                    note = "Team has significantly higher rank."
        except Exception:
            strength = "N/A"
    return {"Opponent strength": strength, "Opponent strength note": note}


def build_payload_analytics(payload: Dict[str, Any], line: float, kill_mode: bool = True) -> Dict[str, Any]:
    team_name = str(payload.get("Team", "N/A"))
    opponent_name = str(payload.get("Opponent", "N/A"))
    team_rank = _safe_int(payload.get("Team ranking"))
    opponent_rank = _safe_int(payload.get("Opponent ranking"))
    public_pick = payload.get("Public pick", "N/A")
    odds = payload.get("Thunderpick odds", payload.get("Match odds", "N/A"))
    h2h = payload.get("H2H Data", {}) or {}
    map_counts = payload.get("Likely maps", {}) or {}
    per_map = payload.get("Per-map averages", {}) or {}
    projection = payload.get("Projected kills", None)
    recent_avg = payload.get("Recent average", None)

    rating = _safe_float(payload.get("Rating 3.0"))
    kpr = _safe_float(payload.get("Kills per round"))
    dpr = _safe_float(payload.get("Deaths per round"))
    kast = _safe_float(payload.get("KAST"))
    impact = _safe_float(payload.get("Impact"))
    firepower = _safe_pct_value(str(payload.get("Firepower", "")))
    opening = _safe_pct_value(str(payload.get("Opening", "")).split("/")[0]) if "/" in str(payload.get("Opening", "")) else None
    entrying = _safe_pct_value(str(payload.get("Entrying", "")).split("/")[0]) if "/" in str(payload.get("Entrying", "")) else None
    trading = _safe_pct_value(str(payload.get("Trading", "")).split("/")[0]) if "/" in str(payload.get("Trading", "")) else None

    opponent_strength = payload.get("Opponent strength", "N/A")
    opponent_strength_note = payload.get("Opponent strength note", "N/A")

    stats = {
        "Team": team_name,
        "Opponent": opponent_name,
        "Team ranking": team_rank,
        "Opponent ranking": opponent_rank,
        "Public pick": public_pick,
        "Odds": odds,
        "H2H Data": h2h,
        "Likely maps": map_counts,
        "Per-map averages": per_map,
        "Projected kills": projection,
        "Recent average": recent_avg,
        "Rating 3.0": rating,
        "KPR": kpr,
        "DPR": dpr,
        "KAST": kast,
        "Impact": impact,
        "Firepower": firepower,
        "Opening": opening,
        "Entrying": entrying,
        "Trading": trading,
        "Opponent strength": opponent_strength,
        "Opponent strength note": opponent_strength_note,
    }
    return stats


def _build_payload(player_name: str, line: float = 0.0, opponent: str = "N/A", kill_mode: bool = True) -> Dict[str, Any]:
    """Build player payload with stats and analytics"""
    print(f"DEBUG: Building payload for {player_name} with line {line}")
    
    try:
        # Return a basic mock payload to test the flow
        payload = {
            "Player": player_name,
            "Team": "Team Name",
            "Team ranking": 10,
            "Opponent": opponent,
            "Opponent ranking": 15,
            "Rating 3.0": 1.15,
            "Kills per round": 0.65,
            "Deaths per round": 0.55,
            "KAST": 72.5,
            "Impact": 1.05,
            "Firepower": 85.0,
            "Opening": 60.0,
            "Entrying": 55.0,
            "Trading": 70.0,
            "Projected kills": line + 2.5,
            "Recent average": line + 1.5,
            "Recent median": line + 1.0,
            "Over probability": 55.0,
            "Under probability": 45.0,
            "Hit rate": 58.0,
            "Edge vs line": 2.5,
            "Bet recommendation": "OVER",
            "Final grade": "B",
            "H2H Data": {},
            "H2H rows": [],
            "Likely maps": {},
            "Per-map averages": {},
            "Opponent strength": "Moderate favorite",
            "Opponent strength note": "Team is ranked higher than opponent",
        }
        
        print(f"DEBUG: Payload built successfully")
        return payload
    except Exception as exc:
        print(f"ERROR in _build_payload: {exc}")
        import traceback
        traceback.print_exc()
        return {"error": str(exc)}


def get_player_info(player_name: str, line: float = 0.0, opponent: str = "N/A") -> Dict[str, Any]:
    try:
        return _build_payload(player_name=player_name, line=float(line), opponent=opponent, kill_mode=True)
    except Exception as exc:
        print(f"CRITICAL FAILURE in get_player_info: {exc}")
        return {"error": str(exc)}


def get_headshot_info(player_name: str, line: float = 0.0, opponent: str = "N/A") -> Dict[str, Any]:
    try:
        payload = _build_payload(player_name=player_name, line=float(line), opponent=opponent, kill_mode=False)
        if payload.get("error"):
            return payload
        payload["Prop Line"] = f"{line} Headshots"
        return payload
    except Exception as exc:
        print(f"CRITICAL FAILURE in get_headshot_info: {exc}")
        return {"error": str(exc)}
