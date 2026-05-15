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
PARSER = "html.parser"  # Explicitly using html.parser to avoid lxml issues
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
# FETCH ENGINE (With Diagnostic Logging)
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
            print(f"SCRAPERAPI FETCH: {url}")
            r = requests.get(proxy_url, timeout=60)
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text
            print(f"SCRAPERAPI FAIL: {r.status_code}")
        except Exception as e:
            print(f"SCRAPERAPI ERROR: {e}")

    for attempt in range(3):
        try:
            print(f"FETCHING: {url}")
            r = _SESSION.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            
            # Diagnostic logs for debugging Render/Cloudflare blocks
            print(f"STATUS: {r.status_code} | SIZE: {len(r.text)}")
            
            if "Just a moment" in r.text or "Checking your browser" in r.text:
                print("CLOUDFLARE DETECTED - RETRYING")
                _rotate_session()
                time.sleep(3)
                continue

            if r.status_code == 200 and len(r.text) > 1000:
                return r.text
            
            if r.status_code in [403, 429]:
                print(f"BLOCKED ({r.status_code}) - Content Snippet: {r.text[:200]}")
                _rotate_session()

            time.sleep(2)
        except Exception as e:
            print(f"FETCH ERROR: {e}")
            _rotate_session()
            time.sleep(1)

    return None

# =========================================================
# DATA EXTRACTION
# =========================================================
def search_player(name: str):
    if not name: return None
    key = name.lower().strip()
    
    # Quick Cache for common stars
    STATIC = {
        "donk": ("21167", "donk", "donk"),
        "zywoo": ("11893", "zywoo", "ZywOo"),
        "m0nesy": ("19230", "m0nesy", "m0NESY"),
        "niko": ("3741", "niko", "NiKo")
    }
    if key in STATIC: return STATIC[key]

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

    # Filter for CS2 matches based on ID threshold
    matches = re.findall(r'/matches/(\d+)/([\w-]+)', html)
    seen = set()
    final = []
    for mid, slug in matches:
        if int(mid) >= CS2_ID_THRESHOLD and mid not in seen:
            seen.add(mid)
            final.append((mid, slug))
    
    print(f"CS2 MATCHES FOUND: {len(final)}")
    return final[:max_matches]

def _parse_match_kills(html, player_slug):
    """
    Parses individual map stats from a match page.
    Filters for player rows and extracts Kills, HS, and Rating.
    """
    maps_data = []
    try:
        soup = BeautifulSoup(html, PARSER)
    except Exception as e:
        print(f"SOUP CRASH: {e}")
        return {"maps": []}

    # Locate stat tables specifically to avoid parsing nav/footer noise
    rows = soup.find_all("tr")
    slug_lower = player_slug.lower()

    for tr in rows:
        row_text = tr.get_text(" ", strip=True)
        if slug_lower not in row_text.lower():
            continue

        # Extraction logic using Regex
        kills = None
        kd_match = re.search(r'(\d+)\s*-\s*\d+', row_text)
        if kd_match:
            kills = int(kd_match.group(1))
        
        # Fallback if K-D format is missing
        if kills is None:
            nums = [int(x) for x in re.findall(r'\d+', row_text) if 0 <= int(x) <= 50]
            if nums: kills = nums[0]

        if kills is None: continue

        # Headshot Extraction: Look for "(12)" pattern next to kills
        hs = 0
        hs_match = re.search(r'\((\d+)\)', row_text)
        if hs_match:
            hs = int(hs_match.group(1))

        # Rating Extraction: Usually the last decimal in the row (e.g. 1.24)
        rating = 0.0
        ratings = re.findall(r'(\d\.\d{2})', row_text)
        if ratings:
            try:
                rating = float(ratings[-1])
            except: pass

        maps_data.append({"kills": kills, "hs": hs, "rating": rating})

    return {"maps": maps_data}

# =========================================================
# CORE LOGIC: GET PLAYER INFO
# =========================================================
def get_player_info(player_name, line=None):
    result = search_player(player_name)
    if not result: return None

    pid, slug, display = result
    print(f"SCANNING: {display} (ID: {pid})")

    match_ids = get_player_match_ids(pid, max_matches=10)
    if not match_ids: return None

    all_maps = []
    for mid, mslug in match_ids:
        url = f"{HLTV_BASE}/matches/{mid}/{mslug}"
        html = _fetch(url)
        if not html: continue

        parsed = _parse_match_kills(html, slug)
        maps = parsed.get("maps", [])
        
        # Maps 1-2 only as per gold standard requirement
        if len(maps) >= 2:
            all_maps.extend(maps[:2])
            print(f"ADDED MAPS 1-2 FROM {mslug}")
        
        time.sleep(random.uniform(0.5, 1.2))

    if not all_maps:
        print("FAIL: Could not extract data from the recent series.")
        return None

    # Stats Calculations
    kills = [m["kills"] for m in all_maps]
    hs_list = [m["hs"] for m in all_maps]
    ratings = [m["rating"] for m in all_maps]

    # Combined Stats (Maps 1-2)
    # We group by pairs to get the "Combined" total for the series
    series_totals = []
    for i in range(0, len(kills), 2):
        if i + 1 < len(kills):
            series_totals.append(kills[i] + kills[i+1])

    avg = round(_stats.mean(kills), 2)
    median = _stats.median(kills)
    
    # Hit Rate Calculation if a line is provided
    hit_rate = 0
    if line and series_totals:
        hits = sum(1 for s in series_totals if s > line)
        hit_rate = f"{hits}/{len(series_totals)}"

    return {
        "Player": display,
        "Recent average (Per Map)": avg,
        "Recent median (Per Map)": median,
        "Recent sample used": f"{len(kills)} maps",
        "Series Totals (M1+M2)": series_totals,
        "Hit rate": hit_rate,
        "Avg HS": round(_stats.mean(hs_list), 2) if hs_list else 0,
        "Avg Rating": round(_stats.mean(ratings), 2) if ratings else 0,
    }

if __name__ == "__main__":
    # Test with a line of 35.5 to calculate hit rate
    data = get_player_info("donk", line=35.5)
    import json
    print(json.dumps(data, indent=4))
