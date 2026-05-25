import os
import re
import time
import statistics as stats
from collections import defaultdict
from urllib.parse import quote, urljoin
from datetime import datetime, timedelta
import numpy as np
from bs4 import BeautifulSoup
try:
    from curl_cffi import requests # type: ignore
except Exception:
    import requests # type: ignore

HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

STATIC_IDS = {
    "donk": ("21167", "donk"),
    "zywoo": ("11893", "zywoo"),
    "m0nesy": ("19230", "m0nesy"),
    "niko": ("3741", "niko"),
    "jl": ("19206", "jl"),
    "xertion": ("20312", "xertion"),
    "ammar": ("21109", "ammar"),
}

MAP_CODE = {
    "anc": "Ancient",
    "anb": "Anubis",
    "d2": "Dust2",
    "inf": "Inferno",
    "mrg": "Mirage",
    "nuke": "Nuke",
    "ovp": "Overpass",
    "vrt": "Vertigo",
    "ancient": "Ancient",
    "anubis": "Anubis",
    "dust2": "Dust2",
    "inferno": "Inferno",
    "mirage": "Mirage",
    "overpass": "Overpass",
    "vertigo": "Vertigo",
}

def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()

def fnum(value, default=0.0):
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except Exception:
        return default

def visible_lines(html: str):
    soup = BeautifulSoup(html, "html.parser")
    return [clean(x) for x in soup.stripped_strings if clean(x)]

def visible_text(html: str) -> str:
    return " ".join(visible_lines(html))

def fetch(url: str, render: bool = False, timeout: int = 30, retries: int = 2):
    """Fetch URL with retry logic and exponential backoff."""
    for attempt in range(retries):
        targets = []
        if SCRAPERAPI_KEY:
            encoded = quote(url, safe="")
            for use_render in (render, not render, True):
                proxy = (
                    "http://api.scraperapi.com"
                    f"?api_key={SCRAPERAPI_KEY}"
                    f"&url={encoded}"
                    f"&country_code=us"
                    f"&keep_headers=true"
                    f"{'&render=true' if use_render else ''}"
                )
                targets.append(proxy)
        else:
            targets.append(url)

        for target in targets:
            try:
                resp = requests.get(target, headers=HEADERS, timeout=timeout, allow_redirects=True)
                if resp.status_code == 200 and len(resp.text or "") > 800:
                    final_url = resp.headers.get("Sa-Final-Url") or getattr(resp, "url", url)
                    return resp.text, final_url
            except requests.exceptions.Timeout:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    break
                continue
            except Exception:
                if attempt < retries - 1:
                    time.sleep(1)
                    break
                continue
    
    return None, None

def search_player(name: str):
    q = norm(name)
    if q in STATIC_IDS:
        pid, slug = STATIC_IDS[q]
        return pid, slug, slug.replace("-", " ").title()
    
    html, final_url = fetch(f"{HLTV_BASE}/search?query={quote(name)}", render=True)
    
    if not html:
        return None
    
    if final_url and "/player/" in final_url:
        m = re.search(r"/player/(\d+)/([^/?#\s]+)", final_url)
        if m:
            pid, slug = m.group(1), m.group(2)
            return pid, slug, slug.replace("-", " ").title()
    
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"/player/(\d+)/([a-zA-Z0-9_-]+)", a["href"])
        if m:
            pid, slug = m.group(1), m.group(2)
            if pid not in {x[0] for x in found}:
                found.append((pid, slug))
    
    if not found:
        return None
    
    for pid, slug in found:
        if q == norm(slug) or q in norm(slug):
            return pid, slug, slug.replace("-", " ").title()
    
    pid, slug = found[0]
    return pid, slug, slug.replace("-", " ").title()

def error_response(msg, player_name, line, opponent):
    return {
        "Player": player_name.title(),
        "Match": f"vs {opponent.title()}",
        "Prop Line": f"{line} Kills",
        "Bet recommendation": "NO BET",
        "error": msg,
    }

