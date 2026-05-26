import os
import asyncio
from typing import Any, Dict, List
import discord
from discord.ext import commands

# AUDIT FIX: import the dedicated exact-HS scraper entrypoint as well.
from scraper import get_headshot_info, get_player_info

GREEN = 0x35D39B
RED = 0xE24A68
BRAND = 0xF0A51A
PANEL = 0x111827
MUTED = 0x64748B

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def score_num(data: Dict[str, Any]) -> float:
    try:
        return float(str(data.get("Final grade", "0")).split("/")[0])
    except Exception:
        return 0.0


def bar(score: float, total: int = 10) -> str:
    filled = max(0, min(total, int(round(score))))
    return "▰" * filled + "▱" * (total - filled)


def side_color(data: Dict[str, Any]):
    rec = str(data.get("Bet recommendation", "NO BET")).upper()
    if "OVER" in rec:
        return "OVER", GREEN
    if "UNDER" in rec:
        return "UNDER", RED
    return "NO BET", MUTED


def map_name(value: str) -> str:
    names = {
        "dust2": "Dust2",
        "mirage": "Mirage",
        "inferno": "Inferno",
        "nuke": "Nuke",
        "ancient": "Ancient",
        "anubis": "Anubis",
        "vertigo": "Vertigo",
        "overpass": "Overpass",
        "cache": "Cache",
        "train": "Train",
        "cobblestone": "Cobblestone",
        "tuscan": "Tuscan",
        "season": "Season",
    }
    return names.get(str(value).lower(), str(value).title())


def safe_field_value(value: str, max_chars: int = 1024) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 4] + "..."


def trim_lines(lines: List[str], limit: int = 1024) -> str:
    out = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > limit:
            break
        out.append(line)
        total += len(line) + 1
    return "\n".join(out) if out else "N/A"


def header(data: Dict[str, Any], line: float, opponent: str, prop: str) -> str:
    return (
        f"# CS2 Prop Grader\n"
        f"`Maps 1–2 only` • `HLTV direct stats` • `Bootstrap from exact totals`\n\n"
        f"## {data.get('Player', 'Player')} vs {opponent.title()} | `{prop} O/U {line}`\n"
        f"**Rating 3.0:** `{data.get('Rating 3.0', 'N/A')}` • "
        f"**Role:** `{data.get('Role', 'N/A')}` • "
        f"**Team rank:** `{data.get('Team ranking', 'N/A')}` • "
        f"**Odds:** `{data.get('Match odds', 'N/A')}`"
    )


def grade_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    side, color = side_color(data)
    score = score_num(data)
    totals = data.get("Recent Totals (M1+M2 Combined)", [])
    q25 = data.get("25th percentile", "N/A")
    q75 = data.get("75th percentile", "N/A")
    recent = " ".join(((" 🟢" if x > line else " 🔴") + f" `{x}`") for x in totals[:10]) or "No sample"
    scenarios = data.get("Scenarios", {}) or {}

    embed = discord.Embed(
        color=color,
        description=safe_field_value(header(data, line, opponent, "Kills")),
    )

    grade_value = (
        f"**Side:** `{side}`\n"
        f"**Grade:** `{data.get('Final grade', 'N/A')}`\n"
        f"{bar(score)}\n"
        f"**Misprice:** `{data.get('Mispriced or not', 'N/A')}`"
    )
    embed.add_field(name="🎯 Grade", value=safe_field_value(grade_value), inline=False)

    sample_value = (
        f"**Avg:** `{data.get('Recent average', 'N/A')}`\n"
        f"**Median:** `{data.get('Recent median', 'N/A')}`\n"
        f"**Projection:** `{data.get('Recent projection', 'N/A')}`\n"
        f"**Hit rate:** `{data.get('Hit rate', 'N/A')}`\n"
        f"**25th/75th:** `{q25}` / `{q75}`"
    )
    embed.add_field(name="📊 Exact sample", value=safe_field_value(sample_value), inline=True)

    bootstrap_value = (
        f"**Mean:** `{data.get('Simulated mean', 'N/A')}`\n"
        f"**Median:** `{data.get('Simulated median', 'N/A')}`\n"
        f"**Std Dev:** `{data.get('Std Dev', 'N/A')}`\n"
        f"**Over:** `{data.get('Over probability', 'N/A')}`\n"
        f"**Under:** `{data.get('Under probability', 'N/A')}`\n"
        f"**Edge:** `{data.get('Edge vs line', 'N/A')}`"
    )
    embed.add_field(name="📈 Bootstrap", value=safe_field_value(bootstrap_value), inline=True)

    embed.add_field(name="⭐ Recent totals", value=safe_field_value(recent), inline=False)

    scenarios_value = (
        f"**Short:** `{scenarios.get('short', {}).get('expected_kills', 'N/A')}` | "
        f"**Normal:** `{scenarios.get('normal', {}).get('expected_kills', 'N/A')}` | "
        f"**Long:** `{scenarios.get('long', {}).get('expected_kills', 'N/A')}`"
    )
    embed.add_field(name="🎮 Round scenarios", value=safe_field_value(scenarios_value), inline=False)

    embed.set_footer(text="Exact K(hs) mapstats only • no fabricated headshots or negative-binomial fallback")
    return embed


