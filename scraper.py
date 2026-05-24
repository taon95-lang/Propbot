import os
import re
import time
import functools
from bs4 import BeautifulSoup
from collections import defaultdict
import statistics as _stats
import numpy as np

print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")

def _fetch(url, render=False):
    """Fetch URL with ScraperAPI and timeout handling"""
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
            print(f"ATTEMPT {attempt + 1} FAILED: Status code {r.status_code}, Length: {len(r.text)}")
            time.sleep(2)
        except Exception as e:
            print(f"ATTEMPT {attempt + 1} EXCEPTION: {e}")
            time.sleep(2)
    return None, None

def search_player(name: str):
    """Search for player on HLTV by name"""
    name_clean = name.lower().strip()
    STATIC = {
        "donk": ("21167", "donk"), "zywoo": ("11893", "zywoo"), 
        "m0nesy": ("19230", "m0nesy"), "niko": ("3741", "niko"),
        "jl": ("19206", "jl"), "xertion": ("20312", "xertion"),
        "jamyoung": ("19645", "jamyoung"), "h4san4tor": ("22189", "h4san4tor"),
        "brooxsy": ("21971", "brooxsy"), "djoko": ("7175", "djoko"),
        "flouzer": ("20928", "flouzer"), "myltsi": ("20928", "myltsi"),
        "pointer": ("26666", "pointer"), "caleyy": ("27093", "caleyy"),
        "eraa": ("25677", "eraa"), "tomate": ("27410", "tomate"),
        "avid": ("25488", "avid"), "marix": ("26544", "marix"),
        "keoz": ("25673", "keoz"), "forsyy": ("20445", "forsyy"),
        "glowiing": ("21968", "glowiing"), "kaide": ("22052", "kaide"),
        "matys": ("27032", "matys"), "yawara": ("27091", "yawara")
    }
    if name_clean in STATIC: 
        print(f"✅ STATIC LOOKUP: {name_clean} → ID {STATIC[name_clean][0]}")
        return STATIC[name_clean][0], STATIC[name_clean][1], STATIC[name_clean][1].title()

    print(f"🔍 SEARCHING HLTV FOR: {name_clean}")
    html, final_url = _fetch(f"{HLTV_BASE}/search?query={name_clean}", render=True)
    if not html: 
        print(f"❌ SEARCH FAILED: No HTML returned")
        return None
    
    if final_url and "/player/" in final_url:
        print(f"✅ REDIRECT DETECTED: {final_url}")
        m = re.search(r'/player/(\d+)/([^/?#\s]+)', final_url)
        if m: 
            return m.group(1), m.group(2), m.group(2).title()
    
    print(f"📊 PARSING SEARCH RESULTS ({len(html)} chars)...")
    soup = BeautifulSoup(html, "html.parser")
    
    found_links = []
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if "/player/" in href:
            m = re.search(r'/player/(\d+)/([a-zA-Z0-9_-]+)', href)
            if m:
                pid, slug = m.group(1), m.group(2)
                if not any(p[0] == pid for p in found_links):
                    found_links.append((pid, slug))
                    print(f"📍 Found: {slug} (ID: {pid})")
    
    if found_links:
        print(f"✅ FOUND {len(found_links)} PLAYER LINKS")
        for pid, slug in found_links:
            if name_clean == slug.lower() or name_clean in slug.lower():
                print(f"✅ MATCHED: {slug} (ID: {pid})")
                return pid, slug, slug.replace("-", " ").title()
        pid, slug = found_links[0]
        print(f"⚠️ NO EXACT MATCH, USING FIRST: {slug} (ID: {pid})")
        return pid, slug, slug.replace("-", " ").title()
    
    print(f"❌ NO PLAYER LINKS FOUND IN HTML")
    return None

def _error_response(msg, player_name, line, opponent):
    return {
        "Player": player_name.title(),
        "Match": f"vs {opponent.title()}",
        "Prop Line": f"{line} Kills",
        "Bet Recommendation": "NO BET",
        "error": msg
    }

