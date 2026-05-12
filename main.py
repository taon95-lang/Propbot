import discord
import os

from scraper import (
    search_player,
    get_player_data
)

# =====================================================
# TOKEN
# =====================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# =====================================================
# DISCORD SETUP
# =====================================================

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(
    intents=intents
)

# =====================================================
# READY
# =====================================================

@client.event
async def on_ready():

    print(
        f"✅ Logged in as {client.user}"
    )

# =====================================================
# MESSAGE HANDLER
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

        await message.channel.send(
            "🏓 pong"
        )

    # =================================================
    # !GRADE
    # Example:
    # !grade donk 32.5 spirit
    # =================================================

    elif content.startswith("!grade"):

        args = message.content.split()

        if len(args) < 4:

            await message.channel.send(
                "Usage: !grade player line opponent"
            )

            return

        # =============================================
        # INPUTS
        # =============================================

        player_name = args[1]

        try:

            line = float(args[2])

        except:

            await message.channel.send(
                "❌ Invalid line."
            )

            return

        opponent = " ".join(args[3:])

        # =============================================
        # START MESSAGE
        # =============================================

        await message.channel.send(
            (
                f"🔎 Grading "
                f"{player_name} vs {opponent}..."
            )
        )

        # =============================================
        # SCRAPER
        # =============================================

        try:

            data = get_player_data(
                player_name
            )

        except Exception as e:

            await message.channel.send(
                f"❌ Scraper error:\n{e}"
            )

            return

        # =============================================
        # NO DATA
        # =============================================

        if not data:

            await message.channel.send(
                "❌ No player data found."
            )

            return

        # =============================================
        # PLAYER DATA
        # =============================================

        avg = data["avg"]

        sample = data["sample"]

        maps = data["maps"]

        kills_list = [
            m["kills"]
            for m in maps
            if m["kills"] is not None
        ]

        hs_list = [
            m["hs"]
            for m in maps
            if m["hs"] is not None
        ]

        rating_list = [
            m["rating"]
            for m in maps
            if m["rating"] is not None
        ]

        # =============================================
        # PROJECTIONS
        # =============================================

        edge = round(
            avg - line,
            2
        )

        hit_count = len([
            k for k in kills_list
            if k > line
        ])

        hit_rate = round(
            (
                hit_count
                / len(kills_list)
            ) * 100,
            1
        ) if kills_list else 0

        avg_hs = round(
            (
                sum(hs_list)
                / len(hs_list)
            ),
            2
        ) if hs_list else 0

        avg_rating = round(
            (
                sum(rating_list)
                / len(rating_list)
            ),
            2
        ) if rating_list else 0

        # =============================================
        # DECISION ENGINE
        # =============================================

        if edge >= 4:

            decision = "OVER"

            grade = "A"

        elif edge >= 2:

            decision = "OVER LEAN"

            grade = "B"

        elif edge <= -4:

            decision = "UNDER"

            grade = "A"

        elif edge <= -2:

            decision = "UNDER LEAN"

            grade = "B"

        else:

            decision = "NO BET"

            grade = "C"

        # =============================================
        # RECENT MAPS
        # =============================================

        recent_maps = (
            ", ".join(
                str(k)
                for k in kills_list[:10]
            )
            if kills_list
            else "N/A"
        )

        # =============================================
        # HLTV LINK
        # =============================================

        player = search_player(
            player_name
        )

        hltv_link = "N/A"

        if player:

            pid = player[0]

            slug = player[1]

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
                f"{player_name.upper()} "
                f"PROP GRADE"
            ),
            color=0x00ff00
        )

        embed.add_field(
            name="👤 Player",
            value=player_name,
            inline=True
        )

        embed.add_field(
            name="⚔ Opponent",
            value=opponent,
            inline=True
        )

        embed.add_field(
            name="🎯 Line",
            value=str(line),
            inline=True
        )

        embed.add_field(
            name="📊 Avg Kills",
            value=str(avg),
            inline=True
        )

        embed.add_field(
            name="📈 Edge",
            value=str(edge),
            inline=True
        )

        embed.add_field(
            name="🏆 Decision",
            value=(
                f"{decision} "
                f"({grade})"
            ),
            inline=True
        )

        embed.add_field(
            name="🔥 Hit Rate",
            value=f"{hit_rate}%",
            inline=True
        )

        embed.add_field(
            name="💥 Avg HS",
            value=str(avg_hs),
            inline=True
        )

        embed.add_field(
            name="⭐ Avg Rating",
            value=str(avg_rating),
            inline=True
        )

        embed.add_field(
            name="🧪 Sample",
            value=str(sample),
            inline=True
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

        await message.channel.send(
            embed=embed
        )

# =====================================================
# RUN BOT
# =====================================================

client.run(DISCORD_TOKEN)
