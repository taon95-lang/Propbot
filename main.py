import os
import re
import time
import asyncio
import statistics as stats
from urllib.parse import quote

import discord
from discord.ext import commands

# =========================================================
# DISCORD
# =========================================================

GREEN = 0x35D39B
RED = 0xE24A68
BRAND = 0xF0A51A
PANEL = 0x111827
MUTED = 0x64748B

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =========================================================
# SAFE HELPERS
# =========================================================

def safe_str(value, default="N/A"):

    try:

        if value in [None, "", [], {}, "N/A"]:
            return default

        return str(value).strip()

    except Exception:
        return default


def num(value, default=0.0):

    try:

        if value in [None, "", "N/A", "-", "--"]:
            return default

        return float(
            str(value)
            .replace("%", "")
            .replace(",", "")
            .strip()
        )

    except Exception:
        return default


def safe_list(value, default=None):

    if default is None:
        default = []

    if isinstance(value, list):
        return value

    return default


def safe_dict(value, default=None):

    if default is None:
        default = {}

    if isinstance(value, dict):
        return value

    return default


def trim_lines(lines, limit=950):

    lines = safe_list(lines)

    if not lines:
        return "N/A"

    out = []
    total = 0

    for line in lines:

        line = safe_str(line)

        if total + len(line) >= limit:
            break

        out.append(line)
        total += len(line)

    return "\n".join(out)


def bar(score, total=10):

    try:

        score = max(
            0,
            min(total, round(float(score)))
        )

        return (
            "▰" * int(score) +
            "▱" * (total - int(score))
        )

    except Exception:
        return "▱" * total


# =========================================================
# MOCK DATA
# =========================================================

def get_player_info(player_name, line=0.0, opponent="N/A"):

    recent_totals = [33, 23, 19, 20, 32, 26, 37, 28, 24, 26]
    recent_hs = [11, 8, 6, 6, 11, 8, 12, 9, 8, 9]

    raw_maps = [
        {
            "map_name": "Ancient",
            "kills": 18,
            "deaths": 14,
            "headshots": 6,
            "rounds": 13,
            "opponent": "UNKNOWN"
        },
        {
            "map_name": "Dust2",
            "kills": 15,
            "deaths": 16,
            "headshots": 5,
            "rounds": 13,
            "opponent": "UNKNOWN"
        },
        {
            "map_name": "Mirage",
            "kills": 16,
            "deaths": 15,
            "headshots": 5,
            "rounds": 13,
            "opponent": "UNKNOWN"
        }
    ]

    avg = round(stats.mean(recent_totals), 1)
    median = round(stats.median(recent_totals), 1)

    projection = round(
        (
            stats.mean(recent_totals[:5]) * 0.6
        ) +
        (
            stats.mean(recent_totals[5:]) * 0.4
        ),
        1
    )

    hit_rate = round(
        (
            sum(1 for x in recent_totals if x > line)
            / len(recent_totals)
        ) * 100,
        1
    )

    if projection > line and hit_rate >= 60:

        side = "OVER"
        grade = "8.4/10 ✅ STRONG PLAY"

    elif projection < line and hit_rate <= 40:

        side = "UNDER"
        grade = "7.8/10 ✅ STRONG PLAY"

    else:

        side = "NO BET"
        grade = "5.5/10 ⚖️ SMALL EDGE"

    return {

        "Player": player_name,
        "Role": "Support / IGL",
        "Team": "Sample Team",

        "Rating 3.0": "1.05",

        "KPR": "1.13",
        "DPR": "1.07",
        "ADR": "84.1",
        "KAST": "72.5%",
        "Impact": "1.23",

        "Recent average": avg,
        "Recent median": median,
        "Recent projection": projection,

        "Recent Totals (M1+M2 Combined)": recent_totals,
        "Recent HS Totals (M1+M2)": recent_hs,

        "Recent HS Average": round(stats.mean(recent_hs), 1),

        "Recent HS %": "32.8%",

        "Hit rate": f"{hit_rate}%",

        "Simulated mean": avg,
        "Simulated median": median,

        "Std Dev": round(
            stats.pstdev(recent_totals),
            1
        ),

        "25th percentile": min(recent_totals),
        "75th percentile": max(recent_totals),

        "Over probability": f"{hit_rate}%",
        "Under probability": f"{100-hit_rate}%",

        "Edge vs line": f"{round(hit_rate-50,1)}%",

        "Final grade": grade,
        "Bet recommendation": side,

        "Team ranking": "#8",
        "Opponent ranking": "#21",

        "Match odds": "1.63",
        "Moneyline": "1.63",
        "Moneyline american": "-158",

        "Similar teams": "Vs Top 30: 1.14 rating over 18 maps",

        "Per-map averages": {
            "Ancient": {
                "avg_kills": 15.4,
                "avg_kpr": 1.119,
                "sample_size": 16
            },
            "Dust2": {
                "avg_kills": 14.6,
                "avg_kpr": 1.079,
                "sample_size": 24
            },
            "Mirage": {
                "avg_kills": 14.9,
                "avg_kpr": 1.123,
                "sample_size": 25
            }
        },

        "H2H Data": {
            "h2h_sample_size": 1,
            "h2h_avg_kills": 21,
            "h2h_avg_headshots": 8,
            "h2h_note": "1 recent map"
        },

        "Likely maps": {
            "Map 1": "Overpass",
            "Map 2": "Ancient",
            "Map 3": "Mirage"
        },

        "Veto": [
            "Team A picked Mirage",
            "Team B picked Ancient"
        ],

        "Paired series rows": [
            {
                "opponent": "UNKNOWN",
                "date": "23/05/26",
                "kills": recent_totals[i],
                "headshots": recent_hs[i],
                "rounds": 26,
                "map1": "Dust2",
                "map2": "Ancient"
            }
            for i in range(len(recent_totals))
        ],

        "Raw maps": raw_maps,
    }

