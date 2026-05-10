import discord
import os
import requests
from bs4 import BeautifulSoup

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

headers = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    )
}

# =========================================================
# HLTV PLAYER SEARCH
# =========================================================

def search_player(player_name):

    url = f"https://www.hltv.org/search?term={player_name}"

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return None

    try:

        data = response.json()

        players = data[0]["players"]

        if not players:
            return None

        first_player = players[0]

        return {
            "id": first_player["id"],
            "name": first_player["name"]
        }

    except Exception as e:
        print("HLTV Search Error:", e)
        return None

# =========================================================
# BOT ONLINE
# =========================================================

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

# =========================================================
# MESSAGE EVENT
# =========================================================

@client.event
async def on_message(message):

    if message.author == client.user:
        return

    content = message.content.lower()

    # =====================================================
    # !PING
    # =====================================================

    if content == "!ping":
        await message.channel.send("🏓 pong")

    # =====================================================
    # !GRADE
    # Example:
    # !grade donk 32.5 spirit
    # =====================================================

    elif content.startswith("!grade"):

        args = message.content.split()

        if len(args) < 4:
            await message.channel.send(
                "Usage: !grade player line opponent"
            )
            return

        player_name = args[1]
        line = args[2]
        opponent = args[3]

        # =================================================
        # SEARCH PLAYER
        # =================================================

        player_data = search_player(player_name)

        if not player_data:
            await message.channel.send(
                "❌ Player not found on HLTV"
            )
            return

        # =================================================
        # TEMP TEST OUTPUT
        # =================================================

        embed = discord.Embed(
            title="🎯 CS2 PROP GRADE",
            color=0x00ff00
        )

        embed.add_field(
            name="Player",
            value=player_data["name"],
            inline=False
        )

        embed.add_field(
            name="HLTV ID",
            value=player_data["id"],
            inline=False
        )

        embed.add_field(
            name="Line",
            value=line,
            inline=False
        )

        embed.add_field(
            name="Opponent",
            value=opponent,
            inline=False
        )

        embed.add_field(
            name="Status",
            value="✅ HLTV Search Working",
            inline=False
        )

        await message.channel.send(embed=embed)

# =========================================================
# RUN BOT
# =========================================================

client.run(TOKEN)
