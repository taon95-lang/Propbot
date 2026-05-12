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

    # =============================================
    # VALIDATION
    # =============================================

    if not player:

        await ctx.send(
            "❌ Missing player"
        )

        return

    result = search_player(player)

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

    embed = discord.Embed(

        title="🎯 PLAYER SCAN",

        color=0x00ff00
    )

    embed.add_field(
        name="👤 Player",
        value=display,
        inline=False
    )

    embed.add_field(
        name="🆔 HLTV ID",
        value=pid,
        inline=False
    )

    embed.add_field(
        name="🎯 Line",
        value=line,
        inline=False
    )

    embed.add_field(
        name="⚔️ Opponent",
        value=opponent,
        inline=False
    )

    embed.add_field(
        name="🔗 HLTV",
        value=(
            f"https://www.hltv.org/player/"
            f"{pid}/{slug}"
        ),
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
