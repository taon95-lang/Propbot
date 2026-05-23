import os
import asyncio
import statistics as _stats
from typing import Any, Dict, List

import discord
from discord.ext import commands

from scraper import get_player_info

BRAND = 0xF0A51A
GREEN = 0x35D39B
RED = 0xE24A68
PANEL = 0x111827
MUTED = 0x64748B

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def pct_float(v: Any, default: float = 0.0) -> float:
    """Convert percentage string to float"""
    try:
        return float(str(v).replace("%", ""))
    except Exception:
        return default


def num(v: Any, default: float = 0.0) -> float:
    """Convert value to float"""
    try:
        return float(v)
    except Exception:
        return default


def bar(value: float, total: int = 10) -> str:
    """Generate progress bar"""
    value = max(0, min(total, int(round(value))))
    return "▰" * value + "▱" * (total - value)


def grade_score(data: Dict[str, Any]) -> float:
    """Extract numeric grade from final_grade string"""
    text = str(data.get("Final grade", ""))
    import re
    m = re.search(r"(\d+(?:\.\d+)?)/10", text)
    if m:
        return float(m.group(1))
    over = pct_float(data.get("Over probability"))
    under = pct_float(data.get("Under probability"))
    return round(max(over, under) / 10, 1)


def side_and_color(data: Dict[str, Any]) -> tuple[str, int]:
    """Determine side (OVER/UNDER) and color"""
    rec = str(data.get("Bet recommendation", data.get("Bet Recommendation", "NO BET"))).upper()
    if "OVER" in rec:
        return "OVER", GREEN
    if "UNDER" in rec:
        return "UNDER", RED
    return "NO BET", MUTED


def clean_map_name(m: str) -> str:
    """Clean map name for display"""
    names = {
        "dust2": "Dust2", "mirage": "Mirage", "inferno": "Inferno", 
        "nuke": "Nuke", "ancient": "Ancient", "anubis": "Anubis", 
        "vertigo": "Vertigo", "overpass": "Overpass"
    }
    return names.get(str(m).lower(), str(m).title())


def split_chunks(text: str, limit: int = 3900) -> List[str]:
    """Split text into chunks for Discord message limits"""
    chunks, cur = [], ""
    for line in text.splitlines():
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur += ("\n" if cur else "") + line
    if cur:
        chunks.append(cur)
    return chunks


def top_header(data: Dict[str, Any], line: float, opponent: str, prop_type: str = "Kills") -> str:
    """Create top header for embeds"""
    rating = data.get('Rating 3.0', 'N/A')
    kpr = data.get('KPR', 'N/A')
    impact = data.get('Impact', 'N/A')
    
    return (
        f"# CS2 Prop Grader\n"
        f"`MAPS 1–2` • `BO3` • `100K SIMS` • `HLTV DATA`\n\n"
        f"## {data.get('Player', 'Player')} vs {opponent.title()} | `{prop_type} O/U {line}`\n"
        f"**HIGH CONFIDENCE** — Rating 3.0: `{rating}` | KPR: `{kpr}` | Impact: `{impact}`"
    )