def extract_advanced_stats_from_matches(all_maps):
    if not all_maps:
        return {
            "rating_3": 1.0,
            "kast": 70.0,
            "impact": 1.0,
            "adr": 75.0,
            "kpr": 0.68,
            "dpr": 0.65,
        }
    
    total_k = sum(m.get('kills', 0) for m in all_maps)
    total_d = sum(m.get('deaths', 0) for m in all_maps)
    total_r = sum(m.get('rounds', 0) for m in all_maps)
    
    kpr = total_k / total_r if total_r > 0 else 0.68
    dpr = total_d / total_r if total_r > 0 else 0.65
    
    kd_ratio = total_k / total_d if total_d > 0 else 1.0
    if kpr >= 0.85 and kd_ratio >= 1.3:
        rating_3 = 1.35
    elif kpr >= 0.75 and kd_ratio >= 1.15:
        rating_3 = 1.20
    elif kpr >= 0.68:
        rating_3 = 1.05
    else:
        rating_3 = 0.90
    
    return {
        "rating_3": round(rating_3, 2),
        "kast": 70.0,
        "impact": round(1.0 + (kpr - 0.68) / 2, 2),
        "adr": 75.0,
        "kpr": round(kpr, 2),
        "dpr": round(dpr, 2),
    }

def classify_role_from_stats(kpr, dpr, hs_rate):
    kd = kpr / dpr if dpr > 0 else 1.0
    if kpr >= 0.78 and kd >= 1.25 and hs_rate >= 38:
        return "Star Rifler"
    elif kpr >= 0.75 and kd >= 1.20 and hs_rate >= 35:
        return "Entry Fragger"
    elif kpr >= 0.75 and dpr >= 0.65 and hs_rate <= 30:
        return "Primary AWPer"
    elif 0.65 <= kpr <= 0.74 and 0.60 <= dpr <= 0.70:
        return "Lurker/Closer"
    elif kpr <= 0.65 and dpr >= 0.65:
        return "Support/IGL"
    else:
        return "Flex/Rotator"

def calculate_multi_kill_rounds(all_maps):
    total_rounds = sum(m.get('rounds', 0) for m in all_maps)
    total_kills = sum(m.get('kills', 0) for m in all_maps)
    if total_rounds == 0:
        return 15.0
    kpr = total_kills / total_rounds
    if kpr >= 0.85:
        return 22.0
    elif kpr >= 0.75:
        return 18.0
    elif kpr >= 0.68:
        return 15.0
    return 12.0

def calculate_round_swing_impact(kpr, hs_rate):
    if kpr >= 0.80 and hs_rate >= 40:
        return 12.5
    elif kpr >= 0.75 and hs_rate >= 37:
        return 10.0
    elif kpr >= 0.68:
        return 8.0
    return 5.5

def calculate_ceiling_floor(kills_list):
    if len(kills_list) < 3:
        return max(kills_list) if kills_list else 0, min(kills_list) if kills_list else 0
    sorted_kills = sorted(kills_list, reverse=True)
    return round(_stats.mean(sorted_kills[:3]), 1), round(_stats.mean(sorted_kills[-3:]), 1)

def project_map_scenarios(kpr, opponent_strength_factor):
    adjusted_kpr = kpr * opponent_strength_factor
    return {
        "short": {"rounds_per_map": 19, "total_rounds": 38, "expected_kills": round(adjusted_kpr * 38, 1)},
        "normal": {"rounds_per_map": 22, "total_rounds": 44, "expected_kills": round(adjusted_kpr * 44, 1)},
        "long": {"rounds_per_map": 25, "total_rounds": 50, "expected_kills": round(adjusted_kpr * 50, 1)},
    }

def analyze_map_pool_enhanced(all_maps):
    map_stats = defaultdict(lambda: {"kills": [], "kpr": [], "rounds": []})
    for m in all_maps:
        map_name = m.get("map_name", "unknown")
        if map_name != "unknown":
            map_stats[map_name]["kills"].append(m.get("kills", 0))
            map_stats[map_name]["rounds"].append(m.get("rounds", 22))
            if m.get("rounds", 0) > 0:
                map_stats[map_name]["kpr"].append(m["kills"] / m["rounds"])
    
    map_averages = {}
    for map_name, stats in map_stats.items():
        if stats["kills"]:
            map_averages[map_name] = {
                "avg_kills": round(_stats.mean(stats["kills"]), 1),
                "avg_kpr": round(_stats.mean(stats["kpr"]), 3) if stats["kpr"] else 0.68,
                "sample_size": len(stats["kills"]),
            }
    
    sorted_maps = sorted(map_averages.items(), key=lambda x: x[1]["avg_kills"], reverse=True)
    likely_maps = {}
    if len(sorted_maps) >= 3:
        likely_maps["Best Map"] = f"{sorted_maps[0][0].title()} ({sorted_maps[0][1]['avg_kills']}k)"
        likely_maps["2nd Map"] = f"{sorted_maps[1][0].title()} ({sorted_maps[1][1]['avg_kills']}k)"
        likely_maps["3rd Map"] = f"{sorted_maps[2][0].title()} ({sorted_maps[2][1]['avg_kills']}k)"
    return map_averages, likely_maps

