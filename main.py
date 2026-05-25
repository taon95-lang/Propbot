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
    try:
        return float(str(value).replace("%", "").strip())
    except Exception:
        return default

def bar(score: float, total: int = 10) -> str:
    filled = max(0, min(total, int(round(score))))
    return "▰" * filled + "▱" * (total - filled)

def score_num(data: Dict[str, Any]) -> float:
    try:
        return float(str(data.get("Final grade", "0")).split("/")[0])
    except Exception:
        return 0.0

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
    }
    return names.get(str(value).lower(), str(value).title())

def trim_lines(lines: List[str], limit: int = 1024) -> str:
    """Trim lines to fit Discord field char limit (1024)."""
    out = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > limit:
            break
        out.append(line)
        total += len(line) + 1
    return "\n".join(out) if out else "N/A"

def safe_field_value(value: str, max_chars: int = 1024) -> str:
    """**FIXED: Truncate field value to Discord limit with ellipsis."""
    if len(value) <= max_chars:
        return value
    return value[:max_chars - 4] + "..."

def header(data: Dict[str, Any], line: float, opponent: str, prop: str) -> str:
    return (
        f"# CS2 Prop Grader\n"
        f"`Maps 1–2 only` • `HLTV exact data` • `No fake HS fallback`\n\n"
        f"## {data.get('Player', 'Player')} vs {opponent.title()} | `{prop} O/U {line}`\n"
        f"**Rating 3.0:** `{data.get('Rating 3.0', 'N/A')}` • "
        f"**Role:** `{data.get('Role', 'N/A')}` • "
        f"**Team rank:** `{data.get('Team ranking', 'N/A')}` • "
        f"**Odds:** `{data.get('Match odds', 'N/A')}`"
    )

def grade_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    """**FIXED: Use safe_field_value to prevent char limit overflow."""
    side, color = side_color(data)
    score = score_num(data)
    totals = data.get("Recent Totals (M1+M2 Combined)", [])
    q25 = data.get("25th percentile", "N/A")
    q75 = data.get("75th percentile", "N/A")
    
    recent = " ".join(
        (("🟩" if x > line else "🟥") + f" `{x}`") for x in totals[:10]
    ) or "No sample"
    
    scenarios = data.get("Scenarios", {}) or {}
    
    e = discord.Embed(color=color, description=safe_field_value(header(data, line, opponent, "Kills")))
    
    grade_value = (
        f"**Side:** `{side}`\n"
        f"**Grade:** `{data.get('Final grade', 'N/A')}`\n"
        f"{bar(score)}\n"
        f"**Misprice:** `{data.get('Mispriced or not', 'N/A')}`"
    )
    e.add_field(name="☠️ Grade", value=safe_field_value(grade_value), inline=False)
    
    sample_value = (
        f"**Avg:** `{data.get('Recent average', 'N/A')}`\n"
        f"**Median:** `{data.get('Recent median', 'N/A')}`\n"
        f"**Projection:** `{data.get('Recent projection', 'N/A')}`\n"
        f"**Hit rate:** `{data.get('Hit rate', 'N/A')}`\n"
        f"**25th/75th:** `{q25}` / `{q75}`"
    )
    e.add_field(name="📊 Exact sample", value=safe_field_value(sample_value), inline=True)
    
    bootstrap_value = (
        f"**Mean:** `{data.get('Simulated mean', 'N/A')}`\n"
        f"**Median:** `{data.get('Simulated median', 'N/A')}`\n"
        f"**Std Dev:** `{data.get('Std Dev', 'N/A')}`\n"
        f"**Over:** `{data.get('Over probability', 'N/A')}`\n"
        f"**Under:** `{data.get('Under probability', 'N/A')}`\n"
        f"**Edge:** `{data.get('Edge vs line', 'N/A')}`"
    )
    e.add_field(name="📈 Bootstrap", value=safe_field_value(bootstrap_value), inline=True)
    
    e.add_field(name="🎯 Recent totals", value=safe_field_value(recent), inline=False)
    
    scenarios_value = (
        f"**Short:** `{scenarios.get('short', {}).get('expected_kills', 'N/A')}` | "
        f"**Normal:** `{scenarios.get('normal', {}).get('expected_kills', 'N/A')}` | "
        f"**Long:** `{scenarios.get('long', {}).get('expected_kills', 'N/A')}`"
    )
    e.add_field(name="🗺️ Round scenarios", value=safe_field_value(scenarios_value), inline=False)
    
    e.set_footer(text="All kills/headshots are exact HLTV maps 1-2 totals from each BO3 stats page")
    return e