def profile_metrics(profile_html: str):
    """Extract profile metrics with resilient parsing."""
    text = visible_text(profile_html)
    out = {
        "rating_3": "N/A",
        "firepower": "N/A",
        "entrying": "N/A",
        "trading": "N/A",
        "opening": "N/A",
        "clutching": "N/A",
        "sniping": "N/A",
        "utility": "N/A",
        "all_time_hs_pct": "N/A",
        "team": "N/A",
        "team_url": None,
    }
    
    # **FIXED: More resilient attribute parsing without strict header matching**
    attribute_patterns = {
        "rating_3": r"Rating 3\.0\s+([0-9]+(?:\.[0-9]+)?)",
        "firepower": r"Firepower\s+(\d+)\s*/\s*100",
        "entrying": r"Entrying\s+(\d+)\s*/\s*100",
        "trading": r"Trading\s+(\d+)\s*/\s*100",
        "opening": r"Opening\s+(\d+)\s*/\s*100",
        "clutching": r"Clutching\s+(\d+)\s*/\s*100",
        "sniping": r"Sniping\s+(\d+)\s*/\s*100",
        "utility": r"Utility\s+(\d+)\s*/\s*100",
    }
    
    for key, pattern in attribute_patterns.items():
        m = re.search(pattern, text, re.I)
        if m:
            out[key] = int(m.group(1)) if key != "rating_3" else m.group(1)
    
    m = re.search(r"Headshots\s+([0-9]+(?:\.[0-9]+)?)%", text, re.I)
    if m:
        out["all_time_hs_pct"] = f"{m.group(1)}%"
    
    soup = BeautifulSoup(profile_html, "html.parser")
    for a in soup.find_all("a", href=True):
        if re.search(r"^/team/\d+/[^/]+$", a["href"]):
            out["team"] = clean(a.get_text(" "))
            out["team_url"] = urljoin(HLTV_BASE, a["href"])
            break
    
    return out

def stats_metrics(stats_html: str):
    text = visible_text(stats_html)
    out = {
        "KPR": "N/A",
        "DPR": "N/A",
        "ADR": "N/A",
        "KAST": "N/A",
        "Impact": "N/A",
        "Opening KPR": "N/A",
        "Trade KPR": "N/A",
        "Round Swing": "N/A",
        "Multi-kill %": "N/A",
        "vs_top": {},
    }
    
    simple_before = {
        "KPR": r"([0-9]+(?:\.[0-9]+)?)\s+KPR\b",
        "DPR": r"([0-9]+(?:\.[0-9]+)?)\s+DPR\b",
        "ADR": r"([0-9]+(?:\.[0-9]+)?)\s+ADR\b",
        "KAST": r"([0-9]+(?:\.[0-9]+)?%)\s+KAST\b",
        "Multi-kill %": r"([0-9]+(?:\.[0-9]+)?%)\s+Rounds with a multi-kill\b",
    }
    
    for key, rx in simple_before.items():
        m = re.search(rx, text, re.I)
        if m:
            out[key] = m.group(1)
    
    simple_after = {
        "Impact": r"Impact rating\s+([0-9]+(?:\.[0-9]+)?)",
        "Opening KPR": r"Opening kills per round\s+([0-9]+(?:\.[0-9]+)?)",
        "Trade KPR": r"Trade kills per round\s+([0-9]+(?:\.[0-9]+)?)",
        "Round Swing": r"Round swing\s+([+\-]?[0-9]+(?:\.[0-9]+)?%)",
    }
    
    for key, rx in simple_after.items():
        m = re.search(rx, text, re.I)
        if m:
            out[key] = m.group(1)
    
    for cutoff in (5, 10, 20, 30, 50):
        m = re.search(rf"([0-9]+(?:\.[0-9]+)?|-)\s+vs top {cutoff} opponents\s+\((\d+) maps\)", text, re.I)
        if m:
            out["vs_top"][cutoff] = {"rating": m.group(1), "maps": int(m.group(2))}
    
    return out

def team_rank(team_html: str):
    text = visible_text(team_html)
    out = {"HLTV Rank": "N/A", "Valve Rank": "N/A"}
    
    m = re.search(r"World ranking\s+#(\d+)", text, re.I)
    if m:
        out["HLTV Rank"] = f"#{m.group(1)}"
    
    m = re.search(r"Valve ranking\s+Beta\s+#(\d+)", text, re.I)
    if m:
        out["Valve Rank"] = f"#{m.group(1)}"
    
    return out

