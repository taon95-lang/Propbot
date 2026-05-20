import os
import discord
import asyncio
from discord.ext import commands
import statistics as _stats

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
            
            embed = discord.Embed(title=f"🎯 {data['Player'].upper()} KILLS ANALYSIS", color=color)
            
            embed.add_field(name="👤 Player", value=data['Player'], inline=True)
            embed.add_field(name="⚔️ Match", value=data['Match'], inline=True)
            embed.add_field(name="🎯 Prop Line", value=data['Prop'], inline=True)
            
            embed.add_field(name="🎭 Role", value=data['Role'], inline=True)
            embed.add_field(name="🧪 Recent Sample", value=data['Recent sample used'], inline=True)
            embed.add_field(name="📊 Recent Avg", value=data['Recent average'], inline=True)
            
            embed.add_field(name="📈 Median", value=data['Recent median'], inline=True)
            embed.add_field(name="🔥 Hit Rate", value=data['Hit rate'], inline=True)
            embed.add_field(name="⏳ Proj Rounds", value=data['Projected rounds'], inline=True)
            
            embed.add_field(name="🔫 Expected Kills", value=data['Expected kills'], inline=True)
            embed.add_field(name="🤖 Sim Mean", value=data['Simulated mean'], inline=True)
            embed.add_field(name="📉 Std Dev", value=data['Standard deviation'], inline=True)
            
            embed.add_field(name="📈 Over %", value=data['Over probability'], inline=True)
            embed.add_field(name="📉 Under %", value=data['Under probability'], inline=True)
            embed.add_field(name="📐 Edge", value=data['Edge vs line'], inline=True)
            
            embed.add_field(name="⚖️ Mispriced", value=data['Mispriced or not'], inline=True)
            embed.add_field(name="✅ Grade", value=f"**{data['Final grade']}**", inline=True)
            embed.add_field(name="💰 Bet", value=f"**{rec}**", inline=True)
            
            totals = data.get('Recent Totals (M1+M2 Combined)', [])
            if totals:
                totals_str = ', '.join(str(x) for x in totals)
                embed.add_field(name="📋 Recent Totals (M1+M2)", value=f"`{totals_str}`", inline=False)
            
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

            # Extract HS-specific data
            hs_totals = data.get('Recent HS Totals (M1+M2)', [])
            hs_avg = data.get('Recent HS Average', 0)
            hs_median = data.get('Recent HS Median', 0)
            hs_rate = data.get('HS Rate', 0)
            individual_hs = data.get('Individual Map HS', [])
            
            if not hs_totals:
                return await msg.edit(content="❌ No headshot data found")
            
            # Calculate HS-specific stats
            hits = sum(1 for x in hs_totals if x > line_float)
            hit_rate = (hits / len(hs_totals)) * 100
            
            # HS grading logic
            if hs_avg > (line_float + 2) and hs_median > line_float and hit_rate >= 60:
                bet_rec = "OVER"
                color = 0x00ff00
            elif hs_avg < (line_float - 1) and hs_median < line_float and hit_rate <= 40:
                bet_rec = "UNDER"
                color = 0xff0000
            else:
                bet_rec = "NO BET"
                color = 0x808080
            
            # Edge calculation for HS
            if len(hs_totals) > 1:
                hs_var = _stats.variance(hs_totals)
                if hs_var <= hs_avg:
                    hs_var = hs_avg * 1.3
                
                p_nb = hs_avg / hs_var
                n_nb = (hs_avg ** 2) / (hs_var - hs_avg)
                
                import numpy as np
                sim = np.random.negative_binomial(max(1, int(n_nb)), min(0.99, p_nb), 100000)
                over_prob = (np.sum(sim > line_float) / 100000) * 100
                under_prob = 100.0 - over_prob
                edge = over_prob - 50.0
            else:
                over_prob, under_prob, edge = 50.0, 50.0, 0.0
            
            # Build embed
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
            
            # Series breakdown
            hs_str = ', '.join(str(x) for x in hs_totals)
            embed.add_field(name="📋 Recent HS Totals (M1+M2)", value=f"`{hs_str}`", inline=False)
            
            # Individual map HS
            if individual_hs:
                ind_str = ', '.join(str(x) for x in individual_hs[:10])
                embed.add_field(name="🗺️ Individual Map HS", value=f"`{ind_str}...`", inline=False)
            
            # Line comparison
            over_under_str = ""
            for i, hs_val in enumerate(hs_totals, 1):
                status = "✅" if hs_val > line_float else "❌"
                over_under_str += f"S{i}: **{hs_val}** {status}  "
            embed.add_field(name="📊 Series Breakdown", value=over_under_str, inline=False)
            
            embed.add_field(name="🎯 Line Check", value=f"**Line {line} → need >{line}**", inline=False)
            
            embed.set_footer(text="God-Tier Headshot Analyzer • Last 10 BO3 Maps 1-2")

            await msg.edit(content=None, embed=embed)

        except ValueError:
            await msg.edit(content="❌ Invalid line. Use decimal (e.g., 16.5)")
        except Exception as e:
            print(f"HS SCAN ERROR: {e}")
            await msg.edit(content=f"❌ HS scan crashed: {e}")

bot.run(os.getenv("DISCORD_TOKEN"))
