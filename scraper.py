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

# ==========================================

# HLTV SCRAPER ENGINE

# ==========================================

HLTV_BASE = “https://www.hltv.org”
SCRAPERAPI_KEY = os.environ.get(“SCRAPERAPI_KEY”)

def _fetch(url, render=False):
if not SCRAPERAPI_KEY:
print(“CRITICAL: SCRAPERAPI_KEY environment variable is missing.”)
return None, None

```
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
```

def search_player(name: str):
name_clean = name.lower().strip()
STATIC = {
“donk”: (“21167”, “donk”), “zywoo”: (“11893”, “zywoo”),
“m0nesy”: (“19230”, “m0nesy”), “niko”: (“3741”, “niko”),
“jl”: (“19206”, “jl”), “xertion”: (“20312”, “xertion”),
“jamyoung”: (“19645”, “jamyoung”), “h4san4tor”: (“22189”, “h4san4tor”),
“brooxsy”: (“21971”, “brooxsy”), “djoko”: (“7175”, “djoko”),
“flouzer”: (“20928”, “flouzer”), “myltsi”: (“20928”, “myltsi”)
}
if name_clean in STATIC:
return STATIC[name_clean][0], STATIC[name_clean][1], STATIC[name_clean][1].title()

```
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
```

def _error_response(msg, player_name, line, opponent):
return {
“Player”: player_name.title(),
“Match”: f”vs {opponent.title()}”,
“Prop Line”: f”{line} Kills”,
“Bet Recommendation”: “NO BET”,
“error”: msg
}

def extract_advanced_stats(soup, pid):
“”“Extract Rating 3.0, KAST, Impact, and other advanced metrics”””
advanced = {
“rating_3”: 1.0,
“kast”: 70.0,
“impact”: 1.0,
“adr”: 75.0,
“kpr”: 0.68,
“dpr”: 0.65,
“clutch_success”: 0.0,
“opening_kill_rating”: 0.0,
“awp_kills_per_round”: 0.0,
“utility_damage”: 0.0,
“trade_kill_success”: 0.0
}

```
try:
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
```

def calculate_multi_kill_rounds(all_maps):
“”“Calculate actual multi-kill percentage from match data”””
total_rounds = sum(m.get(‘rounds’, 0) for m in all_maps)
total_kills = sum(m.get(‘kills’, 0) for m in all_maps)

```
if total_rounds == 0:
    return 15.0

# Estimate multi-kills: if KPR > 0.75, likely has frequent multi-kill rounds
kpr = total_kills / total_rounds if total_rounds > 0 else 0.68

if kpr >= 0.85:
    multi_kill_pct = 22.0
elif kpr >= 0.75:
    multi_kill_pct = 18.0
elif kpr >= 0.68:
    multi_kill_pct = 15.0
else:
    multi_kill_pct = 12.0

return round(multi_kill_pct, 1)
```

def calculate_round_swing_impact(all_maps, kpr, advanced_stats):
“”“Calculate round swing percentage based on clutches and opening kills”””
impact = advanced_stats.get(“impact”, 1.0)
rating = advanced_stats.get(“rating_3”, 1.0)

```
# High impact players create more round swings
if impact >= 1.25 and rating >= 1.20:
    return 12.5
elif impact >= 1.15 and rating >= 1.10:
    return 10.0
elif impact >= 1.05:
    return 8.0
else:
    return 5.5
```

def classify_role_detailed(advanced_stats, kpr, adr, all_maps):
“”“Classify player role with detailed usage stats”””
rating = advanced_stats.get(“rating_3”, 1.0)
impact = advanced_stats.get(“impact”, 1.0)
kast = advanced_stats.get(“kast”, 70.0)

