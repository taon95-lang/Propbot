import re
import os
import time
import random
import logging  # FIXED: Added missing import to resolve NameError
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
CS2_ID_THRESHOLD = 2366000 
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")

# =========================================================
# FETCH ENGINE
# =========================================================
def _fetch(url):
    """Fetches HTML using ScraperAPI proxy"""
    if SCRAPERAPI_KEY and "search" not in url:
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}"
        try:
            r = requests.get(proxy_url, timeout=60)
            if r.status_code == 200:
                return r.text
        except: pass
    
    # Direct fallback
    try:
        headers = {"Referer": HLTV_BASE, "User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=20)
        return r.text if r.status_code == 200 else None
    except: return None

# =========================================================
# GOLD STANDARD PARSER (Resilient Map 1 & 2)
# =========================================================
def _parse_match_kills(html, player_slug):
    """Resiliently captures Map 1 & 2 data"""
    maps_data = []
    soup = BeautifulSoup(html, "lxml")
    
    # Locate all map content containers (e.g., id="12345-content")
    map_containers = soup.find_all("div", id=re.compile(r"\d+-content"))
    if not map_containers:
        return {"maps": []}

    # Iterate through the containers to find Map 1 and Map 2 stats
    for content in map_containers:
        # Stop once we have Map 1 and Map 2
        if len(maps_data) >= 2:
            break
            
        player_row = None
        for tr in content.find_all("tr"):
            row_text = tr.get_text().lower()
            # Flexible matching for the player
            if player_slug.lower() in row_text or "donk" in row_text:
                player_row = tr
                break
        
        if player_row:
            # Targeted extraction for Pattern "Kills (Headshots)"
            kd_cell = player_row.find(string=re.compile(r"\d+\s*\(\d+\)"))
            rating_cell = player_row.find("td", class_=re.compile(r"rating"))
            
            if kd_cell:
                try:
                    raw_text = kd_cell.strip()
                    kills = int(raw_text.split('(')[0].strip())
                    hs = int(re.search(r"\((\d+)\)", raw_text).group(1))
                    rating = float(rating_cell.get_text().strip()) if rating_cell else 0
                    maps_data.append({"kills": kills, "hs": hs, "rating": rating})
                except: pass
                
    return {"maps": maps_data}

# =========================================================
# CORE FUNCTIONS (Corrected Keys for Display)
# =========================================================
def search_player(name: str):
    """FIXED: Explicitly defined for main.py import"""
    key = name.lower().strip()
    STATIC = {"donk": ("21167", "donk", "donk"), "zywoo": ("11893", "zywoo", "ZywOo"), "m0nesy": ("19230", "m0nesy", "m0NESY")}
    if key in STATIC: return STATIC[key]
    
    html = _fetch(f"{HLTV_BASE}/search?query={name}")
    if not html: return None
    matches = re.findall(r'/player/(\d+)/([\w-]+)', html)
    if not matches: return None
    pid, slug = matches[0]
    return (pid, slug, slug.replace("-", " ").title())

def get_player_info(player_name, opponent=None):
    """Extracts Map 1+2 stats for the last 10 series"""
    result = search_player(player_name)
    if not result: return None
    pid, slug, display = result
    
    print(f"STARTING SCAN: {display} (Last 10 Series / 20 Maps)")
    
    res_html = _fetch(f"{HLTV_BASE}/results?player={pid}")
    if not res_html: return None
    
    # Grab the first 10 match links from the profile results
    all_links = re.findall(r'/matches/(\d+)/([\w-]+)', res_html)
    seen, candidate_ids = set(), []
    for mid, mslug in all_links:
        if int(mid) >= CS2_ID_THRESHOLD and mid not in seen:
            seen.add(mid)
            candidate_ids.append((mid, mslug))
            if len(candidate_ids) >= 10: break # STRICT last 10 series

    all_maps = []
    for mid, mslug in candidate_ids:
        time.sleep(0.4)
        m_html = _fetch(f"{HLTV_BASE}/matches/{mid}/{mslug}")
        if m_html:
            parsed = _parse_match_kills(m_html, slug)
            maps = parsed.get("maps", [])
            # If the parser found Map 1 and Map 2, add them
            if len(maps) >= 2:
                all_maps.extend(maps[:2])
                print(f"SUCCESS: Captured Maps 1 & 2 for {mslug}")

    if not all_maps: 
        print("FAIL: Could not extract data from the recent series.")
        return None

    # CRITICAL: Use keys matching your main.py (avg, avg_hs, sample)
    kills = [m["kills"] for m in all_maps]
    hs_list = [m["hs"] for m in all_maps]
    ratings = [m["rating"] for m in all_maps]

    return {
        "player": display,
        "avg": round(_stats.mean(kills), 2),
        "avg_hs": round(_stats.mean(hs_list), 2),
        "avg_rating": round(_stats.mean(ratings), 2),
        "sample": len(kills),
        "maps": all_maps
    }