def make_grade_embed(data: Dict[str, Any], line: float, opponent: str, prop_type: str = "Kills") -> discord.Embed:
    """Create main grade embed"""
    side, color = side_and_color(data)
    score = grade_score(data)
    label = "Strong Play" if score >= 7.5 else "Lean" if score >= 6 else "Avoid"
    mis = str(data.get("Mispriced or not", "NO"))
    totals = data.get("Recent Totals (M1+M2 Combined)", [])
    avg = data.get("Recent average", "N/A")
    med = data.get("Recent median", "N/A")
    hit = data.get("Hit rate", "N/A")
    floor = data.get("Floor (Bottom 3)", "N/A")
    ceil = data.get("Ceiling (Top 3)", "N/A")
    
    q25 = q75 = "N/A"
    if len(totals) >= 4:
        s = sorted(totals)
        q25, q75 = s[len(s)//4], s[(len(s)*3)//4]

    # Recent performance bars
    recent_lines = []
    for v in totals[:10]:
        mark = "🟩" if num(v) > line else "🟥"
        recent_lines.append(f"{mark} `{v}`")
    recent = " ".join(recent_lines) or "No recent data"

    # Scenarios
    scenarios = data.get("Scenarios", {}) or {}
    short = scenarios.get("short", {}).get("expected_kills", "N/A")
    normal = scenarios.get("normal", {}).get("expected_kills", "N/A")
    long = scenarios.get("long", {}).get("expected_kills", "N/A")

    e = discord.Embed(color=color, description=top_header(data, line, opponent, prop_type))
    
    e.add_field(
        name="☠️ Kills Prop",
        value=f"O/U `{line}`\n{bar(score)} **{score}/10**\n**{side}** — {label} | `{mis}`",
        inline=False
    )
    
    e.add_field(
        name="📊 Simulation Results (100K Runs)",
        value=(
            f"**Sim Mean:** `{data.get('Simulated mean', 'N/A')}`\n"
            f"**Sim Median:** `{data.get('Simulated median', 'N/A')}`\n"
            f"**Std Dev:** `{data.get('Std Dev', 'N/A')}`\n"
            f"**25th / 75th:** `{q25} / {q75}`\n"
            f"**Over %:** `{data.get('Over probability', 'N/A')}`\n"
            f"**Under %:** `{data.get('Under probability', 'N/A')}`\n"
            f"**Edge:** `{data.get('Edge vs line', 'N/A')}`"
        ),
        inline=True
    )
    
    e.add_field(
        name="📈 Recent Performance vs Line",
        value=(
            f"**AVG:** `{avg}` | **MED:** `{med}` | **HIT:** `{hit}`\n"
            f"**FLOOR:** `{floor}` | **CEIL:** `{ceil}`\n"
            f"{recent}"
        ),
        inline=False
    )
    
    e.add_field(
        name="🗺️ Map Projections",
        value=f"**Short:** `{short}` | **Normal:** `{normal}` | **Long:** `{long}`",
        inline=False
    )
    
    e.set_footer(text="CS2 Prop Grader • Maps 1–2 only • HLTV data")
    return e


def make_data_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    """Create data details embed"""
    e = discord.Embed(color=BRAND, description=top_header(data, line, opponent, "Kills"))
    
    raw = data.get("Raw maps", [])[:14]
    rows = []
    for m in raw:
        map_name = clean_map_name(m.get('map_name', '?'))
        kills = m.get('kills', 0)
        deaths = m.get('deaths', 0)
        hs = m.get('headshots', 0)
        rounds = m.get('rounds', 0)
        opp = str(m.get('opponent', '?')).upper()[:12]
        rows.append(f"`{map_name:<8} {kills:>2}-{deaths:<2} HS {hs:>2} R {rounds:>2} vs {opp}`")
    
    e.add_field(
        name="📋 RAW MAP DATA (14 MAPS)",
        value="\n".join(rows)[:1024] or "No raw maps",
        inline=False
    )

    paired = data.get("Paired series rows", [])[:10]
    prow = []
    for p in paired:
        mark = "🟢" if num(p.get("kills")) > line else "🔴"
        opp = p.get('opponent', 'N/A')
        date = p.get('date', 'N/A')
        kills = p.get('kills', 0)
        hs = p.get('headshots', 0)
        rounds = p.get('rounds', 0)
        map1 = p.get('map1', '?')
        map2 = p.get('map2', '?')
        prow.append(
            f"{mark} **{opp}** (`{date}`) — {kills}K {hs}HS {rounds}R | {clean_map_name(map1)} + {clean_map_name(map2)}"
        )
    
    e.add_field(
        name="🎯 PAIRED SERIES (M1+M2)",
        value="\n".join(prow)[:1024] or "No series",
        inline=False
    )

    e.add_field(
        name="📊 HLTV VERIFIED STATS",
        value=(
            f"**Rating 3.0:** `{data.get('Rating 3.0', 'N/A')}`\n"
            f"**KPR:** `{data.get('KPR', 'N/A')}`\n"
            f"**DPR:** `{data.get('DPR', 'N/A')}`\n"
            f"**Impact:** `{data.get('Impact', 'N/A')}`\n"
            f"**HS%:** `{data.get('HS %', 'N/A')}`\n"
            f"**Multi-kill %:** `{data.get('Multi-kill %', 'N/A')}`\n"
            f"**Round Swing %:** `{data.get('Round Swing %', 'N/A')}`\n"
            f"**HS Avg (M1+M2):** `{data.get('Recent HS Average', 'N/A')}`"
        ),
        inline=True
    )
    
    maps = data.get("Per-map averages", {}) or {}
    mlines = []
    for k, v in list(maps.items())[:7]:
        avg_kills = v.get('avg_kills', 0)
        avg_kpr = v.get('avg_kpr', 0)
        sample = v.get('sample_size', 0)
        mlines.append(f"`{clean_map_name(k):<10} {avg_kills}K • {avg_kpr} KPR • {sample} maps`")
    
    e.add_field(
        name="🗺️ MAP POOL / KPR BY MAP",
        value="\n".join(mlines)[:1024] or "No map data",
        inline=False
    )
    
    e.set_footer(text="DATA tab • raw HLTV-derived sample")
    return e


def make_context_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    """Create context/analysis embed"""
    e = discord.Embed(color=PANEL, description=top_header(data, line, opponent, "Kills"))
    
    role = data.get('Role', 'N/A')
    rating = data.get('Rating 3.0', 'N/A')
    kpr = data.get('KPR', 'N/A')
    dpr = data.get('DPR', 'N/A')
    impact = data.get('Impact', 'N/A')
    
    h2h = data.get("H2H Data", {}) or {}
    h2h_size = h2h.get('h2h_sample_size', 0)
    h2h_avg = h2h.get('h2h_avg_kills', 'N/A')
    h2h_kpr = h2h.get('h2h_kpr', 'N/A')
    h2h_note = h2h.get('h2h_note', 'No H2H')
    
    opp_factor = data.get('Opponent strength factor', 1.02)
    
    e.add_field(
        name="🎮 MATCH CONTEXT & ROLE",
        value=(
            f"**Role:** `{role}`\n"
            f"**Rating 3.0:** `{rating}` | **KPR:** `{kpr}` | **DPR:** `{dpr}` | **Impact:** `{impact}`\n"
            f"**Opponent Strength Factor:** `{round(opp_factor, 3)}` (lower = tougher defense)\n"
            f"**H2H Sample:** `{h2h_size}` maps | Avg: `{h2h_avg}` | KPR: `{h2h_kpr}` | {h2h_note}"
        ),
        inline=False
    )
    
    likely = data.get("Likely maps", {}) or {}
    map_str = " • ".join([f"{v}" for v in likely.values()][:3]) or "Map data unavailable"
    
    e.add_field(
        name="🎯 KEY FACTORS",
        value=(
            f"**Likely Maps:** {map_str}\n"
            f"**Hit Rate:** `{data.get('Hit rate', 'N/A')}`\n"
            f"**Average:** `{data.get('Recent average', 'N/A')}` | **Median:** `{data.get('Recent median', 'N/A')}`\n"
            f"**Ceiling/Floor:** `{data.get('Ceiling (Top 3)', 'N/A')}` / `{data.get('Floor (Bottom 3)', 'N/A')}`"
        ),
        inline=False
    )
    
    e.add_field(
        name="📝 DATA NOTES",
        value=(
            "Uses **Maps 1–2 only** from last 10 BO3 series. All stats pulled from **HLTV** directly. "
            "Headshots extracted from HLTV detailed stats. No made-up odds inserted. "
            "Opponent strength factor adjusts expected kills based on defensive tier."
        ),
        inline=False
    )
    
    e.set_footer(text="CONTEXT tab • role, maps, H2H, opponent profile")
    return e


class PropView(discord.ui.View):
    """Interactive button view for prop grades"""
    def __init__(self, data: Dict[str, Any], line: float, opponent: str):
        super().__init__(timeout=3600)  # 1 hour timeout
        self.data = data
        self.line = line
        self.opponent = opponent

    async def swap(self, interaction: discord.Interaction, embed: discord.Embed):
        """Update embed on button click"""
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="GRADE", style=discord.ButtonStyle.primary, emoji="☠️")
    async def grade(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.swap(interaction, make_grade_embed(self.data, self.line, self.opponent))

    @discord.ui.button(label="DATA", style=discord.ButtonStyle.secondary, emoji="📊")
    async def data_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.swap(interaction, make_data_embed(self.data, self.line, self.opponent))

    @discord.ui.button(label="CONTEXT", style=discord.ButtonStyle.secondary, emoji="🧠")
    async def context(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.swap(interaction, make_context_embed(self.data, self.line, self.opponent))


@bot.event
async def on_ready():
    """Bot startup event"""
    print(f"✅ CS2 PROP GRADER ONLINE: {bot.user}", flush=True)


@bot.command()
async def scan(ctx, player=None, line=None, *, opponent="N/A"):
    """
    Grade a CS2 player kills prop
    Usage: !scan <player> <line> <opponent>
    Example: !scan pointer 28.5 yawara
    """
    if not player or not line:
        return await ctx.send(
            "❌ **Usage:** `!scan player line opponent`\n"
            "**Example:** `!scan pointer 28.5 yawara`"
        )
    
    msg = await ctx.send(
        f"🔎 **CS2 Prop Grader Loading**\n"
        f"Player: `{player}` | Kills O/U: `{line}` | Opponent: `{opponent}`"
    )
    
    async with ctx.typing():
        try:
            line_float = float(line)
            print(f"🎯 SCAN REQUEST: {player} {line} vs {opponent}", flush=True)
            
            data = await asyncio.to_thread(get_player_info, player, line_float, opponent)
            
            if data.get("error"):
                return await msg.edit(content=f"❌ **Error:** {data['error']}")
            
            view = PropView(data, line_float, opponent)
            await msg.edit(
                content=None,
                embed=make_grade_embed(data, line_float, opponent),
                view=view
            )
            print(f"✅ SCAN COMPLETE: {player}", flush=True)
            
        except ValueError:
            await msg.edit(content="❌ **Invalid line.** Use a number like `28.5`")
        except Exception as e:
            print(f"💥 SCAN ERROR: {e}", flush=True)
            await msg.edit(content=f"❌ **Scan crashed:** `{e}`")


@bot.command()
async def hs(ctx, player=None, line=None, *, opponent="N/A"):
    """
    Grade a CS2 player headshots prop
    Usage: !hs <player> <line> <opponent>
    Example: !hs pointer 10.5 yawara
    """
    if not player or not line:
        return await ctx.send(
            "❌ **Usage:** `!hs player line opponent`\n"
            "**Example:** `!hs pointer 10.5 yawara`"
        )
    
    msg = await ctx.send(
        f"🎯 **CS2 Headshot Grader Loading**\n"
        f"Player: `{player}` | HS O/U: `{line}` | Opponent: `{opponent}`"
    )
    
    async with ctx.typing():
        try:
            line_float = float(line)
            print(f"🎯 HS SCAN REQUEST: {player} {line} vs {opponent}", flush=True)
            
            data = await asyncio.to_thread(get_player_info, player, 0, opponent)
            
            if data.get("error"):
                return await msg.edit(content=f"❌ **Error:** {data['error']}")
            
            hs_totals = data.get("Recent HS Totals (M1+M2)", [])
            if not hs_totals:
                return await msg.edit(content="❌ **No headshot data found.**")
            
            avg = round(_stats.mean(hs_totals), 1)
            med = round(_stats.median(hs_totals), 1)
            hits = sum(1 for x in hs_totals if x > line_float)
            hit_rate = round(hits / len(hs_totals) * 100, 1) if hs_totals else 0
            
            # Decision logic
            if avg > line_float and med > line_float and hit_rate >= 60:
                side = "OVER"
                color = GREEN
            elif avg < line_float and med < line_float and hit_rate <= 40:
                side = "UNDER"
                color = RED
            else:
                side = "NO BET"
                color = MUTED
            
            # Recent bars
            rows = []
            for x in hs_totals[:10]:
                mark = "🟩" if x > line_float else "🟥"
                rows.append(f"{mark} `{x}`")
            recent_display = " ".join(rows) or "No data"
            
            e = discord.Embed(color=color, description=top_header(data, line_float, opponent, "Headshots"))
            
            e.add_field(
                name="🎯 HEADSHOT PROP",
                value=(
                    f"**{side}** — O/U `{line_float}`\n"
                    f"**AVG:** `{avg}` | **MED:** `{med}` | **HIT RATE:** `{hit_rate}%`\n"
                    f"{recent_display}"
                ),
                inline=False
            )
            
            e.add_field(
                name="🔫 HS PROFILE",
                value=(
                    f"**HS% (Overall):** `{data.get('HS Rate', 'N/A')}`\n"
                    f"**HS Avg (M1+M2):** `{data.get('Recent HS Average', 'N/A')}`\n"
                    f"**KPR:** `{data.get('KPR', 'N/A')}`\n"
                    f"**Role:** `{data.get('Role', 'N/A')}`"
                ),
                inline=False
            )
            
            e.set_footer(text="CS2 Prop Grader • Headshots • Maps 1–2 only • HLTV data")
            await msg.edit(content=None, embed=e)
            print(f"✅ HS SCAN COMPLETE: {player}", flush=True)
            
        except ValueError:
            await msg.edit(content="❌ **Invalid line.** Use a number like `10.5`")
        except Exception as e:
            print(f"💥 HS SCAN ERROR: {e}", flush=True)
            await msg.edit(content=f"❌ **HS scan crashed:** `{e}`")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("❌ DISCORD_TOKEN environment variable not found.")
    print("🚀 Starting CS2 Prop Grader Discord Bot...", flush=True)
    bot.run(token)