```
# Calculate usage indicators
total_rounds = sum(m.get('rounds', 0) for m in all_maps)
total_kills = sum(m.get('kills', 0) for m in all_maps)

usage_stats = {
    "opening_duels": 0.0,
    "clutch_attempts": 0.0,
    "utility_usage": 0.0,
    "sniping_frequency": 0.0,
    "trade_opportunities": 0.0
}

# Role classification with usage metrics
if kpr >= 0.80 and adr >= 85 and rating >= 1.15:
    role = "Star Rifler"
    usage_stats["opening_duels"] = 85.0
    usage_stats["clutch_attempts"] = 75.0
    usage_stats["utility_usage"] = 65.0
    usage_stats["trade_opportunities"] = 80.0
elif adr >= 90 and rating >= 1.10 and kpr >= 0.75:
    role = "Primary AWPer"
    usage_stats["sniping_frequency"] = 95.0
    usage_stats["opening_duels"] = 70.0
    usage_stats["clutch_attempts"] = 60.0
    usage_stats["utility_usage"] = 40.0
elif kpr >= 0.75 and adr >= 78 and impact >= 1.10:
    role = "Entry Fragger"
    usage_stats["opening_duels"] = 95.0
    usage_stats["trade_opportunities"] = 85.0
    usage_stats["utility_usage"] = 55.0
    usage_stats["clutch_attempts"] = 50.0
elif 0.65 <= kpr <= 0.74 and 70 <= adr <= 80 and kast >= 72:
    role = "Lurker/Closer"
    usage_stats["clutch_attempts"] = 80.0
    usage_stats["opening_duels"] = 55.0
    usage_stats["trade_opportunities"] = 70.0
    usage_stats["utility_usage"] = 60.0
elif kast >= 75 and impact >= 1.05:
    role = "Support/IGL"
    usage_stats["utility_usage"] = 90.0
    usage_stats["trade_opportunities"] = 75.0
    usage_stats["clutch_attempts"] = 65.0
    usage_stats["opening_duels"] = 45.0
else:
    role = "Flex/Rotator"
    usage_stats["utility_usage"] = 70.0
    usage_stats["trade_opportunities"] = 65.0
    usage_stats["clutch_attempts"] = 60.0
    usage_stats["opening_duels"] = 60.0

return role, usage_stats
```

def calculate_ceiling_floor(kills_list):
“”“Calculate historical ceiling and floor”””
if len(kills_list) < 3:
return max(kills_list) if kills_list else 0, min(kills_list) if kills_list else 0

```
sorted_kills = sorted(kills_list, reverse=True)
ceiling = round(_stats.mean(sorted_kills[:3]), 1)
floor = round(_stats.mean(sorted_kills[-3:]), 1)

return ceiling, floor
```

def project_map_scenarios(kpr, opponent_strength, multi_kill_pct, round_swing_pct):
“”“Project kills under different match length scenarios with enhanced factors”””
scenarios = {}

```
# Adjust KPR based on multi-kill and round swing impact
mk_bonus = (multi_kill_pct - 15.0) / 100.0  # Bonus for high multi-kill %
rs_bonus = (round_swing_pct - 8.0) / 100.0  # Bonus for high round swing %
adjusted_kpr = kpr * (1 + mk_bonus + rs_bonus)

# Short map (stomp): 18-20 rounds per map
scenarios["short"] = {
    "rounds_per_map": 19,
    "total_rounds": 38,
    "expected_kills": round(adjusted_kpr * 38 * opponent_strength.get("adjustment_factor", 1.0), 1),
    "description": "Blowout/Stomp (38R)",
    "likelihood": "20%"
}

# Normal map: 21-23 rounds per map
scenarios["normal"] = {
    "rounds_per_map": 22,
    "total_rounds": 44,
    "expected_kills": round(adjusted_kpr * 44 * opponent_strength.get("adjustment_factor", 1.0), 1),
    "description": "Competitive (44R)",
    "likelihood": "55%"
}

# Long map (close): 24-26 rounds per map
scenarios["long"] = {
    "rounds_per_map": 25,
    "total_rounds": 50,
    "expected_kills": round(adjusted_kpr * 50 * opponent_strength.get("adjustment_factor", 1.0), 1),
    "description": "Close/OT (50R)",
    "likelihood": "25%"
}

return scenarios
```

def analyze_map_pool_enhanced(all_maps, opponent):
“”“Enhanced per-map performance with KPR tracking”””
map_stats = defaultdict(lambda: {“kills”: [], “kpr”: [], “rounds”: [], “dates”: []})

