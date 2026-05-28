import discord
from discord.ext import commands
from discord import ui
from scraper import get_player_info, get_headshot_info
import os
import sys

def _pick(info, key, default="N/A"):
    val = info.get(key, None)
    return default if val is None else val

def _truncate(text, length=1024):
    # ensure embed field limits
    if text is None:
        return "N/A"
    s = str(text)
    return s if len(s) <= length else s[:length-3] + "..."

def _fmt_bullets(items, limit=None):
    items = items or []
    lines = [f"- {item}" for item in items[:limit]] if limit else [f"- {item}" for item in items]
    return "\n".join(lines) or "N/A"

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

    @ui.button(label="RAW", style=discord.ButtonStyle.secondary)
    async def raw_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = build_raw_embed(self.player, self.info)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="ANALYTICS", style=discord.ButtonStyle.secondary)
    async def analytics_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = build_analytics_embed(self.player, self.opponent, self.info)
        await interaction.response.edit_message(embed=embed, view=self)


def build_scan_embed(player, line, opponent, info):
    resolved_opponent = _pick(info, "Opponent", default=opponent.title())
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
                f"Mispriced: {_pick(info, 'Mispriced or not')}"
            )
        ),
        inline=False,
    )
    embed.add_field(
        name="Round-based scenarios",
        value=_truncate(
            (
                f"Pistol: {info.get('pistol_rounds', 'N/A')} rounds → "
                f"{info.get('pistol_kills', 'N/A')} K\n"
                f"Short: {info.get('short_rounds', 'N/A')} rounds → "
                f"{info.get('short_kills', 'N/A')} K\n"
                f"Normal: {info.get('normal_rounds', 'N/A')} rounds → "
                f"{info.get('normal_kills', 'N/A')} K\n"
                f"Long: {info.get('long_rounds', 'N/A')} rounds → "
                f"{info.get('long_kills', 'N/A')} K"
            )
        ),
        inline=False,
    )
    # Headshot profile field (only relevant for HS mode)
    if False:
        embed.add_field(
            name="Headshot profile",
            value=_truncate(
                (
                    f"Recent HS%: {_pick(info, 'Recent HS %')}\n"
                    f"All-time HS%: {_pick(info, 'All-time profile HS %')}\n"
                    f"Recent totals: {_fmt_list(_pick(info, 'Recent HS Totals (M1+M2)', default=[]))}"
                )
            ),
            inline=False,
        )
    return embed


def build_context_embed(player, opponent, info):
    resolved_opponent = _pick(info, "Opponent", default=opponent.title())
    h2h = info.get("H2H Data", {})
    embed = discord.Embed(title=f"{player.title()} vs {resolved_opponent} | Context",
                          description="Match context pulled from HLTV match, team-map, and player pages",
                          color=discord.Color.orange())
    embed.add_field(
        name="Context",
        value=_truncate(
            (
                f"Role: {_pick(info, 'Role')}\n"
                f"Team: {_pick(info, 'Team')}\n"
                f"Team rank: {_pick(info, 'Team ranking')}\n"
                f"Opponent rank: {_pick(info, 'Opponent ranking')}\n"
                f"Odds (Thunderpick): {_pick(info, 'Thunderpick odds')}\n"
                f"Public pick: {_pick(info, 'Public pick')}\n"
                f"H2H summary: {_pick(info, 'H2H summary')}"
            )
        ),
        inline=False,
    )
    # Game pace & blowout fields
    embed.add_field(
        name="Game pace",
        value=_truncate(
            (
                f"Pace model: {_pick(info, 'Pace model')}\n"
                f"Map pace: {_pick(info, 'Map pace')}\n"
                f"Blowout risk: {_pick(info, 'Blowout risk')}\n"
                f"Overtime probability: {_pick(info, 'Overtime probability')}"
            )
        ),
        inline=False,
    )
    # Likely maps and map weighting
    embed.add_field(
        name="Likely maps",
        value=_truncate(_fmt_list(_pick(info, "Likely maps", default=[]))),
        inline=False,
    )
    embed.add_field(
        name="Map weighting",
        value=_truncate(
            (
                f"Map weighted projection: {_pick(info, 'Map weighted projection')}\n"
                f"Map weighted KPR: {_pick(info, 'Map weighted KPR')}\n"
                f"True map weighting: {_pick(info, 'True map weighting')}"
            )
        ),
        inline=False,
    )
    embed.add_field(
        name="Multi-kill pressure",
        value=_truncate(
            (
                f"Multi-kill pressure: {_pick(info, 'Multi-kill pressure')}\n"
                f"2K/3K frequency: {_pick(info, '2K/3K frequency')}\n"
                f"Clutch conversion: {_pick(info, 'Clutch conversion')}\n"
                f"Eco farming: {_pick(info, 'Eco farming')}\n"
                f"Anti-eco padding: {_pick(info, 'Anti-eco padding')}"
            )
        ),
        inline=False,
    )
    embed.add_field(
        name="Team pros",
        value=_fmt_bullets(_pick(info, "Team pros", default=[])),
        inline=True,
    )
    embed.add_field(
        name="Team cons",
        value=_fmt_bullets(_pick(info, "Team cons", default=[])),
        inline=True,
    )
    embed.add_field(
        name=f"{resolved_opponent} pros",
        value=_fmt_bullets(_pick(info, "Opponent pros", default=[])),
        inline=True,
    )
    embed.add_field(
        name=f"{resolved_opponent} cons",
        value=_fmt_bullets(_pick(info, "Opponent cons", default=[])),
        inline=True,
    )
    embed.add_field(
        name="H2H rows",
        value=_truncate(_fmt_list(h2h.get("h2h_rows", []))),
        inline=False,
    )
    return embed


