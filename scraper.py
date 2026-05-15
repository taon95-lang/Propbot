import re
import os
import time
import statistics as _stats
import functools
import random
from bs4 import BeautifulSoup

print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")

def _fetch(url):
    if not SCRAPERAPI_KEY: return None, None
    proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}&country_code=us"
    try:
        r = requests.get(proxy_url, timeout=60)
        if r.status_code == 200:
            return r.text, r.headers.get("Sa-Final-Url", url)
    except Exception as e:
        print(f"FETCH ERROR: {e}")
    return None, None

def search_player(name: str):
    name_clean = name.lower().strip()
    # STATIC CACHE: Instant results for common stars
    STATIC = {
        "donk": ("21167", "donk"),
        "zywoo": ("11893", "zywoo"),
        "m0nesy": ("19230", "m0nesy"),
        "niko": ("3741", "niko"),
        "elkera": ("21126", "elkera")
    }
    if name_clean in STATIC: return STATIC[name_clean][0], STATIC[name_clean][1], STATIC[name_clean][1].title()

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

def get_player_info(player_name, line=0.0, opponent="N/A"):
    search_res = search_player(player_name)
    if not search_res: return "FAIL: Player not found."
    pid, slug, display = search_res
    
    # FETCH ALL HISTORY IN ONE GO
    stats_url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"
    html, _ = _fetch(stats_url)
    if not html: return "FAIL: Stats page blocked."

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find("table", {"class": "stats-table"}).find("tbody").find_all("tr")
    
    series_map = {}
    total_rounds_played = 0
    total_kills_all = 0

    for row in rows:
        cols = row.find_all("td")
        date, opp, m_name, kd = cols[0].text, cols[1].text.lower(), cols[2].text, cols[4].text
        # Extract rounds from the 'Result' column (e.g., "13 - 7")
        res_text = cols[3].text
        r_nums = re.findall(r'\d+', res_text)
        m_rounds = sum(int(n) for n in r_nums) if len(r_nums) >= 2 else 24

        try:
            kills = int(kd.split("-")[0].strip())
            key = f"{date}_{opp}"
            if key not in series_map: series_map[key] = []
            if len(series_map[key]) < 2:
                series_map[key].append(kills)
                total_rounds_played += m_rounds
                total_kills_all += kills
        except: continue

    series_totals = [sum(m) for m in series_map.values() if len(m) == 2][:10]
    if not series_totals: return "FAIL: No BO3 data found."

    # --- CALCULATIONS ---
    kpr = total_kills_all / total_rounds_played if total_rounds_played > 0 else 0.70
    proj_rounds = 44 if "close" in opponent.lower() or "vitality" in opponent.lower() else 42
    expected_kills = round(kpr * proj_rounds, 1)
    
    # 100k Poisson Simulation for Probabilities
    import numpy as np
    sim_results = np.random.poisson(expected_kills, 100000)
    over_prob = (np.sum(sim_results > line) / 100000) * 100
    
    avg_2map = round(_stats.mean(series_totals), 2)
    median = _stats.median(series_totals)
    hits = sum(1 for x in series_totals if x > line)
    
    return {
        "Player": display,
        "Recent average": avg_2map,
        "Recent median": median,
        "Recent totals": series_totals,
        "Hit rate": f"{round((hits/len(series_totals))*100, 1)}%",
        "Expected kills": expected_kills,
        "Projected rounds": proj_rounds,
        "Standard deviation": round(_stats.stdev(series_totals), 2),
        "Simulated mean": round(np.mean(sim_results), 2),
        "Over probability": f"{round(over_prob, 1)}%",
        "Edge vs line": f"{round(over_prob - 50, 1)}%",
        "Final grade": f"{hits}/{len(series_totals)}",
        "Recommendation": "OVER" if over_prob > 60 else "UNDER" if over_prob < 40 else "NO BET"
    }
