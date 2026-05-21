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
        "Prop": f"{line} Kills",
        "Role": "Unknown",
        "Recent sample used": "N/A",
        "Recent average": 0,
        "Recent median": 0,
        "Hit rate": "0%",
        "Projected rounds": 0,
        "Expected kills": 0,
        "Simulated mean": 0,
        "Standard deviation": 0,
        "Over probability": "0%",
        "Under probability": "0%",
        "Edge vs line": "0%",
        "Mispriced or not": "NO",
        "Final grade": "Below 5/10 (No Bet)",
        "Bet recommendation": "NO BET",
        "error": msg
    }

def extract_advanced_stats(soup, pid):
    advanced = {
        "rating_3": 1.0, "kast": 70.0, "impact": 1.0, "adr": 75.0,
        "kpr": 0.68, "dpr": 0.65, "multi_kill_pct": 15.0, "round_swing_pct": 8.0
    }
    try:
        stats_divs = soup.find_all("div", {"class": "stats-row"})
        for div in stats_divs:
            text = div.get_text().lower()
            if "rating" in text and "3.0" in text:
                rating_match = re.search(r'(\d+\.\d+)', text)
                if rating_match: advanced["rating_3"] = float(rating_match.group(1))
            elif "k/d" in text or "kpr" in text:
                kpr_match = re.search(r'(\d+\.\d+)', text)
                if kpr_match: advanced["kpr"] = float(kpr_match.group(1))
            elif "kast" in text:
                kast_match = re.search(r'(\d+\.?\d*)%?', text)
                if kast_match: advanced["kast"] = float(kast_match.group(1))
            elif "impact" in text:
                impact_match = re.search(r'(\d+\.\d+)', text)
                if impact_match: advanced["impact"] = float(impact_match.group(1))
            elif "adr" in text:
                adr_match = re.search(r'(\d+\.?\d*)', text)
                if adr_match: advanced["adr"] = float(adr_match.group(1))
    except Exception as e:
        print(f"Advanced stats extraction warning: {e}")
    return advanced

def classify_role(advanced_stats, kpr, adr):
    rating = advanced_stats.get("rating_3", 1.0)
    if kpr >= 0.78 and adr >= 85 and rating >= 1.15: return "Star Rifler"
    elif adr >= 90 and rating >= 1.10: return "AWPer"
    elif kpr >= 0.75 and adr >= 80: return "Entry Fragger"
    elif 0.65 <= kpr <= 0.72 and 70 <= adr <= 78: return "Lurker"
    else: return "Support"

