import os
import re
import time
import math
import functools
from datetime import date, timedelta
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
            "team_ranking": "N/A",
            "rating_3": "N/A",
            "profile_buckets": {},
            "match_links": [],
        }

    lines = _lines_from_soup(soup)

    display_name = slug
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            display_name = _norm(line.replace("# ", "", 1))
            break

    team_name = "N/A"
    marker = soup.find(string=re.compile(r"Current team", re.I))
    if marker is not None:
        try:
            team_link = marker.parent.find_next("a", href=re.compile(r"/team/"))
        except Exception:
            team_link = None
        if team_link is not None:
            txt = _norm(team_link.get_text(" ", strip=True))
            if txt:
                team_name = txt

    current_rank = _value_after(lines, "Current ranking", r"#?\d+", lookahead=4)
    rating_3 = _value_after(lines, "Rating 3.0", r"\d+\.\d+", lookahead=4) or "N/A"

    buckets = {
        "Firepower": _value_after(lines, "Firepower", r"\d{1,3}/100", lookahead=5) or "N/A",
        "Entrying": _value_after(lines, "Entrying", r"\d{1,3}/100", lookahead=5) or "N/A",
        "Trading": _value_after(lines, "Trading", r"\d{1,3}/100", lookahead=5) or "N/A",
        "Opening": _value_after(lines, "Opening", r"\d{1,3}/100", lookahead=5) or "N/A",
        "Clutching": _value_after(lines, "Clutching", r"\d{1,3}/100", lookahead=5) or "N/A",
        "Sniping": _value_after(lines, "Sniping", r"\d{1,3}/100", lookahead=5) or "N/A",
        "Utility": _value_after(lines, "Utility", r"\d{1,3}/100", lookahead=5) or "N/A",
    }

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
        if len(match_links) >= 12:
            break

    return {
        "display_name": display_name,
        "team_name": team_name,
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
        return {}

    lines = _lines_from_soup(soup)
    text = "\n".join(lines)
    stats: Dict[str, str] = {}

    stats["Rating 2.0"] = _value_before(lines, "Rating 2.0", r"\d+\.\d+", lookback=4) or "N/A"
    stats["Rating 3.0 recent"] = _value_before(lines, "Rating 3.0", r"\d+\.\d+", lookback=4) or "N/A"
    stats["Round swing"] = _value_before(lines, "Round swing", r"[+-]?\d+\.\d+%", lookback=4) or "N/A"
    stats["KAST"] = _value_before(lines, "KAST", r"\d+\.\d+%", lookback=4) or "N/A"
    stats["ADR"] = _value_before(lines, "ADR", r"\d+\.\d+", lookback=4) or "N/A"
    stats["KPR"] = _value_before(lines, "KPR", r"\d+\.\d+", lookback=4) or "N/A"
    stats["DPR"] = _value_before(lines, "DPR", r"\d+\.\d+", lookback=4) or "N/A"

    if stats["Round swing"] == "N/A":
        m = re.search(r"([+-]?\d+\.\d+%)\s+Round swing", text, flags=re.I)
        if m:
            stats["Round swing"] = m.group(1)

    stats["HS %"] = _value_after(lines, "Headshot %", r"\d+(?:\.\d+)?%", lookahead=2) or "N/A"
    stats["Impact"] = _value_after(lines, "Impact rating", r"\d+\.\d+", lookahead=3) or "N/A"
    stats["Opening kills per round"] = _value_after(lines, "Opening kills per round", r"\d+\.\d+", lookahead=3) or "N/A"
    stats["Trade kills per round"] = _value_after(lines, "Trade kills per round", r"\d+\.\d+", lookahead=3) or "N/A"
    stats["Maps played"] = _value_after(lines, "Maps played", r"[\d,]+", lookahead=2) or "N/A"
    stats["Rounds played"] = _value_after(lines, "Rounds played", r"[\d,]+", lookahead=2) or "N/A"

    for label in ("Firepower", "Entrying", "Trading", "Opening", "Clutching", "Sniping", "Utility"):
        stats[label] = _value_after(lines, label, r"\d{1,3}/100", lookahead=4) or "N/A"

    for bucket in (5, 10, 20, 30, 50):
        label = f"vs top {bucket} opponents"
        stats[f"Vs Top {bucket} rating"] = _value_after(lines, label, r"-|\d+\.\d+", lookahead=8) or "N/A"

    return stats


def extract_history_rows(pid: str, slug: str) -> List[Dict[str, Any]]:
    soup, _, _ = _get_soup(f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}", render=False)
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

        links = tr.find_all("a", href=True)
        team_names: List[str] = []
        mapstats_url = ""
        match_url = ""
        for a in links:
            href = a.get("href", "")
            txt = _norm(a.get_text(" ", strip=True))
            if "/stats/matches/mapstatsid/" in href and not mapstats_url:
                mapstats_url = _abs_url(href)
            elif "/matches/" in href and not match_url:
                match_url = _abs_url(href)
            elif "/team/" in href and txt and txt not in team_names:
                team_names.append(txt)

        score_bits = re.findall(r"\((\d+)\)", row_text)
        rounds_played = 24
        if len(score_bits) >= 2:
            try:
                rounds_played = int(score_bits[0]) + int(score_bits[1])
            except Exception:
                pass

        rating_match = re.findall(r"\b(\d+\.\d+)\b", row_text)
        rating = rating_match[-1] if rating_match else "N/A"

        rows.append({
            "date": date_match.group(1),
            "team": team_names[0] if team_names else "N/A",
            "opponent": team_names[1] if len(team_names) > 1 else "UNK",
            "map_name": MAP_ALIASES.get(map_match.group(1).lower(), map_match.group(1).lower()),
            "kills": int(kd_match.group(1)),
            "deaths": int(kd_match.group(2)),
            "rating": rating,
            "rounds": rounds_played,
            "mapstats_url": mapstats_url,
            "match_url": match_url,
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


def pair_recent_series(rows: List[Dict[str, Any]], max_series: int = MAX_RECENT_SERIES) -> List[Dict[str, Any]]:
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
        chrono_maps = list(reversed(grp["maps"]))  # HLTV history is reverse chronological within a series
        if len(chrono_maps) < 2:
            continue

        first_two = chrono_maps[:2]
        paired.append({
            "date": first_two[0].get("date", "N/A"),
            "team": first_two[0].get("team", "N/A"),
            "opponent": first_two[0].get("opponent", "UNK"),
            "map1": first_two[0].get("map_name", "N/A"),
            "map2": first_two[1].get("map_name", "N/A"),
            "kills": int(first_two[0].get("kills", 0)) + int(first_two[1].get("kills", 0)),
            "deaths": int(first_two[0].get("deaths", 0)) + int(first_two[1].get("deaths", 0)),
            "headshots": int(first_two[0].get("headshots", 0)) + int(first_two[1].get("headshots", 0)),
            "rounds": int(first_two[0].get("rounds", 0)) + int(first_two[1].get("rounds", 0)),
            "rating_avg": round(mean([
                _safe_float(first_two[0].get("rating")) or 0.0,
                _safe_float(first_two[1].get("rating")) or 0.0,
            ]), 2),
            "maps_in_series": len(chrono_maps),
            "raw_maps": first_two,
        })
        if len(paired) >= max_series:
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


def _h2h_payload(series_rows: List[Dict[str, Any]], opponent: str) -> Dict[str, Any]:
    opp_key = _slugify(opponent)
    if not opp_key:
        return {}
    relevant = [row for row in series_rows if _slugify(str(row.get("opponent", ""))) == opp_key]
    if not relevant:
        return {"h2h_sample_size": 0, "h2h_avg_kills": "N/A", "h2h_avg_headshots": "N/A"}
    return {
        "h2h_sample_size": len(relevant),
        "h2h_avg_kills": round(mean(int(x.get("kills", 0)) for x in relevant), 2),
        "h2h_avg_headshots": round(mean(int(x.get("headshots", 0)) for x in relevant), 2),
    }


def _find_profile_match_url(match_links: List[Tuple[str, str]], opponent: str) -> Optional[str]:
    opp_key = _slugify(opponent)
    for text, url in match_links:
        if opp_key and opp_key in _slugify(text):
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
    veto = [line for line in lines if re.match(r"\d+\.\s", line)]
    likely: Dict[str, str] = {}
    picks = []
    decider = None

    for line in veto:
        pm = re.match(r"\d+\.\s+(.+?)\s+picked\s+(.+)", line, flags=re.I)
        if pm:
            picks.append(_norm(pm.group(2)))
        dm = re.match(r"\d+\.\s+(.+?)\s+was left over", line, flags=re.I)
        if dm:
            decider = _norm(dm.group(1))

    if picks:
        if len(picks) >= 1:
            likely["Map 1"] = picks[0]
        if len(picks) >= 2:
            likely["Map 2"] = picks[1]
    if decider:
        likely["Decider"] = decider

    return veto, likely


def _extract_decimal_odds_from_html(html: str, teams: List[str]) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    if not html:
        return None, None, None

    patterns = [
        r'"team1Odds"\s*:\s*"?([0-9]+\.[0-9]+)"?.{0,200}?"team2Odds"\s*:\s*"?([0-9]+\.[0-9]+)"?',
        r'"homeOdds"\s*:\s*"?([0-9]+\.[0-9]+)"?.{0,200}?"awayOdds"\s*:\s*"?([0-9]+\.[0-9]+)"?',
        r'data-team1-odds="([0-9]+\.[0-9]+)".{0,200}?data-team2-odds="([0-9]+\.[0-9]+)"',
        r'data-odds1="([0-9]+\.[0-9]+)".{0,200}?data-odds2="([0-9]+\.[0-9]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.I | re.S)
        if m:
            return float(m.group(1)), float(m.group(2)), "html"

    if len(teams) >= 2:
        m = re.search(
            rf"{re.escape(teams[0])}.{{0,120}}?([0-9]+\.[0-9]+).{{0,120}}?{re.escape(teams[1])}.{{0,120}}?([0-9]+\.[0-9]+)",
            html,
            flags=re.I | re.S,
        )
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
    teams = _team_names_from_match_soup(soup)
    veto, likely_maps = _extract_veto_and_maps(lines)

    player_rank = _extract_team_rank_from_lines(lines, player_team)
    opponent_rank = _extract_team_rank_from_lines(lines, opponent)

    public_pick = _extract_pick_percentages(lines, teams)
    odds_a, odds_b, odds_source = _extract_decimal_odds_from_html(html or "", teams)

    analytics_url = _analytics_url_from_match(match_url)
    if analytics_url:
        analytics_soup, _, analytics_html = _get_soup(analytics_url, render=True)
        if not analytics_soup:
            analytics_soup, _, analytics_html = _get_soup(analytics_url, render=False)
        analytics_lines = _lines_from_soup(analytics_soup) if analytics_soup else []

        if analytics_lines:
            player_rank = player_rank or _extract_team_rank_from_lines(analytics_lines, player_team)
            opponent_rank = opponent_rank or _extract_team_rank_from_lines(analytics_lines, opponent)
        if (odds_a is None or odds_b is None) and analytics_html:
            odds_a, odds_b, odds_source = _extract_decimal_odds_from_html(analytics_html, teams)

    odds_display = "N/A"
    moneyline = None
    moneyline_american = "N/A"

    if odds_a and odds_b and len(teams) >= 2:
        odds_display = f"{teams[0]} {odds_a:.2f} | {teams[1]} {odds_b:.2f}"
        if _slugify(player_team) == _slugify(teams[0]):
            moneyline = odds_a
        elif _slugify(player_team) == _slugify(teams[1]):
            moneyline = odds_b
        if moneyline:
            moneyline_american = _decimal_to_american(moneyline)

    return {
        "Match URL": match_url,
        "Veto": veto,
        "Likely maps": likely_maps,
        "Team ranking": _fmt_rank(player_rank),
        "Opponent ranking": _fmt_rank(opponent_rank),
        "Match odds": odds_display,
        "Moneyline": f"{moneyline:.2f}" if moneyline else "N/A",
        "Moneyline american": moneyline_american,
        "Public pick": public_pick or "N/A",
        "Odds source": odds_source or "N/A",
    }


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
    recent_stats = fetch_player_stats(pid, slug, start_date=start_30, end_date=end_30)
    all_time_stats = fetch_player_stats(pid, slug)

    raw_rows = extract_history_rows(pid, slug)
    if not raw_rows:
        return {"error": "No HLTV match history was found for this player."}

    hydrated_rows = hydrate_maps(raw_rows, slug, display_name)
    paired_rows = pair_recent_series(hydrated_rows, max_series=MAX_RECENT_SERIES)

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

    payload = {
        "Player": display_name,
        "Opponent": opponent.title() if opponent and opponent.upper() != "N/A" else "N/A",
        "Team": team_name,
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
        "Round swing": recent_stats.get("Round swing", "N/A"),
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
        "Moneyline": match_context.get("Moneyline", "N/A"),
        "Moneyline american": match_context.get("Moneyline american", "N/A"),
        "Public pick": match_context.get("Public pick", "N/A"),
        "Veto": match_context.get("Veto", []),
        "Likely maps": match_context.get("Likely maps", {}),
        "H2H Data": _h2h_payload(paired_rows, opponent),
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
        "Raw maps": hydrated_rows,
        "Per-map averages": build_per_map_averages(hydrated_rows),
        "Sample": f"{len(paired_rows)} series" if paired_rows else f"{len(hydrated_rows[:10])} maps (fallback)",
        "Sample note": "Exact series sample" if not fallback_used else "Fallback to exact map sample",
        "Recent stat window": f"{start_30} to {end_30}",
    }

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