def data_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    """**FIXED: Trim lines for all field values."""
    e = discord.Embed(color=BRAND, description=safe_field_value(header(data, line, opponent, "Kills")))
    
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
            f"`{map_name(row['map_name']):<8} {row['kills']:>2}-{row['deaths']:<2} "
            f"HS {row['headshots']:>2} R {row['rounds']:>2} vs {str(row['opponent']).upper()[:12]}`"
        )
    
    pmap = []
    for m, vals in list((data.get("Per-map averages") or {}).items())[:7]:
        pmap.append(
            f"`{map_name(m):<10} {vals['avg_kills']}K • "
            f"{vals['avg_hs']}HS • {vals['avg_kpr']} KPR • "
            f"{vals['sample_size']} maps`"
        )
    
    e.add_field(name="🎯 Exact paired series", value=trim_lines(paired), inline=False)
    e.add_field(name="📋 Exact raw maps", value=trim_lines(raw), inline=False)
    
    profile_value = (
        f"**Rating 3.0:** `{data.get('Rating 3.0', 'N/A')}`\n"
        f"**Firepower:** `{data.get('Firepower', 'N/A')}`\n"
        f"**Entrying:** `{data.get('Entrying', 'N/A')}`\n"
        f"**Trading:** `{data.get('Trading', 'N/A')}`\n"
        f"**Opening:** `{data.get('Opening', 'N/A')}`\n"
        f"**KPR:** `{data.get('KPR', 'N/A')}`\n"
        f"**DPR:** `{data.get('DPR', 'N/A')}`\n"
        f"**ADR:** `{data.get('ADR', 'N/A')}`\n"
        f"**KAST:** `{data.get('KAST', 'N/A')}`\n"
        f"**Impact:** `{data.get('Impact', 'N/A')}`"
    )
    e.add_field(name="📊 Current HLTV profile/stats", value=safe_field_value(profile_value), inline=True)
    
    e.add_field(name="🗺️ Per-map sample", value=trim_lines(pmap), inline=False)
    
    e.set_footer(text="The HS totals shown here are exact K(hs) sums from maps 1 and 2")
    return e

def context_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    """**FIXED: Safe field values."""
    e = discord.Embed(color=PANEL, description=safe_field_value(header(data, line, opponent, "Kills")))
    
    h2h = data.get("H2H Data", {}) or {}
    veto = data.get("Veto", []) or []
    likely = data.get("Likely maps", {}) or {}
    
    context_value = (
        f"**Role:** `{data.get('Role', 'N/A')}`\n"
        f"**Team:** `{data.get('Team', 'N/A')}`\n"
        f"**Team rank:** `{data.get('Team ranking', 'N/A')}`\n"
        f"**Opponent rank:** `{data.get('Opponent ranking', 'N/A')}`\n"
        f"**Odds:** `{data.get('Match odds', 'N/A')}`\n"
        f"**Moneyline:** `{data.get('Moneyline', 'N/A')}` / "
        f"`{data.get('Moneyline american', 'N/A')}`"
    )
    e.add_field(name="🧠 Context", value=safe_field_value(context_value), inline=False)
    
    h2h_value = (
        f"**Similar team split:** `{data.get('Similar teams', 'N/A')}`\n"
        f"**H2H sample:** `{h2h.get('h2h_sample_size', 0)}`\n"
        f"**H2H avg kills:** `{h2h.get('h2h_avg_kills', 'N/A')}`\n"
        f"**H2H avg HS:** `{h2h.get('h2h_avg_headshots', 'N/A')}`\n"
        f"**Note:** `{h2h.get('h2h_note', 'N/A')}`"
    )
    e.add_field(name="📚 Similar teams / H2H", value=safe_field_value(h2h_value), inline=False)
    
    maps_str = " • ".join(str(v) for v in likely.values()) if likely else "N/A"
    e.add_field(name="🎯 Likely maps", value=safe_field_value(maps_str), inline=False)
    
    e.add_field(name="📝 Veto / map notes", value=trim_lines(veto), inline=False)
    
    e.set_footer(text="Role is derived from current HLTV profile buckets, not guessed from old form")
    return e

