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
    try:
        return float(str(v).replace("%", ""))
    except Exception:
        return default


def num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def bar(value: float, total: int = 10) -> str:
    value = max(0, min(total, int(round(value))))
    return "▰" * value + "▱" * (total - value)


def grade_score(data: Dict[str, Any]) -> float:
    text = str(data.get("Final grade", ""))
    import re
    m = re.search(r"(\d+(?:\.\d+)?)/10", text)
    if m:
        return float(m.group(1))
    over = pct_float(data.get("Over probability"))
    under = pct_float(data.get("Under probability"))
    return round(max(over, under) / 10, 1)


def side_and_color(data: Dict[str, Any]) -> tuple[str, int]:
    rec = str(data.get("Bet recommendation", data.get("Bet Recommendation", "NO BET"))).upper()
    if "OVER" in rec:
        return "OVER", GREEN
    if "UNDER" in rec:
        return "UNDER", RED
    return "NO BET", MUTED


def clean_map_name(m: str) -> str:
    names = {"dust2": "Dust2", "mirage": "Mirage", "inferno": "Inferno", "nuke": "Nuke", "ancient": "Ancient", "anubis": "Anubis", "vertigo": "Vertigo", "overpass": "Overpass"}
    return names.get(str(m).lower(), str(m).title())


def split_chunks(text: str, limit: int = 3900) -> List[str]:
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
    return (
        f"# CS2 Prop Grader\n"
        f"`MAPS 1–2` • `BO3` • `100K SIMS` • `HLTV DATA`\n\n"
        f"## {data.get('Player','Player')}  vs {opponent.title()}   `{prop_type} O/U {line}`\n"
        f"**HIGH CONFIDENCE** — HLTV KPR `{data.get('KPR','N/A')}`, Rating `{data.get('Rating 3.0','N/A')}`, Impact `{data.get('Impact','N/A')}`"
    )


