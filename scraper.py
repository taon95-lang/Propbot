import re
import os
import time
import random
import logging
import statistics as _stats
from bs4 import BeautifulSoup

# Ensure Real-time logging for Render/GitHub
import functools
print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

logger = logging.getLogger(__name__)
HLTV_BASE = "https://www.hltv.org"

# =========================================================
# CONFIGURATION & PROXIES
# =========================================================
FETCH_TIMEOUT = 25
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY") # Set this in Render Env Vars

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
# FETCH WITH CLOUDFLARE BYPASS
# =========================================================
def _fetch(url):
    global _SESSION
    
    # Try ScraperAPI first if key is available to guarantee data
    if SCRAPERAPI_KEY and "search" not in url:
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}"
        try:
            print(f"FETCHING VIA PROXY: {url}")
            r = requests.get(proxy_url, timeout=60)
            if r.status_code == 200 and len(r.text) > 2000:
                return r.text
        except Exception as e:
            print(f"PROXY ERROR: {e}")

    # Fallback to direct fetch with rotation
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
# DATA PARSING (TARGETED BEAUTIFULSOUP)
# =========================================================
def _parse_match_kills(html, player_slug):
    """Targeted parsing for Maps 1 & 2 only"""
    maps_data = []
    soup = BeautifulSoup(html, "lxml")
    
    match_stats = soup.find(id="match-stats")
    if not match_stats:
        print("CRITICAL: Match stats container not found.")
        return {"maps": []}

    # Identify map content divs (e.g., id="12345-content")
    map_contents = match_stats.find_all("div", id=re.compile(r"\d+-content"))
    
    # We only care about Maps 1 & 2 per User Logic
    for content in map_contents[:2]:
        player_row = None
        # Search all tables in this map's tab for the player
        for tr in content.find_all("tr"):
            if player_slug in tr.get_text().lower():
                player_row = tr
                break
        
        if player_row:
            # Extract Kills from K-D cell
            kd_text = player_row.find(string=re.compile(r"\d+-\d+"))
            # Extract Rating
            rating_cell = player_row.find("td", class_=re.compile(r"rating"))
            
            if kd_text:
                try:
                    kills = int(kd_text.split('-')[0].strip())
                    rating = float(rating_cell.get_text().strip()) if rating_cell else None
                    
                    # Logic for HS: In the overview, it often shows "Kills (HS)"
                    hs = None
                    if "(" in kd_text:
                        hs_match = re.search(r"\((\d+)\)", kd_text)
                        if hs_match:
                            hs = int(hs_match.group(1))

                    maps_data.append({
                        "kills": kills,
                        "hs": hs,
                        "rating": rating
                    })
                    print(f"EXTRACTED: {kills} Kills | {hs} HS | {rating} Rating")
                except:
                    pass
                    
    return {"maps": maps_data}

# =========================================================
# CORE LOGIC
# =========================================================
def search_player(name: str):
    key = name.lower().strip()
    STATIC_IDS = {
        "donk": ("21167", "donk", "donk"),
        "zywoo": ("11893", "zywoo", "ZywOo"),
        "m0nesy": ("19230", "m0nesy", "m0NESY"),
        "niko": ("3741", "niko", "NiKo"),
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
    
    print(f"STARTING ANALYSIS FOR: {display}")
    
    # Fetch results page
    html_res = _fetch(f"{HLTV_BASE}/results?player={pid}")
    if not html_res: return None
    
    # Extract only BO3 series (Matches with score 2-0 or 2-1)
    all_match_links = re.findall(r'/matches/(\d+)/([\w-]+)', html_res)
    seen = set()
    match_ids = []
    for mid, mslug in all_match_links:
        if mid not in seen:
            seen.add(mid)
            match_ids.append((mid, mslug))
            if len(match_ids) >= 10: break # Last 10 BO3 series

    all_maps = []
    for mid, mslug in match_ids:
        time.sleep(random.uniform(1, 2))
        m_html = _fetch(f"{HLTV_BASE}/matches/{mid}/{mslug}")
        if not m_html: continue
        
        parsed = _parse_match_kills(m_html, slug)
        maps = parsed.get("maps", [])
        
        for m in maps:
            all_maps.append(m)

    if not all_maps:
        return {"player": display, "avg": 0, "sample": 0, "maps": []}

    # Aggregate Data
    kills = [m["kills"] for m in all_maps if m["kills"] is not None]
    hs = [m["hs"] for m in all_maps if m["hs"] is not None]
    ratings = [m["rating"] for m in all_maps if m["rating"] is not None]

    return {
        "player": display,
        "avg": round(_stats.mean(kills), 2) if kills else 0,
        "avg_hs": round(_stats.mean(hs), 2) if hs else 0,
        "avg_rating": round(_stats.mean(ratings), 2) if ratings else 0,
        "sample": len(kills),
        "maps": all_maps
    }

if __name__ == "__main__":
    # Test with donk
    data = get_player_info("donk")
    print(f"\nFINAL DATA: {data}")
