import os
import discord
from discord.ext import commands

from scraper import get_player_data

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

@bot.event
async def on_ready():

    print("BOT ONLINE")

@bot.command()
async def grade(ctx, player=None, line=None, opponent=None):

    print("COMMAND HIT")

    await ctx.send(
        f"Testing {player}"
    )

    print("RUNNING GET_PLAYER_DATA")

    data = get_player_data(player)

    print("SCRAPER RETURN:", data)

    if not data:

        await ctx.send(
            "❌ No player data found."
        )

        return

    await ctx.send(data)

TOKEN = os.getenv(
    "DISCORD_TOKEN"
)

bot.run(TOKEN)
