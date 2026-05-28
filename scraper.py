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
FETCH_RETRIES = 3
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
    "d2": "Dust2",
    "inf": "Inferno",
    "mrg": "Mirage",
    "nuke": "Nuke",
    "ovp": "Overpass",
    "trn": "Train",
    "vrt": "Vertigo",
    "cbl": "Cobblestone",
    "cch": "Cache",
    "tcn": "Tuscan",
    "ssn": "Season",
}

STATIC_PLAYERS = {
    "donk": ("21167", "donk"),
    "zywoo": ("11893", "zywoo"),
    "m0nesy": ("19230", "m0nesy"),
    "niko": ("3741", "niko"),
    "s1mple": ("7998", "s1mple"),
    "ropz": ("11816", "ropz"),
    "sh1ro": ("16920", "sh1ro"),
    "szejn": ("17113", "szejn"),
}

ATTR_BUCKET_KEYS = (
    "Firepower",
    "Entrying",
    "Trading",
    "Opening",
    "Clutching",
    "Sniping",
    "Utility",
)

MAP_NAMES = (
    "Ancient",
    "Anubis",
    "Cache",
    "Cobblestone",
    "Dust2",
    "Inferno",
    "Mirage",
    "Nuke",
    "Overpass",
    "Season",
    "Train",
    "Tuscan",
    "Vertigo",
)

TEAM_MAP_WINDOW_DAYS = 90
H2H_WINDOW_DAYS = 90


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).replace("\xa0", " ").strip()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _abs_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return f"{HLTV_BASE}{href}"


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace("%", "").replace("#", "").strip())
    except Exception:
        return None


def _fmt_rank(value: Optional[int]) -> str:
    return f"#{value}" if value else "N/A"


def _decimal_to_american(decimal_odds: Optional[float]) -> str:
    if decimal_odds is None or decimal_odds <= 1:
        return "N/A"
    if decimal_odds >= 2:
        return f"+{int(round((decimal_odds - 1.0) * 100))}"
    return f"-{int(round(100 / (decimal_odds - 1.0)))}"


def _today_range(days: int = 30) -> Tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def _should_render(url: str) -> bool:
    url_lower = url.lower()
    if any(x in url_lower for x in (
        "/stats/players/",
        "/stats/players/matches/",
        "/stats/matches/mapstatsid/",
        "/ranking/teams/",
    )):
        return False
    if any(x in url_lower for x in ("/search?", "/player/", "/matches/", "/betting/analytics/")):
        return True
    return False


def _fetch(url: str, render: Optional[bool] = None) -> Tuple[Optional[str], Optional[str]]:
    if render is None:
        render = _should_render(url)

    cache_key = (url, bool(render))
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

    cache_key = (url, bool(render))
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


def _find_line_indices(lines: List[str], label: str, exact: bool = True) -> List[int]:
    target = label.lower().strip()
    hits = []
    for idx, line in enumerate(lines):
        cur = line.lower().strip()
        if (cur == target) if exact else (target in cur):
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
    hits = _find_line_indices(lines, label, exact=exact)
    if len(hits) < occurrence:
        return None
    idx = hits[occurrence - 1]
    rx = re.compile(pattern)
    for j in range(idx + 1, min(len(lines), idx + 1 + lookahead)):
        if rx.fullmatch(lines[j]):
            return lines[j]
    return None


def _value_before(
    lines: List[str],
    label: str,
    pattern: str,
    occurrence: int = 1,
    lookback: int = 4,
    exact: bool = True,
) -> Optional[str]:
    hits = _find_line_indices(lines, label, exact=exact)
    if len(hits) < occurrence:
        return None
    idx = hits[occurrence - 1]
    rx = re.compile(pattern)
    for j in range(idx - 1, max(-1, idx - 1 - lookback), -1):
        if rx.fullmatch(lines[j]):
            return lines[j]
    return None



