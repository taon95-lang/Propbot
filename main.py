import os
import json
import discord
from discord.ext import commands
from discord import ui

from scraper import get_player_info, get_headshot_info, CS2DataExtractor


TOKEN = os.getenv("DISCORD_BOT_TOKEN")
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# =====================================================================
# Proposition Grading Engine
# =====================================================================

class PropositionGrader:
    def __init__(self):
        self.extractor = CS2DataExtractor()

    def grade_proposition(self, player_name, prop_type, line_value):
        profile_url = self.extractor.resolve_player_entity(player_name)
        if not profile_url:
            return self._format_response(player_name, "ERROR",
                details="Player entity could not be resolved. Check spelling.")

        stats = self.extractor.extract_player_statistics(profile_url)
        if not stats:
            return self._format_response(player_name, "ERROR",
                details="Failed to extract statistical profile.")

        result = "PENDING"
        details = ""
        prop_type = str(prop_type).strip().upper()

        try:
            line_value = float(line_value)
        except ValueError:
            return self._format_response(player_name, "ERROR",
                details=f"Invalid line value: {line_value}")

        if prop_type in ("KILLS", "KILL"):
            projected = stats["rating_3"] * 0.70 * 21.0
            result = "OVER" if projected > line_value else "UNDER"
            details = f"Projected Kills: {projected:.2f} | Rating 3.0: {stats['rating_3']}"

        elif prop_type == "KAST":
            actual_kast = stats["kast_percent"]
            if actual_kast == 0.0:
                return self._format_response(player_name, "INSUFFICIENT_DATA",
                    details="KAST returned 0.0 — sample too small.")
            result = "OVER" if actual_kast > line_value else "UNDER"
            details = f"Historical KAST: {actual_kast}% | Line: {line_value}%"

        elif prop_type == "MULTI_KILL":
            actual_mk = stats["multi_kill_percent"]
            if actual_mk == 0.0:
                return self._format_response(player_name, "INSUFFICIENT_DATA",
                    details="Multi-Kill % returned 0.0.")
            result = "OVER" if actual_mk > line_value else "UNDER"
            details = f"Multi-Kill %: {actual_mk}% | Line: {line_value}%"

        elif prop_type in ("FIRST_KILL", "FK"):
            opening_score = stats["attributes"]["opening"]
            if opening_score == 0:
                return self._format_response(player_name, "INSUFFICIENT_DATA",
                    details="Opening attribute missing.")
            projected_fk = (opening_score / 100.0) * 21.0
            result = "OVER" if projected_fk > line_value else "UNDER"
            details = f"Opening: {opening_score}/100 | Projected FK: {projected_fk:.2f}"

        elif prop_type == "HEADSHOTS":
            firepower_score = stats["attributes"]["firepower"]
            result = "OVER" if firepower_score > 75 else "UNDER"
            details = f"Firepower: {firepower_score}/100"

        else:
            return self._format_response(player_name, "ERROR",
                details=f"Unsupported prop type: {prop_type}")

        return self._format_response(
            player_name=stats["name"], status="SUCCESS", grading=result,
            prop_type=prop_type, line=line_value, details=details, raw_stats=stats,
        )

    def _format_response(self, player_name, status, grading=None, prop_type=None,
                         line=None, details=None, raw_stats=None):
        return json.dumps({
            "player_entity": player_name, "execution_status": status,
            "grading_verdict": grading, "proposition_type": prop_type,
            "line_value": line, "analytical_details": details,
            "raw_extracted_metrics": raw_stats,
        }, indent=4)

    def shutdown(self):
        self.extractor.close()


# =====================================================================
# Shared helpers
# =====================================================================

def _pick(data, *keys, default="N/A"):
    for key in keys:
        if key in data:
            value = data.get(key)
            if value not in (None, "", [], {}):
                return value
    return default

def _fmt_list(values, limit=10):
    if not values:
        return "No sample"
    return ", ".join(str(x) for x in values[:limit])

def _fmt_maps(likely_maps):
    if not likely_maps:
        return "N/A"
    if isinstance(likely_maps, dict):
        parts = [f"{k}: {v}" for k, v in likely_maps.items()]
        return "\n".join(parts) if parts else "N/A"
    if isinstance(likely_maps, list):
        return "\n".join(str(x) for x in likely_maps[:8]) or "N/A"
    return str(likely_maps)

