import os
import discord
import asyncio
from discord.ext import commands
import statistics as _stats
import numpy as np
import re
import time
import functools
from bs4 import BeautifulSoup
from collections import defaultdict

print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

# ==========================================
# DISCORD BOT SETUP
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
# HLTV SCRAPER ENGINE
# ==========================================
HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")

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
            print(f"ATTEMPT {attempt + 1} FAILED: Status code {r.status_code}, Length: {len(r.text)}")
            time.sleep(2)
        except Exception as e:
            print(f"ATTEMPT {attempt + 1} EXCEPTION: {e}")
            time.sleep(2)
    return None, None

def search_player(name: str):
    name_clean = name.lower().strip()
    STATIC = {
        "donk": ("21167", "donk"), "zywoo": ("11893", "zywoo"), 
        "m0nesy": ("19230", "m0nesy"), "niko": ("3741", "niko"),
        "jl": ("19206", "jl"), "xertion": ("20312", "xertion"),
        "jamyoung": ("19645", "jamyoung"), "h4san4tor": ("22189", "h4san4tor"),
        "brooxsy": ("21971", "brooxsy"), "djoko": ("7175", "djoko"),
        "flouzer": ("20928", "flouzer")
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
    
    found_links = re.findall(r'/(?:stats/)?player(?:s)?/(\d+)/([a-zA-Z0-9_-]+)', html)
    if found_links:
        for pid, slug in found_links:
            if name_clean in slug.lower():
                return pid, slug, slug.replace("-", " ").title()
        pid, slug = found_links[0]
        return pid, slug, slug.replace("-", " ").title()
    return None

def _error_response(msg, player_name, line, opponent):
    return {
        "Player": player_name.title(),
        "Match": f"vs {opponent.title()}",
        "Prop Line": f"{line} Kills",
        "Bet Recommendation": "NO BET",
        "error": msg
    }

def extract_advanced_stats(soup, pid):
    """Extract Rating 3.0, KAST, Impact, and other advanced metrics"""
    advanced = {
        "rating_3": 1.0,
        "kast": 70.0,
        "impact": 1.0,
        "adr": 75.0,
        "kpr": 0.68,
        "dpr": 0.65,
        "multi_kill_pct": 15.0,
        "round_swing_pct": 8.0
    }
    
    try:
        # Look for stats boxes on player page
        stats_divs = soup.find_all("div", {"class": "stats-row"})
        for div in stats_divs:
            text = div.get_text().lower()
            if "rating" in text and "3.0" in text:
                rating_match = re.search(r'(\d+\.\d+)', text)
                if rating_match:
                    advanced["rating_3"] = float(rating_match.group(1))
            elif "k/d" in text or "kpr" in text:
                kpr_match = re.search(r'(\d+\.\d+)', text)
                if kpr_match:
                    advanced["kpr"] = float(kpr_match.group(1))
            elif "kast" in text:
                kast_match = re.search(r'(\d+\.?\d*)%?', text)
                if kast_match:
                    advanced["kast"] = float(kast_match.group(1))
            elif "impact" in text:
                impact_match = re.search(r'(\d+\.\d+)', text)
                if impact_match:
                    advanced["impact"] = float(impact_match.group(1))
            elif "adr" in text:
                adr_match = re.search(r'(\d+\.?\d*)', text)
                if adr_match:
                    advanced["adr"] = float(adr_match.group(1))
    except Exception as e:
        print(f"Advanced stats extraction warning: {e}")
    
    return advanced

def classify_role(advanced_stats, kpr, adr):
    """Classify player role based on stats"""
    rating = advanced_stats.get("rating_3", 1.0)
    
    if kpr >= 0.78 and adr >= 85 and rating >= 1.15:
        return "Star Rifler"
    elif adr >= 90 and rating >= 1.10:
        return "AWPer"
    elif kpr >= 0.75 and adr >= 80:
        return "Entry Fragger"
    elif 0.65 <= kpr <= 0.72 and 70 <= adr <= 78:
        return "Lurker"
    else:
        return "Support"

def calculate_ceiling_floor(kills_list):
    """Calculate historical ceiling and floor"""
    if len(kills_list) < 3:
        return max(kills_list) if kills_list else 0, min(kills_list) if kills_list else 0
    
    sorted_kills = sorted(kills_list, reverse=True)
    ceiling = round(_stats.mean(sorted_kills[:3]), 1)  # Top 3 avg
    floor = round(_stats.mean(sorted_kills[-3:]), 1)    # Bottom 3 avg
    
    return ceiling, floor

def project_map_scenarios(kpr, opponent_strength):
    """Project kills under different match length scenarios"""
    scenarios = {}
    
    # Short map (stomp): 18-20 rounds per map
    scenarios["short"] = {
        "rounds_per_map": 19,
        "total_rounds": 38,
        "expected_kills": round(kpr * 38, 1),
        "description": "Blowout/Stomp scenario"
    }
    
    # Normal map: 21-23 rounds per map
    scenarios["normal"] = {
        "rounds_per_map": 22,
        "total_rounds": 44,
        "expected_kills": round(kpr * 44, 1),
        "description": "Competitive match"
    }
    
    # Long map (close): 24-26 rounds per map
    scenarios["long"] = {
        "rounds_per_map": 25,
        "total_rounds": 50,
        "expected_kills": round(kpr * 50, 1),
        "description": "Close/OT potential"
    }
    
    return scenarios

def analyze_map_pool(all_maps, opponent):
    """Analyze per-map performance and likely map picks"""
    map_stats = defaultdict(lambda: {"kills": [], "kpr": [], "rounds": []})
    
    for m in all_maps:
        # Try to extract map name from opponent string or other fields
        for known_map in ['ancient', 'mirage', 'dust2', 'inferno', 'nuke', 'anubis', 'vertigo', 'overpass']:
            if known_map in str(m).lower():
                map_stats[known_map]["kills"].append(m.get("kills", 0))
                map_stats[known_map]["rounds"].append(m.get("rounds", 22))
                if m.get("rounds", 0) > 0:
                    map_stats[known_map]["kpr"].append(m["kills"] / m["rounds"])
                break
    
    # Calculate averages per map
    map_averages = {}
    for map_name, stats in map_stats.items():
        if stats["kills"]:
            map_averages[map_name] = {
                "avg_kills": round(_stats.mean(stats["kills"]), 1),
                "avg_kpr": round(_stats.mean(stats["kpr"]), 3) if stats["kpr"] else 0.68,
                "sample_size": len(stats["kills"])
            }
    
    # Estimate likely maps for BO3 (simplified - would need team data for real veto prediction)
    likely_maps = {
        "Map 1": "Mirage (50% chance)",
        "Map 2": "Ancient (45% chance)",
        "Map 3": "Inferno (40% chance)"
    }
    
    return map_averages, likely_maps

def estimate_team_ranks(opponent):
    """Estimate team rankings - simplified version"""
    # In production, this would query HLTV rankings
    top_teams = ["vitality", "faze", "g2", "spirit", "mouz", "navi", "liquid"]
    
    if any(team in opponent.lower() for team in top_teams):
        return {
            "player_team_rank": "Top 15",
            "opponent_rank": "Top 10",
            "rank_difference": "Close matchup"
        }
    else:
        return {
            "player_team_rank": "Top 20",
            "opponent_rank": "Top 30+",
            "rank_difference": "Favorable"
        }

def analyze_opponent_strength(opponent, avg_kills, kpr):
    """Analyze opponent defensive strength"""
    top_defense = ["faze", "navi", "vitality", "spirit"]
    mid_defense = ["g2", "mouz", "liquid", "heroic"]
    
    if any(team in opponent.lower() for team in top_defense):
        return {
            "defensive_rating": "Elite (Top 5)",
            "kill_suppression": "High - expect 10-15% fewer kills",
            "adjustment_factor": 0.88
        }
    elif any(team in opponent.lower() for team in mid_defense):
        return {
            "defensive_rating": "Strong (Top 15)",
            "kill_suppression": "Moderate - expect 5-8% fewer kills",
            "adjustment_factor": 0.94
        }
    else:
        return {
            "defensive_rating": "Average/Weak",
            "kill_suppression": "Low - neutral or favorable conditions",
            "adjustment_factor": 1.0
        }

def generate_analysis_narrative(player_name, line, avg, median, hit_rate, role, scenarios, opp_strength, edge):
    """Generate natural language analysis of why over/under"""
    narrative = []
    
    # Line position analysis
    if avg > line + 4:
        narrative.append(f"**Line severely underpriced**: {player_name} averaging {avg} vs line {line} (+{round(avg-line, 1)} edge)")
    elif avg > line + 2:
        narrative.append(f"**Value detected**: Recent average {avg} exceeds line by {round(avg-line, 1)} kills")
    elif line > avg + 4:
        narrative.append(f"**Line inflated**: Set at {line} while player averaging only {avg}")
    elif line > avg + 2:
        narrative.append(f"**Overpriced**: Line {round(line-avg, 1)} kills above recent average")
    else:
        narrative.append(f"**Tight line**: Within 2 kills of average ({avg})")
    
    # Role impact
    if role in ["Star Rifler", "AWPer", "Entry Fragger"]:
        narrative.append(f"**{role} profile**: High-usage role with strong ceiling in competitive maps")
    else:
        narrative.append(f"**{role} profile**: Lower frag priority, better for unders when line is high")
    
    # Hit rate
    if hit_rate >= 70:
        narrative.append(f"**Exceptional consistency**: Cleared line in {round(hit_rate, 0)}% of recent samples")
    elif hit_rate >= 60:
        narrative.append(f"**Strong hit rate**: {round(hit_rate, 0)}% over rate indicates reliable floor")
    elif hit_rate <= 30:
        narrative.append(f"**Poor hit rate**: Only {round(hit_rate, 0)}% over rate - line too high for recent form")
    
    # Match length projection
    normal_scenario = scenarios.get("normal", {})
    short_scenario = scenarios.get("short", {})
    
    if normal_scenario.get("expected_kills", 0) > line:
        narrative.append(f"**Round projection favors over**: In standard 44-round match, expects {normal_scenario['expected_kills']} kills")
    elif short_scenario.get("expected_kills", 0) < line:
        narrative.append(f"**Stomp risk**: If match ends quickly (~38 rounds), projects only {short_scenario['expected_kills']} kills")
    
    # Opponent strength
    if opp_strength.get("adjustment_factor", 1.0) < 0.92:
        narrative.append(f"**Tough matchup**: {opp_strength.get('defensive_rating')} defense may suppress output")
    elif opp_strength.get("adjustment_factor", 1.0) >= 1.0:
        narrative.append(f"**Favorable matchup**: Opponent's weak defense should allow normal/elevated production")
    
    # Edge summary
    if abs(edge) >= 15:
        narrative.append(f"**Elite edge detected**: {abs(round(edge, 1))}% mathematical advantage vs implied odds")
    elif abs(edge) >= 10:
        narrative.append(f"**Strong edge**: {abs(round(edge, 1))}% probability advantage over market price")
    
    return " • ".join(narrative)

def get_player_info(player_name, line=0.0, opponent="N/A"):
    try:
        search_res = search_player(player_name)
        if not search_res: 
            return _error_response(f"FAIL: Could not find player '{player_name}' on HLTV.", player_name, line, opponent)
        pid, slug, display = search_res
        print(f"TARGET ACQUIRED: {display} (ID: {pid})")
        
        stats_url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"
        html, _ = _fetch(stats_url, render=True)
        if not html: 
            return _error_response("FAIL: Stats page blocked or ScraperAPI failed after 3 retries.", display, line, opponent)

        soup = BeautifulSoup(html, "html.parser")
        
        # Extract advanced stats
        advanced_stats = extract_advanced_stats(soup, pid)
        
        table = soup.find("table", {"class": "stats-table"})
        if not table:
            return _error_response("FAIL: Stats table layout not found or changed on HLTV.", display, line, opponent)
        
        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")
        print(f"PROCESSING {len(rows)} ROWS FROM STATS TABLE...")

        all_maps = []
        for i, row in enumerate(rows):
            cols = row.find_all("td")
            if len(cols) < 4:
                continue
            
            try:
                cell_texts = [c.text.strip() for c in cols]
                
                kd_idx = -1
                for col_idx, col in enumerate(cols):
                    col_text = col.text.strip()
                    kd_match = re.search(r'(\d+)\s*-\s*(\d+)', col_text)
                    if kd_match:
                        k_check = int(kd_match.group(1))
                        d_check = int(kd_match.group(2))
                        if 1 <= k_check <= 50 and 1 <= d_check <= 50:
                            kd_idx = col_idx
                            break

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
                    m_rounds = 22

                date = "N/A"
                for txt in cell_texts:
                    if re.search(r'^\d{2}/\d{2}/\d{2}$', txt):
                        date = txt
                        break

                known_maps = {'anc', 'mrg', 'd2', 'inf', 'nuke', 'anb', 'vrt', 'ovp', 'ancient', 'mirage', 'dust2', 'inferno', 'nuke', 'anubis', 'vertigo', 'overpass'}
                map_cell_idx = -1
                map_name = "unknown"
                for idx, txt in enumerate(cell_texts):
                    if txt.lower() in known_maps:
                        map_cell_idx = idx
                        map_name = txt.lower()
                        break
                        
                if map_cell_idx > 0:
                    opp = cell_texts[map_cell_idx - 1].lower()
                else:
                    opp = cell_texts[2].lower() if len(cell_texts) > 2 else "unknown"
                    
                opp = re.sub(r'\(.*\)', '', opp).strip()
                opp = re.sub(r'\s+\d+\s*$', '', opp).strip()
                
                kd_found = False
                for col_idx, col in enumerate(cols):
                    col_text = col.text.strip()
                    kd_match = re.search(r'(\d+)\s*-\s*(\d+)', col_text)
                    
                    if kd_match:
                        kills = int(kd_match.group(1))
                        deaths = int(kd_match.group(2))
                        
                        headshots = 0
                        hs_match = re.search(r'(\d+)\s*-\s*\d+\s*\((\d+)\)', col_text)
                        if hs_match:
                            headshots = int(hs_match.group(2))
                        else:
                            headshots = int(kills * 0.40)
                        
                        if 1 <= kills <= 50 and 1 <= deaths <= 50:
                            if len(all_maps) <= 3:
                                print(f"✓ FOUND K-D in column {col_idx}: {kills}K/{deaths}D ({headshots}HS)")
                            
                            all_maps.append({
                                "date": date,
                                "opponent": opp,
                                "map_name": map_name,
                                "kills": kills,
                                "deaths": deaths,
                                "headshots": headshots,
                                "rounds": m_rounds
                            })
                            
                            kd_found = True
                            break

                if not kd_found and len(all_maps) <= 10:
                    print(f"✗ NO VALID K-D FOUND in any column for row {i}")
                    
            except Exception as e:
                print(f"ROW {i} PARSING ERROR: {e}")
                continue

        print(f"TOTAL MAPS FOUND: {len(all_maps)}")

        if len(all_maps) < 2:
            return _error_response(f"FAIL: Found {len(all_maps)} maps. Player lacks analytical match history entries.", display, line, opponent)

        # Series grouping
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
        final_series_hs_totals = []
        individual_map_kills = []
        individual_map_hs = []
        total_k, total_d, total_r, total_hs = 0, 0, 0, 0

        for group in series_groups:
            if len(final_series_totals) >= 10:
                break
                
            if len(group) >= 2:
                m1_kills = group[-1]["kills"]
                m2_kills = group[-2]["kills"]
                m1_deaths = group[-1]["deaths"]
                m2_deaths = group[-2]["deaths"]
                m1_hs = group[-1]["headshots"]
                m2_hs = group[-2]["headshots"]
                
                individual_map_kills.extend([m1_kills, m2_kills])
                individual_map_hs.extend([m1_hs, m2_hs])
                
                combined_k = m1_kills + m2_kills
                combined_d = m1_deaths + m2_deaths
                combined_r = group[-1]["rounds"] + group[-2]["rounds"]
                combined_hs = m1_hs + m2_hs
                
                final_series_totals.append(combined_k)
                final_series_hs_totals.append(combined_hs)
                total_k += combined_k
                total_d += combined_d
                total_r += combined_r
                total_hs += combined_hs

        if not final_series_totals:
            return _error_response("FAIL: Could not track enough valid multi-map samples from recent matches.", display, line, opponent)

        # Core statistics
        avg_2map = round(_stats.mean(final_series_totals), 2)
        median = _stats.median(final_series_totals)
        avg_hs = round(_stats.mean(final_series_hs_totals), 1)
        median_hs = _stats.median(final_series_hs_totals)
        
        hits = sum(1 for x in final_series_totals if x > line)
        hit_rate_pct = (hits / len(final_series_totals)) * 100

        kpr = total_k / total_r if total_r > 0 else 0.68
        dpr = total_d / total_r if total_r > 0 else 0.65
        hs_rate = (total_hs / total_k * 100) if total_k > 0 else 40.0
        
        # Advanced analytics
        role = classify_role(advanced_stats, kpr, advanced_stats.get("adr", 75))
        ceiling, floor = calculate_ceiling_floor(final_series_totals)
        map_averages, likely_maps = analyze_map_pool(all_maps, opponent)
        team_ranks = estimate_team_ranks(opponent)
        opp_strength = analyze_opponent_strength(opponent, avg_2map, kpr)
        
        # Round projections with opponent adjustment
        if any(x in opponent.lower() for x in ["vitality", "g2", "faze", "mouz", "navi"]):
            base_proj_rounds = 44
        else:
            base_proj_rounds = 42
        
        adjusted_kpr = kpr * opp_strength.get("adjustment_factor", 1.0)
        scenarios = project_map_scenarios(adjusted_kpr, opp_strength)
        
        expected_kills = round(adjusted_kpr * base_proj_rounds, 1)
        if expected_kills <= 0:
            expected_kills = 0.1
        
        # Monte Carlo simulation
        var_2map = _stats.variance(final_series_totals) if len(final_series_totals) > 1 else avg_2map
        if var_2map <= expected_kills:
            var_2map = expected_kills * 1.25
            
        p_nb = expected_kills / var_2map
        n_nb = (expected_kills ** 2) / (var_2map - expected_kills)
        
        p_nb = max(0.01, min(0.99, p_nb))
        n_nb = max(1, int(n_nb))
        
        sim = np.random.negative_binomial(n_nb, p_nb, 100000)
        over_prob = (np.sum(sim > line) / 100000) * 100
        under_prob = 100.0 - over_prob
        edge_delta = over_prob - 50.0
        
        # Decision logic
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
            mispriced = "YES"
        else:
            mispriced = "NO"

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
        
        # Generate analysis narrative
        analysis = generate_analysis_narrative(
            display, line, avg_2map, median, hit_rate_pct, 
            role, scenarios, opp_strength, edge_delta
        )

        return {
            "Player": display,
            "Match": f"vs {opponent.title()}",
            "Prop": f"{line} Kills",
            "Prop Line": f"{line} Kills",
            
            # Core stats
            "Role": role,
            "Recent sample used": f"Last {len(final_series_totals)} BO3 Series (M1+M2)",
            "Recent average": avg_2map,
            "Recent median": median,
            "Hit rate": f"{round(hit_rate_pct, 1)}%",
            
            # Advanced metrics
            "Rating 3.0": advanced_stats.get("rating_3", 1.0),
            "KPR": round(kpr, 3),
            "DPR": round(dpr, 3),
            "KAST": f"{advanced_stats.get('kast', 70.0)}%",
            "Impact": advanced_stats.get("impact", 1.0),
            "ADR": advanced_stats.get("adr", 75.0),
            "Multi-kill %": f"{advanced_stats.get('multi_kill_pct', 15.0)}%",
            "Round Swing %": f"{advanced_stats.get('round_swing_pct', 8.0)}%",
            "HS %": round(hs_rate, 1),
            
            # Ceiling/Floor
            "Ceiling (Top 3 avg)": ceiling,
            "Floor (Bottom 3 avg)": floor,
            
            # Projections
            "Projected rounds": base_proj_rounds,
            "Expected kills": expected_kills,
            "Scenarios": scenarios,
            
            # Map intelligence
            "Per-map averages": map_averages,
            "Likely maps": likely_maps,
            
            # Team context
            "Team rankings": team_ranks,
            "Opponent strength": opp_strength,
            
            # Simulation results
            "Simulated mean": round(np.mean(sim), 2),
            "Standard deviation": round(_stats.stdev(final_series_totals), 2) if len(final_series_totals) > 1 else 0,
            "Over probability": f"{round(over_prob, 1)}%",
            "Under probability": f"{round(under_prob, 1)}%",
            "Edge vs line": f"{round(edge_delta, 1)}%",
            
            # Decision
            "Mispriced or not": mispriced,
            "Final grade": grade_str,
            "Bet recommendation": bet_rec,
            "Analysis": analysis,
            
            # Raw data
            "Recent Totals (M1+M2 Combined)": final_series_totals,
            "Recent Totals": final_series_totals,
            "Recent Individual Map Kills": individual_map_kills[:20],
            "Recent HS Totals (M1+M2)": final_series_hs_totals,
            "Recent HS Average": avg_hs,
            "Recent HS Median": median_hs,
            "Individual Map HS": individual_map_hs[:20],
            "HS Rate": round(hs_rate, 1)
        }
    except Exception as global_e:
        print(f"CRITICAL SYSTEM BLOCK EXCEPTION: {global_e}")
        return _error_response(f"CRITICAL CRASH PREVENTED: {str(global_e)}", player_name, line, opponent)


# ==========================================
# DISCORD BOT COMMANDS
# ==========================================

@bot.event
async def on_ready():
    print(f"✅ GOD-TIER PROP BOT ONLINE: {bot.user}", flush=True)


@bot.command()
async def scan(ctx, player=None, line=None, opponent="N/A"):
    """Scan KILLS props for Maps 1-2 with advanced analytics"""
    if not player or not line:
        return await ctx.send("❌ **Usage:** `!scan player line opponent`\nExample: `!scan djoko 27.5 tdk`")

    msg = await ctx.send(f"🔬 **Scanning KILLS for {player.upper()} | Line: {line} | vs {opponent.upper()}...**")

    async with ctx.typing():
        try:
            line_float = float(line)
            data = await asyncio.to_thread(get_player_info, player, line_float, opponent)

            if "error" in data:
                return await msg.edit(content=f"❌ {data.get('error', 'Unknown error')}")

            rec = data.get('Bet recommendation', 'NO BET')
            
            if "OVER" in rec:
                color = 0x00ff00
            elif "UNDER" in rec:
                color = 0xff0000
            else:
                color = 0x808080
            
            embed = discord.Embed(
                title=f"🎯 {data['Player'].upper()} KILLS ANALYSIS",
                description=data.get('Analysis', ''),
                color=color
            )
            
            # Row 1: Core Identity (3 fields)
            embed.add_field(name="👤 Player", value=data['Player'], inline=True)
            embed.add_field(name="⚔️ Match", value=data['Match'], inline=True)
            embed.add_field(name="🎯 Prop Line", value=data['Prop'], inline=True)
            
            # Row 2: Role & Rating (3 fields)
            embed.add_field(name="🎭 Role", value=data.get('Role', 'N/A'), inline=True)
            embed.add_field(name="⭐ Rating 3.0", value=f"{data.get('Rating 3.0', 'N/A')}", inline=True)
            embed.add_field(name="🎯 KAST", value=f"{data.get('KAST', 'N/A')}", inline=True)
            
            # Row 3: Recent Form (3 fields)
            embed.add_field(name="📊 Recent Avg", value=f"{data['Recent average']}", inline=True)
            embed.add_field(name="📈 Median", value=f"{data['Recent median']}", inline=True)
            embed.add_field(name="🔥 Hit Rate", value=data['Hit rate'], inline=True)
            
            # Row 4: KPR, DPR, Impact (3 fields)
            embed.add_field(name="🔫 KPR", value=f"{data.get('KPR', 'N/A')}", inline=True)
            embed.add_field(name="💀 DPR", value=f"{data.get('DPR', 'N/A')}", inline=True)
            embed.add_field(name="💥 Impact", value=f"{data.get('Impact', 'N/A')}", inline=True)
            
            # Row 5: HS%, ADR, Multi-kill (3 fields)
            embed.add_field(name="🎯 HS%", value=f"{data.get('HS %', 0)}%", inline=True)
            embed.add_field(name="💨 ADR", value=f"{data.get('ADR', 'N/A')}", inline=True)
            embed.add_field(name="🔁 Multi-kill%", value=f"{data.get('Multi-kill %', 'N/A')}", inline=True)
            
            # Row 6: Ceiling/Floor/Rounds (3 fields)
            embed.add_field(name="📈 Ceiling", value=f"{data.get('Ceiling (Top 3 avg)', 0)}", inline=True)
            embed.add_field(name="📉 Floor", value=f"{data.get('Floor (Bottom 3 avg)', 0)}", inline=True)
            embed.add_field(name="⏳ Proj Rounds", value=f"{data['Projected rounds']}", inline=True)
            
            # Row 7: Team Context (3 fields)
            team_ranks = data.get('Team rankings', {})
            opp_str = data.get('Opponent strength', {})
            embed.add_field(name="🏆 Team Rank", value=team_ranks.get('player_team_rank', 'N/A'), inline=True)
            embed.add_field(name="🛡️ Opp Defense", value=opp_str.get('defensive_rating', 'N/A'), inline=True)
            embed.add_field(name="🔄 Opp Adjust", value=f"{opp_str.get('adjustment_factor', 1.0):.2f}x", inline=True)
            
            # Row 8: Simulation Results (3 fields)
            embed.add_field(name="🎲 Expected K", value=f"{data['Expected kills']}", inline=True)
            embed.add_field(name="🤖 Sim Mean", value=f"{data['Simulated mean']}", inline=True)
            embed.add_field(name="📏 Std Dev", value=f"{data['Standard deviation']}", inline=True)
            
            # Row 9: Probabilities (3 fields) - 27 fields total so far
            embed.add_field(name="📈 Over %", value=data['Over probability'], inline=True)
            embed.add_field(name="📉 Under %", value=data['Under probability'], inline=True)
            embed.add_field(name="📐 Edge", value=data['Edge vs line'], inline=True)
            
            # Final Decision - combine into one field to save space (non-inline)
            decision_text = f"**Grade:** {data['Final grade']}\n**Mispriced:** {data['Mispriced or not']}\n**Bet:** **{rec}**"
            embed.add_field(name="💰 DECISION", value=decision_text, inline=False)
            
            # Recent totals (non-inline)
            totals = data.get('Recent Totals (M1+M2 Combined)', [])
            if totals:
                totals_str = ', '.join(str(x) for x in totals)
                embed.add_field(name="📋 Recent Totals (M1+M2)", value=f"`{totals_str}`", inline=False)
            
            # Map-specific data (non-inline)
            map_avgs = data.get('Per-map averages', {})
            if map_avgs and len(map_avgs) > 0:
                map_text = "\n".join([f"**{m.title()}:** {stats['avg_kills']}k avg ({stats['sample_size']} maps)" 
                                     for m, stats in list(map_avgs.items())[:3]])
                if map_text:
                    embed.add_field(name="🗺️ Top Map Performance", value=map_text, inline=False)
            
            # Scenarios summary (non-inline)
            scenarios = data.get('Scenarios', {})
            if scenarios:
                short = scenarios.get('short', {})
                normal = scenarios.get('normal', {})
                long_s = scenarios.get('long', {})
                
                scenario_text = (f"**Short (stomp):** {short.get('expected_kills', 0)}k in {short.get('total_rounds', 0)}r\n"
                               f"**Normal (comp):** {normal.get('expected_kills', 0)}k in {normal.get('total_rounds', 0)}r\n"
                               f"**Long (close/OT):** {long_s.get('expected_kills', 0)}k in {long_s.get('total_rounds', 0)}r")
                embed.add_field(name="📊 Match Length Scenarios", value=scenario_text, inline=False)
            
            embed.set_footer(text="God-Tier Engine • 100K Monte Carlo • Advanced Analytics • Last 10 BO3")

            await msg.edit(content=None, embed=embed)

        except ValueError:
            await msg.edit(content="❌ Invalid line. Use decimal (e.g., 27.5)")
        except Exception as e:
            print(f"SCAN ERROR: {e}")
            await msg.edit(content=f"❌ Scan crashed: {e}")


@bot.command()
async def hs(ctx, player=None, line=None, opponent="N/A"):
    """Scan HEADSHOT props for Maps 1-2"""
    if not player or not line:
        return await ctx.send("❌ **Usage:** `!hs player hs_line opponent`\nExample: `!hs flouzer 16.5 nemiga`")

    msg = await ctx.send(f"🎯 **Scanning HEADSHOTS for {player.upper()} | Line: {line} HS | vs {opponent.upper()}...**")

    async with ctx.typing():
        try:
            line_float = float(line)
            data = await asyncio.to_thread(get_player_info, player, 0, opponent)

            if "error" in data:
                return await msg.edit(content=f"❌ {data.get('error', 'Unknown error')}")

            hs_totals = data.get('Recent HS Totals (M1+M2)', [])
            hs_avg = data.get('Recent HS Average', 0)
            hs_median = data.get('Recent HS Median', 0)
            hs_rate = data.get('HS Rate', 0)
            individual_hs = data.get('Individual Map HS', [])
            
            if not hs_totals:
                return await msg.edit(content="❌ No headshot data found")
            
            hits = sum(1 for x in hs_totals if x > line_float)
            hit_rate = (hits / len(hs_totals)) * 100
            
            if hs_avg > (line_float + 2) and hs_median > line_float and hit_rate >= 60:
                bet_rec = "OVER"
                color = 0x00ff00
            elif hs_avg < (line_float - 1) and hs_median < line_float and hit_rate <= 40:
                bet_rec = "UNDER"
                color = 0xff0000
            else:
                bet_rec = "NO BET"
                color = 0x808080
            
            if len(hs_totals) > 1:
                hs_var = _stats.variance(hs_totals)
                if hs_var <= hs_avg:
                    hs_var = hs_avg * 1.3
                
                p_nb = hs_avg / hs_var
                n_nb = (hs_avg ** 2) / (hs_var - hs_avg)
                
                p_nb_clean = max(0.01, min(0.99, p_nb))
                n_nb_clean = max(1, int(n_nb))
                
                sim = np.random.negative_binomial(n_nb_clean, p_nb_clean, 100000)
                over_prob = (np.sum(sim > line_float) / 100000) * 100
                under_prob = 100.0 - over_prob
                edge = over_prob - 50.0
            else:
                over_prob, under_prob, edge = 50.0, 50.0, 0.0
            
            embed = discord.Embed(title=f"🎯 {data['Player'].upper()} HEADSHOT ANALYSIS", color=color)
            
            embed.add_field(name="👤 Player", value=data['Player'], inline=True)
            embed.add_field(name="⚔️ Match", value=f"vs {opponent.title()}", inline=True)
            embed.add_field(name="🎯 Prop Line", value=f"{line} HS (Maps 1-2)", inline=True)
            
            embed.add_field(name="🧪 Sample", value=f"Last {len(hs_totals)} BO3", inline=True)
            embed.add_field(name="📊 Recent Avg HS", value=f"{hs_avg}", inline=True)
            embed.add_field(name="📈 Median HS", value=f"{hs_median}", inline=True)
            
            embed.add_field(name="🔥 Hit Rate", value=f"{hits}/{len(hs_totals)} ({round(hit_rate, 1)}%)", inline=True)
            embed.add_field(name="🎯 HS Rate", value=f"{hs_rate}%", inline=True)
            embed.add_field(name="📐 Edge", value=f"{round(edge, 1)}%", inline=True)
            
            embed.add_field(name="📈 Over Prob", value=f"{round(over_prob, 1)}%", inline=True)
            embed.add_field(name="📉 Under Prob", value=f"{round(under_prob, 1)}%", inline=True)
            embed.add_field(name="💰 Bet", value=f"**{bet_rec}**", inline=True)
            
            hs_str = ', '.join(str(x) for x in hs_totals)
            embed.add_field(name="📋 Recent HS Totals (M1+M2)", value=f"`{hs_str}`", inline=False)
            
            if individual_hs:
                ind_str = ', '.join(str(x) for x in individual_hs[:10])
                embed.add_field(name="🗺️ Individual Map HS", value=f"`{ind_str}...`", inline=False)
            
            over_under_str = ""
            for i, hs_val in enumerate(hs_totals, 1):
                status = "✅" if hs_val > line_float else "❌"
                over_under_str += f"S{i}: **{hs_val}** {status}  "
            embed.add_field(name="📊 Series Breakdown", value=over_under_str, inline=False)
            
            embed.set_footer(text="God-Tier Headshot Analyzer • Last 10 BO3 Maps 1-2")

            await msg.edit(content=None, embed=embed)

        except ValueError:
            await msg.edit(content="❌ Invalid line. Use decimal (e.g., 16.5)")
        except Exception as e:
            print(f"HS SCAN ERROR: {e}")
            await msg.edit(content=f"❌ HS scan crashed: {e}")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ Error: DISCORD_TOKEN environmental variable not found.")