class PropView(discord.ui.View):
    def __init__(self, data: Dict[str, Any], line: float, opponent: str):
        super().__init__(timeout=3600)
        self.data = data
        self.line = line
        self.opponent = opponent
    
    async def swap(self, interaction: discord.Interaction, embed: discord.Embed):
        await interaction.response.edit_message(embed=embed, view=self)
    
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
    if not player or not line:
        return await ctx.send("❌ Usage: `!scan player line opponent`")
    
    msg = await ctx.send(f"🔎 Loading exact HLTV grade for `{player}` vs `{opponent}`...")
    
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
    
    msg = await ctx.send(f"🎯 Loading exact HLTV headshot grade for `{player}` vs `{opponent}`...")
    
    async with ctx.typing():
        try:
            line_val = float(line)
            data = await asyncio.to_thread(get_player_info, player, 0.0, opponent)
            
            if data.get("error"):
                return await msg.edit(content=f"❌ {data['error']}")
            
            hs = data.get("Recent HS Totals (M1+M2)", [])
            
            if not hs:
                return await msg.edit(content="❌ No exact headshot sample found.")
            
            avg_hs = round(stats.mean(hs), 1)
            med_hs = round(stats.median(hs), 1)
            proj_hs = data.get("Recent HS Projection", "N/A")
            hit_rate = round((sum(1 for x in hs if x > line_val) / len(hs)) * 100, 1)
            
            if avg_hs > line_val and med_hs > line_val and hit_rate >= 60:
                side, color = "OVER", GREEN
            elif avg_hs < line_val and med_hs < line_val and hit_rate <= 40:
                side, color = "UNDER", RED
            else:
                side, color = "NO BET", MUTED
            
            recent = " ".join(
                (("🟩" if x > line_val else "🟥") + f" `{x}`") for x in hs[:10]
            ) or "No sample"
            
            e = discord.Embed(color=color, description=safe_field_value(header(data, line_val, opponent, "Headshots")))
            
            hs_grade_value = (
                f"**Side:** `{side}`\n"
                f"**Avg:** `{avg_hs}`\n"
                f"**Median:** `{med_hs}`\n"
                f"**Projection:** `{proj_hs}`\n"
                f"**Hit rate:** `{hit_rate}%`\n"
                f"{recent}"
            )
            e.add_field(name="🔫 Headshot grade", value=safe_field_value(hs_grade_value), inline=False)
            
            hs_profile_value = (
                f"**Recent HS %:** `{data.get('Recent HS %', 'N/A')}`\n"
                f"**Recent HS avg:** `{data.get('Recent HS Average', 'N/A')}`\n"
                f"**Recent HS median:** `{data.get('Recent HS Median', 'N/A')}`\n"
                f"**All-time profile HS %:** `{data.get('All-time profile HS %', 'N/A')}`\n"
                f"**Role:** `{data.get('Role', 'N/A')}`\n"
                f"**Odds:** `{data.get('Match odds', 'N/A')}`"
            )
            e.add_field(name="📊 HS profile", value=safe_field_value(hs_profile_value), inline=False)
            
            e.set_footer(text="Exact Maps 1-2 headshots only; no estimated HS fallback")
            
            await msg.edit(content=None, embed=e)
        
        except ValueError:
            await msg.edit(content="❌ Invalid line; must be a number (e.g., `7.5`)")
        except Exception as exc:
            await msg.edit(content=f"❌ HS scan crashed: `{exc}`")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("❌ DISCORD_TOKEN missing.")
    bot.run(token)
