import re
import os
import time
import statistics as _stats
import functools
import numpy as np
from bs4 import BeautifulSoup
from collections import defaultdict

# Ensure real-time print updates populate Render service streams immediately
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
        if attempt == 0:
            use_render = render
        elif attempt == 1:
            use_render = not render
        else:
            use_render = True
            
        if use_render:
            render_param = "&render=true"
        else:
            render_param = ""
            
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}{render_param}&country_code=us"
        
        try:
            print(f"FETCH ATTEMPT {attempt + 1}/3: {url} (JS_Render={use_render})")
            r = requests.get(proxy_url, timeout=60)
            
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text, r.headers.get("Sa-Final-Url", url)
                
            print(f"ATTEMPT {attempt + 1} FAILED: Status code {r.status_code}, Length: {len(r.text)}")
            time.sleep(2)
        except Exception as e:
            print(f"ATTEMPT {attempt + 1} EXCEPTION: {e}")
            time.sleep(2)
            
    return None, None

# =========================================================
# THE ABSOLUTE PLAYER SEARCH OVERHAUL
# =========================================================
def search_player(name: str):
    name_clean = name.lower().strip()
    
    STATIC = {
        "donk": ("21167", "donk"), 
        "zywoo": ("11893", "zywoo"), 
        "m0nesy": ("19230", "m0nesy"), 
        "niko": ("3741", "niko"),
        "jl": ("19206", "jl"),
        "xertion": ("20312", "xertion"),
        "jamyoung": ("19645", "jamyoung"),
        "h4san4tor": ("22189", "h4san4tor")
    }
    if name_clean in STATIC: 
        return STATIC[name_clean][0], STATIC[name_clean][1], STATIC[name_clean][1].title()

    html, final_url = _fetch(f"{HLTV_BASE}/search?query={name_clean}", render=False)
    if not html: 
        return None
    
    if final_url and "/player/" in final_url:
        m = re.search(r'/player/(\d+)/([^/]+)', final_url)
        if m: 
            return m.group(1), m.group(2), m.group(2).title()

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
# THE PERFECT NO-GUESSWORK CONTENT-SCANNING ENGINE
# =========================================================
def get_player_info(player_name, line=0.0, opponent="N/A"):
    search_res = search_player(player_name)
    if not search_res: 
        return f"FAIL: Could not find player '{player_name}' on HLTV."
    pid, slug, display = search_res
    print(f"TARGET ACQUIRED: {display} (ID: {pid})")
    
    stats_url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"
    html, _ = _fetch(stats_url, render=True)
    if not html: 
        return "FAIL: Stats page blocked or ScraperAPI failed after 3 retries."

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "stats-table"})
    if not table:
        return "FAIL: Stats table layout not found or changed on HLTV."
    
    rows = table.find("tbody").find_all("tr")
    print(f"PROCESSING {len(rows)} ROWS FROM STATS TABLE...")

    all_maps = []

    for i, row in enumerate(rows):
        cols = row.find_all("td")
        if len(cols) < 5:
            continue
        
        try:
            cell_texts = [c.text.strip() for c in cols]
            
            # 1. Content-based Date Extraction
            date = "N/A"
            for txt in cell_texts:
                if re.search(r'^\d{2}/\d{2}/\d{2}$', txt):
                    date = txt
                    break
            if date == "N/A":
                date = cell_texts[0]
                
            # 2. Map & Opponent Detection via Map Names
            known_maps = {'anc', 'mrg', 'd2', 'inf', 'nuke', 'anb', 'vrt', 'ovp', 'ancient', 'mirage', 'dust2', 'inferno', 'nuke', 'anubis', 'vertigo', 'overpass'}
            map_idx = -1
            for idx, txt in enumerate(cell_texts):
                if txt.lower() in known_maps:
                    map_idx = idx
                    break
            
            if map_idx != -1 and map_idx > 0:
                opp = cell_texts[map_idx - 1].lower()
            else:
                opp = cell_texts[2].lower() if len(cell_texts) > 2 else "unknown"
                
            # Strip trailing tournament match-score indicators, e.g., "astral (2)" -> "astral"
            opp = re.sub(r'\s*\(\d+\)\s*', '', opp).strip()

            # 3. Scan all columns for strict numerical hyphen formats (X - Y)
            hyphen_patterns = []
            for txt in cell_texts:
                m = re.search(r'^\s*(\d+)\s*-\s*(\d+)\s*$', txt)
                if m:
                    hyphen_patterns.append((int(m.group(1)), int(m.group(2))))
            
            # An authentic match row must contain at least Map Score and Player K-D
            if len(hyphen_patterns) < 2:
                continue
                
            map_score = hyphen_patterns[0]
            player_kd = hyphen_patterns[1]
            
            m_rounds = map_score[0] + map_score[1]
            kills = player_kd[0]
            
            # Final sanity validation filter
            if kills < 1 or kills > 50:
                continue
                
            all_maps.append({
                "date": date,
                "opponent": opp,
                "kills": kills,
                "rounds": m_rounds
            })
            
            if len(all_maps) <= 3:
                print(f"✓ PARSED MAP {len(all_maps)}: {date} vs {opp} -> {kills}K in {m_rounds}R")
                
        except Exception as e:
            continue

    print(f"TOTAL MAPS FOUND: {len(all_maps)}")

    if len(all_maps) < 2:
        return f"FAIL: Only found {len(all_maps)} maps. Player may not have recent match data on HLTV."

    # CHRONOLOGICAL SERIES GROUPING (MAPS 1-2 ONLY)
    series_dict = defaultdict(list)
    for map_data in all_maps:
        key = f"{map_data['date']}_{map_data['opponent']}"
        series_dict[key].append(map_data)

    series_groups = []
    for key, maps in series_dict.items():
        if len(maps) >= 2:
            # Table rows go from newest to oldest. Map 1 is at the end of the list.
            # maps[-2:] extracts exactly Map 2 and Map 1 chronologically, completely bypassing Map 3.
            series_groups.append(maps[-2:])

    print(f"FOUND {len(series_groups)} MULTI-MAP SERIES")

    if not series_groups:
        return f"FAIL: Could not create valid 2-map samples from data window."

    final_series_totals = []
    total_k, total_r = 0, 0

    # Limit exactly to the last 10 BO3 Series (Totaling 20 Maps)
    for group in series_groups[:10]:
        if len(group) >= 2:
            combined_k = group[0]["kills"] + group[1]["kills"]
            combined_r = group[0]["rounds"] + group[1]["rounds"]
            final_series_totals.append(combined_k)
            total_k += combined_k
            total_r += combined_r

    print(f"FINAL SAMPLE: {len(final_series_totals)} series (20 maps max total)")
    print(f"RECENT TOTALS: {final_series_totals}")

    kpr = total_k / total_r if total_r > 0 else 0.67
    
    if any(x in opponent.lower() for x in ["vitality", "g2", "faze", "mouz", "navi"]):
        proj_rounds = 44
    else:
        proj_rounds = 42
        
    expected_kills = round(kpr * proj_rounds, 1)
    
    # ADVANCED NEGATIVE BINOMIAL MONTE CARLO SIMULATION (100,000 RUNS)
    avg_2map = round(_stats.mean(final_series_totals), 2)
    var_2map = _stats.variance(final_series_totals) if len(final_series_totals) > 1 else avg_2map
    
    # Enforce overdispersion properties to track high volatility/ceilings safely
    if var_2map <= expected_kills:
        var_2map = expected_kills * 1.2 
        
    p_nb = expected_kills / var_2map
    n_nb = (expected_kills ** 2) / (var_2map - expected_kills)
    
    sim = np.random.negative_binomial(n_nb, p_nb, 100000)
    
    over_prob = (np.sum(sim > line) / 100000) * 100
    under_prob = 100.0 - over_prob
    edge_delta = over_prob - 50.0
    
    median = _stats.median(final_series_totals)
    pct_25 = int(np.percentile(sim, 25))
    pct_75 = int(np.percentile(sim, 75))
    hits = sum(1 for x in final_series_totals if x > line)
    hit_rate_pct = (hits / len(final_series_totals)) * 100
    
    # GOLD STANDARD DECISION RULES
    if avg_2map > line and median > line and hit_rate_pct >= 60.0:
        bet_rec = "OVER"
    elif avg_2map < line and median < line and hit_rate_pct <= 40.0:
        bet_rec = "UNDER"
    else:
        bet_rec = "NO BET"
        
    if line > 0 and (avg_2map - line) >= 8.0:
        mispriced = "PROP ERROR (Wildly Underpriced)"
    elif line > 0 and (line - avg_2map) >= 8.0:
        mispriced = "PROP ERROR (Wildly Overpriced)"
    elif abs(avg_2map - line) >= 4.0:
        mispriced = "YES (Mispriced Prop)"
    else:
        mispriced = "NO"
    
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
        "25th percentile": pct_25,
        "75th percentile": pct_75,
        "Over probability": f"{round(over_prob, 1)}%",
        "Under probability": f"{round(under_prob, 1)}%",
        "Edge vs line": f"{round(edge_delta, 1)}%",
        "Mispriced or not": mispriced,
        "Final grade": f"{hits}/{len(final_series_totals)}",
        "Bet recommendation": bet_rec,
        "Recent totals": final_series_totals
    }
