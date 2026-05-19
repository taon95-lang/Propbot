import os
import discord
import asyncio
import functools
from discord.ext import commands
from scraper import get_player_info

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}", flush=True)

@bot.command()
async def scan(ctx, player=None, line=None, opponent="N/A"):
    if not player or not line:
        return await ctx.send("❌ Usage: `!scan player line opponent`")

    msg = await ctx.send(f"🔎 **Scanning {player} for line {line} vs {opponent}...**")
    
    async with ctx.typing():
        try:
            line_float = float(line)
            data = await asyncio.to_thread(get_player_info, player, line_float, opponent)

            if isinstance(data, str) and "FAIL" in data:
                return await msg.edit(content=f"❌ {data}")

            # Handle error responses
            if "error" in data:
                return await msg.edit(content=f"❌ {data.get('error', 'Unknown error occurred')}")

            rec = data.get('Bet recommendation', 'NO BET')
            
            # Explicit statement assignment prevents structural syntax parsing drops
            if "OVER" in rec:
                color = 0x00ff00
            elif "UNDER" in rec:
                color = 0xff0000
            else:
                color = 0x808080
            
            embed = discord.Embed(title=f"🎯 {data.get('Player', player).upper()} GOLD SCAN", color=color)
            
            embed.add_field(name="👤 Player", value=data.get('Player', 'N/A'), inline=True)
            embed.add_field(name="⚔️ Match", value=data.get('Match', 'N/A'), inline=True)
            embed.add_field(name="🎯 Prop Line", value=data.get('Prop', f"{line} Kills"), inline=True)
            
            embed.add_field(name="🎭 Role", value=data.get('Role', 'N/A'), inline=True)
            embed.add_field(name="🧪 Recent Sample Used", value=data.get('Recent sample used', 'N/A'), inline=True)
            embed.add_field(name="📊 Recent Average", value=data.get('Recent average', 0.0), inline=True)
            
            embed.add_field(name="📈 Recent Median", value=data.get('Recent median', 0.0), inline=True)
            embed.add_field(name="🔥 Hit Rate", value=data.get('Hit rate', '0.0%'), inline=True)
            embed.add_field(name="⏳ Projected Rounds", value=data.get('Projected rounds', 0), inline=True)
            
            embed.add_field(name="🔫 Expected Kills", value=data.get('Expected kills', 0.0), inline=True)
            embed.add_field(name="🤖 Simulated Mean", value=data.get('Simulated mean', 0.0), inline=True)
            embed.add_field(name="📉 Standard Deviation", value=data.get('Standard deviation', 0.0), inline=True)
            
            embed.add_field(name="📈 Over Probability", value=data.get('Over probability', '0.0%'), inline=True)
            embed.add_field(name="📉 Under Probability", value=data.get('Under probability', '0.0%'), inline=True)
            embed.add_field(name="📐 Edge vs Line", value=data.get('Edge vs line', '0.0%'), inline=True)
            
            embed.add_field(name="⚖️ Mispriced or Not", value=data.get('Mispriced or not', 'NO'), inline=True)
            embed.add_field(name="✅ Final Grade", value=f"**{data.get('Final grade', 'N/A')}**", inline=True)
            embed.add_field(name="💰 Bet Recommendation", value=f"**{rec}**", inline=True)
            
            # ✅ FIXED: Safe fallback chain for Recent Totals
            recent_totals = (
                data.get('Recent Totals (M1+M2 Combined)') or
                data.get('Recent Totals') or
                data.get('Recent totals') or
                []
            )
            
            if recent_totals:
                totals_display = ', '.join(str(x) for x in recent_totals)
                embed.add_field(name="📋 Recent Totals (Maps 1-2 Only)", value=f"`{totals_display}`", inline=False)
            else:
                embed.add_field(name="📋 Recent Totals (Maps 1-2 Only)", value="`No data available`", inline=False)
            
            embed.set_footer(text="Gold Standard Prediction Engine • 100,000 Monte Carlo Simulation Runs")

            await msg.edit(content=None, embed=embed)

        except ValueError:
            await msg.edit(content="❌ The **line** parameter must match a valid decimal format (e.g. 32.5).")
        except Exception as e:
            print(f"SCAN ERROR: {e}")
            await msg.edit(content=f"❌ Scan execution crashed: {e}")

bot.run(os.getenv("DISCORD_TOKEN"))
