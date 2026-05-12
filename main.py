import os
import discord
from discord.ext import commands

from scraper import search_player

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

@bot.event
async def on_ready():

    print(f"Logged in as {bot.user}")

@bot.command()
async def lookup(ctx, player=None):

    result = search_player(player)

    if not result:

        await ctx.send(
            "NO PLAYER"
        )

        return

    pid, slug, display = result

    await ctx.send(
        f"FOUND: {display} ({pid})"
    )
    @bot.command()
async def lookup(ctx, player=None):

    result = search_player(player)

    if not result:

        await ctx.send(
            "NO PLAYER"
        )

        return

    pid, slug, display = result

    await ctx.send(
        f"FOUND: {display} ({pid})"
    )

TOKEN = os.getenv(
    "DISCORD_TOKEN"
)

bot.run(TOKEN)
