import re
import os
import statistics as _stats
import functools
from bs4 import BeautifulSoup

# =========================================================
# REALTIME PRINTS FOR RENDER
# =========================================================
print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")

# =========================================================
# FETCH ENGINE (Using ScraperAPI for Unblockable Access)
# =========================================================
def _fetch(url):
    if not SCRAPERAPI_KEY:
        print("CRITICAL: SCRAPERAPI_KEY environment variable is missing.")
        return None, None
    proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}&country_code=us"
    try:
        r = requests.get(proxy_url, timeout=60)
        if r.status_code == 200 and len(r.text) > 1000:
            return r.text, r.headers.get("Sa-Final-Url", url)
    except Exception as e:
        print(f"FETCH ERROR: {e}")
    return None, None

def search_player(name: str):
    name_clean = name.lower().strip()
    STATIC = {
        "donk": ("21167", "donk"), 
        "zywoo": ("11893", "zywoo"), 
        "m0nesy": ("19230", "m0nesy"), 
        "niko": ("3741", "niko")
    }
    if name_clean in STATIC: 
        return STATIC[name_clean][0], STATIC[name_clean][1], STATIC[name_clean][1].title()

    html, final_url = _fetch(f"{HLTV_BASE}/search?query={name_clean}")
    if not html: return None
    if "/player/" in final_url:
        m = re.search(r'/player/(\d+)/([^/]+)', final_url)
        if m: return m.group(1), m.group(2), m.group(2).title()
    matches = re.findall(r'/player/(\d+)/([^"]+)', html)
    if matches:
        pid, slug = matches[0]
        return pid, slug, slug.replace("-", " ").title()
    return None

# =========================================================
# SURGICAL MATCH PAGE PARSER
# =========================================================
def _parse_match_page(html, player_slug):
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table", {"class": "stats-table"})
    
    if not tables:
        return []
        
    # The first table is always the 'Total' summary table. Skip it!
    map_tables = tables[1:]
    slug_lower = player_slug.lower()
    maps_data = []
    
    for table in map_tables:
        if len(maps_data) >= 2: # Only pull Map 1 and Map 2
            break
            
        rounds = 22 # Default fallback
        prev_div = table.find_previous("div")
        if prev_div:
            scores = re.findall(r'\d+', prev_div.get_text())
            if len(scores) >= 2:
                try: rounds = int(scores[-2]) + int(scores[-1])
                except: pass
                if rounds < 13 or rounds > 40: rounds = 22

        rows = table.find_all("tr")
        for tr in rows:
            row_text = tr.get_text(" ", strip=True).lower()
            if slug_lower in row_text:
                kd_match = re.search(r'(\d+)\s*-\s*(\d+)', tr.get_text())
                if not kd_match: continue
                kills = int(kd_match.group(1))
                maps_data.append({"kills": kills, "rounds": rounds})
                break
                
    return maps_data

# =========================================================
# GOLD STANDARD SCANNERS
# =========================================================
def get_player_info(player_name, line=0.0, opponent="N/A"):
    search_res = search_player(player_name)
    if not search_res: return "FAIL: Player not found."
    pid, slug, display = search_res
    
    # Get the last 10 clean series URLs from results
    results_url = f"{HLTV_BASE}/results?player={pid}"
    html, _ = _fetch(results_url)
    if not html: return "FAIL: Could not load history overview."
    
    matches = re.findall(r'/matches/(\d+)/([\w-]+)', html)
    seen = set()
    match_links = []
    for mid, mslug in matches:
        if mid not in seen:
            seen.add(mid)
            match_links.append((mid, mslug))
            if len(match_links) >= 10: break
                
    if not match_links: return "FAIL: No recent match entries found."
    
    series_totals = []
    total_k, total_r = 0, 0
    
    # Surgical individual extraction sequence
    for mid, mslug in match_links:
        match_url = f"{HLTV_BASE}/matches/{mid}/{mslug}"
        m_html, _ = _fetch(match_url)
        if not m_html: continue
        
        maps = _parse_match_page(m_html, slug)
        if len(maps) >= 2:
            m1, m2 = maps[0], maps[1]
            combined_k = m1["kills"] + m2["kills"]
            series_totals.append(combined_k)
            total_k += combined_k
            total_r += (m1["rounds"] + m2["rounds"])
            
    if not series_totals: return "FAIL: Insufficient series data generated."
    
    # Advanced Betting Models Calculations
    kpr = total_k / total_r if total_r > 0 else 0.80
    proj_rounds = 44 if any(x in opponent.lower() for x in ["vitality", "g2", "faze", "mouz", "navi"]) else 42
    expected_kills = round(kpr * proj_rounds, 1)
    
    import numpy as np
    sim = np.random.poisson(expected_kills, 100000)
    over_prob = (np.sum(sim > line) / 100000) * 100
    under_prob = 100.0 - over_prob
    
    avg_2map = round(_stats.mean(series_totals), 2)
    median = _stats.median(series_totals)
    hits = sum(1 for x in series_totals if x > line)
    hit_rate_pct = (hits / len(series_totals)) * 100
    edge_delta = over_prob - 50.0
    
    return {
        "Player": display,
        "Match": f"vs {opponent.title()}",
        "Prop": f"{line} Kills",
        "Role": "Star / Entry Rifler",
        "Recent sample used": f"Last {len(series_totals)} BO3 Series",
        "Recent average": avg_2map,
        "Recent median": median,
        "Hit rate": f"{round(hit_rate_pct, 1)}%",
        "Projected rounds": proj_rounds,
        "Expected kills": expected_kills,
        "Simulated mean": round(np.mean(sim), 2),
        "Standard deviation": round(_stats.stdev(series_totals), 2) if len(series_totals) > 1 else 0,
        "Over probability": f"{round(over_prob, 1)}%",
        "Under probability": f"{round(under_prob, 1)}%",
        "Edge vs line": f"{round(edge_delta, 1)}%",
        "Mispriced or not": "YES" if abs(edge_delta) >= 10.0 else "NO",
        "Final grade": f"{hits}/{len(series_totals)}",
        "Bet recommendation": "OVER" if over_prob > 60 else "UNDER" if over_prob < 40 else "NO BET",
        "Recent totals": series_totals
    }
