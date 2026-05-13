import os
import discord
from discord.ext import commands

from scraper import (
    search_player,
    get_player_info
)

# =====================================================
# DISCORD SETUP
# =====================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =====================================================
# READY EVENT
# =====================================================

@bot.event
async def on_ready():

    print(
        f"✅ Logged in as {bot.user}"
    )

# =====================================================
# TEST COMMAND
# =====================================================

@bot.command()
async def test(ctx):

    await ctx.send(
        "✅ BOT WORKING"
    )

# =====================================================
# LOOKUP COMMAND
# =====================================================

@bot.command()
async def lookup(
    ctx,
    player=None
):

    if not player:

        await ctx.send(
            "❌ Please provide a player"
        )

        return

    result = search_player(player)

    if not result:

        await ctx.send(
            "❌ NO PLAYER"
        )

        return

    pid, slug, display = result

    await ctx.send(
        f"✅ FOUND: {display} ({pid})"
    )

# =====================================================
# SCAN COMMAND
# =====================================================

@bot.command()
async def scan(
    ctx,
    player=None,
    line=None,
    opponent=None
):

    try:

        if not player or not line or not opponent:

            await ctx.send(
                "❌ Usage: !scan player line opponent"
            )

            return

        await ctx.send(
            f"🔎 Scanning {player}..."
        )

        print(
            "SCAN COMMAND HIT"
        )

        await ctx.send(
            "📡 Fetching HLTV data..."
        )

        data = get_player_info(
            player,
            opponent
        )

        await ctx.send(
            "✅ HLTV response received"
        )

        print(
            "SCRAPER RETURN:",
            data
        )

        if not data:

            await ctx.send(
                "❌ No player data found."
            )

            return

        # =====================================================
        # SAFE DATA EXTRACTION
        # =====================================================

        avg = data.get("avg", 0)

        avg_hs = data.get("avg_hs", 0)

        avg_rating = data.get("avg_rating", 0)

        sample = data.get("sample", 0)

        maps = data.get("maps", [])

        try:
            line_float = float(line)
        except:
            await ctx.send(
                "❌ Invalid line"
            )
            return

        # =====================================================
        # RECENT KILLS
        # =====================================================

        recent_kills = [

            m.get("kills")

            for m in maps

            if m.get("kills") is not None
        ]

        # =====================================================
        # HIT RATE FIX
        # =====================================================

        hits = len([

            k for k in recent_kills

            if k > line_float
        ])

        if len(recent_kills) == 0:

            hit_rate = 0.0

        else:

            hit_rate = round(
                (
                    hits / len(recent_kills)
                ) * 100,
                1
            )

        # =====================================================
        # EDGE
        # =====================================================

        edge = round(
            avg - line_float,
            2
        )

        # =====================================================
        # RECENT MAPS STRING
        # =====================================================

        if len(recent_kills) == 0:

            recent_maps = "No maps found"

        else:

            recent_maps = ", ".join([
                str(k)
                for k in recent_kills[:10]
            ])

        # =====================================================
        # EMBED
        # =====================================================

        embed = discord.Embed(

            title=(
                f"🎯 {player.upper()} "
                f"PROP SCAN"
            ),

            color=0x00ff00
        )

        embed.add_field(
            name="👤 Player",
            value=player,
            inline=False
        )

        embed.add_field(
            name="⚔️ Opponent",
            value=opponent,
            inline=False
        )

        embed.add_field(
            name="🎯 Line",
            value=line,
            inline=False
        )

        embed.add_field(
            name="📊 Avg Kills",
            value=avg,
            inline=False
        )

        embed.add_field(
            name="📈 Edge",
            value=edge,
            inline=False
        )

        embed.add_field(
            name="🔥 Hit Rate",
            value=f"{hit_rate}%",
            inline=False
        )

        embed.add_field(
            name="💥 Avg HS",
            value=avg_hs,
            inline=False
        )

        embed.add_field(
            name="⭐ Avg Rating",
            value=avg_rating,
            inline=False
        )

        embed.add_field(
            name="🧪 Sample",
            value=sample,
            inline=False
        )

        embed.add_field(
            name="📋 Recent Maps",
            value=recent_maps,
            inline=False
        )

        await ctx.send(
            embed=embed
        )

    except Exception as e:

        print(
            "SCAN ERROR:",
            e
        )

        await ctx.send(
            f"❌ Scan crashed: {e}"
        )

# =====================================================
# TOKEN
# =====================================================

TOKEN = os.getenv(
    "DISCORD_TOKEN"
)

# =====================================================
# RUN BOT
# =====================================================

bot.run(TOKEN)
