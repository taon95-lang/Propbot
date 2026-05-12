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

    print(
        "TEST COMMAND HIT"
    )

    await ctx.send(
        "TEST WORKING"
    )

# =====================================================
# REAL GRADE COMMAND
# =====================================================

@bot.command()
async def grade(
    ctx,
    player=None,
    line=None,
    opponent=None
):

    await ctx.send(
        f"🔎 Grading {player} vs {opponent}..."
    )

    print(
        "RUNNING GET_PLAYER_DATA"
    )

    data = get_player_data(
        player,
        opponent
    )

    print(
        "SCRAPER RETURN:",
        data
    )

    # =============================================
    # NO DATA
    # =============================================

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

    # =============================================
    # RECENT KILLS
    # =============================================

    recent_kills = [

        m["kills"]

        for m in maps

        if m.get("kills") is not None
    ]

    # =============================================
    # HIT RATE
    # =============================================

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

    # =============================================
    # EDGE
    # =============================================

    edge = round(
        avg - line_float,
        2
    )

    # =============================================
    # DECISION ENGINE
    # =============================================

    if edge >= 3:

        decision = "OVER"
        grade_letter = "A"

    elif edge >= 1:

        decision = "LEAN OVER"
        grade_letter = "B"

    elif edge <= -3:

        decision = "UNDER"
        grade_letter = "A"

    elif edge <= -1:

        decision = "LEAN UNDER"
        grade_letter = "B"

    else:

        decision = "NO BET"
        grade_letter = "C"

    # =============================================
    # RECENT MAPS DISPLAY
    # =============================================

    recent_maps = ", ".join([
        str(k)
        for k in recent_kills[:10]
    ])

    # =============================================
    # EMBED
    # =============================================

    embed = discord.Embed(
        title=(
            f"🎯 {player.upper()} "
            f"PROP GRADE"
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
        name="🏆 Decision",
        value=(
            f"{decision} "
            f"({grade_letter})"
        ),
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
