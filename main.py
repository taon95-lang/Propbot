import os
import asyncio
import discord
from discord.ext import commands
from discord import app_commands

from scraper import get_player_info, get_headshot_info

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
intents = discord.Intents.default()
intents.message_content = True

class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    async def on_ready(self):
        print(f"{self.user} is now running!")
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

bot = MyBot(command_prefix="!", intents=intents)

# Utility to pick fields from info safely
def _pick(info, key, fallback_key=None, default="N/A"):
    val = info.get(key)
    if val is None and fallback_key:
        val = info.get(fallback_key)
    return val if val is not None else default

# Formatting list outputs
def _fmt_list(values, limit=10):
    if not values:
        return "No sample"
    return ", ".join(str(x) for x in values[:limit])

@bot.tree.command(description="Get over/under player Kills projection and stats")
async def player(interaction: discord.Interaction, player: str, line: float, opponent: str = "N/A"):
    await interaction.response.defer()
    info = get_player_info(player, line, opponent)
    if "error" in info:
        await interaction.followup.send(info["error"])
        return

    desc = (
        f"**Rating 3.0:** {_pick(info, 'Rating 3.0')}\n"
        f"**Role:** {_pick(info, 'Role')}\n"
        f"**Match Odds:** {_pick(info, 'Match odds')}"
    )

    embed = discord.Embed(
        title=f"{player.title()} vs {opponent.title()} | Kills O/U {line}",
        description=desc,
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Header",
        value=(
            f"Rating 3.0: {_pick(info, 'Rating 3.0')}\n"
            f"Role: {_pick(info, 'Role')}\n"
            f"Team rank: {_pick(info, 'Team ranking')}\n"
            f"Odds: {_pick(info, 'Match odds')}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Quick view",
        value=(
            f"Recent avg: {_pick(info, 'Recent average')}\n"
            f"Recent median: {_pick(info, 'Recent median')}\n"
            f"Projection: {_pick(info, 'Projected kills', 'Recent projection')}\n"
            f"Hit rate: {_pick(info, 'Hit rate')}\n"
            f"Over/Under: {_pick(info, 'Over probability')} / {_pick(info, 'Under probability')}\n"
            f"Edge: {_pick(info, 'Edge vs line')}\n"
            f"Recommendation: {_pick(info, 'Bet recommendation')}\n"
            f"Grade: {_pick(info, 'Final grade')}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Recent exact totals",
        value=_fmt_list(_pick(info, "Recent Totals (M1+M2 Combined)", default=[])),
        inline=False,
    )
    embed.add_field(
        name="Analytics",
        value=(
            f"Final Grade: {_pick(info, 'Final grade')}\n"
            f"Pros: {_pick(info, 'Role')} - {_pick(info, 'Role note')}\n"
            f"Cons: {_pick(info, 'Player')} has weaker performance in other areas."
        ),
        inline=False,
    )
    embed.set_footer(text="Role is derived from HLTV profile buckets.")
    await interaction.followup.send(embed=embed)

@bot.tree.command(description="Get over/under player Headshots projection and stats")
async def headshots(interaction: discord.Interaction, player: str, line: float, opponent: str = "N/A"):
    await interaction.response.defer()
    info = get_headshot_info(player, line, opponent)
    if "error" in info:
        await interaction.followup.send(info["error"])
        return

    desc = (
        f"**Rating 3.0:** {_pick(info, 'Rating 3.0')}\n"
        f"**Role:** {_pick(info, 'Role')}\n"
        f"**Match Odds:** {_pick(info, 'Match odds')}\n"
        f"**HS %:** {_pick(info, 'HS %')}"
    )
    embed = discord.Embed(
        title=f"{player.title()} vs {opponent.title()} | Headshots O/U {line}",
        description=desc,
        color=discord.Color.purple(),
    )
    embed.add_field(
        name="Header",
        value=(
            f"Rating 3.0: {_pick(info, 'Rating 3.0')}\n"
            f"Role: {_pick(info, 'Role')}\n"
            f"Team rank: {_pick(info, 'Team ranking')}\n"
            f"Odds: {_pick(info, 'Match odds')}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Quick view",
        value=(
            f"Recent HS avg: {_pick(info, 'Recent HS Average')}\n"
            f"Recent HS median: {_pick(info, 'Recent HS Median')}\n"
            f"Projection: {_pick(info, 'Projected headshots', 'Recent projection')}\n"
            f"Hit rate: {_pick(info, 'Hit rate')}\n"
            f"Over/Under: {_pick(info, 'Over probability')} / {_pick(info, 'Under probability')}\n"
            f"Edge: {_pick(info, 'Edge vs line')}\n"
            f"Recommendation: {_pick(info, 'Bet recommendation')}\n"
            f"Grade: {_pick(info, 'Final grade')}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Recent exact HS totals",
        value=_fmt_list(_pick(info, "Recent HS Totals (M1+M2)", default=[])),
        inline=False,
    )
    embed.add_field(
        name="Analytics",
        value=(
            f"Final Grade: {_pick(info, 'Final grade')}\n"
            f"Pros: {_pick(info, 'Role')} - {_pick(info, 'Role note')}\n"
            f"Cons: {_pick(info, 'Player')} has weaker performance in other areas."
        ),
        inline=False,
    )
    embed.set_footer(text="Role is derived from HLTV profile buckets.")
    await interaction.followup.send(embed=embed)

@bot.tree.command(description="Scan multiple players and get prop recommendations")
async def scan(interaction: discord.Interaction, players: str, lines: str, opponent: str = "N/A"):
    """
    Scan multiple players at once.
    Format: /scan players:s1mple,niko,device lines:25.5,24.2,23.0 opponent:faze
    """
    await interaction.response.defer()
    
    player_list = [p.strip() for p in players.split(",")]
    line_list = [float(l.strip()) for l in lines.split(",")]
    
    if len(player_list) != len(line_list):
        await interaction.followup.send("❌ Number of players must match number of lines!")
        return
    
    embeds = []
    for player_name, line in zip(player_list, line_list):
        info = get_player_info(player_name, line, opponent)
        if "error" in info:
            continue
        
        embed = discord.Embed(
            title=f"{player_name.title()} | Kills O/U {line}",
            color=discord.Color.green() if info.get("Bet recommendation") == "OVER" else discord.Color.red() if info.get("Bet recommendation") == "UNDER" else discord.Color.greyple(),
        )
        embed.add_field(
            name="Summary",
            value=(
                f"Rec: **{_pick(info, 'Bet recommendation')}**\n"
                f"Grade: **{_pick(info, 'Final grade')}**\n"
                f"Avg: {_pick(info, 'Recent average')}\n"
                f"Hit Rate: {_pick(info, 'Hit rate')}\n"
                f"Edge: {_pick(info, 'Edge vs line')}"
            ),
            inline=False,
        )
        embeds.append(embed)
    
    if not embeds:
        await interaction.followup.send("❌ No valid players found!")
        return
    
    # Send embeds (Discord allows up to 10 per message)
    for embed in embeds[:10]:
        await interaction.followup.send(embed=embed)

if __name__ == "__main__":
    bot.run(TOKEN)