def build_data_embed(player, line, opponent, info):
    resolved_opponent = _pick(info, "Opponent", default=opponent.title())
    # Profile buckets and recent stats
    embed = discord.Embed(title=f"{player.title()} | Data",
                          description="Player profile buckets, recent filtered stats, and raw match data",
                          color=discord.Color.green())
    embed.add_field(
        name="Profile buckets",
        value=(
            f"Firepower: {_pick(info, 'Firepower')}\n"
            f"Entrying: {_pick(info, 'Entrying')}\n"
            f"Trading: {_pick(info, 'Trading')}\n"
            f"Opening: {_pick(info, 'Opening')}\n"
            f"Clutching: {_pick(info, 'Clutching')}\n"
            f"Sniping: {_pick(info, 'Sniping')}\n"
            f"Utility: {_pick(info, 'Utility')}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Recent filtered stats",
        value=(
            f"KPR: {_pick(info, 'Recent KPR')}\n"
            f"DPR: {_pick(info, 'Recent DPR')}\n"
            f"ADR: {_pick(info, 'Recent ADR')}\n"
            f"KAST: {_pick(info, 'KAST')}\n"
            f"Impact: {_pick(info, 'Impact rating')}\n"
            f"Round swing: {_pick(info, 'Round swing')}\n"
            f"HS%: {_pick(info, 'HS %')}\n"
            f"Opening KPR: {_pick(info, 'Opening KPR')}\n"
            f"Trade KPR: {_pick(info, 'Trade KPR')}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Opponent buckets",
        value=(
            f"Top 5: {_pick(info, 'Vs Top 5 rating')}\n"
            f"Top 10: {_pick(info, 'Vs Top 10 rating')}\n"
            f"Top 20: {_pick(info, 'Vs Top 20 rating')}\n"
            f"Top 30: {_pick(info, 'Vs Top 30 rating')}\n"
            f"Top 50: {_pick(info, 'Vs Top 50 rating')}\n"
            f"Similar teams: {_pick(info, 'Similar teams')}\n"
            f"Similar teams rating: {_pick(info, 'Similar teams rating')}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Exact paired series sample",
        value=_truncate(_fmt_list(_pick(info, "Exact series sample", default=[]))),
        inline=False,
    )
    embed.add_field(
        name="Per-map exact averages",
        value=_truncate(_fmt_list(_pick(info, "Per-map averages", default=[]))),
        inline=False,
    )
    embed.add_field(
        name="Paired series rows",
        value=_truncate(_fmt_list(_pick(info, "Paired series rows", default=[]))),
        inline=False,
    )
    embed.add_field(
        name="Raw maps",
        value=_truncate(_fmt_list(_pick(info, "Raw maps", default=[]))),
        inline=False,
    )
    return embed

def build_grade_embed(player, line, info, headshots=False):
    stat_name = "Headshots" if headshots else "Kills"
    embed = discord.Embed(
        title=f"{player.title()} | {stat_name} Grade",
        description="Maps 1–2 only, based on exact recent HLTV samples",
        color=discord.Color.purple(),
    )
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
                f"Mispriced: {_pick(info, 'Mispriced or not')}"
            )
        ),
        inline=False,
    )
    embed.add_field(
        name="Round-based scenarios",
        value=_truncate(
            (
                f"Pistol: {info.get('pistol_rounds', 'N/A')} rounds → "
                f"{info.get('pistol_kills', 'N/A')} K\n"
                f"Short: {info.get('short_rounds', 'N/A')} rounds → "
                f"{info.get('short_kills', 'N/A')} K\n"
                f"Normal: {info.get('normal_rounds', 'N/A')} rounds → "
                f"{info.get('normal_kills', 'N/A')} K\n"
                f"Long: {info.get('long_rounds', 'N/A')} rounds → "
                f"{info.get('long_kills', 'N/A')} K"
            )
        ),
        inline=False,
    )
    if not headshots:
        embed.add_field(
            name="Player pros",
            value=_fmt_bullets(_pick(info, "Player pros", default=[]), limit=5),
            inline=True,
        )
        embed.add_field(
            name="Player cons",
            value=_fmt_bullets(_pick(info, "Player cons", default=[]), limit=5),
            inline=True,
        )
    return embed

