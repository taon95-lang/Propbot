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
# FETCH ENGINE (ScraperAPI enabled for all)
# =========================================================
def _fetch(url):
    global _SESSION
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": HLTV_BASE,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }

    # FIX: Use ScraperAPI for EVERYTHING, especially searches
    if SCRAPERAPI_KEY:
        try:
            proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}&render=false"
            r = requests.get(proxy_url, timeout=60)
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text, r.url # Return text AND the final URL
            print(f"SCRAPERAPI FAIL: {r.status_code}")
        except Exception as e:
            print(f"SCRAPERAPI ERROR: {e}")

    for attempt in range(3):
        try:
            r = _SESSION.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            if "Just a moment" in r.text or "Checking your browser" in r.text:
                _rotate_session()
                time.sleep(3)
                continue
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text, r.url
            if r.status_code in [403, 429]:
                _rotate_session()
            time.sleep(2)
        except:
            _rotate_session()
            time.sleep(1)
    return None, None

# =========================================================
# RESILIENT SEARCH
# =========================================================
def search_player(name: str):
    if not name: return None
    
    url = f"{HLTV_BASE}/search?query={name.strip()}"
    html, final_url = _fetch(url)
    if not html: return None

    # FIX: Check if we were redirected straight to a player profile
    # Final URL looks like: https://www.hltv.org/player/21167/donk
    redirect_match = re.search(r'/player/(\d+)/([^/]+)', final_url)
    if redirect_match:
        pid, slug = redirect_match.groups()
        return (pid, slug, slug.replace("-", " ").title())

    # Pattern 1: Standard search results list
    matches = re.findall(r'/player/(\d+)/([^"]+)', html)
    
    # Pattern 2: Stats links
    if not matches:
        matches = re.findall(r'/stats/players/(\d+)/([^"]+)', html)

    if not matches:
        print(f"SEARCH FAILED: No matches found for {name}")
        return None

    pid, slug = matches[0]
    slug = slug.split('?')[0].split('&')[0] # Clean slug
    return (pid, slug, slug.replace("-", " ").title())

# =========================================================
# ACCURATE PARSING
# =========================================================
def _parse_match_kills(html, player_slug):
    maps_data = []
    soup = BeautifulSoup(html, PARSER)
    map_containers = soup.find_all("div", {"id": re.compile(r'map-stats-\d+')})
    
    if not map_containers:
        map_containers = soup.find_all("table", {"class": "stats-table"})

    slug_lower = player_slug.lower()

    for container in map_containers:
        # Round detection
        rounds = 24
        header = container.find_previous("div", {"class": "bold"})
        if header:
            nums = re.findall(r'\d+', header.text)
            if len(nums) >= 2: rounds = sum(int(n) for n in nums)

        rows = container.find_all("tr")
        for tr in rows:
            row_text = tr.get_text(" ", strip=True).lower()
            if slug_lower not in row_text:
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
# THE GOLD SCAN
# =========================================================
def get_player_info(player_name, line=0.0, opponent="N/A"):
    result = search_player(player_name)
    if not result:
        print(f"SEARCH ERROR: Could not find player '{player_name}'")
        return None

    pid, slug, display = result
    print(f"SCANNING: {display} (ID: {pid})")
    
    # Get last 10 series
    url = f"{HLTV_BASE}/results?player={pid}"
    res_html, _ = _fetch(url)
    if not res_html: return None
    match_ids = re.findall(r'/matches/(\d+)/([\w-]+)', res_html)[:10]

    all_series = []
    for mid, mslug in match_ids:
        m_html, _ = _fetch(f"{HLTV_BASE}/matches/{mid}/{mslug}")
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

    totals = [s["kills"] for s in all_series]
    avg_series = round(_stats.mean(totals), 2)
    median_series = _stats.median(totals)
    stdev = round(_stats.stdev(totals), 2) if len(totals) > 1 else 0
    kpr = round(sum(s["kills"] for s in all_series) / sum(s["rounds"] for s in all_series), 2)
    
    # Simple Round Projection
    proj_rounds = 44 if "close" in opponent.lower() else 42
    expected_kills = round(kpr * proj_rounds, 1)
    hits = sum(1 for t in totals if t > line)
    hit_rate = round((hits / len(totals)) * 100, 1)
    
    return {
        "Player": display,
        "Match": f"vs {opponent}",
        "Prop": f"{line} Kills (M1+M2)",
        "Recent average": avg_series,
        "Recent median": median_series,
        "Hit rate": f"{hit_rate}%",
        "Projected rounds": proj_rounds,
        "Expected kills": expected_kills,
        "Standard deviation": stdev,
        "Final grade": f"{hits}/{len(totals)}",
        "Recommendation": "OVER" if expected_kills > line and hit_rate > 60 else "UNDER",
        "Recent totals": totals
    }

if __name__ == "__main__":
    data = get_player_info("donk", line=32.5, opponent="Vitality")
    if data:
        print(data)
