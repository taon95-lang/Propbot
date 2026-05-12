import os
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

@bot.event
async def on_ready():

    print("BOT ONLINE SUCCESS")

@bot.command()
async def test(ctx):

    print("TEST COMMAND HIT")

    await ctx.send(
        "TEST WORKING"
    )

TOKEN = os.getenv(
    "DISCORD_TOKEN"
)

bot.run(TOKEN)