def data_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    embed = discord.Embed(
        color=BRAND,
        description=safe_field_value(header(data, line, opponent, "Kills")),
    )

    paired = []
    for row in data.get("Paired series rows", [])[:10]:
        emoji = "🟢" if row["kills"] > line else "🔴"
        paired.append(
            f"{emoji} **{row['opponent']}** (`{row['date']}`) — "
            f"{row['kills']}K {row['headshots']}HS {row['rounds']}R | "
            f"{map_name(row['map1'])} + {map_name(row['map2'])}"
        )

    raw = []
    for row in data.get("Raw maps", [])[:20]:
        raw.append(
            f"`{map_name(row['map_name']):<10} {str(row['kills']):>2}-{str(row['deaths']):<2} "
            f"HS {str(row['headshots']):>3} R {str(row['rounds']):>3} vs {str(row['opponent']).upper()[:12]}`"
        )

    pmap = []
    for map_key, vals in list((data.get("Per-map averages") or {}).items())[:7]:
        pmap.append(
            f"`{map_name(map_key):<10} {vals['avg_kills']}K • "
            f"{vals['avg_hs']}HS • {vals['avg_kpr']} KPR • "
            f"{vals['sample_size']} maps`"
        )

    embed.add_field(name="⭐ Exact paired series", value=trim_lines(paired), inline=False)
    embed.add_field(name="📦 Exact raw maps", value=trim_lines(raw), inline=False)

    profile_value = (
        f"**Rating 3.0:** `{data.get('Rating 3.0', 'N/A')}`\n"
        f"**Firepower:** `{data.get('Firepower', 'N/A')}`\n"
        f"**Entrying:** `{data.get('Entrying', 'N/A')}`\n"
        f"**Trading:** `{data.get('Trading', 'N/A')}`\n"
        f"**Opening:** `{data.get('Opening', 'N/A')}`\n"
        f"**Clutching:** `{data.get('Clutching', 'N/A')}`\n"
        f"**Sniping:** `{data.get('Sniping', 'N/A')}`\n"
        f"**Utility:** `{data.get('Utility', 'N/A')}`"
    )
    embed.add_field(name="📋 HLTV profile buckets", value=safe_field_value(profile_value), inline=True)

    stats_value = (
        f"**KPR:** `{data.get('KPR', 'N/A')}`\n"
        f"**DPR:** `{data.get('DPR', 'N/A')}`\n"
        f"**ADR:** `{data.get('ADR', 'N/A')}`\n"
        f"**KAST:** `{data.get('KAST', 'N/A')}`\n"
        f"**Impact:** `{data.get('Impact', 'N/A')}`\n"
        f"**HS %:** `{data.get('HS %', 'N/A')}`\n"
        f"**Op.KPR:** `{data.get('Opening kills per round', 'N/A')}`\n"
        f"**Trade.KPR:** `{data.get('Trade kills per round', 'N/A')}`"
    )
    embed.add_field(name="📊 Direct HLTV stats", value=safe_field_value(stats_value), inline=True)

    versus_value = (
        f"**Top 5:** `{data.get('Vs Top 5 rating', 'N/A')}`\n"
        f"**Top 10:** `{data.get('Vs Top 10 rating', 'N/A')}`\n"
        f"**Top 20:** `{data.get('Vs Top 20 rating', 'N/A')}`\n"
        f"**Top 30:** `{data.get('Vs Top 30 rating', 'N/A')}`\n"
        f"**Top 50:** `{data.get('Vs Top 50 rating', 'N/A')}`"
    )
    embed.add_field(name="⚔️ Opponent buckets", value=safe_field_value(versus_value), inline=False)

    embed.add_field(name="🗺️ Per-map sample", value=trim_lines(pmap), inline=False)

    embed.set_footer(text="All kills/headshots shown here are exact Maps 1-2 totals from HLTV mapstats pages")
    return embed


