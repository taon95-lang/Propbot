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
            # Safe threaded background pool isolation runs parallel to main Discord tasks
            data = await asyncio.to_thread(get_player_info, player, line_float, opponent)

            if isinstance(data, str) and "FAIL" in data:
                return await msg.edit(content=f"❌ {data}")

            rec = data['Bet recommendation']
            color = 0x00ff00 if "OVER" in rec else 0xff0000 if "UNDER" in rec else 0x808080
            
            embed = discord.Embed(title=f"🎯 {data['Player'].upper()} GOLD SCAN", color=color)
            
            embed.add_field(name="👤 Player", value=data['Player'], inline=True)
            embed.add_field(name="⚔️ Match", value=data['Match'], inline=True)
            embed.add_field(name="🎯 Prop Line", value=data['Prop'], inline=True)
            
            embed.add_field(name="🎭 Role", value=data['Role'], inline=True)
            embed.add_field(name="🧪 Recent Sample Used", value=data['Recent sample used'], inline=True)
            embed.add_field(name="📊 Recent Average", value=data['Recent average'], inline=True)
            
            embed.add_field(name="📈 Recent Median", value=data['Recent median'], inline=True)
            embed.add_field(name="🔥 Hit Rate", value=data['Hit rate'], inline=True)
            embed.add_field(name="⏳ Projected Rounds", value=data['Projected rounds'], inline=True)
            
            embed.add_field(name="🔫 Expected Kills", value=data['Expected kills'], inline=True)
            embed.add_field(name="🤖 Simulated Mean", value=data['Simulated mean'], inline=True)
            embed.add_field(name="📉 Standard Deviation", value=data['Standard deviation'], inline=True)
            
            embed.add_field(name="📈 Over Probability", value=data['Over probability'], inline=True)
            embed.add_field(name="📉 Under Probability", value=data['Under probability'], inline=True)
            embed.add_field(name="📐 Edge vs Line", value=data['Edge vs line'], inline=True)
            
            embed.add_field(name="⚖️ Mispriced or Not", value=data['Mispriced or not'], inline=True)
            embed.add_field(name="✅ Final Grade", value=f"**{data['Final grade']}**", inline=True)
            embed.add_field(name="💰 Bet Recommendation", value=f"**{rec}**", inline=True)
            
            embed.add_field(name="📋 Recent Totals (Maps 1-2 Only)", value=f"`{data['Recent totals']}`", inline=False)
            embed.set_footer(text="Gold Standard Prediction Engine • 100,000 Monte Carlo Simulation Runs")

            await msg.edit(content=None, embed=embed)

        except ValueError:
            await msg.edit(content="❌ The **line** parameter must match a valid decimal structure layout (e.g. 32.5).")
        except Exception as e:
            print(f"SCAN ERROR: {e}")
            await msg.edit(content=f"❌ Scan execution crashed: {e}")

bot.run(os.getenv("DISCORD_TOKEN"))
