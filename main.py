import os
import discord
from discord.ext import commands

from scraper import search_player

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
# TEST COMMAND
# =====================================================

@bot.command()
async def test(ctx):

    print("TEST COMMAND HIT")

    await ctx.send(
        "TEST WORKING"
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

    print(
        "GRADE COMMAND HIT"
    )

    await ctx.send(
        f"🔎 Testing player: {player}"
    )

    # =============================================
    # SEARCH PLAYER
    # =============================================

    print(
        "RUNNING SEARCH"
    )

    result = search_player(
        player
    )

    print(
        "SEARCH RESULT:",
        result
    )

    # =============================================
    # PLAYER NOT FOUND
    # =============================================

    if not result:

        await ctx.send(
            "❌ Player not found"
        )

        return

    pid, slug, display = result

    # =============================================
    # SUCCESS
    # =============================================

    await ctx.send(

        f"✅ Found player:\n"
        f"{display}\n"
        f"ID: {pid}"
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
