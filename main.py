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
        return await ctx.send("❌ Usage: `!scan name line opponent`")

    status_msg = await ctx.send(f"🔎 **Scanning {player} for line {line} vs {opponent}...**")
    
    async with ctx.typing():
        try:
            line_float = float(line)
            # Run the heavy scraper in a background thread to prevent timeout
            data = await asyncio.to_thread(get_player_info, player, line_float, opponent)

            if isinstance(data, str) and "FAIL" in data:
                return await status_msg.edit(content=f"❌ {data}")

            # Grading Logic
            grade_val = int(data['Final grade'].split('/')[0])
            recommendation = data['Recommendation']
            
            # Embed Color: Green for Over, Red for Under, Gray for No Bet
            color = 0x00ff00 if "OVER" in recommendation else 0xff0000 if "UNDER" in recommendation else 0x808080
            
            embed = discord.Embed(title=f"🎯 {data['Player'].upper()} GOLD SCAN", color=color)
            embed.add_field(name="👤 Player", value=data['Player'], inline=True)
            embed.add_field(name="⚔️ Opponent", value=opponent, inline=True)
            embed.add_field(name="🎯 Line (M1+M2)", value=f"**{line}**", inline=True)
            
            embed.add_field(name="📊 Recent Avg (2-Map)", value=data['Recent average'], inline=True)
            embed.add_field(name="📈 Recent Median", value=data['Recent median'], inline=True)
            embed.add_field(name="🔥 Hit Rate", value=data['Hit rate'], inline=True)
            
            embed.add_field(name="🔫 Expected Kills", value=data['Expected kills'], inline=True)
            embed.add_field(name="⏳ Proj Rounds", value=data['Projected rounds'], inline=True)
            embed.add_field(name="📐 Edge vs Line", value=data['Edge vs line'], inline=True)

            embed.add_field(name="📉 Std Dev", value=data['Standard deviation'], inline=True)
            embed.add_field(name="✅ Final Grade", value=f"**{data['Final grade']}**", inline=True)
            embed.add_field(name="💰 Recommendation", value=f"**{recommendation}**", inline=True)
            
            embed.add_field(name="📋 Recent Totals (M1+M2)", value=f"`{data['Recent totals']}`", inline=False)
            embed.set_footer(text="Simulation: 100k runs | Maps 1-2 Only")

            await status_msg.edit(content=None, embed=embed)

        except Exception as e:
            await status_msg.edit(content=f"❌ Scan error: {e}")

bot.run(os.getenv("DISCORD_TOKEN"))
