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
# UNIVERSAL DYNAMIC PLAYER LOOKUP ENGINE
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
        "h4san4tor": ("22189", "h4san4tor"),
        "brooxsy": ("21971", "brooxsy")
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

    # Dynamic fallback: Scan using highly adaptive variations of player route layouts
    found_links = re.findall(r'/(?:stats/)?player(?:s)?/(\d+)/([a-zA-Z0-9_-]+)', html)
    if found_links:
        for pid, slug in found_links:
            if name_clean in slug.lower():
                return pid, slug, slug.replace("-", " ").title()
        pid, slug = found_links[0]
        return pid, slug, slug.replace("-", " ").title()
        
    return None

# =========================================================
# THE PERFECT CONTENT-SCANNING PROCESSING CORE
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
        if len(cols) < 4:
            continue
        
        try:
            cell_texts = [c.text.strip() for c in cols]
            
            # 1. MATHEMATICAL DIFFERENTIAL RULE FOR K-D LOCATION
            kd_info = None
            for idx, txt in enumerate(cell_texts):
                m = re.search(r'^(\d+)\s*-\s*(\d+)$', txt)
                if m:
                    k_val = int(m.group(1))
                    d_val = int(m.group(2))
                    diff_val = k_val - d_val
                    
                    is_kd = False
                    for j, t in enumerate(cell_texts):
                        if j == idx:
                            continue
                        if t == f"{diff_val}" or t == f"+{diff_val}" or (diff_val == 0 and t == "0"):
                            is_kd = True
                            break
                    
                    if not is_kd and 0 <= k_val <= 60 and 0 <= d_val <= 60:
                        for t in cell_texts:
                            if re.search(r'^[0-2]\.\d{2}$', t):
                                is_kd = True
                                break
                                
                    if is_kd:
                        kd_info = (k_val, d_val, idx)
                        break
            
            if not kd_info:
                for idx, txt in enumerate(cell_texts):
                    m = re.search(r'^(\d+)\s*-\s*(\d+)$', txt)
                    if m:
                        k_val = int(m.group(1))
                        if 1 <= k_val <= 50:
                            kd_info = (k_val, int(m.group(2)), idx)
                            break
                            
            if not kd_info:
                continue
                
            kills = kd_info[0]
            kd_idx = kd_info[2]
            
            # 2. IDENTIFY ROUNDS PLAYED
            m_rounds = 0
            parentheses_nums = []
            for txt in cell_texts:
                p_matches = re.findall(r'\((\d+)\)', txt)
                for pm in p_matches:
                    parentheses_nums.append(int(pm))
            
            if len(parentheses_nums) >= 2:
                m_rounds = parentheses_nums[0] + parentheses_nums[1]
                
            if m_rounds < 10 or m_rounds > 60:
                for idx, txt in enumerate(cell_texts):
                    if idx == kd_idx:
                        continue
                    m = re.search(r'^(\d+)\s*-\s*(\d+)$', txt)
                    if m:
                        s1 = int(m.group(1))
                        s2 = int(m.group(2))
                        if 13 <= (s1 + s2) <= 50:
                            m_rounds = s1 + s2
                            break
            
            if m_rounds < 10 or m_rounds > 60:
                m_rounds = 22  # Standard Fallback

            # 3. DATE EXTRACTION
            date = "N/A"
            for txt in cell_texts:
                if re.search(r'^\d{2}/\d{2}/\d{2}$', txt):
                    date = txt
                    break

            # 4. OPPONENT EXTRACTION
            known_maps = {'anc', 'mrg', 'd2', 'inf', 'nuke', 'anb', 'vrt', 'ovp', 'ancient', 'mirage', 'dust2', 'inferno', 'nuke', 'anubis', 'vertigo', 'overpass'}
            map_cell_idx = -1
            for idx, txt in enumerate(cell_texts):
                if txt.lower() in known_maps:
                    map_cell_idx = idx
                    break
                    
            if map_cell_idx > 0:
                opp = cell_texts[map_cell_idx - 1].lower()
            else:
                opp = cell_texts[2].lower() if len(cell_texts) > 2 else "unknown"
                
            opp = re.sub(r'\(.*\)', '', opp).strip()
            opp = re.sub(r'\s+\d+\s*$', '', opp).strip()
            
            all_maps.append({
                "date": date,
                "opponent": opp,
                "kills": kills,
                "rounds": m_rounds
            })
                
        except Exception as e:
            continue

    print(f"TOTAL MAPS FOUND: {len(all_maps)}")

    if len(all_maps) < 2:
        return f"FAIL: Found {len(all_maps)} maps. Player lacks analytical match history entries."

    # SEQUENTIAL CONTIGUOUS SERIES GROUPING COHERENCE
    series_groups = []
    if all_maps:
        current_group = [all_maps[0]]
        for m_data in all_maps[1:]:
            if m_data['opponent'] == current_group[0]['opponent'] and m_data['date'] == current_group[0]['date']:
                current_group.append(m_data)
            else:
                series_groups.append(current_group)
                current_group = [m_data]
        if current_group:
            series_groups.append(current_group)

    final_series_totals = []
    individual_map_kills = []
    total_k, total_r = 0, 0

    # Extract Maps 1-2 across the target 10 BO3 matches chronologically
    for group in series_groups:
        if len(final_series_totals) >= 10:
            break
            
        if len(group) >= 2:
            # Table rows run newest-to-oldest. group[-1] is Map 1, group[-2] is Map 2
            m1_kills = group[-1]["kills"]
            m2_kills = group[-2]["kills"]
            
            individual_map_kills.extend([m1_kills, m2_kills])
            
            combined_k = m1_kills + m2_kills
            combined_r = group[-1]["rounds"] + group[-2]["rounds"]
            
            final_series_totals.append(combined_k)
            total_k += combined_k
            total_r += combined_r

    if not final_series_totals:
        return "FAIL: Could not track enough valid multi-map samples from recent matches."

    avg_2map = round(_stats.mean(final_series_totals), 2)
    median = _stats.median(final_series_totals)
    hits = sum(1 for x in final_series_totals if x > line)
    hit_rate_pct = (hits / len(final_series_totals)) * 100

    kpr = total_k / total_r if total_r > 0 else 0.68
    
    if any(x in opponent.lower() for x in ["vitality", "g2", "faze", "mouz", "navi"]):
        proj_rounds = 44
    else:
        proj_rounds = 42
        
    expected_kills = round(kpr * proj_rounds, 1)
    
    # NEGATIVE BINOMIAL MONTE CARLO MODEL SIMULATION
    var_2map = _stats.variance(final_series_totals) if len(final_series_totals) > 1 else avg_2map
    if var_2map <= expected_kills:
        var_2map = expected_kills * 1.25
        
    p_nb = expected_kills / var_2map
    n_nb = (expected_kills ** 2) / (var_2map - expected_kills)
    
    sim = np.random.negative_binomial(n_nb, p_nb, 100000)
    over_prob = (np.sum(sim > line) / 100000) * 100
    under_prob = 100.0 - over_prob
    edge_delta = over_prob - 50.0
    
    # CRITERIA STRATEGIC RULES
    if avg_2map > line and median > line and hit_rate_pct >= 60.0:
        bet_rec = "OVER"
    elif avg_2map < line and median < line and hit_rate_pct <= 40.0:
        bet_rec = "UNDER"
    else:
        bet_rec = "NO BET"
        
    # MISPRICED STRATIFICATION ENGINE
    if line > 0 and (avg_2map - line) >= 8.0:
        mispriced = "PROP ERROR (Wildly Underpriced)"
    elif line > 0 and (line - avg_2map) >= 8.0:
        mispriced = "PROP ERROR (Wildly Overpriced)"
    elif abs(avg_2map - line) >= 4.0:
        mispriced = "YES"
    else:
        mispriced = "NO"

    # EDGE CALCULATOR AND GRADING SCALE
    if abs(edge_delta) >= 25.0 and "PROP ERROR" in mispriced:
        grade_str = "10/10 (Elite Edge / Prop Error)"
    elif abs(edge_delta) >= 20.0:
        grade_str = "9/10 (Very Strong Edge)"
    elif abs(edge_delta) >= 15.0:
        grade_str = "8/10 (Strong Playable Edge)"
    elif abs(edge_delta) >= 10.0:
        grade_str = "7/10 (Solid Lean / Favorable Value)"
    elif abs(edge_delta) >= 5.0:
        grade_str = "6/10 (Small Edge / Minor Value)"
    elif abs(edge_delta) >= 2.0:
        grade_str = "5/10 (Thin Edge / Borderline)"
    else:
        grade_str = "Below 5/10 (No Bet)"

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
        "Mispriced or not": mispriced,
        "Final grade": grade_str,
        "Bet recommendation": bet_rec,
        "Recent Totals (M1+M2 Combined)": final_series_totals,
        "Recent Individual Map Kills": individual_map_kills[:20]
    }