def derive_role(profile):
    sniping = int(profile.get("sniping") or 0)
    firepower = int(profile.get("firepower") or 0)
    entrying = int(profile.get("entrying") or 0)
    trading = int(profile.get("trading") or 0)
    opening = int(profile.get("opening") or 0)
    utility = int(profile.get("utility") or 0)
    
    if sniping >= 55:
        return "Primary AWPer"
    if firepower >= 65 and opening >= 45:
        return "Star Entry Rifler"
    if entrying >= 55 and opening >= 35:
        return "Entry / Space Creator"
    if trading >= 60 and firepower >= 55:
        return "Trade / Lurk Rifler"
    if utility >= 60 and firepower <= 52:
        return "Support / Anchor"
    if firepower >= 58 and trading >= 50:
        return "Flex Rifler"
    
    return "Flex / Support Rifler"

def results_links(player_id: str, limit=20):
    html, _ = fetch(f"{HLTV_BASE}/results?player={player_id}", render=True)
    
    if not html:
        return []
    
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    
    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = clean(a.get_text(" "))
        
        if not href.startswith("/matches/"):
            continue
        if "bo3" not in txt.lower() and "best of 3" not in txt.lower():
            continue
        if not re.search(r"\b\d+\s*-\s*\d+\b", txt):
            continue
        
        full = urljoin(HLTV_BASE, href)
        if full not in seen:
            out.append(full)
            seen.add(full)
        
        if len(out) >= limit:
            break
    
    return out

def stats_page_from_match(match_html: str):
    m = re.search(r"/stats/matches/\d+/[^\"']+", match_html)
    return urljoin(HLTV_BASE, m.group(0)) if m else None

def map_list_from_stats_page(text: str):
    """
    **FIXED: Extract only Maps 1 and 2, respecting BO3 boundary.
    Prevents Map 3 contamination.
    """
    maps = []
    
    # Look for map score patterns: "16 - 14 ancient" style
    # Only extract first 2 occurrences
    for idx, match in enumerate(re.finditer(
        r"(\d+)\s*-\s*(\d+)\s+([a-z0-9]+)\s+(Ancient|Anubis|Dust2|Inferno|"
        r"Mirage|Nuke|Overpass|Vertigo|Train|Cache|Cobblestone)",
        text,
        re.I,
    )):
        if idx >= 2:  # **Only grab first 2 maps**
            break
        
        a, b, code, name = match.groups()
        maps.append({
            "map_name": MAP_CODE.get(code.lower(), name),
            "rounds": int(a) + int(b),
            "score": f"{a}-{b}",
        })
    
    return maps

def player_rows(stats_html: str, player_slug: str, player_display: str):
    """
    **FIXED: Headshot extraction with fallback for parse failures.
    No longer silently drops headshot data if regex fails.
    """
    lines = visible_lines(stats_html)
    needles = {norm(player_slug), norm(player_display)}
    rows = []
    
    row_rx = re.compile(
        r"^\d+\s*:\s*\d+\s+\d+\s*:\s*\d+\s+\d+\s+"
        r"\d+(?:\.\d+)?%\s+\d+(?:\.\d+)?%\s+\d+\s+"
        r"\d+(?:\.\d+)?(?:\([0-9]+\))?.*?[+\-]?\d+(?:\.\d+)?%\s+[0-9]+(?:\.[0-9]+)?$"
    )
    
    for i, line in enumerate(lines):
        if norm(line) not in needles:
            continue
        
        for j in range(1, 7):  # Extended range for layout shifts
            if i + j >= len(lines):
                continue
            
            cand = lines[i + j]
            if not row_rx.search(cand):
                continue
            
            pairs = re.findall(r"(\d+)\s*\((\d+)\)", cand)
            
            # **NEW: Fallback if parentheses parsing fails**
            if len(pairs) < 4:
                # Try alternative: extract kills from first number group
                nums = re.findall(r"\d+(?:\.\d+)?", cand)
                if len(nums) < 5:
                    continue
                
                rows.append({
                    "kills": int(float(nums[0])),
                    "headshots": 0,  # **FLAG: HS parsing failed, using 0**
                    "assists": int(float(nums[2])) if len(nums) > 2 else 0,
                    "deaths": int(float(nums[1])),
                    "rating_3": fnum(nums[-1], 0.0),
                    "row": cand,
                    "hs_fallback": True,
                })
                break
            
            # **Standard path: headshots in parentheses**
            rows.append({
                "kills": int(pairs[0][0]),
                "headshots": int(pairs[0][1]),
                "assists": int(pairs[2][0]),
                "deaths": int(pairs[3][0]),
                "rating_3": fnum(cand.split()[-1], 0.0),
                "row": cand,
                "hs_fallback": False,
            })
            break
    
    return rows

