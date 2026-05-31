import os
import re
import time
import math
import functools
from datetime import date, datetime, timedelta
from statistics import mean, median, stdev
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

from bs4 import BeautifulSoup

try:
    import numpy as np
except Exception:
    np = None

print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as curl_requests
    import requests as std_requests

    class _SessionWrapper:
        def get(self, url, **kw):
            try:
                return curl_requests.get(url, **kw)
            except Exception:
                return std_requests.get(url, **kw)

    requests = _SessionWrapper()
except Exception:
    import requests


HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")

REQUEST_TIMEOUT = 18
FETCH_RETRIES = 2
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
    "anc": "Ancient", "anb": "Anubis", "d2": "Dust2", "inf": "Inferno",
    "mrg": "Mirage", "nuke": "Nuke", "ovp": "Overpass", "trn": "Train",
    "vrt": "Vertigo", "cbl": "Cobblestone", "cch": "Cache", "tcn": "Tuscan",
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

ATTR_BUCKET_KEYS = ("Firepower", "Entrying", "Trading", "Opening", "Clutching", "Sniping", "Utility")

MAP_NAMES = (
    "Ancient", "Anubis", "Cache", "Cobblestone", "Dust2", "Inferno",
    "Mirage", "Nuke", "Overpass", "Season", "Train", "Tuscan", "Vertigo",
)

# Map pace profiles: avg rounds per map historically (higher = slower/longer)
MAP_PACE_PROFILES = {
    "Mirage":    {"avg_rounds": 25.8, "ot_rate": 0.12, "ct_sided": 0.52, "blowout_rate": 0.18},
    "Inferno":   {"avg_rounds": 26.1, "ot_rate": 0.14, "ct_sided": 0.54, "blowout_rate": 0.16},
    "Nuke":      {"avg_rounds": 24.9, "ot_rate": 0.10, "ct_sided": 0.59, "blowout_rate": 0.22},
    "Ancient":   {"avg_rounds": 25.5, "ot_rate": 0.11, "ct_sided": 0.53, "blowout_rate": 0.17},
    "Anubis":    {"avg_rounds": 25.2, "ot_rate": 0.13, "ct_sided": 0.51, "blowout_rate": 0.19},
    "Vertigo":   {"avg_rounds": 25.0, "ot_rate": 0.09, "ct_sided": 0.55, "blowout_rate": 0.21},
    "Overpass":  {"avg_rounds": 26.3, "ot_rate": 0.15, "ct_sided": 0.52, "blowout_rate": 0.15},
    "Dust2":     {"avg_rounds": 25.4, "ot_rate": 0.11, "ct_sided": 0.50, "blowout_rate": 0.20},
    "Train":     {"avg_rounds": 25.6, "ot_rate": 0.12, "ct_sided": 0.56, "blowout_rate": 0.17},
    "Cache":     {"avg_rounds": 25.1, "ot_rate": 0.10, "ct_sided": 0.51, "blowout_rate": 0.20},
    "Cobblestone":{"avg_rounds": 25.3,"ot_rate": 0.11, "ct_sided": 0.52, "blowout_rate": 0.18},
    "Tuscan":    {"avg_rounds": 25.0, "ot_rate": 0.10, "ct_sided": 0.51, "blowout_rate": 0.20},
    "Season":    {"avg_rounds": 25.0, "ot_rate": 0.10, "ct_sided": 0.51, "blowout_rate": 0.20},
}
DEFAULT_MAP_PACE = {"avg_rounds": 25.3, "ot_rate": 0.11, "ct_sided": 0.52, "blowout_rate": 0.19}

TEAM_MAP_WINDOW_DAYS = 90
H2H_WINDOW_DAYS = 90


# ─────────────────────────────────────────────────────────────────────
# Core utility helpers
# ─────────────────────────────────────────────────────────────────────

def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).replace("\xa0", " ").strip()

def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())

def _abs_url(href: str) -> str:
    if not href:
        return ""
    return href if href.startswith("http") else f"{HLTV_BASE}{href}"

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
    if any(x in url_lower for x in ("/stats/players/", "/stats/players/matches/", "/stats/matches/mapstatsid/", "/ranking/teams/")):
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
            f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}"
            f"&url={encoded}{'&render=true' if render else ''}&country_code=us&keep_headers=true"
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
        time.sleep(0.5)

    if render:
        alt_html, alt_url = _fetch(url, render=False)
        if alt_html:
            FETCH_CACHE[cache_key] = (alt_html, alt_url)
            return alt_html, alt_url

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
    return [_norm(line) for line in soup.get_text("\n", strip=True).splitlines() if _norm(line)]

def _find_line_indices(lines: List[str], label: str, exact: bool = True) -> List[int]:
    target = label.lower().strip()
    return [idx for idx, line in enumerate(lines) if (line.lower().strip() == target if exact else target in line.lower().strip())]

def _value_after(lines, label, pattern, occurrence=1, lookahead=8, exact=True):
    hits = _find_line_indices(lines, label, exact=exact)
    if len(hits) < occurrence:
        return None
    idx = hits[occurrence - 1]
    rx = re.compile(pattern)
    for j in range(idx + 1, min(len(lines), idx + 1 + lookahead)):
        if rx.fullmatch(lines[j]):
            return lines[j]
    return None

def _value_before(lines, label, pattern, occurrence=1, lookback=4, exact=True):
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

def _value_near(lines, label, pattern, occurrence=1, window=8, exact=True):
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
    return [m for m in MAP_NAMES if m.lower() in raw.lower()][:3]

def _series_stat_average(rows, field):
    values = [float(row.get(field, 0) or 0) for row in rows if row.get(field) is not None]
    return round(mean(values), 2) if values else None


# ─────────────────────────────────────────────────────────────────────
# Attribute bucket extraction (FIXED — returns numeric scores)
# ─────────────────────────────────────────────────────────────────────

def _extract_bucket_scores(lines: List[str], soup: Optional[BeautifulSoup] = None) -> Dict[str, str]:
    """Returns scores in 'NN/100' format for all ATTR_BUCKET_KEYS."""
    buckets: Dict[str, str] = {}

    # Method 1: near-label search
    for label in ATTR_BUCKET_KEYS:
        val = _value_near(lines, label, r"(\d{1,3}/100)", window=6, exact=True)
        if val:
            buckets[label] = val if "/100" in str(val) else f"{val}/100"

    # Method 2: regex sweep full text
    if len(buckets) < len(ATTR_BUCKET_KEYS):
        full_text = " ".join(lines)
        for label in ATTR_BUCKET_KEYS:
            if label in buckets:
                continue
            m = re.search(rf"{re.escape(label)}\s*[:\-]?\s*(\d{{1,3}})/100", full_text, re.I)
            if m:
                buckets[label] = f"{m.group(1)}/100"

    # Method 3: soup-level extraction
    if soup and len(buckets) < len(ATTR_BUCKET_KEYS):
        for label in ATTR_BUCKET_KEYS:
            if label in buckets:
                continue
            # Try data-* attributes that HLTV uses for radar charts
            for tag in soup.find_all(attrs={"data-value": True}):
                parent_text = _norm(tag.find_parent().get_text(" ") if tag.find_parent() else "")
                if label.lower() in parent_text.lower():
                    try:
                        val = int(tag.get("data-value", ""))
                        buckets[label] = f"{val}/100"
                        break
                    except Exception:
                        pass

            if label in buckets:
                continue

            node = soup.find(string=re.compile(re.escape(label), re.I))
            if node:
                parent = node.find_parent()
                if parent:
                    text = _norm(parent.get_text(" "))
                    m = re.search(r"(\d{1,3})/100", text)
                    if m:
                        buckets[label] = f"{m.group(1)}/100"
                        continue
                for sibling in (node.next_siblings if hasattr(node, "next_siblings") else []):
                    sib_text = _norm(str(sibling))
                    m = re.search(r"(\d{1,3})/100", sib_text)
                    if m:
                        buckets[label] = f"{m.group(1)}/100"
                        break

    # Method 4: brute-force line scan
    if len(buckets) < len(ATTR_BUCKET_KEYS):
        for label in ATTR_BUCKET_KEYS:
            if label in buckets:
                continue
            for line in lines:
                if label.lower() in line.lower():
                    m = re.search(r"(\d{1,3})/100", line)
                    if m:
                        buckets[label] = f"{m.group(1)}/100"
                        break

    # Method 5: Try percentage-style rendering (some HLTV pages render "Firepower 89%")
    if len(buckets) < len(ATTR_BUCKET_KEYS):
        for label in ATTR_BUCKET_KEYS:
            if label in buckets:
                continue
            for line in lines:
                if label.lower() in line.lower():
                    m = re.search(r"(\d{1,3})%", line)
                    if m:
                        buckets[label] = f"{m.group(1)}/100"
                        break

    for label in ATTR_BUCKET_KEYS:
        buckets.setdefault(label, "N/A")

    return buckets


def _bucket_numeric(val: str) -> Optional[int]:
    """Extract integer from 'NN/100' or 'N/A'."""
    if not val or val == "N/A":
        return None
    m = re.search(r"(\d{1,3})/100", str(val))
    return int(m.group(1)) if m else None


# ─────────────────────────────────────────────────────────────────────
# Team / match helpers
# ─────────────────────────────────────────────────────────────────────

def _extract_team_link(anchor: Any) -> Optional[Dict[str, str]]:
    if anchor is None:
        return None
    href = anchor.get("href", "") if hasattr(anchor, "get") else ""
    text = _norm(anchor.get_text(" ", strip=True)) if hasattr(anchor, "get_text") else ""
    m = re.search(r"/team/(\d+)/([^/?#]+)", href)
    if not (m and text):
        return None
    return {"id": m.group(1), "slug": m.group(2), "name": text, "url": _abs_url(href)}

def _extract_team_links_from_soup(soup, limit=12):
    if not soup:
        return []
    teams, seen = [], set()
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

def _resolve_match_teams(team_links, player_team, opponent):
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

def _profile_bucket_role(buckets: Dict[str, str]) -> Tuple[str, str]:
    scores: Dict[str, float] = {}
    for key, value in buckets.items():
        m = re.search(r"(\d{1,3})/100", str(value))
        if m:
            scores[key] = float(m.group(1))
    if not scores:
        return "N/A", "Role could not be derived — HLTV attribute buckets unavailable."
    fire = scores.get("Firepower", 0); open_ = scores.get("Opening", 0)
    entry = scores.get("Entrying", 0); trade = scores.get("Trading", 0)
    clutch = scores.get("Clutching", 0); snipe = scores.get("Sniping", 0)
    util = scores.get("Utility", 0)
    if snipe >= 70:
        return "AWPer", f"Sniping {int(snipe)}/100 is the dominant attribute."
    if entry >= 60 and open_ >= 55:
        return "Entry", f"Entrying {int(entry)}/100 + Opening {int(open_)}/100 — entry fragger profile."
    if open_ >= 70:
        return "Opener", f"Opening {int(open_)}/100 is the clearest role signal."
    if fire >= 70:
        return "Star rifler", f"Firepower {int(fire)}/100 leads the profile."
    if util >= 60 and fire < 65:
        return "Support", f"Utility {int(util)}/100 — support role."
    if clutch >= 60 and fire >= 50:
        return "Closer / rifler", f"Clutching {int(clutch)}/100 with Firepower {int(fire)}/100."
    if trade >= 55:
        return "Trader / lurker", f"Trading {int(trade)}/100 — lurker/trader profile."
    best_key = max(scores.items(), key=lambda kv: kv[1])[0]
    mapped = {"Firepower": "Rifler", "Opening": "Opener", "Entrying": "Entry",
              "Trading": "Trader", "Clutching": "Closer", "Sniping": "AWPer", "Utility": "Support"}
    return mapped.get(best_key, "Rifler"), f"{best_key} is the strongest profile attribute."


