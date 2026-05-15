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
    STATIC = {"donk": ("21167", "donk"), "zywoo": ("11893", "zywoo"), "m0nesy": ("19230", "m0nesy"), "niko": ("3741", "niko")}
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
    
    # FETCH HISTORY (One request for speed)
    stats_url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"
    html, _ = _fetch(stats_url)
    if not html: return "FAIL: Stats page blocked."

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find("table", {"class": "stats-table"}).find("tbody").find_all("tr")
    
    series_groups = []
    current_key = None
    current_maps = []

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 5: continue
        date, opp = cols[0].text, cols[1].text.lower()
        res_text, kd = cols[3].text, cols[4].text
        
        try:
            kills = int(kd.split("-")[0].strip())
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
            # Table is newest-to-oldest. Last two are Map 1 and Map 2.
            m1, m2 = group[-1], group[-2]
            combined_k = m1["kills"] + m2["kills"]
            final_series_totals.append(combined_k)
            total_k += combined_k
            total_r += (m1["rounds"] + m2["rounds"])

    if not final_series_totals: return "FAIL: Not enough BO3 history."

    # Simulation & Metrics
    kpr = total_k / total_r if total_r > 0 else 0.80
    proj_rounds = 44 if any(x in opponent.lower() for x in ["vitality", "g2", "faze", "mouz", "navi"]) else 42
    expected_kills = round(kpr * proj_rounds, 1)
    
    import numpy as np
    sim = np.random.poisson(expected_kills, 100000)
    over_prob = (np.sum(sim > line) / 100000) * 100
    hits = sum(1 for x in final_series_totals if x > line)

    return {
        "Player": display,
        "Recent average": round(_stats.mean(final_series_totals), 2),
        "Recent median": _stats.median(final_series_totals),
        "Hit rate": f"{round((hits/len(final_series_totals))*100, 1)}%",
        "Expected kills": expected_kills,
        "Proj Rounds": proj_rounds,
        "Edge vs Line": f"{round(over_prob - 52, 1)}%", # 52% is standard implied line
        "Std Dev": round(_stats.stdev(final_series_totals), 2),
        "Final grade": f"{hits}/10",
        "Recent totals": final_series_totals,
        "Recommendation": "OVER" if over_prob > 62 else "UNDER" if over_prob < 40 else "NO BET"
    }