def _fmt_veto(veto):
    if not veto:
        return "N/A"
    if isinstance(veto, list):
        return "\n".join(str(x) for x in veto[:7])
    return str(veto)

def _fmt_per_map(per_map):
    if not per_map:
        return "No map sample"
    lines = []
    for map_name, vals in per_map.items():
        avg_k = vals.get("avg_kills", "N/A")
        avg_hs = vals.get("avg_hs", "N/A")
        avg_kpr = vals.get("avg_kpr", "N/A")
        sample = vals.get("sample_size", 0)
        lines.append(f"• {map_name}: {avg_k}K | {avg_hs}HS | {avg_kpr}KPR ({sample}g)")
    return "\n".join(lines[:8]) or "No map sample"

def _fmt_paired_rows(rows, headshots=False):
    if not rows:
        return "No exact 2-map series sample"
    out = []
    for row in rows[:8]:
        total = row.get("headshots") if headshots else row.get("kills")
        out.append(f"{row.get('date','N/A')} vs {row.get('opponent','UNK')}: "
                   f"{row.get('map1','N/A')}+{row.get('map2','N/A')} = {total} ({row.get('rounds','N/A')}R)")
    return "\n".join(out)

def _fmt_raw_maps(rows):
    if not rows:
        return "No raw map sample"
    out = []
    for row in rows[:12]:
        out.append(f"{row.get('date','N/A')} vs {row.get('opponent','UNK')} "
                   f"on {row.get('map_name','N/A')}: "
                   f"{row.get('kills','N/A')}K/{row.get('headshots','N/A')}HS/"
                   f"{row.get('rounds','N/A')}R/{row.get('rating','N/A')}rtg")
    return "\n".join(out)

def _truncate(value, limit=1024):
    text = str(value or "N/A").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"

def _fmt_bullets(values, limit=5):
    if not values:
        return "N/A"
    out = [f"• {str(x)}" for x in values[:limit] if str(x).strip()]
    return _truncate("\n".join(out) or "N/A", 1024)

def _fmt_h2h_rows(rows, headshots=False):
    if not rows:
        return "No H2H series in window"
    stat_key = "headshots" if headshots else "kills"
    suffix = "HS" if headshots else "K"
    out = [
        f"{r.get('date','N/A')} vs {r.get('opponent','UNK')}: "
        f"{r.get('map1','N/A')}+{r.get('map2','N/A')} = {r.get(stat_key,'N/A')} {suffix}"
        for r in rows[:5]
    ]
    return _truncate("\n".join(out), 1024)

def _fmt_bucket(val: str) -> str:
    """Format bucket value — always show NN/100 if available."""
    if not val or val == "N/A":
        return "N/A"
    import re
    m = re.search(r"(\d{1,3})/100", str(val))
    return f"{m.group(1)}/100" if m else val

def _fmt_pace_model(pace: dict) -> str:
    if not pace:
        return "N/A"
    return (
        f"KPR used: {pace.get('kpr_used', 'N/A')}\n"
        f"Fast pace ({pace.get('fast_pace_rounds','N/A')}R): {pace.get('proj_fast','N/A')} kills\n"
        f"Normal pace ({pace.get('normal_pace_rounds','N/A')}R): {pace.get('proj_normal','N/A')} kills\n"
        f"Slow/OT pace ({pace.get('slow_pace_rounds','N/A')}R): {pace.get('proj_slow','N/A')} kills\n"
        f"Both maps OT: {pace.get('proj_ot','N/A')} kills\n"
        f"OT rate: {pace.get('ot_rate_pct','N/A')}% | Blowout rate: {pace.get('blowout_rate_pct','N/A')}%\n"
        f"Pace edge vs line: {pace.get('pace_edge','N/A')}"
    )

def _fmt_blowout(blowout: dict) -> str:
    if not blowout:
        return "N/A"
    return (
        f"Blowout avg kills: {blowout.get('blowout_avg_kills','N/A')} ({blowout.get('blowout_sample',0)} games)\n"
        f"Normal avg kills: {blowout.get('normal_avg_kills','N/A')} ({blowout.get('normal_sample',0)} games)\n"
        f"Map blowout prob: {blowout.get('expected_blowout_rate_pct','N/A')}%\n"
        f"{blowout.get('blowout_note','N/A')}"
    )

