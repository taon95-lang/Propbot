import os
import asyncio
import statistics as stats
from typing import Any, Dict, List

import discord
from discord.ext import commands

from scraper import get_player_info

GREEN = 0x35D39B
RED = 0xE24A68
BRAND = 0xF0A51A
PANEL = 0x111827
MUTED = 0x64748B

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def num(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float."""
    try:
        if value is None or value == "N/A":
            return default
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (ValueError, AttributeError, TypeError):
        return default


def safe_list(value: Any, default: List = None) -> List:
    """Safely convert value to list."""
    if default is None:
        default = []
    if isinstance(value, list):
        return value
    if value is None or value == "N/A":
        return default
    return default


def safe_dict(value: Any, default: Dict = None) -> Dict:
    """Safely convert value to dict."""
    if default is None:
        default = {}
    if isinstance(value, dict):
        return value
    if value is None or value == "N/A":
        return default
    return default


def safe_str(value: Any, default: str = "N/A") -> str:
    """Safely convert value to string."""
    if value is None:
        return default
    if value == "N/A":
        return default
    try:
        return str(value).strip()
    except Exception:
        return default


def bar(score: float, total: int = 10) -> str:
    """Generate a visual bar representation of a score."""
    try:
        score = num(score, 0.0)
        filled = max(0, min(total, int(round(score))))
        return "▰" * filled + "▱" * (total - filled)
    except Exception:
        return "▱" * total


def score_num(data: Dict[str, Any]) -> float:
    """Extract numeric score from grade string."""
    try:
        grade_str = safe_str(data.get("Final grade", "0/10"))
        numeric_part = str(grade_str).split("/")[0].strip()
        return num(numeric_part, 0.0)
    except Exception:
        return 0.0


def side_color(data: Dict[str, Any]):
    """Determine bet side and color from data."""
    rec = safe_str(data.get("Bet recommendation", "NO BET")).upper()
    if "OVER" in rec:
        return "OVER", GREEN
    if "UNDER" in rec:
        return "UNDER", RED
    return "NO BET", MUTED


def map_name(value: str) -> str:
    """Convert map code to display name."""
    names = {
        "dust2": "Dust2",
        "mirage": "Mirage",
        "inferno": "Inferno",
        "nuke": "Nuke",
        "ancient": "Ancient",
        "anubis": "Anubis",
        "vertigo": "Vertigo",
        "overpass": "Overpass",
        "train": "Train",
        "cache": "Cache",
    }
    return names.get(safe_str(value).lower(), safe_str(value).title())


def trim_lines(lines: List[str], limit: int = 1024) -> str:
    """Trim lines to fit Discord embed field limit."""
    lines = safe_list(lines, [])
    if not lines:
        return "N/A"
    
    out = []
    total = 0
    for line in lines:
        line_str = safe_str(line)
        if total + len(line_str) + 1 > limit:
            break
        out.append(line_str)
        total += len(line_str) + 1
    
    return "\n".join(out) if out else "N/A"


def header(data: Dict[str, Any], line: float, opponent: str, prop: str) -> str:
    """Generate header text for embed."""
    player = safe_str(data.get("Player", "Player"))
    rating = safe_str(data.get("Rating 3.0", "N/A"))
    role = safe_str(data.get("Role", "N/A"))
    team_rank = safe_str(data.get("Team ranking", "N/A"))
    odds = safe_str(data.get("Match odds", "N/A"))
    
    return (
        f"# CS2 Prop Grader\n"
        f"`Maps 1–2 only` • `HLTV exact data` • `No fake HS fallback`\n\n"
        f"## {player} vs {opponent.title()} | `{prop} O/U {line}`\n"
        f"**Rating 3.0:** `{rating}` • "
        f"**Role:** `{role}` • "
        f"**Team rank:** `{team_rank}` • "
        f"**Odds:** `{odds}`"
    )


def grade_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    """Create grade embed showing main prop analysis."""
    side, color = side_color(data)
    score = score_num(data)
    totals = safe_list(data.get("Recent Totals (M1+M2 Combined)"), [])
    q25 = safe_str(data.get("25th percentile", "N/A"))
    q75 = safe_str(data.get("75th percentile", "N/A"))
    
    scenarios = safe_dict(data.get("Scenarios"), {})

    # Build recent totals bar
    recent_parts = []
    for x in totals[:10]:
        x_val = safe_dict(x) if isinstance(x, dict) else x
        x_num = num(x_val, 0.0)
        emoji = "🟩" if x_num > line else "🟥"
        recent_parts.append(emoji + f"`{int(x_num)}`")
    recent = " ".join(recent_parts) if recent_parts else "No sample"

    e = discord.Embed(color=color, description=header(data, line, opponent, "Kills"))
    e.add_field(
        name="☠️ Grade",
        value=(
            f"**Side:** `{side}`\n"
            f"**Grade:** `{safe_str(data.get('Final grade', 'N/A'))}`\n"
            f"{bar(score)}\n"
            f"**Misprice:** `{safe_str(data.get('Mispriced or not', 'N/A'))}`"
        ),
        inline=False,
    )
    e.add_field(
        name="📊 Exact sample",
        value=(
            f"**Avg:** `{safe_str(data.get('Recent average', 'N/A'))}`\n"
            f"**Median:** `{safe_str(data.get('Recent median', 'N/A'))}`\n"
            f"**Projection:** `{safe_str(data.get('Recent projection', 'N/A'))}`\n"
            f"**Hit rate:** `{safe_str(data.get('Hit rate', 'N/A'))}`\n"
            f"**25th/75th:** `{q25}` / `{q75}`"
        ),
        inline=True,
    )
    e.add_field(
        name="📈 Bootstrap",
        value=(
            f"**Mean:** `{safe_str(data.get('Simulated mean', 'N/A'))}`\n"
            f"**Median:** `{safe_str(data.get('Simulated median', 'N/A'))}`\n"
            f"**Std Dev:** `{safe_str(data.get('Std Dev', 'N/A'))}`\n"
            f"**Over:** `{safe_str(data.get('Over probability', 'N/A'))}`\n"
            f"**Under:** `{safe_str(data.get('Under probability', 'N/A'))}`\n"
            f"**Edge:** `{safe_str(data.get('Edge vs line', 'N/A'))}`"
        ),
        inline=True,
    )
    e.add_field(
        name="🎯 Recent totals",
        value=recent,
        inline=False,
    )
    
    # Build scenarios safely
    short_kills = safe_str(safe_dict(scenarios.get("short")).get("expected_kills", "N/A"))
    normal_kills = safe_str(safe_dict(scenarios.get("normal")).get("expected_kills", "N/A"))
    long_kills = safe_str(safe_dict(scenarios.get("long")).get("expected_kills", "N/A"))
    
    e.add_field(
        name="🗺️ Round scenarios",
        value=(
            f"**Short:** `{short_kills}` | "
            f"**Normal:** `{normal_kills}` | "
            f"**Long:** `{long_kills}`"
        ),
        inline=False,
    )
    e.set_footer(text="All kills/headshots are exact HLTV maps 1-2 totals from each BO3 stats page")
    return e


def data_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    """Create data embed showing detailed stats and history."""
    e = discord.Embed(color=BRAND, description=header(data, line, opponent, "Kills"))

    paired = []
    for row in safe_list(data.get("Paired series rows"), [])[:10]:
        row_dict = safe_dict(row)
        row_kills = num(row_dict.get("kills"), 0.0)
        row_emoji = "🟢" if row_kills > line else "🔴"
        row_opponent = safe_str(row_dict.get("opponent", "Unknown"))
        row_date = safe_str(row_dict.get("date", "N/A"))
        row_hs = safe_str(row_dict.get("headshots", "0"))
        row_rounds = safe_str(row_dict.get("rounds", "0"))
        row_map1 = map_name(safe_str(row_dict.get("map1", "Unknown")))
        row_map2 = map_name(safe_str(row_dict.get("map2", "Unknown")))
        
        paired.append(
            f"{row_emoji} **{row_opponent}** (`{row_date}`) — "
            f"{int(row_kills)}K {row_hs}HS {row_rounds}R | "
            f"{row_map1} + {row_map2}"
        )

    raw = []
    for row in safe_list(data.get("Raw maps"), [])[:20]:
        row_dict = safe_dict(row)
        raw_map = map_name(safe_str(row_dict.get("map_name", "Unknown")))
        raw_kills = safe_str(row_dict.get("kills", "0"))
        raw_deaths = safe_str(row_dict.get("deaths", "0"))
        raw_hs = safe_str(row_dict.get("headshots", "0"))
        raw_rounds = safe_str(row_dict.get("rounds", "0"))
        raw_opp = safe_str(row_dict.get("opponent", "Unknown"))[:12].upper()
        
        raw.append(
            f"`{raw_map:<8} {raw_kills:>2}-{raw_deaths:<2} "
            f"HS {raw_hs:>2} R {raw_rounds:>2} vs {raw_opp}`"
        )

    pmap = []
    for m, vals in list(safe_dict(data.get("Per-map averages")).items())[:7]:
        vals_dict = safe_dict(vals)
        pmap_name = map_name(safe_str(m))
        pmap_kills = safe_str(vals_dict.get("avg_kills", "N/A"))
        pmap_hs = safe_str(vals_dict.get("avg_hs", "N/A"))
        pmap_kpr = safe_str(vals_dict.get("avg_kpr", "N/A"))
        pmap_sample = safe_str(vals_dict.get("sample_size", "0"))
        
        pmap.append(
            f"`{pmap_name:<10} {pmap_kills}K • "
            f"{pmap_hs}HS • {pmap_kpr} KPR • {pmap_sample} maps`"
        )

    e.add_field(name="🎯 Exact paired series", value=trim_lines(paired), inline=False)
    e.add_field(name="📋 Exact raw maps", value=trim_lines(raw), inline=False)
    e.add_field(
        name="📊 Current HLTV profile/stats",
        value=(
            f"**Rating 3.0:** `{safe_str(data.get('Rating 3.0', 'N/A'))}`\n"
            f"**Firepower:** `{safe_str(data.get('Firepower', 'N/A'))}`\n"
            f"**Entrying:** `{safe_str(data.get('Entrying', 'N/A'))}`\n"
            f"**Trading:** `{safe_str(data.get('Trading', 'N/A'))}`\n"
            f"**Opening:** `{safe_str(data.get('Opening', 'N/A'))}`\n"
            f"**KPR:** `{safe_str(data.get('KPR', 'N/A'))}`\n"
            f"**DPR:** `{safe_str(data.get('DPR', 'N/A'))}`\n"
            f"**ADR:** `{safe_str(data.get('ADR', 'N/A'))}`\n"
            f"**KAST:** `{safe_str(data.get('KAST', 'N/A'))}`\n"
            f"**Impact:** `{safe_str(data.get('Impact', 'N/A'))}`"
        ),
        inline=True,
    )
    e.add_field(name="🗺️ Per-map sample", value=trim_lines(pmap), inline=False)
    e.set_footer(text="The HS totals shown here are exact K(hs) sums from maps 1 and 2")
    return e


def context_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    """Create context embed showing matchup and veto info."""
    e = discord.Embed(color=PANEL, description=header(data, line, opponent, "Kills"))
    h2h = safe_dict(data.get("H2H Data"), {})
    veto = safe_list(data.get("Veto"), [])
    likely = safe_dict(data.get("Likely maps"), {})

    e.add_field(
        name="🧠 Context",
        value=(
            f"**Role:** `{safe_str(data.get('Role', 'N/A'))}`\n"
            f"**Team:** `{safe_str(data.get('Team', 'N/A'))}`\n"
            f"**Team rank:** `{safe_str(data.get('Team ranking', 'N/A'))}`\n"
            f"**Opponent rank:** `{safe_str(data.get('Opponent ranking', 'N/A'))}`\n"
            f"**Odds:** `{safe_str(data.get('Match odds', 'N/A'))}`\n"
            f"**Moneyline:** `{safe_str(data.get('Moneyline', 'N/A'))}` / "
            f"`{safe_str(data.get('Moneyline american', 'N/A'))}`"
        ),
        inline=False,
    )
    e.add_field(
        name="📚 Similar teams / H2H",
        value=(
            f"**Similar team split:** `{safe_str(data.get('Similar teams', 'N/A'))}`\n"
            f"**H2H sample:** `{safe_str(h2h.get('h2h_sample_size', 0))}`\n"
            f"**H2H avg kills:** `{safe_str(h2h.get('h2h_avg_kills', 'N/A'))}`\n"
            f"**H2H avg HS:** `{safe_str(h2h.get('h2h_avg_headshots', 'N/A'))}`\n"
            f"**Note:** `{safe_str(h2h.get('h2h_note', 'N/A'))}`"
        ),
        inline=False,
    )
    
    likely_maps = " • ".join(safe_str(v) for v in likely.values() if v) if likely else "N/A"
    e.add_field(
        name="🎯 Likely maps",
        value=likely_maps,
        inline=False,
    )
    e.add_field(
        name="📝 Veto / map notes",
        value=trim_lines(veto),
        inline=False,
    )
    e.set_footer(text="Role is derived from current HLTV profile buckets, not guessed from old form")
    return e


class PropView(discord.ui.View):
    """View with buttons to switch between grade, data, and context embeds."""
    
    def __init__(self, data: Dict[str, Any], line: float, opponent: str):
        super().__init__(timeout=3600)
        self.data = data
        self.line = line
        self.opponent = opponent

    async def swap(self, interaction: discord.Interaction, embed: discord.Embed):
        """Swap to a new embed."""
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.errors.NotFound:
            pass
        except Exception as e:
            print(f"Swap error: {e}")

    @discord.ui.button(label="GRADE", style=discord.ButtonStyle.primary, emoji="☠️")
    async def grade_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.swap(interaction, grade_embed(self.data, self.line, self.opponent))

    @discord.ui.button(label="DATA", style=discord.ButtonStyle.secondary, emoji="📊")
    async def data_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.swap(interaction, data_embed(self.data, self.line, self.opponent))

    @discord.ui.button(label="CONTEXT", style=discord.ButtonStyle.secondary, emoji="🧠")
    async def context_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.swap(interaction, context_embed(self.data, self.line, self.opponent))


@bot.event
async def on_ready():
    print(f"✅ Bot online: {bot.user}", flush=True)


@bot.command()
async def scan(ctx, player=None, line=None, *, opponent="N/A"):
    """Grade a CS2 player prop for kills."""
    if not player or not line:
        return await ctx.send("❌ Usage: `!scan player line opponent`")

    msg = await ctx.send(f"🔎 Loading exact HLTV grade for `{player}` vs `{opponent}`...")
    async with ctx.typing():
        try:
            line_val = num(line, 0.0)
            if line_val <= 0:
                return await msg.edit(content="❌ Line must be a positive number")
            
            data = await asyncio.to_thread(get_player_info, player, line_val, opponent)
            
            if data.get("error"):
                return await msg.edit(content=f"❌ {safe_str(data['error'])}")

            view = PropView(data, line_val, opponent)
            await msg.edit(
                content=None,
                embed=grade_embed(data, line_val, opponent),
                view=view
            )
        except ValueError:
            await msg.edit(content="❌ Line must be a valid number (e.g., 27.5)")
        except Exception as exc:
            await msg.edit(content=f"❌ Scan crashed: `{exc}`")


@bot.command()
async def hs(ctx, player=None, line=None, *, opponent="N/A"):
    """Grade a CS2 player prop for headshots."""
    if not player or not line:
        return await ctx.send("❌ Usage: `!hs player line opponent`")

    msg = await ctx.send(
        f"🎯 Loading exact HLTV headshot grade for `{player}` vs `{opponent}`..."
    )
    async with ctx.typing():
        try:
            line_val = num(line, 0.0)
            if line_val < 0:
                return await msg.edit(content="❌ Line must be a non-negative number")
            
            data = await asyncio.to_thread(get_player_info, player, 0.0, opponent)
            
            if data.get("error"):
                return await msg.edit(content=f"❌ {safe_str(data['error'])}")

            hs = safe_list(data.get("Recent HS Totals (M1+M2)"), [])
            if not hs:
                return await msg.edit(content="❌ No exact headshot sample found.")

            # Convert all hs values to floats safely
            hs_vals = [num(x, 0.0) for x in hs]
            if not hs_vals:
                return await msg.edit(content="❌ No valid headshot data.")

            avg_hs = round(stats.mean(hs_vals), 1)
            med_hs = round(stats.median(hs_vals), 1)
            proj_hs = safe_str(data.get("Recent HS Projection", "N/A"))
            hit_rate = round((sum(1 for x in hs_vals if x > line_val) / len(hs_vals)) * 100, 1)

            if avg_hs > line_val and med_hs > line_val and hit_rate >= 60:
                side, color = "OVER", GREEN
            elif avg_hs < line_val and med_hs < line_val and hit_rate <= 40:
                side, color = "UNDER", RED
            else:
                side, color = "NO BET", MUTED

            # Build recent HS bar
            recent_parts = []
            for x in hs_vals[:10]:
                emoji = "🟩" if x > line_val else "🟥"
                recent_parts.append(emoji + f"`{int(x)}`")
            recent = " ".join(recent_parts) if recent_parts else "No sample"

            e = discord.Embed(color=color, description=header(data, line_val, opponent, "Headshots"))
            e.add_field(
                name="🔫 Headshot grade",
                value=(
                    f"**Side:** `{side}`\n"
                    f"**Avg:** `{avg_hs}`\n"
                    f"**Median:** `{med_hs}`\n"
                    f"**Projection:** `{proj_hs}`\n"
                    f"**Hit rate:** `{hit_rate}%`\n"
                    f"{recent}"
                ),
                inline=False,
            )
            e.add_field(
                name="📊 HS profile",
                value=(
                    f"**Recent HS %:** `{safe_str(data.get('Recent HS %', 'N/A'))}`\n"
                    f"**Recent HS avg:** `{safe_str(data.get('Recent HS Average', 'N/A'))}`\n"
                    f"**Recent HS median:** `{safe_str(data.get('Recent HS Median', 'N/A'))}`\n"
                    f"**All-time profile HS %:** `{safe_str(data.get('All-time profile HS %', 'N/A'))}`\n"
                    f"**Role:** `{safe_str(data.get('Role', 'N/A'))}`\n"
                    f"**Odds:** `{safe_str(data.get('Match odds', 'N/A'))}`"
                ),
                inline=False,
            )
            e.set_footer(text="Exact Maps 1-2 headshots only; no estimated HS fallback")
            await msg.edit(content=None, embed=e)
        except ValueError:
            await msg.edit(content="❌ Line must be a valid number (e.g., 8.5)")
        except Exception as exc:
            await msg.edit(content=f"❌ HS scan crashed: `{exc}`")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("❌ DISCORD_TOKEN missing.")
    bot.run(token)