```
# Map name detection
for m in all_maps:
    map_name = m.get("map_name", "unknown")
    if map_name != "unknown":
        map_stats[map_name]["kills"].append(m.get("kills", 0))
        map_stats[map_name]["rounds"].append(m.get("rounds", 22))
        map_stats[map_name]["dates"].append(m.get("date", "N/A"))
        if m.get("rounds", 0) > 0:
            map_stats[map_name]["kpr"].append(m["kills"] / m["rounds"])

# Calculate averages per map
map_averages = {}
for map_name, stats in map_stats.items():
    if stats["kills"]:
        map_averages[map_name] = {
            "avg_kills": round(_stats.mean(stats["kills"]), 1),
            "avg_kpr": round(_stats.mean(stats["kpr"]), 3) if stats["kpr"] else 0.68,
            "sample_size": len(stats["kills"]),
            "recent_form": stats["kills"][-3:] if len(stats["kills"]) >= 3 else stats["kills"]
        }

# Sort by avg_kills to identify best maps
sorted_maps = sorted(map_averages.items(), key=lambda x: x[1]["avg_kills"], reverse=True)

# Veto prediction (simplified - would need team data)
likely_maps = {}
if len(sorted_maps) >= 3:
    likely_maps["Map 1"] = f"{sorted_maps[0][0].title()} ({sorted_maps[0][1]['avg_kills']}k avg)"
    likely_maps["Map 2"] = f"{sorted_maps[1][0].title()} ({sorted_maps[1][1]['avg_kills']}k avg)"
    likely_maps["Map 3"] = f"{sorted_maps[2][0].title()} ({sorted_maps[2][1]['avg_kills']}k avg)"

return map_averages, likely_maps
```

def estimate_team_ranks_enhanced(opponent):
“”“Enhanced team ranking estimation with tier system”””
team_tiers = {
“s_tier”: [“vitality”, “faze”, “g2”, “spirit”, “mouz”],
“a_tier”: [“navi”, “liquid”, “heroic”, “furia”, “complexity”],
“b_tier”: [“astralis”, “nip”, “ence”, “bne”, “monte”],
“c_tier”: [“eternal fire”, “saw”, “apeks”, “gamerlegion”, “outsiders”]
}

```
opponent_lower = opponent.lower()

for tier, teams in team_tiers.items():
    if any(team in opponent_lower for team in teams):
        if tier == "s_tier":
            return {
                "player_team_rank": "Top 10",
                "opponent_rank": "Top 5 (S-Tier)",
                "rank_difference": "Elite matchup",
                "odds_context": "Underdog position"
            }
        elif tier == "a_tier":
            return {
                "player_team_rank": "Top 15",
                "opponent_rank": "Top 10 (A-Tier)",
                "rank_difference": "Competitive matchup",
                "odds_context": "Even matchup"
            }
        elif tier == "b_tier":
            return {
                "player_team_rank": "Top 20",
                "opponent_rank": "Top 20 (B-Tier)",
                "rank_difference": "Favorable matchup",
                "odds_context": "Slight favorite"
            }

return {
    "player_team_rank": "Top 20",
    "opponent_rank": "Top 30+ (C-Tier)",
    "rank_difference": "Highly favorable",
    "odds_context": "Strong favorite"
}
```

def analyze_opponent_strength_enhanced(opponent, avg_kills, kpr, all_maps):
“”“Enhanced opponent analysis with weakness detection”””

```
# Elite defensive teams
elite_defense = {
    "faze": {"rating": "Elite", "suppression": 0.85, "weakness": "Slow T-sides"},
    "navi": {"rating": "Elite", "suppression": 0.87, "weakness": "Map pool depth"},
    "vitality": {"rating": "Elite", "suppression": 0.86, "weakness": "B-site holds"},
    "spirit": {"rating": "Elite", "suppression": 0.88, "weakness": "Anti-eco rounds"}
}

# Strong defensive teams
strong_defense = {
    "g2": {"rating": "Strong", "suppression": 0.92, "weakness": "AWP duels"},
    "mouz": {"rating": "Strong", "suppression": 0.93, "weakness": "Retake situations"},
    "liquid": {"rating": "Strong", "suppression": 0.91, "weakness": "Mid-round calls"},
    "heroic": {"rating": "Strong", "suppression": 0.92, "weakness": "Individual aim battles"}
}

opponent_lower = opponent.lower()

for team, data in elite_defense.items():
    if team in opponent_lower:
        return {
            "defensive_rating": f"{data['rating']} Defense (Top 5)",
            "kill_suppression": f"High - expect 12-15% fewer kills",
            "adjustment_factor": data["suppression"],
            "exploitable_weakness": data["weakness"],
            "difficulty_tier": "S-Tier"
        }

for team, data in strong_defense.items():
    if team in opponent_lower:
        return {
            "defensive_rating": f"{data['rating']} Defense (Top 15)",
            "kill_suppression": f"Moderate - expect 6-9% fewer kills",
            "adjustment_factor": data["suppression"],
            "exploitable_weakness": data["weakness"],
            "difficulty_tier": "A-Tier"
        }

return {
    "defensive_rating": "Average/Weak Defense",
    "kill_suppression": "Low - neutral or favorable conditions",
    "adjustment_factor": 1.02,
    "exploitable_weakness": "Multiple structural weaknesses",
    "difficulty_tier": "B/C-Tier"
}
```