def _parse_hltv_date(value: Any) -> Optional[date]:
    raw = _norm(value)
    if not raw:
        return None
    for fmt in ("%d/%m/%y", "%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    return None


def _within_days(value: Any, max_age_days: int) -> bool:
    parsed = _parse_hltv_date(value)
    if not parsed:
        return False
    return (date.today() - parsed).days <= max_age_days


def _team_name_matches(left: str, right: str) -> bool:
    l_key = _slugify(str(left or ""))
    r_key = _slugify(str(right or ""))
    if not l_key or not r_key:
        return False
    return l_key == r_key or l_key in r_key or r_key in l_key


def _strip_score_suffix(value: str) -> str:
    return _norm(re.sub(r"\(\d+\)$", "", _norm(value))).strip()


def _extract_first_match(line: str, pattern: str) -> Optional[str]:
    m = re.search(pattern, str(line or ""), flags=re.I | re.S)
    if not m:
        return None
    return _norm(m.group(1) if m.groups() else m.group(0))


def _value_near(
    lines: List[str],
    label: str,
    pattern: str,
    occurrence: int = 1,
    window: int = 8,
    exact: bool = True,
) -> Optional[str]:
    hits = _find_line_indices(lines, label, exact=exact)
    if len(hits) < occurrence:
        return None
    idx = hits[occurrence - 1]
    rx = re.compile(pattern, flags=re.I)
    for j in range(max(0, idx - window), min(len(lines), idx + window + 1)):
        m = rx.search(lines[j])
        if m:
            return _norm(m.group(1) if m.groups() else m.group(0))
    return None


def _normalise_bucket_score(value: Any) -> str:
    """Return HLTV attribute values as X/100, never as a bare label."""
    raw = _norm(value)
    if not raw or raw.upper() == "N/A":
        return "N/A"
    m = re.search(r"(\d{1,3})\s*/\s*100", raw)
    if m:
        n = max(0, min(100, int(m.group(1))))
        return f"{n}/100"
    m = re.fullmatch(r"\d{1,3}", raw)
    if m:
        n = max(0, min(100, int(raw)))
        return f"{n}/100"
    return "N/A"


def _extract_bucket_scores(lines: List[str]) -> Dict[str, str]:
    """Extract HLTV's seven profile attribute buckets as numeric X/100 scores.

    HLTV sometimes renders attributes as separate label/value nodes and sometimes as
    compact text around the label. This parser handles both layouts.
    """
    buckets: Dict[str, str] = {}
    compact_text = " ".join(lines)
    for label in ATTR_BUCKET_KEYS:
        value = (
            _value_near(lines, label, r"(\d{1,3}\s*/\s*100)", window=10, exact=True)
            or _value_after(lines, label, r"\d{1,3}", lookahead=5, exact=True)
            or _value_before(lines, label, r"\d{1,3}", lookback=5, exact=True)
            or _extract_first_match(compact_text, rf"{re.escape(label)}\s*(?:score)?\s*(\d{{1,3}}\s*/\s*100)")
            or _extract_first_match(compact_text, rf"(\d{{1,3}}\s*/\s*100)\s*{re.escape(label)}")
            or _extract_first_match(compact_text, rf"{re.escape(label)}\s*(?:score)?\s*(\d{{1,3}})(?!\d)")
        )
        buckets[label] = _normalise_bucket_score(value)
    return buckets


def _extract_team_link(anchor: Any) -> Optional[Dict[str, str]]:
    if anchor is None:
        return None
    href = anchor.get("href", "") if hasattr(anchor, "get") else ""
    text = _norm(anchor.get_text(" ", strip=True)) if hasattr(anchor, "get_text") else ""
    m = re.search(r"/team/(\d+)/([^/?#]+)", href)
    if not (m and text):
        return None
    return {"id": m.group(1), "slug": m.group(2), "name": text, "url": _abs_url(href)}


def _extract_team_links_from_soup(soup: Optional[BeautifulSoup], limit: int = 12) -> List[Dict[str, str]]:
    if not soup:
        return []
    teams: List[Dict[str, str]] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        info = _extract_team_link(a)
        if not info:
            continue
        key = (info["id"], _slugify(info["name"]))
        if key in seen:
            continue
        seen.add(key)
        teams.append(info)
        if len(teams) >= limit:
            break
    return teams


def _resolve_match_teams(team_links: List[Dict[str, str]], player_team: str, opponent: str) -> Tuple[Optional[Dict[str, str]], Optional[Dict[str, str]]]:
    player_entry = next((x for x in team_links if _team_name_matches(x.get("name", ""), player_team)), None)
    opponent_entry = next((x for x in team_links if _team_name_matches(x.get("name", ""), opponent) and (not player_entry or x.get("id") != player_entry.get("id"))), None)
    if player_entry and not opponent_entry:
        opponent_entry = next((x for x in team_links if x.get("id") != player_entry.get("id")), None)
    if opponent_entry and not player_entry:
        player_entry = next((x for x in team_links if x.get("id") != opponent_entry.get("id")), None)
    if not player_entry and team_links:
        player_entry = team_links[0]
    if not opponent_entry and len(team_links) > 1:
        opponent_entry = next((x for x in team_links if x.get("id") != (player_entry or {}).get("id")), team_links[1])
    return player_entry, opponent_entry


def _parse_pick_line(value: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not value or value == "N/A":
        return out
    for chunk in str(value).split("|"):
        part = _norm(chunk)
        m = re.match(r"(.+?)\s+(\d+(?:\.\d+)?)%$", part)
        if m:
            out[_norm(m.group(1))] = float(m.group(2))
    return out


def _parse_odds_line(value: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not value or value == "N/A":
        return out
    for chunk in str(value).split("|"):
        part = _norm(chunk)
        m = re.match(r"(.+?)\s+([0-9]+\.[0-9]+)$", part)
        if m:
            out[_norm(m.group(1))] = float(m.group(2))
    return out


def _safe_pct_value(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace("%", "").replace("+", "").replace("/100", "").strip())
    except Exception:
        return None


def _safe_rank_value(value: Any) -> Optional[int]:
    try:
        return int(str(value).replace("#", "").strip())
    except Exception:
        return None


def _extract_map_names_from_text(value: Any) -> List[str]:
    if not value:
        return []
    raw = str(value)
    hits: List[str] = []
    for map_name in MAP_NAMES:
        if map_name.lower() in raw.lower() and map_name not in hits:
            hits.append(map_name)
    return hits[:3]


def _series_stat_average(rows: List[Dict[str, Any]], field: str) -> Optional[float]:
    values = [float(row.get(field, 0) or 0) for row in rows if row.get(field) is not None]
    if not values:
        return None
    return round(mean(values), 2)

def _profile_bucket_role(buckets: Dict[str, str]) -> Tuple[str, str]:
    scores: Dict[str, float] = {}
    for key, value in buckets.items():
        m = re.search(r"(\d{1,3})/100", str(value))
        if m:
            scores[key] = float(m.group(1))

    if not scores:
        return "N/A", "Role could not be derived because HLTV profile buckets were unavailable."

    fire = scores.get("Firepower", 0.0)
    open_ = scores.get("Opening", 0.0)
    entry = scores.get("Entrying", 0.0)
    trade = scores.get("Trading", 0.0)
    clutch = scores.get("Clutching", 0.0)
    snipe = scores.get("Sniping", 0.0)
    util = scores.get("Utility", 0.0)

    if snipe >= 70:
        return "AWPer", f"Derived from HLTV buckets: Sniping {int(snipe)}/100 is the dominant skill."
    if entry >= 60 and open_ >= 55:
        return "Entry", f"Derived from HLTV buckets: Entrying {int(entry)}/100 and Opening {int(open_)}/100 profile as entry-heavy."
    if open_ >= 70:
        return "Opener", f"Derived from HLTV buckets: Opening {int(open_)}/100 is the clearest role signal."
    if fire >= 70:
        return "Star rifler", f"Derived from HLTV buckets: Firepower {int(fire)}/100 leads the profile."
    if util >= 60 and fire < 65:
        return "Support", f"Derived from HLTV buckets: Utility {int(util)}/100 is the strongest support signal."
    if clutch >= 60 and fire >= 50:
        return "Closer / rifler", f"Derived from HLTV buckets: Clutching {int(clutch)}/100 leads with enough Firepower ({int(fire)}/100)."
    if trade >= 55:
        return "Trader / lurker", f"Derived from HLTV buckets: Trading {int(trade)}/100 is the clearest role signal."

    best_key = max(scores.items(), key=lambda kv: kv[1])[0]
    mapped = {
        "Firepower": "Rifler",
        "Opening": "Opener",
        "Entrying": "Entry",
        "Trading": "Trader",
        "Clutching": "Closer",
        "Sniping": "AWPer",
        "Utility": "Support",
    }
    return mapped.get(best_key, "Rifler"), f"Derived from HLTV buckets: {best_key} is the strongest profile category."


def search_player(name: str) -> Optional[Tuple[str, str, str]]:
    key = _slugify(name)
    if key in STATIC_PLAYERS:
        pid, slug = STATIC_PLAYERS[key]
        return pid, slug, slug

    query = quote_plus(name.strip())
    soup, final_url, _ = _get_soup(f"{HLTV_BASE}/search?query={query}", render=True)

    if final_url and "/player/" in final_url:
        m = re.search(r"/player/(\d+)/([^/?#]+)", final_url)
        if m:
            return m.group(1), m.group(2), m.group(2)

    if soup:
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            m = re.search(r"/player/(\d+)/([^/?#]+)", href)
            if m:
                return m.group(1), m.group(2), m.group(2)

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
            "match_links": [],
        }

    lines = _lines_from_soup(soup)
    display_name = slug
    for line in lines:
        if line.startswith("# "):
            display_name = _norm(line.replace("# ", "", 1))
            break

    team_name = "N/A"
    team_id = None
    team_slug = None
    marker = soup.find(string=re.compile(r"Current team", re.I))
    if marker is not None:
        try:
            team_link = marker.parent.find_next("a", href=re.compile(r"/team/"))
        except Exception:
            team_link = None
        info = _extract_team_link(team_link)
        if info:
            team_name = info["name"]
            team_id = info["id"]
            team_slug = info["slug"]

    current_rank = _value_after(lines, "Current ranking", r"#?\d+", lookahead=4)
    rating_3 = (_value_after(lines, "Rating 3.0", r"\d+\.\d+", lookahead=4) or _value_near(lines, "Rating 3.0", r"(\d+\.\d+)", window=4, exact=True) or "N/A")
    buckets = _extract_bucket_scores(lines)

    match_links: List[Tuple[str, str]] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = _norm(a.get_text(" ", strip=True))
        if "/matches/" in href and text and "vs" in text.lower():
            full = _abs_url(href)
            if full not in seen:
                seen.add(full)
                match_links.append((text, full))
        if len(match_links) >= 20:
            break

    return {
        "display_name": display_name,
        "team_name": team_name,
        "team_id": team_id,
        "team_slug": team_slug,
        "team_ranking": _fmt_rank(int(current_rank.replace("#", ""))) if current_rank else "N/A",
        "rating_3": rating_3,
        "profile_buckets": buckets,
        "match_links": match_links,
    }

def _build_stats_url(pid: str, slug: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    url = f"{HLTV_BASE}/stats/players/{pid}/{slug}"
    params = []
    if start_date:
        params.append(f"startDate={start_date}")
    if end_date:
        params.append(f"endDate={end_date}")
    return url + ("?" + "&".join(params) if params else "")


def fetch_player_stats(pid: str, slug: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, str]:
    soup, _, _ = _get_soup(_build_stats_url(pid, slug, start_date, end_date), render=False)
    if not soup:
        soup, _, _ = _get_soup(_build_stats_url(pid, slug, start_date, end_date), render=True)
    if not soup:
        return {}

    lines = _lines_from_soup(soup)
    text = "\n".join(lines)
    stats: Dict[str, str] = {}
    stats["Rating 2.0"] = _value_before(lines, "Rating 2.0", r"\d+\.\d+", lookback=4) or _value_near(lines, "Rating 2.0", r"(\d+\.\d+)", window=4, exact=True) or "N/A"
    stats["Rating 3.0 recent"] = _value_before(lines, "Rating 3.0", r"\d+\.\d+", lookback=4) or _value_near(lines, "Rating 3.0", r"(\d+\.\d+)", window=4, exact=True) or "N/A"
    stats["Round swing"] = _value_near(lines, "Round swing", r"([+-]?\d+\.\d+%)", window=6, exact=True) or _extract_first_match(text, r"Round swing(?:.|\n){0,120}?([+-]?\d+\.\d+%)") or _extract_first_match(text, r"([+-]?\d+\.\d+%)\s+Round swing") or "N/A"
    stats["KAST"] = _value_near(lines, "KAST", r"(\d+\.\d+%)", window=6, exact=True) or _extract_first_match(text, r"KAST(?:.|\n){0,120}?(\d+\.\d+%)") or _extract_first_match(text, r"(\d+\.\d+%)\s+KAST") or "N/A"
    stats["ADR"] = _value_near(lines, "ADR", r"(\d+\.\d+)", window=5, exact=True) or _extract_first_match(text, r"ADR(?:.|\n){0,80}?(\d+\.\d+)") or "N/A"
    stats["KPR"] = _value_near(lines, "KPR", r"(\d+\.\d+)", window=5, exact=True) or _extract_first_match(text, r"KPR(?:.|\n){0,80}?(\d+\.\d+)") or "N/A"
    stats["DPR"] = _value_near(lines, "DPR", r"(\d+\.\d+)", window=5, exact=True) or _extract_first_match(text, r"DPR(?:.|\n){0,80}?(\d+\.\d+)") or "N/A"
    stats["HS %"] = _value_near(lines, "Headshot %", r"(\d+(?:\.\d+)?%)", window=4, exact=False) or _extract_first_match(text, r"Headshot %\s*([0-9]+(?:\.[0-9]+)?%)") or "N/A"
    stats["Impact"] = _value_near(lines, "Impact rating", r"(\d+\.\d+)", window=5, exact=False) or _extract_first_match(text, r"Impact rating\s*([0-9]+\.[0-9]+)") or "N/A"
    stats["Opening kills per round"] = _value_near(lines, "Opening kills per round", r"(\d+\.\d+)", window=5, exact=True) or _extract_first_match(text, r"Opening kills per round(?:.|\n){0,40}?([0-9]+\.[0-9]+)") or "N/A"
    stats["Trade kills per round"] = _value_near(lines, "Trade kills per round", r"(\d+\.\d+)", window=5, exact=True) or _extract_first_match(text, r"Trade kills per round(?:.|\n){0,40}?([0-9]+\.[0-9]+)") or "N/A"
    stats["Maps played"] = _value_near(lines, "Maps played", r"([\d,]+)", window=4, exact=False) or _extract_first_match(text, r"Maps played\s*([\d,]+)") or "N/A"
    stats["Rounds played"] = _value_near(lines, "Rounds played", r"([\d,]+)", window=4, exact=False) or _extract_first_match(text, r"Rounds played\s*([\d,]+)") or "N/A"
    for label, value in _extract_bucket_scores(lines).items():
        stats[label] = value
    for bucket in (5, 10, 20, 30, 50):
        label = f"vs top {bucket} opponents"
        stats[f"Vs Top {bucket} rating"] = _value_near(lines, label, r"(-|\d+\.\d+)", window=8, exact=False) or _extract_first_match(text, rf"vs top {bucket} opponents(?:.|\n){{0,80}}?(-|[0-9]+\.[0-9]+)") or "N/A"
    return stats

def extract_history_rows(pid: str, slug: str) -> List[Dict[str, Any]]:
    soup, _, _ = _get_soup(f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}", render=False)
    if not soup:
        soup, _, _ = _get_soup(f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}", render=True)
    if not soup:
        return []
    table = soup.find("table")
    if not table or not table.find("tbody"):
        return []
    rows: List[Dict[str, Any]] = []
    for tr in table.find("tbody").find_all("tr"):
        row_text = _norm(tr.get_text(" ", strip=True))
        if not row_text:
            continue
        date_match = re.search(r"(\d{2}/\d{2}/\d{2})", row_text)
        kd_match = re.search(r"\b(\d+)\s*-\s*(\d+)\b", row_text)
        map_match = re.search(r"\b(anc|anb|d2|inf|mrg|nuke|ovp|vrt|trn|cbl|cch|tcn|ssn)\b", row_text, flags=re.I)
        if not (date_match and kd_match and map_match):
            continue
        cells = [_norm(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        links = tr.find_all("a", href=True)
        team_links: List[Dict[str, str]] = []
        mapstats_url = ""
        match_url = ""
        for a in links:
            href = a.get("href", "")
            if "/stats/matches/mapstatsid/" in href and not mapstats_url:
                mapstats_url = _abs_url(href)
            elif "/matches/" in href and not match_url:
                match_url = _abs_url(href)
            info = _extract_team_link(a)
            if info and all(info.get("id") != existing.get("id") for existing in team_links):
                team_links.append(info)
        if len(team_links) >= 2:
            team_name = team_links[0]["name"]
            opponent_name = team_links[1]["name"]
            team_id = team_links[0]["id"]
            team_slug = team_links[0]["slug"]
            opponent_id = team_links[1]["id"]
            opponent_slug = team_links[1]["slug"]
        else:
            team_name = _strip_score_suffix(cells[1]) if len(cells) > 1 else "N/A"
            opponent_name = _strip_score_suffix(cells[2]) if len(cells) > 2 else "UNK"
            team_id = team_slug = opponent_id = opponent_slug = None
        score_bits = re.findall(r"\((\d+)\)", row_text)
        rounds_played = 24
        if len(score_bits) >= 2:
            try:
                rounds_played = int(score_bits[0]) + int(score_bits[1])
            except Exception:
                pass
        rating_match = re.findall(r"\b(\d+\.\d+)\b", row_text)
        rating = rating_match[-1] if rating_match else "N/A"
        rows.append({"date": date_match.group(1), "team": team_name or "N/A", "team_id": team_id, "team_slug": team_slug, "opponent": opponent_name or "UNK", "opponent_id": opponent_id, "opponent_slug": opponent_slug, "map_name": MAP_ALIASES.get(map_match.group(1).lower(), map_match.group(1).lower()), "kills": int(kd_match.group(1)), "deaths": int(kd_match.group(2)), "rating": rating, "rounds": rounds_played, "mapstats_url": mapstats_url, "match_url": match_url})
        if len(rows) >= MAX_RECENT_MAPS:
            break
    return rows

def parse_mapstats(url: str, player_candidates: List[str]) -> Tuple[Optional[int], Optional[int]]:
    if not url:
        return None, None
    soup, _, _ = _get_soup(url, render=False)
    if not soup:
        return None, None

    normalized_candidates = [c for c in {_slugify(x) for x in player_candidates if x}]
    for tr in soup.find_all("tr"):
        row_text = _norm(tr.get_text(" ", strip=True))
        key = _slugify(row_text)
        if not key:
            continue
        if not any(candidate and candidate in key for candidate in normalized_candidates):
            continue
        m = re.search(r"(\d+)\s*\((\d+)\)", row_text)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def hydrate_maps(rows: List[Dict[str, Any]], slug: str, display_name: str) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        exact_kills, exact_hs = parse_mapstats(row.get("mapstats_url", ""), [slug, display_name])
        copy_row = dict(row)
        if exact_kills is not None:
            copy_row["kills"] = exact_kills
        copy_row["headshots"] = exact_hs if exact_hs is not None else 0
        out.append(copy_row)
    return out


def pair_recent_series(rows: List[Dict[str, Any]], max_series: Optional[int] = MAX_RECENT_SERIES) -> List[Dict[str, Any]]:
    if not rows:
        return []
    grouped: List[Dict[str, Any]] = []
    for row in rows:
        key = (_slugify(row.get("date", "")), _slugify(row.get("opponent", "")), _slugify(row.get("team", "")))
        if grouped and grouped[-1]["key"] == key:
            grouped[-1]["maps"].append(row)
        else:
            grouped.append({"key": key, "maps": [row]})
    paired = []
    for grp in grouped:
        chrono_maps = list(reversed(grp["maps"]))
        if len(chrono_maps) < 2:
            continue
        first_two = chrono_maps[:2]
        paired.append({"date": first_two[0].get("date", "N/A"), "team": first_two[0].get("team", "N/A"), "team_id": first_two[0].get("team_id"), "team_slug": first_two[0].get("team_slug"), "opponent": first_two[0].get("opponent", "UNK"), "opponent_id": first_two[0].get("opponent_id"), "opponent_slug": first_two[0].get("opponent_slug"), "map1": first_two[0].get("map_name", "N/A"), "map2": first_two[1].get("map_name", "N/A"), "kills": int(first_two[0].get("kills", 0)) + int(first_two[1].get("kills", 0)), "deaths": int(first_two[0].get("deaths", 0)) + int(first_two[1].get("deaths", 0)), "headshots": int(first_two[0].get("headshots", 0)) + int(first_two[1].get("headshots", 0)), "rounds": int(first_two[0].get("rounds", 0)) + int(first_two[1].get("rounds", 0)), "rating_avg": round(mean([_safe_float(first_two[0].get("rating")) or 0.0, _safe_float(first_two[1].get("rating")) or 0.0]), 2), "maps_in_series": len(chrono_maps), "raw_maps": first_two})
        if max_series is not None and len(paired) >= max_series:
            break
    return paired

def build_per_map_averages(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(row.get("map_name", "Unknown"), []).append(row)

    final: Dict[str, Dict[str, Any]] = {}
    for map_name, items in buckets.items():
        total_rounds = sum(int(x.get("rounds", 0)) for x in items) or 1
        total_kills = sum(int(x.get("kills", 0)) for x in items)
        total_hs = sum(int(x.get("headshots", 0)) for x in items)
        final[map_name] = {
            "avg_kills": round(total_kills / len(items), 2),
            "avg_hs": round(total_hs / len(items), 2),
            "avg_kpr": round(total_kills / total_rounds, 3),
            "sample_size": len(items),
        }
    return final


def bootstrap_distribution(samples: List[int], iterations: int = 25000) -> List[float]:
    if not samples:
        return []
    if np is not None:
        rng = np.random.default_rng(42)
        arr = rng.choice(np.array(samples), size=iterations, replace=True)
        return arr.astype(float).tolist()

    out = []
    idx = 0
    for _ in range(iterations):
        out.append(float(samples[idx % len(samples)]))
        idx += 7
    return out


def _series_percentiles(samples: List[int]) -> Tuple[str, str]:
    if not samples:
        return "N/A", "N/A"
    if np is not None:
        q25, q75 = np.percentile(np.array(samples), [25, 75])
        return f"{round(float(q25), 1)}", f"{round(float(q75), 1)}"

    ordered = sorted(samples)
    q25_idx = max(0, int(0.25 * (len(ordered) - 1)))
    q75_idx = max(0, int(0.75 * (len(ordered) - 1)))
    return str(ordered[q25_idx]), str(ordered[q75_idx])


def _sample_stats(values: List[int], line: float) -> Dict[str, Any]:
    if not values:
        return {
            "avg": None,
            "median": None,
            "hit_rate": None,
            "q25": "N/A",
            "q75": "N/A",
            "bootstrap": [],
            "over_probability": None,
            "under_probability": None,
            "sim_mean": None,
            "sim_median": None,
            "std_dev": None,
        }

    avg_val = mean(values)
    median_val = median(values)
    hit_rate = (sum(1 for v in values if float(v) > line) / len(values)) * 100.0
    q25, q75 = _series_percentiles(values)
    boot = bootstrap_distribution(values)

    if boot:
        if np is not None:
            arr = np.array(boot, dtype=float)
            sim_mean = float(np.mean(arr))
            sim_median = float(np.median(arr))
            std_dev = float(np.std(arr))
            over_prob = float(np.mean(arr > line) * 100.0)
        else:
            sim_mean = mean(boot)
            sim_median = median(boot)
            mean_boot = sim_mean
            std_dev = (sum((x - mean_boot) ** 2 for x in boot) / len(boot)) ** 0.5
            over_prob = (sum(1 for x in boot if x > line) / len(boot)) * 100.0
        under_prob = 100.0 - over_prob
    else:
        sim_mean = sim_median = std_dev = over_prob = under_prob = None

    return {
        "avg": avg_val,
        "median": median_val,
        "hit_rate": hit_rate,
        "q25": q25,
        "q75": q75,
        "bootstrap": boot,
        "over_probability": over_prob,
        "under_probability": under_prob,
        "sim_mean": sim_mean,
        "sim_median": sim_median,
        "std_dev": std_dev,
    }


def _build_scenarios(series_rows: List[Dict[str, Any]], total_kills: int, total_rounds: int) -> Dict[str, Dict[str, str]]:
    if not series_rows or total_rounds <= 0:
        return {}

    rounds = [int(row.get("rounds", 0)) for row in series_rows if int(row.get("rounds", 0)) > 0]
    if not rounds:
        return {}

    if np is not None:
        short_rounds, norm_rounds, long_rounds = np.percentile(np.array(rounds), [25, 50, 75]).tolist()
    else:
        ordered = sorted(rounds)
        short_rounds = ordered[max(0, int(0.25 * (len(ordered) - 1)))]
        norm_rounds = ordered[len(ordered) // 2]
        long_rounds = ordered[max(0, int(0.75 * (len(ordered) - 1)))]

    kpr = total_kills / total_rounds
    return {
        "short": {"rounds": f"{round(short_rounds, 1)}", "expected_kills": f"{round(kpr * float(short_rounds), 1)}"},
        "normal": {"rounds": f"{round(norm_rounds, 1)}", "expected_kills": f"{round(kpr * float(norm_rounds), 1)}"},
        "long": {"rounds": f"{round(long_rounds, 1)}", "expected_kills": f"{round(kpr * float(long_rounds), 1)}"},
    }


def _recent_form_string(series_rows: List[Dict[str, Any]]) -> str:
    if not series_rows:
        return "N/A"
    last5 = series_rows[:5]
    last10 = series_rows[:10]
    avg5 = mean(int(x.get("kills", 0)) for x in last5)
    avg10 = mean(int(x.get("kills", 0)) for x in last10)
    hs5 = mean(int(x.get("headshots", 0)) for x in last5)
    return f"Last 5 series: {avg5:.1f} K / {hs5:.1f} HS • Last {len(last10)} series: {avg10:.1f} K"


def _h2h_payload(series_rows: List[Dict[str, Any]], opponent: str, max_age_days: int = H2H_WINDOW_DAYS) -> Dict[str, Any]:
    opp_key = _slugify(opponent)
    if not opp_key:
        return {}
    relevant = [row for row in series_rows if _team_name_matches(str(row.get("opponent", "")), opponent) and _within_days(row.get("date"), max_age_days)]
    if not relevant:
        return {"h2h_sample_size": 0, "h2h_avg_kills": "N/A", "h2h_avg_headshots": "N/A", "h2h_rows": [], "h2h_summary": f"No HLTV H2H sample in the last {max_age_days} days."}
    avg_k = _series_stat_average(relevant, "kills")
    avg_hs = _series_stat_average(relevant, "headshots")
    return {"h2h_sample_size": len(relevant), "h2h_avg_kills": avg_k if avg_k is not None else "N/A", "h2h_avg_headshots": avg_hs if avg_hs is not None else "N/A", "h2h_last_meeting": relevant[0].get("date", "N/A"), "h2h_rows": relevant[:5], "h2h_summary": f"{len(relevant)} HLTV series in last {max_age_days}d • {avg_k if avg_k is not None else 'N/A'} kills • {avg_hs if avg_hs is not None else 'N/A'} HS"}

def _find_profile_match_url(match_links: List[Tuple[str, str]], opponent: str) -> Optional[str]:
    for text, url in match_links:
        if _team_name_matches(text, opponent):
            return url
    return None

def _team_names_from_match_soup(soup: BeautifulSoup) -> List[str]:
    teams: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        txt = _norm(a.get_text(" ", strip=True))
        if "/team/" in href and txt and txt not in teams:
            teams.append(txt)
        if len(teams) >= 2:
            break
    return teams


def _extract_team_rank_from_lines(lines: List[str], team_name: str) -> Optional[int]:
    if not team_name:
        return None
    indices = [idx for idx, line in enumerate(lines) if _slugify(line) == _slugify(team_name)]
    for idx in indices:
        for j in range(idx + 1, min(len(lines), idx + 8)):
            m = re.search(r"World rank:\s*#(\d+)", lines[j], flags=re.I)
            if m:
                return int(m.group(1))
    return None


def _extract_pick_percentages(lines: List[str], teams: List[str]) -> Optional[str]:
    hits = _find_line_indices(lines, "Pick a winner", exact=True)
    if not hits:
        return None
    idx = hits[0]
    percentages = []
    for j in range(idx + 1, min(len(lines), idx + 15)):
        if re.fullmatch(r"\d+(?:\.\d+)?%", lines[j]):
            percentages.append(lines[j])
    if len(percentages) >= 2 and len(teams) >= 2:
        return f"{teams[0]} {percentages[0]} | {teams[1]} {percentages[1]}"
    return None


def _extract_veto_and_maps(lines: List[str]) -> Tuple[List[str], Dict[str, str]]:
    veto = [line for line in lines if re.search(r"(picked|removed|was left over)", line, flags=re.I) and (re.match(r"\d+\.\s*", line) or " picked " in line.lower() or " removed " in line.lower() or " was left over" in line.lower())]
    likely: Dict[str, str] = {}
    picks = []
    decider = None
    for line in veto:
        pm = re.search(r"(.+?)\s+picked\s+(.+)", line, flags=re.I)
        if pm:
            picks.append((_norm(pm.group(1)), _norm(pm.group(2))))
        dm = re.search(r"(.+?)\s+was left over", line, flags=re.I)
        if dm:
            decider = _norm(dm.group(1))
    if picks:
        for team_name, map_name in picks[:2]:
            likely[f"{team_name} pick"] = map_name
    if decider:
        likely["Decider"] = decider
    return veto, likely

def _extract_decimal_odds_from_html(html: str, teams: List[str]) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    if not html:
        return None, None, None
    thunder_patterns = [r'Thunderpick.{0,240}?"team1Odds"\s*:\s*"?([0-9]+\.[0-9]+)"?.{0,180}?"team2Odds"\s*:\s*"?([0-9]+\.[0-9]+)"?', r'"bookie"\s*:\s*"Thunderpick".{0,240}?"homeOdds"\s*:\s*"?([0-9]+\.[0-9]+)"?.{0,180}?"awayOdds"\s*:\s*"?([0-9]+\.[0-9]+)"?', r'"name"\s*:\s*"Thunderpick".{0,240}?"odds1"\s*:\s*"?([0-9]+\.[0-9]+)"?.{0,180}?"odds2"\s*:\s*"?([0-9]+\.[0-9]+)"?']
    for pat in thunder_patterns:
        m = re.search(pat, html, flags=re.I | re.S)
        if m:
            return float(m.group(1)), float(m.group(2)), "Thunderpick"
    patterns = [r'"team1Odds"\s*:\s*"?([0-9]+\.[0-9]+)"?.{0,200}?"team2Odds"\s*:\s*"?([0-9]+\.[0-9]+)"?', r'"homeOdds"\s*:\s*"?([0-9]+\.[0-9]+)"?.{0,200}?"awayOdds"\s*:\s*"?([0-9]+\.[0-9]+)"?', r'data-team1-odds="([0-9]+\.[0-9]+)".{0,200}?data-team2-odds="([0-9]+\.[0-9]+)"', r'data-odds1="([0-9]+\.[0-9]+)".{0,200}?data-odds2="([0-9]+\.[0-9]+)"']
    for pat in patterns:
        m = re.search(pat, html, flags=re.I | re.S)
        if m:
            return float(m.group(1)), float(m.group(2)), "html"
    if len(teams) >= 2:
        m = re.search(rf"{re.escape(teams[0])}.{{0,120}}?([0-9]+\.[0-9]+).{{0,120}}?{re.escape(teams[1])}.{{0,120}}?([0-9]+\.[0-9]+)", html, flags=re.I | re.S)
        if m:
            return float(m.group(1)), float(m.group(2)), "team-nearby"
    return None, None, None

def _analytics_url_from_match(match_url: str) -> Optional[str]:
    m = re.search(r"/matches/(\d+)/(.*)$", match_url)
    if not m:
        return None
    return f"{HLTV_BASE}/betting/analytics/{m.group(1)}/{m.group(2)}"


def fetch_match_context(match_url: Optional[str], player_team: str, opponent: str) -> Dict[str, Any]:
    if not match_url:
        return {}
    soup, _, html = _get_soup(match_url, render=True)
    if not soup:
        soup, _, html = _get_soup(match_url, render=False)
    if not soup:
        return {}
    lines = _lines_from_soup(soup)
    team_links = _extract_team_links_from_soup(soup, limit=12)
    player_entry, opponent_entry = _resolve_match_teams(team_links, player_team, opponent)
    resolved_player_team = player_entry.get("name") if player_entry else player_team
    resolved_opponent = opponent_entry.get("name") if opponent_entry else opponent
    veto, official_likely_maps = _extract_veto_and_maps(lines)
    player_rank = _extract_team_rank_from_lines(lines, resolved_player_team)
    opponent_rank = _extract_team_rank_from_lines(lines, resolved_opponent)
    if not player_rank and player_entry:
        player_rank = _safe_rank_value(fetch_team_rank(player_entry.get("id"), player_entry.get("slug")))
    if not opponent_rank and opponent_entry:
        opponent_rank = _safe_rank_value(fetch_team_rank(opponent_entry.get("id"), opponent_entry.get("slug")))
    teams_for_display = [x for x in [resolved_player_team, resolved_opponent] if x]
    if len(teams_for_display) < 2:
        teams_for_display = [x.get("name", "") for x in team_links[:2] if x.get("name")]
    public_pick = _extract_pick_percentages(lines, teams_for_display)
    odds_a, odds_b, odds_source = _extract_decimal_odds_from_html(html or "", teams_for_display)
    analytics_url = _analytics_url_from_match(match_url)
    if analytics_url:
        analytics_soup, _, analytics_html = _get_soup(analytics_url, render=True)
        if not analytics_soup:
            analytics_soup, _, analytics_html = _get_soup(analytics_url, render=False)
        analytics_lines = _lines_from_soup(analytics_soup) if analytics_soup else []
        if analytics_lines:
            analytics_team_links = _extract_team_links_from_soup(analytics_soup, limit=12) if analytics_soup else []
            if analytics_team_links:
                team_links = analytics_team_links + [x for x in team_links if x.get("id") not in {y.get("id") for y in analytics_team_links}]
                player_entry, opponent_entry = _resolve_match_teams(team_links, resolved_player_team, resolved_opponent)
                resolved_player_team = player_entry.get("name") if player_entry else resolved_player_team
                resolved_opponent = opponent_entry.get("name") if opponent_entry else resolved_opponent
                teams_for_display = [x for x in [resolved_player_team, resolved_opponent] if x]
            player_rank = player_rank or _extract_team_rank_from_lines(analytics_lines, resolved_player_team)
            opponent_rank = opponent_rank or _extract_team_rank_from_lines(analytics_lines, resolved_opponent)
            if not player_rank and player_entry:
                player_rank = _safe_rank_value(fetch_team_rank(player_entry.get("id"), player_entry.get("slug")))
            if not opponent_rank and opponent_entry:
                opponent_rank = _safe_rank_value(fetch_team_rank(opponent_entry.get("id"), opponent_entry.get("slug")))
            public_pick = public_pick or _extract_pick_percentages(analytics_lines, teams_for_display)
            if not veto:
                analytics_veto, analytics_likely = _extract_veto_and_maps(analytics_lines)
                if analytics_veto:
                    veto = analytics_veto; official_likely_maps = analytics_likely
        if (odds_a is None or odds_b is None) and analytics_html:
            odds_a, odds_b, odds_source = _extract_decimal_odds_from_html(analytics_html, teams_for_display)
    odds_display = "N/A"
    if odds_a and odds_b and len(teams_for_display) >= 2:
        odds_display = f"{teams_for_display[0]} {odds_a:.2f} | {teams_for_display[1]} {odds_b:.2f}"
    thunderpick_display = odds_display if odds_source in ("Thunderpick", "html", "team-nearby") else "N/A"
    start_maps, end_maps = _today_range(TEAM_MAP_WINDOW_DAYS)
    player_pool = fetch_team_map_stats(player_entry.get("id") if player_entry else None, player_entry.get("slug") if player_entry else None, start_date=start_maps, end_date=end_maps)
    opponent_pool = fetch_team_map_stats(opponent_entry.get("id") if opponent_entry else None, opponent_entry.get("slug") if opponent_entry else None, start_date=start_maps, end_date=end_maps)
    derived_likely_maps, veto_notes = build_likely_maps_from_pools(resolved_player_team, resolved_opponent, player_pool, opponent_pool, official_veto=veto)
    likely_maps = dict(official_likely_maps or {})
    for key, value in derived_likely_maps.items(): likely_maps.setdefault(key, value)
    return {"Match URL": match_url, "Resolved team": resolved_player_team or player_team, "Resolved opponent": resolved_opponent or opponent, "Veto": veto if veto else veto_notes, "Likely maps": likely_maps, "Likely maps source": "Official HLTV veto" if official_likely_maps else f"Derived from last {TEAM_MAP_WINDOW_DAYS} days of HLTV team map data", "Team ranking": _fmt_rank(player_rank), "Opponent ranking": _fmt_rank(opponent_rank), "Match odds": odds_display, "Thunderpick odds": thunderpick_display, "Public pick": public_pick or "N/A", "Odds source": odds_source or "N/A", "Team map pool": player_pool, "Opponent map pool": opponent_pool, "Veto notes": veto_notes}

def _build_team_maps_url(team_id: str, team_slug: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    url = f"{HLTV_BASE}/stats/teams/maps/{team_id}/{team_slug}"
    params = []
    if start_date:
        params.append(f"startDate={start_date}")
    if end_date:
        params.append(f"endDate={end_date}")
    return url + ("?" + "&".join(params) if params else "")


def fetch_team_map_stats(team_id: Optional[str], team_slug: Optional[str], start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    if not team_id or not team_slug:
        return {}
    soup, _, _ = _get_soup(_build_team_maps_url(team_id, team_slug, start_date, end_date), render=False)
    if not soup:
        soup, _, _ = _get_soup(_build_team_maps_url(team_id, team_slug, start_date, end_date), render=True)
    if not soup:
        return {}
    lines = _lines_from_soup(soup)
    data: Dict[str, Dict[str, Any]] = {}
    for idx, line in enumerate(lines):
        if line not in MAP_NAMES:
            continue
        block = lines[idx:idx + 18]
        win_rate = pick_pct = ban_pct = None
        for j, cur in enumerate(block):
            if "Win rate" in cur:
                win_rate = _extract_first_match(cur, r"Win rate\s*([0-9]+(?:\.[0-9]+)?%)") or (block[j + 1] if j + 1 < len(block) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%", block[j + 1]) else None)
            if "Pick %" in cur:
                pick_pct = _extract_first_match(cur, r"Pick %\s*([0-9]+(?:\.[0-9]+)?%)") or (block[j + 1] if j + 1 < len(block) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%", block[j + 1]) else None)
            if "Ban %" in cur:
                ban_pct = _extract_first_match(cur, r"Ban %\s*([0-9]+(?:\.[0-9]+)?%)") or (block[j + 1] if j + 1 < len(block) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%", block[j + 1]) else None)
        if win_rate or pick_pct or ban_pct:
            data[line] = {"win_rate": win_rate or "N/A", "pick_pct": pick_pct or "N/A", "ban_pct": ban_pct or "N/A"}
    return data


def _best_map_by(pool: Dict[str, Dict[str, Any]], key: str, reverse: bool = True, exclude: Optional[List[str]] = None) -> Optional[Tuple[str, Dict[str, Any]]]:
    exclude_keys = {_slugify(x) for x in (exclude or [])}
    candidates = []
    for map_name, vals in pool.items():
        if _slugify(map_name) in exclude_keys:
            continue
        score = _safe_pct_value(vals.get(key))
        if score is not None:
            candidates.append((score, map_name, vals))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=reverse)
    return candidates[0][1], candidates[0][2]


def _best_shared_map(team_pool: Dict[str, Dict[str, Any]], opp_pool: Dict[str, Dict[str, Any]], exclude: Optional[List[str]] = None) -> Optional[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    exclude_keys = {_slugify(x) for x in (exclude or [])}
    best = None
    best_score = None
    for map_name, team_vals in team_pool.items():
        if _slugify(map_name) in exclude_keys or map_name not in opp_pool:
            continue
        opp_vals = opp_pool[map_name]
        team_pick = _safe_pct_value(team_vals.get("pick_pct")) or 0.0
        opp_pick = _safe_pct_value(opp_vals.get("pick_pct")) or 0.0
        team_ban = _safe_pct_value(team_vals.get("ban_pct")) or 100.0
        opp_ban = _safe_pct_value(opp_vals.get("ban_pct")) or 100.0
        score = min(team_pick, opp_pick) + (200.0 - team_ban - opp_ban)
        if best_score is None or score > best_score:
            best_score = score
            best = (map_name, team_vals, opp_vals)
    return best


def build_likely_maps_from_pools(player_team_name: str, opponent_name: str, player_pool: Dict[str, Dict[str, Any]], opponent_pool: Dict[str, Dict[str, Any]], official_veto: Optional[List[str]] = None) -> Tuple[Dict[str, str], List[str]]:
    likely: Dict[str, str] = {}
    notes: List[str] = []
    if official_veto:
        notes.append("Official HLTV veto found for this match.")
    if not player_pool or not opponent_pool:
        if not notes:
            notes.append("No official veto on HLTV and team map-pool data could not be resolved.")
        return likely, notes
    excluded: List[str] = []
    team_ban = _best_map_by(player_pool, "ban_pct")
    opp_ban = _best_map_by(opponent_pool, "ban_pct")
    if team_ban:
        excluded.append(team_ban[0]); notes.append(f"{player_team_name} permaban lean: {team_ban[0]} (ban {team_ban[1].get('ban_pct', 'N/A')}).")
    if opp_ban:
        excluded.append(opp_ban[0]); notes.append(f"{opponent_name} permaban lean: {opp_ban[0]} (ban {opp_ban[1].get('ban_pct', 'N/A')}).")
    team_pick = _best_map_by(player_pool, "pick_pct", exclude=excluded)
    if team_pick and team_pick[0] in opponent_pool:
        o = opponent_pool[team_pick[0]]
        likely[f"{player_team_name} likely pick"] = f"{team_pick[0]} (pick {team_pick[1].get('pick_pct', 'N/A')}, WR {team_pick[1].get('win_rate', 'N/A')} vs {opponent_name} WR {o.get('win_rate', 'N/A')})"
        excluded.append(team_pick[0])
    opp_pick = _best_map_by(opponent_pool, "pick_pct", exclude=excluded)
    if opp_pick and opp_pick[0] in player_pool:
        t = player_pool[opp_pick[0]]
        likely[f"{opponent_name} likely pick"] = f"{opp_pick[0]} (pick {opp_pick[1].get('pick_pct', 'N/A')}, WR {opp_pick[1].get('win_rate', 'N/A')} vs {player_team_name} WR {t.get('win_rate', 'N/A')})"
        excluded.append(opp_pick[0])
    decider = _best_shared_map(player_pool, opponent_pool, exclude=excluded)
    if decider:
        likely["Likely decider"] = f"{decider[0]} ({player_team_name} pick {decider[1].get('pick_pct', 'N/A')} / {opponent_name} pick {decider[2].get('pick_pct', 'N/A')})"
    notes.append(f"Likely maps are derived from last {TEAM_MAP_WINDOW_DAYS} days of HLTV team map pick/ban and win-rate splits when official veto is unavailable.")
    return likely, notes


def _likely_map_combo_note(per_map: Dict[str, Dict[str, Any]], likely_maps: Dict[str, str], headshots: bool = False) -> Optional[str]:
    if not per_map or not likely_maps:
        return None
    extracted: List[str] = []
    for value in likely_maps.values():
        for map_name in _extract_map_names_from_text(value):
            if map_name not in extracted:
                extracted.append(map_name)
    if len(extracted) < 2:
        return None
    total = 0.0; details = []
    for map_name in extracted[:2]:
        vals = per_map.get(map_name)
        if not vals:
            return None
        cur = vals.get("avg_hs") if headshots else vals.get("avg_kills")
        try:
            cur_float = float(cur)
        except Exception:
            return None
        total += cur_float
        details.append(f"{map_name} {cur_float:.1f}{'HS' if headshots else 'K'}")
    return f"Likely two-map sample from exact HLTV map history: {', '.join(details)} -> {total:.1f} {'HS' if headshots else 'kills'}."

def fetch_team_rank(team_id: Optional[str], team_slug: Optional[str]) -> str:
    """Fetch HLTV team page rank as a fallback when match page rank is missing."""
    if not team_id or not team_slug:
        return "N/A"
    soup, _, _ = _get_soup(f"{HLTV_BASE}/team/{team_id}/{team_slug}", render=True)
    if not soup:
        soup, _, _ = _get_soup(f"{HLTV_BASE}/team/{team_id}/{team_slug}", render=False)
    if not soup:
        return "N/A"
    lines = _lines_from_soup(soup)
    text = "\n".join(lines)
    for pat in (
        r"World ranking\s*#\s*(\d+)",
        r"World rank\s*#\s*(\d+)",
        r"Current rank\s*#\s*(\d+)",
        r"#\s*(\d+)\s*World ranking",
    ):
        hit = _extract_first_match(text, pat)
        if hit:
            try:
                return _fmt_rank(int(hit))
            except Exception:
                pass
    for idx, line in enumerate(lines):
        if "ranking" in line.lower() or "world" in line.lower():
            block = " ".join(lines[max(0, idx - 3):idx + 6])
            m = re.search(r"#\s*(\d+)", block)
            if m:
                return _fmt_rank(int(m.group(1)))
    return "N/A"


def _series_maps(row: Dict[str, Any]) -> List[str]:
    out = []
    for key in ("map1", "map2"):
        val = _norm(row.get(key))
        if val and val != "N/A":
            out.append(val)
    if not out and isinstance(row.get("raw_maps"), list):
        for rm in row.get("raw_maps", [])[:2]:
            val = _norm(rm.get("map_name"))
            if val:
                out.append(val)
    return out


def _map_weighted_projection(
    rows: List[Dict[str, Any]],
    likely_maps: Dict[str, str],
    per_map: Dict[str, Dict[str, Any]],
    fallback_projection: Optional[float],
    headshots: bool = False,
) -> Dict[str, Any]:
    extracted: List[str] = []
    for value in (likely_maps or {}).values():
        for map_name in _extract_map_names_from_text(value):
            if map_name not in extracted:
                extracted.append(map_name)
    details = []
    total = 0.0
    used = 0
    for map_name in extracted[:2]:
        vals = per_map.get(map_name, {})
        key = "avg_hs" if headshots else "avg_kills"
        cur = _safe_float(vals.get(key))
        sample = vals.get("sample_size", vals.get("maps", "N/A"))
        if cur is None:
            continue
        details.append(f"{map_name}: {cur:.1f} {'HS' if headshots else 'K'} over {sample} map sample")
        total += cur
        used += 1
    if used >= 2:
        return {
            "Map weighted projection": round(total, 1),
            "Map weighted KPR": _map_weighted_kpr_from_names(extracted[:2], per_map),
            "Map weighting note": " | ".join(details),
            "True map weighting": "ON: likely HLTV map pool matched player exact map history",
        }
    return {
        "Map weighted projection": fallback_projection if fallback_projection is not None else "N/A",
        "Map weighted KPR": "N/A",
        "Map weighting note": "No two-map likely-map match found in player exact map history; using recent M1-M2 projection.",
        "True map weighting": "LIMITED: official veto / map pool unavailable or thin sample",
    }


def _map_weighted_kpr_from_names(map_names: List[str], per_map: Dict[str, Dict[str, Any]]) -> str:
    vals = []
    weights = []
    for map_name in map_names:
        row = per_map.get(map_name, {})
        kpr = _safe_float(row.get("avg_kpr"))
        sample = _safe_float(row.get("sample_size", row.get("maps", 1))) or 1.0
        if kpr is not None:
            vals.append(kpr * sample)
            weights.append(sample)
    if vals and sum(weights) > 0:
        return f"{sum(vals)/sum(weights):.3f}"
    return "N/A"


def _pace_model(rows: List[Dict[str, Any]], line: float, projection: Optional[float]) -> Dict[str, Any]:
    rounds = [int(r.get("rounds", 0) or 0) for r in rows if int(r.get("rounds", 0) or 0) > 0]
    kills = [int(r.get("kills", 0) or 0) for r in rows if int(r.get("rounds", 0) or 0) > 0]
    if not rounds:
        return {
            "Pace model": "N/A",
            "Map pace": "N/A",
            "Blowout risk": "N/A",
            "Overtime probability": "N/A",
            "Pace adjusted projection": projection if projection is not None else "N/A",
        }
    avg_rounds = mean(rounds)
    med_rounds = median(rounds)
    short_rate = sum(1 for r in rounds if r <= 38) / len(rounds) * 100.0
    ot_rate = sum(1 for r in rounds if r >= 49) / len(rounds) * 100.0
    blowout_rate = sum(1 for r in rounds if r <= 34) / len(rounds) * 100.0
    total_rounds = sum(rounds)
    kpr = (sum(kills) / total_rounds) if total_rounds else None
    adjusted = round(kpr * med_rounds, 1) if kpr is not None else projection
    pace_label = "Fast/short" if med_rounds < 40 else "Normal" if med_rounds <= 46 else "Long/OT-prone"
    return {
        "Pace model": f"{pace_label}: median {med_rounds:.1f} rounds, average {avg_rounds:.1f} rounds",
        "Map pace": f"Short-map rate {short_rate:.1f}% | normal center {med_rounds:.1f} rounds",
        "Blowout risk": f"{blowout_rate:.1f}% of recent M1-M2 samples finished at 34 rounds or fewer",
        "Overtime probability": f"{ot_rate:.1f}% of recent M1-M2 samples reached 49+ rounds",
        "Pace adjusted projection": adjusted if adjusted is not None else "N/A",
    }


def _multi_kill_pressure(rows: List[Dict[str, Any]], line: float) -> Dict[str, Any]:
    if not rows:
        return {
            "Multi-kill pressure": "N/A",
            "2K/3K frequency": "N/A",
            "Clutch conversion": "N/A",
            "Eco farming": "N/A",
            "Anti-eco padding": "N/A",
        }
    kill_samples = [int(r.get("kills", 0) or 0) for r in rows]
    round_samples = [int(r.get("rounds", 0) or 0) for r in rows]
    if not kill_samples:
        return {"Multi-kill pressure": "N/A", "2K/3K frequency": "N/A", "Clutch conversion": "N/A", "Eco farming": "N/A", "Anti-eco padding": "N/A"}
    avg_kills = mean(kill_samples)
    ceiling = max(kill_samples)
    high_spike_rate = sum(1 for k in kill_samples if k >= line + 3) / len(kill_samples) * 100.0
    two_k_proxy = sum(max(0, k - (r * 0.58)) for k, r in zip(kill_samples, round_samples or [40]*len(kill_samples)))
    two_k_freq = min(100.0, max(0.0, (two_k_proxy / max(1, sum(round_samples) / 2.0)) * 100.0)) if round_samples else 0.0
    pressure = "HIGH" if high_spike_rate >= 35 or ceiling >= line + 8 else "MEDIUM" if high_spike_rate >= 20 or ceiling >= line + 4 else "LOW"
    clutch_note = "Use HLTV Clutching bucket when available; fallback is spike stability from exact M1-M2 samples."
    eco_note = "Potential padding risk checked through blowout/short-map rate; exact eco kills are only used if HLTV exposes them on parsed pages."
    anti_eco = "Downgrade unders when spike rate is high; downgrade overs when blowout risk is high and KPR is not elite."
    return {
        "Multi-kill pressure": f"{pressure}: ceiling {ceiling}, avg {avg_kills:.1f}, spike rate {high_spike_rate:.1f}% above line+3",
        "2K/3K frequency": f"Proxy {two_k_freq:.1f}% from excess kills over normal KPR pace",
        "Clutch conversion": clutch_note,
        "Eco farming": eco_note,
        "Anti-eco padding": anti_eco,
    }


def _opponent_strength_model(payload: Dict[str, Any]) -> Dict[str, Any]:
    team_rank = _safe_rank_value(payload.get("Team ranking"))
    opp_rank = _safe_rank_value(payload.get("Opponent ranking"))
    sim_rating = _safe_float(payload.get("Similar teams rating"))
    if opp_rank is None:
        strength = "N/A"
        note = "Opponent rank unavailable from current HLTV scrape."
    elif opp_rank <= 10:
        strength = "Elite"
        note = f"Opponent is ranked #{opp_rank}; similar-team bucket should carry extra weight."
    elif opp_rank <= 30:
        strength = "Strong"
        note = f"Opponent is ranked #{opp_rank}; normal top-tier resistance expected."
    elif opp_rank <= 50:
        strength = "Mid"
        note = f"Opponent is ranked #{opp_rank}; moderate resistance expected."
    else:
        strength = "Lower"
        note = f"Opponent is ranked #{opp_rank}; softer team-strength profile."
    if team_rank and opp_rank:
        gap = opp_rank - team_rank
        note += f" Rank gap: team #{team_rank} vs opponent #{opp_rank} ({gap:+d})."
    if sim_rating is not None:
        note += f" Player rating in selected similar bucket: {sim_rating:.2f}."
    return {"Opponent strength": strength, "Opponent strength note": note}


def build_payload_analytics(payload: Dict[str, Any], line: float, kill_mode: bool = True) -> Dict[str, Any]:
    team_name = str(payload.get("Team", "N/A")); opponent_name = str(payload.get("Opponent", "N/A"))
    team_rank = _safe_rank_value(payload.get("Team ranking")); opponent_rank = _safe_rank_value(payload.get("Opponent ranking"))
    public_pick = _parse_pick_line(str(payload.get("Public pick", "N/A")))
    odds = _parse_odds_line(str(payload.get("Thunderpick odds", payload.get("Match odds", "N/A"))))
    h2h = payload.get("H2H Data", {}) or {}; likely_maps = payload.get("Likely maps", {}) or {}; per_map = payload.get("Per-map averages", {}) or {}
    projection = _safe_float(payload.get("Projected kills" if kill_mode else "Projected headshots")); recent_avg = _safe_float(payload.get("Recent average"))
    rating = _safe_float(payload.get("Rating 3.0")); kpr = _safe_float(payload.get("KPR")); dpr = _safe_float(payload.get("DPR")); adr = _safe_float(payload.get("ADR")); kast = _safe_pct_value(payload.get("KAST")); impact = _safe_float(payload.get("Impact"))
    firepower = _safe_pct_value(str(payload.get("Firepower", "")).split("/")[0]) if "/" in str(payload.get("Firepower", "")) else None
    opening = _safe_pct_value(str(payload.get("Opening", "")).split("/")[0]) if "/" in str(payload.get("Opening", "")) else None
    entrying = _safe_pct_value(str(payload.get("Entrying", "")).split("/")[0]) if "/" in str(payload.get("Entrying", "")) else None
    trading = _safe_pct_value(str(payload.get("Trading", "")).split("/")[0]) if "/" in str(payload.get("Trading", "")) else None
    similar_rating = _safe_float(payload.get("Similar teams rating")); over_prob = _safe_pct_value(payload.get("Over probability")); under_prob = _safe_pct_value(payload.get("Under probability")); hit_rate = _safe_pct_value(payload.get("Hit rate"))
    h2h_avg = _safe_float(h2h.get("h2h_avg_kills" if kill_mode else "h2h_avg_headshots")); h2h_sample = int(h2h.get("h2h_sample_size", 0) or 0)
    map_combo_note = _likely_map_combo_note(per_map, likely_maps, headshots=not kill_mode)
    recommendation = str(payload.get("Bet recommendation", "NO BET"))
    if recommendation == "NO BET" and projection is not None:
        recommendation = "OVER lean" if projection > line else "UNDER lean"
    player_pros: List[str] = []; player_cons: List[str] = []; team_pros: List[str] = []; team_cons: List[str] = []; opponent_pros: List[str] = []; opponent_cons: List[str] = []
    if projection is not None:
        edge = projection - line; (player_pros if edge >= 1 else player_cons).append(f"Projection {projection:.1f} is {abs(edge):.1f} {'above' if edge >= 0 else 'below'} the line.")
    if recent_avg is not None:
        diff = recent_avg - line
        if diff >= 1: player_pros.append(f"Recent exact two-map average is {recent_avg:.1f}.")
        elif diff <= -1: player_cons.append(f"Recent exact two-map average is only {recent_avg:.1f}.")
    for val, high, low, label in [(rating,1.1,1.0,"Rating 3.0"),(kpr,.75,.65,"KPR"),(adr,80,70,"ADR"),(kast,72,68,"KAST"),(impact,1.1,1.0,"Impact rating")]:
        if val is None: continue
        txt = f"{label} is {val:.1f}{'%' if label=='KAST' else ''}." if label in ('ADR','KAST') else f"{label} is {val:.2f}."
        (player_pros if val >= high else player_cons if val < low else player_pros).append(txt)
    if dpr is not None: (player_cons if dpr >= .72 else player_pros).append(f"DPR is {dpr:.2f}.")
    for val,label,cut in [(firepower,"Firepower",70),(opening,"Opening",65),(entrying,"Entrying",60),(trading,"Trading",60)]:
        if val is not None and val >= cut: player_pros.append(f"{label} bucket is {int(val)}/100.")
    if similar_rating is not None: (player_pros if similar_rating >= 1.05 else player_cons if similar_rating < 1.0 else player_pros).append(f"Similar-team rating is {similar_rating:.2f}.")
    if h2h_sample > 0 and h2h_avg is not None: (player_pros if h2h_avg > line else player_cons).append(f"H2H sample is {h2h_sample} series with {h2h_avg:.1f} average.")
    if map_combo_note: (player_pros if projection is not None and projection >= line else player_cons).append(map_combo_note)
    if team_rank is not None and opponent_rank is not None:
        if team_rank < opponent_rank: team_pros.append(f"Better rank edge: #{team_rank} vs #{opponent_rank}."); opponent_cons.append(f"Rank disadvantage: #{opponent_rank} vs #{team_rank}.")
        elif team_rank > opponent_rank: team_cons.append(f"Rank disadvantage: #{team_rank} vs #{opponent_rank}."); opponent_pros.append(f"Better rank edge: #{opponent_rank} vs #{team_rank}.")
    for name,pct in public_pick.items():
        if _team_name_matches(name, team_name): (team_pros if pct >= 55 else team_cons if pct <= 45 else team_pros).append(f"Public pick is {pct:.1f}% on {team_name}.")
        elif _team_name_matches(name, opponent_name): (opponent_pros if pct >= 55 else opponent_cons if pct <= 45 else opponent_pros).append(f"Public pick is {pct:.1f}% on {opponent_name}.")
    for name, odd in odds.items():
        if _team_name_matches(name, team_name): (team_pros if odd <= 1.70 else team_cons if odd >= 2.20 else team_pros).append(f"Thunderpick price: {team_name} {odd:.2f}.")
        elif _team_name_matches(name, opponent_name): (opponent_pros if odd <= 1.70 else opponent_cons if odd >= 2.20 else opponent_pros).append(f"Thunderpick price: {opponent_name} {odd:.2f}.")
    if not team_pros: team_pros.append("No clean extra team edge from available HLTV sample.")
    if not team_cons: team_cons.append("No major team-level red flag in available HLTV sample.")
    if not opponent_pros: opponent_pros.append("No major opponent-level edge beyond default matchup context.")
    if not opponent_cons: opponent_cons.append("No obvious opponent weakness beyond available HLTV data.")
    if not player_pros: player_pros.append("No standout player edge beyond raw projection.")
    if not player_cons: player_cons.append("No major player-specific red flag beyond normal variance.")
    side_prob = over_prob if "OVER" in recommendation.upper() else under_prob
    report = [f"Final grade {payload.get('Final grade','N/A')} with a {recommendation} angle."]
    if projection is not None: report.append(f"Projection is {projection:.1f} against a {line:.1f} line.")
    if hit_rate is not None: report.append(f"Exact two-map hit rate is {hit_rate:.1f}%.")
    if side_prob is not None: report.append(f"Model side probability is {side_prob:.1f}%.")
    if h2h_sample > 0: report.append(str(h2h.get("h2h_summary", "")) + ".")
    if map_combo_note: report.append(map_combo_note)
    return {"Team pros": team_pros[:4], "Team cons": team_cons[:4], "Opponent pros": opponent_pros[:4], "Opponent cons": opponent_cons[:4], "Player pros": player_pros[:5], "Player cons": player_cons[:5], "Player report": " ".join(report).strip(), "H2H summary": h2h.get("h2h_summary", "N/A"), "Likely map combo note": map_combo_note or "N/A", "Analytics headline": f"{payload.get('Final grade','N/A')} • {payload.get('Thunderpick odds', payload.get('Match odds','N/A'))} • {h2h.get('h2h_summary','No H2H sample')}", "Recommended side probability": f"{side_prob:.1f}%" if side_prob is not None else "N/A"}

def _choose_similar_bucket(opponent_rank: Optional[int], stats: Dict[str, str]) -> Tuple[str, str]:
    if opponent_rank is None:
        return "N/A", "N/A"
    for threshold in (5, 10, 20, 30, 50):
        if opponent_rank <= threshold:
            return f"Top {threshold} bucket (opponent rank #{opponent_rank})", stats.get(f"Vs Top {threshold} rating", "N/A")
    return f"Outside Top 50 (opponent rank #{opponent_rank})", "N/A"


def _grade(abs_edge: float, side_hit_rate: float) -> str:
    if abs_edge >= 25 and side_hit_rate >= 70:
        return "9.5/10 ELITE"
    if abs_edge >= 18:
        return "8.5/10 STRONG"
    if abs_edge >= 10:
        return "7.5/10 GOOD"
    if abs_edge >= 5:
        return "6.5/10 SMALL EDGE"
    return "5.0/10 NO BET"


def _build_payload(player_name: str, line: float, opponent: str, kill_mode: bool = True) -> Dict[str, Any]:
    result = search_player(player_name)
    if not result:
        return {"error": f"Could not find {player_name} on HLTV."}

    pid, slug, display_slug = result
    profile = fetch_player_profile(pid, slug)
    display_name = profile.get("display_name") or display_slug

    start_30, end_30 = _today_range(30)
    start_90, end_90 = _today_range(H2H_WINDOW_DAYS)
    recent_stats = fetch_player_stats(pid, slug, start_date=start_30, end_date=end_30)
    all_time_stats = fetch_player_stats(pid, slug)

    raw_rows = extract_history_rows(pid, slug)
    if not raw_rows:
        return {"error": "No HLTV match history was found for this player."}

    hydrated_rows = hydrate_maps(raw_rows, slug, display_name)
    all_paired_rows = pair_recent_series(hydrated_rows, max_series=None)
    paired_rows = all_paired_rows[:MAX_RECENT_SERIES]

    fallback_used = False
    if paired_rows:
        kill_samples = [int(row["kills"]) for row in paired_rows]
        hs_samples = [int(row["headshots"]) for row in paired_rows]
        sample_rounds = [int(row["rounds"]) for row in paired_rows]
    else:
        fallback_used = True
        kill_samples = [int(row["kills"]) for row in hydrated_rows[:10]]
        hs_samples = [int(row["headshots"]) for row in hydrated_rows[:10]]
        sample_rounds = [int(row["rounds"]) for row in hydrated_rows[:10]]

    target_samples = kill_samples if kill_mode else hs_samples
    stats = _sample_stats(target_samples, line)

    if target_samples and sample_rounds:
        total_rounds = sum(sample_rounds)
        total_stat = sum(target_samples)
        rate_per_round = total_stat / total_rounds if total_rounds else 0.0
        projection = round(rate_per_round * median(sample_rounds), 1)
    else:
        total_rounds = total_stat = 0
        projection = None

    recommendation = "NO BET"
    side_probability = None
    hit_rate = stats["hit_rate"]

    if stats["avg"] is not None and stats["over_probability"] is not None and stats["under_probability"] is not None and hit_rate is not None:
        if stats["avg"] > line and stats["over_probability"] >= 55 and hit_rate >= 55:
            recommendation = "OVER"
            side_probability = stats["over_probability"]
        elif stats["avg"] < line and stats["under_probability"] >= 55 and (100 - hit_rate) >= 55:
            recommendation = "UNDER"
            side_probability = stats["under_probability"]
        else:
            side_probability = max(stats["over_probability"], stats["under_probability"])

    edge_pct = (side_probability - 50.0) if side_probability is not None else None
    side_hit_rate = hit_rate if recommendation == "OVER" else (100.0 - hit_rate if hit_rate is not None else 0.0)
    final_grade = _grade(abs(edge_pct or 0.0), side_hit_rate or 0.0)

    team_name = profile.get("team_name", "N/A")
    match_url = _find_profile_match_url(profile.get("match_links", []), opponent)
    match_context = fetch_match_context(match_url, team_name, opponent) if match_url else {}
    resolved_team = match_context.get("Resolved team", team_name)
    resolved_opponent = match_context.get("Resolved opponent", opponent.title() if opponent and opponent.upper() != "N/A" else "N/A")

    if match_context.get("Team ranking") in (None, "", "N/A"):
        match_context["Team ranking"] = profile.get("team_ranking", "N/A")

    opponent_rank_int = None
    try:
        if match_context.get("Opponent ranking") not in (None, "", "N/A"):
            opponent_rank_int = int(str(match_context["Opponent ranking"]).replace("#", ""))
    except Exception:
        opponent_rank_int = None

    buckets = dict(profile.get("profile_buckets") or {})
    role, role_note = _profile_bucket_role(buckets)

    merged_stats = dict(recent_stats)
    for key in ("Firepower", "Entrying", "Trading", "Opening", "Clutching", "Sniping", "Utility"):
        if merged_stats.get(key) in (None, "", "N/A"):
            merged_stats[key] = buckets.get(key, "N/A")

    similar_teams, similar_bucket_rating = _choose_similar_bucket(opponent_rank_int, merged_stats)

    total_kill_sample = sum(kill_samples) if kill_samples else 0
    total_hs_sample = sum(hs_samples) if hs_samples else 0
    recent_hs_pct = (total_hs_sample / total_kill_sample * 100.0) if total_kill_sample > 0 else None

    per_map_averages = build_per_map_averages(hydrated_rows)
    map_weighting = _map_weighted_projection(
        rows=paired_rows,
        likely_maps=match_context.get("Likely maps", {}) or {},
        per_map=per_map_averages,
        fallback_projection=projection,
        headshots=not kill_mode,
    )
    pace_model = _pace_model(paired_rows if paired_rows else [], line=line, projection=projection)
    multi_kill_model = _multi_kill_pressure(paired_rows if paired_rows else [], line=line)

    payload = {
        "Player": display_name,
        "Opponent": resolved_opponent,
        "Team": resolved_team,
        "Prop Line": f"{line} {'Kills' if kill_mode else 'Headshots'}",
        "Bet recommendation": recommendation,
        "Final grade": final_grade,
        "Mispriced or not": "YES" if (edge_pct is not None and abs(edge_pct) >= 5) else "NO",
        "Recent average": round(stats["avg"], 2) if stats["avg"] is not None else "N/A",
        "Recent median": round(stats["median"], 1) if stats["median"] is not None else "N/A",
        "Recent projection": projection if projection is not None else "N/A",
        "Projected kills": projection if projection is not None else "N/A",
        "Projected headshots": projection if projection is not None else "N/A",
        "Hit rate": f"{hit_rate:.1f}%" if hit_rate is not None else "N/A",
        "25th percentile": stats["q25"],
        "75th percentile": stats["q75"],
        "Over probability": f"{stats['over_probability']:.1f}%" if stats["over_probability"] is not None else "N/A",
        "Under probability": f"{stats['under_probability']:.1f}%" if stats["under_probability"] is not None else "N/A",
        "Edge vs line": f"{edge_pct:.1f}%" if edge_pct is not None else "N/A",
        "Simulated mean": round(stats["sim_mean"], 2) if stats["sim_mean"] is not None else "N/A",
        "Simulated median": round(stats["sim_median"], 2) if stats["sim_median"] is not None else "N/A",
        "Std Dev": round(stats["std_dev"], 2) if stats["std_dev"] is not None else "N/A",
        "Rating 3.0": recent_stats.get("Rating 3.0 recent") if recent_stats.get("Rating 3.0 recent") not in (None, "", "N/A") else profile.get("rating_3", "N/A"),
        "Role": role,
        "Role note": role_note,
        "Recent form": _recent_form_string(paired_rows if paired_rows else []),
        "Exact round note": "Using first two maps only from each exact HLTV series sample." if not fallback_used else "Fell back to exact individual map sample because recent two-map series were unavailable.",
        "Firepower": merged_stats.get("Firepower", "N/A"),
        "Entrying": merged_stats.get("Entrying", "N/A"),
        "Trading": merged_stats.get("Trading", "N/A"),
        "Opening": merged_stats.get("Opening", "N/A"),
        "Clutching": merged_stats.get("Clutching", "N/A"),
        "Sniping": merged_stats.get("Sniping", "N/A"),
        "Utility": merged_stats.get("Utility", "N/A"),
        "KPR": recent_stats.get("KPR", all_time_stats.get("KPR", "N/A")),
        "DPR": recent_stats.get("DPR", all_time_stats.get("DPR", "N/A")),
        "ADR": recent_stats.get("ADR", all_time_stats.get("ADR", "N/A")),
        "KAST": recent_stats.get("KAST", all_time_stats.get("KAST", "N/A")),
        "Impact": recent_stats.get("Impact", all_time_stats.get("Impact", "N/A")),
        "Round swing": recent_stats.get("Round swing", all_time_stats.get("Round swing", "N/A")),
        "HS %": recent_stats.get("HS %", all_time_stats.get("HS %", "N/A")),
        "Opening kills per round": recent_stats.get("Opening kills per round", all_time_stats.get("Opening kills per round", "N/A")),
        "Trade kills per round": recent_stats.get("Trade kills per round", all_time_stats.get("Trade kills per round", "N/A")),
        "Vs Top 5 rating": recent_stats.get("Vs Top 5 rating", all_time_stats.get("Vs Top 5 rating", "N/A")),
        "Vs Top 10 rating": recent_stats.get("Vs Top 10 rating", all_time_stats.get("Vs Top 10 rating", "N/A")),
        "Vs Top 20 rating": recent_stats.get("Vs Top 20 rating", all_time_stats.get("Vs Top 20 rating", "N/A")),
        "Vs Top 30 rating": recent_stats.get("Vs Top 30 rating", all_time_stats.get("Vs Top 30 rating", "N/A")),
        "Vs Top 50 rating": recent_stats.get("Vs Top 50 rating", all_time_stats.get("Vs Top 50 rating", "N/A")),
        "Similar teams": similar_teams,
        "Similar teams rating": similar_bucket_rating,
        "Team ranking": match_context.get("Team ranking", profile.get("team_ranking", "N/A")),
        "Opponent ranking": match_context.get("Opponent ranking", "N/A"),
        "Match odds": match_context.get("Match odds", "N/A"),
        "Thunderpick odds": match_context.get("Thunderpick odds", match_context.get("Match odds", "N/A")),
        "Public pick": match_context.get("Public pick", "N/A"),
        "Veto": match_context.get("Veto", []),
        "Likely maps": match_context.get("Likely maps", {}),
        "Likely maps source": match_context.get("Likely maps source", "N/A"),
        "Veto notes": match_context.get("Veto notes", []),
        "H2H Data": _h2h_payload(all_paired_rows, resolved_opponent, max_age_days=H2H_WINDOW_DAYS),
        "Scenarios": _build_scenarios(paired_rows, sum(kill_samples), sum(sample_rounds)) if paired_rows else {},
        "Recent Totals (M1+M2 Combined)": kill_samples,
        "Recent HS Totals (M1+M2)": hs_samples,
        "Recent kills": kill_samples,
        "Recent headshots": hs_samples,
        "Recent HS %": f"{recent_hs_pct:.1f}%" if recent_hs_pct is not None else "N/A",
        "Recent HS Average": round(mean(hs_samples), 2) if hs_samples else "N/A",
        "Recent HS Median": round(median(hs_samples), 1) if hs_samples else "N/A",
        "All-time profile HS %": all_time_stats.get("HS %", recent_stats.get("HS %", "N/A")),
        "Paired series rows": paired_rows,
        "All paired series rows": all_paired_rows,
        "Raw maps": hydrated_rows,
        "Per-map averages": per_map_averages,
        "Sample": f"{len(paired_rows)} series" if paired_rows else f"{len(hydrated_rows[:10])} maps (fallback)",
        "Sample note": "Exact series sample" if not fallback_used else "Fallback to exact map sample",
        "Recent stat window": f"{start_30} to {end_30}",
        "H2H window": f"{start_90 if 'start_90' in locals() else 'N/A'} to {end_90 if 'end_90' in locals() else 'N/A'}",
    }

    payload.update(map_weighting)
    payload.update(pace_model)
    payload.update(multi_kill_model)
    payload.update(_opponent_strength_model(payload))
    payload.update(build_payload_analytics(payload, line=line, kill_mode=kill_mode))
    return payload


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
