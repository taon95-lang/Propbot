import re
import os
import time
import random
import logging
import statistics as _stats
from datetime import date, timedelta
from bs4 import BeautifulSoup

# Ensure Real-time logging for Render dashboard
import functools
print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as _cffi_req
    _CFFI_OK = True
except ImportError:
    _CFFI_OK = False

logger = logging.getLogger(__name__)
HLTV_BASE = "https://www.hltv.org"
FETCH_TIMEOUT = 25 
CS2_ID_THRESHOLD = 2366000 #

# =========================================================
# SESSION & PROFILES
# =========================================================
_PROFILES = ["chrome116", "safari17_0", "chrome107", "chrome110", "chrome99"]
_profile_idx = 0
_HLTV_SESSION = None
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "").strip()

def _get_session():
    global _profile_idx
    profile = _PROFILES[_profile_idx]
    try:
        return _cffi_req.Session(impersonate=profile)
    except:
        return _cffi_req.Session()

_SESSION = _get_session()

def _rotate_session():
    global _SESSION, _profile_idx
    _profile_idx = (_profile_idx + 1) % len(_PROFILES)
    _SESSION = _get_session()
    print(f"ROTATING PROFILE -> {_PROFILES[_profile_idx]}")

# =========================================================
# FETCH ENGINE (ScraperAPI + render=true)
# =========================================================
def _fetch(url, render_js=False):
    """Bypasses Cloudflare using ScraperAPI Render mode"""
    # Priority: ScraperAPI for match/stats pages to ensure JS data visibility
    if SCRAPERAPI_KEY and ("matches" in url or "stats" in url):
        render_param = "&render=true" if render_js else ""
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}{render_param}"
        try:
            print(f"FETCHING VIA PROXY (Render={render_js}): {url[-50:]}")
            r = _cffi_req.get(proxy_url, timeout=60)
            if r.status_code == 200: return r.text
        except Exception as e: print(f"PROXY ERROR: {e}")

    # Fallback: Direct fetch with curl_cffi impersonation
    for attempt in range(2):
        try:
            headers = {"Referer": HLTV_BASE, "User-Agent": "Mozilla/5.0"}
            r = _SESSION.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            if r.status_code == 200 and "Just a moment" not in r.text:
                return r.text
            _rotate_session()
            time.sleep(1)
        except: _rotate_session()
    return None

# =========================================================
# GOLD STANDARD PARSER (Maps 1-2, Last 10 BO3, HS)
# =========================================================
def _parse_match_kills(html, player_slug):
    """Targets Map 1 & 2 and extracts the (hs) column"""
    maps_data = []
    soup = BeautifulSoup(html, "lxml")
    
    # 1. Verify BO3: Must have at least 2 played maps
    if len(soup.find_all("div", class_="mapholder")) < 2:
        return {"maps": []}

    match_stats = soup.find(id="match-stats")
    if not match_stats: return {"maps": []}

    # 2. Isolate Map 1 & 2 containers
    map_containers = match_stats.find_all("div", id=re.compile(r"\d+-content"))
    for content in map_containers[:2]:
        player_row = None
        for tr in content.find_all("tr"):
            if player_slug.lower() in tr.get_text().lower():
                player_row = tr
                break
        
        if player_row:
            # 3. Targeted extraction for "K (hs)"
            kd_cell = player_row.find(string=re.compile(r"\d+\s*\(\d+\)"))
            rating_cell = player_row.find("td", class_=re.compile(r"rating"))
            
            if kd_cell:
                try:
                    text = kd_cell.strip()
                    kills = int(text.split('(')[0].strip())
                    hs = int(re.search(r"\((\d+)\)", text).group(1))
                    rating = float(rating_cell.get_text().strip()) if rating_cell else 0.0
                    maps_data.append({"kills": kills, "hs": hs, "rating": rating})
                    print(f"SUCCESS: {kills} Kills | {hs} HS Captured")
                except: pass
    return {"maps": maps_data}

# =========================================================
# SEARCH & RESOLUTION (Fixes ImportError)
# =========================================================
def search_player(name: str):
    """Primary entry point for main.py"""
    key = name.lower().strip()
    STATIC = {"donk": ("21167", "donk", "donk"), "zywoo": ("11893", "zywoo", "ZywOo"), "m0nesy": ("19230", "m0nesy", "m0NESY")}
    if key in STATIC: return STATIC[key]

    html = _fetch(f"{HLTV_BASE}/search?query={name}")
    if not html: return None
    matches = re.findall(r'/player/(\d+)/([\w-]+)', html)
    if not matches: return None
    pid, slug = matches[0]
    return (pid, slug, slug.replace("-", " ").title())

def get_player_info(player_name, opponent_hint=None):
    """Core analysis logic"""
    result = search_player(player_name)
    if not result: return None
    pid, slug, display = result
    print(f"STARTING ANALYSIS: {display} (BO3 / CS2 ONLY)")

    # Fetch last 10 CS2 Matches
    res_html = _fetch(f"{HLTV_BASE}/results?player={pid}")
    if not res_html: return None
    all_links = re.findall(r'/matches/(\d+)/([\w-]+)', res_html)
    valid_ids = []
    for mid, mslug in all_links:
        if int(mid) >= CS2_ID_THRESHOLD:
            valid_ids.append((mid, mslug))
            if len(valid_ids) >= 10: break

    map_kills = []
    for mid, mslug in valid_ids:
        time.sleep(1)
        # Use render=True for match pages to solve the 0 stats issue
        m_html = _fetch(f"{HLTV_BASE}/matches/{mid}/{mslug}", render_js=True)
        if m_html:
            parsed = _parse_match_kills(m_html, slug)
            map_kills.extend(parsed.get("maps", []))

    if not map_kills: return None

    # Aggregate Results
    kill_vals = [m["kills"] for m in map_kills]
    hs_vals = [m["hs"] for m in map_kills]
    
    return {
        "player": display, "player_id": pid, "map_kills": map_kills,
        "mean": round(_stats.mean(kill_vals), 2),
        "std": round(_stats.stdev(kill_vals), 2) if len(kill_vals) > 1 else 4.0,
        "recent_hs_avg": round(_stats.mean(hs_vals), 2),
        "sample_size": len(kill_vals),
        "source": "HLTV Gold Standard"
    }

if __name__ == "__main__":
    print(get_player_info("donk"))
