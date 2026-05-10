import discord
import os
import requests
from bs4 import BeautifulSoup
import statistics

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

# =========================
# SAMPLE PLAYER DATABASE
# Replace later with HLTV scraper
# =========================

players = {
    "donk": {
        "team": "spirit",
        "role": "Entry",
        "rating": 1.37,
        "kpr": 0.92,
        "dpr": 0.63,
        "adr": 92.4,
        "kast": 73.1,
        "round_swing": "HIGH",
        "multi_kill": "HIGH",
        "maps": [34, 29, 31, 42, 38, 27, 36, 33, 30, 40]
    },

    "m0nesy": {
        "team": "g2",
        "role": "AWP",
        "rating": 1.28,
        "kpr": 0.84,
        "dpr": 0.59,
        "adr": 81.2,
        "kast": 74.5,
        "round_swing": "HIGH",
        "multi_kill": "HIGH",
        "maps": [35, 28, 39, 32, 31, 30, 26, 34, 37, 29]
    },

    "zywoo": {
        "team": "vitality",
        "role": "AWP",
        "rating": 1.35,
        "kpr": 0.88,
        "dpr": 0.57,
        "adr": 86.7,
        "kast": 75.4,
        "round_swing": "HIGH",
        "multi_kill": "MEDIUM",
        "maps": [33, 35, 37, 29, 30, 42, 31, 34, 28, 36]
    }
}

# =========================
# BOT ONLINE
# =========================

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

# =========================
# MESSAGE COMMANDS
# =========================

@client.event
async def on_message(message):

    if message.author == client.user:
        return

    content = message.content.lower()

    # ======================================
    # !PING
    # ======================================

    if content == "!ping":
        await message.channel.send("🏓 pong")

    # ======================================
    # !PLAYERS
    # ======================================

    elif content == "!players":

        names = ", ".join(players.keys())

        await message.channel.send(
            f"📋 Available Players:\n{names}"
        )

    # ======================================
    # !GRADE COMMAND
    # Example:
    # !grade donk 31.5 faze
    # ======================================

    elif content.startswith("!grade"):

        args = content.split()

        if len(args) < 4:
            await message.channel.send(
                "Usage: !grade player line opponent"
            )
            return

        player_name = args[1]
        line = float(args[2])
        opponent = args[3]

        # ======================
        # PLAYER CHECK
        # ======================

        if player_name not in players:

            await message.channel.send(
                f"❌ No data found for {player_name}"
            )
            return

        # ======================
        # PLAYER DATA
        # ======================

        player = players[player_name]

        recent_maps = player["maps"]

        avg = round(statistics.mean(recent_maps), 1)
        median = round(statistics.median(recent_maps), 1)
        ceiling = max(recent_maps)
        floor = min(recent_maps)

        std_dev = round(statistics.stdev(recent_maps), 1)

        hits = sum(1 for x in recent_maps if x > line)
        misses = len(recent_maps) - hits

        hit_rate = round((hits / len(recent_maps)) * 100)

        # ======================
        # SHORT / NORMAL MAP
        # ======================

        short_projection = round(avg * 0.80, 1)
        normal_projection = round(avg, 1)

        # ======================
        # EDGE
        # ======================

        edge = round(((avg - line) / line) * 100, 1)

        # ======================
        # PROJECTION
        # ======================

        if avg >= line and hit_rate >= 60:
            projection = "✅ OVER"

        elif avg < line and hit_rate <= 40:
            projection = "❌ UNDER"

        else:
            projection = "⛔ NO BET"

        # ======================
        # GRADE
        # ======================

        if hit_rate >= 80:
            grade = "A"

        elif hit_rate >= 70:
            grade = "B"

        elif hit_rate >= 60:
            grade = "C"

        else:
            grade = "F"

        # ======================
        # EMBED
        # ======================

        embed = discord.Embed(
            title="🏆 CS2 PROP GRADER",
            color=discord.Color.green()
        )

        embed.add_field(
            name="👤 Player",
            value=player_name,
            inline=True
        )

        embed.add_field(
            name="🎯 Line",
            value=line,
            inline=True
        )

        embed.add_field(
            name="⚔ Opponent",
            value=opponent,
            inline=True
        )

        embed.add_field(
            name="📈 Projection",
            value=projection,
            inline=False
        )

        embed.add_field(
            name="🏅 Grade",
            value=grade,
            inline=True
        )

        embed.add_field(
            name="🔥 Hit Rate",
            value=f"{hit_rate}% ({hits}/10)",
            inline=True
        )

        embed.add_field(
            name="📊 Average",
            value=avg,
            inline=True
        )

        embed.add_field(
            name="📉 Median",
            value=median,
            inline=True
        )

        embed.add_field(
            name="📈 Ceiling",
            value=ceiling,
            inline=True
        )

        embed.add_field(
            name="📉 Floor",
            value=floor,
            inline=True
        )

        embed.add_field(
            name="📉 Std Dev",
            value=std_dev,
            inline=True
        )

        embed.add_field(
            name="⚡ KPR",
            value=player["kpr"],
            inline=True
        )

        embed.add_field(
            name="💀 DPR",
            value=player["dpr"],
            inline=True
        )

        embed.add_field(
            name="🔥 ADR",
            value=player["adr"],
            inline=True
        )

        embed.add_field(
            name="🧠 KAST",
            value=player["kast"],
            inline=True
        )

        embed.add_field(
            name="⭐ Rating",
            value=player["rating"],
            inline=True
        )

        embed.add_field(
            name="🎭 Role",
            value=player["role"],
            inline=True
        )

        embed.add_field(
            name="🔄 Round Swing",
            value=player["round_swing"],
            inline=True
        )

        embed.add_field(
            name="💥 Multi-kill",
            value=player["multi_kill"],
            inline=True
        )

        embed.add_field(
            name="🗺 Short Projection",
            value=short_projection,
            inline=True
        )

        embed.add_field(
            name="🗺 Normal Projection",
            value=normal_projection,
            inline=True
        )

        embed.add_field(
            name="💰 Edge",
            value=f"{edge}%",
            inline=True
        )

        embed.add_field(
            name="📜 Last 10",
            value=str(recent_maps),
            inline=False
        )

        # ======================
        # SEND EMBED
        # ======================

        await message.channel.send(embed=embed)

# =========================
# START BOT
# =========================

client.run(TOKEN)