def _fmt_ot(ot: dict) -> str:
    if not ot:
        return "N/A"
    return (
        f"Per-map OT rate: {ot.get('per_map_ot_rate_pct','N/A')}%\n"
        f"Series OT probability: {ot.get('series_ot_probability_pct','N/A')}%\n"
        f"Expected bonus OT rounds: {ot.get('expected_extra_ot_rounds','N/A')}\n"
        f"{ot.get('ot_note','N/A')}"
    )

def _fmt_multikill(mk: dict) -> str:
    if not mk:
        return "N/A"
    return (
        f"Est. 2K rounds/series: {mk.get('est_2k_series','N/A')}\n"
        f"Est. 3K rounds/series: {mk.get('est_3k_series','N/A')}\n"
        f"Est. 2K per map: {mk.get('est_2k_per_map','N/A')} | 3K: {mk.get('est_3k_per_map','N/A')}\n"
        f"High-KPR map rate: {mk.get('high_kill_map_rate_pct','N/A')}%\n"
        f"{mk.get('multikill_note','N/A')}"
    )

def _fmt_eco_clutch(eco: dict) -> str:
    if not eco:
        return "N/A"
    notes = "\n".join(f"• {n}" for n in eco.get("eco_clutch_notes", []))
    return (
        f"HS%: {eco.get('hs_pct','N/A')}% | Eco farming: {'YES' if eco.get('eco_farming_signal') else 'NO'} "
        f"| Anti-eco padding: {'YES' if eco.get('anti_eco_padding') else 'NO'}\n"
        f"Est. clutch conversion: {eco.get('clutch_conversion_pct','N/A')}% "
        f"(Clutch {eco.get('clutch_score','N/A')}/100)\n"
        f"Kill std dev: {eco.get('kill_std_dev','N/A')} | Variance (CV): {eco.get('kill_cv','N/A')}\n"
        f"{notes}"
    )

def _fmt_opp_strength(opp: dict) -> str:
    if not opp:
        return "N/A"
    return (
        f"Opponent tier: {opp.get('opponent_tier','N/A')} (#{opp.get('opponent_rank','N/A')})\n"
        f"Tier rating: {opp.get('tier_rating','N/A')}\n"
        f"Kill adj. multiplier: {opp.get('adjustment_multiplier','N/A')}x\n"
        f"{opp.get('adjustment_note','N/A')}"
    )

def _fmt_map_kpr(mwk: dict) -> str:
    if not mwk:
        return "N/A"
    wkpr = mwk.get("weighted_kpr", "N/A")
    map_kpr = mwk.get("map_kpr", {})
    map_weights = mwk.get("map_weights", {})
    lines = [f"Weighted KPR: {wkpr}"]
    for m_name, kpr in list(map_kpr.items())[:6]:
        w = map_weights.get(m_name, "")
        lines.append(f"• {m_name}: {kpr} KPR" + (f" (weight {w})" if w else ""))
    return "\n".join(lines)


# =====================================================================
# Embed builders
# =====================================================================