def series_from_stats_page(stats_html: str, player_slug: str, player_display: str, current_team: str):
    soup = BeautifulSoup(stats_html, "html.parser")
    text = visible_text(stats_html)
    
    title = clean(soup.title.get_text(" ")) if soup.title else ""
    tm = re.search(r"([A-Za-z0-9 .\-]+) vs\. ([A-Za-z0-9 .\-]+)", title)
    if not tm:
        return None
    
    team1, team2 = tm.group(1).strip(), tm.group(2).strip()
    
    dm = re.search(r"(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}", text)
    date = dm.group(1) if dm else "N/A"
    
    bo = re.search(r"bo(\d+)\s+Best of\s+(\d+)", text, re.I)
    best_of = int(bo.group(2)) if bo else None
    
    if best_of != 3:
        return None
    
    maps = map_list_from_stats_page(text)
    rows = player_rows(stats_html, player_slug, player_display)
    
    if len(maps) < 2 or len(rows) < 3:
        return None
    
    # **FIXED: Validate row/map alignment**
    if len(rows) > 3:
        rows = rows[:3]  # Trim to aggregate + map1 + map2
    
    m1, m2 = rows[1], rows[2]
    map1, map2 = maps[0], maps[1]
    
    # **Sanity check: m1+m2 kills should match aggregate within 15%**
    m1_m2_sum = m1["kills"] + m2["kills"]
    aggregate_kills = rows[0]["kills"]
    if aggregate_kills > 0:
        ratio = m1_m2_sum / aggregate_kills
        if ratio < 0.85 or ratio > 1.15:
            return None  # Data integrity issue
    
    opponent = team2 if norm(team1) == norm(current_team) else (
        team1 if norm(team2) == norm(current_team) else team2
    )
    
    return {
        "date": date,
        "opponent": opponent,
        "kills": m1["kills"] + m2["kills"],
        "headshots": m1["headshots"] + m2["headshots"],
        "deaths": m1["deaths"] + m2["deaths"],
        "rounds": map1["rounds"] + map2["rounds"],
        "map1": map1["map_name"],
        "map2": map2["map_name"],
        "raw_maps": [
            {
                "date": date,
                "opponent": opponent,
                "map_name": map1["map_name"],
                "score": map1["score"],
                "kills": m1["kills"],
                "deaths": m1["deaths"],
                "headshots": m1["headshots"],
                "rounds": map1["rounds"],
                "rating_3": m1["rating_3"],
            },
            {
                "date": date,
                "opponent": opponent,
                "map_name": map2["map_name"],
                "score": map2["score"],
                "kills": m2["kills"],
                "deaths": m2["deaths"],
                "headshots": m2["headshots"],
                "rounds": map2["rounds"],
                "rating_3": m2["rating_3"],
            },
        ],
    }

def build_recent_series(player_id: str, player_slug: str, player_display: str, current_team: str, limit=10):
    out = []
    
    for match_url in results_links(player_id, limit=max(18, limit * 2)):
        if len(out) >= limit:
            break
        
        match_html, _ = fetch(match_url, render=True)
        if not match_html:
            continue
        
        stats_url = stats_page_from_match(match_html)
        if not stats_url:
            continue
        
        stats_html, _ = fetch(stats_url, render=True)
        if not stats_html:
            continue
        
        item = series_from_stats_page(stats_html, player_slug, player_display, current_team)
        if item:
            out.append(item)
    
    return out[:limit]

def flat_raw_maps(series_rows):
    out = []
    for row in series_rows:
        out.extend(row.get("raw_maps", []))
    return out

