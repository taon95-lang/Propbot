import os
import discord
import statistics as _stats
from discord.ext import commands
from scraper import search_player, get_player_info

# =====================================================
# BOT SETUP
# =====================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}", flush=True)

# =====================================================
# SCAN COMMAND (UPDATED FOR GOLD STANDARD)
# =====================================================
@bot.command()
async def scan(ctx, player=None, line=None, opponent=None):
    try:
        if not player or not line or not opponent:
            return await ctx.send("❌ Usage: !scan player line opponent")

        await ctx.send(f"🔎 Scanning {player} for line {line} vs {opponent}...")
        
        # 1. Fetch Gold Standard Data
        data = get_player_info(player, opponent)
        if not data:
            return await ctx.send("❌ No player data found.")

        # 2. Extract Data
        avg = data.get("avg", 0)
        avg_hs = data.get("avg_hs", 0)
        maps = data.get("maps", [])
        line_float = float(line)

        # 3. Group Maps into Series (Combined Maps 1+2 Total)
        # This fixes the 0% hit rate bug
        series_totals = []
        for i in range(0, len(maps), 2):
            if i + 1 < len(maps):
                combined = maps[i]["kills"] + maps[i+1]["kills"]
                series_totals.append(combined)

        # 4. Calculate Critical Metrics
        median = _stats.median(series_totals) if series_totals else 0
        stdev = _stats.stdev(series_totals) if len(series_totals) > 1 else 0
        hits = sum(1 for total in series_totals if total > line_float)
        hit_rate = round((hits / len(series_totals)) * 100, 1) if series_totals else 0
        edge = round((avg * 2) - line_float, 2) # avg is per-map, line is 2-map

        # 5. Final Decision Logic
        # Rules: Over if avg/median are far above line and hit rate is strong.
        recommendation = "No Bet"
        grade = "5/10"
        if (avg * 2) > line_float + 2 and median > line_float and hit_rate >= 70:
            recommendation = "OVER"
            grade = "8/10"
        elif (avg * 2) < line_float - 2 and median < line_float:
            recommendation = "UNDER"
            grade = "8/10"

        # 6. Build the Gold Standard Embed
        embed = discord.Embed(title=f"🎯 {player.upper()} GOLD SCAN", color=0x00ff00)
        embed.add_field(name="👤 Player", value=data['player'], inline=True)
        embed.add_field(name="⚔️ Opponent", value=opponent, inline=True)
        embed.add_field(name="🎯 Line (M1+M2)", value=line, inline=True)
        
        embed.add_field(name="📊 Recent Avg (2-Map)", value=round(avg * 2, 2), inline=True)
        embed.add_field(name="📈 Recent Median", value=median, inline=True)
        embed.add_field(name="🔥 Hit Rate", value=f"{hit_rate}%", inline=True)
        
        embed.add_field(name="💥 Avg HS", value=avg_hs, inline=True)
        embed.add_field(name="🧪 Sample (Series)", value=len(series_totals), inline=True)
        embed.add_field(name="📉 Standard Dev", value=round(stdev, 2), inline=True)

        embed.add_field(name="✅ Final Grade", value=f"**{grade}**", inline=True)
        embed.add_field(name="💰 Recommendation", value=f"**{recommendation}**", inline=True)
        embed.add_field(name="📋 Recent Totals", value=", ".join(map(str, series_totals)), inline=False)

        await ctx.send(embed=embed)

    except Exception as e:
        print(f"SCAN ERROR: {e}", flush=True)
        await ctx.send(f"❌ Scan crashed: {e}")

bot.run(os.getenv("DISCORD_TOKEN"))
