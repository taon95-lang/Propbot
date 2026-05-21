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

            # --- BUILD ADVANCED RAW MARKDOWN TEXT FOR DESCRIPTION ---
            desc_lines = [
                f"**PLAYER:** {data['Player']} vs. {opponent.upper()}",
                f"**MATCH:** Maps 1–2 Kills | **PROP LINE:** {data['Prop Line']}",
                "----------------------------------------------------------------",
                f"**GRADE:** {data['Final grade']}",
                f"**PROJECTION:** ⏸️ **{rec}** ({data['Mispriced or not']})",
                "----------------------------------------------------------------",
                "",
                "### 📊 CORE METRICS",
                f"• **Recent Avg (Last 10):** {data['Recent average']}",
                f"• **Recent Median:** {data['Recent median']}",
                f"• **Hit Rate:** {data['Hit rate']}",
                f"• **Projected Rounds:** {data['Projected rounds']}",
                f"• **Role:** {data.get('Role', 'N/A')}",
                "",
                "### 📈 PROJECTION (EMPIRICAL MODEL)",
                f"• **Simulated Mean:** {data.get('Simulated mean', 'N/A')}  |  **σ:** {data.get('Standard deviation', 'N/A')}",
                f"• **Over Probability:** {data['Over probability']}",
                f"• **Under Probability:** {data['Under probability']}",
                f"• **Edge vs. Line:** {data['Edge vs line']}",
                f"• **Expected Kills:** {data['Expected kills']}",
                f"• **Historical Ceiling/Floor:** {data.get('Floor (Bottom 3 avg)', 'N/A')}–{data.get('Ceiling (Top 3 avg)', 'N/A')}",
                f"• **Combat Stats:** KPR: {data.get('KPR', 'N/A')} | ADR: {data.get('ADR', 'N/A')} | HS%: {data.get('HS', 0)}%",
                ""
            ]

            # Add Map Pool Intelligence if available
            map_avgs = data.get('Per-map averages', {})
            if map_avgs:
                desc_lines.append("### 🗺️ MAP INTELLIGENCE")
                for m, stats in list(map_avgs.items())[:4]:
                    desc_lines.append(f"• **{m.title()}:** {stats['avg_kills']}k avg ({stats['avg_kpr']} KPR)")
                desc_lines.append("")

            # Add Match History Log Array
            totals = data.get('Recent Totals (M1+M2 Combined)', [])
            if totals:
                desc_lines.append("### 📋 SERIES BREAKDOWN")
                over_under_history = ""
                for idx, val in enumerate(totals, 1):
                    status_emoji = "✅" if val > line_float else "❌"
                    over_under_history += f"S{idx}: **{val}** {status_emoji}  "
                desc_lines.append(over_under_history)
                desc_lines.append("")

            # Append the narrative generator summary
            if 'Analysis' in data:
                desc_lines.append("### 🔍 ANALYSIS")
                desc_lines.append(data['Analysis'])

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

            # --- BUILD ADVANCED RAW MARKDOWN TEXT FOR HEADSHOTS ---
            hs_lines = [
                f"**PLAYER:** {data['Player']} vs. {opponent.upper()}",
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

            if list(individual_hs):
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