def per_map_averages(raw_maps):
    buckets = defaultdict(lambda: {"kills": [], "hs": [], "rounds": []})
    
    for row in raw_maps:
        m = row["map_name"]
        buckets[m]["kills"].append(int(row["kills"]))
        buckets[m]["hs"].append(int(row["headshots"]))
        buckets[m]["rounds"].append(int(row["rounds"]))
    
    result = {}
    for m, parts in buckets.items():
        total_rounds = sum(parts["rounds"]) or 1
        result[m] = {
            "avg_kills": round(stats.mean(parts["kills"]), 1),
            "avg_hs": round(stats.mean(parts["hs"]), 1),
            "avg_kpr": round(sum(parts["kills"]) / total_rounds, 3),
            "sample_size": len(parts["kills"]),
        }
    
    return dict(sorted(result.items(), key=lambda x: x[1]["avg_kills"], reverse=True))

def bootstrap(values, line, min_sample=5):
    """
    **FIXED: Return warning if sample too small for reliable stats.
    """
    if not values or len(values) < min_sample:
        return {
            "mean": "N/A",
            "median": "N/A",
            "std": "N/A",
            "q25": "N/A",
            "q75": "N/A",
            "over": "N/A",
            "under": "N/A",
            "edge": "N/A",
            "sample_warning": f"Sample too small: {len(values or [])} entries (min {min_sample})"
        }
    
    arr = np.array(values, dtype=np.float32)
    np.random.seed(42)
    sims = np.random.choice(arr, 100000, replace=True)
    
    over = round(float((sims > line).mean() * 100), 1)
    
    return {
        "mean": round(float(np.mean(sims)), 2),
        "median": round(float(np.median(sims)), 2),
        "std": round(float(np.std(arr, ddof=1)), 2),
        "q25": round(float(np.percentile(sims, 25)), 1),
        "q75": round(float(np.percentile(sims, 75)), 1),
        "over": f"{over}%",
        "under": f"{round(100 - over, 1)}%",
        "edge": f"{round(over - 50, 1)}%",
        "sample_warning": None,
    }

def weighted_projection(values):
    if not values:
        return 0.0
    recent = values[:5]
    earlier = values[5:10]
    if not earlier:
        return round(stats.mean(recent), 1)
    return round((stats.mean(recent) * 0.6) + (stats.mean(earlier) * 0.4), 1)

def ceiling_floor(values):
    if not values:
        return "N/A", "N/A"
    if len(values) < 3:
        return max(values), min(values)
    s = sorted(values)
    return round(stats.mean(s[-3:]), 1), round(stats.mean(s[:3]), 1)

def upcoming_match_url(profile_html: str, current_team: str, opponent: str):
    target = norm(opponent)
    team = norm(current_team)
    soup = BeautifulSoup(profile_html, "html.parser")
    candidates = []
    
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("/matches/"):
            continue
        blob = " ".join([href, a.get_text(" ")])
        if target and target in norm(blob):
            candidates.append(urljoin(HLTV_BASE, href))
    
    for url in candidates:
        if not team or team in norm(url):
            return url
    
    return candidates[0] if candidates else None

