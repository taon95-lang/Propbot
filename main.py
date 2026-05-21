import os
import discord
import asyncio
from discord.ext import commands
import statistics as _stats
import numpy as np

# Import the enhanced scraper

from scraper import get_player_info

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=”!”, intents=intents)

@bot.event
async def on_ready():
print(f”✅ GOD-TIER PROP BOT ONLINE: {bot.user}”, flush=True)

@bot.command()
async def scan(ctx, player=None, line=None, opponent=“N/A”):
“”“Scan KILLS props for Maps 1-2 with comprehensive analytics”””
if not player or not line:
return await ctx.send(“❌ **Usage:** `!scan player line opponent`\nExample: `!scan djoko 27.5 tdk`”)

```
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

        # Safe variable extraction
        p_name = str(data.get('Player', 'Unknown'))
        p_prop_line = str(data.get('Prop Line', data.get('Prop', f"{line} Kills")))
        p_grade = str(data.get('Final grade', 'N/A'))
        p_mispriced = str(data.get('Mispriced or not', 'N/A'))
        
        p_avg = str(data.get('Recent average', 'N/A'))
        p_median = str(data.get('Recent median', 'N/A'))
        p_hitrate = str(data.get('Hit rate', 'N/A'))
        p_rounds = str(data.get('Projected rounds', 'N/A'))
        p_role = str(data.get('Role', 'N/A'))
        
        s_mean = str(data.get('Simulated mean', 'N/A'))
        s_std = str(data.get('Standard deviation', 'N/A'))
        s_over = str(data.get('Over probability', 'N/A'))
        s_under = str(data.get('Under probability', 'N/A'))
        s_edge = str(data.get('Edge vs line', 'N/A'))
        s_expected = str(data.get('Expected kills', 'N/A'))
        
        p_floor = str(data.get('Floor (Bottom 3 avg)', 'N/A'))
        p_ceil = str(data.get('Ceiling (Top 3 avg)', 'N/A'))
        
        p_kpr = str(data.get('KPR', 'N/A'))
        p_adr = str(data.get('ADR', 'N/A'))
        p_hs = str(data.get('HS %', 'N/A'))
        p_rating = str(data.get('Rating 3.0', 'N/A'))
        p_kast = str(data.get('KAST', 'N/A'))
        p_impact = str(data.get('Impact', 'N/A'))
        
        # New enhanced metrics
        p_multi_kill = str(data.get('Multi-kill %', 'N/A'))
        p_round_swing = str(data.get('Round Swing %', 'N/A'))
        
        usage_stats = data.get('Usage Stats', {})
        p_opening = f"{usage_stats.get('opening_duels', 0):.0f}%"
        p_clutch = f"{usage_stats.get('clutch_attempts', 0):.0f}%"
        p_utility = f"{usage_stats.get('utility_usage', 0):.0f}%"
        p_sniping = f"{usage_stats.get('sniping_frequency', 0):.0f}%"
        p_trading = f"{usage_stats.get('trade_opportunities', 0):.0f}%"
        
        team_ranks = data.get('Team rankings', {})
        p_team_rank = str(team_ranks.get('player_team_rank', 'N/A'))
        p_opp_rank = str(team_ranks.get('opponent_rank', 'N/A'))
        p_odds_context = str(team_ranks.get('odds_context', 'N/A'))
        
        opp_str = data.get('Opponent strength', {})
        p_opp_defense = str(opp_str.get('defensive_rating', 'N/A'))
        p_opp_adjust = f"{opp_str.get('adjustment_factor', 1.0):.2f}x"
        p_opp_weakness = str(opp_str.get('exploitable_weakness', 'N/A'))
        p_opp_tier = str(opp_str.get('difficulty_tier', 'N/A'))
        
        h2h_data = data.get('H2H Data', {})
        p_h2h_size = h2h_data.get('h2h_sample_size', 0)
        p_h2h_avg = str(h2h_data.get('h2h_avg_kills', 'N/A'))
        p_h2h_kpr = str(h2h_data.get('h2h_kpr', 'N/A'))

        # --- BUILD ENHANCED MARKDOWN DESCRIPTION ---
        desc_lines = [
            f"**PLAYER:** {p_name} vs. {opponent.upper()}",
            f"**MATCH:** Maps 1–2 Kills | **PROP LINE:** {p_prop_line}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"**GRADE:** {p_grade}",
            f"**PROJECTION:** ⏸️ **{rec}** ({p_mispriced})",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "### 📊 CORE METRICS",
            f"• **Recent Avg (Last 10 BO3):** {p_avg} kills",
            f"• **Recent Median:** {p_median} kills",
            f"• **Hit Rate:** {p_hitrate}",
            f"• **Projected Rounds:** {p_rounds}R",
            f"• **Role:** {p_role}",
            "",
            "### 🎯 PLAYER PROFILE & USAGE",
            f"• **Rating 3.0:** {p_rating} | **KAST:** {p_kast} | **Impact:** {p_impact}",
            f"• **KPR:** {p_kpr} | **ADR:** {p_adr} | **HS%:** {p_hs}%",
            f"• **Multi-Kill Rounds:** {p_multi_kill}",
            f"• **Round Swing Impact:** {p_round_swing}",
            "",
            "### 🎮 ROLE USAGE BREAKDOWN",
            f"• **Opening Duels:** {p_opening}",
            f"• **Clutch Situations:** {p_clutch}",
            f"• **Utility Usage:** {p_utility}",
            f"• **Sniping Frequency:** {p_sniping}",
            f"• **Trade Opportunities:** {p_trading}",
            "",
            "### 📈 PROJECTION MODEL (100K Monte Carlo)",
            f"• **Simulated Mean:** {s_mean}k | **σ:** {s_std}",
            f"• **Expected Kills:** {s_expected}k",
            f"• **Over Probability:** {s_over}",
            f"• **Under Probability:** {s_under}",
            f"• **Edge vs. Line:** {s_edge}",
            f"• **Ceiling/Floor:** {p_ceil}k / {p_floor}k",
            ""
        ]

        # Match length scenarios
        scenarios = data.get('Scenarios', {})
        if scenarios:
            desc_lines.append("### ⏱️ MATCH LENGTH SCENARIOS")
            short = scenarios.get('short', {})
            normal = scenarios.get('normal', {})
            long_s = scenarios.get('long', {})
            
            desc_lines.append(f"• **Stomp ({short.get('total_rounds', 38)}R):** {short.get('expected_kills', 0)}k - {short.get('likelihood', '20%')} chance")
            desc_lines.append(f"• **Normal ({normal.get('total_rounds', 44)}R):** {normal.get('expected_kills', 0)}k - {normal.get('likelihood', '55%')} chance")
            desc_lines.append(f"• **Close/OT ({long_s.get('total_rounds', 50)}R):** {long_s.get('expected_kills', 0)}k - {long_s.get('likelihood', '25%')} chance")
            desc_lines.append("")

        # Map pool intelligence
        map_avgs = data.get('Per-map averages', {})
        if map_avgs and len(map_avgs) > 0:
            desc_lines.append("### 🗺️ MAP POOL INTELLIGENCE")
            sorted_maps = sorted(map_avgs.items(), key=lambda x: x[1]['avg_kills'], reverse=True)
            for m, stats in sorted_maps[:5]:
                desc_lines.append(f"• **{m.title()}:** {stats['avg_kills']}k avg | {stats['avg_kpr']} KPR | ({stats['sample_size']} maps)")
            desc_lines.append("")
            
            # Likely map picks
            likely_maps = data.get('Likely maps', {})
            if likely_maps:
                desc_lines.append("**🎲 Projected Map Picks:**")
                for map_num, map_info in likely_maps.items():
                    desc_lines.append(f"• {map_num}: {map_info}")
                desc_lines.append("")

        # Team rankings and opponent analysis
        desc_lines.append("### 🏆 TEAM CONTEXT & MATCHUP")
        desc_lines.append(f"• **Player Team:** {p_team_rank}")
        desc_lines.append(f"• **Opponent:** {p_opp_rank} ({p_opp_tier})")
        desc_lines.append(f"• **Matchup Odds:** {p_odds_context}")
        desc_lines.append(f"• **Opponent Defense:** {p_opp_defense}")
        desc_lines.append(f"• **Kill Adjustment:** {p_opp_adjust}")
        desc_lines.append(f"• **Exploitable Weakness:** {p_opp_weakness}")
        desc_lines.append("")

        # H2H history
        if p_h2h_size > 0:
            desc_lines.append("### 🔄 HEAD-TO-HEAD HISTORY")
            desc_lines.append(f"• **H2H Sample:** {p_h2h_size} recent maps vs {opponent.upper()}")
            desc_lines.append(f"• **H2H Avg Kills:** {p_h2h_avg}")
            desc_lines.append(f"• **H2H KPR:** {p_h2h_kpr}")
            h2h_kills = h2h_data.get('h2h_kills_list', [])
            if h2h_kills:
                desc_lines.append(f"• **Recent H2H:** {', '.join(str(k) for k in h2h_kills)}")
            desc_lines.append("")

        # Series breakdown
        totals = data.get('Recent Totals (M1+M2 Combined)', [])
        if totals:
            desc_lines.append("### 📋 SERIES BREAKDOWN (Over/Under)")
            over_under_history = ""
            for idx, val in enumerate(totals, 1):
                status_emoji = "✅" if float(val) > line_float else "❌"
                over_under_history += f"S{idx}: **{val}** {status_emoji}  "
            desc_lines.append(over_under_history)
            desc_lines.append("")

        # Analysis narrative
        if 'Analysis' in data:
            desc_lines.append("### 🔍 EXPERT ANALYSIS")
            desc_lines.append(str(data['Analysis']))

        # Build embed
        embed = discord.Embed(
            title="🎯 ULTIMATE KILLS ANALYSIS", 
            description="\n".join(desc_lines), 
            color=color
        )
        embed.set_footer(text="God-Tier Engine v2.0 • 100K Monte Carlo • Enhanced Analytics • Last 10 BO3")

        await msg.edit(content=None, embed=embed)

    except ValueError:
        await msg.edit(content="❌ Invalid line. Use decimal (e.g., 27.5)")
    except Exception as e:
        print(f"SCAN ERROR: {e}")
        await msg.edit(content=f"❌ Scan crashed: {e}")
```

