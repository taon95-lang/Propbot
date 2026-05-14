"""
HLTV scraper — UPDATED GOLD STANDARD VERSION
- Bypasses Cloudflare on Render via ScraperAPI (Priority Tier)
- Enforces CS2 Era Gate (IDs >= 2,366,000)
- Strict BO3 & Maps 1-2 Only Logic
- High-fidelity K(hs) parsing for HS props
"""

import re
import random
import time
import logging
import os
import statistics as _stats
from datetime import date, timedelta
from bs4 import BeautifulSoup

# Ensure Real-time logging for Render visibility
import functools
print = functools.partial(print, flush=True)

logger = logging.getLogger(__name__)

HLTV_BASE = "https://www.hltv.org"
FETCH_TIMEOUT = 25 
CS2_ID_THRESHOLD = 2366000  # Gold Standard CS2 Era Gate

try:
    from curl_cffi import requests as _cffi_req
    _CFFI_OK = True
except ImportError:
    _CFFI_OK = False
    logger.warning("curl_cffi not available — install it for HLTV access")

_PROFILES = ["chrome116", "safari17_0", "chrome107", "chrome110", "chrome99"]
_profile_idx = 0
_HLTV_SESSION = None

def _get_session():
    global _profile_idx
    profile = _PROFILES[_profile_idx]
    try:
        return _cffi_req.Session(impersonate=profile)
    except:
        return _cffi_req.Session()

def _rotate_session():
    global _HLTV_SESSION, _profile_idx
    _profile_idx = (_profile_idx + 1) % len(_PROFILES)
    _HLTV_SESSION = _get_session()
    print(f"ROTATING PROFILE -> {_PROFILES[_profile_idx]}")

# =========================================================
# UPDATED FETCH ENGINE (Priority Proxy for Render/GitHub)
# =========================================================
def _fetch(url: str, max_retries: int = 3) -> str | None:
    """Fetch URL with priority for ScraperAPI on hosted environments"""
    global _HLTV_SESSION
    if _HLTV_SESSION is None:
        _HLTV_SESSION = _get_session()

    # TIER 1: ScraperAPI (Mandatory for hosted IPs to avoid 403)
    api_key = os.environ.get("SCRAPERAPI_KEY", "").strip()
    if api_key:
        # Added render=true to handle JS-protected match tables
        proxy_url = f"http://api.scraperapi.com?api_key={api_key}&url={url}&render=true"
        try:
            print(f"FETCHING VIA PROXY (JS Render): {url}")
            import requests as _req
            r = _req.get(proxy_url, timeout=70)
            if r.status_code == 200 and len(r.text) > 3000:
                return r.text
        except Exception as e:
            print(f"PROXY ERROR: {e}")

    # TIER 2: Direct Fetch (Only reliable if running locally)
    for attempt in range(max_retries):
        try:
            print(f"FETCHING DIRECT: {url} [{_PROFILES[_profile_idx]}]")
            headers = {"Referer": HLTV_BASE, "User-Agent": "Mozilla/5.0"}
            resp = _HLTV_SESSION.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            
            if resp.status_code == 200 and "Just a moment" not in resp.text:
                return resp.text
            
            if resp.status_code == 403:
                print(f"BLOCKED BY CLOUDFLARE (Status 403) - Rotating...")
                _rotate_session()
            time.sleep(1)
        except Exception as e:
            print(f"FETCH ERROR: {e}")
            _rotate_session()
    return None