def make_grade_embed(data: Dict[str, Any], line: float, opponent: str, prop_type: str = "Kills") -> discord.Embed:
    side, color = side_and_color(data)
    score = grade_score(data)
    label = "Strong Play" if score >= 7.5 else "Lean" if score >= 6 else "Avoid"
    mis = str(data.get("Mispriced or not", "NO"))
    totals = data.get("Recent Totals (M1+M2 Combined)", [])
    avg = data.get("Recent average", "N/A")
    med = data.get("Recent median", "N/A")
    hit = data.get("Hit rate", "N/A")
    floor = data.get("Floor (Bottom 3 avg)", "N/A")
    ceil = data.get("Ceiling (Top 3 avg)", "N/A")
    q25 = q75 = "N/A"
    if len(totals) >= 4:
        s = sorted(totals)
        q25, q75 = s[len(s)//4], s[(len(s)*3)//4]

    recent_lines = []
    for v in totals[:10]:
        mark = "🟩" if num(v) > line else "🟥"
        recent_lines.append(f"{mark} `{v}`")
    recent = " ".join(recent_lines) or "No recent series found"

    scenarios = data.get("Scenarios", {}) or {}
    short = scenarios.get("short", {}).get("expected_kills", "N/A")
    normal = scenarios.get("normal", {}).get("expected_kills", "N/A")
    long = scenarios.get("long", {}).get("expected_kills", "N/A")

    e = discord.Embed(color=color, description=top_header(data, line, opponent, prop_type))
    e.add_field(name="☠️ Kills Prop", value=f"O/U `{line}`\n`{bar(score)}` **{score}/10**\n**{side} — {label}**  `{mis}`", inline=False)
    e.add_field(name="ELITE EDGE — CLEAR MISPRICE", value=(
        f"**Sim Mean:** `{data.get('Simulated mean','N/A')}`\n"
        f"**Sim Median:** `{round(num(data.get('Simulated mean')),1) if data.get('Simulated mean')!='N/A' else 'N/A'}`\n"
        f"**Std Dev:** `{data.get('Standard deviation','N/A')}`\n"
        f"**25th / 75th:** `{q25} / {q75}`\n"
        f"**Over %:** `{data.get('Over probability','N/A')}`\n"
        f"**Under %:** `{data.get('Under probability','N/A')}`\n"
        f"**Edge:** `{data.get('Edge vs line','N/A')}`\n"
        f"**EV+:** `{'Yes' if abs(pct_float(data.get('Edge vs line'))) >= 6 else 'No'}`"
    ), inline=True)
    e.add_field(name="Recent Performance vs Line", value=(
        f"**AVG:** `{avg}`  **MEDIAN:** `{med}`  **HIT RATE:** `{hit}`\n"
        f"**FLOOR/CEIL:** `{floor}/{ceil}`\n"
        f"{recent}"
    ), inline=False)
    e.add_field(name="Short / Normal / Long Map Projections", value=f"Short `{short}` • Normal `{normal}` • Long `{long}`", inline=False)
    e.set_footer(text="CS2 Prop Grader • Maps 1–2 only • HLTV data")
    return e


def make_data_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    e = discord.Embed(color=BRAND, description=top_header(data, line, opponent, "Kills"))
    raw = data.get("Raw maps", [])[:14]
    rows = []
    for m in raw:
        rows.append(f"`{clean_map_name(m.get('map_name','?')):<8} {m.get('kills',0):>2}-{m.get('deaths',0):<2} HS {m.get('headshots',0):>2} R {m.get('rounds',0):>2} vs {str(m.get('opponent','?')).upper()[:12]}`")
    e.add_field(name="RAW MAP DATA (14 MAPS)", value="\n".join(rows)[:1024] or "No raw maps found", inline=False)

    paired = data.get("Paired series rows", [])[:10]
    prow = []
    for p in paired:
        mark = "🟢" if num(p.get("kills")) > line else "🔴"
        prow.append(f"{mark} vs **{p.get('opponent','N/A')}** · `{p.get('date','N/A')}` — **{p.get('kills')}K**  **{p.get('headshots')}HS**  `{p.get('rounds')}rds`")
    e.add_field(name="PAIRED SERIES (MAPS 1–2 COMBINED)", value="\n".join(prow)[:1024] or "No paired series found", inline=False)

    e.add_field(name="HLTV VERIFIED STATS", value=(
        f"**KPR:** `{data.get('KPR','N/A')}`\n"
        f"**DPR:** `{data.get('DPR','N/A')}`\n"
        f"**Rating:** `{data.get('Rating 3.0','N/A')}`\n"
        f"**Impact:** `{data.get('Impact','N/A')}`\n"
        f"**ADR:** `{data.get('ADR','N/A')}`\n"
        f"**KAST:** `{data.get('KAST','N/A')}`\n"
        f"**HS%:** `{data.get('HS %','N/A')}`\n"
        f"**Multi-kill:** `{data.get('Multi-kill %','N/A')}`\n"
        f"**Round Swing:** `{data.get('Round Swing %','N/A')}`"
    ), inline=True)
    maps = data.get("Per-map averages", {}) or {}
    mlines = [f"`{clean_map_name(k)}` {v.get('avg_kills')}K avg • {v.get('avg_kpr')} KPR • {v.get('sample_size')} maps" for k, v in list(maps.items())[:7]]
    e.add_field(name="MAP POOL / KPR BY MAP", value="\n".join(mlines)[:1024] or "No map pool data found", inline=False)
    e.set_footer(text="DATA tab • raw HLTV-derived sample")
    return e


def make_context_embed(data: Dict[str, Any], line: float, opponent: str) -> discord.Embed:
    e = discord.Embed(color=PANEL, description=top_header(data, line, opponent, "Kills"))
    ranks = data.get("Team rankings", {}) or {}
    opp = data.get("Opponent strength", {}) or {}
    h2h = data.get("H2H Data", {}) or {}
    usage = data.get("Usage Stats", {}) or {}
    e.add_field(name="MATCH CONTEXT", value=(
        f"`{data.get('Role','N/A')}`  `{ranks.get('player_team_rank','N/A')} vs {ranks.get('opponent_rank','N/A')}`  `{ranks.get('odds_context','N/A')}`\n\n"
        f"**ROLE**\nKPR `{data.get('KPR','N/A')}` • DPR `{data.get('DPR','N/A')}` • Impact `{data.get('Impact','N/A')}` • Rating `{data.get('Rating 3.0','N/A')}`\n"
        f"Opening `{usage.get('opening_duels','N/A')}` • Trading `{usage.get('trade_opportunities','N/A')}` • Clutch `{usage.get('clutch_attempts','N/A')}`\n\n"
        f"**ODDS / TEAM RANKING**\n{ranks.get('rank_difference','N/A')} — {ranks.get('odds_context','N/A')}\n\n"
        f"**OPPONENT STRENGTH**\n{opp.get('defensive_rating','N/A')} • {opp.get('kill_suppression','N/A')} • Weakness: {opp.get('exploitable_weakness','N/A')}\n\n"
        f"**H2H**\nSample `{h2h.get('h2h_sample_size',0)}` maps • Avg `{h2h.get('h2h_avg_kills','N/A')}` • KPR `{h2h.get('h2h_kpr','N/A')}`"
    )[:1024], inline=False)
    e.add_field(name="KEY FACTORS", value=str(data.get("Analysis", "No analysis generated"))[:1024], inline=False)
    e.add_field(name="DATA NOTES", value=(
        "Uses Maps 1–2 only. Match odds are shown only as rank/odds context from available scraper data; "
        "add a real odds feed to display sportsbook prices. No made-up odds are inserted."
    ), inline=False)
    e.set_footer(text="CONTEXT tab • role, ranks, H2H, opponent profile")
    return e


class PropView(discord.ui.View):
    def __init__(self, data: Dict[str, Any], line: float, opponent: str):
        super().__init__(timeout=600)
        self.data = data
        self.line = line
        self.opponent = opponent

    async def swap(self, interaction: discord.Interaction, embed: discord.Embed):
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
    print(f"✅ CS2 PROP GRADER ONLINE: {bot.user}", flush=True)


@bot.command()
async def scan(ctx, player=None, line=None, *, opponent="N/A"):
    if not player or not line:
        return await ctx.send("❌ Usage: `!scan player line opponent`\nExample: `!scan caleyy 30.5 The Last Resort`")
    msg = await ctx.send(f"🔎 **CS2 Prop Grader loading** — `{player}` kills O/U `{line}` vs `{opponent}`")
    async with ctx.typing():
        try:
            line_float = float(line)
            data = await asyncio.to_thread(get_player_info, player, line_float, opponent)
            if data.get("error"):
                return await msg.edit(content=f"❌ {data['error']}")
            view = PropView(data, line_float, opponent)
            await msg.edit(content=None, embed=make_grade_embed(data, line_float, opponent), view=view)
        except ValueError:
            await msg.edit(content="❌ Invalid line. Use a number like `30.5`.")
        except Exception as e:
            print(f"SCAN ERROR: {e}", flush=True)
            await msg.edit(content=f"❌ Scan crashed: `{e}`")


@bot.command()
async def hs(ctx, player=None, line=None, *, opponent="N/A"):
    if not player or not line:
        return await ctx.send("❌ Usage: `!hs player line opponent`\nExample: `!hs caleyy 14.5 The Last Resort`")
    msg = await ctx.send(f"🎯 **CS2 Headshot Grader loading** — `{player}` HS O/U `{line}` vs `{opponent}`")
    async with ctx.typing():
        try:
            line_float = float(line)
            data = await asyncio.to_thread(get_player_info, player, 0, opponent)
            if data.get("error"):
                return await msg.edit(content=f"❌ {data['error']}")
            hs_totals = data.get("Recent HS Totals (M1+M2)", [])
            if not hs_totals:
                return await msg.edit(content="❌ No headshot data found.")
            avg = round(_stats.mean(hs_totals), 1)
            med = _stats.median(hs_totals)
            hits = sum(1 for x in hs_totals if x > line_float)
            hit_rate = round(hits / len(hs_totals) * 100, 1)
            side = "OVER" if avg > line_float and med > line_float and hit_rate >= 60 else "UNDER" if avg < line_float and med < line_float and hit_rate <= 40 else "NO BET"
            color = GREEN if side == "OVER" else RED if side == "UNDER" else MUTED
            rows = " ".join(("🟩" if x > line_float else "🟥") + f" `{x}`" for x in hs_totals[:10])
            e = discord.Embed(color=color, description=top_header(data, line_float, opponent, "Headshots"))
            e.add_field(name="🎯 HEADSHOT PROP", value=f"**{side}** — O/U `{line_float}`\nAVG `{avg}` • MEDIAN `{med}` • HIT RATE `{hit_rate}%`\n{rows}", inline=False)
            e.add_field(name="HS PROFILE", value=f"HS% `{data.get('HS Rate','N/A')}` • KPR `{data.get('KPR','N/A')}` • Role `{data.get('Role','N/A')}`", inline=False)
            e.set_footer(text="CS2 Prop Grader • Headshots • Maps 1–2 only")
            await msg.edit(content=None, embed=e)
        except ValueError:
            await msg.edit(content="❌ Invalid line. Use a number like `14.5`.")
        except Exception as e:
            print(f"HS ERROR: {e}", flush=True)
            await msg.edit(content=f"❌ HS scan crashed: `{e}`")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("❌ DISCORD_TOKEN environment variable not found.")
    bot.run(token)