@bot.command()
async def hs(ctx, player=None, line=None, opponent=“N/A”):
“”“Scan HEADSHOT props for Maps 1-2”””
if not player or not line:
return await ctx.send(“❌ **Usage:** `!hs player hs_line opponent`\nExample: `!hs flouzer 16.5 nemiga`”)

```
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

        # Safe string conversions
        p_name = str(data.get('Player', player.title()))
        p_role = str(data.get('Role', 'N/A'))
        p_rating = str(data.get('Rating 3.0', 'N/A'))
        p_kpr = str(data.get('KPR', 'N/A'))
        p_adr = str(data.get('ADR', 'N/A'))

        # --- BUILD ENHANCED HEADSHOT ANALYSIS ---
        hs_lines = [
            f"**PLAYER:** {p_name} vs. {opponent.upper()}",
            f"**MATCH:** Maps 1–2 Headshots | **PROP LINE:** {line} HS",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"**PROJECTION:** 🎯 **{bet_rec}**",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "### 👤 PLAYER PROFILE",
            f"• **Role:** {p_role}",
            f"• **Rating 3.0:** {p_rating}",
            f"• **KPR:** {p_kpr} | **ADR:** {p_adr}",
            "",
            "### 🎯 HEADSHOT PERFORMANCE",
            f"• **Recent Avg HS (M1+M2):** {hs_avg}",
            f"• **Median HS:** {hs_median}",
            f"• **Base HS Rate:** {hs_rate}%",
            f"• **Hit Rate:** {hits}/{len(hs_totals)} ({round(hit_rate, 1)}%)",
            "",
            "### 🤖 SIMULATION PROBABILITIES",
            f"• **Over Probability:** {round(over_prob, 1)}%",
            f"• **Under Probability:** {round(under_prob, 1)}%",
            f"• **Calculated Edge:** {round(edge, 1)}%",
            "",
            "### 📋 SERIES BREAKDOWN (Over/Under)"
        ]

        over_under_str = ""
        for i, hs_val in enumerate(hs_totals, 1):
            status = "✅" if hs_val > line_float else "❌"
            over_under_str += f"S{i}: **{hs_val}** {status}  "
        hs_lines.append(over_under_str)
        hs_lines.append("")

        if individual_hs:
            hs_lines.append("### 🗺️ MAP-BY-MAP HS BREAKDOWN")
            ind_str = ', '.join(str(x) for x in individual_hs[:20])
            hs_lines.append(f"`{ind_str}`")
            hs_lines.append("")

        hs_lines.append(f"**Line Assessment:** Prop set at {line} HS → player must exceed {line} to clear.")
        
        # Grade the HS bet
        if abs(edge) >= 15:
            hs_grade = "🔥 Elite Edge"
        elif abs(edge) >= 10:
            hs_grade = "⭐ Strong Value"
        elif abs(edge) >= 5:
            hs_grade = "✅ Solid Play"
        else:
            hs_grade = "⚖️ Borderline"
        
        hs_lines.append(f"**HS Bet Grade:** {hs_grade}")

        embed = discord.Embed(
            title="🎯 ULTIMATE HEADSHOT ANALYSIS", 
            description="\n".join(hs_lines), 
            color=color
        )
        embed.set_footer(text="God-Tier Headshot Analyzer v2.0 • Last 10 BO3 Maps 1-2")

        await msg.edit(content=None, embed=embed)

    except ValueError:
        await msg.edit(content="❌ Invalid line. Use decimal (e.g., 16.5)")
    except Exception as e:
        print(f"HS SCAN ERROR: {e}")
        await msg.edit(content=f"❌ HS scan crashed: {e}")
```

if **name** == “**main**”:
token = os.getenv(“DISCORD_TOKEN”)
if token:
bot.run(token)
else:
print(“❌ Error: DISCORD_TOKEN environmental variable not found.”)
