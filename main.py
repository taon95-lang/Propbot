import os
import discord
import asyncio
from discord.ext import commands
from scraper import get_player_info

# =========================================================
# DISCORD SETUP
# =========================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =========================================================
# READY EVENT
# =========================================================

@bot.event
async def on_ready():

    print(
        f"✅ Logged in as {bot.user}",
        flush=True
    )

# =========================================================
# SCAN COMMAND
# =========================================================

@bot.command()
async def scan(
    ctx,
    player=None,
    line=None,
    opponent="N/A"
):

    # =====================================================
    # VALIDATION
    # =====================================================

    if not player or not line:

        return await ctx.send(
            "❌ Usage: `!scan player line opponent`"
        )

    # =====================================================
    # START MESSAGE
    # =====================================================

    msg = await ctx.send(
        f"🔎 Scanning {player}..."
    )

    async with ctx.typing():

        try:

            # =================================================
            # LINE
            # =================================================

            line_float = float(line)

            # =================================================
            # RUN SCRAPER
            # =================================================

            data = await asyncio.to_thread(
                get_player_info,
                player,
                line_float,
                opponent
            )

            # =================================================
            # NO DATA
            # =================================================

            if not data:

                return await msg.edit(
                    content="❌ No player data found"
                )

            # =================================================
            # STRING FAILS
            # =================================================

            if isinstance(data, str):

                return await msg.edit(
                    content=f"❌ {data}"
                )

            # =================================================
            # SAFE GETTERS
            # =================================================

            player_name = data.get(
                "player",
                player
            )

            avg = data.get(
                "avg",
                0
            )

            avg_hs = data.get(
                "avg_hs",
                0
            )

            avg_rating = data.get(
                "avg_rating",
                0
            )

            sample = data.get(
                "sample",
                0
            )

            edge = data.get(
                "edge",
                0
            )

            hit_rate = data.get(
                "hit_rate",
                0
            )

            bet = data.get(
                "Bet recommendation",
                "NO BET"
            )

            maps = data.get(
                "maps",
                []
            )

            recent_totals = data.get(
                "Recent totals",
                []
            )

            # =================================================
            # RECENT MAPS
            # =================================================

            recent_maps = ", ".join([

                str(m.get("kills"))

                for m in maps[:10]

                if m.get("kills") is not None

            ])

            if not recent_maps:

                recent_maps = "No maps found"

            # =================================================
            # COLOR
            # =================================================

            if "OVER" in bet:

                color = 0x00ff00

            elif "UNDER" in bet:

                color = 0xff0000

            else:

                color = 0x808080

            # =================================================
            # EMBED
            # =================================================

            embed = discord.Embed(

                title=(
                    f"🎯 "
                    f"{player_name.upper()} "
                    f"PROP SCAN"
                ),

                color=color
            )

            # =================================================
            # BASIC INFO
            # =================================================

            embed.add_field(
                name="👤 Player",
                value=player_name,
                inline=True
            )

            embed.add_field(
                name="⚔️ Opponent",
                value=opponent,
                inline=True
            )

            embed.add_field(
                name="🎯 Line",
                value=line,
                inline=True
            )

            # =================================================
            # STATS
            # =================================================

            embed.add_field(
                name="📊 Avg Kills",
                value=avg,
                inline=True
            )

            embed.add_field(
                name="📈 Edge",
                value=edge,
                inline=True
            )

            embed.add_field(
                name="🔥 Hit Rate",
                value=f"{hit_rate}%",
                inline=True
            )

            embed.add_field(
                name="💥 Avg HS",
                value=avg_hs,
                inline=True
            )

            embed.add_field(
                name="⭐ Avg Rating",
                value=avg_rating,
                inline=True
            )

            embed.add_field(
                name="🧪 Sample",
                value=sample,
                inline=True
            )

            # =================================================
            # BET
            # =================================================

            embed.add_field(
                name="💰 Bet Recommendation",
                value=bet,
                inline=False
            )

            # =================================================
            # RECENT MAPS
            # =================================================

            embed.add_field(
                name="📋 Recent Maps",
                value=recent_maps,
                inline=False
            )

            # =================================================
            # RECENT TOTALS
            # =================================================

            embed.add_field(
                name="📦 Recent Totals",
                value=str(recent_totals),
                inline=False
            )

            # =================================================
            # FOOTER
            # =================================================

            embed.set_footer(
                text=(
                    "HLTV Gold Scan Engine "
                    "• Maps 1-2 Only"
                )
            )

            # =================================================
            # SEND
            # =================================================

            await msg.edit(
                content=None,
                embed=embed
            )

        # =====================================================
        # INVALID LINE
        # =====================================================

        except ValueError:

            await msg.edit(

                content=(
                    "❌ Invalid line. "
                    "Use decimal format "
                    "(example: 28.5)"
                )
            )

        # =====================================================
        # CRASH LOGGER
        # =====================================================

        except Exception as e:

            print(
                f"SCAN ERROR: {e}",
                flush=True
            )

            await msg.edit(
                content=(
                    f"❌ Scan crashed: {e}"
                )
            )

# =========================================================
# RUN BOT
# =========================================================

bot.run(
    os.getenv("DISCORD_TOKEN")
)