# ─────────────────────────────────────────────────────────────────────
# Player search
# ─────────────────────────────────────────────────────────────────────

def search_player(name: str) -> Optional[Tuple[str, str, str]]:
    key = _slugify(name)
    if key in STATIC_PLAYERS:
        pid, slug = STATIC_PLAYERS[key]
        return pid, slug, slug

    query = quote_plus(name.strip())
    for render in (True, False):
        soup, final_url, _ = _get_soup(f"{HLTV_BASE}/search?query={query}", render=render)
        if final_url and "/player/" in final_url:
            m = re.search(r"/player/(\d+)/([^/?#]+)", final_url)
            if m:
                return m.group(1), m.group(2), m.group(2)
        if soup:
            for a in soup.find_all("a", href=True):
                m = re.search(r"/player/(\d+)/([^/?#]+)", a.get("href", ""))
                if m:
                    return m.group(1), m.group(2), m.group(2)

    stats_soup, _, _ = _get_soup(f"{HLTV_BASE}/stats/players?query={query}", render=False)
    if stats_soup:
        for a in stats_soup.find_all("a", href=True):
            for pat in (r"/player/(\d+)/([^/?#]+)", r"/stats/players/(\d+)/([^/?#]+)"):
                m = re.search(pat, a.get("href", ""))
                if m:
                    return m.group(1), m.group(2), m.group(2)
    return None


# ─────────────────────────────────────────────────────────────────────
# Player profile
# ─────────────────────────────────────────────────────────────────────

def fetch_player_profile(pid: str, slug: str) -> Dict[str, Any]:
    soup = None
    for render in (True, False):
        s, _, _ = _get_soup(f"{HLTV_BASE}/player/{pid}/{slug}", render=render)
        if s:
            soup = s
            break

    if not soup:
        return {"display_name": slug, "team_name": "N/A", "team_id": None,
                "team_slug": None, "team_ranking": "N/A", "rating_3": "N/A",
                "profile_buckets": {}, "match_links": []}

    lines = _lines_from_soup(soup)
    display_name = slug
    h1 = soup.find("h1")
    if h1:
        display_name = _norm(h1.get_text(" ", strip=True)) or slug

    team_name, team_id, team_slug = "N/A", None, None
    marker = soup.find(string=re.compile(r"Current team", re.I))
    if marker:
        try:
            tl = marker.parent.find_next("a", href=re.compile(r"/team/"))
            info = _extract_team_link(tl)
            if info:
                team_name, team_id, team_slug = info["name"], info["id"], info["slug"]
        except Exception:
            pass
    if team_name == "N/A":
        for a in soup.find_all("a", href=re.compile(r"/team/\d+")):
            info = _extract_team_link(a)
            if info and info.get("name"):
                team_name, team_id, team_slug = info["name"], info["id"], info["slug"]
                break

    current_rank = _value_after(lines, "Current ranking", r"#?\d+", lookahead=4)
    rating_3 = (
        _value_after(lines, "Rating 3.0", r"\d+\.\d+", lookahead=4)
        or _value_near(lines, "Rating 3.0", r"(\d+\.\d+)", window=4)
        or _extract_first_match("\n".join(lines), r"Rating 3\.0\D{0,30}?(\d+\.\d+)")
        or "N/A"
    )
    buckets = _extract_bucket_scores(lines, soup=soup)

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

    rank_int = None
    if current_rank:
        try:
            rank_int = int(current_rank.replace("#", ""))
        except Exception:
            pass

    return {
        "display_name": display_name, "team_name": team_name, "team_id": team_id,
        "team_slug": team_slug, "team_ranking": _fmt_rank(rank_int),
        "rating_3": rating_3, "profile_buckets": buckets, "match_links": match_links,
    }


# ─────────────────────────────────────────────────────────────────────
# Player stats (KAST / Round Swing / all stats)
# ─────────────────────────────────────────────────────────────────────

def _build_stats_url(pid, slug, start_date=None, end_date=None):
    url = f"{HLTV_BASE}/stats/players/{pid}/{slug}"
    params = []
    if start_date:
        params.append(f"startDate={start_date}")
    if end_date:
        params.append(f"endDate={end_date}")
    return url + ("?" + "&".join(params) if params else "")

def _extract_kast_from_page(soup: BeautifulSoup, lines: List[str], text: str) -> str:
    """Multi-strategy KAST extraction."""
    # Strategy 1: look for KAST label in stats summary boxes
    for tag in soup.find_all(["div", "span", "td"], string=re.compile(r"^KAST$", re.I)):
        parent = tag.find_parent()
        if parent:
            siblings = list(parent.find_next_siblings())
            for sib in siblings[:4]:
                m = re.search(r"(\d{1,3}\.?\d*)\s*%?", sib.get_text())
                if m:
                    return f"{m.group(1)}%"
        # Try value in same cell structure
        nxt = tag.find_next(string=re.compile(r"\d+\.?\d*%?"))
        if nxt:
            m = re.search(r"(\d{1,3}\.?\d*)", str(nxt))
            if m:
                val = float(m.group(1))
                if 0 < val <= 100:
                    return f"{val}%"

    # Strategy 2: line-based patterns
    for pat in [
        r"KAST\s*[\n:]\s*(\d{1,3}\.?\d*)\s*%",
        r"(\d{1,3}\.?\d*)\s*%\s*KAST",
        r"KAST[^\d]{0,40}?(\d{2,3}\.?\d*)\s*%?",
    ]:
        m = re.search(pat, text, re.I | re.S)
        if m:
            val = float(m.group(1))
            if 0 < val <= 100:
                return f"{val}%"

    # Strategy 3: near-label line scanning
    result = (
        _value_near(lines, "KAST", r"(\d{1,3}\.\d+%)", window=6)
        or _value_near(lines, "KAST", r"(\d{1,3}%)", window=6)
    )
    return result or "N/A"

def _extract_round_swing_from_page(soup: BeautifulSoup, lines: List[str], text: str) -> str:
    """Multi-strategy Round Swing extraction."""
    # Strategy 1: soup tag search
    for tag in soup.find_all(["div", "span", "td"], string=re.compile(r"round swing", re.I)):
        parent = tag.find_parent()
        if parent:
            full_text = _norm(parent.get_text(" "))
            m = re.search(r"([+-]?\d+\.?\d*)\s*%", full_text)
            if m:
                return f"{m.group(1)}%"
        nxt = tag.find_next(string=re.compile(r"[+-]?\d+\.?\d*%?"))
        if nxt:
            m = re.search(r"([+-]?\d+\.?\d*)", str(nxt))
            if m:
                return f"{m.group(1)}%"

    # Strategy 2: regex patterns
    for pat in [
        r"Round swing\s*[\n:]\s*([+-]?\d+\.?\d*)\s*%?",
        r"([+-]?\d+\.?\d*)\s*%?\s*Round swing",
        r"Round swing[^\d+-]{0,40}?([+-]?\d+\.?\d*)",
    ]:
        m = re.search(pat, text, re.I | re.S)
        if m:
            return f"{m.group(1)}%"

    result = (
        _value_near(lines, "Round swing", r"([+-]?\d+\.\d+%)", window=6)
        or _value_near(lines, "Round swing", r"([+-]?\d+%)", window=6)
        or _extract_first_match(text, r"Round swing(?:.|\n){0,120}?([+-]?\d+\.?\d*%)")
    )
    return result or "N/A"

def fetch_player_stats(pid: str, slug: str, start_date=None, end_date=None) -> Dict[str, str]:
    def _try_fetch(sd, ed):
        url = _build_stats_url(pid, slug, sd, ed)
        for render in (False, True):
            s, _, _ = _get_soup(url, render=render)
            if s:
                lines_check = _lines_from_soup(s)
                if any(re.search(r"\d+\.\d+", l) for l in lines_check):
                    return s
        return None

    soup = _try_fetch(start_date, end_date)
    if not soup and (start_date or end_date):
        print(f"Stats thin for {slug} with date filter, falling back to all-time")
        soup = _try_fetch(None, None)
    if not soup:
        return {}

    lines = _lines_from_soup(soup)
    text = "\n".join(lines)
    stats: Dict[str, str] = {}

    stats["Rating 2.0"] = (
        _value_before(lines, "Rating 2.0", r"\d+\.\d+", lookback=4)
        or _extract_first_match(text, r"Rating 2\.0\D{0,30}?(\d+\.\d+)") or "N/A"
    )
    stats["Rating 3.0 recent"] = (
        _value_before(lines, "Rating 3.0", r"\d+\.\d+", lookback=4)
        or _value_near(lines, "Rating 3.0", r"(\d+\.\d+)", window=6)
        or _extract_first_match(text, r"Rating 3\.0\D{0,30}?(\d+\.\d+)") or "N/A"
    )

    # KAST — use dedicated multi-strategy extractor
    stats["KAST"] = _extract_kast_from_page(soup, lines, text)

    # Round Swing — use dedicated multi-strategy extractor
    stats["Round swing"] = _extract_round_swing_from_page(soup, lines, text)

    stats["ADR"] = (
        _value_near(lines, "ADR", r"(\d+\.\d+)", window=5)
        or _value_near(lines, "ADR", r"(\d+)", window=5)
        or _extract_first_match(text, r"\bADR\b(?:.|\n){0,80}?(\d+\.?\d*)") or "N/A"
    )
    stats["KPR"] = (
        _value_near(lines, "KPR", r"(\d+\.\d+)", window=5)
        or _extract_first_match(text, r"\bKPR\b(?:.|\n){0,80}?(\d+\.\d+)") or "N/A"
    )
    stats["DPR"] = (
        _value_near(lines, "DPR", r"(\d+\.\d+)", window=5)
        or _extract_first_match(text, r"\bDPR\b(?:.|\n){0,80}?(\d+\.\d+)") or "N/A"
    )
    stats["HS %"] = (
        _value_near(lines, "Headshot %", r"(\d+(?:\.\d+)?%)", window=4, exact=False)
        or _extract_first_match(text, r"Headshot\s*%\s*([0-9]+(?:\.[0-9]+)?%)")
        or _extract_first_match(text, r"HS%?\s*([0-9]+(?:\.[0-9]+)?%)") or "N/A"
    )
    stats["Impact"] = (
        _value_near(lines, "Impact rating", r"(\d+\.\d+)", window=5, exact=False)
        or _extract_first_match(text, r"Impact rating\s*([0-9]+\.[0-9]+)")
        or _extract_first_match(text, r"\bImpact\b(?:.|\n){0,60}?([0-9]+\.[0-9]+)") or "N/A"
    )
    stats["Opening kills per round"] = (
        _value_near(lines, "Opening kills per round", r"(\d+\.\d+)", window=5)
        or _extract_first_match(text, r"Opening kills per round(?:.|\n){0,40}?([0-9]+\.[0-9]+)") or "N/A"
    )
    stats["Trade kills per round"] = (
        _value_near(lines, "Trade kills per round", r"(\d+\.\d+)", window=5)
        or _extract_first_match(text, r"Trade kills per round(?:.|\n){0,40}?([0-9]+\.[0-9]+)") or "N/A"
    )
    stats["Maps played"] = (
        _value_near(lines, "Maps played", r"([\d,]+)", window=4, exact=False)
        or _extract_first_match(text, r"Maps played\s*([\d,]+)") or "N/A"
    )
    stats["Rounds played"] = (
        _value_near(lines, "Rounds played", r"([\d,]+)", window=4, exact=False)
        or _extract_first_match(text, r"Rounds played\s*([\d,]+)") or "N/A"
    )

    for label in ATTR_BUCKET_KEYS:
        stats[label] = (
            _value_near(lines, label, r"(\d{1,3}/100)", window=6)
            or _extract_first_match(text, rf"{re.escape(label)}\s*[:\-]?\s*(\d{{1,3}}/100)") or "N/A"
        )

    for bucket in (5, 10, 20, 30, 50):
        label = f"vs top {bucket} opponents"
        stats[f"Vs Top {bucket} rating"] = (
            _value_near(lines, label, r"(-|\d+\.\d+)", window=8, exact=False)
            or _extract_first_match(text, rf"vs top {bucket} opponents(?:.|\n){{0,80}}?(-|[0-9]+\.[0-9]+)") or "N/A"
        )

    return stats


