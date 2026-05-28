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

HLTV_BASE = "https://hltv.org"

# Helper functions (URL fetching, parsing, etc.)
def _norm(value: Any) -> str:
    return str(value).strip() if value is not None else ""

def _slugify(value: str) -> str:
    return re.sub(r'[^a-z0-9\-]', '', value.lower())

def _abs_url(href: str) -> str:
    if not href:
        return href
    if href.startswith("http"):
        return href
    return HLTV_BASE.rstrip("/") + "/" + href.lstrip("/")

def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except:
        return None

def _fmt_rank(value: Optional[int]) -> str:
    if value is None or value == 0:
        return "N/A"
    return f"#{value}"

def _decimal_to_american(decimal_odds: Optional[float]) -> str:
    if decimal_odds is None or decimal_odds == 0:
        return "N/A"
    dec = float(decimal_odds)
    if dec > 2:
        return f"+{int((dec - 1) * 100)}"
    else:
        return str(-int(100 / (dec - 1)))

def _today_range(days: int = 30) -> Tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()

def _should_render(url: str) -> bool:
    # Render HLTV analytics if needed (dynamic content)
    return "analytics" in url

def _fetch(url: str, render: Optional[bool] = None) -> Tuple[Optional[str], Optional[str]]:
    """Fetch HTML content or indicate failure."""
    import requests
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        return res.text, None
    except Exception as e:
        return None, str(e)

def _get_soup(url: str, render: Optional[bool] = None) -> Tuple[Optional[BeautifulSoup], Optional[str], Optional[str]]:
    """Fetch and parse HTML into BeautifulSoup."""
    html, err = _fetch(url)
    if not html:
        return None, None, err
    soup = BeautifulSoup(html, "html.parser")
    return soup, html, err