def estimate_opponent_strength(opponent_name):
    elite_defense = {
        "vitality": 0.85, "faze": 0.87, "navi": 0.87, "spirit": 0.88,
        "g2": 0.92, "mouz": 0.93, "liquid": 0.91, "heroic": 0.92
    }
    opponent_lower = opponent_name.lower()
    for team, factor in elite_defense.items():
        if team in opponent_lower:
            return factor
    return 1.02

def analyze_h2h_history(all_maps, opponent):
    opponent_lower = opponent.lower()
    h2h_maps = [m for m in all_maps if opponent_lower in m.get("opponent", "").lower()]
    if not h2h_maps:
        return {"h2h_sample_size": 0, "h2h_avg_kills": "N/A", "h2h_kpr": "N/A", "h2h_note": "No recent H2H data"}
    h2h_kills = [m["kills"] for m in h2h_maps]
    h2h_rounds = sum(m.get("rounds", 0) for m in h2h_maps)
    return {
        "h2h_sample_size": len(h2h_maps),
        "h2h_avg_kills": round(_stats.mean(h2h_kills), 1),
        "h2h_kpr": round(sum(h2h_kills) / h2h_rounds, 3) if h2h_rounds > 0 else 0.68,
        "h2h_note": f"Last {len(h2h_maps)} maps vs this opponent",
    }

def calculate_weighted_grade(edge_delta, hit_rate, avg_vs_line, role, multi_kill_pct, round_swing_pct, scenarios):
    base_score = 5.0
    if abs(edge_delta) >= 25: base_score += 3.0
    elif abs(edge_delta) >= 20: base_score += 2.5
    elif abs(edge_delta) >= 15: base_score += 2.0
    elif abs(edge_delta) >= 10: base_score += 1.5
    elif abs(edge_delta) >= 5: base_score += 1.0
    
    if hit_rate >= 70: base_score += 1.5
    elif hit_rate >= 60: base_score += 1.0
    elif hit_rate <= 30: base_score -= 1.0
    elif hit_rate <= 40: base_score -= 0.5
    
    if abs(avg_vs_line) >= 8: base_score += 1.5
    elif abs(avg_vs_line) >= 5: base_score += 1.0
    elif abs(avg_vs_line) >= 3: base_score += 0.5
    
    if role in ["Star Rifler", "Primary AWPer", "Entry Fragger"]: base_score += 1.0
    elif role in ["Lurker/Closer"]: base_score += 0.5
    
    if multi_kill_pct >= 20: base_score += 0.75
    elif multi_kill_pct >= 17: base_score += 0.5
    
    if round_swing_pct >= 12: base_score += 0.75
    elif round_swing_pct >= 10: base_score += 0.5
    
    final_score = min(10.0, max(1.0, base_score))
    if final_score >= 9.5: return f"{final_score:.1f}/10 🔥 ELITE EDGE"
    elif final_score >= 8.5: return f"{final_score:.1f}/10 ⭐ Very Strong"
    elif final_score >= 7.5: return f"{final_score:.1f}/10 ✅ Strong Play"
    elif final_score >= 6.5: return f"{final_score:.1f}/10 👍 Solid Lean"
    elif final_score >= 5.5: return f"{final_score:.1f}/10 ⚖️ Small Edge"
    return f"{final_score:.1f}/10 ❌ No Bet"

