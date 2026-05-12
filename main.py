import discord
import os

from scraper import search_player

# =====================================================
# TOKEN
# =====================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# =====================================================
# DISCORD SETUP
# =====================================================

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

# =====================================================
# READY
# =====================================================

@client.event
async def on_ready():

    print(f"✅ Logged in as {client.user}")

# =====================================================
# MESSAGES
# =====================================================

@client.event
async def on_message(message):

    if message.author == client.user:
        return

    content = message.content.lower()

    # =================================================
    # PING
    # =================================================

    if content == "!ping":

        await message.channel.send("🏓 pong")

    # =================================================
    # GRADE
    # =================================================

    elif content.startswith("!grade"):

        args = message.content.split()

        if len(args) < 4:

            await message.channel.send(
                "Usage: !grade player line opponent"
            )

            return

        player_name = args[1]
        line = args[2]
        opponent = " ".join(args[3:])

        await message.channel.send(
            f"🔍 Searching HLTV for {player_name}..."
        )

        # =============================================
        # SEARCH PLAYER
        # =============================================

        try:

            player = search_player(player_name)

        except Exception as e:

            print("SEARCH ERROR:", e)

            await message.channel.send(
                f"❌ Scraper crashed:\n{e}"
            )

            return

        # =============================================
        # PLAYER NOT FOUND
        # =============================================

        if not player:

            await message.channel.send(
                "❌ Player not found on HLTV"
            )

            return

        # =============================================
        # PLAYER DATA
        # =============================================

        player_id = player[0]
        player_slug = player[1]
        player_display = player[2]

        hltv_url = (
            f"https://www.hltv.org/player/"
            f"{player_id}/{player_slug}"
        )

        # =============================================
        # EMBED
        # =============================================

        embed = discord.Embed(
            title="🎯 HLTV PLAYER FOUND",
            color=0x00ff00
        )

        embed.add_field(
            name="👤 Player",
            value=player_display,
            inline=False
        )

        embed.add_field(
            name="🎯 Line",
            value=line,
            inline=False
        )

        embed.add_field(
            name="⚔ Opponent",
            value=opponent,
            inline=False
        )

        embed.add_field(
            name="🔗 HLTV",
            value=hltv_url,
            inline=False
        )

        await message.channel.send(embed=embed)

# =====================================================
# RUN
# =====================================================

client.run(DISCORD_TOKEN)
