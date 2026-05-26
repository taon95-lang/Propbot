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
# HLTV SCRAPER ENGINE - AUDIT-ALIGNED
# ==========================================

HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")

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
    "cache": "cache",
    "train": "train",
    "tuscan": "tuscan",
    "season": "season",
    "cobblestone": "cobblestone",
}

FETCH_CACHE: Dict[Tuple[str, bool], Tuple[Optional[str], Optional[str]]] = {}


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


def _as_float(value: Any) -> Optional[float]:
    try:
        text = str(value).replace("%", "").replace("+", "").strip()
        if text.upper() == "N/A" or not text:
            return None
        return float(text)
    except Exception:
        return None


def _fmt_percent(value: Optional[float], digits: int = 1) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}%"


def _fmt_number(value: Optional[float], digits: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def _decimal_to_american(decimal_odds: Optional[float]) -> str:
    if decimal_odds is None or decimal_odds <= 1:
        return "N/A"
    if decimal_odds >= 2:
        return f"+{int(round((decimal_odds - 1) * 100))}"
    return f"-{int(round(100 / (decimal_odds - 1)))}"


def _fetch(url: str, render: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """Fetch URL with ScraperAPI and preserve a small in-process cache."""
    cache_key = (url, render)
    if cache_key in FETCH_CACHE:
        return FETCH_CACHE[cache_key]

    if not SCRAPERAPI_KEY:
        print("CRITICAL: SCRAPERAPI_KEY environment variable is missing.")
        return None, None

    for attempt in range(3):
        use_render = render if attempt == 0 else (not render if attempt == 1 else True)
        render_param = "&render=true" if use_render else ""
        proxy_url = (
            "http://api.scraperapi.com"
            f"?api_key={SCRAPERAPI_KEY}"
            f"&url={url}"
            f"{render_param}"
            "&country_code=us"
        )
        try:
            print(f"FETCH ATTEMPT {attempt + 1}/3: {url} (JS_Render={use_render})")
            response = requests.get(proxy_url, timeout=60)
            if response.status_code == 200 and len(response.text) > 1000:
                final_url = response.headers.get("Sa-Final-Url", url)
                FETCH_CACHE[cache_key] = (response.text, final_url)
                return response.text, final_url
            print(
                f"ATTEMPT {attempt + 1} FAILED: "
                f"Status code {response.status_code}, Length: {len(response.text)}"
            )
            time.sleep(2)
        except Exception as exc:
            print(f"ATTEMPT {attempt + 1} EXCEPTION: {exc}")
            time.sleep(2)

    FETCH_CACHE[cache_key] = (None, None)
    return None, None


def _get_soup(url: str, render: bool = False) -> Tuple[Optional[BeautifulSoup], Optional[str]]:
    html, final_url = _fetch(url, render=render)
    if not html:
        return None, final_url
    return BeautifulSoup(html, "html.parser"), final_url


def search_player(name: str):
    """Search for player on HLTV by name."""
    name_clean = name.lower().strip()
    static = {
        "donk": ("21167", "donk"), "zywoo": ("11893", "zywoo"),
        "m0nesy": ("19230", "m0nesy"), "niko": ("3741", "niko"),
        "jl": ("19206", "jl"), "xertion": ("20312", "xertion"),
        "jamyoung": ("19645", "jamyoung"), "h4san4tor": ("22189", "h4san4tor"),
        "brooxsy": ("21971", "brooxsy"), "djoko": ("7175", "djoko"),
        "flouzer": ("20928", "flouzer"), "myltsi": ("20928", "myltsi"),
        "pointer": ("26666", "pointer"), "caleyy": ("27093", "caleyy"),
        "eraa": ("25677", "eraa"), "tomate": ("27410", "tomate"),
        "avid": ("25488", "avid"), "marix": ("26544", "marix"),
        "keoz": ("25673", "keoz"), "forsyy": ("20445", "forsyy"),
        "glowiing": ("21968", "glowiing"), "kaide": ("22052", "kaide"),
        "matys": ("27032", "matys"), "yawara": ("27091", "yawara")
    }
    if name_clean in static:
        print(f" STATIC LOOKUP: {name_clean} → ID {static[name_clean][0]}")
        pid, slug = static[name_clean]
        return pid, slug, slug.replace("-", " ").title()

    print(f" SEARCHING HLTV FOR PLAYER: {name_clean}")
    html, final_url = _fetch(f"{HLTV_BASE}/search?query={name_clean}", render=True)
    if not html:
        print(" PLAYER SEARCH FAILED: No HTML returned")
        return None

    if final_url and "/player/" in final_url:
        match = re.search(r"/player/(\d+)/([^/]+)", final_url)
        if match:
            pid, slug = match.group(1), match.group(2)
            return pid, slug, slug.replace("-", " ").title()

    soup = BeautifulSoup(html, "html.parser")
    found_links = []
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        match = re.search(r"/player/(\d+)/([a-zA-Z0-9_-]+)", href)
        if match:
            pid, slug = match.group(1), match.group(2)
            if not any(item[0] == pid for item in found_links):
                found_links.append((pid, slug))

    if found_links:
        for pid, slug in found_links:
            if name_clean == slug.lower() or name_clean in slug.lower():
                return pid, slug, slug.replace("-", " ").title()
        pid, slug = found_links[0]
        return pid, slug, slug.replace("-", " ").title()

    print(" NO PLAYER LINKS FOUND")
    return None


def search_team(name: str):
    """Best-effort team search on HLTV."""
    name_clean = name.lower().strip()
    print(f" SEARCHING HLTV FOR TEAM: {name_clean}")
    html, final_url = _fetch(f"{HLTV_BASE}/search?query={name_clean}", render=True)
    if not html:
        return None

    if final_url and "/team/" in final_url:
        match = re.search(r"/team/(\d+)/([^/?#]+)", final_url)
        if match:
            return match.group(1), match.group(2), match.group(2).replace("-", " ").title()

    soup = BeautifulSoup(html, "html.parser")
    found_links = []
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        match = re.search(r"/team/(\d+)/([a-zA-Z0-9_-]+)", href)
        if match:
            team_id, slug = match.group(1), match.group(2)
            if not any(item[0] == team_id for item in found_links):
                found_links.append((team_id, slug))

    if found_links:
        for team_id, slug in found_links:
            team_name = slug.replace("-", " ").lower()
            if name_clean == team_name or name_clean in team_name or team_name in name_clean:
                return team_id, slug, slug.replace("-", " ").title()
        team_id, slug = found_links[0]
        return team_id, slug, slug.replace("-", " ").title()

    return None


def _line_value(
    lines: List[str],
    label: str,
    pattern: str,
    prefer: str = "next",
    window: int = 6,
) -> Optional[str]:
    label_lower = label.lower()
    indices = [index for index, line in enumerate(lines) if line.lower() == label_lower]
    if not indices:
        return None
    for index in indices:
        if prefer == "prev":
            candidates = range(index - 1, max(-1, index - window - 1), -1)
        else:
            candidates = range(index + 1, min(len(lines), index + window + 1))
        for candidate in candidates:
            if re.fullmatch(pattern, lines[candidate]):
                return lines[candidate]
    return None


def _regex_value(text: str, pattern: str) -> Optional[str]:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None


def _parse_profile_attributes(lines: List[str]) -> Dict[str, Optional[int]]:
    attributes = {}
    for label in ["Firepower", "Entrying", "Trading", "Opening", "Clutching", "Sniping", "Utility"]:
        raw = _line_value(lines, label, r"\d{1,3}/100", prefer="next", window=4)
        if raw is None:
            attributes[label] = None
        else:
            try:
                attributes[label] = int(raw.split("/")[0])
            except Exception:
                attributes[label] = None
    return attributes


def _derive_role_from_profile(attributes: Dict[str, Optional[int]]) -> Tuple[str, str]:
    """
    AUDIT FIX: derive roles dynamically from HLTV profile buckets instead of hardcoding
    labels from KPR/HS heuristics.
    """
    firepower = attributes.get("Firepower") or 0
    entrying = attributes.get("Entrying") or 0
    trading = attributes.get("Trading") or 0
    opening = attributes.get("Opening") or 0
    utility = attributes.get("Utility") or 0
    sniping = attributes.get("Sniping") or 0

    if sniping >= 85:
        return "Primary AWPer", "Derived from elite HLTV Sniping bucket."
    if entrying >= 70 and opening >= 70:
        return "Entry/Opener", "Derived from HLTV Entrying + Opening buckets."
    if firepower >= 80 and trading >= 60:
        return "Star Rifler", "Derived from HLTV Firepower + Trading buckets."
    if utility >= 75 and firepower <= 65:
        return "Support", "Derived from HLTV Utility bucket."
    if trading >= 65 and firepower >= 60:
        return "Flex Rifler", "Derived from HLTV Trading + Firepower buckets."
    return "Hybrid/Flex", "Derived from HLTV profile bucket mix."


def _extract_first_team_link(soup: BeautifulSoup) -> Tuple[str, str, str]:
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        match = re.search(r"/team/(\d+)/([a-zA-Z0-9_-]+)", href)
        text = _norm(link.get_text(" ", strip=True))
        if match and text:
            return match.group(1), match.group(2), text
    return "", "", "N/A"


def fetch_player_profile(pid: str, slug: str) -> Dict[str, Any]:
    profile_url = f"{HLTV_BASE}/player/{pid}/{slug}"
    soup, _ = _get_soup(profile_url, render=True)
    if not soup:
        return {
            "display_name": slug.replace("-", " ").title(),
            "team_id": "",
            "team_slug": "",
            "team_name": "N/A",
            "rating_3": "N/A",
            "attributes": {},
            "role": "N/A",
            "role_note": "N/A",
            "profile_url": profile_url,
            "profile_soup": None,
        }

    lines = _split_lines(soup)
    rating_3 = _line_value(lines, "Rating 3.0", r"\d+\.\d+", prefer="next", window=4)
    attributes = _parse_profile_attributes(lines)
    role, role_note = _derive_role_from_profile(attributes)
    team_id, team_slug, team_name = _extract_first_team_link(soup)
    display_name = slug.replace("-", " ").title()
    for h1 in soup.find_all(["h1", "h2"]):
        candidate = _norm(h1.get_text(" ", strip=True))
        if candidate and candidate.lower() not in {"upcoming & recent matches"}:
            display_name = candidate
            break

    return {
        "display_name": display_name,
        "team_id": team_id,
        "team_slug": team_slug,
        "team_name": team_name,
        "rating_3": rating_3 or "N/A",
        "attributes": attributes,
        "role": role,
        "role_note": role_note,
        "profile_url": profile_url,
        "profile_soup": soup,
    }


def fetch_player_stats(pid: str, slug: str) -> Dict[str, Any]:
    """
    AUDIT FIX: pull exact, visible HLTV numbers directly from the player stats page.
    No homemade Rating/Impact/Firepower/Open/Trading estimates.
    """
    stats_url = f"{HLTV_BASE}/stats/players/{pid}/{slug}"
    soup, _ = _get_soup(stats_url, render=True)
    if not soup:
        return {
            "KPR": "N/A",
            "DPR": "N/A",
            "ADR": "N/A",
            "KAST": "N/A",
            "Impact": "N/A",
            "HS %": "N/A",
            "Multi-kill %": "N/A",
            "Round Swing %": "N/A",
            "Opening kills per round": "N/A",
            "Trade kills per round": "N/A",
            "Vs Top 5 rating": "N/A",
            "Vs Top 10 rating": "N/A",
            "Vs Top 20 rating": "N/A",
            "Vs Top 30 rating": "N/A",
            "Vs Top 50 rating": "N/A",
            "Total kills": "N/A",
            "Rounds played": "N/A",
            "stats_url": stats_url,
        }

    lines = _split_lines(soup)
    text = "\n".join(lines)
    kpr = _regex_value(text, r"Kills / round\s+(\d+\.\d+)") or _line_value(lines, "KPR", r"\d+\.\d+", prefer="prev")
    dpr = _regex_value(text, r"Deaths / round\s+(\d+\.\d+)") or _line_value(lines, "DPR", r"\d+\.\d+", prefer="prev")
    adr = _regex_value(text, r"Damage / Round\s+(\d+\.\d+)") or _line_value(lines, "ADR", r"\d+\.\d+", prefer="prev")
    kast = _line_value(lines, "KAST", r"\d+\.\d+%", prefer="prev")
    impact = _regex_value(text, r"Impact rating\s+(\d+\.\d+)")
    hs_pct = _regex_value(text, r"Headshot %\s*([0-9.]+%)")
    multi_kill_pct = _regex_value(text, r"Rounds with a multi-kill\s+([0-9.]+%)")
    round_swing = _regex_value(text, r"Round swing\s+([+\-]?[0-9.]+%)")
    opening_kpr = _regex_value(text, r"Opening kills per round\s+(\d+\.\d+)")
    trade_kpr = _regex_value(text, r"Trade kills per round\s+(\d+\.\d+)")
    total_kills = _regex_value(text, r"Total kills\s+(\d+)")
    rounds_played = _regex_value(text, r"Rounds played\s+(\d+)")

    def versus_bucket(bucket: str) -> str:
        return _regex_value(text, rf"vs top {bucket} opponents\s+\(\d+ maps\)\s+(\d+\.\d+)") or "N/A"

    return {
        "KPR": kpr or "N/A",
        "DPR": dpr or "N/A",
        "ADR": adr or "N/A",
        "KAST": kast or "N/A",
        "Impact": impact or "N/A",
        "HS %": hs_pct or "N/A",
        "Multi-kill %": multi_kill_pct or "N/A",
        "Round Swing %": round_swing or "N/A",
        "Opening kills per round": opening_kpr or "N/A",
        "Trade kills per round": trade_kpr or "N/A",
        "Vs Top 5 rating": versus_bucket("5"),
        "Vs Top 10 rating": versus_bucket("10"),
        "Vs Top 20 rating": versus_bucket("20"),
        "Vs Top 30 rating": versus_bucket("30"),
        "Vs Top 50 rating": versus_bucket("50"),
        "Total kills": total_kills or "N/A",
        "Rounds played": rounds_played or "N/A",
        "stats_url": stats_url,
    }


def fetch_team_rank(team_name: str) -> Dict[str, str]:
    if not team_name or team_name == "N/A":
        return {"Team": "N/A", "Team ranking": "N/A"}
    team_search = search_team(team_name)
    if not team_search:
        return {"Team": team_name, "Team ranking": "N/A"}
    team_id, team_slug, display = team_search
    team_url = f"{HLTV_BASE}/team/{team_id}/{team_slug}"
    soup, _ = _get_soup(team_url, render=True)
    if not soup:
        return {"Team": display, "Team ranking": "N/A"}
    lines = _split_lines(soup)
    text = "\n".join(lines)
    ranking = (
        _regex_value(text, r"World ranking\s+#(\d+)")
        or _regex_value(text, r"current world rank\?\s+.+?ranked\s+#(\d+)")
        or _regex_value(text, r"Current ranking\s+#(\d+)")
    )
    if ranking:
        ranking = f"#{ranking}"
    elif "Unranked" in text:
        ranking = "Unranked"
    else:
        ranking = "N/A"
    return {
        "Team": display,
        "Team ranking": ranking,
        "team_id": team_id,
        "team_slug": team_slug,
        "team_url": team_url,
        "team_soup": soup,
    }


def _extract_row_map_url(row) -> str:
    for link in row.find_all("a", href=True):
        href = link.get("href", "")
        if "/stats/matches/mapstatsid/" in href:
            return _abs_url(href)
    return ""


def _extract_row_team_names(row) -> Tuple[str, str]:
    team_names = []
    for link in row.find_all("a", href=True):
        href = link.get("href", "")
        text = _norm(link.get_text(" ", strip=True))
        if "/stats/teams/" in href and text:
            team_names.append(text)
    if len(team_names) >= 2:
        return team_names[0], team_names[1]
    row_text = _norm(row.get_text(" ", strip=True))
    tokens = row_text.split()
    exact_vs = re.search(
        r"\d{2}/\d{2}/\d{2}\s+(.+?)\s+\(\d+\)\s+(.+?)\s+\(\d+\)\s+(?:anc|mrg|d2|inf|nuke|anb|vrt|ovp|ancient|mirage|dust2|inferno|anubis|vertigo|overpass)\b",
        row_text,
        flags=re.IGNORECASE,
    )
    if exact_vs:
        return _norm(exact_vs.group(1)), _norm(exact_vs.group(2))
    return "N/A", "N/A"


def _extract_row_scores(row_text: str) -> Tuple[Optional[int], Optional[int]]:
    numbers = [int(value) for value in re.findall(r"\((\d+)\)", row_text)]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    return None, None


def _extract_history_rows(pid: str, slug: str) -> List[Dict[str, Any]]:
    history_url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"
    soup, _ = _get_soup(history_url, render=True)
    if not soup:
        return []

    table = soup.find("table", {"class": "stats-table"}) or soup.find("table")
    if not table:
        return []

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")
    print(f" PROCESSING {len(rows)} HISTORY ROWS FROM HLTV...")

    history_rows = []
    for row in rows:
        row_text = _norm(row.get_text(" ", strip=True))
        if not row_text:
            continue

        date_match = re.search(r"\b\d{2}/\d{2}/\d{2}\b", row_text)
        kd_match = re.search(r"\b(\d+)\s*-\s*(\d+)\b", row_text)
        map_match = re.search(
            r"\b(anc|mrg|d2|inf|nuke|anb|vrt|ovp|ancient|mirage|dust2|inferno|anubis|vertigo|overpass)\b",
            row_text,
            flags=re.IGNORECASE,
        )

        if not (date_match and kd_match and map_match):
            continue

        team_name, opponent_name = _extract_row_team_names(row)
        team_score, opponent_score = _extract_row_scores(row_text)
        map_url = _extract_row_map_url(row)
        row_info = {
            "date": date_match.group(0),
            "team": team_name,
            "opponent": opponent_name,
            "team_score": team_score,
            "opponent_score": opponent_score,
            "rounds": (team_score + opponent_score) if team_score is not None and opponent_score is not None else None,
            "map_name": MAP_ALIASES.get(map_match.group(1).lower(), map_match.group(1).lower()),
            "kills": int(kd_match.group(1)),
            "deaths": int(kd_match.group(2)),
            "mapstats_url": map_url,
            "row_text": row_text,
        }
        history_rows.append(row_info)

    return history_rows


def _group_series(rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    if not rows:
        return []
    groups: List[List[Dict[str, Any]]] = []
    current_group = [rows[0]]
    for row in rows[1:]:
        same_series = (
            row.get("date") == current_group[0].get("date")
            and _norm(row.get("opponent")).lower() == _norm(current_group[0].get("opponent")).lower()
            and _norm(row.get("team")).lower() == _norm(current_group[0].get("team")).lower()
        )
        if same_series:
            current_group.append(row)
        else:
            groups.append(current_group)
            current_group = [row]
    if current_group:
        groups.append(current_group)
    return groups


def _parse_mapstats_headshots(mapstats_url: str, player_candidates: List[str]) -> Tuple[Optional[int], Optional[int]]:
    """
    AUDIT FIX: pull exact K(hs) from the mapstats page.
    No fallback HS = kills * HS%.
    """
    if not mapstats_url:
        return None, None
    soup, _ = _get_soup(mapstats_url, render=True)
    if not soup:
        return None, None

    lines = [line.lower() for line in _split_lines(soup)]
    original_lines = _split_lines(soup)
    for idx, line in enumerate(lines):
        if any(line == candidate or re.search(rf"\b{re.escape(candidate)}\b", line) for candidate in player_candidates):
            for look_ahead in range(1, 6):
                pointer = idx + look_ahead
                if pointer >= len(original_lines):
                    break
                match = re.search(r"(\d+)\s*\((\d+)\)", original_lines[pointer])
                if match:
                    return int(match.group(1)), int(match.group(2))

    for tr in soup.find_all("tr"):
        row_text = _norm(tr.get_text(" ", strip=True))
        lower_row = row_text.lower()
        if any(re.search(rf"\b{re.escape(candidate)}\b", lower_row) for candidate in player_candidates):
            match = re.search(r"(\d+)\s*\((\d+)\)", row_text)
            if match:
                return int(match.group(1)), int(match.group(2))

    return None, None


def _hydrate_exact_maps(
    series_groups: List[List[Dict[str, Any]]],
    player_slug: str,
    display_name: str,
    series_limit: int = 10,
) -> List[Dict[str, Any]]:
    all_maps: List[Dict[str, Any]] = []
    series_seen = 0
    player_candidates = [
        player_slug.lower(),
        display_name.lower(),
        display_name.replace("'", "").lower(),
    ]

    for group in series_groups:
        if series_seen >= series_limit:
            break
        if len(group) < 2:
            continue

        selected_rows = [group[-1], group[-2]]
        for row in selected_rows:
            exact_kills, exact_hs = _parse_mapstats_headshots(row.get("mapstats_url", ""), player_candidates)
            hydrated = dict(row)
            if exact_kills is not None:
                hydrated["kills"] = exact_kills
                hydrated["headshots"] = exact_hs
            if hydrated.get("rounds") is None:
                hydrated["rounds"] = "N/A"
            all_maps.append(hydrated)
        series_seen += 1

    return all_maps


def _series_rows_from_exact_maps(all_maps: List[Dict[str, Any]]) -> Tuple[List[int], List[int], List[Dict[str, Any]]]:
    final_series_totals: List[int] = []
    final_series_hs_totals: List[int] = []
    paired_series_rows: List[Dict[str, Any]] = []
    exact_groups = _group_series(all_maps)

    for group in exact_groups[:10]:
        if len(group) < 2:
            continue
        map1, map2 = group[0], group[1]
        if map1.get("headshots") is None or map2.get("headshots") is None:
            combined_hs = None
        else:
            combined_hs = int(map1["headshots"]) + int(map2["headshots"])

        rounds_1 = map1.get("rounds")
        rounds_2 = map2.get("rounds")
        combined_rounds = (
            int(rounds_1) + int(rounds_2)
            if isinstance(rounds_1, int) and isinstance(rounds_2, int)
            else "N/A"
        )
        combined_kills = int(map1["kills"]) + int(map2["kills"])
        final_series_totals.append(combined_kills)
        if combined_hs is not None:
            final_series_hs_totals.append(combined_hs)

        paired_series_rows.append(
            {
                "opponent": _norm(map1.get("opponent", "N/A")).upper(),
                "date": map1.get("date", "N/A"),
                "kills": combined_kills,
                "headshots": combined_hs if combined_hs is not None else "N/A",
                "rounds": combined_rounds,
                "map1": map1.get("map_name", "unknown"),
                "map2": map2.get("map_name", "unknown"),
            }
        )

    return final_series_totals, final_series_hs_totals, paired_series_rows


def _bootstrap_distribution(samples: List[int], iterations: int = 50000) -> np.ndarray:
    if not samples:
        return np.array([], dtype=float)
    if len(samples) == 1:
        return np.full(iterations, float(samples[0]))
    weights = np.arange(len(samples), 0, -1, dtype=float)
    weights = weights / weights.sum()
    rng = np.random.default_rng(42)
    return rng.choice(np.array(samples, dtype=float), size=iterations, replace=True, p=weights)


def _recent_projection(samples: List[int]) -> Optional[float]:
    if not samples:
        return None
    weights = np.arange(len(samples), 0, -1, dtype=float)
    weights = weights / weights.sum()
    return float(np.average(np.array(samples, dtype=float), weights=weights))


def analyze_map_pool_enhanced(all_maps: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    map_stats = defaultdict(lambda: {"kills": [], "headshots": [], "kpr": []})
    for map_row in all_maps:
        map_name = map_row.get("map_name", "unknown")
        rounds_played = map_row.get("rounds")
        if map_name == "unknown":
            continue
        map_stats[map_name]["kills"].append(map_row.get("kills", 0))
        if isinstance(map_row.get("headshots"), int):
            map_stats[map_name]["headshots"].append(map_row.get("headshots", 0))
        if isinstance(rounds_played, int) and rounds_played > 0:
            map_stats[map_name]["kpr"].append(map_row.get("kills", 0) / rounds_played)

    map_averages = {}
    for map_name, payload in map_stats.items():
        if not payload["kills"]:
            continue
        map_averages[map_name] = {
            "avg_kills": round(_stats.mean(payload["kills"]), 1),
            "avg_hs": round(_stats.mean(payload["headshots"]), 1) if payload["headshots"] else "N/A",
            "avg_kpr": round(_stats.mean(payload["kpr"]), 3) if payload["kpr"] else "N/A",
            "sample_size": len(payload["kills"]),
        }

    sorted_maps = sorted(
        map_averages.items(),
        key=lambda item: (item[1]["avg_kills"], item[1]["sample_size"]),
        reverse=True,
    )
    likely_maps = {}
    for idx, (map_name, data) in enumerate(sorted_maps[:3], start=1):
        likely_maps[f"Best map {idx}"] = f"{map_name.title()} ({data['avg_kills']}k)"
    return map_averages, likely_maps


def analyze_h2h_history(paired_series_rows: List[Dict[str, Any]], opponent: str) -> Dict[str, Any]:
    opponent_lower = opponent.lower().strip()
    relevant = [row for row in paired_series_rows if opponent_lower and opponent_lower in row.get("opponent", "").lower()]
    if not relevant:
        return {
            "h2h_sample_size": 0,
            "h2h_avg_kills": "N/A",
            "h2h_avg_headshots": "N/A",
            "h2h_note": "No exact Maps 1-2 H2H sample found.",
        }
    kills = [row["kills"] for row in relevant if isinstance(row.get("kills"), (int, float))]
    headshots = [row["headshots"] for row in relevant if isinstance(row.get("headshots"), (int, float))]
    return {
        "h2h_sample_size": len(relevant),
        "h2h_avg_kills": round(_stats.mean(kills), 1) if kills else "N/A",
        "h2h_avg_headshots": round(_stats.mean(headshots), 1) if headshots else "N/A",
        "h2h_note": f"Exact Maps 1-2 sample vs {opponent.title()}",
    }


def _similar_team_split(opponent_rank: str, stats_payload: Dict[str, Any]) -> str:
    rank_match = re.search(r"#(\d+)", str(opponent_rank))
    if not rank_match:
        return "N/A"
    rank_value = int(rank_match.group(1))
    if rank_value <= 5:
        bucket = "Vs Top 5 rating"
    elif rank_value <= 10:
        bucket = "Vs Top 10 rating"
    elif rank_value <= 20:
        bucket = "Vs Top 20 rating"
    elif rank_value <= 30:
        bucket = "Vs Top 30 rating"
    else:
        bucket = "Vs Top 50 rating"
    return f"{bucket}: {stats_payload.get(bucket, 'N/A')}"


def _calculate_grade(
    line: float,
    recent_average: float,
    recent_median: float,
    hit_rate_pct: float,
    over_probability: float,
    sample_size: int,
) -> str:
    score = 5.0
    edge_pct = abs(over_probability - 50.0)
    avg_delta = abs(recent_average - line)
    median_delta = abs(recent_median - line)

    if edge_pct >= 25:
        score += 2.5
    elif edge_pct >= 18:
        score += 2.0
    elif edge_pct >= 12:
        score += 1.5
    elif edge_pct >= 7:
        score += 1.0

    if hit_rate_pct >= 70 or hit_rate_pct <= 30:
        score += 1.0
    elif hit_rate_pct >= 60 or hit_rate_pct <= 40:
        score += 0.5

    if avg_delta >= 6:
        score += 1.0
    elif avg_delta >= 3:
        score += 0.5

    if median_delta >= 5:
        score += 0.75
    elif median_delta >= 2:
        score += 0.25

    if sample_size < 5:
        score -= 0.5

    score = max(1.0, min(10.0, score))

    if score >= 9.0:
        tier = " ELITE EDGE"
    elif score >= 8.0:
        tier = " Very Strong"
    elif score >= 7.0:
        tier = " Strong Play"
    elif score >= 6.0:
        tier = " Solid Lean"
    elif score >= 5.0:
        tier = " Small Edge"
    else:
        tier = " No Bet"

    return f"{score:.1f}/10{tier}"


def project_map_scenarios(kpr_recent: Optional[float]) -> Dict[str, Dict[str, Any]]:
    """
    AUDIT FIX: scenario modeling now uses real recent KPR × projected rounds.
    No hardcoded opponent-strength multipliers.
    """
    if kpr_recent is None:
        return {
            "short": {"rounds_per_map": 19, "total_rounds": 38, "expected_kills": "N/A", "description": "Blowout/Stomp (38R)", "likelihood": "20%"},
            "normal": {"rounds_per_map": 22, "total_rounds": 44, "expected_kills": "N/A", "description": "Competitive (44R)", "likelihood": "55%"},
            "long": {"rounds_per_map": 25, "total_rounds": 50, "expected_kills": "N/A", "description": "Close/OT (50R)", "likelihood": "25%"},
        }
    return {
        "short": {
            "rounds_per_map": 19,
            "total_rounds": 38,
            "expected_kills": round(kpr_recent * 38, 1),
            "description": "Blowout/Stomp (38R)",
            "likelihood": "20%",
        },
        "normal": {
            "rounds_per_map": 22,
            "total_rounds": 44,
            "expected_kills": round(kpr_recent * 44, 1),
            "description": "Competitive (44R)",
            "likelihood": "55%",
        },
        "long": {
            "rounds_per_map": 25,
            "total_rounds": 50,
            "expected_kills": round(kpr_recent * 50, 1),
            "description": "Close/OT (50R)",
            "likelihood": "25%",
        },
    }


def calculate_ceiling_floor(values: List[int]) -> Tuple[Any, Any]:
    if not values:
        return "N/A", "N/A"
    if len(values) < 3:
        return max(values), min(values)
    sorted_values = sorted(values, reverse=True)
    return round(_stats.mean(sorted_values[:3]), 1), round(_stats.mean(sorted_values[-3:]), 1)


def _find_match_links(soup: Optional[BeautifulSoup], opponent: str) -> List[str]:
    if not soup:
        return []
    opponent_lower = opponent.lower().strip()
    found = []
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        text = _norm(link.get_text(" ", strip=True))
        if "/matches/" in href and text:
            if not opponent_lower or opponent_lower in text.lower():
                found.append(_abs_url(href))
    return found


def _parse_match_page_context(match_url: str, team_name: str, opponent_name: str) -> Dict[str, Any]:
    soup, _ = _get_soup(match_url, render=True)
    if not soup:
        return {
            "Match odds": "N/A",
            "Moneyline": "N/A",
            "Moneyline american": "N/A",
            "Veto": [],
            "Likely maps": {},
            "Match URL": match_url,
        }

    lines = _split_lines(soup)
    text = "\n".join(lines)
    veto = [
        line for line in lines
        if re.match(r"^\d+\.\s+", line) and any(term in line.lower() for term in ["removed", "picked", "left over"])
    ]

    team_labels = []
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        txt = _norm(link.get_text(" ", strip=True))
        if "/team/" in href and txt and txt not in team_labels:
            team_labels.append(txt)
        if len(team_labels) >= 2:
            break

    odds_lines = []
    for index, line in enumerate(lines):
        if line == "Betting":
            odds_lines.extend(lines[index:index + 8])
            break

    odds_values = [float(item) for item in re.findall(r"\b\d+\.\d+\b", " ".join(odds_lines))]

    match_odds = "N/A"
    moneyline = "N/A"
    moneyline_american = "N/A"

    if len(odds_values) >= 2:
        if len(team_labels) >= 2:
            match_odds = f"{team_labels[0]} {odds_values[0]:.2f} | {team_labels[1]} {odds_values[1]:.2f}"
            if _norm(team_labels[0]).lower() == _norm(team_name).lower():
                moneyline = f"{odds_values[0]:.2f}"
                moneyline_american = _decimal_to_american(odds_values[0])
            elif _norm(team_labels[1]).lower() == _norm(team_name).lower():
                moneyline = f"{odds_values[1]:.2f}"
                moneyline_american = _decimal_to_american(odds_values[1])
        else:
            match_odds = f"{odds_values[0]:.2f} | {odds_values[1]:.2f}"

    likely_maps = {}
    for line in veto:
        picked = re.search(r"picked\s+([A-Za-z0-9]+)", line, flags=re.IGNORECASE)
        leftover = re.search(r"([A-Za-z0-9]+)\s+was left over", line, flags=re.IGNORECASE)
        removed = re.search(r"removed\s+([A-Za-z0-9]+)", line, flags=re.IGNORECASE)
        if picked:
            key = f"Pick {len([k for k in likely_maps if k.startswith('Pick')]) + 1}"
            likely_maps[key] = picked.group(1).title()
        elif leftover:
            likely_maps["Decider"] = leftover.group(1).title()
        elif removed:
            key = f"Removal {len([k for k in likely_maps if k.startswith('Removal')]) + 1}"
            likely_maps[key] = removed.group(1).title()

    if not likely_maps:
        likely_maps = {}

    return {
        "Match odds": match_odds,
        "Moneyline": moneyline,
        "Moneyline american": moneyline_american,
        "Veto": veto,
        "Likely maps": likely_maps,
        "Match URL": match_url,
    }


def _build_context(profile_payload: Dict[str, Any], team_payload: Dict[str, Any], opponent: str) -> Dict[str, Any]:
    profile_links = _find_match_links(profile_payload.get("profile_soup"), opponent)
    team_links = _find_match_links(team_payload.get("team_soup"), opponent)
    candidate_links = profile_links + [link for link in team_links if link not in profile_links]
    if candidate_links:
        return _parse_match_page_context(candidate_links[0], team_payload.get("Team", "N/A"), opponent)
    return {
        "Match odds": "N/A",
        "Moneyline": "N/A",
        "Moneyline american": "N/A",
        "Veto": [],
        "Likely maps": {},
        "Match URL": "N/A",
    }


def _error_response(msg: str, player_name: str, line: float, opponent: str) -> Dict[str, Any]:
    return {
        "Player": player_name.title(),
        "Match": f"vs {opponent.title()}",
        "Prop Line": f"{line} Kills",
        "Bet recommendation": "NO BET",
        "error": msg,
    }


def _compose_output(
    display: str,
    profile_payload: Dict[str, Any],
    team_payload: Dict[str, Any],
    opponent_payload: Dict[str, Any],
    stats_payload: Dict[str, Any],
    context_payload: Dict[str, Any],
    exact_maps: List[Dict[str, Any]],
    line: float,
    opponent: str,
) -> Dict[str, Any]:
    final_series_totals, final_series_hs_totals, paired_series_rows = _series_rows_from_exact_maps(exact_maps)
    if not final_series_totals:
        raise ValueError("Could not build exact Maps 1-2 series totals from HLTV history.")

    sample_size = len(final_series_totals)
    recent_average = round(_stats.mean(final_series_totals), 2)
    recent_median = round(_stats.median(final_series_totals), 1)
    recent_projection = _recent_projection(final_series_totals)
    recent_projection_rounded = round(recent_projection, 1) if recent_projection is not None else "N/A"
    hs_projection = _recent_projection(final_series_hs_totals)
    hs_projection_rounded = round(hs_projection, 1) if hs_projection is not None else "N/A"

    hit_rate_pct = round((sum(1 for value in final_series_totals if value > line) / sample_size) * 100, 1) if line > 0 else 0.0
    hs_hit_rate_pct = round((sum(1 for value in final_series_hs_totals if value > line) / len(final_series_hs_totals)) * 100, 1) if line > 0 and final_series_hs_totals else 0.0

    bootstrap = _bootstrap_distribution(final_series_totals)
    over_probability = round(float(np.mean(bootstrap > line) * 100), 1) if line > 0 and bootstrap.size else 50.0
    under_probability = round(100.0 - over_probability, 1)
    edge_delta = round(over_probability - 50.0, 1)

    hs_bootstrap = _bootstrap_distribution(final_series_hs_totals) if final_series_hs_totals else np.array([], dtype=float)
    hs_over_probability = round(float(np.mean(hs_bootstrap > line) * 100), 1) if line > 0 and hs_bootstrap.size else 50.0
    hs_under_probability = round(100.0 - hs_over_probability, 1)
    hs_edge_delta = round(hs_over_probability - 50.0, 1)

    if line > 0 and recent_average > line and recent_median > line and hit_rate_pct >= 60.0:
        bet_recommendation = "OVER"
    elif line > 0 and recent_average < line and recent_median < line and hit_rate_pct <= 40.0:
        bet_recommendation = "UNDER"
    else:
        bet_recommendation = "NO BET"

    if line > 0 and hs_projection is not None:
        if hs_projection > line and hs_hit_rate_pct >= 60.0:
            hs_bet_recommendation = "OVER"
        elif hs_projection < line and hs_hit_rate_pct <= 40.0:
            hs_bet_recommendation = "UNDER"
        else:
            hs_bet_recommendation = "NO BET"
    else:
        hs_bet_recommendation = "NO BET"

    if line > 0 and (recent_average - line) >= 8.0:
        mispriced = "CLEAR MISPRICE (Underpriced)"
    elif line > 0 and (line - recent_average) >= 8.0:
        mispriced = "CLEAR MISPRICE (Overpriced)"
    elif abs(recent_average - line) >= 4.0:
        mispriced = "YES"
    else:
        mispriced = "NO"

    grade_str = _calculate_grade(
        line=line,
        recent_average=recent_average,
        recent_median=recent_median,
        hit_rate_pct=hit_rate_pct,
        over_probability=over_probability,
        sample_size=sample_size,
    )

    total_recent_rounds = sum(row["rounds"] for row in exact_maps if isinstance(row.get("rounds"), int))
    total_recent_kills = sum(int(row.get("kills", 0)) for row in exact_maps)
    recent_kpr = round(total_recent_kills / total_recent_rounds, 3) if total_recent_rounds > 0 else None

    map_averages, likely_maps_fallback = analyze_map_pool_enhanced(exact_maps)
    likely_maps = context_payload.get("Likely maps") or likely_maps_fallback
    ceiling, floor = calculate_ceiling_floor(final_series_totals)
    h2h_data = analyze_h2h_history(paired_series_rows, opponent)
    recent_hs_average = round(_stats.mean(final_series_hs_totals), 1) if final_series_hs_totals else "N/A"
    recent_hs_median = round(_stats.median(final_series_hs_totals), 1) if final_series_hs_totals else "N/A"
    recent_total_hs = sum(final_series_hs_totals) if final_series_hs_totals else 0
    total_series_kills = sum(final_series_totals)
    recent_hs_pct = round((recent_total_hs / total_series_kills) * 100, 1) if total_series_kills > 0 and final_series_hs_totals else None

    scenarios = project_map_scenarios(recent_kpr)
    exact_round_note = f"Exact rounds from grouped Maps 1-2 sample ({sample_size} series)"

    output = {
        "Player": display,
        "Team": team_payload.get("Team", profile_payload.get("team_name", "N/A")),
        "Team ranking": team_payload.get("Team ranking", "N/A"),
        "Opponent": opponent.title() if opponent else "N/A",
        "Opponent ranking": opponent_payload.get("Team ranking", "N/A"),
        "Match": f"vs {opponent.title()}",
        "Prop": f"{line} Kills",
        "Prop Line": f"{line} Kills O/U",
        "Bet recommendation": bet_recommendation,
        "HS Bet recommendation": hs_bet_recommendation,
        "Mispriced or not": mispriced,
        "Final grade": grade_str,
        "Rating 3.0": profile_payload.get("rating_3", "N/A"),
        "Role": profile_payload.get("role", "N/A"),
        "Role note": profile_payload.get("role_note", "N/A"),
        "Firepower": f"{profile_payload['attributes'].get('Firepower')}/100" if profile_payload.get("attributes", {}).get("Firepower") is not None else "N/A",
        "Entrying": f"{profile_payload['attributes'].get('Entrying')}/100" if profile_payload.get("attributes", {}).get("Entrying") is not None else "N/A",
        "Trading": f"{profile_payload['attributes'].get('Trading')}/100" if profile_payload.get("attributes", {}).get("Trading") is not None else "N/A",
        "Opening": f"{profile_payload['attributes'].get('Opening')}/100" if profile_payload.get("attributes", {}).get("Opening") is not None else "N/A",
        "Clutching": f"{profile_payload['attributes'].get('Clutching')}/100" if profile_payload.get("attributes", {}).get("Clutching") is not None else "N/A",
        "Sniping": f"{profile_payload['attributes'].get('Sniping')}/100" if profile_payload.get("attributes", {}).get("Sniping") is not None else "N/A",
        "Utility": f"{profile_payload['attributes'].get('Utility')}/100" if profile_payload.get("attributes", {}).get("Utility") is not None else "N/A",
        "KPR": stats_payload.get("KPR", "N/A"),
        "DPR": stats_payload.get("DPR", "N/A"),
        "ADR": stats_payload.get("ADR", "N/A"),
        "KAST": stats_payload.get("KAST", "N/A"),
        "Impact": stats_payload.get("Impact", "N/A"),
        "HS %": stats_payload.get("HS %", "N/A"),
        "Multi-kill %": stats_payload.get("Multi-kill %", "N/A"),
        "Round Swing %": stats_payload.get("Round Swing %", "N/A"),
        "Opening kills per round": stats_payload.get("Opening kills per round", "N/A"),
        "Trade kills per round": stats_payload.get("Trade kills per round", "N/A"),
        "Vs Top 5 rating": stats_payload.get("Vs Top 5 rating", "N/A"),
        "Vs Top 10 rating": stats_payload.get("Vs Top 10 rating", "N/A"),
        "Vs Top 20 rating": stats_payload.get("Vs Top 20 rating", "N/A"),
        "Vs Top 30 rating": stats_payload.get("Vs Top 30 rating", "N/A"),
        "Vs Top 50 rating": stats_payload.get("Vs Top 50 rating", "N/A"),
        "Recent sample used": f"Last {sample_size} exact BO3/BO5 series (Maps 1-2 only)",
        "Recent average": recent_average,
        "Recent median": recent_median,
        "Recent projection": recent_projection_rounded,
        "Hit rate": f"{hit_rate_pct}%",
        "Recent Totals (M1+M2 Combined)": final_series_totals,
        "Recent HS Totals (M1+M2)": final_series_hs_totals,
        "Recent HS Projection": hs_projection_rounded,
        "Recent HS Average": recent_hs_average,
        "Recent HS Median": recent_hs_median,
        "Recent HS %": _fmt_percent(recent_hs_pct, 1),
        "All-time profile HS %": stats_payload.get("HS %", "N/A"),
        "Ceiling (Top 3)": ceiling,
        "Floor (Bottom 3)": floor,
        "Simulated mean": round(float(np.mean(bootstrap)), 2) if bootstrap.size else "N/A",
        "Simulated median": round(float(np.median(bootstrap)), 2) if bootstrap.size else "N/A",
        "Std Dev": round(float(np.std(bootstrap)), 2) if bootstrap.size else "N/A",
        "25th percentile": round(float(np.percentile(bootstrap, 25)), 1) if bootstrap.size else "N/A",
        "75th percentile": round(float(np.percentile(bootstrap, 75)), 1) if bootstrap.size else "N/A",
        "Over probability": f"{over_probability}%" if line > 0 else "N/A",
        "Under probability": f"{under_probability}%" if line > 0 else "N/A",
        "Edge vs line": f"{edge_delta}%" if line > 0 else "N/A",
        "HS Simulated mean": round(float(np.mean(hs_bootstrap)), 2) if hs_bootstrap.size else "N/A",
        "HS Simulated median": round(float(np.median(hs_bootstrap)), 2) if hs_bootstrap.size else "N/A",
        "HS Std Dev": round(float(np.std(hs_bootstrap)), 2) if hs_bootstrap.size else "N/A",
        "HS Over probability": f"{hs_over_probability}%" if line > 0 and hs_bootstrap.size else "N/A",
        "HS Under probability": f"{hs_under_probability}%" if line > 0 and hs_bootstrap.size else "N/A",
        "HS Edge vs line": f"{hs_edge_delta}%" if line > 0 and hs_bootstrap.size else "N/A",
        "Projected rounds": 44,
        "Expected kills": scenarios.get("normal", {}).get("expected_kills", "N/A"),
        "Scenarios": scenarios,
        "Match odds": context_payload.get("Match odds", "N/A"),
        "Moneyline": context_payload.get("Moneyline", "N/A"),
        "Moneyline american": context_payload.get("Moneyline american", "N/A"),
        "Veto": context_payload.get("Veto", []),
        "Likely maps": likely_maps,
        "Similar teams": _similar_team_split(opponent_payload.get("Team ranking", "N/A"), stats_payload),
        "H2H Data": h2h_data,
        "Per-map averages": map_averages,
        "Paired series rows": paired_series_rows,
        "Raw maps": [
            {
                **row,
                "headshots": row.get("headshots") if isinstance(row.get("headshots"), int) else "N/A",
                "rounds": row.get("rounds") if isinstance(row.get("rounds"), int) else "N/A",
            }
            for row in exact_maps[:20]
        ],
        "Exact round note": exact_round_note,
        "Source URLs": {
            "profile": profile_payload.get("profile_url", "N/A"),
            "stats": stats_payload.get("stats_url", "N/A"),
            "match": context_payload.get("Match URL", "N/A"),
        },
    }
    return output


def get_player_info(player_name: str, line: float = 0.0, opponent: str = "N/A") -> Dict[str, Any]:
    """Main prop scraper entrypoint for kills."""
    try:
        search_res = search_player(player_name)
        if not search_res:
            return _error_response(f"Could not find player '{player_name}' on HLTV.", player_name, line, opponent)

        pid, slug, display = search_res
        print(f" TARGET ACQUIRED: {display} (ID: {pid})")

        profile_payload = fetch_player_profile(pid, slug)
        stats_payload = fetch_player_stats(pid, slug)
        history_rows = _extract_history_rows(pid, slug)

        if len(history_rows) < 2:
            return _error_response("Insufficient HLTV match-history rows.", display, line, opponent)

        series_groups = _group_series(history_rows)
        exact_maps = _hydrate_exact_maps(
            series_groups=series_groups,
            player_slug=slug,
            display_name=display,
            series_limit=10,
        )

        if len(exact_maps) < 2:
            return _error_response("Could not collect exact Maps 1-2 data from HLTV mapstats pages.", display, line, opponent)

        team_name = profile_payload.get("team_name") or "N/A"
        team_payload = fetch_team_rank(team_name)
        opponent_payload = fetch_team_rank(opponent) if opponent and opponent != "N/A" else {"Team": opponent, "Team ranking": "N/A"}
        context_payload = _build_context(profile_payload, team_payload, opponent)

        return _compose_output(
            display=display,
            profile_payload=profile_payload,
            team_payload=team_payload,
            opponent_payload=opponent_payload,
            stats_payload=stats_payload,
            context_payload=context_payload,
            exact_maps=exact_maps,
            line=line,
            opponent=opponent,
        )

    except Exception as global_exc:
        print(f" CRITICAL EXCEPTION: {global_exc}")
        return _error_response(f"System crash: {str(global_exc)}", player_name, line, opponent)


def get_headshot_info(player_name: str, line: float = 0.0, opponent: str = "N/A") -> Dict[str, Any]:
    """
    Dedicated headshot entrypoint so main.py can import and use an audit-aligned
    exact HS workflow rather than calling the kill function and recomputing ad hoc.
    """
    payload = get_player_info(player_name=player_name, line=line, opponent=opponent)
    if payload.get("error"):
        return payload

    recent_hs = payload.get("Recent HS Totals (M1+M2)", [])
    if not recent_hs:
        payload["error"] = "No exact headshot sample found on HLTV mapstats pages."
        payload["Bet recommendation"] = "NO BET"
        return payload

    avg_hs = round(_stats.mean(recent_hs), 1)
    median_hs = round(_stats.median(recent_hs), 1)
    hit_rate = round((sum(1 for value in recent_hs if value > line) / len(recent_hs)) * 100, 1) if line > 0 else 0.0

    payload["Prop"] = f"{line} Headshots"
    payload["Prop Line"] = f"{line} Headshots O/U"
    payload["Recent average"] = avg_hs
    payload["Recent median"] = median_hs
    payload["Recent projection"] = payload.get("Recent HS Projection", "N/A")
    payload["Hit rate"] = f"{hit_rate}%"
    payload["Bet recommendation"] = payload.get("HS Bet recommendation", "NO BET")
    payload["Over probability"] = payload.get("HS Over probability", "N/A")
    payload["Under probability"] = payload.get("HS Under probability", "N/A")
    payload["Edge vs line"] = payload.get("HS Edge vs line", "N/A")
    payload["Simulated mean"] = payload.get("HS Simulated mean", "N/A")
    payload["Simulated median"] = payload.get("HS Simulated median", "N/A")
    payload["Std Dev"] = payload.get("HS Std Dev", "N/A")
    payload["25th percentile"] = "N/A"
    payload["75th percentile"] = "N/A"

    return payload


__all__ = ["get_player_info", "get_headshot_info", "search_player", "search_team"]