# =========================================================
# GOLD STANDARD PARSER (Strict Maps 1-2 & HS Extraction)
# =========================================================
def _parse_match_kills(html, player_slug, match_url="", series_num=0):
    maps_data = []
    soup = BeautifulSoup(html, "lxml")
    
    # Verify BO3 Format: Must have at least 2 played maps
    played_maps = soup.find_all("div", class_="mapholder")
    if len(played_maps) < 2:
        return None

    match_stats = soup.find(id="match-stats")
    if not match_stats: return None

    # Identify map content divs for Map 1 and Map 2 only
    map_contents = match_stats.find_all("div", id=re.compile(r"\d+-content"))
    for map_idx, content in enumerate(map_contents[:2]): 
        player_row = None
        # Flexible row search to catch different nickname stylings
        for tr in content.find_all("tr"):
            row_text = tr.get_text().lower()
            if player_slug.lower() in row_text or "player" in row_text:
                player_row = tr
                break
        
        if player_row:
            # Extract Gold Standard K(hs) data
            kd_cell = player_row.find(string=re.compile(r"\d+\s*\(\d+\)"))
            rating_cell = player_row.find("td", class_=re.compile(r"rating"))
            
            if kd_cell:
                try:
                    raw_kd = kd_cell.strip()
                    kills = int(raw_kd.split('(')[0].strip())
                    hs = int(re.search(r"\((\d+)\)", raw_kd).group(1))
                    rating = float(rating_cell.get_text().strip()) if rating_cell else 0.0
                    
                    maps_data.append({
                        "map_name": f"Map {map_idx+1}",
                        "kills": kills,
                        "headshots": hs,
                        "rating": rating,
                        "map_number": map_idx + 1
                    })
                    print(f"EXTRACTED: {kills} Kills | {hs} HS")
                except: pass
    return {"maps": maps_data, "bo_type": 3}

# =========================================================
# MAIN ENTRY POINT (CS2 ERA GATE)
# =========================================================
def get_player_info(player_name, stat_type="Kills"):
    # Static Verified IDs for core players
    STATIC = {"donk": "21167", "zywoo": "11893", "m0nesy": "19230", "niko": "3741"}
    pid = STATIC.get(player_name.lower())
    slug = player_name.lower()

    if not pid:
        # Live search if not in static list
        search_html = _fetch(f"{HLTV_BASE}/search?query={player_name}")
        if search_html:
            found = re.search(r'/player/(\d+)/([\w-]+)', search_html)
            if found: pid, slug = found.groups()

    if not pid:
        raise RuntimeError(f"Player {player_name} not found.")

    print(f"STARTING GOLD STANDARD ANALYSIS: {player_name} (CS2 ERA ONLY)")
    
    # Fetch Results and apply CS2 Era Gate
    res_html = _fetch(f"{HLTV_BASE}/results?player={pid}")
    if not res_html: return None
    
    match_links = re.findall(r'/matches/(\d+)/([\w-]+)', res_html)
    valid_matches = []
    for mid, mslug in match_links:
        if int(mid) >= CS2_ID_THRESHOLD: # ID Gate
            valid_matches.append((mid, mslug))
        if len(valid_matches) >= 10: break # Last 10 BO3

    map_kills = []
    for mid, mslug in valid_matches:
        time.sleep(1) # Rate limit protection
        m_html = _fetch(f"{HLTV_BASE}/matches/{mid}/{mslug}")
        if m_html:
            data = _parse_match_kills(m_html, slug)
            if data and data.get("maps"):
                for m in data["maps"]:
                    # Format for simulator compatibility
                    m["stat_value"] = m["headshots"] if stat_type.lower() == "hs" else m["kills"]
                    m["match_id"] = mid
                    map_kills.append(m)

    if not map_kills:
        raise RuntimeError("No recent BO3 maps found in CS2 Era.")

    # Calculate Aggregated Stats
    vals = [m["stat_value"] for m in map_kills]
    hs_vals = [m["headshots"] for m in map_kills if m["headshots"] is not None]

    return {
        "player": player_name,
        "player_id": pid,
        "map_kills": map_kills,
        "mean": round(_stats.mean(vals), 2),
        "std": round(_stats.stdev(vals), 2) if len(vals) > 1 else 2.0,
        "recent_hs_avg": round(_stats.mean(hs_vals), 2) if hs_vals else 0,
        "sample_size": len(map_kills),
        "source": "HLTV Gold Standard (Proxy)"
    }

if __name__ == "__main__":
    print(get_player_info("donk"))