def get_player_info(player_name, line=0.0, opponent="N/A"):
    try:
        search_res = search_player(player_name)
        if not search_res: 
            return _error_response(f"FAIL: Could not find player '{player_name}' on HLTV.", player_name, line, opponent)
        pid, slug, display = search_res
        
        stats_url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"
        html, _ = _fetch(stats_url, render=True)
        if not html: 
            return _error_response("FAIL: Stats page blocked or ScraperAPI failed.", display, line, opponent)

        soup = BeautifulSoup(html, "html.parser")
        advanced_stats = extract_advanced_stats(soup, pid)
        
        table = soup.find("table", {"class": "stats-table"})
        if not table: return _error_response("FAIL: Stats table layout changed.", display, line, opponent)
        
        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")

        all_maps = []
        for i, row in enumerate(rows):
            cols = row.find_all("td")
            if len(cols) < 4: continue
            try:
                cell_texts = [c.text.strip() for c in cols]
                kd_idx = -1
                for col_idx, col in enumerate(cols):
                    col_text = col.text.strip()
                    kd_match = re.search(r'(\d+)\s*-\s*(\d+)', col_text)
                    if kd_match:
                        k_check, d_check = int(kd_match.group(1)), int(kd_match.group(2))
                        if 1 <= k_check <= 50 and 1 <= d_check <= 50:
                            kd_idx = col_idx
                            break

                m_rounds = 22
                parentheses_nums = []
                for txt in cell_texts:
                    p_matches = re.findall(r'\((\d+)\)', txt)
                    for pm in p_matches: parentheses_nums.append(int(pm))
                
                if len(parentheses_nums) >= 2:
                    m_rounds = parentheses_nums[0] + parentheses_nums[1]

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
                        
                opp = cell_texts[map_cell_idx - 1].lower() if map_cell_idx > 0 else (cell_texts[2].lower() if len(cell_texts) > 2 else "unknown")
                opp = re.sub(r'\(.*\)', '', opp).strip()
                opp = re.sub(r'\s+\d+\s*$', '', opp).strip()
                
                for col_idx, col in enumerate(cols):
                    col_text = col.text.strip()
                    kd_match = re.search(r'(\d+)\s*-\s*(\d+)', col_text)
                    if kd_match:
                        kills, deaths = int(kd_match.group(1)), int(kd_match.group(2))
                        headshots = int(re.search(r'\((\d+)\)', col_text).group(1)) if re.search(r'\((\d+)\)', col_text) else int(kills * 0.40)
                        
                        all_maps.append({
                            "date": date, "opponent": opp, "map_name": map_name,
                            "kills": kills, "deaths": deaths, "headshots": headshots, "rounds": m_rounds
                        })
                        break
            except: continue

        if len(all_maps) < 2: return _error_response("FAIL: Insufficient match records.", display, line, opponent)

        series_groups = []
        current_group = [all_maps[0]]
        for m_data in all_maps[1:]:
            if m_data['opponent'] == current_group[0]['opponent'] and m_data['date'] == current_group[0]['date']:
                current_group.append(m_data)
            else:
                series_groups.append(current_group)
                current_group = [m_data]
        if current_group: series_groups.append(current_group)

        final_series_totals, final_series_hs_totals = [], []
        total_k, total_r, total_hs = 0, 0, 0

        for group in series_groups:
            if len(final_series_totals) >= 10: break
            if len(group) >= 2:
                m1_k, m2_k = group[-1]["kills"], group[-2]["kills"]
                m1_hs, m2_hs = group[-1]["headshots"], group[-2]["headshots"]
                
                combined_k = m1_k + m2_k
                combined_r = group[-1]["rounds"] + group[-2]["rounds"]
                combined_hs = m1_hs + m2_hs
                
                final_series_totals.append(combined_k)
                final_series_hs_totals.append(combined_hs)
                total_k += combined_k
                total_r += combined_r
                total_hs += combined_hs

        if not final_series_totals: return _error_response("FAIL: No valid BO3 samples found.", display, line, opponent)

        # Base Math Calculations
        avg_2map = round(_stats.mean(final_series_totals), 1)
        median = float(_stats.median(final_series_totals))
        hits = sum(1 for x in final_series_totals if x > line)
        hit_rate_pct = (hits / len(final_series_totals)) * 100
        kpr = total_k / total_r if total_r > 0 else 0.68
        role = classify_role(advanced_stats, kpr, advanced_stats.get("adr", 75))

        # Round Projection Logical Rules
        if any(x in opponent.lower() for x in ["vitality", "g2", "faze", "mouz", "navi", "3dmax"]):
            base_proj_rounds = 44  # Competitive boost
        else:
            base_proj_rounds = 42

        expected_kills = round(kpr * base_proj_rounds, 1)

        # 100k Negative Binomial Monte Carlo Simulation
        var_2map = _stats.variance(final_series_totals) if len(final_series_totals) > 1 else avg_2map
        if var_2map <= expected_kills: var_2map = expected_kills * 1.25
        p_nb = max(0.01, min(0.99, expected_kills / var_2map))
        n_nb = max(1, int((expected_kills ** 2) / (var_2map - expected_kills)))
        
        sim = np.random.negative_binomial(n_nb, p_nb, 100000)
        over_prob = (np.sum(sim > line) / 100000) * 100
        under_prob = 100.0 - over_prob
        edge_delta = over_prob - 50.0

        # Strict Gold Standard Decision Mapping Matrix
        if avg_2map > (line + 3) and median > line and hit_rate_pct >= 60.0:
            bet_rec = "OVER"
        elif avg_2map < line and median < line and hit_rate_pct <= 40.0:
            bet_rec = "UNDER"
        else:
            bet_rec = "NO BET"

        # Check for Sportsbook Mispricing / Prop Error Structural Outliers
        if abs(avg_2map - line) >= 7.5 and hit_rate_pct in [0.0, 100.0]:
            mispriced = "PROP ERROR"
        elif abs(avg_2map - line) >= 4.0:
            mispriced = "MISPRICED PROP"
        else:
            mispriced = "NO"

        # Direct Line Grading Formula Integration
        if bet_rec == "NO BET":
            grade_str = "Below 5/10 (No Bet)"
        else:
            abs_edge = abs(edge_delta)
            if abs_edge >= 25.0: grade_str = "10/10 (Elite Edge / Strong Misprice)"
            elif abs_edge >= 20.0: grade_str = "9/10 (Very Strong Edge)"
            elif abs_edge >= 15.0: grade_str = "8/10 (Strong Playable Edge)"
            elif abs_edge >= 10.0: grade_str = "7/10 (Solid Lean / Good Value)"
            elif abs_edge >= 5.0: grade_str = "6/10 (Small Edge / Minor Value)"
            else: grade_str = "5/10 (Thin Edge / Borderline)"

        return {
            "Player": display,
            "Match": f"vs {opponent.upper()}",
            "Prop": f"{line} Kills",
            "Role": role,
            "Recent sample used": f"Last {len(final_series_totals)} BO3 Series (M1+M2)",
            "Recent average": avg_2map,
            "Recent median": median,
            "Hit rate": f"{round(hit_rate_pct, 1)}%",
            "Projected rounds": base_proj_rounds,
            "Expected kills": expected_kills,
            "Simulated mean": round(np.mean(sim), 2),
            "Standard deviation": round(np.std(sim), 2),
            "Over probability": f"{round(over_prob, 1)}%",
            "Under probability": f"{round(under_prob, 1)}%",
            "Edge vs line": f"{round(edge_delta, 1)}%",
            "Mispriced or not": mispriced,
            "Final grade": grade_str,
            "Bet recommendation": bet_rec,
            "Recent Totals Raw": final_series_totals
        }
    except Exception as e:
        return _error_response(f"SYSTEM CRASH: {str(e)}", player_name, line, opponent)

