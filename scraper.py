import re
import os
import time
import random
import logging
import statistics as _stats
from bs4 import BeautifulSoup

# Ensure Real-time logging
import functools
print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

logger = logging.getLogger(__name__)
HLTV_BASE = "https://www.hltv.org"
CS2_ID_THRESHOLD = 2366000 

# =========================================================
# FETCH ENGINE
# =========================================================
def _fetch(url):
    SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")
    if SCRAPERAPI_KEY and "search" not in url:
        # No &render=true needed for mapstatsid pages
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}"
        try:
            print(f"FETCHING VIA PROXY: {url[-50:]}")
            r = requests.get(proxy_url, timeout=60)
            if r.status_code == 200: return r.text
        except Exception as e: print(f"PROXY ERROR: {e}")
    
    headers = {"Referer": HLTV_BASE, "User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        return r.text if r.status_code == 200 else None
    except: return None

# =========================================================
# THE "GOLD STANDARD" MAPSTATS PARSER
# =========================================================
def _parse_individual_map_stats(html, player_slug):
    """Parses the static /stats/matches/mapstatsid/ page for Kills and HS"""
    soup = BeautifulSoup(html, "lxml")
    # Find the stats table
    table = soup.find("table", class_="stats-table")
    if not table: return None

    # Identify the K (hs) column
    k_hs_col = None
    headers = table.find("tr").find_all(["th", "td"])
    for i, h in enumerate(headers):
        if "k" in h.get_text().lower() and "hs" in h.get_text().lower():
            k_hs_col = i
            break
    
    if k_hs_col is None: return None

    # Find the player row
    for tr in table.find_all("tr")[1:]:
        if player_slug.lower() in tr.get_text().lower():
            cells = tr.find_all("td")
            kd_text = cells[k_hs_col].get_text(strip=True)
            # Pattern: "21 (11)"
            match = re.search(r"(\d+)\s*\((\d+)\)", kd_text)
            if match:
                return {"kills": int(match.group(1)), "hs": int(match.group(2))}
    return None

# =========================================================
# CORE LOGIC
# =========================================================
def search_player(name: str):
    key = name.lower().strip()
    STATIC = {"donk": ("21167", "donk", "donk"), "zywoo": ("11893", "zywoo", "ZywOo"), "m0nesy": ("19230", "m0nesy", "m0NESY")}
    if key in STATIC: return STATIC[key]
    html = _fetch(f"{HLTV_BASE}/search?query={name}")
    if not html: return None
    matches = re.findall(r'/player/(\d+)/([\w-]+)', html)
    return (matches[0][0], matches[0][1], matches[0][1].replace("-", " ").title()) if matches else None

def get_player_info(player_name, opponent=None):
    res = search_player(player_name)
    if not res: return None
    pid, slug, display = res
    print(f"STARTING GOLD SCAN: {display}")

    # 1. Get Match Results
    html_res = _fetch(f"{HLTV_BASE}/results?player={pid}")
    if not html_res: return None
    
    match_links = re.findall(r'/matches/(\d+)/([\w-]+)', html_res)
    valid_matches = [m for m in match_links if int(m[0]) >= CS2_ID_THRESHOLD][:10]

    all_maps = []
    for mid, mslug in valid_matches:
        # 2. Fetch match page to get Individual Map Stats links
        m_html = _fetch(f"{HLTV_BASE}/matches/{mid}/{mslug}")
        if not m_html: continue
        
        # Look for the "Detailed stats" links (mapstatsid)
        map_stats_links = re.findall(r'/stats/matches/mapstatsid/(\d+)/[\w-]+', m_html)
        
        # Fetch Map 1 and Map 2 specifically
        for msid in map_stats_links[:2]:
            ms_html = _fetch(f"{HLTV_BASE}/stats/matches/mapstatsid/{msid}/_")
            if ms_html:
                stats = _parse_individual_map_stats(ms_html, slug)
                if stats:
                    all_maps.append(stats)
                    print(f"SUCCESS: {stats['kills']} Kills | {stats['hs']} HS")

    if not all_maps: return None

    # 3. Aggregate
    kills = [m["kills"] for m in all_maps]
    hs = [m["hs"] for m in all_maps]
    return {
        "player": display,
        "recent_average": round(_stats.mean(kills), 2),
        "recent_median": _stats.median(kills),
        "recent_hs_avg": round(_stats.mean(hs), 2),
        "sample": len(kills),
        "maps": all_maps
    }