def build_scan_embed(player, line, opponent, info):
    resolved_opponent = _pick(info, "Opponent", default=opponent.title())
    embed = discord.Embed(
        title=f"{player.title()} vs {resolved_opponent} | Kills O/U {line}",
        description="Maps 1–2 only · HLTV exact sample + profile context",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Header",
        value=_truncate(
            f"Rating 3.0: {_pick(info,'Rating 3.0')}\n"
            f"Role: {_pick(info,'Role')}\n"
            f"Team: {_pick(info,'Team')}\n"
            f"Team rank: {_pick(info,'Team ranking')}\n"
            f"Opponent rank: {_pick(info,'Opponent ranking')}\n"
            f"Thunderpick odds: {_pick(info,'Thunderpick odds','Match odds')}\n"
            f"Public pick: {_pick(info,'Public pick')}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Quick view",
        value=_truncate(
            f"Recent avg: {_pick(info,'Recent average')}\n"
            f"Recent median: {_pick(info,'Recent median')}\n"
            f"Projection: {_pick(info,'Projected kills','Recent projection')}\n"
            f"Hit rate: {_pick(info,'Hit rate')}\n"
            f"Over/Under: {_pick(info,'Over probability')} / {_pick(info,'Under probability')}\n"
            f"Edge: {_pick(info,'Edge vs line')}\n"
            f"Recommendation: {_pick(info,'Bet recommendation')}\n"
            f"Grade: {_pick(info,'Final grade')}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Analytics",
        value=_truncate(
            f"Headline: {_pick(info,'Analytics headline')}\n"
            f"H2H: {_pick(info,'H2H summary')}\n"
            f"Map source: {_pick(info,'Likely maps source')}\n"
            f"Map combo: {_pick(info,'Likely map combo note')}"
        ),
        inline=False,
    )
    embed.add_field(name="Player report", value=_truncate(_pick(info, "Player report")), inline=False)
    embed.add_field(name="Player pros", value=_fmt_bullets(_pick(info, "Player pros", default=[])), inline=True)
    embed.add_field(name="Player cons", value=_fmt_bullets(_pick(info, "Player cons", default=[])), inline=True)
    embed.add_field(
        name="Recent exact totals",
        value=_truncate(_fmt_list(_pick(info, "Recent Totals (M1+M2 Combined)", default=[]))),
        inline=False,
    )
    embed.set_footer(text="Use buttons below for GRADE · DATA · CONTEXT · RAW · ANALYTICS")
    return embed


def build_context_embed(player, opponent, info):
    resolved_opponent = _pick(info, "Opponent", default=opponent.title())
    h2h = _pick(info, "H2H Data", default={})
    embed = discord.Embed(
        title=f"{player.title()} vs {resolved_opponent} | Context",
        description="Match context from HLTV match, team-map, and player pages",
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="Context",
        value=_truncate(
            f"Role: {_pick(info,'Role')}\n"
            f"Role note: {_pick(info,'Role note')}\n"
            f"Team: {_pick(info,'Team')}\n"
            f"Team rank: {_pick(info,'Team ranking')}\n"
            f"Opponent rank: {_pick(info,'Opponent ranking')}\n"
            f"Thunderpick odds: {_pick(info,'Thunderpick odds','Match odds')}\n"
            f"Public pick: {_pick(info,'Public pick')}\n"
            f"H2H summary: {h2h.get('h2h_summary','N/A') if isinstance(h2h,dict) else 'N/A'}"
        ),
        inline=False,
    )
    embed.add_field(name="Likely maps", value=_truncate(_fmt_maps(_pick(info, "Likely maps", default={}))), inline=False)
    embed.add_field(name="Veto / map notes", value=_truncate(_fmt_veto(_pick(info, "Veto", default=[]))), inline=False)
    embed.add_field(name="Team pros", value=_fmt_bullets(_pick(info, "Team pros", default=[])), inline=True)
    embed.add_field(name="Team cons", value=_fmt_bullets(_pick(info, "Team cons", default=[])), inline=True)
    embed.add_field(name=f"{resolved_opponent} pros", value=_fmt_bullets(_pick(info, "Opponent pros", default=[])), inline=True)
    embed.add_field(name=f"{resolved_opponent} cons", value=_fmt_bullets(_pick(info, "Opponent cons", default=[])), inline=True)
    h2h_rows = h2h.get("h2h_rows", []) if isinstance(h2h, dict) else []
    embed.add_field(name="H2H rows", value=_fmt_h2h_rows(h2h_rows, headshots=False), inline=False)
    return embed


def build_grade_embed(player, line, info, headshots=False):
    stat_name = "Headshots" if headshots else "Kills"
    recent_totals_key = "Recent HS Totals (M1+M2)" if headshots else "Recent Totals (M1+M2 Combined)"
    projection_key = "Projected headshots" if headshots else "Projected kills"

    embed = discord.Embed(
        title=f"{player.title()} | {stat_name} Grade",
        description="Maps 1–2 only, based on exact HLTV samples",
        color=discord.Color.purple(),
    )
    embed.add_field(
        name="Projection / edge",
        value=_truncate(
            f"Line: {line}\n"
            f"Projection: {_pick(info, projection_key, 'Recent projection')}\n"
            f"Recent avg: {_pick(info, 'Recent average') if not headshots else _pick(info,'Recent HS Average')}\n"
            f"Recent median: {_pick(info, 'Recent median') if not headshots else _pick(info,'Recent HS Median')}\n"
            f"Over probability: {_pick(info,'Over probability')}\n"
            f"Under probability: {_pick(info,'Under probability')}\n"
            f"Hit rate: {_pick(info,'Hit rate')}\n"
            f"Edge: {_pick(info,'Edge vs line')}\n"
            f"Recommendation: {_pick(info,'Bet recommendation')}\n"
            f"Grade: {_pick(info,'Final grade')}\n"
            f"Mispriced: {_pick(info,'Mispriced or not')}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Analytics",
        value=_truncate(
            f"Thunderpick odds: {_pick(info,'Thunderpick odds','Match odds')}\n"
            f"Public pick: {_pick(info,'Public pick')}\n"
            f"H2H: {_pick(info,'H2H summary')}\n"
            f"Side prob: {_pick(info,'Recommended side probability')}\n"
            f"Map combo: {_pick(info,'Likely map combo note')}"
        ),
        inline=False,
    )
    embed.add_field(name="Player report", value=_truncate(_pick(info, "Player report")), inline=False)
    embed.add_field(name="Player pros", value=_fmt_bullets(_pick(info, "Player pros", default=[])), inline=True)
    embed.add_field(name="Player cons", value=_fmt_bullets(_pick(info, "Player cons", default=[])), inline=True)
    embed.add_field(
        name="Distribution",
        value=_truncate(
            f"Recent totals: {_fmt_list(_pick(info, recent_totals_key, default=[]))}\n"
            f"P25: {_pick(info,'25th percentile')}\n"
            f"P75: {_pick(info,'75th percentile')}\n"
            f"Sim mean: {_pick(info,'Simulated mean')}\n"
            f"Sim median: {_pick(info,'Simulated median')}\n"
            f"Std dev: {_pick(info,'Std Dev')}"
        ),
        inline=False,
    )
    if not headshots:
        scenarios = _pick(info, "Scenarios", default={})
        if scenarios and isinstance(scenarios, dict):
            embed.add_field(
                name="Round-based scenarios",
                value=_truncate(
                    f"Short: {scenarios.get('short',{}).get('rounds','N/A')}R → {scenarios.get('short',{}).get('expected_kills','N/A')}K\n"
                    f"Normal: {scenarios.get('normal',{}).get('rounds','N/A')}R → {scenarios.get('normal',{}).get('expected_kills','N/A')}K\n"
                    f"Long: {scenarios.get('long',{}).get('rounds','N/A')}R → {scenarios.get('long',{}).get('expected_kills','N/A')}K"
                ),
                inline=False,
            )
    else:
        embed.add_field(
            name="Headshot profile",
            value=_truncate(
                f"Recent HS%: {_pick(info,'Recent HS %')}\n"
                f"All-time HS%: {_pick(info,'All-time profile HS %')}\n"
                f"Recent HS totals: {_fmt_list(_pick(info,'Recent HS Totals (M1+M2)',default=[]))}"
            ),
            inline=False,
        )
    return embed


def build_data_embed(player, info):
    embed = discord.Embed(
        title=f"{player.title()} | Data",
        description="Profile buckets · recent filtered stats · exact series sample · raw map hydration",
        color=discord.Color.green(),
    )
    # Attribute buckets — always show NN/100
    embed.add_field(
        name="Attribute buckets (X/100)",
        value=_truncate(
            f"🔥 Firepower: {_fmt_bucket(_pick(info,'Firepower'))}\n"
            f"⚔️  Entrying:  {_fmt_bucket(_pick(info,'Entrying'))}\n"
            f"🔄 Trading:   {_fmt_bucket(_pick(info,'Trading'))}\n"
            f"🎯 Opening:   {_fmt_bucket(_pick(info,'Opening'))}\n"
            f"💪 Clutching: {_fmt_bucket(_pick(info,'Clutching'))}\n"
            f"🎿 Sniping:   {_fmt_bucket(_pick(info,'Sniping'))}\n"
            f"🛠️  Utility:   {_fmt_bucket(_pick(info,'Utility'))}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Recent filtered stats",
        value=_truncate(
            f"KPR: {_pick(info,'KPR')}\n"
            f"DPR: {_pick(info,'DPR')}\n"
            f"ADR: {_pick(info,'ADR')}\n"
            f"KAST: {_pick(info,'KAST')}\n"
            f"Impact: {_pick(info,'Impact')}\n"
            f"Round swing: {_pick(info,'Round swing')}\n"
            f"HS%: {_pick(info,'HS %')}\n"
            f"Opening KPR: {_pick(info,'Opening kills per round')}\n"
            f"Trade KPR: {_pick(info,'Trade kills per round')}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Opponent tier ratings",
        value=_truncate(
            f"vs Top 5:  {_pick(info,'Vs Top 5 rating')}\n"
            f"vs Top 10: {_pick(info,'Vs Top 10 rating')}\n"
            f"vs Top 20: {_pick(info,'Vs Top 20 rating')}\n"
            f"vs Top 30: {_pick(info,'Vs Top 30 rating')}\n"
            f"vs Top 50: {_pick(info,'Vs Top 50 rating')}\n"
            f"Similar tier: {_pick(info,'Similar teams')} → {_pick(info,'Similar teams rating')}"
        ),
        inline=False,
    )
    embed.add_field(name="Exact paired series sample", value=_fmt_paired_rows(_pick(info, "Paired series rows", default=[])), inline=False)
    embed.add_field(name="Per-map averages", value=_fmt_per_map(_pick(info, "Per-map averages", default={})), inline=False)
    return embed


def build_raw_embed(player, info):
    embed = discord.Embed(
        title=f"{player.title()} | Raw exact sample",
        description="Raw exact maps + paired 2-map series",
        color=discord.Color.dark_teal(),
    )
    embed.add_field(name="Paired series rows", value=_fmt_paired_rows(_pick(info, "Paired series rows", default=[])), inline=False)
    embed.add_field(name="Raw maps", value=_fmt_raw_maps(_pick(info, "Raw maps", default=[])), inline=False)
    embed.set_footer(text=f"Sample: {_pick(info,'Sample')} | {_pick(info,'Sample note')}")
    return embed


def build_analytics_embed(player, line, opponent, info, headshots=False):
    """
    NEW: Full analytics embed with final grade, pros/cons, advanced models,
    and a detailed player characteristic report.
    """
    resolved_opponent = _pick(info, "Opponent", default=opponent.title())
    stat_label = "HS" if headshots else "Kills"

    embed = discord.Embed(
        title=f"{player.title()} vs {resolved_opponent} | ANALYTICS",
        description=f"Full model output · {stat_label} O/U {line}",
        color=discord.Color.from_rgb(255, 165, 0),  # gold/amber
    )

    # ── Grade summary ──
    embed.add_field(
        name="📊 Grade & verdict",
        value=_truncate(
            f"**Grade:** {_pick(info,'Final grade')}\n"
            f"**Recommendation:** {_pick(info,'Bet recommendation')}\n"
            f"**Mispriced:** {_pick(info,'Mispriced or not')}\n"
            f"**Side probability:** {_pick(info,'Recommended side probability')}\n"
            f"**Edge vs line:** {_pick(info,'Edge vs line')}\n"
            f"**Hit rate:** {_pick(info,'Hit rate')}\n"
            f"**Over prob:** {_pick(info,'Over probability')} | **Under prob:** {_pick(info,'Under probability')}"
        ),
        inline=False,
    )

    # ── Player report ──
    embed.add_field(
        name="📝 Player characteristic report",
        value=_truncate(_pick(info, "Player report")),
        inline=False,
    )

    # ── Player pros / cons ──
    embed.add_field(name="✅ Player pros", value=_fmt_bullets(_pick(info, "Player pros", default=[]), limit=6), inline=True)
    embed.add_field(name="❌ Player cons", value=_fmt_bullets(_pick(info, "Player cons", default=[]), limit=6), inline=True)

    # ── Team pros / cons ──
    embed.add_field(name=f"✅ {_pick(info,'Team')} pros", value=_fmt_bullets(_pick(info, "Team pros", default=[]), limit=5), inline=True)
    embed.add_field(name=f"❌ {_pick(info,'Team')} cons", value=_fmt_bullets(_pick(info, "Team cons", default=[]), limit=5), inline=True)

    # ── Opponent pros / cons ──
    embed.add_field(name=f"✅ {resolved_opponent} pros", value=_fmt_bullets(_pick(info, "Opponent pros", default=[]), limit=4), inline=True)
    embed.add_field(name=f"❌ {resolved_opponent} cons", value=_fmt_bullets(_pick(info, "Opponent cons", default=[]), limit=4), inline=True)

    # ── Pace model ──
    pace = _pick(info, "Pace model", default={})
    embed.add_field(
        name="⏱️ Pace modeling",
        value=_truncate(_fmt_pace_model(pace) if isinstance(pace, dict) else "N/A"),
        inline=False,
    )

    # ── Blowout analysis ──
    blowout = _pick(info, "Blowout analysis", default={})
    embed.add_field(
        name="💥 Blowout / map length",
        value=_truncate(_fmt_blowout(blowout) if isinstance(blowout, dict) else "N/A"),
        inline=True,
    )

    # ── Overtime ──
    ot = _pick(info, "Overtime analysis", default={})
    embed.add_field(
        name="🕐 Overtime probability",
        value=_truncate(_fmt_ot(ot) if isinstance(ot, dict) else "N/A"),
        inline=True,
    )

    # ── Multi-kill pressure ──
    mk = _pick(info, "Multikill analysis", default={})
    embed.add_field(
        name="💣 Multi-kill pressure (2K/3K)",
        value=_truncate(_fmt_multikill(mk) if isinstance(mk, dict) else "N/A"),
        inline=False,
    )

    # ── Eco/clutch/farming ──
    eco = _pick(info, "Eco clutch analysis", default={})
    embed.add_field(
        name="💰 Eco farming · anti-eco · clutch",
        value=_truncate(_fmt_eco_clutch(eco) if isinstance(eco, dict) else "N/A"),
        inline=False,
    )

    # ── Opponent strength adjustment ──
    opp_str = _pick(info, "Opponent strength", default={})
    embed.add_field(
        name="🎯 Opponent strength adjustment",
        value=_truncate(_fmt_opp_strength(opp_str) if isinstance(opp_str, dict) else "N/A"),
        inline=False,
    )

    # ── Map-weighted KPR ──
    mwk = _pick(info, "Map weighted KPR", default={})
    embed.add_field(
        name="🗺️ Map-weighted KPR",
        value=_truncate(_fmt_map_kpr(mwk) if isinstance(mwk, dict) else "N/A"),
        inline=True,
    )

    # ── KAST + Round Swing ──
    embed.add_field(
        name="📈 KAST & Round Swing",
        value=_truncate(
            f"KAST: {_pick(info,'KAST')}\n"
            f"Round swing: {_pick(info,'Round swing')}"
        ),
        inline=True,
    )

    embed.set_footer(text=f"Sample: {_pick(info,'Sample')} | Window: {_pick(info,'Recent stat window')}")
    return embed


def build_prop_grade_embed(player, prop_type, line, result_json):
    data = json.loads(result_json)
    status = data.get("execution_status", "UNKNOWN")
    verdict = data.get("grading_verdict") or "N/A"
    details = data.get("analytical_details") or "N/A"
    color_map = {"SUCCESS": discord.Color.green(), "ERROR": discord.Color.red(), "INSUFFICIENT_DATA": discord.Color.yellow()}
    embed = discord.Embed(
        title=f"{player.title()} | {prop_type.upper()} O/U {line}",
        description="Proposition grading via Rating 3.0 heuristics",
        color=color_map.get(status, discord.Color.greyple()),
    )
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Verdict", value=verdict, inline=True)
    embed.add_field(name="Details", value=_truncate(details), inline=False)
    raw = data.get("raw_extracted_metrics")
    if raw:
        attrs = raw.get("attributes", {})
        embed.add_field(
            name="Raw metrics",
            value=_truncate(
                f"Name: {raw.get('name','N/A')}\n"
                f"Rating 3.0: {raw.get('rating_3','N/A')}\n"
                f"KAST: {raw.get('kast_percent','N/A')}%\n"
                f"Multi-kill %: {raw.get('multi_kill_percent','N/A')}%\n"
                f"Impact: {raw.get('impact_rating','N/A')}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Attribute buckets",
            value=_truncate(
                f"🔥 Firepower: {attrs.get('firepower',0)}/100\n"
                f"⚔️  Entrying:  {attrs.get('entrying',0)}/100\n"
                f"🔄 Trading:   {attrs.get('trading',0)}/100\n"
                f"🎯 Opening:   {attrs.get('opening',0)}/100\n"
                f"💪 Clutching: {attrs.get('clutching',0)}/100\n"
                f"🎿 Sniping:   {attrs.get('sniping',0)}/100\n"
                f"🛠️  Utility:   {attrs.get('utility',0)}/100"
            ),
            inline=True,
        )
    return embed


# =====================================================================
# Discord UI — buttons (now includes ANALYTICS)
# =====================================================================

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
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="DATA", style=discord.ButtonStyle.secondary)
    async def data_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = build_data_embed(self.player, self.info)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="CONTEXT", style=discord.ButtonStyle.secondary)
    async def context_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = build_context_embed(self.player, self.opponent, self.info)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="RAW", style=discord.ButtonStyle.secondary)
    async def raw_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = build_raw_embed(self.player, self.info)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="ANALYTICS", style=discord.ButtonStyle.success)
    async def analytics_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = build_analytics_embed(self.player, self.line, self.opponent, self.info, headshots=self.headshots)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# =====================================================================
# Bot commands
# =====================================================================

@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")


@bot.command()
async def scan(ctx, player: str = None, line: str = None, *, opponent: str = None):
    """!scan player line opponent — Main scan command."""
    if not player or not line or not opponent:
        await ctx.send("Usage: `!scan player line opponent`")
        return
    try:
        prop_line = float(line)
    except ValueError:
        await ctx.send("Line must be a number. Example: `!scan szejn 28.5 BRUTE`")
        return

    msg = await ctx.send(f"⏳ Pulling HLTV data for **{player}** vs **{opponent}**...")
    info = get_player_info(player, prop_line, opponent)

    if info.get("error"):
        await msg.edit(content=f"❌ Error: {info['error']}")
        return

    embed = build_scan_embed(player, prop_line, opponent, info)
    view = ScanButtons(player, prop_line, opponent, info, headshots=False)
    await msg.edit(content="", embed=embed, view=view)


@bot.command()
async def hs(ctx, player: str = None, line: str = None, *, opponent: str = None):
    """!hs player line opponent — Headshot scan command."""
    if not player or not line or not opponent:
        await ctx.send("Usage: `!hs player line opponent`")
        return
    try:
        prop_line = float(line)
    except ValueError:
        await ctx.send("Line must be a number. Example: `!hs szejn 16.5 BRUTE`")
        return

    msg = await ctx.send(f"⏳ Pulling HLTV headshot data for **{player}** vs **{opponent}**...")
    info = get_headshot_info(player, prop_line, opponent)

    if info.get("error"):
        await msg.edit(content=f"❌ Error: {info['error']}")
        return

    embed = build_grade_embed(player, prop_line, info, headshots=True)
    view = ScanButtons(player, prop_line, opponent, info, headshots=True)
    await msg.edit(content="", embed=embed, view=view)


@bot.command()
async def grade(ctx, player: str = None, prop_type: str = None, line: str = None):
    """
    !grade <player> <prop_type> <line>
    Prop types: KILLS, KAST, MULTI_KILL, FIRST_KILL, HEADSHOTS
    Example: !grade ZywOo KILLS 19.5
    """
    if not player or not prop_type or not line:
        await ctx.send(
            "Usage: `!grade player prop_type line`\n"
            "Prop types: `KILLS` `KAST` `MULTI_KILL` `FIRST_KILL` `HEADSHOTS`\n"
            "Example: `!grade ZywOo KILLS 19.5`"
        )
        return
    try:
        prop_line = float(line)
    except ValueError:
        await ctx.send("Line must be a number. Example: `!grade ZywOo KILLS 19.5`")
        return

    msg = await ctx.send(f"⏳ Grading **{player}** | **{prop_type.upper()}** O/U **{line}**...")
    try:
        grader = PropositionGrader()
        result_json = grader.grade_proposition(player, prop_type, prop_line)
        grader.shutdown()
    except Exception as e:
        await msg.edit(content=f"❌ Grading engine error: {e}")
        return

    embed = build_prop_grade_embed(player, prop_type, prop_line, result_json)
    await msg.edit(content="", embed=embed)


# =====================================================================
# Run
# =====================================================================

if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN is missing from environment.")

bot.run(TOKEN)