def match_context(match_url: str, current_team: str):
    out = {
        "Match odds": "N/A",
        "Moneyline": "N/A",
        "Moneyline american": "N/A",
        "Opponent ranking": "N/A",
        "Likely maps": {},
        "Veto": [],
    }
    
    if not match_url:
        return out
    
    analytics_url = match_url.replace("/matches/", "/betting/analytics/")
    analytics_html, _ = fetch(analytics_url, render=True)
    match_html, _ = fetch(match_url, render=True)
    
    if analytics_html:
        text = visible_text(analytics_html)
        title = re.search(r"([A-Za-z0-9 .\-]+) vs\. ([A-Za-z0-9 .\-]+) odds", text, re.I)
        bests = re.findall(r"Best odds\s*-\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
        
        if title and len(bests) >= 2:
            t1, t2 = title.group(1).strip(), title.group(2).strip()
            out["Match odds"] = f"{t1} {bests[0]} | {t2} {bests[1]}"
            
            if norm(current_team) == norm(t1):
                out["Moneyline"] = bests[0]
            elif norm(current_team) == norm(t2):
                out["Moneyline"] = bests[1]
            
            if out["Moneyline"] != "N/A":
                dec = fnum(out["Moneyline"], 0.0)
                if dec > 1:
                    prob = 1 / dec
                    if prob >= 0.5:
                        out["Moneyline american"] = f"{-round((prob / (1 - prob)) * 100):+d}"
                    else:
                        out["Moneyline american"] = f"{round(((1 - prob) / prob) * 100):+d}"
    
    if match_html:
        text = visible_text(match_html)
        ranks = re.findall(r"World rank:\s*#(\d+)", text, re.I)
        
        if len(ranks) >= 2:
            title = BeautifulSoup(match_html, "html.parser").title
            title_txt = clean(title.get_text(" ")) if title else ""
            tm = re.search(r"([A-Za-z0-9 .\-]+) vs\. ([A-Za-z0-9 .\-]+)", title_txt)
            
            if tm:
                t1, t2 = tm.group(1).strip(), tm.group(2).strip()
                if norm(current_team) == norm(t1):
                    out["Opponent ranking"] = f"#{ranks[1]}"
                elif norm(current_team) == norm(t2):
                    out["Opponent ranking"] = f"#{ranks[0]}"
        
        # **FIXED: Guard veto parsing with None checks**
        veto = []
        for line in visible_lines(match_html):
            if (re.match(r"\d+\.\s+.+\s+(removed|picked)\s+.+", line, re.I) or
                line.endswith("was left over")):
                veto.append(line)
        out["Veto"] = veto[:7]
        
        picked = []
        for line in veto:
            if "picked" not in line.lower():
                continue
            mm = re.search(
                r"(Ancient|Anubis|Dust2|Inferno|Mirage|Nuke|Overpass|Vertigo|Train)",
                line,
                re.I
            )
            if mm:
                picked.append(mm.group(1).title())
        
        out["Likely maps"] = {f"Map {i+1}": m for i, m in enumerate(picked[:3])}
    
    return out

def similar_team_note(vs_top: dict, opponent_rank_text: str):
    if not vs_top:
        return "N/A"
    
    rk = opponent_rank_text.replace("#", "") if opponent_rank_text and opponent_rank_text != "N/A" else ""
    opp_rank = int(rk) if rk.isdigit() else None
    
    if opp_rank is None:
        if 50 in vs_top and vs_top[50]["rating"] != "-":
            return f"Vs Top 50: {vs_top[50]['rating']} rating over {vs_top[50]['maps']} maps"
        return "N/A"
    
    for cutoff in (5, 10, 20, 30, 50):
        if opp_rank <= cutoff and cutoff in vs_top and vs_top[cutoff]["rating"] != "-":
            return f"Vs Top {cutoff}: {vs_top[cutoff]['rating']} rating over {vs_top[cutoff]['maps']} maps"
    
    if 50 in vs_top and vs_top[50]["rating"] != "-":
        return f"Vs Top 50: {vs_top[50]['rating']} rating over {vs_top[50]['maps']} maps"
    
    return "Opponent outside top-50 bucket; use direct recent sample + H2H"

def grade_pick(proj, median_val, hit_rate, line, role, h2h_avg, moneyline):
    """
    **FIXED: Better moneyline logic that considers opponent odds, not just your team's.
    """
    side = "NO BET"
    
    if proj >= line + 1.5 and median_val >= line + 1.0 and hit_rate >= 60:
        side = "OVER"
    elif proj <= line - 1.5 and median_val <= line - 1.0 and hit_rate <= 40:
        side = "UNDER"
    
    score = 5.0
    score += min(2.0, abs(proj - line) / 2.0)
    score += min(1.25, abs(median_val - line) / 3.0)
    
    if hit_rate >= 70:
        score += 1.5
    elif hit_rate >= 60:
        score += 1.0
    elif hit_rate <= 30:
        score += 1.0
    elif hit_rate <= 40:
        score += 0.5
    
    if side == "OVER" and role in {"Primary AWPer", "Star Entry Rifler", "Entry / Space Creator", "Flex Rifler"}:
        score += 0.4
    
    if side == "UNDER" and role == "Support / Anchor":
        score += 0.4
    
    if h2h_avg is not None:
        if side == "OVER" and h2h_avg > line:
            score += 0.4
        if side == "UNDER" and h2h_avg < line:
            score += 0.4
    
    # **FIXED: Better moneyline logic**
    ml = fnum(moneyline, 0.0)
    if ml > 0 and ml != 0.0:
        your_prob = 1 / ml
        # Heavy favorite (>70% win prob) = stomp risk
        if side == "OVER" and your_prob > 0.70:
            score -= 0.35
        elif side == "UNDER" and your_prob > 0.70:
            score += 0.25
        # Close match bonus for overs
        if side == "OVER" and 0.45 < your_prob < 0.55:
            score += 0.25
    
    if side == "NO BET":
        score = max(4.8, min(score, 6.0))
    
    score = round(max(1.0, min(10.0, score)), 1)
    
    if score >= 8.5:
        label = "🔥 ELITE EDGE"
    elif score >= 7.5:
        label = "✅ STRONG PLAY"
    elif score >= 6.5:
        label = "👍 SOLID LEAN"
    elif score >= 5.5:
        label = "⚖️ SMALL EDGE"
    else:
        label = "❌ NO BET"
    
    return side, f"{score}/10 {label}", score

def get_player_info(player_name, line=0.0, opponent="N/A"):
    try:
        found = search_player(player_name)
        if not found:
            return error_response(f"Could not find player '{player_name}' on HLTV.", player_name, line, opponent)
        
        pid, slug, display = found
        
        profile_html, _ = fetch(f"{HLTV_BASE}/player/{pid}/{slug}", render=True)
        if not profile_html:
            return error_response("Profile page blocked or unavailable.", display, line, opponent)
        
        stats_html, _ = fetch(f"{HLTV_BASE}/stats/players/{pid}/{slug}", render=True)
        if not stats_html:
            return error_response("Stats page blocked or unavailable.", display, line, opponent)
        
        profile = profile_metrics(profile_html)
        stats_page = stats_metrics(stats_html)
        current_team = profile["team"]
        role = derive_role(profile)
        
        team_info = {"HLTV Rank": "N/A", "Valve Rank": "N/A"}
        if profile["team_url"]:
            team_html, _ = fetch(profile["team_url"], render=True)
            if team_html:
                team_info = team_rank(team_html)
        
        series_rows = build_recent_series(pid, slug, display, current_team, limit=10)
        
        if len(series_rows) < 5:
            return error_response(
                f"Only found {len(series_rows)} recent BO3 series with full HLTV stats.",
                display, line, opponent
            )
        
        raw_maps = flat_raw_maps(series_rows)
        recent_totals = [x["kills"] for x in series_rows]
        recent_hs = [x["headshots"] for x in series_rows]
        recent_rounds = [x["rounds"] for x in series_rows]
        
        avg_kills = round(stats.mean(recent_totals), 1)
        med_kills = round(stats.median(recent_totals), 1)
        proj_kills = weighted_projection(recent_totals)
        
        avg_hs = round(stats.mean(recent_hs), 1)
        med_hs = round(stats.median(recent_hs), 1)
        proj_hs = weighted_projection(recent_hs)
        
        recent_hs_pct = round((sum(recent_hs) / max(1, sum(recent_totals))) * 100, 1)
        
        boot = bootstrap(recent_totals, line)
        ceil_val, floor_val = ceiling_floor(recent_totals)
        
        hit_rate = (
            round((sum(1 for x in recent_totals if x > line) / len(recent_totals)) * 100, 1)
            if line > 0 else 0.0
        )
        
        upcoming = upcoming_match_url(profile_html, current_team, opponent)
        live_match = match_context(upcoming, current_team)
        
        # **FIXED: H2H with date filtering and minimum sample**
        h2h_rows = [x for x in series_rows if norm(x["opponent"]) == norm(opponent)]
        cutoff_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        h2h_recent = [x for x in h2h_rows if x.get("date", "") >= cutoff_date]
        h2h_to_use = h2h_recent if len(h2h_recent) >= 2 else h2h_rows
        
        h2h_avg = (
            round(stats.mean([x["kills"] for x in h2h_to_use]), 1)
            if len(h2h_to_use) >= 2 else None
        )
        h2h_hs = (
            round(stats.mean([x["headshots"] for x in h2h_to_use]), 1)
            if len(h2h_to_use) >= 2 else None
        )
        
        side, grade_str, grade_num = grade_pick(
            proj_kills, med_kills, hit_rate, line, role, h2h_avg,
            live_match["Moneyline"]
        )
        
        mispriced = "NO"
        if line > 0:
            if proj_kills - line >= 4:
                mispriced = "YES - OVER VALUE"
            elif line - proj_kills >= 4:
                mispriced = "YES - UNDER VALUE"
        
        scenarios = {}
        official_kpr = fnum(stats_page["KPR"], 0.0)
        if official_kpr > 0:
            for tag, rounds in (("short", 38), ("normal", 44), ("long", 50)):
                scenarios[tag] = {
                    "rounds_per_map": rounds // 2,
                    "total_rounds": rounds,
                    "expected_kills": round(official_kpr * rounds, 1),
                }
        
        return {
            "Player": display,
            "Match": f"vs {opponent.title()}",
            "Team": current_team,
            "Team ranking": team_info["HLTV Rank"],
            "Valve ranking": team_info["Valve Rank"],
            "Opponent ranking": live_match["Opponent ranking"],
            "Match odds": live_match["Match odds"],
            "Moneyline": live_match["Moneyline"],
            "Moneyline american": live_match["Moneyline american"],
            "Role": role,
            "Recent sample used": f"Last {len(series_rows)} BO3 series (maps 1-2 only)",
            "Recent average": avg_kills,
            "Recent median": med_kills,
            "Recent projection": proj_kills,
            "Hit rate": f"{hit_rate}%",
            "Rating 3.0": profile["rating_3"],
            "Firepower": profile["firepower"],
            "Entrying": profile["entrying"],
            "Trading": profile["trading"],
            "Opening": profile["opening"],
            "Clutching": profile["clutching"],
            "Sniping": profile["sniping"],
            "Utility": profile["utility"],
            "KPR": stats_page["KPR"],
            "DPR": stats_page["DPR"],
            "ADR": stats_page["ADR"],
            "KAST": stats_page["KAST"],
            "Impact": stats_page["Impact"],
            "Opening KPR": stats_page["Opening KPR"],
            "Trade KPR": stats_page["Trade KPR"],
            "Round Swing": stats_page["Round Swing"],
            "Multi-kill %": stats_page["Multi-kill %"],
            "Similar teams": similar_team_note(stats_page["vs_top"], live_match["Opponent ranking"]),
            "Ceiling (Top 3)": ceil_val,
            "Floor (Bottom 3)": floor_val,
            "Average rounds (M1+M2)": round(stats.mean(recent_rounds), 1),
            "Scenarios": scenarios,
            "Likely maps": live_match["Likely maps"],
            "Veto": live_match["Veto"],
            "Per-map averages": per_map_averages(raw_maps),
            "H2H Data": {
                "h2h_sample_size": len(h2h_to_use),
                "h2h_avg_kills": h2h_avg if h2h_avg is not None else "N/A",
                "h2h_avg_headshots": h2h_hs if h2h_hs is not None else "N/A",
                "h2h_note": f"{len(h2h_to_use)} recent BO3 meeting(s) in sample (within 60 days)"
                if h2h_to_use else "No recent H2H in sampled set",
            },
            "Simulated mean": boot["mean"],
            "Simulated median": boot["median"],
            "Std Dev": boot["std"],
            "25th percentile": boot["q25"],
            "75th percentile": boot["q75"],
            "Over probability": boot["over"],
            "Under probability": boot["under"],
            "Edge vs line": boot["edge"],
            "Mispriced or not": mispriced,
            "Final grade": grade_str,
            "Grade numeric": grade_num,
            "Bet recommendation": side,
            "Recent Totals (M1+M2 Combined)": recent_totals,
            "Recent HS Totals (M1+M2)": recent_hs,
            "Recent HS Average": avg_hs,
            "Recent HS Median": med_hs,
            "Recent HS Projection": proj_hs,
            "Recent HS %": f"{recent_hs_pct}%",
            "All-time profile HS %": profile["all_time_hs_pct"],
            "Paired series rows": [
                {
                    "opponent": x["opponent"],
                    "date": x["date"],
                    "kills": x["kills"],
                    "headshots": x["headshots"],
                    "rounds": x["rounds"],
                    "map1": x["map1"],
                    "map2": x["map2"],
                }
                for x in series_rows
            ],
            "Raw maps": raw_maps,
            "Current match url": upcoming or "N/A",
        }
    
    except Exception as exc:
        return error_response(f"System crash: {exc}", player_name, line, opponent)
