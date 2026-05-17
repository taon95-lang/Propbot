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

# =========================================================
# RESILIENT PROGRESSIVE FETCH ENGINE
# =========================================================
def _fetch(url, render=False):
    if not SCRAPERAPI_KEY:
        print("CRITICAL: SCRAPERAPI_KEY environment variable is missing.")
        return None, None
    
    for attempt in range(3):
        use_render = render if attempt == 0 else (not render if attempt == 1 else True)
        render_param = "&render=true" if use_render else ""
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}{render_param}&country_code=us"
        
        try:
            print(f"FETCH ATTEMPT {attempt + 1}/3: {url} (JS_Render={use_render})")
            r = requests.get(proxy_url, timeout=60)
            
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text, r.headers.get("Sa-Final-Url", url)
                
            print(f"ATTEMPT {attempt + 1} FAILED: Status code {r.status_code}")
            time.sleep(1.5)
        except Exception as e:
            print(f"ATTEMPT {attempt + 1} EXCEPTION: {e}")
            time.sleep(1.5)
            
    return None, None

# =========================================================
# THE ABSOLUTE PLAYER SEARCH OVERHAUL
# =========================================================
def search_player(name: str):
    name_clean = name.lower().strip()
    
    # Fast-pass cache for major star-tier requests
    STATIC = {
        "donk": ("21167", "donk"), 
        "zywoo": ("11893", "zywoo"), 
        "m0nesy": ("19230", "m0nesy"), 
        "niko": ("3741", "niko"),
        "jl": ("19206", "jl"),
        "xertion": ("20312", "xertion"),
        "jamyoung": ("19645", "jamyoung")
    }
    if name_clean in STATIC: 
        return STATIC[name_clean][0], STATIC[name_clean][1], STATIC[name_clean][1].title()

    html, final_url = _fetch(f"{HLTV_BASE}/search?query={name_clean}", render=False)
    if not html: return None
    
    if final_url and "/player/" in final_url:
        m = re.search(r'/player/(\d+)/([^/]+)', final_url)
        if m: return m.group(1), m.group(2), m.group(2).title()

    found_links = re.findall(r'href="/player/(\d+)/([^"/\s>]+)"', html)
    if not found_links:
        found_links = re.findall(r'href="/stats/players/(\d+)/([^"/\s>]+)"', html)
    if not found_links:
        found_links = re.findall(r'/player/(\d+)/([^"\'\s>?&)]+)', html)

    if found_links:
        pid, slug = found_links[0]
        slug_clean = slug.split('"')[0].split("'")[0].split(')')[0].split('?')[0].split('&')[0].strip()
        return pid, slug_clean, slug_clean.replace("-", " ").title()
        
    return None

# =========================================================
# THE PERFECT GOLD SCAN ENGINE
# =========================================================
def get_player_info(player_name, line=0.0, opponent="N/A"):
    search_res = search_player(player_name)
    if not search_res: return f"FAIL: Could not find player '{player_name}' on HLTV."
    pid, slug, display = search_res
    print(f"TARGET ACQUIRED: {display} (ID: {pid})")
    
    stats_url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"
    html, _ = _fetch(stats_url, render=True)
    if not html: return "FAIL: Stats page blocked by Cloudflare after 3 retries."

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "stats-table"})
    if not table: return "FAIL: Stats table layout changed on HLTV."

    rows = table.find("tbody").find_all("tr")
    series_groups = []
    current_key = None
    current_maps = []

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 5: continue
        
        date = cols[0].text.strip()
        opp = cols[2].text.strip().lower()
        
        # Clean opponent name to keep grouping safe against score layout shifts
        opp_clean = re.sub(r'[^a-zA-Z0-9]', '', opp)
        
        # FIX: Universal dash regex support safely catches standard hyphens, en-dashes, and em-dashes
        hyphen_cells = []
        for cell in cols:
            txt = cell.get_text(strip=True)
            if re.match(r'^\d+\s*[-\u2013\u2014]\s*\d+$', txt):
                hyphen_cells.append(txt)
                
        if len(hyphen_cells) < 2: continue
        res_text = hyphen_cells[0]
        kd_text = hyphen_cells[1]
        
        try:
            # FIX: Pull numbers using re.findall to avoid split errors on varying dash configurations
            res_nums = re.findall(r'\d+', res_text)
            kd_nums = re.findall(r'\d+', kd_text)
            
            kills = int(kd_nums[0])
            m_rounds = sum(int(n) for n in res_nums) if len(res_nums) >= 2 else 24
            
            key = f"{date}_{opp_clean}"
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
            m1, m2 = group[-1], group[-2]
            combined_k = m1["kills"] + m2["kills"]
            final_series_totals.append(combined_k)
            total_k += combined_k
            total_r += (m1["rounds"] + m2["rounds"])

    if not final_series_totals: return "FAIL: Not enough valid multi-map series found."

    # Statistical Projections Models
    kpr = total_k / total_r if total_r > 0 else 0.80
    proj_rounds = 44 if any(x in opponent.lower() for x in ["vitality", "g2", "faze", "mouz", "navi"]) else 42
    expected_kills = round(kpr * proj_rounds, 1)
    
    # 100,000 Monte Carlo Simulation Runs
    import numpy as np
    sim = np.random.poisson(expected_kills, 100000)
    over_prob = (np.sum(sim > line) / 100000) * 100
    under_prob = 100.0 - over_prob
    edge_delta = over_prob - 50.0
    
    avg_2map = round(_stats.mean(final_series_totals), 2)
    median = _stats.median(final_series_totals)
    hits = sum(1 for x in final_series_totals if x > line)
    hit_rate_pct = (hits / len(final_series_totals)) * 100
    
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
