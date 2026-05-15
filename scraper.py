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
        "Accept-Language": "en-US,en;q=0.5",
    }

    if SCRAPERAPI_KEY and "search" not in url:
        try:
            proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}"
            r = requests.get(proxy_url, timeout=60)
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text
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
                return r.text
            if r.status_code in [403, 429]:
                _rotate_session()
            time.sleep(2)
        except Exception:
            _rotate_session()
            time.sleep(1)
    return None

# =========================================================
# DATA EXTRACTION
# =========================================================
def search_player(name: str):
    if not name: return None
    url = f"{HLTV_BASE}/search?query={name}"
    html = _fetch(url)
    if not html: return None
    matches = re.findall(r'/player/(\d+)/([\w-]+)', html)
    if not matches: return None
    pid, slug = matches[0]
    return (pid, slug, slug.replace("-", " ").title())

def get_player_match_ids(player_id, max_matches=10):
    url = f"{HLTV_BASE}/results?player={player_id}"
    html = _fetch(url)
    if not html: return []
    matches = re.findall(r'/matches/(\d+)/([\w-]+)', html)
    seen = set()
    final = []
    for mid, slug in matches:
        if int(mid) >= CS2_ID_THRESHOLD and mid not in seen:
            seen.add(mid)
            final.append((mid, slug))
    return final[:max_matches]

def _parse_match_kills(html, player_slug):
    """
    SURGICAL FIX: This skips the 'Total Stats' table and grabs individual maps.
    """
    maps_data = []
    try:
        soup = BeautifulSoup(html, PARSER)
    except:
        return {"maps": []}

    # Specifically look for map-specific containers (id="map-stats-1", etc.)
    # This automatically ignores the summary table at the top.
    map_containers = soup.find_all("div", {"id": re.compile(r'map-stats-\d+')})
    
    slug_lower = player_slug.lower()

    for container in map_containers:
        rows = container.find_all("tr")
        for tr in rows:
            row_text = tr.get_text(" ", strip=True)
            if slug_lower not in row_text.lower():
                continue

            # Extract Kills (K-D format)
            kd_match = re.search(r'(\d+)\s*-\s*\d+', row_text)
            if not kd_match: continue
            kills = int(kd_match.group(1))

            # Headshots "(12)"
            hs = 0
            hs_match = re.search(r'\((\d+)\)', row_text)
            if hs_match: hs = int(hs_match.group(1))

            # Rating
            rating = 0.0
            rating_match = re.search(r'(\d\.\d{2})', row_text)
            if rating_match: rating = float(rating_match.group(1))

            maps_data.append({"kills": kills, "hs": hs, "rating": rating})
            # Once we find the player for this map, move to the next map container
            break 
            
    return {"maps": maps_data}

# =========================================================
# CORE LOGIC: GET PLAYER INFO (GOLD SCAN VERSION)
# =========================================================
def get_player_info(player_name, line=0.0, opponent="N/A"):
    result = search_player(player_name)
    if not result: return None

    pid, slug, display = result
    match_ids = get_player_match_ids(pid, max_matches=10)
    if not match_ids: return None

    all_series = []
    for mid, mslug in match_ids:
        url = f"{HLTV_BASE}/matches/{mid}/{mslug}"
        html = _fetch(url)
        if not html: continue

        parsed = _parse_match_kills(html, slug)
        maps = parsed.get("maps", [])
        
        # Only take Maps 1 and 2
        if len(maps) >= 2:
            m1 = maps[0]
            m2 = maps[1]
            all_series.append({
                "total_kills": m1["kills"] + m2["kills"],
                "total_hs": m1["hs"] + m2["hs"],
                "avg_rating": (m1["rating"] + m2["rating"]) / 2
            })
        
        time.sleep(random.uniform(0.5, 1.0))

    if not all_series:
        print("FAIL: Could not extract data from the recent series.")
        return None

    # Calculate Stats on Series Totals (M1+M2)
    series_totals = [s["total_kills"] for s in all_series]
    hs_list = [s["total_hs"] for s in all_series]

    avg_series = round(_stats.mean(series_totals), 2)
    median_series = _stats.median(series_totals)
    stdev = round(_stats.stdev(series_totals), 2) if len(series_totals) > 1 else 0

    # Hit Rate Percentage
    hits = sum(1 for s in series_totals if s > line)
    hit_rate_pct = round((hits / len(series_totals)) * 100, 1)

    # Simple Recommendation
    recommendation = "OVER" if median_series > line else "UNDER"

    return {
        "Player": display,
        "Opponent": opponent,
        "Line (M1+M2)": line,
        "Recent Avg (2-Map)": avg_series,
        "Recent Median": median_series,
        "Hit Rate": f"{hit_rate_pct}%",
        "Avg HS": round(_stats.mean(hs_list), 2) if hs_list else 0,
        "Sample (Series)": len(series_totals),
        "Standard Dev": stdev,
        "Final Grade": f"{hits}/{len(series_totals)}",
        "Recommendation": recommendation,
        "Recent Totals": series_totals
    }

if __name__ == "__main__":
    # Example to match your !scan command
    data = get_player_info("donk", line=32.5, opponent="vitality")
    
    if data:
        print("\n🎯 GOLD SCAN RESULT")
        import json
        print(json.dumps(data, indent=4))
