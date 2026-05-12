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
# READY
# =====================================================

@bot.event
async def on_ready():

    print(
        f"✅ Logged in as {bot.user}"
    )

# =====================================================
# GRADE COMMAND
# =====================================================

@bot.command()
async def grade(
    ctx,
    player=None,
    line=None,
    opponent=None
):

    # =============================================
    # VALIDATION
    # =============================================

    if not player or not line:

        await ctx.send(
            "Usage: !grade player line opponent"
        )

        return

    await ctx.send(
        f"🔎 Grading {player} vs {opponent}..."
    )

    print(
        "RUNNING GET_PLAYER_DATA"
    )

    # =============================================
    # SCRAPER
    # =============================================

    try:

        data = get_player_data(
            player,
            opponent
        )

        print(
            "SCRAPER RETURN:",
            data
        )

    except Exception as e:

        print(
            "SCRAPER ERROR:",
            e
        )

        await ctx.send(
            f"❌ Scraper error:\n{e}"
        )

        return

    # =============================================
    # NO DATA
    # =============================================

    if not data:

        await ctx.send(
            "❌ No player data found."
        )

        return

    # =============================================
    # DATA
    # =============================================

    avg = data.get("avg", 0)

    avg_hs = data.get(
        "avg_hs",
        0
    )

    avg_rating = data.get(
        "avg_rating",
        0
    )

    avg_adr = data.get(
        "avg_adr",
        0
    )

    avg_kast = data.get(
        "avg_kast",
        0
    )

    sample = data.get(
        "sample",
        0
    )

    maps = data.get(
        "maps",
        []
    )

    # =============================================
    # LINE
    # =============================================

    try:

        line_float = float(line)

    except:

        await ctx.send(
            "❌ Invalid line."
        )

        return

    # =============================================
    # RECENT MAPS
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

    hit_rate = 0

    if recent_kills:

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
    # RECENT MAPS STRING
    # =============================================

    recent_maps = ", ".join([

        str(k)

        for k in recent_kills[:10]
    ])

    # =============================================
    # HLTV LINK
    # =============================================

    player_lookup = search_player(
        player
    )

    hltv_link = "N/A"

    if player_lookup:

        pid, slug, display = player_lookup

        hltv_link = (
            f"https://www.hltv.org/player/"
            f"{pid}/{slug}"
        )

    # =============================================
    # EMBED
    # =============================================

    embed = discord.Embed(

        title=(
            f"🎯 "
            f"{player.upper()} "
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
        name="🎯 ADR",
        value=avg_adr,
        inline=False
    )

    embed.add_field(
        name="🛡️ KAST",
        value=avg_kast,
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

    embed.add_field(
        name="🔗 HLTV",
        value=hltv_link,
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
