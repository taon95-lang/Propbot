import re
import os
import time
import random
import logging
import statistics as _stats
from bs4 import BeautifulSoup

# Ensure Real-time logging for Render dashboard visibility
import functools
print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

logger = logging.getLogger(__name__)
HLTV_BASE = "https://www.hltv.org"

# CS2 Era Gate (IDs >= 2,366,000 to filter out old CS:GO data)
CS2_ID_THRESHOLD = 2366000 

# =========================================================
# CONFIGURATION & PROXIES
# =========================================================
FETCH_TIMEOUT = 30
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY") 

_PROFILES = ["chrome116", "chrome110", "safari17_0", "chrome107", "chrome99"]
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
# FETCH WITH JS RENDERING (Required to fix "0 stats")
# =========================================================
def _fetch(url, render_js=False):
    """
    Uses ScraperAPI with &render=true to ensure Javascript-loaded 
    scorecard tables are visible to the parser.
    """
    if SCRAPERAPI_KEY and "search" not in url:
        # Match pages MUST use render=true to see the stats div
        render_param = "&render=true" if render_js else ""
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}{render_param}"
        try:
            print(f"FETCHING VIA PROXY (Render={render_js}): {url[-60:]}")
            r = requests.get(proxy_url, timeout=60)
            if r.status_code == 200:
                return r.text
        except Exception as e:
            print(f"PROXY ERROR: {e}")

    # Fallback for search or direct fetch
    for attempt in range(2):
        try:
            headers = {"Referer": HLTV_BASE, "User-Agent": "Mozilla/5.0"}
            r = _SESSION.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            if "Just a moment" in r.text or r.status_code == 403:
                _rotate_session()
                continue
            return r.text if r.status_code == 200 else None
        except:
            _rotate_session()
    return None

# =========================================================
# GOLD STANDARD PARSER (Maps 1-2, Last 10 BO3, and HS)
# =========================================================
def _parse_match_kills(html, player_slug):
    """Targeted parsing for Maps 1 & 2 only, capturing (hs) data"""
    maps_data = []
    soup = BeautifulSoup(html, "lxml")
    
    # Verify BO3: Must have at least 2 mapholders with results
    played_maps = soup.find_all("div", class_="mapholder")
    if len(played_maps) < 2:
        print("AUDIT: Skipping match - not a BO3 series.")
        return {"maps": []}

    match_stats = soup.find(id="match-stats")
    if not match_stats:
        print("CRITICAL: Stats container NOT FOUND. Check ScraperAPI key.")
        return {"maps": []}

    # Focus only on the first two map containers
    map_containers = match_stats.find_all("div", id=re.compile(r"\d+-content"))
    
    for content in map_containers[:2]:
        player_row = None
        for tr in content.find_all("tr"):
            if player_slug.lower() in tr.get_text().lower():
                player_row = tr
                break
        
        if player_row:
            # Targeted extraction for "Kills (Headshots)" pattern
            kd_cell = player_row.find(string=re.compile(r"\d+\s*\(\d+\)"))
            rating_cell = player_row.find("td", class_=re.compile(r"rating"))
            
            if kd_cell:
                try:
                    text = kd_cell.strip()
                    kills = int(text.split('(')[0].strip())
                    hs = int(re.search(r"\((\d+)\)", text).group(1))
                    rating = float(rating_cell.get_text().strip()) if rating_cell else None
                    
                    maps_data.append({"kills": kills, "hs": hs, "rating": rating})
                    print(f"SUCCESS: {kills} Kills | {hs} HS Captured")
                except:
                    pass
    return {"maps": maps_data}

# =========================================================
# CORE FUNCTIONS (Required by main.py)
# =========================================================
def search_player(name: str):
    """Resolves player ID and Slug (Required for Import)"""
    key = name.lower().strip()
    STATIC = {
        "donk": ("21167", "donk", "donk"),
        "zywoo": ("11893", "zywoo", "ZywOo"),
        "m0nesy": ("19230", "m0nesy", "m0NESY"),
        "niko": ("3741", "niko", "NiKo"),
    }
    if key in STATIC: return STATIC[key]

    html = _fetch(f"{HLTV_BASE}/search?query={name}")
    if not html: return None
    matches = re.findall(r'/player/(\d+)/([\w-]+)', html)
    if not matches: return None
    pid, slug = matches[0]
    return (pid, slug, slug.replace("-", " ").title())

def get_player_info(player_name, opponent=None):
    """Primary entry point for grading workflow"""
    result = search_player(player_name)
    if not result: return None
    pid, slug, display = result
    
    print(f"STARTING GOLD SCAN: {display} (BO3 / CS2 ONLY)")
    
    res_html = _fetch(f"{HLTV_BASE}/results?player={pid}")
    if not res_html: return None
    
    # Filter for CS2 IDs and extract Last 10 Matches
    all_links = re.findall(r'/matches/(\d+)/([\w-]+)', res_html)
    valid_ids = []
    for mid, mslug in all_links:
        if int(mid) >= CS2_ID_THRESHOLD:
            valid_ids.append((mid, mslug))
            if len(valid_ids) >= 10: break 

    all_maps = []
    for mid, mslug in valid_ids:
        time.sleep(1) 
        # Match pages MUST use render=True to solve "0 stats" issue
        m_html = _fetch(f"{HLTV_BASE}/matches/{mid}/{mslug}", render_js=True)
        if m_html:
            parsed = _parse_match_kills(m_html, slug)
            all_maps.extend(parsed.get("maps", []))

    if not all_maps:
        return {"player": display, "avg": 0, "sample": 0, "maps": []}

    kill_list = [m["kills"] for m in all_maps]
    hs_list = [m["hs"] for m in all_maps]

    return {
        "player": display,
        "recent_average": round(_stats.mean(kill_list), 2),
        "recent_median": _stats.median(kill_list),
        "recent_hs_avg": round(_stats.mean(hs_list), 2),
        "sample": len(kill_list),
        "maps": all_maps
    }

def get_actual_result(player_name, opponent, grade_ts, line, baseline_match_id=None):
    """Placeholder for results checking — add logic as needed"""
    return None

def get_matchup_adjustment(opponent_name):
    """Placeholder for matchup adjustments"""
    return None

if __name__ == "__main__":
    print(get_player_info("donk"))
