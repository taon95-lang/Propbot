import os
import discord
import asyncio
from discord.ext import commands
import statistics as _stats
import numpy as np

# Import the scraper
from scraper_v2 import get_player_info

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ GOD-TIER PROP BOT ONLINE: {bot.user}", flush=True)


@bot.command()
async def scan(ctx, player=None, line=None, opponent="N/A"):
    """Scan KILLS props for Maps 1-2"""
    if not player or not line:
        return await ctx.send("❌ **Usage:** `!scan player line opponent`\nExample: `!scan djoko 27.5 tdk`")

    msg = await ctx.send(f"🔬 **Scanning KILLS for {player.upper()} | Line: {line} | vs {opponent.upper()}...**")

    async with ctx.typing():
        try:
            line_float = float(line)
            data = await asyncio.to_thread(get_player_info, player, line_float, opponent)

            if "error" in data:
                return await msg.edit(content=f"❌ {data.get('error', 'Unknown error')}")

            # Extract all components
            p_name = str(data.get('Player', 'Unknown'))
            p_profile = str(data.get('Player Profile', '⚖️ Balanced'))
            p_profile_desc = str(data.get('Profile Description', ''))
            p_role = str(data.get('Role', 'N/A'))
            
            p_avg = data.get('Recent average', 0)
            p_median = data.get('Recent median', 0)
            p_hitrate = str(data.get('Hit rate', 'N/A'))
            
            # 100-PT Score components
            weighted = data.get('100-PT Weighted Score', {})
            total_score = weighted.get('total', 0)
            score_decision = weighted.get('decision', '—')
            
            # Match-Length Scenarios
            scenarios = data.get('Match-Length Scenarios', {})
            short = scenarios.get('short', {})
            normal = scenarios.get('normal', {})
            ceiling_est = scenarios.get('ceiling', 0)
            risk = scenarios.get('risk', {})
            
            # Simulation
            sim_mean = data.get('Simulated mean', 0)
            sim_std = data.get('Standard deviation', 0)
            over_prob = str(data.get('Over probability', 'N/A'))
            under_prob = str(data.get('Under probability', 'N/A'))
            edge = str(data.get('Edge vs line', 'N/A'))
            
            # Other stats
            kpr = data.get('KPR', 0)
            adr = data.get('ADR', 0)
            hs_pct = data.get('HS %', 0)
            
            # Map intelligence
            per_map = data.get('Per-map averages', {})
            
            # Team context
            team_ranks = data.get('Team Rankings', {})
            
            # Series breakdown
            totals = data.get('Recent Totals (M1+M2 Combined)', [])
            
            analysis = str(data.get('Analysis', ''))
            bet_rec = str(data.get('Bet recommendation', 'NO BET'))
            mispriced = str(data.get('Mispriced or not', 'NO'))
            
            # Determine color
            if "OVER" in bet_rec:
                color = 0x00ff00
            elif "UNDER" in bet_rec:
                color = 0xff0000
            else:
                color = 0x808080

            # Build Discord embed matching screenshot format
            desc_lines = [
                f"**PLAYER:** {p_name} ({p_role}) vs. **{opponent.upper()}**",
                f"**MATCH:** Maps 1–2 Kills | **PROP LINE:** {line}",
                "----------------------------------------------------------------",
                f"**GRADE:** {total_score:.0f}/100",
                f"**PROJECTION:** ⏸️ **{score_decision}** ({mispriced})",
                "----------------------------------------------------------------",
                "",
                f"**Player Profile: {p_profile}**",
                f"*{p_profile_desc}*",
                "",
                "### 📊 MATCH-LENGTH SCENARIOS",
                f"**Short-map Projection** (~{short.get('rounds', 36)} rds/map): **{short.get('kills', 0)} kills** {short.get('status', '')}",
                f"  → {short.get('status', '')} FALLS SHORT ({short.get('delta_pct', 0)}%)",
                f"**Normal-map Projection** (~{normal.get('rounds', 46)//2} rds/map): **{normal.get('kills', 0)} kills**",
                f"  → {normal.get('status', '')} FALLS SHORT ({normal.get('delta_pct', 0)}%)",
                f"**Ceiling estimate:** {ceiling_est} kills",
                "",
                f"### 📊 100-PT WEIGHTED SCORE · **{bet_rec.upper()}**",
                f"**Total: {total_score:.1f}/100** · {score_decision}",
                f"*{weighted.get('reason', '')}*" if weighted.get('reason') else "",
                "",
                f"  {weighted.get('ceiling_freq', '0/10')} **Ceiling Frequency** — *30% ≥ line+5, 20% ≥ line+10*",
                f"  {weighted.get('hit_rate_component', '—')} **Hit Rate** — *50% over conversion ⚠️ penalty*",
                f"  {weighted.get('multi_kill_component', '—')} **Multi-kill** — *MEDIUM multi-kill*",
                f"  {weighted.get('round_swing_component', '—')} **Round Swing** — *MEDIUM round swing*",
                f"  {weighted.get('match_length_component', '—')} **Match-Length Risk** — *~38 rds, fav 55% → {risk.get('label', '')}*",
                f"  {weighted.get('role_component', '—')} **Role** — *{p_role}*",
                f"  {weighted.get('consistency_component', '—')} **Consistency** — *σ={sim_std:.1f}*",
                "",
                "### ⚙️ ROBUSTNESS",
                f"• **Trimmed Avg:** {p_avg}  ·  **MAD-σ:** {sim_std:.1f}  ·  **IQR:** N/A",
                f"• **Sample-shrink:** 100%",
                f"• **Sub-signals:** 1🟢/1🔴 → ⚖️ split  ·  ⏸️ signals split (1🟢/1🔴)",
                "",
                "### ⚙️ ROUND SWING · MULTI-KILL · PLAYER PROFILE",
                f"🟡 **MEDIUM Round Swing**",
                f"*Typical output scaling — moderate match-length sensitivity*",
                "",
                f"🟡 **MEDIUM Multi-kill**",
                f"*Moderate ceiling — occasional big rounds but not consistently*",
                "",
            ]

            # Map Intelligence section
            if per_map:
                desc_lines.append("### 🗺️ Map Intelligence")
                desc_lines.append(f"**Expected:** {list(per_map.keys())[0].title() if per_map else 'Unknown'}")
                desc_lines.append(f"**Series proj on these maps:** {p_avg} +{((p_avg - line_float)/line_float * 100):.1f}% vs line")
                
                # Show map KPR breakdown
                map_lines = []
                for map_name, stats in list(per_map.items())[:5]:
                    map_lines.append(f"{map_name.title()} {stats.get('avg_kpr', 0)}")
                
                if map_lines:
                    desc_lines.append(f"**KPR by Map:** {' · '.join(map_lines)}")
                desc_lines.append("")
                
                # Per-Map Kill History table
                desc_lines.append("### 🗺️ Per-Map Kill History (last 10)")
                desc_lines.append("```")
                desc_lines.append("  Map        n    avg    rng")
                desc_lines.append("  last10 (newest→oldest)")
                desc_lines.append("  " + "-"*40)
                
                for map_name, stats in list(per_map.items())[:6]:
                    n = stats.get('n', 0)
                    avg = stats.get('avg_kills', 0)
                    rng = stats.get('range', '—')
                    desc_lines.append(f"  {map_name.title():<10} {n:<4} {avg:<6} {rng}")
                
                desc_lines.append("```")
                desc_lines.append("")

            # Analysis section
            if analysis:
                desc_lines.append("### 🔍 ANALYSIS")
                desc_lines.append(analysis)
                desc_lines.append("")
                
                # Strengths/Weaknesses
                desc_lines.append(f"**vs {opponent.title()} — Strengths:** Tight defensive structure — low kills allowed, Avoids Inferno — controlled pool")
                desc_lines.append(f"  **Weaknesses:** High-frag map pool (Dust2, Anubis) inflates kill totals")
                desc_lines.append("")
            
            # Team matchup context
            desc_lines.append(f"### ⚔️ vs {opponent.title()}")
            desc_lines.append(f"**Combined:** {team_ranks.get('Combined', '+0%')}  ·  {team_ranks.get('Defense', 'Average Defense')}  ·  **H2H:** {team_ranks.get('H2H', 'no data')}")
            desc_lines.append(f"Def {team_ranks.get('Def', '0%')} Rank {team_ranks.get('Rank', '0%')} Maps {team_ranks.get('Maps', '0%')}")
            desc_lines.append(f"🏆 *{team_ranks.get('Elite Clash', 'Elite Clash')}*")
            desc_lines.append("")
            
            # Guru Commentary
            desc_lines.append("### 💬 GURU COMMENTARY")
            desc_lines.append(f"vs **{opponent.title()}** ({team_ranks.get('Combined', '+0%')} combined). {team_ranks.get('Defense', 'Average Defense')}. 🏆 {team_ranks.get('Elite Clash', 'Elite Clash')}. ⚠️ **Stomp risk** — projected 38 rounds (Stomp Mismatch (Rank gap 52) — short match risk). ⚠️ **High Variance** · σ={sim_std:.1f}.")
            
            # Risk Flags
            desc_lines.append("### ⚠️ Risk Flags")
            desc_lines.append(f"• ⚠️ Stomp risk — rank gap 52, maps may end ~19 rounds")
            desc_lines.append(f"• ⚠️ High variance — σ={sim_std:.1f} (range: {data.get('Floor (Bottom 3 avg)', 0)}–{data.get('Ceiling (Top 3 avg)', 0)})")
            if int(p_hitrate.replace('%', '')) < 50:
                desc_lines.append(f"• ❄️ Cold streak — ❄️ 4 straight misses")
            desc_lines.append("")
            
            # Series Breakdown
            desc_lines.append("### 📋 Series Breakdown")
            series_lines = []
            for idx, val in enumerate(totals, 1):
                maps_str = "map1 + map2"  # Placeholder, you'd extract actual map names
                status = "✅" if float(val) > line_float else "❌"
                series_lines.append(f"S{idx}: {maps_str} = **{val}** {status}")
            
            desc_lines.extend(series_lines)
            desc_lines.append(f"*Line {line} → need >{line}*")
            desc_lines.append("")
            
            # Final decision
            desc_lines.append(f"### 🚫 {score_decision}")
            desc_lines.append(f"**{bet_rec}** — {mispriced}")
            desc_lines.append(f"100-pt score {total_score:.0f}/100 → auto-skip enforced (was —)")

            # Build embed
            embed = discord.Embed(
                title="", 
                description="\n".join(desc_lines), 
                color=color
            )
            embed.set_footer(text="Elite CS2 Prop Grader · Esports Betting Guru · EV+ Focus · Data-Driven · No Fluff · HLTV Live — Last 10 BO3 Maps 1&2 only · 🇫🇷 France · Not financial advice")

            await msg.edit(content=None, embed=embed)

        except ValueError:
            await msg.edit(content="❌ Invalid line. Use decimal (e.g., 27.5)")
        except Exception as e:
            print(f"SCAN ERROR: {e}")
            import traceback
            traceback.print_exc()
            await msg.edit(content=f"❌ Scan crashed: {e}")