# ─────────────────────────────────────────────────────────────────────
# History rows & hydration
# ─────────────────────────────────────────────────────────────────────

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
        mapstats_url = match_url = ""
        for a in links:
            href = a.get("href", "")
            if "/stats/matches/mapstatsid/" in href and not mapstats_url:
                mapstats_url = _abs_url(href)
            elif "/matches/" in href and not match_url:
                match_url = _abs_url(href)
            info = _extract_team_link(a)
            if info and all(info.get("id") != e.get("id") for e in team_links):
                team_links.append(info)
        if len(team_links) >= 2:
            team_name = team_links[0]["name"]; opponent_name = team_links[1]["name"]
            team_id = team_links[0]["id"]; team_slug_v = team_links[0]["slug"]
            opponent_id = team_links[1]["id"]; opponent_slug_v = team_links[1]["slug"]
        else:
            team_name = _strip_score_suffix(cells[1]) if len(cells) > 1 else "N/A"
            opponent_name = _strip_score_suffix(cells[2]) if len(cells) > 2 else "UNK"
            team_id = team_slug_v = opponent_id = opponent_slug_v = None
        score_bits = re.findall(r"\((\d+)\)", row_text)
        rounds_played = 24
        if len(score_bits) >= 2:
            try:
                rounds_played = int(score_bits[0]) + int(score_bits[1])
            except Exception:
                pass
        rating_matches = re.findall(r"\b(\d+\.\d+)\b", row_text)
        rating = rating_matches[-1] if rating_matches else "N/A"
        rows.append({
            "date": date_match.group(1), "team": team_name, "team_id": team_id,
            "team_slug": team_slug_v, "opponent": opponent_name, "opponent_id": opponent_id,
            "opponent_slug": opponent_slug_v,
            "map_name": MAP_ALIASES.get(map_match.group(1).lower(), map_match.group(1).lower()),
            "kills": int(kd_match.group(1)), "deaths": int(kd_match.group(2)),
            "rating": rating, "rounds": rounds_played,
            "mapstats_url": mapstats_url, "match_url": match_url,
        })
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
        if not any(c and c in key for c in normalized_candidates):
            continue
        m = re.search(r"(\d+)\s*\((\d+)\)", row_text)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None

def hydrate_maps(rows, slug, display_name):
    """Parallel hydration for speed."""
    def _hydrate_one(row):
        exact_kills, exact_hs = parse_mapstats(row.get("mapstats_url", ""), [slug, display_name])
        copy_row = dict(row)
        if exact_kills is not None:
            copy_row["kills"] = exact_kills
        copy_row["headshots"] = exact_hs if exact_hs is not None else 0
        return copy_row

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_hydrate_one, row): i for i, row in enumerate(rows)}
        results = [None] * len(rows)
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = rows[idx]
    return [r for r in results if r is not None]

def pair_recent_series(rows, max_series=MAX_RECENT_SERIES):
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
        paired.append({
            "date": first_two[0].get("date", "N/A"),
            "team": first_two[0].get("team", "N/A"),
            "team_id": first_two[0].get("team_id"),
            "team_slug": first_two[0].get("team_slug"),
            "opponent": first_two[0].get("opponent", "UNK"),
            "opponent_id": first_two[0].get("opponent_id"),
            "opponent_slug": first_two[0].get("opponent_slug"),
            "map1": first_two[0].get("map_name", "N/A"),
            "map2": first_two[1].get("map_name", "N/A"),
            "kills": int(first_two[0].get("kills", 0)) + int(first_two[1].get("kills", 0)),
            "deaths": int(first_two[0].get("deaths", 0)) + int(first_two[1].get("deaths", 0)),
            "headshots": int(first_two[0].get("headshots", 0)) + int(first_two[1].get("headshots", 0)),
            "rounds": int(first_two[0].get("rounds", 0)) + int(first_two[1].get("rounds", 0)),
            "rating_avg": round(mean([_safe_float(first_two[0].get("rating")) or 0.0, _safe_float(first_two[1].get("rating")) or 0.0]), 2),
            "maps_in_series": len(chrono_maps),
            "raw_maps": first_two,
        })
        if max_series is not None and len(paired) >= max_series:
            break
    return paired

def build_per_map_averages(rows):
    buckets: Dict[str, List] = {}
    for row in rows:
        buckets.setdefault(row.get("map_name", "Unknown"), []).append(row)
    final = {}
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


# ─────────────────────────────────────────────────────────────────────
# Advanced map modeling: pace, blowout, overtime, multi-kill
# ─────────────────────────────────────────────────────────────────────

def compute_map_weighted_kpr(hydrated_rows: List[Dict[str, Any]], likely_map_names: List[str]) -> Dict[str, Any]:
    """
    True map-weighted KPR: weight each map's KPR by how likely it is to appear
    in the upcoming series, based on map pace profiles.
    """
    if not hydrated_rows:
        return {"weighted_kpr": None, "map_weights": {}, "map_kpr": {}}

    # Build per-map KPR from exact history
    map_kpr: Dict[str, List[float]] = {}
    for row in hydrated_rows:
        mname = row.get("map_name", "Unknown")
        rounds = int(row.get("rounds", 24) or 24)
        kills = int(row.get("kills", 0))
        if rounds > 0:
            map_kpr.setdefault(mname, []).append(kills / rounds)

    avg_kpr_per_map = {m: mean(vals) for m, vals in map_kpr.items() if vals}

    # Weight by likely maps
    map_weights: Dict[str, float] = {}
    if likely_map_names:
        for mname in likely_map_names:
            pace = MAP_PACE_PROFILES.get(mname, DEFAULT_MAP_PACE)
            # Heavier maps get slightly more weight (more rounds = more kill opportunities)
            map_weights[mname] = pace["avg_rounds"] / 25.3
        total_w = sum(map_weights.values()) or 1
        map_weights = {k: v / total_w for k, v in map_weights.items()}

    if likely_map_names and avg_kpr_per_map:
        weighted_kpr = 0.0
        total_w = 0.0
        for mname in likely_map_names:
            kpr = avg_kpr_per_map.get(mname)
            if kpr is None:
                # Fall back to global average KPR
                all_kprs = [v for vals in avg_kpr_per_map.values() for v in [mean(vals)] if vals]
                kpr = mean(all_kprs) if all_kprs else 0.65
            w = map_weights.get(mname, 1.0 / len(likely_map_names))
            weighted_kpr += kpr * w
            total_w += w
        weighted_kpr = weighted_kpr / total_w if total_w else None
    else:
        all_kprs = list(avg_kpr_per_map.values())
        weighted_kpr = mean(all_kprs) if all_kprs else None

    return {
        "weighted_kpr": round(weighted_kpr, 4) if weighted_kpr else None,
        "map_weights": {k: round(v, 3) for k, v in map_weights.items()},
        "map_kpr": {k: round(v, 3) for k, v in avg_kpr_per_map.items()},
    }


