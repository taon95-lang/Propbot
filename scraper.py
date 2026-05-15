import re
import os
import time
import random
import logging
import statistics as _stats
import functools
from bs4 import BeautifulSoup

# =========================================================
# REALTIME PRINTS FOR RENDER
# =========================================================
print = functools.partial(print, flush=True)

# =========================================================
# REQUESTS (CURL_CFFI for TLS Impersonation)
# =========================================================
try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

# =========================================================
# SETTINGS & GLOBALS
# =========================================================
PARSER = "html.parser" 
HLTV_BASE = "https://www.hltv.org"
CS2_ID_THRESHOLD = 2366000
FETCH_TIMEOUT = 25
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")

_PROFILES = ["chrome116", "chrome110", "chrome107", "chrome99"]
_profile_idx = 0

# =========================================================
# SESSION MANAGEMENT
# =========================================================
def _get_new_session():
    global _profile_idx
    profile = _PROFILES[_profile_idx]
    try:
        return requests.Session(impersonate=profile)
    except:
        return requests.Session()

_SESSION = _get_new_session()

def _rotate_session():
    global _SESSION, _profile_idx
    _profile_idx = (_profile_idx + 1) % len(_PROFILES)
    print(f"ROTATING PROFILE -> {_PROFILES[_profile_idx]}")
    _SESSION = _get_new_session()

# =========================================================
# FETCH ENGINE
# =========================================================
def _fetch(url):
    global _SESSION
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": HLTV_BASE,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }

    if SCRAPERAPI_KEY and "search" not in url:
        try:
            proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}"
            r = requests.get(proxy_url, timeout=60)
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text
        except: pass

    for attempt in range(3):
        try:
            r = _SESSION.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            if "Just a moment" in r.text or "Checking your browser" in r.text:
                _rotate_session()
                time.sleep(3)
                continue
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text
            if r.status_code in [403, 429]:
                _rotate_session()
            time.sleep(2)
        except:
            _rotate_session()
            time.sleep(1)
    return None

# =========================================================
# RESILIENT SEARCH (No ID Required)
# =========================================================
def search_player(name: str):
    if not name: return None
    
    # 1. Try a more direct search endpoint
    url = f"{HLTV_BASE}/search?query={name.strip()}"
    html = _fetch(url)
    if not html: return None

    # Pattern 1: Table row matches (Standard search list)
    matches = re.findall(r'/player/(\d+)/([^"]+)', html)
    
    # Pattern 2: Result links (If page is a redirect or specific layout)
    if not matches:
        matches = re.findall(r'href="/stats/players/(\d+)/([^"]+)"', html)

    if not matches:
        # Final fallback: BeautifulSoup search for any link containing '/player/'
        soup = BeautifulSoup(html, PARSER)
        for a in soup.find_all('a', href=True):
            if '/player/' in a['href']:
                parts = a['href'].split('/')
                if len(parts) >= 4:
                    matches.append((parts[2], parts[3]))
                    break

    if not matches:
        print(f"DEBUG: Search failed for {name}. Content length: {len(html)}")
        return None

    pid, slug = matches[0]
    # Clean slug (remove query params if any)
    slug = slug.split('?')[0].split('&')[0]
    return (pid, slug, slug.replace("-", " ").title())

# =========================================================
# ACCURATE PARSING (Skip Summary Table)
# =========================================================
def _parse_match_kills(html, player_slug):
    maps_data = []
    soup = BeautifulSoup(html, PARSER)

    # Use map-specific containers to ignore the "Total" row duplicates
    map_containers = soup.find_all("div", {"id": re.compile(r'map-stats-\d+')})
    
    if not map_containers:
        map_containers = soup.find_all("table", {"class": "stats-table"})

    for container in map_containers:
        # Find rounds played on this map
        rounds = 24 # Default
        header = container.find_previous("div", {"class": "bold"})
        if header:
            nums = re.findall(r'\d+', header.text)
            if len(nums) >= 2: rounds = sum(int(n) for n in nums)

        rows = container.find_all("tr")
        for tr in rows:
            row_text = tr.get_text(" ", strip=True).lower()
            if player_slug.lower() not in row_text:
                continue

            kd_match = re.search(r'(\d+)\s*-\s*\d+', tr.get_text())
            if not kd_match: continue
            kills = int(kd_match.group(1))

            hs = 0
            hs_match = re.search(r'\((\d+)\)', tr.get_text())
            if hs_match: hs = int(hs_match.group(1))

            rating = 1.0
            r_match = re.search(r'(\d\.\d{2})', tr.get_text())
            if r_match: rating = float(r_match.group(1))

            maps_data.append({"kills": kills, "hs": hs, "rating": rating, "rounds": rounds})
            break 
            
    return {"maps": maps_data}

# =========================================================
# THE GOLD SCAN (Final Formatting)
# =========================================================
def get_player_info(player_name, line=0.0, opponent="N/A"):
    result = search_player(player_name)
    if not result: return None

    pid, slug, display = result
    
    # Get last 10 series
    url = f"{HLTV_BASE}/results?player={pid}"
    res_html = _fetch(url)
    if not res_html: return None
    match_ids = re.findall(r'/matches/(\d+)/([\w-]+)', res_html)[:10]

    all_series = []
    for mid, mslug in match_ids:
        m_html = _fetch(f"{HLTV_BASE}/matches/{mid}/{mslug}")
        if not m_html: continue
        parsed = _parse_match_kills(m_html, slug)
        maps = parsed.get("maps", [])
        
        if len(maps) >= 2:
            m1, m2 = maps[0], maps[1]
            all_series.append({
                "kills": m1["kills"] + m2["kills"],
                "hs": m1["hs"] + m2["hs"],
                "rounds": m1["rounds"] + m2["rounds"]
            })
        time.sleep(0.5)

    if not all_series: return None

    # Core Stats
    totals = [s["kills"] for s in all_series]
    avg_series = round(_stats.mean(totals), 2)
    median_series = _stats.median(totals)
    stdev = round(_stats.stdev(totals), 2) if len(totals) > 1 else 0
    kpr = round(sum(s["kills"] for s in all_series) / sum(s["rounds"] for s in all_series), 2)
    
    # Projection (Assuming standard 21 rounds per map average = 42 rounds)
    proj_rounds = 44 if "close" in opponent.lower() else 42
    expected_kills = round(kpr * proj_rounds, 1)
    
    # Hit Rate & Edge
    hits = sum(1 for t in totals if t > line)
    hit_rate = round((hits / len(totals)) * 100, 1)
    
    return {
        "Player": display,
        "Match": f"vs {opponent}",
        "Prop": f"{line} Kills (M1+M2)",
        "Role": "Fragger", # Standardized
        "Recent average": avg_series,
        "Recent median": median_series,
        "Hit rate": f"{hit_rate}%",
        "Projected rounds": proj_rounds,
        "Expected kills": expected_kills,
        "Simulated mean": avg_series, # Simplified for speed
        "Standard deviation": stdev,
        "Final grade": f"{hits}/{len(totals)}",
        "Bet recommendation": "OVER" if expected_kills > line and hit_rate > 60 else "UNDER",
        "Recent totals": totals
    }

if __name__ == "__main__":
    data = get_player_info("donk", line=32.5, opponent="Vitality")
    if data:
        for k, v in data.items(): print(f"**{k}**: {v}")