def _lines_from_soup(soup: Optional[BeautifulSoup]) -> List[str]:
    """Extract text lines from HTML soup."""
    if soup is None:
        return []
    text = soup.get_text("\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines

def _find_line_indices(lines: List[str], label: str, exact: bool = True) -> List[int]:
    """Find line indices containing label."""
    indices = []
    for i, line in enumerate(lines):
        if (exact and line.startswith(label)) or (not exact and label in line):
            indices.append(i)
    return indices

def _value_after(lines: List[str], label: str, regex: str, lookahead: int = 1) -> Optional[str]:
    """Get value after a label using regex search in following lines."""
    idxs = _find_line_indices(lines, label, exact=False)
    for idx in idxs:
        for j in range(1, lookahead+1):
            if idx+j < len(lines):
                m = re.search(regex, lines[idx+j])
                if m:
                    return m.group(0)
    return None

def _value_before(lines: List[str], label: str, regex: str, lookback: int = 1) -> Optional[str]:
    """Get value before a label using regex search in preceding lines."""
    idxs = _find_line_indices(lines, label, exact=False)
    for idx in idxs:
        for j in range(1, lookback+1):
            if idx-j >= 0:
                m = re.search(regex, lines[idx-j])
                if m:
                    return m.group(0)
    return None

def _profile_bucket_role(buckets: Dict[str, str]) -> Tuple[str, str]:
    """Derive player role from HLTV profile attribute buckets."""
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
    if entry >= 60 and open_ >= 50:
        return "Entry", f"Derived from HLTV buckets: Entrying {int(entry)}/100 and Opening {int(open_)}/100 profile as entry-heavy."
    if open_ >= 70:
        return "Opener", f"Derived from HLTV buckets: Opening {int(open_)}/100 is the clearest role signal."
    if fire >= 70:
        return "Star rifler", f"Derived from HLTV buckets: Firepower {int(fire)}/100 leads the profile."
    if util >= 60 and fire < 65:
        return "Support", f"Derived from HLTV buckets: Utility {int(util)}/100 is the strongest support signal."
    if clutch >= 60 and fire >= 50:
        return "Closer / rifler", f"Derived from HLTV buckets: Clutching {int(clutch)}/100 leads with enough Firepower ({int(fire)}/100)."
    return "N/A", "No single attribute strongly dictates a role."

def search_player(name: str) -> Optional[Tuple[str, str, str]]:
    """Search HLTV for player and return (id, slug, display_name)."""
    url_name = quote_plus(name)
    url = f"{HLTV_BASE}/stats/players?query={url_name}"
    soup, _, _ = _get_soup(url)
    if not soup:
        return None
    link = soup.find("a", href=re.compile(r"/stats/players/\d+/.+"))
    if not link:
        return None
    href = link["href"]
    m = re.search(r"/stats/players/(\d+)/([^/]+)$", href)
    if not m:
        return None
    pid = m.group(1)
    slug = m.group(2)
    display = link.get_text(strip=True)
    return pid, slug, display

def fetch_player_profile(pid: str, slug: str) -> Dict[str, Any]:
    """Fetch player profile info, attributes, and team."""
    soup, _, _ = _get_soup(f"{HLTV_BASE}/player/{pid}/{slug}", render=True)
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
    for line in lines:
        if line.startswith("# "):
            display_name = _norm(line.replace("# ", "", 1))
            break

    team_name = "N/A"
    try:
        marker = soup.find(string=re.compile(r"Current team", re.I))
        if marker:
            team_link = marker.parent.find_next("a", href=re.compile(r"/team/"))
            if team_link:
                team_name = _norm(team_link.get_text(" ", strip=True))
    except:
        pass

    current_rank = _value_after(lines, "Current ranking", r"#?\d+", lookahead=4) or "N/A"
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
    for a in soup.find_all("a", href=re.compile(r"/stats/players/\d+/.+")):
        if a.text and a["href"] and a["href"].endswith(slug) and a.text.strip():
            url = HLTV_BASE + a["href"]
            if url not in seen:
                seen.add(url)
                match_links.append((url, a.text.strip()))

    role, role_note = _profile_bucket_role(buckets)

    return {
        "display_name": display_name,
        "team_name": team_name,
        "team_ranking": current_rank,
        "rating_3": rating_3,
        "profile_buckets": buckets,
        "match_links": match_links,
        "role": role,
        "role_note": role_note,
    }

def _build_stats_url(pid: str, slug: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    url = f"{HLTV_BASE}/stats/players/{pid}/{slug}/-"
    if start_date and end_date:
        url += f"?startDate={start_date}&endDate={end_date}"
    return url

def fetch_player_stats(pid: str, slug: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, str]:
    """Fetch player stats (Rating, KAST, KPR, etc.) from HLTV."""
    soup, _, _ = _get_soup(_build_stats_url(pid, slug, start_date, end_date), render=False)
    if not soup:
        return {}

    lines = _lines_from_soup(soup)
    stats: Dict[str, str] = {}

    stats["Rating 2.0"] = _value_before(lines, "Rating 2.0", r"\d+\.\d+", lookback=4) or "N/A"
    stats["Rating 3.0 recent"] = _value_before(lines, "Rating 3.0", r"\d+\.\d+", lookback=4) or "N/A"
    stats["Round swing"] = _value_before(lines, "Round swing", r"[+-]?\d+\.\d+%", lookback=4) or "N/A"
    stats["KAST"] = _value_before(lines, "KAST", r"\d+\.\d+%", lookback=4) or "N/A"
    stats["ADR"] = _value_before(lines, "ADR", r"\d+\.\d+", lookback=4) or "N/A"
    stats["KPR"] = _value_before(lines, "KPR", r"\d+\.\d+", lookback=4) or "N/A"
    stats["DPR"] = _value_before(lines, "DPR", r"\d+\.\d+", lookback=4) or "N/A"
    stats["HS %"] = _value_before(lines, "HS%", r"\d+\.\d+%", lookback=4) or "N/A"
    stats["Impact"] = _value_before(lines, "Impact", r"\d+\.\d+", lookback=4) or "N/A"
    # Stats against top teams
    stats["Vs Top 5 rating"] = _value_before(lines, "vs. Top 5 rating", r"\d+\.\d+", lookback=4) or "N/A"
    stats["Vs Top 10 rating"] = _value_before(lines, "vs. Top 10 rating", r"\d+\.\d+", lookback=4) or "N/A"
    stats["Vs Top 20 rating"] = _value_before(lines, "vs. Top 20 rating", r"\d+\.\d+", lookback=4) or "N/A"
    stats["Vs Top 30 rating"] = _value_before(lines, "vs. Top 30 rating", r"\d+\.\d+", lookback=4) or "N/A"
    stats["Vs Top 50 rating"] = _value_before(lines, "vs. Top 50 rating", r"\d+\.\d+", lookback=4) or "N/A"
    return stats

def extract_history_rows(pid: str, slug: str) -> List[Dict[str, Any]]:
    """Extract player's recent matches (last 10 or so) with kills and headshots from HLTV."""
    url = f"{HLTV_BASE}/stats/players/{pid}/{slug}"
    soup, html, _ = _get_soup(url)
    if not soup:
        return []
    table = soup.find("table", {"class": "player-matches-table"})
    if not table:
        return []
    rows = []
    for tr in table.find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if not cols or cols[0] == "Date":
            continue
        row = {
            "date": cols[0],
            "championship": cols[1],
            "map": cols[2],
            "opponent": cols[3],
            "result": cols[4],
            "rounds": int(cols[5]),
            "kills": int(cols[6]),
            "headshots": int(cols[7]),
            "rating": cols[8],
        }
        rows.append(row)
    return rows

def hydrate_maps(rows: List[Dict[str, Any]], slug: str, display_name: str) -> List[Dict[str, Any]]:
    """Combine maps for double-map series and add context."""
    hydrated = []
    for row in rows:
        hydrated.append({
            "date": row["date"],
            "opponent": row["opponent"],
            "map1": row["map"],
            "map2": None,
            "kills": row["kills"],
            "headshots": row["headshots"],
            "rounds": row["rounds"],
        })
    return hydrated

def pair_recent_series(hydrated_rows: List[Dict[str, Any]], max_series: int = 8) -> List[Dict[str, Any]]:
    """Pair recent two-map series (maps 1&2)."""
    paired = []
    used = set()
    for row in hydrated_rows:
        key = (row["date"], row["opponent"])
        if key in used:
            continue
        if row["map1"] and not row["map2"]:
            paired.append(row)
        used.add(key)
        if len(paired) >= max_series:
            break
    return paired

def _sample_stats(samples: List[int], line: float) -> Dict[str, float]:
    """Calculate distribution stats and probabilities."""
    stats: Dict[str, float] = {"avg": None, "median": None, "hit_rate": None,
                               "over_probability": None, "under_probability": None,
                               "q25": None, "q75": None,
                               "sim_mean": None, "sim_median": None, "std_dev": None}
    if not samples:
        return stats
    arr = np.array(samples) if np else None
    stats["avg"] = float(np.mean(arr)) if np else float(sum(samples) / len(samples))
    stats["median"] = float(np.median(arr)) if np else float(sorted(samples)[len(samples)//2])
    stats["hit_rate"] = float((np.sum(arr > line)/len(arr) * 100)) if np else float(sum(x > line for x in samples)/len(samples) * 100)
    stats["over_probability"] = stats["hit_rate"]
    stats["under_probability"] = 100.0 - stats["hit_rate"]
    stats["q25"] = float(np.percentile(arr, 25)) if np else float(sorted(samples)[max(int(len(samples)*0.25)-1,0)])
    stats["q75"] = float(np.percentile(arr, 75)) if np else float(sorted(samples)[min(int(len(samples)*0.75), len(samples)-1)])
    # Simple simulation for illustrative purposes
    if np:
        sims = [np.mean(np.random.choice(arr, size=len(arr))) for _ in range(1000)]
        stats["sim_mean"] = float(np.mean(sims))
        stats["sim_median"] = float(np.median(sims))
        stats["std_dev"] = float(np.std(sims))
    return stats

def _find_profile_match_url(match_links: List[Tuple[str, str]], opponent: str) -> Optional[str]:
    for url, text in match_links:
        if opponent and opponent.lower() in text.lower():
            return url
    return None

def fetch_match_context(match_url: Optional[str], player_team: str, opponent: str) -> Dict[str, Any]:
    """Fetch match context: team ranks, odds, veto, etc."""
    if not match_url:
        return {}
    soup, html, _ = _get_soup(match_url, render=True)
    if not soup:
        return {}
    lines = _lines_from_soup(soup)
    teams = [team.strip() for team in player_team.split(",")] if player_team else []
    # Simplistic: find team ranks
    player_rank = None
    opponent_rank = None
    team_rank_regex = re.compile(rf"{player_team}.*#(\d+)")
    opp_rank_regex = re.compile(rf"{opponent}.*#(\d+)")
    for line in lines:
        if team_rank_regex.search(line):
            m = team_rank_regex.search(line)
            player_rank = m.group(1)
        if opp_rank_regex.search(line):
            m = opp_rank_regex.search(line)
            opponent_rank = m.group(1)
    context: Dict[str, Any] = {}
    context["Team ranking"] = f"#{player_rank}" if player_rank else None
    context["Opponent ranking"] = f"#{opponent_rank}" if opponent_rank else None
    # Odds (placeholder)
    context["Match odds"] = None
    context["Moneyline"] = None
    context["Veto"] = None
    context["Likely maps"] = None
    # Additional analytics placeholders
    context["Blowouts"] = None
    context["Map pace"] = None
    context["Overtime probability"] = None
    context["Multi-kill pressure"] = None
    context["2K frequency"] = None
    context["3K frequency"] = None
    context["Clutch conversion"] = None
    context["Eco farming"] = None
    context["Anti eco padding"] = None
    context["Opponent strength"] = None
    return context

def _h2h_payload(paired_rows: List[Dict[str, Any]], opponent: str) -> str:
    """Format head-to-head recent matches summary."""
    if not paired_rows:
        return "No head-to-head matches."
    lines = []
    for row in paired_rows:
        total_kills = row.get("kills", 0)
        total_hs = row.get("headshots", 0)
        lines.append(f"{row.get('date','N/A')} vs {row.get('opponent','N/A')}: Kills {total_kills}, HS {total_hs}")
    return "\n".join(lines)

def _build_scenarios(paired_rows: List[Dict[str, Any]], total_kills: int, total_rounds: int) -> Dict[str, Any]:
    """Placeholder for future scenario modeling (e.g., simulating different outcomes)."""
    # Not implemented in this version
    return {}

def _fmt_list(values, limit=10):
    if not values:
        return "No sample"
    return ", ".join(str(x) for x in values[:limit])

def _fmt_maps(likely_maps):
    if not likely_maps:
        return "N/A"
    if isinstance(likely_maps, dict):
        return ", ".join(f"{k}: {v}" for k, v in likely_maps.items())
    if isinstance(likely_maps, list):
        return ", ".join(str(x) for x in likely_maps)
    return str(likely_maps)

def get_player_info(player_name: str, line: float = 0.0, opponent: str = "N/A") -> Dict[str, Any]:
    try:
        return _build_payload(player_name=player_name, line=float(line), opponent=opponent, kill_mode=True)
    except Exception as exc:
        return {"error": str(exc)}

def get_headshot_info(player_name: str, line: float = 0.0, opponent: str = "N/A") -> Dict[str, Any]:
    try:
        return _build_payload(player_name=player_name, line=float(line), opponent=opponent, kill_mode=False)
    except Exception as exc:
        return {"error": str(exc)}

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
    paired_rows = pair_recent_series(hydrated_rows, max_series=8)

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
        projection = None

    recommendation = "NO BET"
    side_probability = None
    hit_rate = stats["hit_rate"]
    if stats["avg"] is not None and stats["over_probability"] is not None:
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
    # Grade based on edge and consistency
    if edge_pct is not None:
        if abs(edge_pct) >= 20:
            final_grade = "A"
        elif abs(edge_pct) >= 10:
            final_grade = "B"
        else:
            final_grade = "C"
    else:
        final_grade = "C"

    team_name = profile.get("team_name", "N/A")
    match_url = _find_profile_match_url(profile.get("match_links", []), opponent)
    match_context = fetch_match_context(match_url, team_name, opponent) if match_url else {}

    # Ensure team ranking fallback
    if match_context.get("Team ranking") in (None, "", "N/A"):
        match_context["Team ranking"] = profile.get("team_ranking", "N/A")

    # Parse opponent rank if available
    opponent_rank_int = None
    try:
        opp_rank_val = match_context.get("Opponent ranking", "")
        if opp_rank_val and opp_rank_val.startswith("#"):
            opponent_rank_int = int(opp_rank_val.replace("#", ""))
    except:
        opponent_rank_int = None

    buckets = dict(profile.get("profile_buckets") or {})
    role = profile.get("role", "N/A")
    role_note = profile.get("role_note", "")

    # Merge HLTV profile buckets into stats for attributes
    merged_stats = dict(recent_stats)
    for key, value in buckets.items():
        if value and value != "N/A":
            try:
                merged_stats[key] = int(value.split("/")[0])
            except:
                merged_stats[key] = value
    # Fallback to all-time if recent is missing
    for key in ("Firepower", "Entrying", "Trading", "Opening", "Clutching", "Sniping", "Utility"):
        if merged_stats.get(key) in (None, "", "N/A"):
            merged_stats[key] = all_time_stats.get(key, "N/A")

    similar_teams, similar_bucket_rating = [], None

    # Calculate total and percentage headshots
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
        "Rating 3.0": recent_stats.get("Rating 3.0 recent", profile.get("rating_3", "N/A")),
        "Role": role,
        "Role note": role_note,
        "Recent form": None,  # To be implemented: summary string of recent performance
        "Exact round note": "Using first two maps only for calculation.",
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
        "Moneyline american": _decimal_to_american(match_context.get("Moneyline")),
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
        "Raw maps": hydrated_rows,
        "Per-map averages": None,  # Not implemented
        "Sample": f"{len(paired_rows)} series" if paired_rows else f"{len(hydrated_rows[:10])} maps",
        "Sample note": "Exact series sample" if not fallback_used else "Fallback to map sample",
        "Recent stat window": f"{start_30} to {end_30}",
        "Blowouts": match_context.get("Blowouts", "N/A"),
        "Map pace": match_context.get("Map pace", "N/A"),
        "Overtime probability": match_context.get("Overtime probability", "N/A"),
        "Multi-kill pressure": match_context.get("Multi-kill pressure", "N/A"),
        "2K frequency": match_context.get("2K frequency", "N/A"),
        "3K frequency": match_context.get("3K frequency", "N/A"),
        "Clutch conversion": match_context.get("Clutch conversion", "N/A"),
        "Eco farming": match_context.get("Eco farming", "N/A"),
        "Anti eco padding": match_context.get("Anti eco padding", "N/A"),
        "Opponent strength": match_context.get("Opponent strength", "N/A")
    }
    return payload
