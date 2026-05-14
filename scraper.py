import re
import os
import time
import random
import logging
import statistics as _stats
from bs4 import BeautifulSoup

# Ensure Real-time logging for Render/GitHub environment visibility
import functools
print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

logger = logging.getLogger(__name__)
HLTV_BASE = "https://www.hltv.org"

# CS2 Launch Threshold (Approximate match ID to filter out CS:GO matches)
CS2_ID_THRESHOLD = 2366000 

# =========================================================
# CONFIGURATION & PROXIES
# =========================================================
FETCH_TIMEOUT = 25
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY") 

_PROFILES = ["chrome116", "chrome110", "chrome107", "safari17_0"]
_profile_idx = 0

def _get_session():
    global _profile_idx
    profile = _PROFILES[_profile_idx]
    try:
        return requests.Session(impersonate=profile)
    except:
        return requests.Session()

_SESSION = _get_session()

def _rotate_session():
    global _SESSION, _profile_idx
    _profile_idx = (_profile_idx + 1) % len(_PROFILES)
    _SESSION = _get_session()
    print(f"ROTATING PROFILE -> {_PROFILES[_profile_idx]}")

# =========================================================
# FETCH WITH CLOUDFLARE BYPASS & JS RENDERING
# =========================================================
def _fetch(url):
    global _SESSION
    
    # Priority 1: ScraperAPI with Javascript Rendering
    if SCRAPERAPI_KEY and "search" not in url:
        # Added &render=true to ensure JS-loaded scorecard tables are visible
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}&render=true"
        try:
            print(f"FETCHING VIA PROXY (JS Render): {url}")
            r = requests.get(proxy_url, timeout=60)
            if r.status_code == 200 and len(r.text) > 2000:
                return r.text
        except Exception as e:
            print(f"PROXY ERROR: {e}")

    # Priority 2: Direct fetch with browser impersonation fallback
    for attempt in range(3):
        try:
            print(f"FETCHING DIRECT: {url}")
            headers = {"Referer": HLTV_BASE, "User-Agent": "Mozilla/5.0"}
            r = _SESSION.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            
            if "Just a moment" in r.text or r.status_code == 403:
                print(f"BLOCKED BY CLOUDFLARE (Status {r.status_code})")
                _rotate_session()
                time.sleep(2)
                continue
                
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text
        except Exception as e:
            print(f"FETCH ERROR: {e}")
            _rotate_session()
            time.sleep(1)
    return None

# =========================================================
# GOLD STANDARD PARSER (Strict BO3, Maps 1-2, and HS)
# =========================================================
def _parse_match_kills(html, player_slug):
    """Targeted parsing for Maps 1 & 2 only, capturing parenthetical HS data"""
    maps_data = []
    # Use lxml for faster, more robust parsing
    soup = BeautifulSoup(html, "lxml")
    
    # 1. Verify BO3 Format: Must have at least 2 played mapholders
    played_maps = soup.find_all("div", class_="mapholder")
    if len(played_maps) < 2:
        print("LOG: Skipping BO1 or Incomplete match.")
        return {"maps": []}

    match_stats = soup.find(id="match-stats")
    if not match_stats:
        print("CRITICAL: Match stats container not found. JS Render may have failed.")
        return {"maps": []}

    # 2. Identify map content divs for Map 1 and Map 2 ONLY
    map_contents = match_stats.find_all("div", id=re.compile(r"\d+-content"))
    
    for content in map_contents[:2]: 
        player_row = None
        # Flexible row matching: checks for slug or name case-insensitively
        for tr in content.find_all("tr"):
            row_text = tr.get_text().lower()
            if player_slug.lower() in row_text:
                player_row = tr
                break
        
        if player_row:
            # 3. Targeted HS Parsing: Looking for Gold Standard Pattern "21 (11)"
            kd_cell = player_row.find(string=re.compile(r"\d+\s*\(\d+\)"))
            rating_cell = player_row.find("td", class_=re.compile(r"rating"))
            
            if kd_cell:
                try:
                    raw_kd = kd_cell.strip()
                    kills = int(raw_kd.split('(')[0].strip())
                    hs = int(re.search(r"\((\d+)\)", raw_kd).group(1))
                    rating = float(rating_cell.get_text().strip()) if rating_cell else None

                    maps_data.append({
                        "kills": kills,
                        "hs": hs,
                        "rating": rating
                    })
                    print(f"SUCCESS: {kills} Kills | {hs} HS | {rating} Rating")
                except Exception as e:
                    print(f"PARSE ERROR in Map: {e}")
                    
    return {"maps": maps_data}

# =========================================================
# CORE LOGIC (CS2 Era Gate & Last 10 BO3)
# =========================================================
def search_player(name: str):
    key = name.lower().strip()
    STATIC_IDS = {
        "donk": ("21167", "donk", "donk"),
        "zywoo": ("11893", "zywoo", "ZywOo"),
        "m0nesy": ("19230", "m0nesy", "m0NESY"),
        "niko": ("3741", "niko", "NiKo"),
        "sh1ro": ("16920", "sh1ro", "sh1ro"),
    }
    if key in STATIC_IDS: return STATIC_IDS[key]

    html = _fetch(f"{HLTV_BASE}/search?query={name}")
    if not html: return None
    matches = re.findall(r'/player/(\d+)/([\w-]+)', html)
    if not matches: return None
    pid, slug = matches[0]
    return (pid, slug, slug.replace("-", " ").title())

def get_player_info(player_name, opponent=None):
    result = search_player(player_name)
    if not result: return None
    pid, slug, display = result
    
    print(f"STARTING ANALYSIS: {display} (CS2 ERA & BO3 ONLY)")
    
    # Fetch results page
    html_res = _fetch(f"{HLTV_BASE}/results?player={pid}")
    if not html_res: return None
    
    # 4. Filter for CS2 IDs and extract Last 10 Series
    all_match_links = re.findall(r'/matches/(\d+)/([\w-]+)', html_res)
    seen = set()
    match_ids = []
    for mid, mslug in all_match_links:
        # Enforce CS2 Era Gate
        if int(mid) >= CS2_ID_THRESHOLD and mid not in seen:
            seen.add(mid)
            match_ids.append((mid, mslug))
            if len(match_ids) >= 10: break # Strict Last 10 BO3

    all_maps = []
    for mid, mslug in match_ids:
        time.sleep(random.uniform(0.5, 1.2)) # Gentle delay
        m_html = _fetch(f"{HLTV_BASE}/matches/{mid}/{mslug}")
        if not m_html: continue
        
        parsed = _parse_match_kills(m_html, slug)
        maps = parsed.get("maps", [])
        for m in maps:
            all_maps.append(m)

    if not all_maps:
        return {"player": display, "avg": 0, "sample": 0, "maps": []}

    # 5. Build Aggregated Stats for Props Analysis
    kill_list = [m["kills"] for m in all_maps if m["kills"] is not None]
    hs_list = [m["hs"] for m in all_maps if m["hs"] is not None]
    rating_list = [m["rating"] for m in all_maps if m["rating"] is not None]

    return {
        "player": display,
        "recent_average": round(_stats.mean(kill_list), 2) if kill_list else 0,
        "recent_median": _stats.median(kill_list) if kill_list else 0,
        "recent_hs_avg": round(_stats.mean(hs_list), 2) if hs_list else 0,
        "recent_rating_avg": round(_stats.mean(rating_list), 2) if rating_list else 0,
        "sample_size": len(kill_list),
        "maps": all_maps
    }

if __name__ == "__main__":
    # Test execution
    data = get_player_info("donk")
    print(f"\n--- FINAL DATA ---\n{data}")