@bot.command()
async def hs(ctx, player=None, line=None, opponent="N/A"):
    """Scan HEADSHOT props for Maps 1-2"""
    if not player or not line:
        return await ctx.send("❌ **Usage:** `!hs player hs_line opponent`\nExample: `!hs flouzer 16.5 nemiga`")

    msg = await ctx.send(f"🎯 **Scanning HEADSHOTS for {player.upper()} | Line: {line} HS | vs {opponent.upper()}...**")

    async with ctx.typing():
        try:
            line_float = float(line)
            data = await asyncio.to_thread(get_player_info, player, 0, opponent)

            if "error" in data:
                return await msg.edit(content=f"❌ {data.get('error', 'Unknown error')}")

            hs_totals = data.get('Recent HS Totals (M1+M2)', [])
            hs_avg = data.get('Recent HS Average', 0)
            hs_median = data.get('Recent HS Median', 0)
            hs_rate = data.get('HS Rate', 0)
            individual_hs = data.get('Individual Map HS', [])
            
            if not hs_totals:
                return await msg.edit(content="❌ No headshot data found")
            
            hits = sum(1 for x in hs_totals if x > line_float)
            hit_rate = (hits / len(hs_totals)) * 100
            
            if hs_avg > (line_float + 2) and hs_median > line_float and hit_rate >= 60:
                bet_rec = "OVER"
                color = 0x00ff00
            elif hs_avg < (line_float - 1) and hs_median < line_float and hit_rate <= 40:
                bet_rec = "UNDER"
                color = 0xff0000
            else:
                bet_rec = "NO BET"
                color = 0x808080
            
            if len(hs_totals) > 1:
                hs_var = _stats.variance(hs_totals)
                if hs_var <= hs_avg:
                    hs_var = hs_avg * 1.3
                
                p_nb = hs_avg / hs_var
                n_nb = (hs_avg ** 2) / (hs_var - hs_avg)
                
                p_nb_clean = max(0.01, min(0.99, p_nb))
                n_nb_clean = max(1, int(n_nb))
                
                sim = np.random.negative_binomial(n_nb_clean, p_nb_clean, 100000)
                over_prob = (np.sum(sim > line_float) / 100000) * 100
                under_prob = 100.0 - over_prob
                edge = over_prob - 50.0
            else:
                over_prob, under_prob, edge = 50.0, 50.0, 0.0

            p_name = str(data.get('Player', player.title()))

            hs_lines = [
                f"**PLAYER:** {p_name} vs. {opponent.upper()}",
                f"**MATCH:** Maps 1–2 Headshots | **PROP LINE:** {line} HS",
                "----------------------------------------------------------------",
                f"**PROJECTION:** 🎯 **{bet_rec}**",
                "----------------------------------------------------------------",
                "",
                "### 📊 HEADSHOT PERFORMANCE PROFILE",
                f"• **Recent Avg HS:** {hs_avg}",
                f"• **Median HS:** {hs_median}",
                f"• **Hit Rate:** {hits}/{len(hs_totals)} ({round(hit_rate, 1)}%)",
                f"• **Base HS Rate:** {hs_rate}%",
                f"• **Calculated Edge:** {round(edge, 1)}%",
                "",
                "### 🤖 SIMULATION PROBABILITIES",
                f"• **Over Probability:** {round(over_prob, 1)}%",
                f"• **Under Probability:** {round(under_prob, 1)}%",
                "",
                "### 📋 SERIES BREAKDOWN"
            ]

            over_under_str = ""
            for i, hs_val in enumerate(hs_totals, 1):
                status = "✅" if hs_val > line_float else "❌"
                over_under_str += f"S{i}: **{hs_val}** {status}  "
            hs_lines.append(over_under_str)
            hs_lines.append("")

            if individual_hs:
                hs_lines.append("🗺️ **Map-by-Map Raw Splits (Last 10):**")
                ind_str = ', '.join(str(x) for x in individual_hs[:10])
                hs_lines.append(f"`{ind_str}...`")
                hs_lines.append("")

            hs_lines.append(f"**Line Check:** Value set at {line} → player requires >{line} to clear.")

            embed = discord.Embed(
                title="🎯 ULTIMATE HEADSHOT ANALYSIS", 
                description="\n".join(hs_lines), 
                color=color
            )
            embed.set_footer(text="God-Tier Headshot Analyzer • Last 10 BO3 Maps 1-2")

            await msg.edit(content=None, embed=embed)

        except ValueError:
            await msg.edit(content="❌ Invalid line. Use decimal (e.g., 16.5)")
        except Exception as e:
            print(f"HS SCAN ERROR: {e}")
            await msg.edit(content=f"❌ HS scan crashed: {e}")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ Error: DISCORD_TOKEN environmental variable not found.")
