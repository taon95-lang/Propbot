import re
import os
import time
import statistics as _stats
import functools
import random
from bs4 import BeautifulSoup

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
        "jamyoung": ("19645", "jamyoung")
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
# ADAPTIVE TABLE PARSER - FIXES THE COLUMN INDEX PROBLEM
# =========================================================
def _parse_stats_table(soup):
    """Dynamically identifies column positions instead of hardcoding indices"""
    table = soup.find("table", {"class": "stats-table"})
    if not table:
        return None
    
    # Find header row to identify column positions
    thead = table.find("thead")
    if thead:
        headers = [th.text.strip().lower() for th in thead.find_all("th")]
        print(f"DETECTED COLUMNS: {headers}")
        
        # Map column names to indices
        date_idx = next((i for i, h in enumerate(headers) if "date" in h), 0)
        opp_idx = next((i for i, h in enumerate(headers) if "opponent" in h or "event" in h), 2)
        result_idx = next((i for i, h in enumerate(headers) if "result" in h or "map" in h), 5)
        kd_idx = next((i for i, h in enumerate(headers) if "k-d" in h or "k - d" in h), 6)
    else:
        # Fallback to original indices if no header found
        date_idx, opp_idx, result_idx, kd_idx = 0, 2, 5, 6
        print(f"NO HEADER FOUND - Using fallback indices: date={date_idx}, opp={opp_idx}, result={result_idx}, kd={kd_idx}")
    
    return table, date_idx, opp_idx, result_idx, kd_idx

# =========================================================
# THE PERFECT NO-GUESSWORK DIRECT INDEX ENGINE
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
        return "FAIL: Stats page blocked or ScraperAPI failed after 3 retries. Check SCRAPERAPI_KEY and credits."

    soup = BeautifulSoup(html, "html.parser")
    
    # Use adaptive parser instead of hardcoded indices
    parse_result = _parse_stats_table(soup)
    if not parse_result:
        return "FAIL: Stats table layout not found or changed on HLTV."
    
    table, date_idx, opp_idx, result_idx, kd_idx = parse_result

    rows = table.find("tbody").find_all("tr")
    
    print(f"PROCESSING {len(rows)} ROWS FROM STATS TABLE...")

    # Track all maps regardless of series grouping first
    all_maps = []

    for row in rows:
        cols = row.find_all("td")
        if len(cols) <= max(date_idx, opp_idx, result_idx, kd_idx): 
            continue
        
        try:
            date = cols[date_idx].text.strip()
            opp = cols[opp_idx].text.strip().lower()
            res_text = cols[result_idx].text.strip()
            kd_text = cols[kd_idx].text.strip()
            
            res_nums = re.findall(r'\d+', res_text)
            kd_nums = re.findall(r'\d+', kd_text)
            
            if len(kd_nums) >= 2 and len(res_nums) >= 2:
                kills = int(kd_nums[0])
                m_rounds = int(res_nums[0]) + int(res_nums[1])
                
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
        return f"FAIL: Only found {len(all_maps)} maps. Player may not have recent match data on HLTV."

    # Group maps into series by date AND opponent
    series_groups = []
    i = 0
    while i < len(all_maps) - 1:
        # Check if next map is same date/opponent (same series)
        current = all_maps[i]
        next_map = all_maps[i + 1]
        
        if current["date"] == next_map["date"] and current["opponent"] == next_map["opponent"]:
            # This is a multi-map series
            series_groups.append([current, next_map])
            i += 2  # Skip both maps
        else:
            i += 1  # Single map, skip it

    print(f"FOUND {len(series_groups)} MULTI-MAP SERIES")

    # Now process the series
    final_series_totals = []
    total_k, total_r = 0, 0

    for group in series_groups[:10]:  # Take last 10 series
        if len(group) >= 2:
            combined_k = group[0]["kills"] + group[1]["kills"]
            combined_r = group[0]["rounds"] + group[1]["rounds"]
            final_series_totals.append(combined_k)
            total_k += combined_k
            total_r += combined_r

    if not final_series_totals:
        return f"FAIL: Found {len(all_maps)} maps but no multi-map series. Player may have only played BO1s recently."

    print(f"FINAL SAMPLE: {len(final_series_totals)} BO3 series (Maps 1-2 only)")
    print(f"RECENT TOTALS: {final_series_totals}")

    kpr = total_k / total_r if total_r > 0 else 0.80
    
    if any(x in opponent.lower() for x in ["vitality", "g2", "faze", "mouz", "navi"]):
        proj_rounds = 44
    else:
        proj_rounds = 42
        
    expected_kills = round(kpr * proj_rounds, 1)
    
    import numpy as np
    sim = np.random.poisson(expected_kills, 100000)
    over_prob = (np.sum(sim > line) / 100000) * 100
    under_prob = 100.0 - over_prob
    edge_delta = over_prob - 50.0
    
    avg_2map = round(_stats.mean(final_series_totals), 2)
    median = _stats.median(final_series_totals)
    hits = sum(1 for x in final_series_totals if x > line)
    hit_rate_pct = (hits / len(final_series_totals)) * 100
    
    if over_prob > 60:
        bet_rec = "OVER"
    elif over_prob < 40:
        bet_rec = "UNDER"
    else:
        bet_rec = "NO BET"
        
    if abs(edge_delta) >= 10.0:
        mispriced = "YES"
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
        "Over probability": f"{round(over_prob, 1)}%",
        "Under probability": f"{round(under_prob, 1)}%",
        "Edge vs line": f"{round(edge_delta, 1)}%",
        "Mispriced or not": mispriced,
        "Final grade": f"{hits}/{len(final_series_totals)}",
        "Bet recommendation": bet_rec,
        "Recent totals": final_series_totals
    }
