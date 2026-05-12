import os
import discord
from discord.ext import commands

from scraper import (
    search_player,
    get_player_data
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

@bot.command()
async def scan(
    ctx,
    player=None,
    line=None,
    opponent=None
):

    await ctx.send(
        f"🔎 Scanning {player}..."
    )

    data = get_player_data(
        player,
        opponent
    )

    if not data:

        await ctx.send(
            "❌ No player data found."
        )

        return

    avg = data["avg"]

    avg_hs = data["avg_hs"]

    avg_rating = data["avg_rating"]

    sample = data["sample"]

    maps = data["maps"]

    line_float = float(line)

    recent_kills = [

        m["kills"]

        for m in maps

        if m.get("kills") is not None
    ]

    hits = len([

        k for k in recent_kills

        if k > line_float
    ])

    hit_rate = round(
        (
            hits / len(recent_kills)
        ) * 100,
        1
    )

    edge = round(
        avg - line_float,
        2
    )

    recent_maps = ", ".join([
        str(k)
        for k in recent_kills[:10]
    ])

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
