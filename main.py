import discord
from discord.ext import commands
from discord import ui
from scraper import get_player_info, get_headshot_info
import os
import sys
import asyncio

def _pick(info, key, default="N/A"):
    val = info.get(key, None)
    return default if val is None else val

def _truncate(text, length=1024):
    # ensure embed field limits
    if text is None:
        return "N/A"
    if len(text) > length:
        return text[: length - 3] + "..."
    return text

def _fmt_list(items):
    items = items or []
    return ", ".join(str(x) for x in items) if items else "N/A"

class ScanButtons(ui.View):
    def __init__(self, player, line, opponent, info, headshots=False):
        super().__init__(timeout=None)
        self.player = player
        self.line = line
        self.opponent = opponent
        self.info = info
        self.headshots = headshots

    @ui.button(label="GRADE", style=discord.ButtonStyle.primary)
    async def grade_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = build_grade_embed(self.player, self.line, self.info, headshots=self.headshots)
        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="DATA", style=discord.ButtonStyle.secondary)
    async def data_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = build_data_embed(self.player, self.line, self.opponent, self.info)
        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="CONTEXT", style=discord.ButtonStyle.secondary)
    async def context_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = build_context_embed(self.player, self.opponent, self.info)
        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="HEADSHOTS", style=discord.ButtonStyle.secondary)
    async def headshot_button(self, interaction: discord.Interaction, button: ui.Button):
        # Re-run with headshots data
        info_hs = await asyncio.to_thread(get_headshot_info, self.player, float(self.line), self.opponent)
        embed = build_scan_embed(self.player, self.line, self.opponent, info_hs)
        await interaction.response.edit_message(embed=embed, view=self)

def build_scan_embed(player, line, opponent, info):
    resolved_opponent = _pick(info, "Opponent", default=opponent.title() if opponent else "N/A")
    desc = "Maps 1–2 only • HLTV exact sample + profile/stats context"
    embed = discord.Embed(title=f"{player.title()} vs {resolved_opponent} | Kills O/U {line}",
                          description=desc, color=discord.Color.gold())
    embed.add_field(
        name="Projection / edge",
        value=_truncate(
            (
                f"Line: {line}\n"
                f"Projection: {_pick(info, 'Projected kills')}\n"
                f"Recent avg: {_pick(info, 'Recent average')}\n"
                f"Recent median: {_pick(info, 'Recent median')}\n"
                f"Over probability: {_pick(info, 'Over probability')}\n"
                f"Under probability: {_pick(info, 'Under probability')}\n"
                f"Hit rate: {_pick(info, 'Hit rate')}\n"
                f"Edge: {_pick(info, 'Edge vs line')}\n"
                f"Recommendation: {_pick(info, 'Bet recommendation')}\n"
                f"Grade: {_pick(info, 'Final grade')}\n"
            )
        ),
        inline=False,
    )
    h2h_rows = info.get("H2H rows", [])
    if h2h_rows and h2h_rows != "N/A":
        embed.add_field(
            name="H2H rows",
            value=_truncate("\n".join(f"- {r}" for r in h2h_rows)),
            inline=False,
        )
    embed.add_field(
        name="Profile / stats",
        value=_truncate(
            (
                f"Recent kills: {_pick(info, 'Recent average')} (maps 1&2)\n"
                f"All-time KPR: {_pick(info, 'KPR')}\n"
                f"All-time DPR: {_pick(info, 'DPR')}\n"
                f"KAST: {_pick(info, 'KAST')}\n"
                f"Impact: {_pick(info, 'Impact')}\n"
                f"Team rank: {_pick(info, 'Team ranking')}\n"
                f"Opp rank: {_pick(info, 'Opponent ranking')}\n"
                f"Match context: {_pick(info, 'Match context', default='N/A')}\n"
            )
        ),
        inline=False,
    )
    return embed

@bot.command(name="scan")
async def scan(ctx, player: str, line: str, opponent: str = None):
    async with ctx.typing():
        try:
            info = await asyncio.to_thread(get_player_info, player, float(line), opponent)
            if "error" in info:
                return await ctx.send(f"❌ {info['error']}")

            view = ScanButtons(player, float(line), opponent, info, headshots=False)
            embed = build_scan_embed(player, float(line), opponent, info)
            await ctx.send(embed=embed, view=view)
        except Exception as e:
            await ctx.send(f"⚠️ An internal system error occurred: {e}")

@bot.event
async def on_ready():
    print(f"✅ Bot successfully logged in as {bot.user}")

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ CRITICAL ERROR: 'DISCORD_BOT_TOKEN' environment variable is missing!", file=sys.stderr)
        sys.exit(1)
    try:
        bot.run(token)
    except Exception as e:
        print(f"❌ CRITICAL STARTUP ERROR: {e}", file=sys.stderr)
        sys.exit(1)