def compute_pace_model(
    paired_rows: List[Dict[str, Any]],
    likely_map_names: List[str],
    line: float,
    kpr: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Pace model: projects kills using map-specific avg rounds + OT probability.
    Returns projected kills for slow/normal/fast pace + OT scenario.
    """
    if not paired_rows and kpr is None:
        return {}

    # Compute KPR from series sample
    if kpr is None:
        total_k = sum(int(r.get("kills", 0)) for r in paired_rows)
        total_r = sum(int(r.get("rounds", 48)) for r in paired_rows)
        kpr = total_k / total_r if total_r > 0 else 0.65

    # Get pace data for likely maps
    map_paces = [MAP_PACE_PROFILES.get(m, DEFAULT_MAP_PACE) for m in (likely_map_names or [])]
    if not map_paces:
        map_paces = [DEFAULT_MAP_PACE, DEFAULT_MAP_PACE]

    # Two-map expected rounds (sum of two map expected rounds)
    avg_rounds_per_map = mean(p["avg_rounds"] for p in map_paces)
    two_map_avg = avg_rounds_per_map * 2
    two_map_fast = avg_rounds_per_map * 2 * 0.88   # blowout-ish
    two_map_slow = avg_rounds_per_map * 2 * 1.10   # OT-ish

    ot_rate = mean(p["ot_rate"] for p in map_paces)
    blowout_rate = mean(p["blowout_rate"] for p in map_paces)

    # OT adds ~6 extra rounds per map that goes to OT
    ot_rounds_bonus = 6 * ot_rate

    proj_normal = kpr * two_map_avg
    proj_fast = kpr * two_map_fast
    proj_slow = kpr * (two_map_slow + ot_rounds_bonus * 2)
    proj_ot = kpr * (two_map_avg + 12)  # both maps go to OT

    return {
        "kpr_used": round(kpr, 4),
        "fast_pace_rounds": round(two_map_fast, 1),
        "normal_pace_rounds": round(two_map_avg, 1),
        "slow_pace_rounds": round(two_map_slow, 1),
        "proj_fast": round(proj_fast, 1),
        "proj_normal": round(proj_normal, 1),
        "proj_slow": round(proj_slow, 1),
        "proj_ot": round(proj_ot, 1),
        "ot_rate_pct": round(ot_rate * 100, 1),
        "blowout_rate_pct": round(blowout_rate * 100, 1),
        "over_line": line,
        "pace_edge": round(proj_normal - line, 2),
    }


def compute_blowout_impact(
    paired_rows: List[Dict[str, Any]],
    likely_map_names: List[str],
    line: float,
    kpr: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Blowout analysis: checks how player performs in short/blowout maps (<22 rounds)
    vs normal maps, and estimates impact on kill total when blowouts are likely.
    """
    if not paired_rows:
        return {}

    blowout_series = [r for r in paired_rows if int(r.get("rounds", 48)) < 44]  # ~22 per map avg
    normal_series = [r for r in paired_rows if int(r.get("rounds", 48)) >= 44]

    blowout_avg = mean(int(r.get("kills", 0)) for r in blowout_series) if blowout_series else None
    normal_avg = mean(int(r.get("kills", 0)) for r in normal_series) if normal_series else None

    map_blowout_rates = [MAP_PACE_PROFILES.get(m, DEFAULT_MAP_PACE)["blowout_rate"] for m in (likely_map_names or [])]
    expected_blowout_rate = mean(map_blowout_rates) if map_blowout_rates else 0.19

    result = {
        "blowout_sample": len(blowout_series),
        "normal_sample": len(normal_series),
        "blowout_avg_kills": round(blowout_avg, 1) if blowout_avg else "N/A",
        "normal_avg_kills": round(normal_avg, 1) if normal_avg else "N/A",
        "expected_blowout_rate_pct": round(expected_blowout_rate * 100, 1),
    }

    if blowout_avg and normal_avg:
        diff = blowout_avg - normal_avg
        result["blowout_vs_normal_diff"] = round(diff, 1)
        result["blowout_note"] = (
            f"Player averages {abs(diff):.1f} {'more' if diff > 0 else 'fewer'} kills in blowout maps vs normal pace. "
            f"Map blowout probability: {expected_blowout_rate*100:.0f}%."
        )
    return result


def compute_overtime_probability(
    likely_map_names: List[str],
    rank_diff: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Computes overtime probability for the series based on map profiles + rank gap.
    Close rank matchups have higher OT rates.
    """
    map_paces = [MAP_PACE_PROFILES.get(m, DEFAULT_MAP_PACE) for m in (likely_map_names or [])]
    if not map_paces:
        map_paces = [DEFAULT_MAP_PACE, DEFAULT_MAP_PACE]

    base_ot_rate = mean(p["ot_rate"] for p in map_paces)

    # Rank gap modifier: closer teams = more overtime
    rank_modifier = 1.0
    if rank_diff is not None:
        if abs(rank_diff) <= 5:
            rank_modifier = 1.4
        elif abs(rank_diff) <= 15:
            rank_modifier = 1.2
        elif abs(rank_diff) >= 30:
            rank_modifier = 0.7

    adjusted_ot_rate = min(base_ot_rate * rank_modifier, 0.40)

    # Probability at least one map goes to OT in a 2-map series
    at_least_one_ot = 1 - (1 - adjusted_ot_rate) ** 2

    # Expected extra rounds from OT
    expected_extra_rounds = at_least_one_ot * 6

    return {
        "per_map_ot_rate_pct": round(adjusted_ot_rate * 100, 1),
        "series_ot_probability_pct": round(at_least_one_ot * 100, 1),
        "expected_extra_ot_rounds": round(expected_extra_rounds, 1),
        "rank_modifier": round(rank_modifier, 2),
        "ot_note": (
            f"{round(at_least_one_ot * 100, 1)}% chance of OT in this 2-map series. "
            f"Expected {round(expected_extra_rounds, 1)} bonus rounds from OT."
        ),
    }


def compute_multikill_pressure(
    hydrated_rows: List[Dict[str, Any]],
    paired_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Multi-kill pressure: 2K and 3K+ frequency derived from kills/rounds ratio
    and historical series data. Also includes eco-farming and clutch signals.
    """
    if not hydrated_rows:
        return {}

    kills_list = [int(r.get("kills", 0)) for r in hydrated_rows]
    rounds_list = [int(r.get("rounds", 24) or 24) for r in hydrated_rows]

    total_kills = sum(kills_list)
    total_rounds = sum(rounds_list) or 1
    kpr = total_kills / total_rounds

    # Estimate multi-kill frequency
    # 2K probability per round ~ KPR^2 * adjustment (simplified model)
    # 3K probability ~ KPR^3 * adjustment
    p_2k_per_round = min(kpr ** 1.6 * 1.8, 0.35)
    p_3k_per_round = min(kpr ** 2.2 * 1.2, 0.15)

    avg_rounds_per_map = mean(rounds_list) if rounds_list else 24
    est_2k_per_map = p_2k_per_round * avg_rounds_per_map
    est_3k_per_map = p_3k_per_round * avg_rounds_per_map

    # Series-level (2 maps)
    est_2k_series = est_2k_per_map * 2
    est_3k_series = est_3k_per_map * 2

    # High-kill maps (proxy for multi-kill rounds)
    high_kill_maps = [r for r in hydrated_rows if int(r.get("kills", 0)) / max(int(r.get("rounds", 24)), 1) >= 0.85]
    high_kill_rate = len(high_kill_maps) / len(hydrated_rows) if hydrated_rows else 0

    result = {
        "kpr": round(kpr, 3),
        "est_2k_per_map": round(est_2k_per_map, 1),
        "est_3k_per_map": round(est_3k_per_map, 1),
        "est_2k_series": round(est_2k_series, 1),
        "est_3k_series": round(est_3k_series, 1),
        "high_kill_map_rate_pct": round(high_kill_rate * 100, 1),
        "multikill_note": (
            f"Est. {est_2k_series:.1f} double-kills and {est_3k_series:.1f} triple-kill rounds per 2-map series. "
            f"{round(high_kill_rate * 100, 1)}% of maps exceed 0.85 KPR."
        ),
    }
    return result


def compute_eco_and_clutch(
    hydrated_rows: List[Dict[str, Any]],
    paired_rows: List[Dict[str, Any]],
    buckets: Dict[str, str],
) -> Dict[str, Any]:
    """
    Eco farming + anti-eco padding + clutch conversion signals.
    Uses kill distribution, headshot rate, and clutch bucket to estimate.
    """
    kills_list = [int(r.get("kills", 0)) for r in hydrated_rows]
    rounds_list = [int(r.get("rounds", 24) or 24) for r in hydrated_rows]
    hs_list = [int(r.get("headshots", 0)) for r in hydrated_rows]

    total_kills = sum(kills_list)
    total_hs = sum(hs_list)
    total_rounds = sum(rounds_list) or 1

    hs_pct = (total_hs / total_kills * 100) if total_kills > 0 else 0

    clutch_score = _bucket_numeric(buckets.get("Clutching", "N/A")) or 50
    firepower_score = _bucket_numeric(buckets.get("Firepower", "N/A")) or 50

    # High HS% suggests eco farming (pistol/scout rounds)
    # Low HS% suggests more rifle kills (normal rounds)
    eco_farming_signal = hs_pct > 55
    anti_eco_signal = hs_pct > 65  # Very high HS% = lots of eco/pistol kills

    # Clutch conversion estimate
    # Clutch bucket > 65 suggests player wins more 1v1+ scenarios
    clutch_conversion_pct = min(clutch_score * 0.6 + 10, 55)  # scaled estimate

    # Kill variance (high variance = boom-or-bust)
    if len(kills_list) >= 3:
        kill_std = stdev(kills_list)
        kill_cv = kill_std / mean(kills_list) if mean(kills_list) > 0 else 0
    else:
        kill_std = 0
        kill_cv = 0

    notes = []
    if anti_eco_signal:
        notes.append(f"High HS% ({hs_pct:.0f}%) suggests significant eco/pistol round farming — kills may be inflated on eco rounds.")
    elif eco_farming_signal:
        notes.append(f"Moderate eco farming signal (HS% {hs_pct:.0f}%).")
    else:
        notes.append(f"HS% ({hs_pct:.0f}%) is consistent with primarily rifle engagements.")

    notes.append(f"Est. clutch conversion: {clutch_conversion_rate:.0f}% (Clutch bucket {clutch_score}/100)." if False else
                 f"Est. clutch conversion: {clutch_conversion_pct:.0f}% based on Clutch bucket {clutch_score}/100.")

    if kill_cv > 0.25:
        notes.append(f"High kill variance (CV {kill_cv:.2f}) — boom-or-bust tendency.")
    elif kill_cv < 0.12:
        notes.append(f"Very consistent output (CV {kill_cv:.2f}) — low variance profile.")

    return {
        "hs_pct": round(hs_pct, 1),
        "eco_farming_signal": eco_farming_signal,
        "anti_eco_padding": anti_eco_signal,
        "clutch_conversion_pct": round(clutch_conversion_pct, 1),
        "clutch_score": clutch_score,
        "firepower_score": firepower_score,
        "kill_std_dev": round(kill_std, 2),
        "kill_cv": round(kill_cv, 3),
        "eco_clutch_notes": notes,
    }


def compute_opponent_strength_adjustment(
    paired_rows: List[Dict[str, Any]],
    opponent_rank: Optional[int],
    stats: Dict[str, str],
) -> Dict[str, Any]:
    """
    Opponent strength adjustment: compares player's projected kills
    against tier-based historical ratings.
    """
    if opponent_rank is None:
        return {"opponent_tier": "Unknown", "tier_rating": "N/A", "adjustment_note": "Opponent rank unknown — no tier adjustment applied."}

    # Map rank to tier
    if opponent_rank <= 5:
        tier = "Top 5"
        tier_rating = stats.get("Vs Top 5 rating", "N/A")
    elif opponent_rank <= 10:
        tier = "Top 10"
        tier_rating = stats.get("Vs Top 10 rating", "N/A")
    elif opponent_rank <= 20:
        tier = "Top 20"
        tier_rating = stats.get("Vs Top 20 rating", "N/A")
    elif opponent_rank <= 30:
        tier = "Top 30"
        tier_rating = stats.get("Vs Top 30 rating", "N/A")
    elif opponent_rank <= 50:
        tier = "Top 50"
        tier_rating = stats.get("Vs Top 50 rating", "N/A")
    else:
        tier = "Outside Top 50"
        tier_rating = "N/A"

    # Compute kill adjustment multiplier from rating vs baseline 1.0
    tier_rating_float = _safe_float(tier_rating)
    adjustment_multiplier = 1.0
    adjustment_note = f"Opponent is ranked #{opponent_rank} ({tier})."
    if tier_rating_float and tier_rating_float != 0:
        # Rating 1.0 = baseline; above = positive, below = negative
        adjustment_multiplier = tier_rating_float / 1.0
        diff_pct = (adjustment_multiplier - 1.0) * 100
        direction = "higher" if diff_pct > 0 else "lower"
        adjustment_note += f" {tier} rating is {tier_rating} ({abs(diff_pct):.1f}% {direction} than baseline). "
        if abs(diff_pct) >= 10:
            adjustment_note += f"{'Boost' if diff_pct > 0 else 'Fade'} kill projection by ~{abs(diff_pct):.0f}%."
        else:
            adjustment_note += "Minimal tier adjustment needed."
    else:
        adjustment_note += f" No {tier} rating data — using global average."

    return {
        "opponent_tier": tier,
        "opponent_rank": opponent_rank,
        "tier_rating": tier_rating,
        "adjustment_multiplier": round(adjustment_multiplier, 3),
        "adjustment_note": adjustment_note,
    }


# ─────────────────────────────────────────────────────────────────────
# Statistical engine
# ─────────────────────────────────────────────────────────────────────

def bootstrap_distribution(samples: List[int], iterations: int = 15000) -> List[float]:
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

def _series_percentiles(samples):
    if not samples:
        return "N/A", "N/A"
    if np is not None:
        q25, q75 = np.percentile(np.array(samples), [25, 75])
        return f"{round(float(q25), 1)}", f"{round(float(q75), 1)}"
    ordered = sorted(samples)
    return str(ordered[max(0, int(0.25 * (len(ordered) - 1)))]), str(ordered[max(0, int(0.75 * (len(ordered) - 1)))])

def _sample_stats(values: List[int], line: float) -> Dict[str, Any]:
    if not values:
        return {"avg": None, "median": None, "hit_rate": None, "q25": "N/A", "q75": "N/A",
                "bootstrap": [], "over_probability": None, "under_probability": None,
                "sim_mean": None, "sim_median": None, "std_dev": None}
    avg_val = mean(values)
    median_val = median(values)
    hit_rate = (sum(1 for v in values if float(v) > line) / len(values)) * 100.0
    q25, q75 = _series_percentiles(values)
    boot = bootstrap_distribution(values)
    if boot:
        if np is not None:
            arr = np.array(boot, dtype=float)
            sim_mean = float(np.mean(arr)); sim_median = float(np.median(arr))
            std_dev = float(np.std(arr)); over_prob = float(np.mean(arr > line) * 100.0)
        else:
            sim_mean = mean(boot); sim_median = median(boot)
            std_dev = (sum((x - sim_mean) ** 2 for x in boot) / len(boot)) ** 0.5
            over_prob = (sum(1 for x in boot if x > line) / len(boot)) * 100.0
        under_prob = 100.0 - over_prob
    else:
        sim_mean = sim_median = std_dev = over_prob = under_prob = None
    return {"avg": avg_val, "median": median_val, "hit_rate": hit_rate, "q25": q25, "q75": q75,
            "bootstrap": boot, "over_probability": over_prob, "under_probability": under_prob,
            "sim_mean": sim_mean, "sim_median": sim_median, "std_dev": std_dev}

def _build_scenarios(series_rows, total_kills, total_rounds):
    if not series_rows or total_rounds <= 0:
        return {}
    rounds = [int(row.get("rounds", 0)) for row in series_rows if int(row.get("rounds", 0)) > 0]
    if not rounds:
        return {}
    if np is not None:
        short_r, norm_r, long_r = np.percentile(np.array(rounds), [25, 50, 75]).tolist()
    else:
        ordered = sorted(rounds)
        short_r = ordered[max(0, int(0.25 * (len(ordered) - 1)))]
        norm_r = ordered[len(ordered) // 2]
        long_r = ordered[max(0, int(0.75 * (len(ordered) - 1)))]
    kpr = total_kills / total_rounds
    return {
        "short": {"rounds": f"{round(short_r, 1)}", "expected_kills": f"{round(kpr * float(short_r), 1)}"},
        "normal": {"rounds": f"{round(norm_r, 1)}", "expected_kills": f"{round(kpr * float(norm_r), 1)}"},
        "long": {"rounds": f"{round(long_r, 1)}", "expected_kills": f"{round(kpr * float(long_r), 1)}"},
    }

def _recent_form_string(series_rows):
    if not series_rows:
        return "N/A"
    last5 = series_rows[:5]; last10 = series_rows[:10]
    avg5 = mean(int(x.get("kills", 0)) for x in last5)
    avg10 = mean(int(x.get("kills", 0)) for x in last10)
    hs5 = mean(int(x.get("headshots", 0)) for x in last5)
    return f"Last 5: {avg5:.1f}K / {hs5:.1f}HS • Last {len(last10)}: {avg10:.1f}K"


# ─────────────────────────────────────────────────────────────────────
# H2H, match context helpers
# ─────────────────────────────────────────────────────────────────────

def _h2h_payload(series_rows, opponent, max_age_days=H2H_WINDOW_DAYS):
    opp_key = _slugify(opponent)
    if not opp_key:
        return {}
    relevant = [r for r in series_rows if _team_name_matches(str(r.get("opponent", "")), opponent) and _within_days(r.get("date"), max_age_days)]
    if not relevant:
        return {"h2h_sample_size": 0, "h2h_avg_kills": "N/A", "h2h_avg_headshots": "N/A",
                "h2h_rows": [], "h2h_summary": f"No H2H sample in last {max_age_days} days."}
    avg_k = _series_stat_average(relevant, "kills")
    avg_hs = _series_stat_average(relevant, "headshots")
    return {
        "h2h_sample_size": len(relevant), "h2h_avg_kills": avg_k or "N/A",
        "h2h_avg_headshots": avg_hs or "N/A", "h2h_last_meeting": relevant[0].get("date", "N/A"),
        "h2h_rows": relevant[:5],
        "h2h_summary": f"{len(relevant)} series in last {max_age_days}d • {avg_k or 'N/A'} kills • {avg_hs or 'N/A'} HS",
    }

def _find_profile_match_url(match_links, opponent):
    for text, url in match_links:
        if _team_name_matches(text, opponent):
            return url
    return None

def _parse_pick_line(value: str) -> Dict[str, float]:
    out = {}
    if not value or value == "N/A":
        return out
    for chunk in str(value).split("|"):
        part = _norm(chunk)
        m = re.match(r"(.+?)\s+(\d+(?:\.\d+)?)%$", part)
        if m:
            out[_norm(m.group(1))] = float(m.group(2))
    return out

def _parse_odds_line(value: str) -> Dict[str, float]:
    out = {}
    if not value or value == "N/A":
        return out
    for chunk in str(value).split("|"):
        part = _norm(chunk)
        m = re.match(r"(.+?)\s+([0-9]+\.[0-9]+)$", part)
        if m:
            out[_norm(m.group(1))] = float(m.group(2))
    return out

def _extract_pick_percentages(lines, teams):
    hits = _find_line_indices(lines, "Pick a winner", exact=True)
    if not hits:
        hits = [i for i, l in enumerate(lines) if "pick a winner" in l.lower()]
    if not hits:
        return None
    idx = hits[0]
    percentages = []
    for j in range(idx + 1, min(len(lines), idx + 20)):
        if re.fullmatch(r"\d+(?:\.\d+)?%", lines[j]):
            percentages.append(lines[j])
    if len(percentages) >= 2 and len(teams) >= 2:
        return f"{teams[0]} {percentages[0]} | {teams[1]} {percentages[1]}"
    if len(teams) >= 2:
        block = " ".join(lines[idx:idx + 20])
        pcts = re.findall(r"(\d+(?:\.\d+)?%)", block)
        if len(pcts) >= 2:
            return f"{teams[0]} {pcts[0]} | {teams[1]} {pcts[1]}"
    return None

def _extract_veto_and_maps(lines):
    veto = [l for l in lines if re.search(r"(picked|removed|was left over)", l, flags=re.I)
            and (re.match(r"\d+\.\s*", l) or " picked " in l.lower() or " removed " in l.lower() or "was left over" in l.lower())]
    likely, picks, decider = {}, [], None
    for line in veto:
        pm = re.search(r"(.+?)\s+picked\s+(.+)", line, flags=re.I)
        if pm:
            picks.append((_norm(pm.group(1)), _norm(pm.group(2))))
        dm = re.search(r"(.+?)\s+was left over", line, flags=re.I)
        if dm:
            decider = _norm(dm.group(1))
    for team_name, map_name in picks[:2]:
        likely[f"{team_name} pick"] = map_name
    if decider:
        likely["Decider"] = decider
    return veto, likely

def _extract_decimal_odds_from_html(html, teams):
    if not html:
        return None, None, None
    patterns = [
        r'Thunderpick.{0,240}?"team1Odds"\s*:\s*"?([0-9]+\.[0-9]+)"?.{0,180}?"team2Odds"\s*:\s*"?([0-9]+\.[0-9]+)"?',
        r'"bookie"\s*:\s*"Thunderpick".{0,240}?"homeOdds"\s*:\s*"?([0-9]+\.[0-9]+)"?.{0,180}?"awayOdds"\s*:\s*"?([0-9]+\.[0-9]+)"?',
        r'"team1Odds"\s*:\s*"?([0-9]+\.[0-9]+)"?.{0,200}?"team2Odds"\s*:\s*"?([0-9]+\.[0-9]+)"?',
        r'"homeOdds"\s*:\s*"?([0-9]+\.[0-9]+)"?.{0,200}?"awayOdds"\s*:\s*"?([0-9]+\.[0-9]+)"?',
    ]
    for i, pat in enumerate(patterns):
        m = re.search(pat, html, flags=re.I | re.S)
        if m:
            source = "Thunderpick" if i < 2 else "html"
            return float(m.group(1)), float(m.group(2)), source
    all_odds = re.findall(r"\b([1-9]\.[0-9]{2})\b", html)
    for i in range(len(all_odds) - 1):
        o1, o2 = float(all_odds[i]), float(all_odds[i + 1])
        if 1.01 < o1 < 15.0 and 1.01 < o2 < 15.0:
            return o1, o2, "html-scan"
    return None, None, None

def _extract_team_rank_robust(lines, team_name, soup=None):
    # Method 1
    team_key = _slugify(team_name)
    for idx, line in enumerate(lines):
        if team_key not in _slugify(line):
            continue
        window_text = " ".join(lines[max(0, idx - 3):min(len(lines), idx + 10)])
        for pat in [r"(?:World rank|Ranked|ranking)[:\s#]*(\d+)", r"#(\d+)"]:
            m = re.search(pat, window_text, re.I)
            if m:
                return int(m.group(1))
    if soup:
        for tag in soup.find_all(string=re.compile(re.escape(team_name), re.I)):
            parent = tag.find_parent()
            if parent:
                m = re.search(r"#(\d+)", _norm(parent.get_text(" ")))
                if m:
                    return int(m.group(1))
    return None

def _analytics_url_from_match(match_url):
    m = re.search(r"/matches/(\d+)/(.*)$", match_url)
    return f"{HLTV_BASE}/betting/analytics/{m.group(1)}/{m.group(2)}" if m else None


# ─────────────────────────────────────────────────────────────────────
# Team map stats & likely maps
# ─────────────────────────────────────────────────────────────────────

def _build_team_maps_url(team_id, team_slug, start_date=None, end_date=None):
    url = f"{HLTV_BASE}/stats/teams/maps/{team_id}/{team_slug}"
    params = []
    if start_date:
        params.append(f"startDate={start_date}")
    if end_date:
        params.append(f"endDate={end_date}")
    return url + ("?" + "&".join(params) if params else "")

def fetch_team_map_stats(team_id, team_slug, start_date=None, end_date=None):
    if not team_id or not team_slug:
        return {}

    def _try(tid, tslug, sd, ed):
        url = _build_team_maps_url(tid, tslug, sd, ed)
        for render in (False, True):
            s, _, _ = _get_soup(url, render=render)
            if s:
                return s
        return None

    soup = _try(team_id, team_slug, start_date, end_date)
    if soup:
        lines_check = _lines_from_soup(soup)
        if not any(m in lines_check for m in MAP_NAMES) and (start_date or end_date):
            soup = _try(team_id, team_slug, None, None)
    if not soup:
        return {}

    lines = _lines_from_soup(soup)
    data = {}
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

def _best_map_by(pool, key, reverse=True, exclude=None):
    exclude_keys = {_slugify(x) for x in (exclude or [])}
    candidates = [(score, map_name, vals) for map_name, vals in pool.items()
                  if _slugify(map_name) not in exclude_keys
                  and (score := _safe_pct_value(vals.get(key))) is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=reverse)
    return candidates[0][1], candidates[0][2]

def _best_shared_map(team_pool, opp_pool, exclude=None):
    exclude_keys = {_slugify(x) for x in (exclude or [])}
    best, best_score = None, None
    for map_name, team_vals in team_pool.items():
        if _slugify(map_name) in exclude_keys or map_name not in opp_pool:
            continue
        opp_vals = opp_pool[map_name]
        score = (min(_safe_pct_value(team_vals.get("pick_pct")) or 0, _safe_pct_value(opp_vals.get("pick_pct")) or 0) +
                 (200 - (_safe_pct_value(team_vals.get("ban_pct")) or 100) - (_safe_pct_value(opp_vals.get("ban_pct")) or 100)))
        if best_score is None or score > best_score:
            best_score = score
            best = (map_name, team_vals, opp_vals)
    return best

def build_likely_maps_from_pools(player_team_name, opponent_name, player_pool, opponent_pool, official_veto=None):
    likely, notes = {}, []
    if official_veto:
        notes.append("Official HLTV veto found.")
    if not player_pool or not opponent_pool:
        if not notes:
            notes.append("No official veto and team map-pool data unavailable.")
        return likely, notes
    excluded = []
    team_ban = _best_map_by(player_pool, "ban_pct")
    opp_ban = _best_map_by(opponent_pool, "ban_pct")
    if team_ban:
        excluded.append(team_ban[0])
        notes.append(f"{player_team_name} ban lean: {team_ban[0]} ({team_ban[1].get('ban_pct', 'N/A')}).")
    if opp_ban:
        excluded.append(opp_ban[0])
        notes.append(f"{opponent_name} ban lean: {opp_ban[0]} ({opp_ban[1].get('ban_pct', 'N/A')}).")
    team_pick = _best_map_by(player_pool, "pick_pct", exclude=excluded)
    if team_pick and team_pick[0] in opponent_pool:
        o = opponent_pool[team_pick[0]]
        likely[f"{player_team_name} likely pick"] = f"{team_pick[0]} (WR {team_pick[1].get('win_rate', 'N/A')} / opp WR {o.get('win_rate', 'N/A')})"
        excluded.append(team_pick[0])
    opp_pick = _best_map_by(opponent_pool, "pick_pct", exclude=excluded)
    if opp_pick and opp_pick[0] in player_pool:
        t = player_pool[opp_pick[0]]
        likely[f"{opponent_name} likely pick"] = f"{opp_pick[0]} (WR {opp_pick[1].get('win_rate', 'N/A')} / opp WR {t.get('win_rate', 'N/A')})"
        excluded.append(opp_pick[0])
    decider = _best_shared_map(player_pool, opponent_pool, exclude=excluded)
    if decider:
        likely["Likely decider"] = f"{decider[0]} ({player_team_name} {decider[1].get('pick_pct', 'N/A')} / {opponent_name} {decider[2].get('pick_pct', 'N/A')})"
    notes.append(f"Derived from last {TEAM_MAP_WINDOW_DAYS}d of HLTV team map data.")
    return likely, notes

def _likely_map_combo_note(per_map, likely_maps, headshots=False):
    if not per_map or not likely_maps:
        return None
    extracted = []
    for value in likely_maps.values():
        for map_name in _extract_map_names_from_text(value):
            if map_name not in extracted:
                extracted.append(map_name)
    if len(extracted) < 2:
        return None
    total, details = 0.0, []
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
    return f"Exact map combo ({', '.join(details)}) → {total:.1f} {'HS' if headshots else 'kills'}."


# ─────────────────────────────────────────────────────────────────────
# Match context (parallel fetch for speed)
# ─────────────────────────────────────────────────────────────────────

def fetch_match_context(match_url, player_team, opponent):
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
    player_rank = _extract_team_rank_robust(lines, resolved_player_team, soup)
    opponent_rank = _extract_team_rank_robust(lines, resolved_opponent, soup)
    teams_for_display = [x for x in [resolved_player_team, resolved_opponent] if x]
    public_pick = _extract_pick_percentages(lines, teams_for_display)
    odds_a, odds_b, odds_source = _extract_decimal_odds_from_html(html or "", teams_for_display)

    analytics_url = _analytics_url_from_match(match_url)
    if analytics_url:
        analytics_soup, _, analytics_html = _get_soup(analytics_url, render=True)
        if not analytics_soup:
            analytics_soup, _, analytics_html = _get_soup(analytics_url, render=False)
        if analytics_soup:
            analytics_lines = _lines_from_soup(analytics_soup)
            analytics_team_links = _extract_team_links_from_soup(analytics_soup, limit=12)
            if analytics_team_links:
                team_links = analytics_team_links + [x for x in team_links if x.get("id") not in {y.get("id") for y in analytics_team_links}]
                player_entry, opponent_entry = _resolve_match_teams(team_links, resolved_player_team, resolved_opponent)
                resolved_player_team = player_entry.get("name") if player_entry else resolved_player_team
                resolved_opponent = opponent_entry.get("name") if opponent_entry else resolved_opponent
            player_rank = player_rank or _extract_team_rank_robust(analytics_lines, resolved_player_team, analytics_soup)
            opponent_rank = opponent_rank or _extract_team_rank_robust(analytics_lines, resolved_opponent, analytics_soup)
            public_pick = public_pick or _extract_pick_percentages(analytics_lines, [resolved_player_team, resolved_opponent])
            if not veto:
                analytics_veto, analytics_likely = _extract_veto_and_maps(analytics_lines)
                if analytics_veto:
                    veto, official_likely_maps = analytics_veto, analytics_likely
            if (odds_a is None or odds_b is None) and analytics_html:
                odds_a, odds_b, odds_source = _extract_decimal_odds_from_html(analytics_html, [resolved_player_team, resolved_opponent])

    odds_display = f"{resolved_player_team} {odds_a:.2f} | {resolved_opponent} {odds_b:.2f}" if (odds_a and odds_b) else "N/A"
    thunderpick_display = odds_display if odds_source in ("Thunderpick", "html", "html-scan") else "N/A"

    start_maps, end_maps = _today_range(TEAM_MAP_WINDOW_DAYS)

    # Parallel team map stats fetch
    def _fetch_player_pool():
        return fetch_team_map_stats(player_entry.get("id") if player_entry else None,
                                    player_entry.get("slug") if player_entry else None,
                                    start_date=start_maps, end_date=end_maps)
    def _fetch_opp_pool():
        return fetch_team_map_stats(opponent_entry.get("id") if opponent_entry else None,
                                    opponent_entry.get("slug") if opponent_entry else None,
                                    start_date=start_maps, end_date=end_maps)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_player = ex.submit(_fetch_player_pool)
        f_opp = ex.submit(_fetch_opp_pool)
        player_pool = f_player.result()
        opponent_pool = f_opp.result()

    derived_likely_maps, veto_notes = build_likely_maps_from_pools(
        resolved_player_team, resolved_opponent, player_pool, opponent_pool, official_veto=veto)
    likely_maps = dict(official_likely_maps or {})
    for key, value in derived_likely_maps.items():
        likely_maps.setdefault(key, value)

    return {
        "Match URL": match_url, "Resolved team": resolved_player_team or player_team,
        "Resolved opponent": resolved_opponent or opponent,
        "Veto": veto if veto else veto_notes,
        "Likely maps": likely_maps,
        "Likely maps source": "Official HLTV veto" if official_likely_maps else f"Derived from last {TEAM_MAP_WINDOW_DAYS}d HLTV team map data",
        "Team ranking": _fmt_rank(player_rank), "Opponent ranking": _fmt_rank(opponent_rank),
        "Match odds": odds_display, "Thunderpick odds": thunderpick_display,
        "Public pick": public_pick or "N/A", "Odds source": odds_source or "N/A",
        "Team map pool": player_pool, "Opponent map pool": opponent_pool,
        "Veto notes": veto_notes,
    }


# ─────────────────────────────────────────────────────────────────────
# Analytics builder
# ─────────────────────────────────────────────────────────────────────

def _choose_similar_bucket(opponent_rank, stats):
    if opponent_rank is None:
        return "N/A", "N/A"
    for threshold in (5, 10, 20, 30, 50):
        if opponent_rank <= threshold:
            return f"Top {threshold} (opp #{opponent_rank})", stats.get(f"Vs Top {threshold} rating", "N/A")
    return f"Outside Top 50 (#{opponent_rank})", "N/A"

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

def build_payload_analytics(payload: Dict[str, Any], line: float, kill_mode: bool = True) -> Dict[str, Any]:
    team_name = str(payload.get("Team", "N/A"))
    opponent_name = str(payload.get("Opponent", "N/A"))
    team_rank = _safe_rank_value(payload.get("Team ranking"))
    opponent_rank = _safe_rank_value(payload.get("Opponent ranking"))
    public_pick = _parse_pick_line(str(payload.get("Public pick", "N/A")))
    odds = _parse_odds_line(str(payload.get("Thunderpick odds", payload.get("Match odds", "N/A"))))
    h2h = payload.get("H2H Data", {}) or {}
    likely_maps = payload.get("Likely maps", {}) or {}
    per_map = payload.get("Per-map averages", {}) or {}
    projection = _safe_float(payload.get("Projected kills" if kill_mode else "Projected headshots"))
    recent_avg = _safe_float(payload.get("Recent average"))
    rating = _safe_float(payload.get("Rating 3.0"))
    kpr = _safe_float(payload.get("KPR")); dpr = _safe_float(payload.get("DPR"))
    adr = _safe_float(payload.get("ADR")); kast = _safe_pct_value(payload.get("KAST"))
    impact = _safe_float(payload.get("Impact"))
    firepower = _bucket_numeric(payload.get("Firepower", "N/A"))
    opening = _bucket_numeric(payload.get("Opening", "N/A"))
    entrying = _bucket_numeric(payload.get("Entrying", "N/A"))
    trading = _bucket_numeric(payload.get("Trading", "N/A"))
    clutching = _bucket_numeric(payload.get("Clutching", "N/A"))
    sniping = _bucket_numeric(payload.get("Sniping", "N/A"))
    utility = _bucket_numeric(payload.get("Utility", "N/A"))
    similar_rating = _safe_float(payload.get("Similar teams rating"))
    over_prob = _safe_pct_value(payload.get("Over probability"))
    under_prob = _safe_pct_value(payload.get("Under probability"))
    hit_rate = _safe_pct_value(payload.get("Hit rate"))
    h2h_avg = _safe_float(h2h.get("h2h_avg_kills" if kill_mode else "h2h_avg_headshots"))
    h2h_sample = int(h2h.get("h2h_sample_size", 0) or 0)
    map_combo_note = _likely_map_combo_note(per_map, likely_maps, headshots=not kill_mode)

    # Advanced model data
    pace = payload.get("Pace model", {}) or {}
    blowout = payload.get("Blowout analysis", {}) or {}
    ot = payload.get("Overtime analysis", {}) or {}
    mk = payload.get("Multikill analysis", {}) or {}
    eco = payload.get("Eco clutch analysis", {}) or {}
    opp_strength = payload.get("Opponent strength", {}) or {}

    recommendation = str(payload.get("Bet recommendation", "NO BET"))
    if recommendation == "NO BET" and projection is not None:
        recommendation = "OVER lean" if projection > line else "UNDER lean"

    player_pros, player_cons = [], []
    team_pros, team_cons = [], []
    opponent_pros, opponent_cons = [], []

    # Projection edge
    if projection is not None:
        edge = projection - line
        (player_pros if edge >= 1 else player_cons).append(
            f"Projection {projection:.1f} is {abs(edge):.1f} {'above' if edge >= 0 else 'below'} the {line} line.")

    # Recent average
    if recent_avg is not None:
        diff = recent_avg - line
        if diff >= 1:
            player_pros.append(f"Recent 2-map average: {recent_avg:.1f} kills.")
        elif diff <= -1:
            player_cons.append(f"Recent 2-map average is only {recent_avg:.1f} kills.")

    # Core stats
    for val, high, low, label in [
        (rating, 1.1, 1.0, "Rating 3.0"), (kpr, .75, .65, "KPR"),
        (adr, 80, 70, "ADR"), (kast, 72, 68, "KAST"), (impact, 1.1, 1.0, "Impact"),
    ]:
        if val is None:
            continue
        fmt = f"{val:.1f}{'%' if label == 'KAST' else ''}" if label in ("ADR", "KAST") else f"{val:.2f}"
        (player_pros if val >= high else player_cons if val < low else player_pros).append(f"{label}: {fmt}.")
    if dpr is not None:
        (player_cons if dpr >= .72 else player_pros).append(f"DPR: {dpr:.2f}.")

    # Bucket signals
    for val, label, cut in [(firepower, "Firepower", 70), (opening, "Opening", 65),
                             (entrying, "Entrying", 60), (trading, "Trading", 60),
                             (clutching, "Clutching", 60), (sniping, "Sniping", 70),
                             (utility, "Utility", 60)]:
        if val is not None:
            suffix = f"{val}/100"
            if val >= cut:
                player_pros.append(f"{label} bucket: {suffix}.")
            elif val < cut - 15:
                player_cons.append(f"{label} bucket below average: {suffix}.")

    # H2H
    if h2h_sample > 0 and h2h_avg is not None:
        (player_pros if h2h_avg > line else player_cons).append(
            f"H2H: {h2h_sample} series, {h2h_avg:.1f} avg kills vs {opponent_name}.")

    # Map combo
    if map_combo_note:
        (player_pros if projection is not None and projection >= line else player_cons).append(map_combo_note)

    # Pace model signals
    if pace.get("proj_normal"):
        pn = pace["proj_normal"]
        (player_pros if pn > line else player_cons).append(
            f"Pace model: {pn} kills at normal pace (fast: {pace.get('proj_fast', 'N/A')}, slow: {pace.get('proj_slow', 'N/A')}).")
    if ot.get("series_ot_probability_pct"):
        ot_pct = ot["series_ot_probability_pct"]
        if ot_pct >= 20:
            player_pros.append(f"OT probability: {ot_pct}% — extra rounds boost ceiling.")

    # Blowout
    if blowout.get("blowout_note"):
        player_cons.append(blowout["blowout_note"]) if blowout.get("blowout_avg_kills", "N/A") != "N/A" and float(str(blowout.get("blowout_avg_kills", 0)).replace("N/A", "0") or 0) < line else player_pros.append(blowout["blowout_note"])

    # Multi-kill pressure
    if mk.get("multikill_note"):
        (player_pros if (mk.get("est_2k_series", 0) or 0) >= 4 else player_cons).append(mk["multikill_note"])

    # Eco/clutch signals
    if eco.get("eco_clutch_notes"):
        for note in eco["eco_clutch_notes"][:2]:
            player_pros.append(note) if "farming" not in note.lower() and "variance" not in note.lower() else player_cons.append(note)

    # Opponent strength
    if opp_strength.get("adjustment_note"):
        adj_mult = opp_strength.get("adjustment_multiplier", 1.0)
        (player_cons if adj_mult < 0.95 else player_pros if adj_mult > 1.05 else player_pros).append(opp_strength["adjustment_note"])

    # Similar rating
    if similar_rating is not None:
        (player_pros if similar_rating >= 1.05 else player_cons if similar_rating < 1.0 else player_pros).append(
            f"vs similar-tier teams rating: {similar_rating:.2f}.")

    # Team signals
    if team_rank is not None and opponent_rank is not None:
        if team_rank < opponent_rank:
            team_pros.append(f"Rank edge: #{team_rank} vs #{opponent_rank}.")
            opponent_cons.append(f"Rank disadvantage: #{opponent_rank}.")
        else:
            team_cons.append(f"Rank disadvantage: #{team_rank} vs #{opponent_rank}.")
            opponent_pros.append(f"Opponent rank edge: #{opponent_rank}.")

    for name, pct in public_pick.items():
        if _team_name_matches(name, team_name):
            (team_pros if pct >= 55 else team_cons).append(f"Public: {pct:.1f}% on {team_name}.")
        elif _team_name_matches(name, opponent_name):
            (opponent_pros if pct >= 55 else opponent_cons).append(f"Public: {pct:.1f}% on {opponent_name}.")
    for name, odd in odds.items():
        if _team_name_matches(name, team_name):
            (team_pros if odd <= 1.70 else team_cons if odd >= 2.20 else team_pros).append(f"Price: {odd:.2f}.")
        elif _team_name_matches(name, opponent_name):
            (opponent_pros if odd <= 1.70 else opponent_cons if odd >= 2.20 else opponent_pros).append(f"Price: {odd:.2f}.")

    for lst, default in [(team_pros, "No clear team edge."), (team_cons, "No major team flag."),
                          (opponent_pros, "No clear opponent edge."), (opponent_cons, "No clear opponent flag."),
                          (player_pros, "No standout player edge."), (player_cons, "No major player flag.")]:
        if not lst:
            lst.append(default)

    side_prob = over_prob if "OVER" in recommendation.upper() else under_prob

    # Player report — detailed characteristic summary
    report_parts = [f"Grade: {payload.get('Final grade', 'N/A')} | Recommendation: {recommendation}."]
    role = payload.get("Role", "N/A")
    role_note = payload.get("Role note", "")
    report_parts.append(f"Role: {role}. {role_note}")
    if projection is not None:
        report_parts.append(f"Projection: {projection:.1f} vs line {line:.1f} (edge: {projection - line:+.1f}).")
    if hit_rate is not None:
        report_parts.append(f"Historical hit rate: {hit_rate:.1f}%.")
    if side_prob is not None:
        report_parts.append(f"Model side probability: {side_prob:.1f}%.")
    if kast is not None:
        kast_note = "elite KAST" if kast >= 74 else "solid KAST" if kast >= 68 else "below-average KAST"
        report_parts.append(f"{kast_note} ({kast:.1f}%) — {kast_note} signals consistent round impact.")
    if pace.get("proj_normal"):
        report_parts.append(f"Pace model projects {pace['proj_normal']} kills at normal pace ({pace.get('normal_pace_rounds', 'N/A')} rounds).")
    if ot.get("ot_note"):
        report_parts.append(ot["ot_note"])
    if blowout.get("blowout_note"):
        report_parts.append(blowout["blowout_note"])
    if mk.get("multikill_note"):
        report_parts.append(mk["multikill_note"])
    if eco.get("eco_clutch_notes"):
        report_parts.append(eco["eco_clutch_notes"][0])
    if opp_strength.get("adjustment_note"):
        report_parts.append(opp_strength["adjustment_note"])
    if h2h_sample > 0:
        report_parts.append(str(h2h.get("h2h_summary", "")) + ".")
    if map_combo_note:
        report_parts.append(map_combo_note)

    return {
        "Team pros": team_pros[:5], "Team cons": team_cons[:5],
        "Opponent pros": opponent_pros[:4], "Opponent cons": opponent_cons[:4],
        "Player pros": player_pros[:6], "Player cons": player_cons[:6],
        "Player report": " ".join(report_parts).strip(),
        "H2H summary": h2h.get("h2h_summary", "N/A"),
        "Likely map combo note": map_combo_note or "N/A",
        "Analytics headline": f"{payload.get('Final grade', 'N/A')} • {payload.get('Thunderpick odds', 'N/A')} • {h2h.get('h2h_summary', 'No H2H')}",
        "Recommended side probability": f"{side_prob:.1f}%" if side_prob is not None else "N/A",
    }


# ─────────────────────────────────────────────────────────────────────
# Main payload builder (parallel fetch for speed)
# ─────────────────────────────────────────────────────────────────────

def _build_payload(player_name: str, line: float, opponent: str, kill_mode: bool = True) -> Dict[str, Any]:
    result = search_player(player_name)
    if not result:
        return {"error": f"Could not find {player_name} on HLTV."}

    pid, slug, display_slug = result
    profile = fetch_player_profile(pid, slug)
    display_name = profile.get("display_name") or display_slug

    start_30, end_30 = _today_range(30)
    start_90, end_90 = _today_range(H2H_WINDOW_DAYS)

    # Parallel: fetch stats + history simultaneously
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_recent = ex.submit(fetch_player_stats, pid, slug, start_30, end_30)
        f_alltime = ex.submit(fetch_player_stats, pid, slug, None, None)
        f_history = ex.submit(extract_history_rows, pid, slug)
        recent_stats = f_recent.result()
        all_time_stats = f_alltime.result()
        raw_rows = f_history.result()

    if not raw_rows:
        return {"error": "No HLTV match history found for this player."}

    hydrated_rows = hydrate_maps(raw_rows, slug, display_name)
    all_paired_rows = pair_recent_series(hydrated_rows, max_series=None)
    paired_rows = all_paired_rows[:MAX_RECENT_SERIES]

    fallback_used = False
    if paired_rows:
        kill_samples = [int(r["kills"]) for r in paired_rows]
        hs_samples = [int(r["headshots"]) for r in paired_rows]
        sample_rounds = [int(r["rounds"]) for r in paired_rows]
    else:
        fallback_used = True
        kill_samples = [int(r["kills"]) for r in hydrated_rows[:10]]
        hs_samples = [int(r["headshots"]) for r in hydrated_rows[:10]]
        sample_rounds = [int(r["rounds"]) for r in hydrated_rows[:10]]

    target_samples = kill_samples if kill_mode else hs_samples
    stats = _sample_stats(target_samples, line)

    if target_samples and sample_rounds:
        total_rounds = sum(sample_rounds); total_stat = sum(target_samples)
        rate_per_round = total_stat / total_rounds if total_rounds else 0.0
        projection = round(rate_per_round * median(sample_rounds), 1)
    else:
        total_rounds = total_stat = 0; projection = None

    recommendation = "NO BET"
    side_probability = None
    hit_rate = stats["hit_rate"]

    if (stats["avg"] is not None and stats["over_probability"] is not None
            and stats["under_probability"] is not None and hit_rate is not None):
        if stats["avg"] > line and stats["over_probability"] >= 55 and hit_rate >= 55:
            recommendation = "OVER"; side_probability = stats["over_probability"]
        elif stats["avg"] < line and stats["under_probability"] >= 55 and (100 - hit_rate) >= 55:
            recommendation = "UNDER"; side_probability = stats["under_probability"]
        else:
            side_probability = max(stats["over_probability"], stats["under_probability"])

    edge_pct = (side_probability - 50.0) if side_probability is not None else None
    side_hit_rate = hit_rate if recommendation == "OVER" else (100.0 - hit_rate if hit_rate is not None else 0.0)
    final_grade = _grade(abs(edge_pct or 0.0), side_hit_rate or 0.0)

    team_name = profile.get("team_name", "N/A")
    match_url = _find_profile_match_url(profile.get("match_links", []), opponent)
    if not match_url:
        opp_key = _slugify(opponent)
        for row in raw_rows[:20]:
            if opp_key in _slugify(str(row.get("opponent", ""))) and row.get("match_url"):
                match_url = row["match_url"]
                break

    match_context = fetch_match_context(match_url, team_name, opponent) if match_url else {}
    resolved_team = match_context.get("Resolved team", team_name)
    resolved_opponent = match_context.get("Resolved opponent", opponent.title() if opponent and opponent.upper() != "N/A" else "N/A")
    if match_context.get("Team ranking") in (None, "", "N/A"):
        match_context["Team ranking"] = profile.get("team_ranking", "N/A")

    opponent_rank_int = None
    try:
        opp_rank_raw = match_context.get("Opponent ranking", "")
        if opp_rank_raw not in (None, "", "N/A"):
            opponent_rank_int = int(str(opp_rank_raw).replace("#", ""))
    except Exception:
        pass

    player_rank_int = None
    try:
        pl_rank_raw = match_context.get("Team ranking", "")
        if pl_rank_raw not in (None, "", "N/A"):
            player_rank_int = int(str(pl_rank_raw).replace("#", ""))
    except Exception:
        pass

    # Merge buckets from all sources
    buckets = dict(profile.get("profile_buckets") or {})
    for label in ATTR_BUCKET_KEYS:
        if buckets.get(label) in (None, "N/A", ""):
            val = recent_stats.get(label) or all_time_stats.get(label)
            if val and val != "N/A":
                buckets[label] = val

    role, role_note = _profile_bucket_role(buckets)

    merged_stats = dict(recent_stats)
    for key in ATTR_BUCKET_KEYS:
        if merged_stats.get(key) in (None, "", "N/A"):
            merged_stats[key] = buckets.get(key, "N/A")
    for key in list(merged_stats.keys()):
        if merged_stats.get(key) in (None, "", "N/A"):
            at_val = all_time_stats.get(key)
            if at_val and at_val != "N/A":
                merged_stats[key] = at_val

    similar_teams, similar_bucket_rating = _choose_similar_bucket(opponent_rank_int, merged_stats)

    total_kill_sample = sum(kill_samples) if kill_samples else 0
    total_hs_sample = sum(hs_samples) if hs_samples else 0
    recent_hs_pct = (total_hs_sample / total_kill_sample * 100.0) if total_kill_sample > 0 else None

    rating_3_val = "N/A"
    for rv in [recent_stats.get("Rating 3.0 recent"), all_time_stats.get("Rating 3.0 recent"), profile.get("rating_3")]:
        if rv and rv != "N/A":
            rating_3_val = rv
            break

    # ── Advanced modeling ──
    likely_maps_dict = match_context.get("Likely maps", {}) or {}
    likely_map_names = _extract_map_names_from_text(" ".join(str(v) for v in likely_maps_dict.values()))
    if len(likely_map_names) < 2:
        # Fall back to most picked maps from per-map data
        per_map_avgs = build_per_map_averages(hydrated_rows)
        likely_map_names = sorted(per_map_avgs, key=lambda m: per_map_avgs[m].get("sample_size", 0), reverse=True)[:2]

    rank_diff = None
    if player_rank_int and opponent_rank_int:
        rank_diff = player_rank_int - opponent_rank_int

    kpr_float = _safe_float(merged_stats.get("KPR") or all_time_stats.get("KPR"))

    map_weighted = compute_map_weighted_kpr(hydrated_rows, likely_map_names)
    pace_model = compute_pace_model(paired_rows, likely_map_names, line, kpr=kpr_float or map_weighted.get("weighted_kpr"))
    blowout_analysis = compute_blowout_impact(paired_rows, likely_map_names, line, kpr=kpr_float)
    ot_analysis = compute_overtime_probability(likely_map_names, rank_diff=rank_diff)
    mk_analysis = compute_multikill_pressure(hydrated_rows, paired_rows)
    eco_clutch = compute_eco_and_clutch(hydrated_rows, paired_rows, buckets)
    opp_strength = compute_opponent_strength_adjustment(paired_rows, opponent_rank_int, merged_stats)

    per_map_avgs = build_per_map_averages(hydrated_rows)

    payload = {
        "Player": display_name, "Opponent": resolved_opponent,
        "Team": resolved_team, "Prop Line": f"{line} {'Kills' if kill_mode else 'Headshots'}",
        "Bet recommendation": recommendation, "Final grade": final_grade,
        "Mispriced or not": "YES" if (edge_pct is not None and abs(edge_pct) >= 5) else "NO",
        "Recent average": round(stats["avg"], 2) if stats["avg"] is not None else "N/A",
        "Recent median": round(stats["median"], 1) if stats["median"] is not None else "N/A",
        "Recent projection": projection or "N/A", "Projected kills": projection or "N/A",
        "Projected headshots": projection or "N/A",
        "Hit rate": f"{hit_rate:.1f}%" if hit_rate is not None else "N/A",
        "25th percentile": stats["q25"], "75th percentile": stats["q75"],
        "Over probability": f"{stats['over_probability']:.1f}%" if stats["over_probability"] is not None else "N/A",
        "Under probability": f"{stats['under_probability']:.1f}%" if stats["under_probability"] is not None else "N/A",
        "Edge vs line": f"{edge_pct:.1f}%" if edge_pct is not None else "N/A",
        "Simulated mean": round(stats["sim_mean"], 2) if stats["sim_mean"] is not None else "N/A",
        "Simulated median": round(stats["sim_median"], 2) if stats["sim_median"] is not None else "N/A",
        "Std Dev": round(stats["std_dev"], 2) if stats["std_dev"] is not None else "N/A",
        "Rating 3.0": rating_3_val, "Role": role, "Role note": role_note,
        "Recent form": _recent_form_string(paired_rows if paired_rows else []),
        "Exact round note": "First 2 maps per series (exact HLTV sample)." if not fallback_used else "Fallback to exact map sample.",
        # Attribute buckets — numeric values preserved
        "Firepower": buckets.get("Firepower", "N/A"), "Entrying": buckets.get("Entrying", "N/A"),
        "Trading": buckets.get("Trading", "N/A"), "Opening": buckets.get("Opening", "N/A"),
        "Clutching": buckets.get("Clutching", "N/A"), "Sniping": buckets.get("Sniping", "N/A"),
        "Utility": buckets.get("Utility", "N/A"),
        "KPR": merged_stats.get("KPR") or all_time_stats.get("KPR", "N/A"),
        "DPR": merged_stats.get("DPR") or all_time_stats.get("DPR", "N/A"),
        "ADR": merged_stats.get("ADR") or all_time_stats.get("ADR", "N/A"),
        "KAST": merged_stats.get("KAST") or all_time_stats.get("KAST", "N/A"),
        "Impact": merged_stats.get("Impact") or all_time_stats.get("Impact", "N/A"),
        "Round swing": merged_stats.get("Round swing") or all_time_stats.get("Round swing", "N/A"),
        "HS %": merged_stats.get("HS %") or all_time_stats.get("HS %", "N/A"),
        "Opening kills per round": merged_stats.get("Opening kills per round") or all_time_stats.get("Opening kills per round", "N/A"),
        "Trade kills per round": merged_stats.get("Trade kills per round") or all_time_stats.get("Trade kills per round", "N/A"),
        "Vs Top 5 rating": recent_stats.get("Vs Top 5 rating") or all_time_stats.get("Vs Top 5 rating", "N/A"),
        "Vs Top 10 rating": recent_stats.get("Vs Top 10 rating") or all_time_stats.get("Vs Top 10 rating", "N/A"),
        "Vs Top 20 rating": recent_stats.get("Vs Top 20 rating") or all_time_stats.get("Vs Top 20 rating", "N/A"),
        "Vs Top 30 rating": recent_stats.get("Vs Top 30 rating") or all_time_stats.get("Vs Top 30 rating", "N/A"),
        "Vs Top 50 rating": recent_stats.get("Vs Top 50 rating") or all_time_stats.get("Vs Top 50 rating", "N/A"),
        "Similar teams": similar_teams, "Similar teams rating": similar_bucket_rating,
        "Team ranking": match_context.get("Team ranking", profile.get("team_ranking", "N/A")),
        "Opponent ranking": match_context.get("Opponent ranking", "N/A"),
        "Match odds": match_context.get("Match odds", "N/A"),
        "Thunderpick odds": match_context.get("Thunderpick odds", match_context.get("Match odds", "N/A")),
        "Public pick": match_context.get("Public pick", "N/A"),
        "Veto": match_context.get("Veto", []), "Likely maps": likely_maps_dict,
        "Likely maps source": match_context.get("Likely maps source", "N/A"),
        "Veto notes": match_context.get("Veto notes", []),
        "H2H Data": _h2h_payload(all_paired_rows, resolved_opponent),
        "Scenarios": _build_scenarios(paired_rows, sum(kill_samples), sum(sample_rounds)) if paired_rows else {},
        "Recent Totals (M1+M2 Combined)": kill_samples,
        "Recent HS Totals (M1+M2)": hs_samples,
        "Recent kills": kill_samples, "Recent headshots": hs_samples,
        "Recent HS %": f"{recent_hs_pct:.1f}%" if recent_hs_pct is not None else "N/A",
        "Recent HS Average": round(mean(hs_samples), 2) if hs_samples else "N/A",
        "Recent HS Median": round(median(hs_samples), 1) if hs_samples else "N/A",
        "All-time profile HS %": all_time_stats.get("HS %") or recent_stats.get("HS %", "N/A"),
        "Paired series rows": paired_rows, "All paired series rows": all_paired_rows,
        "Raw maps": hydrated_rows, "Per-map averages": per_map_avgs,
        "Sample": f"{len(paired_rows)} series" if paired_rows else f"{len(hydrated_rows[:10])} maps (fallback)",
        "Sample note": "Exact series sample" if not fallback_used else "Fallback to exact map sample",
        "Recent stat window": f"{start_30} to {end_30}", "H2H window": f"{start_90} to {end_90}",
        # Advanced model outputs
        "Map weighted KPR": map_weighted,
        "Pace model": pace_model,
        "Blowout analysis": blowout_analysis,
        "Overtime analysis": ot_analysis,
        "Multikill analysis": mk_analysis,
        "Eco clutch analysis": eco_clutch,
        "Opponent strength": opp_strength,
        "Likely map names": likely_map_names,
    }

    payload.update(build_payload_analytics(payload, line=line, kill_mode=kill_mode))
    return payload


def get_player_info(player_name: str, line: float = 0.0, opponent: str = "N/A") -> Dict[str, Any]:
    try:
        return _build_payload(player_name=player_name, line=float(line), opponent=opponent, kill_mode=True)
    except Exception as exc:
        print(f"CRITICAL FAILURE in get_player_info: {exc}")
        import traceback; traceback.print_exc()
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
        import traceback; traceback.print_exc()
        return {"error": str(exc)}


# ─────────────────────────────────────────────────────────────────────
# CS2DataExtractor (grade command — Selenium-based)
# ─────────────────────────────────────────────────────────────────────

import urllib.parse

class CS2DataExtractor:
    def __init__(self):
        try:
            import undetected_chromedriver as uc
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.common.exceptions import TimeoutException, WebDriverException
        except ImportError as e:
            raise ImportError(f"Requires undetected-chromedriver and selenium: {e}")

        self._By = By; self._WebDriverWait = WebDriverWait
        self._EC = EC; self._TimeoutException = TimeoutException
        self._WebDriverException = WebDriverException

        print("Initializing stealth browser...")
        options = uc.ChromeOptions()
        options.add_argument("--headless"); options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox"); options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        try:
            self.driver = uc.Chrome(options=options)
            self.base_url = "https://www.hltv.org"
            self.wait = self._WebDriverWait(self.driver, 12)
            print("Stealth browser ready.")
        except Exception as e:
            print(f"WebDriver init failed: {e}"); raise

    def _sanitize_metric(self, value_str):
        if not value_str or str(value_str).strip() in ["N/A", "-", "", "null"]:
            return 0.0
        try:
            return float(str(value_str).replace("%", "").strip())
        except ValueError:
            return 0.0

    def resolve_player_entity(self, player_name):
        print(f"Resolving: {player_name}")
        search_url = f"{self.base_url}/search?query={urllib.parse.quote(player_name)}"
        try:
            self.driver.get(search_url)
            self.wait.until(self._EC.presence_of_element_located((self._By.CLASS_NAME, "table")))
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            for profile in soup.find_all("a", href=re.compile(r"/player/\d+/")):
                if player_name.lower() in profile.text.strip().lower():
                    url = self.base_url + profile["href"]
                    print(f"Resolved: {url}"); return url
            print(f"Not found: {player_name}"); return None
        except self._TimeoutException:
            print(f"Timeout for {player_name}"); return None
        except self._WebDriverException as e:
            print(f"WebDriver error: {e}"); return None

    def extract_player_statistics(self, profile_url):
        if not profile_url:
            return None
        try:
            self.driver.get(profile_url)
            time.sleep(2.0)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            stats = {
                "name": "Unknown", "kast_percent": 0.0, "multi_kill_percent": 0.0,
                "rating_3": 0.0, "impact_rating": 0.0, "opponent_rank_modifier": "N/A",
                "attributes": {"firepower": 0, "entrying": 0, "trading": 0, "opening": 0, "clutching": 0, "sniping": 0, "utility": 0},
            }
            name_node = soup.find("h1", class_="playerNickname")
            if name_node:
                stats["name"] = name_node.text.strip()
            for row in soup.find_all("div", class_="summaryStatBreakdownRow"):
                label = row.find("div", class_="summaryStatBreakdownDataLabel")
                value = row.find("div", class_="summaryStatBreakdownDataValue")
                if label and value:
                    lbl = label.text.strip().upper()
                    val = value.text.strip()
                    if "KAST" in lbl:
                        stats["kast_percent"] = self._sanitize_metric(val)
                    elif "RATING" in lbl:
                        stats["rating_3"] = self._sanitize_metric(val)
                    elif "IMPACT" in lbl:
                        stats["impact_rating"] = self._sanitize_metric(val)
            mk_node = soup.find(string=re.compile("Multi-kill", re.I))
            if mk_node:
                parent_div = mk_node.find_parent("div", class_="stat")
                if parent_div:
                    mk_val = parent_div.find("span", class_="value")
                    if mk_val:
                        stats["multi_kill_percent"] = self._sanitize_metric(mk_val.text)
            for attr in ["Firepower", "Entrying", "Trading", "Opening", "Clutching", "Sniping", "Utility"]:
                attr_node = soup.find(string=re.compile(attr, re.I))
                if attr_node:
                    score_parent = attr_node.find_parent("div")
                    if score_parent:
                        m = re.search(r"(\d{1,3})/100", score_parent.text)
                        if m:
                            stats["attributes"][attr.lower()] = int(m.group(1))
            return stats
        except Exception as e:
            print(f"Extraction failed for {profile_url}: {e}"); return None

    def close(self):
        try:
            self.driver.quit(); print("Browser closed.")
        except Exception:
            pass