# =========================================================
# EMBEDS
# =========================================================

def score_num(data):

    try:

        grade = safe_str(
            data.get("Final grade", "0")
        )

        match = re.search(
            r"([0-9]+(?:\.[0-9]+)?)",
            grade
        )

        if not match:
            return 0.0

        return float(match.group(1))

    except Exception:
        return 0.0


def side_color(data):

    rec = safe_str(
        data.get("Bet recommendation", "NO BET")
    ).upper()

    if "OVER" in rec:
        return "OVER", GREEN

    if "UNDER" in rec:
        return "UNDER", RED

    return "NO BET", MUTED


def grade_embed(data, line, opponent):

    side, color = side_color(data)
    score = score_num(data)

    recent = []

    for x in safe_list(
        data.get("Recent Totals (M1+M2 Combined)")
    ):

        emoji = "🟩" if x > line else "🟥"
        recent.append(f"{emoji}{x}")

    e = discord.Embed(color=color)

    e.add_field(
        name="☠️ Grade",
        value=(
            f"**Side:** `{side}`\n"
            f"**Grade:** `{safe_str(data.get('Final grade'))}`\n"
            f"{bar(score)}"
        ),
        inline=False
    )

    e.add_field(
        name="📊 Projection",
        value=(
            f"**Average:** `{safe_str(data.get('Recent average'))}`\n"
            f"**Median:** `{safe_str(data.get('Recent median'))}`\n"
            f"**Projection:** `{safe_str(data.get('Recent projection'))}`\n"
            f"**Hit rate:** `{safe_str(data.get('Hit rate'))}`"
        ),
        inline=False
    )

    e.add_field(
        name="📈 Recent",
        value=" ".join(recent),
        inline=False
    )

    return e


def data_embed(data, line, opponent):

    e = discord.Embed(color=BRAND)

    raw = []

    for row in safe_list(data.get("Raw maps")):

        row = safe_dict(row)

        raw.append(
            f"`{safe_str(row.get('map_name'))} "
            f"{safe_str(row.get('kills'))}-"
            f"{safe_str(row.get('deaths'))} "
            f"HS {safe_str(row.get('headshots'))}`"
        )

    e.add_field(
        name="📋 RAW MAP DATA",
        value=trim_lines(raw),
        inline=False
    )

    return e


def context_embed(data, line, opponent):

    e = discord.Embed(color=PANEL)

    e.add_field(
        name="🎮 CONTEXT",
        value=(
            f"**Role:** `{safe_str(data.get('Role'))}`\n"
            f"**Odds:** `{safe_str(data.get('Match odds'))}`\n"
            f"**Team Rank:** `{safe_str(data.get('Team ranking'))}`"
        ),
        inline=False
    )

    return e

# =========================================================
# VIEW
# =========================================================

class PropView(discord.ui.View):

    def __init__(self, data, line, opponent):

        super().__init__(timeout=1800)

        self.data = data
        self.line = line
        self.opponent = opponent

    async def swap(self, interaction, embed):

        try:

            if interaction.response.is_done():

                await interaction.edit_original_response(
                    embed=embed,
                    view=self
                )

            else:

                await interaction.response.edit_message(
                    embed=embed,
                    view=self
                )

        except Exception as e:
            print(f"VIEW ERROR: {e}")

    @discord.ui.button(
        label="GRADE",
        style=discord.ButtonStyle.primary,
        emoji="☠️"
    )
    async def grade_btn(self, interaction, button):

        await self.swap(
            interaction,
            grade_embed(
                self.data,
                self.line,
                self.opponent
            )
        )

    @discord.ui.button(
        label="DATA",
        style=discord.ButtonStyle.secondary,
        emoji="📊"
    )
    async def data_btn(self, interaction, button):

        await self.swap(
            interaction,
            data_embed(
                self.data,
                self.line,
                self.opponent
            )
        )

    @discord.ui.button(
        label="CONTEXT",
        style=discord.ButtonStyle.secondary,
        emoji="🧠"
    )
    async def context_btn(self, interaction, button):

        await self.swap(
            interaction,
            context_embed(
                self.data,
                self.line,
                self.opponent
            )
        )

# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

# =========================================================
# COMMAND
# =========================================================

@bot.command()
async def scan(ctx, player=None, line=None, *, opponent="N/A"):

    if not player or not line:

        return await ctx.send(
            "❌ Usage: !scan player line opponent"
        )

    try:
        line_val = float(line)

    except Exception:

        return await ctx.send(
            "❌ Invalid line."
        )

    loading = await ctx.send(
        f"🔎 Loading exact HLTV grade for `{player}`..."
    )

    try:

        data = await asyncio.to_thread(
            get_player_info,
            player,
            line_val,
            opponent
        )

        embed = grade_embed(
            data,
            line_val,
            opponent
        )

        view = PropView(
            data,
            line_val,
            opponent
        )

        await loading.edit(
            content=None,
            embed=embed,
            view=view
        )

    except Exception as exc:

        await loading.edit(
            content=f"❌ Scan crashed: {exc}"
        )

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    token = os.getenv("DISCORD_TOKEN")

    if not token:
        raise SystemExit("❌ DISCORD_TOKEN missing.")

    bot.run(token)
