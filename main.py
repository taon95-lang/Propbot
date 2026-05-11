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
# BOT ONLINE
# =====================================================

@client.event
async def on_ready():

    print(f"✅ Logged in as {client.user}")

# =====================================================
# COMMANDS
# =====================================================

@client.event
async def on_message(message):

    if message.author == client.user:
        return

    content = message.content.lower()

    # =================================================
    # !PING
    # =================================================

    if content == "!ping":

        await message.channel.send("🏓 pong")

    # =================================================
    # !GRADE
    # =================================================

    elif content.startswith("!grade"):

        await message.channel.send(
            "🔍 Running HLTV scraper test..."
        )

        # =============================================
        # FORCE DONK TEST
        # =============================================

        try:

            player = search_player("donk")

            print("PLAYER RESULT:", player)

        except Exception as e:

            print("SCRAPER ERROR:", e)

            await message.channel.send(
                f"❌ Scraper crashed:\n{e}"
            )

            return

        # =============================================
        # FAILED
        # =============================================

        if player is None:

            await message.channel.send(
                "❌ Player not found on HLTV"
            )

            return

        # =============================================
        # SCRAPER RETURNS:
        # (player_id, slug, display_name)
        # =============================================

        player_id = player[0]
        player_slug = player[1]
        player_display = player[2]

        # =============================================
        # HLTV URL
        # =============================================

        hltv_url = (
            f"https://www.hltv.org/player/"
            f"{player_id}/{player_slug}"
        )

        # =============================================
        # EMBED
        # =============================================

        embed = discord.Embed(
            title="🎯 HLTV SCRAPER WORKING",
            color=0x00ff00
        )

        embed.add_field(
            name="👤 Player",
            value=player_display,
            inline=False
        )

        embed.add_field(
            name="🆔 HLTV ID",
            value=player_id,
            inline=False
        )

        embed.add_field(
            name="🔗 Profile",
            value=hltv_url,
            inline=False
        )

        embed.add_field(
            name="📡 Status",
            value="✅ Search successful",
            inline=False
        )

        await message.channel.send(embed=embed)

# =====================================================
# RUN BOT
# =====================================================

client.run(DISCORD_TOKEN)