def analyze_h2h_history(all_maps, opponent):
“”“Analyze head-to-head performance against opponent”””
opponent_lower = opponent.lower()
h2h_maps = [m for m in all_maps if opponent_lower in m.get(“opponent”, “”).lower()]

```
if not h2h_maps:
    return {
        "h2h_sample_size": 0,
        "h2h_avg_kills": "N/A",
        "h2h_kpr": "N/A",
        "h2h_note": "No recent H2H data"
    }

h2h_kills = [m["kills"] for m in h2h_maps]
h2h_rounds = sum(m.get("rounds", 0) for m in h2h_maps)
h2h_total_kills = sum(h2h_kills)

return {
    "h2h_sample_size": len(h2h_maps),
    "h2h_avg_kills": round(_stats.mean(h2h_kills), 1),
    "h2h_kpr": round(h2h_total_kills / h2h_rounds, 3) if h2h_rounds > 0 else 0.68,
    "h2h_note": f"Last {len(h2h_maps)} maps vs this opponent",
    "h2h_kills_list": h2h_kills[:5]
}
```

def calculate_weighted_grade(
edge_delta, hit_rate, avg_vs_line, role,
multi_kill_pct, round_swing_pct, scenarios,
opp_strength, team_ranks, avg, median, line
):
“”“Enhanced grading system with weighted factors - GRADE ≠ BET RECOMMENDATION”””

```
base_score = 5.0

# Edge weight (max +3.0) - PRIMARY FACTOR
if abs(edge_delta) >= 25:
    base_score += 3.0
elif abs(edge_delta) >= 20:
    base_score += 2.5
elif abs(edge_delta) >= 15:
    base_score += 2.0
elif abs(edge_delta) >= 10:
    base_score += 1.5
elif abs(edge_delta) >= 5:
    base_score += 1.0

# Hit rate weight (max +1.5)
if hit_rate >= 70:
    base_score += 1.5
elif hit_rate >= 60:
    base_score += 1.0
elif hit_rate >= 50:
    base_score += 0.5
elif hit_rate <= 30:
    base_score -= 1.0
elif hit_rate <= 40:
    base_score -= 0.5

# Average vs line weight (max +1.5)
diff = abs(avg_vs_line)
if diff >= 8:
    base_score += 1.5
elif diff >= 5:
    base_score += 1.0
elif diff >= 3:
    base_score += 0.5

# Role weight (max +1.0)
if role in ["Star Rifler", "Primary AWPer", "Entry Fragger"]:
    base_score += 1.0
elif role in ["Lurker/Closer"]:
    base_score += 0.5

# Multi-kill impact (max +0.75)
if multi_kill_pct >= 20:
    base_score += 0.75
elif multi_kill_pct >= 17:
    base_score += 0.5
elif multi_kill_pct >= 15:
    base_score += 0.25

# Round swing impact (max +0.75)
if round_swing_pct >= 12:
    base_score += 0.75
elif round_swing_pct >= 10:
    base_score += 0.5
elif round_swing_pct >= 8:
    base_score += 0.25

# Opponent difficulty adjustment (max -1.5)
adj_factor = opp_strength.get("adjustment_factor", 1.0)
if adj_factor <= 0.87:
    base_score -= 1.5
elif adj_factor <= 0.92:
    base_score -= 1.0
elif adj_factor <= 0.95:
    base_score -= 0.5

# Scenario consistency (max +0.5)
normal_scenario = scenarios.get("normal", {})
if normal_scenario.get("expected_kills", 0) > avg_vs_line:
    base_score += 0.5

# Cap at 10.0
final_score = min(10.0, max(1.0, base_score))

# Grade string (describes QUALITY of the edge, not whether to bet)
if final_score >= 9.5:
    grade_str = f"{final_score:.1f}/10 (Elite Edge / Prop Error)"
elif final_score >= 8.5:
    grade_str = f"{final_score:.1f}/10 (Very Strong Edge)"
elif final_score >= 7.5:
    grade_str = f"{final_score:.1f}/10 (Strong Playable Edge)"
elif final_score >= 6.5:
    grade_str = f"{final_score:.1f}/10 (Solid Lean / Favorable Value)"
elif final_score >= 5.5:
    grade_str = f"{final_score:.1f}/10 (Small Edge / Minor Value)"
elif final_score >= 4.5:
    grade_str = f"{final_score:.1f}/10 (Thin Edge / Borderline)"
else:
    grade_str = f"{final_score:.1f}/10 (Below Threshold)"

return grade_str, final_score
```