def build_analytics_embed(player, opponent, info):
    resolved_opponent = _pick(info, "Opponent", default=opponent.title())
    embed = discord.Embed(
        title=f"{player.title()} vs {resolved_opponent} | Analytics",
        color=discord.Color.blue(),
    )
    embed.add_field(name="Final grade", value=_pick(info, "Final grade"), inline=False)
    embed.add_field(name="Bet recommendation", value=_pick(info, "Bet recommendation"), inline=False)
    embed.add_field(name="Player report", value=_truncate(_pick(info, "Player report")), inline=False)
    embed.add_field(
        name="Team pros",
        value=_fmt_bullets(_pick(info, "Team pros", default=[]), limit=5),
        inline=True,
    )
    embed.add_field(
        name="Team cons",
        value=_fmt_bullets(_pick(info, "Team cons", default=[]), limit=5),
        inline=True,
    )
    embed.add_field(
        name=f"{resolved_opponent} pros",
        value=_fmt_bullets(_pick(info, "Opponent pros", default=[]), limit=5),
        inline=True,
    )
    embed.add_field(
        name=f"{resolved_opponent} cons",
        value=_fmt_bullets(_pick(info, "Opponent cons", default=[]), limit=5),
        inline=True,
    )
    return embed

def build_raw_embed(player, info):
    embed = discord.Embed(title=f"{player.title()} | Raw Diagnostic Data", color=discord.Color.dark_grey())
    embed.add_field(name="System Logging", value="Granular telemetry has been isolated securely below.", inline=False)
    return embed

@commands.command()
async def scan(ctx, player: str, line: str, opponent: str = None):
    info = get_player_info(player, float(line), opponent)
    if "error" in info:
        return await ctx.send(f"❌ {info['error']}")
    view = ScanButtons(player, float(line), opponent, info, headshots=False)
    embed = build_scan_embed(player, float(line), opponent, info)
    await ctx.send(embed=embed, view=view)

# ===================================================
# AUTOMATED APP RUNNER AND GATEWAY ORCHESTRATION
# ===================================================

# Configure application intent permissions
intents = discord.Intents.default()
intents.message_content = True  

# Build out core Command Framework runtime context 
bot = commands.Bot(command_prefix="!", intents=intents)

# Explicitly bind command tree configurations
bot.add_command(scan)

@bot.event
async def on_ready():
    print(f"✅ Bot successfully logged in as {bot.user}")

if __name__ == "__main__":
    # Pull gateway token safely out of environment variables
    token = os.environ.get("DISCORD_TOKEN")
    
    if not token:
        print("❌ CRITICAL ERROR: 'DISCORD_TOKEN' environment variable is missing!", file=sys.stderr)
        sys.exit(1)
        
    try:
        bot.run(token)
    except Exception as e:
        print(f"❌ CRITICAL STARTUP ERROR: {e}", file=sys.stderr)
        sys.exit(1)