# ==========================================
# DISCORD BOT COMMAND RUNNERS
# ==========================================
@bot.event
async def on_ready():
    print(f"✅ ENGINE CONFIGURED: {bot.user}")

@bot.command()
async def scan(ctx, player=None, line=None, opponent="N/A"):
    if not player or not line:
        return await ctx.send("❌ **Usage:** `!scan player line opponent`")

    msg = await ctx.send(f"🔬 Running 100K Monte Carlo Engine for {player.upper()}...")

    async with ctx.typing():
        try:
            line_float = float(line)
            data = await asyncio.to_thread(get_player_info, player, line_float, opponent)

            if "error" in data:
                return await msg.edit(content=f"❌ {data['error']}")

            # Clean output block construction
            response_block = (
                f"**Player:** {data['Player']}\n"
                f"**Match:** {data['Match']}\n"
                f"**Prop:** {data['Prop']}\n"
                f"**Role:** {data['Role']}\n"
                f"**Recent sample used:** {data['Recent sample used']}\n"
                f"**Recent average:** {data['Recent average']}\n"
                f"**Recent median:** {data['Recent median']}\n"
                f"**Hit rate:** {data['Hit rate']}\n"
                f"**Projected rounds:** {data['Projected rounds']}\n"
                f"**Expected kills:** {data['Expected kills']}\n"
                f"**Simulated mean:** {data['Simulated mean']}\n"
                f"**Standard deviation:** {data['Standard deviation']}\n"
                f"**Over probability:** {data['Over probability']}\n"
                f"**Under probability:** {data['Under probability']}\n"
                f"**Edge vs line:** {data['Edge vs line']}\n"
                f"**Mispriced or not:** {data['Mispriced or not']}\n"
                f"**Final grade:** {data['Final grade']}\n"
                f"**Bet recommendation:** {data['Bet recommendation']}\n"
                f"**Recent Totals (M1+M2 Combined):** `{data['Recent Totals Raw']}`"
            )

            await msg.edit(content=response_block)

        except ValueError:
            await msg.edit(content="❌ Line must be decimal numeric layout (e.g. 27.5)")
        except Exception as e:
            await msg.edit(content=f"❌ Execution Crash: {str(e)}")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token: bot.run(token)
    else: print("❌ Missing DISCORD_TOKEN configuration variable.")