def context_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    embed = discord.Embed(
        color=PANEL,
        description=safe_field_value(header(data, line, opponent, "Kills")),
    )

    h2h = data.get("H2H Data", {}) or {}
    veto = data.get("Veto", []) or []
    likely = data.get("Likely maps", {}) or {}

    context_value = (
        f"**Role:** `{data.get('Role', 'N/A')}`\n"
        f"**Role note:** `{data.get('Role note', 'N/A')}`\n"
        f"**Team:** `{data.get('Team', 'N/A')}`\n"
        f"**Team rank:** `{data.get('Team ranking', 'N/A')}`\n"
        f"**Opponent rank:** `{data.get('Opponent ranking', 'N/A')}`\n"
        f"**Odds:** `{data.get('Match odds', 'N/A')}`\n"
        f"**Moneyline:** `{data.get('Moneyline', 'N/A')}` / "
        f"`{data.get('Moneyline american', 'N/A')}`"
    )
    embed.add_field(name="🎯 Context", value=safe_field_value(context_value), inline=False)

    h2h_value = (
        f"**Similar split:** `{data.get('Similar teams', 'N/A')}`\n"
        f"**H2H sample:** `{h2h.get('h2h_sample_size', 0)}`\n"
        f"**H2H avg kills:** `{h2h.get('h2h_avg_kills', 'N/A')}`\n"
        f"**H2H avg HS:** `{h2h.get('h2h_avg_headshots', 'N/A')}`\n"
        f"**Rounds note:** `{data.get('Exact round note', 'N/A')}`"
    )
    embed.add_field(name="🔄 Similar teams / H2H", value=safe_field_value(h2h_value), inline=False)

    maps_str = " • ".join(f"{key}: {value}" for key, value in likely.items()) if likely else "N/A"
    embed.add_field(name="🗺️ Likely maps", value=safe_field_value(maps_str), inline=False)

    embed.add_field(name="🎪 Veto / map notes", value=trim_lines(veto), inline=False)

    embed.set_footer(text="Role is derived from HLTV profile buckets; missing values remain N/A instead of guessed")
    return embed


class PropView(discord.ui.View):
    def __init__(self, data: Dict[str, Any], line: float, opponent: str):
        super().__init__(timeout=3600)
        self.data = data
        self.line = line
        self.opponent = opponent

    async def swap(self, interaction: discord.Interaction, embed: discord.Embed):
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="GRADE", style=discord.ButtonStyle.primary, emoji="🎯")
    async def grade_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.swap(interaction, grade_embed(self.data, self.line, self.opponent))

    @discord.ui.button(label="DATA", style=discord.ButtonStyle.secondary, emoji="📊")
    async def data_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.swap(interaction, data_embed(self.data, self.line, self.opponent))

    @discord.ui.button(label="CONTEXT", style=discord.ButtonStyle.secondary, emoji="🔍")
    async def context_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.swap(interaction, context_embed(self.data, self.line, self.opponent))


@bot.event
async def on_ready():
    print(f"✅ Bot online: {bot.user}", flush=True)