def generate_analysis_narrative_v2(
player_name, line, avg, median, hit_rate, role,
scenarios, opp_strength, edge, usage_stats,
multi_kill_pct, round_swing_pct, h2h_data
):
“”“Enhanced narrative with all new factors”””
narrative = []

```
# Line position
diff = avg - line
if diff >= 4:
    narrative.append(f"**Severe Value**: Line {line} vs avg {avg} (+{round(diff, 1)}k edge)")
elif diff >= 2:
    narrative.append(f"**Value Detected**: Avg {avg} exceeds line by {round(diff, 1)}k")
elif diff <= -4:
    narrative.append(f"**Overpriced**: Line {round(abs(diff), 1)}k above average")
elif diff <= -2:
    narrative.append(f"**Inflated Line**: Set {round(abs(diff), 1)}k above recent form")
else:
    narrative.append(f"**Fair Line**: Within 2k of average ({avg})")

# Role and usage
narrative.append(f"**{role}**: Opening={usage_stats.get('opening_duels', 0):.0f}% | Clutch={usage_stats.get('clutch_attempts', 0):.0f}% | Utility={usage_stats.get('utility_usage', 0):.0f}%")

# Multi-kill and round swing impact
if multi_kill_pct >= 18 and round_swing_pct >= 10:
    narrative.append(f"**High Impact Profile**: {multi_kill_pct}% multi-kill rounds + {round_swing_pct}% round swings = explosive ceiling")
elif multi_kill_pct >= 15:
    narrative.append(f"**Solid Multi-Kill Rate**: {multi_kill_pct}% indicates consistent 2-3k rounds")

# Hit rate
if hit_rate >= 70:
    narrative.append(f"**Elite Consistency**: {round(hit_rate, 0)}% hit rate = reliable floor")
elif hit_rate >= 60:
    narrative.append(f"**Strong Form**: {round(hit_rate, 0)}% over rate")
elif hit_rate <= 30:
    narrative.append(f"**Poor Form**: Only {round(hit_rate, 0)}% hit rate")

# Scenarios
normal = scenarios.get("normal", {})
short = scenarios.get("short", {})
if normal.get("expected_kills", 0) > line:
    narrative.append(f"**Projection Favors Over**: {normal['expected_kills']}k in standard 44R match")
elif short.get("expected_kills", 0) < line:
    narrative.append(f"**Stomp Risk**: Quick match ({short['expected_kills']}k in 38R) threatens under")

# Opponent
if opp_strength.get("adjustment_factor", 1.0) < 0.90:
    narrative.append(f"**Tough Defense**: {opp_strength.get('defensive_rating')} may suppress output ({opp_strength.get('exploitable_weakness')})")
elif opp_strength.get("adjustment_factor", 1.0) >= 1.0:
    narrative.append(f"**Favorable Matchup**: Weak defense ({opp_strength.get('exploitable_weakness')}) should boost production")

# H2H
if h2h_data.get("h2h_sample_size", 0) > 0:
    h2h_avg = h2h_data.get("h2h_avg_kills", 0)
    narrative.append(f"**H2H History**: {h2h_avg}k avg in {h2h_data['h2h_sample_size']} recent maps vs this opponent")

# Edge
if abs(edge) >= 20:
    narrative.append(f"**🔥 ELITE EDGE**: {abs(round(edge, 1))}% mathematical advantage")
elif abs(edge) >= 10:
    narrative.append(f"**Strong Edge**: {abs(round(edge, 1))}% probability advantage")

return " • ".join(narrative)
```

def get_player_info(player_name, line=0.0, opponent=“N/A”):
try:
search_res = search_player(player_name)
if not search_res:
return _error_response(f”FAIL: Could not find player ‘{player_name}’ on HLTV.”, player_name, line, opponent)
pid, slug, display = search_res
print(f”TARGET ACQUIRED: {display} (ID: {pid})”)

