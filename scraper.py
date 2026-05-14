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

# CS2 Era Gate (IDs >= 2,366,000 to filter out old CS:GO data)
CS2_ID_THRESHOLD = 2366000 

# =========================================================
# CONFIGURATION & PROXIES
# =========================================================
FETCH_TIMEOUT = 30
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY") 

_PROFILES = ["chrome116", "safari17_0", "chrome107"]
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
# FETCH ENGINE (Optimized for ScraperAPI)
# =========================================================
def _fetch(url):
    global _SESSION
    if SCRAPERAPI_KEY and "search" not in url:
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}"
        try:
            print(f"FETCHING VIA PROXY: {url[-50:]}")
            r = requests.get(proxy_url, timeout=60)
            if r.status_code == 200:
                return r.text
        except Exception as e:
            print(f"PROXY CONNECTION ERROR: {e}")

    headers = {"Referer": HLTV_BASE, "User-Agent": "Mozilla/5.0"}
    try:
        r = _SESSION.get(url, headers=headers, timeout=FETCH_TIMEOUT)
        if "Just a moment" in r.text or r.status_code == 403:
            _rotate_session()
        return r.text if r.status_code == 200 else None
    except:
        return None

# =========================================================
# GOLD STANDARD PARSER (Maps 1-2 & HS)
# =========================================================
def _parse_match_kills(html, player_slug):
    """Targeted parsing for Maps 1 & 2 only, capturing parenthetical HS data"""
    maps_data = []
    soup = BeautifulSoup(html, "lxml")
    
    # Verify BO3 Format
    mapholders = soup.find_all("div", class_="mapholder")
    if len(mapholders) < 2:
        return {"maps": []}

    match_stats = soup.find(id="match-stats")
    if not match_stats:
        return {"maps": []}

    # Identify map content divs (Map 1 & 2 only)
    map_containers = match_stats.find_all("div", id=re.compile(r"\d+-content"))
    
    for content in map_containers[:2]:
        player_row = None
        for tr in content.find_all("tr"):
            if player_slug.lower() in tr.get_text().lower():
                player_row = tr
                break
        
        if player_row:
            # Pattern: "22 (11)" for Kills (HS)
            kd_cell = player_row.find(string=re.compile(r"\d+\s*\(\d+\)"))
            rating_cell = player_row.find("td", class_=re.compile(r"rating"))
            
            if kd_cell:
                try:
                    text = kd_cell.strip()
                    kills = int(text.split('(')[0].strip())
                    hs = int(re.search(r"\((\d+)\)", text).group(1))
                    rating = float(rating_cell.get_text().strip()) if rating_cell else 0
                    
                    maps_data.append({"kills": kills, "hs": hs, "rating": rating})
                except:
                    pass
    return {"maps": maps_data}

# =========================================================
# CORE LOGIC (Updated for 10 Matches / 20 Maps)
# =========================================================
def search_player(name: str):
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
    result = search_player(player_name)
    if not result: return None
    pid, slug, display = result
    
    print(f"STARTING GOLD SCAN: {display} (Last 10 BO3s)")
    
    res_html = _fetch(f"{HLTV_BASE}/results?player={pid}")
    if not res_html: return None
    
    # Filter for CS2 IDs and extract links
    all_links = re.findall(r'/matches/(\d+)/([\w-]+)', res_html)
    seen = set()
    match_ids = []
    for mid, mslug in all_links:
        if int(mid) >= CS2_ID_THRESHOLD and mid not in seen:
            seen.add(mid)
            match_ids.append((mid, mslug))
            if len(match_ids) >= 10: break # Analyzes Last 10 BO3 series

    all_maps = []
    for mid, mslug in match_ids:
        time.sleep(0.5)
        m_html = _fetch(f"{HLTV_BASE}/matches/{mid}/{mslug}")
        if m_html:
            parsed = _parse_match_kills(m_html, slug)
            all_maps.extend(parsed.get("maps", []))

    if not all_maps: return None

    kill_list = [m["kills"] for m in all_maps]
    hs_list = [m["hs"] for m in all_maps]
    rating_list = [m["rating"] for m in all_maps]

    # Return keys configured for bot display
    return {
        "player": display,
        "avg": round(_stats.mean(kill_list), 2), # Combined Maps 1+2 average
        "avg_hs": round(_stats.mean(hs_list), 2),
        "avg_rating": round(_stats.mean(rating_list), 2),
        "sample": len(kill_list), # Should show 20 if 10 BO3s were found
        "maps": all_maps
    }

if __name__ == "__main__":
    print(get_player_info("donk"))