@bot.command()
async def scan(ctx, player=None, line=None, *, opponent="N/A"):
    if not player or not line:
        return await ctx.send("❌ Usage: `!scan player line opponent`")

    msg = await ctx.send(f"🔍 Loading exact HLTV grade for `{player}` vs `{opponent}`...")

    async with ctx.typing():
        try:
            line_val = float(line)
            data = await asyncio.to_thread(get_player_info, player, line_val, opponent)

            if data.get("error"):
                return await msg.edit(content=f"❌ {data['error']}")

            view = PropView(data, line_val, opponent)
            await msg.edit(content=None, embed=grade_embed(data, line_val, opponent), view=view)

        except ValueError:
            await msg.edit(content="❌ Invalid line; must be a number (e.g., `27.5`)")
        except Exception as exc:
            await msg.edit(content=f"❌ Scan crashed: `{exc}`")


@bot.command()
async def hs(ctx, player=None, line=None, *, opponent="N/A"):
    if not player or not line:
        return await ctx.send("❌ Usage: `!hs player line opponent`")

    msg = await ctx.send(f"🔍 Loading exact HLTV headshot grade for `{player}` vs `{opponent}`...")

    async with ctx.typing():
        try:
            line_val = float(line)
            # AUDIT FIX: use exact headshot entrypoint from scraper instead of kill scan fallback logic.
            data = await asyncio.to_thread(get_headshot_info, player, line_val, opponent)

            if data.get("error"):
                return await msg.edit(content=f"❌ {data['error']}")

            side, color = side_color(data)
            recent_hs = data.get("Recent HS Totals (M1+M2)", [])
            recent = " ".join((("🟢" if x > line_val else "🔴") + f" `{x}`") for x in recent_hs[:10]) or "No sample"

            embed = discord.Embed(
                color=color,
                description=safe_field_value(header(data, line_val, opponent, "Headshots")),
            )

            grade_value = (
                f"**Side:** `{side}`\n"
                f"**Avg:** `{data.get('Recent average', 'N/A')}`\n"
                f"**Median:** `{data.get('Recent median', 'N/A')}`\n"
                f"**Projection:** `{data.get('Recent projection', 'N/A')}`\n"
                f"**Hit rate:** `{data.get('Hit rate', 'N/A')}`\n"
                f"{recent}"
            )
            embed.add_field(name="🎯 Headshot grade", value=safe_field_value(grade_value), inline=False)

            hs_profile_value = (
                f"**Recent HS %:** `{data.get('Recent HS %', 'N/A')}`\n"
                f"**Recent HS avg:** `{data.get('Recent HS Average', 'N/A')}`\n"
                f"**Recent HS median:** `{data.get('Recent HS Median', 'N/A')}`\n"
                f"**Profile HS %:** `{data.get('All-time profile HS %', 'N/A')}`\n"
                f"**Over:** `{data.get('Over probability', 'N/A')}`\n"
                f"**Under:** `{data.get('Under probability', 'N/A')}`\n"
                f"**Edge:** `{data.get('Edge vs line', 'N/A')}`"
            )
            embed.add_field(name="📊 HS profile", value=safe_field_value(hs_profile_value), inline=False)

            context_value = (
                f"**Role:** `{data.get('Role', 'N/A')}`\n"
                f"**Team rank:** `{data.get('Team ranking', 'N/A')}`\n"
                f"**Opponent rank:** `{data.get('Opponent ranking', 'N/A')}`\n"
                f"**Odds:** `{data.get('Match odds', 'N/A')}`"
            )
            embed.add_field(name="🔍 Context", value=safe_field_value(context_value), inline=False)

            embed.set_footer(text="Exact Maps 1-2 K(hs) only • no estimated HS fallback")

            await msg.edit(content=None, embed=embed)

        except ValueError:
            await msg.edit(content="❌ Invalid line; must be a number (e.g., `7.5`)")
        except Exception as exc:
            await msg.edit(content=f"❌ HS scan crashed: `{exc}`")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("❌ DISCORD_TOKEN missing.")
    bot.run(token)