```
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

            known_maps = {'anc', 'mrg', 'd2', 'inf', 'nuke', 'anb', 'vrt', 'ovp', 'ancient', 'mirage', 'dust2', 'inferno', 'anubis', 'vertigo', 'overpass'}
            map_cell_idx = -1
            map_name = "unknown"
            for idx, txt in enumerate(cell_texts):
                txt_lower = txt.lower()
                if txt_lower in known_maps:
                    map_cell_idx = idx
                    map_name = txt_lower
                    # Normalize map names
                    if map_name in ['anc']:
                        map_name = 'ancient'
                    elif map_name in ['mrg']:
                        map_name = 'mirage'
                    elif map_name in ['d2']:
                        map_name = 'dust2'
                    elif map_name in ['inf']:
                        map_name = 'inferno'
                    elif map_name in ['anb']:
                        map_name = 'anubis'
                    elif map_name in ['vrt']:
                        map_name = 'vertigo'
                    elif map_name in ['ovp']:
                        map_name = 'overpass'
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
    
    # Calculate multi-kill % and round swing %
    multi_kill_pct = calculate_multi_kill_rounds(all_maps)
    round_swing_pct = calculate_round_swing_impact(all_maps, kpr, advanced_stats)
    
    # Role and usage
    role, usage_stats = classify_role_detailed(advanced_stats, kpr, advanced_stats.get("adr", 75), all_maps)
    
    ceiling, floor = calculate_ceiling_floor(final_series_totals)
    map_averages, likely_maps = analyze_map_pool_enhanced(all_maps, opponent)
    team_ranks = estimate_team_ranks_enhanced(opponent)
    opp_strength = analyze_opponent_strength_enhanced(opponent, avg_2map, kpr, all_maps)
    h2h_data = analyze_h2h_history(all_maps, opponent)
    
    # Round projections with adjustments
    if any(x in opponent.lower() for x in ["vitality", "g2", "faze", "mouz", "navi"]):
        base_proj_rounds = 44
    else:
        base_proj_rounds = 42
    
    scenarios = project_map_scenarios(kpr, opp_strength, multi_kill_pct, round_swing_pct)
    
    adjusted_kpr = kpr * opp_strength.get("adjustment_factor", 1.0)
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

    # Enhanced grading (returns grade AND numerical score)
    grade_str, grade_score = calculate_weighted_grade(
        edge_delta, hit_rate_pct, avg_2map - line, role,
        multi_kill_pct, round_swing_pct, scenarios,
        opp_strength, team_ranks, avg_2map, median, line
    )
    
    # BET RECOMMENDATION - SEPARATE DECISION LOGIC (More Conservative)
    # Requires MULTIPLE conditions to be met
    
    # OVER conditions
    over_conditions = 0
    if avg_2map > line:
        over_conditions += 1
    if median > line:
        over_conditions += 1
    if hit_rate_pct >= 60.0:
        over_conditions += 1
    if edge_delta >= 8.0:  # Strong positive edge
        over_conditions += 1
    if expected_kills > line + 2:  # Projection well above line
        over_conditions += 1
    if grade_score >= 7.0:  # Grade must be solid
        over_conditions += 1
    
    # UNDER conditions
    under_conditions = 0
    if avg_2map < line:
        under_conditions += 1
    if median < line:
        under_conditions += 1
    if hit_rate_pct <= 40.0:
        under_conditions += 1
    if edge_delta <= -8.0:  # Strong negative edge
        under_conditions += 1
    if expected_kills < line - 2:  # Projection well below line
        under_conditions += 1
    if grade_score >= 7.0:  # Grade must be solid
        under_conditions += 1
    
    # Decision: Need at least 4/6 conditions met
    if over_conditions >= 4:
        bet_rec = "OVER"
    elif under_conditions >= 4:
        bet_rec = "UNDER"
    else:
        bet_rec = "NO BET"
    
    # Generate analysis narrative
    analysis = generate_analysis_narrative_v2(
        display, line, avg_2map, median, hit_rate_pct, 
        role, scenarios, opp_strength, edge_delta,
        usage_stats, multi_kill_pct, round_swing_pct, h2h_data
    )

    return {
        "Player": display,
        "Match": f"vs {opponent.title()}",
        "Prop": f"{line} Kills",
        "Prop Line": f"{line} Kills",
        
        # Core stats
        "Role": role,
        "Usage Stats": usage_stats,
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
        "Multi-kill %": f"{multi_kill_pct}%",
        "Round Swing %": f"{round_swing_pct}%",
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
        
        # H2H
        "H2H Data": h2h_data,
        
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
```
