import re
import os
import time
import statistics as _stats
import functools
import random
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

def _fetch(url, render=False):
    if not SCRAPERAPI_KEY:
        print("CRITICAL: SCRAPERAPI_KEY environment variable is missing.")
        return None, None
    render_param = "&render=true" if render else ""
    proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}{render_param}&country_code=us"
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

    html, final_url = _fetch(f"{HLTV_BASE}/search?query={name_clean}", render=False)
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
# THE PERFECT GOLD SCAN ENGINE
# =========================================================
def get_player_info(player_name, line=0.0, opponent="N/A"):
    search_res = search_player(player_name)
    if not search_res: return "FAIL: Player not found on HLTV."
    pid, slug, display = search_res
    
    stats_url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"
    html, _ = _fetch(stats_url, render=True)
    if not html: return "FAIL: Stats page blocked by Cloudflare."

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "stats-table"})
    if not table: return "FAIL: Stats table layout not found."

    rows = table.find("tbody").find_all("tr")
    series_groups = []
    current_key = None
    current_maps = []

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 5: continue
        
        date = cols[0].text.strip()
        opp = cols[2].text.strip().lower()
        
        # SURGICAL CELL FILTER: Find all columns with format 'X - Y'
        hyphen_cells = []
        for cell in cols:
            txt = cell.get_text(strip=True)
            if re.match(r'^\d+\s*-\s*\d+$', txt):
                hyphen_cells.append(txt)
                
        # Structural Truth: cell[0] is match score, cell[1] is player K-D
        if len(hyphen_cells) < 2: continue
        res_text = hyphen_cells[0]
        kd_text = hyphen_cells[1]
        
        try:
            kills = int(kd_text.split("-")[0].strip())
            r_nums = re.findall(r'\d+', res_text)
            m_rounds = sum(int(n) for n in r_nums) if len(r_nums) >= 2 else 24
            
            key = f"{date}_{opp}"
            if key != current_key:
                if current_maps: series_groups.append(current_maps)
                current_key, current_maps = key, []
            current_maps.append({"kills": kills, "rounds": m_rounds})
        except: continue
        
    if current_maps: series_groups.append(current_maps)

    final_series_totals = []
    total_k, total_r = 0, 0
    
    for group in series_groups:
        if len(final_series_totals) >= 10: break
        if len(group) >= 2:
            # Reverse-chronological table means group[-1] is Map 1, group[-2] is Map 2
            m1, m2 = group[-1], group[-2]
            combined_k = m1["kills"] + m2["kills"]
            final_series_totals.append(combined_k)
            total_k += combined_k
            total_r += (m1["rounds"] + m2["rounds"])

    if not final_series_totals: return "FAIL: Not enough valid series totals found."

    # Model Projections
    kpr = total_k / total_r if total_r > 0 else 0.80
    proj_rounds = 44 if any(x in opponent.lower() for x in ["vitality", "g2", "faze", "mouz", "navi"]) else 42
    expected_kills = round(kpr * proj_rounds, 1)
    
    # 100k Monte Carlo Poisson Simulation
    import numpy as np
    sim = np.random.poisson(expected_kills, 100000)
    over_prob = (np.sum(sim > line) / 100000) * 100
    under_prob = 100.0 - over_prob
    
    avg_2map = round(_stats.mean(final_series_totals), 2)
    median = _stats.median(final_series_totals)
    hits = sum(1 for x in final_series_totals if x > line)
    hit_rate_pct = (hits / len(final_series_totals)) * 100
    edge_delta = over_prob - 50.0
    
    return {
        "Player": display,
        "Match": f"vs {opponent.title()}",
        "Prop": f"{line} Kills",
        "Role": "Star / Entry Rifler",
        "Recent sample used": f"Last {len(final_series_totals)} BO3 Series (M1+M2)",
        "Recent average": avg_2map,
        "Recent median": median,
        "Hit rate": f"{round(hit_rate_pct, 1)}%",
        "Projected rounds": proj_rounds,
        "Expected kills": expected_kills,
        "Simulated mean": round(np.mean(sim), 2),
        "Standard deviation": round(_stats.stdev(final_series_totals), 2) if len(final_series_totals) > 1 else 0,
        "Over probability": f"{round(over_prob, 1)}%",
        "Under probability": f"{round(under_prob, 1)}%",
        "Edge vs line": f"{round(edge_delta, 1)}%",
        "Mispriced or not": "YES" if abs(edge_delta) >= 10.0 else "NO",
        "Final grade": f"{hits}/{len(final_series_totals)}",
        "Bet recommendation": "OVER" if over_prob > 60 else "UNDER" if over_prob < 40 else "NO BET",
        "Recent totals": final_series_totals
    }
