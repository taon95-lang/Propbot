import os
import discord
import asyncio
from discord.ext import commands
import statistics as _stats
import numpy as np

# Import the real scraper
from scraper import get_player_info

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ GOD-TIER PROP BOT ONLINE: {bot.user}", flush=True)


@bot.command()
async def scan(ctx, player=None, line=None, opponent="N/A"):
    """Scan KILLS props for Maps 1-2"""
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

            # Safe variable extraction matching scraper.py dict keys exactly
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
            p_hs = str(data.get('HS %', 'N/A'))  # Fixed: Matches 'HS %' from scraper.py

            # --- BUILD ADVANCED RAW MARKDOWN TEXT FOR DESCRIPTION ---
            desc_lines = [
                f"**PLAYER:** {p_name} vs. {opponent.upper()}",
                f"**MATCH:** Maps 1–2 Kills | **PROP LINE:** {p_prop_line}",
                "----------------------------------------------------------------",
                f"**GRADE:** {p_grade}",
                f"**PROJECTION:** ⏸️ **{rec}** ({p_mispriced})",
                "----------------------------------------------------------------",
                "",
                "### 📊 CORE METRICS",
                f"• **Recent Avg (Last 10):** {p_avg}",
                f"• **Recent Median:** {p_median}",
                f"• **Hit Rate:** {p_hitrate}",
                f"• **Projected Rounds:** {p_rounds}",
                f"• **Role:** {p_role}",
                "",
                "### 📈 PROJECTION (EMPIRICAL MODEL)",
                f"• **Simulated Mean:** {s_mean}  |  **σ:** {s_std}",
                f"• **Over Probability:** {s_over}",
                f"• **Under Probability:** {s_under}",
                f"• **Edge vs. Line:** {s_edge}",
                f"• **Expected Kills:** {s_expected}",
                f"• **Historical Ceiling/Floor:** {p_floor}–{p_ceil}",
                f"• **Combat Stats:** KPR: {p_kpr} | ADR: {p_adr} | HS%: {p_hs}%",
                ""
            ]

            # Add Map Pool Intelligence if available
            map_avgs = data.get('Per-map averages', {})
            if map_avgs:
                desc_lines.append("### 🗺️ MAP INTELLIGENCE")
                for m, stats in list(map_avgs.items())[:4]:
                    desc_lines.append(f"• **{m.title()}:** {stats.get('avg_kills', 'N/A')}k avg ({stats.get('avg_kpr', 'N/A')} KPR)")
                desc_lines.append("")

            # Add Match History Log Array
            totals = data.get('Recent Totals (M1+M2 Combined)', [])
            if totals:
                desc_lines.append("### 📋 SERIES BREAKDOWN")
                over_under_history = ""
                for idx, val in enumerate(totals, 1):
                    status_emoji = "✅" if float(val) > line_float else "❌"
                    over_under_history += f"S{idx}: **{val}** {status_emoji}  "
                desc_lines.append(over_under_history)
                desc_lines.append("")

            # Append the narrative generator summary
            if 'Analysis' in data:
                desc_lines.append("### 🔍 ANALYSIS")
                desc_lines.append(str(data['Analysis']))

            # Render single clean master block
            embed = discord.Embed(
                title="🎯 ULTIMATE KILLS ANALYSIS", 
                description="\n".join(desc_lines), 
                color=color
            )
            embed.set_footer(text="God-Tier Prop Engine • 100K Monte Carlo • Last 10 BO3")

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

            # Safe string conversions for headshots template
            p_name = str(data.get('Player', player.title()))

            # --- BUILD ADVANCED RAW MARKDOWN TEXT FOR HEADSHOTS ---
            hs_lines = [
                f"**PLAYER:** {p_name} vs. {opponent.upper()}",
                f"**MATCH:** Maps 1–2 Headshots | **PROP LINE:** {line} HS",
                "----------------------------------------------------------------",
                f"**PROJECTION:** 🎯 **{bet_rec}**",
                "----------------------------------------------------------------",
                "",
                "### 📊 HEADSHOT PERFORMANCE PROFILE",
                f"• **Recent Avg HS:** {hs_avg}",
                f"• **Median HS:** {hs_median}",
                f"• **Hit Rate:** {hits}/{len(hs_totals)} ({round(hit_rate, 1)}%)",
                f"• **Base HS Rate:** {hs_rate}%",
                f"• **Calculated Edge:** {round(edge, 1)}%",
                "",
                "### 🤖 SIMULATION PROBABILITIES",
                f"• **Over Probability:** {round(over_prob, 1)}%",
                f"• **Under Probability:** {round(under_prob, 1)}%",
                "",
                "### 📋 SERIES BREAKDOWN"
            ]

            over_under_str = ""
            for i, hs_val in enumerate(hs_totals, 1):
                status = "✅" if hs_val > line_float else "❌"
                over_under_str += f"S{i}: **{hs_val}** {status}  "
            hs_lines.append(over_under_str)
            hs_lines.append("")

            if individual_hs:
                hs_lines.append("🗺️ **Map-by-Map Raw Splits (Last 10):**")
                ind_str = ', '.join(str(x) for x in individual_hs[:10])
                hs_lines.append(f"`{ind_str}...`")
                hs_lines.append("")

            hs_lines.append(f"**Line Check:** Value set at {line} → player requires >{line} to clear.")

            embed = discord.Embed(
                title="🎯 ULTIMATE HEADSHOT ANALYSIS", 
                description="\n".join(hs_lines), 
                color=color
            )
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