def get_player_info(player_name, line=0.0, opponent="N/A"):
    try:
        search_res = search_player(player_name)
        if not search_res: 
            return _error_response(f"Could not find player '{player_name}' on HLTV.", player_name, line, opponent)
        pid, slug, display = search_res
        
        stats_url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"
        html, _ = _fetch(stats_url, render=True)
        if not html: 
            return _error_response("Stats page blocked. Try again.", display, line, opponent)

        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", {"class": "stats-table"})
        if not table:
            return _error_response("Stats table layout failed to render.", display, line, opponent)
        
        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")

        all_maps = []
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 4: continue
            try:
                cell_texts = [c.text.strip() for c in cols]
                date = "N/A"
                for txt in cell_texts:
                    if re.search(r'^\d{2}/\d{2}/\d{2}$', txt):
                        date = txt
                        break

                known_maps = {'anc', 'mrg', 'd2', 'inf', 'nuke', 'anb', 'vrt', 'ovp', 'ancient', 'mirage', 'dust2', 'inferno', 'anubis', 'vertigo', 'overpass'}
                map_name = "unknown"
                for txt in cell_texts:
                    if txt.lower() in known_maps:
                        map_name = {'anc': 'ancient', 'mrg': 'mirage', 'd2': 'dust2', 'inf': 'inferno', 'anb': 'anubis', 'vrt': 'vertigo', 'ovp': 'overpass'}.get(txt.lower(), txt.lower())
                        break
                
                opp = "unknown"
                for idx, txt in enumerate(cell_texts):
                    if map_name.lower() in txt.lower() and idx > 0:
                        opp = cell_texts[idx - 1].lower()
                        break
                opp = re.sub(r'\(.*\)', '', opp).strip()
                opp = re.sub(r'\s+\d+\s*$', '', opp).strip()
                
                m_rounds = 22
                for txt in cell_texts:
                    paren_match = re.search(r'\((\d+)\)', txt)
                    if paren_match:
                        val = int(paren_match.group(1))
                        if 10 <= val <= 60:
                            m_rounds = val
                            break
                
                for col in cols:
                    col_text = col.text.strip()
                    kd_match = re.search(r'(\d+)\s*-\s*(\d+)', col_text)
                    if kd_match:
                        kills = int(kd_match.group(1))
                        deaths = int(kd_match.group(2))
                        hs_paren = re.search(r'\((\d+)\)', col_text)
                        headshots = int(hs_paren.group(1)) if hs_paren else max(0, int(kills * 0.37))
                        
                        if 1 <= kills <= 50 and 1 <= deaths <= 50:
                            all_maps.append({
                                "date": date, "opponent": opp, "map_name": map_name,
                                "kills": kills, "deaths": deaths, "headshots": headshots, "rounds": m_rounds
                            })
                            break
            except Exception:
                continue

        if len(all_maps) < 2:
            return _error_response(f"Found only {len(all_maps)} maps. Insufficient volume.", display, line, opponent)

        series_groups = []
        current_group = [all_maps[0]]
        for m_data in all_maps[1:]:
            if m_data['opponent'] == current_group[0]['opponent'] and m_data['date'] == current_group[0]['date']:
                current_group.append(m_data)
            else:
                series_groups.append(current_group)
                current_group = [m_data]
        if current_group: series_groups.append(current_group)

        final_series_totals, final_series_hs_totals, paired_series_rows = [], [], []
        for group in series_groups:
            if len(final_series_totals) >= 10: break
            if len(group) >= 2:
                combined_k = group[-1]["kills"] + group[-2]["kills"]
                combined_hs = group[-1]["headshots"] + group[-2]["headshots"]
                combined_r = group[-1]["rounds"] + group[-2]["rounds"]
                
                final_series_totals.append(combined_k)
                final_series_hs_totals.append(combined_hs)
                paired_series_rows.append({
                    "opponent": group[-1].get("opponent", "N/A").upper(),
                    "date": group[-1].get("date", "N/A"), "kills": combined_k,
                    "headshots": combined_hs, "rounds": combined_r,
                    "map1": group[-1].get("map_name", "unknown"), "map2": group[-2].get("map_name", "unknown"),
                })

        if not final_series_totals:
            return _error_response("Could not map structural series sets.", display, line, opponent)

        avg_2map = round(_stats.mean(final_series_totals), 2)
        median = round(_stats.median(final_series_totals), 1)
        avg_hs = round(_stats.mean(final_series_hs_totals), 1)
        
        total_k = sum(final_series_totals)
        total_r = sum(m["rounds"] for m in all_maps)
        kpr = total_k / total_r if total_r > 0 else 0.68
        dpr = sum(m["deaths"] for m in all_maps) / total_r if total_r > 0 else 0.65
        hs_rate = (sum(final_series_hs_totals) / total_k * 100) if total_k > 0 else 40.0
        
        hits = sum(1 for x in final_series_totals if x > line)
        hit_rate_pct = (hits / len(final_series_totals)) * 100
        
        advanced_stats = extract_advanced_stats_from_matches(all_maps)
        role = classify_role_from_stats(kpr, dpr, hs_rate)
        ceiling, floor = calculate_ceiling_floor(final_series_totals)
        multi_kill_pct = calculate_multi_kill_rounds(all_maps)
        round_swing_pct = calculate_round_swing_impact(kpr, hs_rate)
        map_averages, likely_maps = analyze_map_pool_enhanced(all_maps)
        opponent_strength = estimate_opponent_strength(opponent)
        h2h_data = analyze_h2h_history(all_maps, opponent)
        scenarios = project_map_scenarios(kpr, opponent_strength)
        
        expected_kills = max(0.1, round(kpr * opponent_strength * 44, 1))
        var_2map = _stats.variance(final_series_totals) if len(final_series_totals) > 1 else avg_2map
        if var_2map <= expected_kills: var_2map = expected_kills * 1.25
        
        p_nb = max(0.01, min(0.99, expected_kills / var_2map))
        n_nb = max(1, int((expected_kills ** 2) / (var_2map - expected_kills) if var_2map > expected_kills else 1))
        
        np.random.seed(42)
        sim = np.random.negative_binomial(n_nb, p_nb, 100000)
        over_prob = (np.sum(sim > line) / 100000) * 100 if line > 0 else 50.0
        under_prob = 100.0 - over_prob
        edge_delta = over_prob - 50.0
        
        bet_rec = "OVER" if avg_2map > line and median > line and hit_rate_pct >= 60.0 else "UNDER" if avg_2map < line and median < line and hit_rate_pct <= 40.0 else "NO BET"
        mispriced = "CLEAR MISPRICE (Underpriced)" if line > 0 and (avg_2map - line) >= 8.0 else "CLEAR MISPRICE (Overpriced)" if line > 0 and (line - avg_2map) >= 8.0 else "YES" if abs(avg_2map - line) >= 4.0 else "NO"
        grade_str = calculate_weighted_grade(edge_delta, hit_rate_pct, avg_2map - line, role, multi_kill_pct, round_swing_pct, scenarios)

        return {
            "Player": display, "Match": f"vs {opponent.title()}", "Prop": f"{line} Kills", "Prop Line": f"{line} Kills O/U",
            "Role": role, "Recent sample used": f"Last {len(final_series_totals)} BO3 Series (Maps 1–2)",
            "Recent average": avg_2map, "Recent median": median, "Hit rate": f"{round(hit_rate_pct, 1)}%",
            "Rating 3.0": advanced_stats.get("rating_3", 1.0), "KPR": advanced_stats.get("kpr", 0.68),
            "DPR": advanced_stats.get("dpr", 0.65), "Impact": advanced_stats.get("impact", 1.0), "HS %": f"{round(hs_rate, 1)}%",
            "Multi-kill %": f"{multi_kill_pct}%", "Round Swing %": f"{round(round_swing_pct, 1)}%",
            "Ceiling (Top 3)": ceiling, "Floor (Bottom 3)": floor, "Projected rounds": 44, "Expected kills": expected_kills,
            "Scenarios": scenarios, "Per-map averages": map_averages, "Likely maps": likely_maps,
            "Opponent strength factor": opponent_strength, "H2H Data": h2h_data,
            "Simulated mean": round(np.mean(sim), 2), "Simulated median": round(np.median(sim), 2),
            "Std Dev": round(_stats.stdev(final_series_totals), 2) if len(final_series_totals) > 1 else 0,
            "25th percentile": round(np.percentile(sim, 25), 1), "75th percentile": round(np.percentile(sim, 75), 1),
            "Over probability": f"{round(over_prob, 1)}%", "Under probability": f"{round(under_prob, 1)}%", "Edge vs line": f"{round(edge_delta, 1)}%",
            "Mispriced or not": mispriced, "Final grade": grade_str, "Bet recommendation": bet_rec,
            "Recent Totals (M1+M2 Combined)": final_series_totals, "Recent HS Totals (M1+M2)": final_series_hs_totals,
            "Recent HS Average": avg_hs, "HS Rate": f"{round(hs_rate, 1)}%", "Paired series rows": paired_series_rows, "Raw maps": all_maps[:20],
        }
    except Exception as global_e:
        print(f"💥 CRITICAL EXCEPTION: {global_e}")
        return _error_response(f"System crash: {str(global_e)}", player_name, line, opponent)
