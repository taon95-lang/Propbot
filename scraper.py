import re
import os
import time
import math
import statistics as _stats
import functools
import numpy as np
from bs4 import BeautifulSoup
from collections import defaultdict, Counter

print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")


def _fetch(url, render=False):
    if not SCRAPERAPI_KEY:
        print("CRITICAL: SCRAPERAPI_KEY environment variable is missing.")
        return None, None

    for attempt in range(3):
        use_render = render if attempt == 0 else (not render if attempt == 1 else True)
        render_param = "&render=true" if use_render else ""
        proxy_url = (
            f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}"
            f"&url={url}{render_param}&country_code=us"
        )

        try:
            print(f"FETCH ATTEMPT {attempt + 1}/3: {url} JS_Render={use_render}")
            r = requests.get(proxy_url, timeout=60)
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text, r.headers.get("Sa-Final-Url", url)

            print(f"FAILED: Status={r.status_code}, Length={len(r.text)}")
            time.sleep(2)
        except Exception as e:
            print(f"FETCH EXCEPTION: {e}")
            time.sleep(2)

    return None, None


def _safe_float(text):
    if text is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(text).replace(",", ""))
    return float(m.group(0)) if m else None


def _safe_int(text):
    val = _safe_float(text)
    return int(val) if val is not None else None


def _pct(num, den):
    return round((num / den) * 100, 1) if den else 0.0


def _mean(values, default=0):
    clean = [v for v in values if isinstance(v, (int, float))]
    return round(_stats.mean(clean), 2) if clean else default


def _median(values, default=0):
    clean = [v for v in values if isinstance(v, (int, float))]
    return round(_stats.median(clean), 2) if clean else default


def _stdev(values):
    clean = [v for v in values if isinstance(v, (int, float))]
    return round(_stats.stdev(clean), 2) if len(clean) > 1 else 0.0


def _percentile(values, p):
    clean = sorted([v for v in values if isinstance(v, (int, float))])
    if not clean:
        return 0
    idx = int(round((len(clean) - 1) * p))
    return clean[idx]


def search_player(name: str):
    name_clean = name.lower().strip()

    STATIC = {
        "donk": ("21167", "donk"),
        "zywoo": ("11893", "zywoo"),
        "m0nesy": ("19230", "m0nesy"),
        "niko": ("3741", "niko"),
        "jl": ("19206", "jl"),
        "xertion": ("20312", "xertion"),
        "jamyoung": ("19645", "jamyoung"),
        "h4san4tor": ("22189", "h4san4tor"),
        "brooxsy": ("21971", "brooxsy"),
        "djoko": ("7175", "djoko"),
        "flouzer": ("20928", "flouzer"),
    }

    if name_clean in STATIC:
        pid, slug = STATIC[name_clean]
        return pid, slug, slug.title()

    html, final_url = _fetch(f"{HLTV_BASE}/search?query={name_clean}", render=False)
    if not html:
        return None

    if final_url and "/player/" in final_url:
        m = re.search(r"/player/(\d+)/([^/]+)", final_url)
        if m:
            return m.group(1), m.group(2), m.group(2).replace("-", " ").title()

    found_links = re.findall(r"/(?:stats/)?player(?:s)?/(\d+)/([a-zA-Z0-9_-]+)", html)
    if found_links:
        for pid, slug in found_links:
            if name_clean in slug.lower():
                return pid, slug, slug.replace("-", " ").title()

        pid, slug = found_links[0]
        return pid, slug, slug.replace("-", " ").title()

    return None


def _error_response(msg, player_name, line, opponent):
    return {
        "Player": player_name.title(),
        "Match": f"vs {opponent.title()}",
        "Prop Line": f"{line} Kills",
        "Bet Recommendation": "NO BET",
        "Bet recommendation": "NO BET",
        "Final grade": "Below 5/10 (No Bet)",
        "error": msg,
    }


def parse_player_profile(pid, slug):
    data = {
        "Team": "Unavailable from HLTV",
        "Role": "Unavailable from HLTV",
        "Rating 3.0": "Unavailable from HLTV",
        "Rating 2.1/2.0": "Unavailable from HLTV",
        "ADR": "Unavailable from HLTV",
        "KAST": "Unavailable from HLTV",
        "Impact": "Unavailable from HLTV",
        "DPR": "Unavailable from HLTV",
        "KPR": "Unavailable from HLTV",
        "HS %": "Unavailable from HLTV",
    }

    html, _ = _fetch(f"{HLTV_BASE}/player/{pid}/{slug}", render=True)
    if not html:
        return data

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    team_link = soup.find("a", href=re.compile(r"/team/\d+/"))
    if team_link:
        data["Team"] = team_link.get_text(" ", strip=True)

    stat_patterns = {
        "Rating 3.0": r"Rating\s*3\.0\s*([0-9.]+)",
        "Rating 2.1/2.0": r"Rating\s*(?:2\.1|2\.0)\s*([0-9.]+)",
        "ADR": r"Damage/Round\s*([0-9.]+)|ADR\s*([0-9.]+)",
        "KAST": r"KAST\s*([0-9.]+%)",
        "Impact": r"Impact\s*([0-9.]+)",
        "DPR": r"Deaths/Round\s*([0-9.]+)",
        "KPR": r"Kills/Round\s*([0-9.]+)",
        "HS %": r"Headshots\s*([0-9.]+%)|HS\s*([0-9.]+%)",
    }

    for key, pattern in stat_patterns.items():
        m = re.search(pattern, text, re.I)
        if m:
            vals = [g for g in m.groups() if g]
            if vals:
                data[key] = vals[0]

    role_guess = "Unavailable from HLTV"
    lower = text.lower()
    if any(x in lower for x in ["awper", "awp"]):
        role_guess = "AWPer"
    elif any(x in lower for x in ["entry", "opening"]):
        role_guess = "Entry / Opener"
    elif any(x in lower for x in ["rifler"]):
        role_guess = "Rifler"

    data["Role"] = role_guess
    return data


def get_team_rank(team_name):
    if not team_name or team_name == "Unavailable from HLTV":
        return "Unavailable from HLTV"

    html, _ = _fetch(f"{HLTV_BASE}/ranking/teams", render=True)
    if not html:
        return "Unavailable from HLTV"

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = text.splitlines()

    for i, line in enumerate(lines):
        if team_name.lower() == line.lower():
            nearby = " ".join(lines[max(0, i - 3): i + 4])
            m = re.search(r"#\s*(\d+)", nearby)
            if m:
                return f"#{m.group(1)}"

    m = re.search(rf"#\s*(\d+)\s+{re.escape(team_name)}", text, re.I)
    if m:
        return f"#{m.group(1)}"

    return "Unavailable from HLTV"


def parse_match_odds(player_team, opponent):
    html, _ = _fetch(f"{HLTV_BASE}/matches", render=True)
    if not html:
        return "Unavailable from HLTV"

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    if player_team and opponent:
        if player_team.lower() in text.lower() and opponent.lower() in text.lower():
            return "Match found on HLTV matches page, odds not reliably parseable from current layout"

    return "Unavailable from HLTV"


def parse_stats_matches(pid, slug):
    stats_url = f"{HLTV_BASE}/stats/players/matches/{pid}/{slug}"
    html, _ = _fetch(stats_url, render=True)

    if not html:
        return None, "FAIL: Stats page blocked or ScraperAPI failed after 3 retries."

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "stats-table"})

    if not table:
        return None, "FAIL: Stats table layout not found or changed on HLTV."

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")
    print(f"PROCESSING {len(rows)} HLTV STATS ROWS")

    all_maps = []

    known_maps = {
        "anc", "mrg", "d2", "inf", "nuke", "anb", "vrt", "ovp",
        "ancient", "mirage", "dust2", "inferno", "anubis", "vertigo", "overpass",
        "train", "cache", "cobblestone"
    }

    for i, row in enumerate(rows):
        cols = row.find_all("td")
        if len(cols) < 4:
            continue

        try:
            cell_texts = [c.get_text(" ", strip=True) for c in cols]

            kd_idx = -1
            kills = deaths = headshots = None

            for col_idx, col in enumerate(cols):
                col_text = col.get_text(" ", strip=True)
                kd_match = re.search(r"(\d+)\s*-\s*(\d+)", col_text)
                if kd_match:
                    k_check = int(kd_match.group(1))
                    d_check = int(kd_match.group(2))

                    if 0 <= k_check <= 60 and 0 <= d_check <= 60:
                        kd_idx = col_idx
                        kills = k_check
                        deaths = d_check

                        hs_match = re.search(r"\d+\s*-\s*\d+\s*\((\d+)\)", col_text)
                        headshots = int(hs_match.group(1)) if hs_match else None
                        break

            if kills is None or deaths is None:
                continue

            date = "N/A"
            for txt in cell_texts:
                if re.search(r"^\d{2}/\d{2}/\d{2}$", txt):
                    date = txt
                    break

            map_name = "Unknown"
            map_cell_idx = -1
            for idx, txt in enumerate(cell_texts):
                if txt.lower() in known_maps:
                    map_cell_idx = idx
                    map_name = txt
                    break

            if map_cell_idx > 0:
                opp = cell_texts[map_cell_idx - 1].lower()
            else:
                opp = cell_texts[2].lower() if len(cell_texts) > 2 else "unknown"

            opp = re.sub(r"\(.*?\)", "", opp).strip()
            opp = re.sub(r"\s+\d+\s*$", "", opp).strip()

            rounds = 0
            score_pairs = []

            for idx, txt in enumerate(cell_texts):
                if idx == kd_idx:
                    continue

                p_matches = re.findall(r"\((\d+)\)", txt)
                if len(p_matches) >= 2:
                    score_pairs.append((int(p_matches[0]), int(p_matches[1])))

                m = re.search(r"^(\d+)\s*-\s*(\d+)$", txt)
                if m:
                    a, b = int(m.group(1)), int(m.group(2))
                    if 13 <= a + b <= 60:
                        score_pairs.append((a, b))

            if score_pairs:
                rounds = sum(score_pairs[0])

            if rounds < 10 or rounds > 60:
                rounds = 22

            if headshots is None:
                headshots = 0

            rating = None
            adr = None
            kast = None

            for txt in cell_texts:
                nums = re.findall(r"\b\d+\.\d+\b", txt)
                for n in nums:
                    f = float(n)
                    if 0.2 <= f <= 2.5 and rating is None:
                        rating = f
                    elif 20 <= f <= 180 and adr is None:
                        adr = f

                if "%" in txt and kast is None:
                    maybe = _safe_float(txt)
                    if maybe and 20 <= maybe <= 100:
                        kast = maybe

            all_maps.append({
                "date": date,
                "opponent": opp,
                "map": map_name,
                "kills": kills,
                "deaths": deaths,
                "headshots": headshots,
                "rounds": rounds,
                "rating": rating,
                "adr": adr,
                "kast": kast,
                "kpr": kills / rounds if rounds else 0,
                "dpr": deaths / rounds if rounds else 0,
            })

        except Exception as e:
            print(f"ROW {i} PARSING ERROR: {e}")
            continue

    return all_maps, None


def build_series_groups(all_maps):
    groups = []

    if not all_maps:
        return groups

    current = [all_maps[0]]

    for m in all_maps[1:]:
        if m["opponent"] == current[0]["opponent"] and m["date"] == current[0]["date"]:
            current.append(m)
        else:
            groups.append(current)
            current = [m]

    if current:
        groups.append(current)

    return groups


def analyze_maps(series_groups, line, opponent):
    final_series_totals = []
    final_series_hs_totals = []
    individual_map_kills = []
    individual_map_hs = []
    per_map_history = []
    map_kpr = defaultdict(list)
    map_kills = defaultdict(list)
    similar_team_series = []
    h2h_series = []

    total_k = total_d = total_r = total_hs = 0
    all_ratings = []
    all_adr = []
    all_kast = []

    for group in series_groups:
        if len(final_series_totals) >= 10:
            break

        if len(group) < 2:
            continue

        m1 = group[-1]
        m2 = group[-2]
        pair = [m1, m2]

        combined_k = sum(x["kills"] for x in pair)
        combined_d = sum(x["deaths"] for x in pair)
        combined_hs = sum(x["headshots"] for x in pair)
        combined_r = sum(x["rounds"] for x in pair)

        final_series_totals.append(combined_k)
        final_series_hs_totals.append(combined_hs)

        for x in pair:
            individual_map_kills.append(x["kills"])
            individual_map_hs.append(x["headshots"])
            map_kpr[x["map"]].append(x["kpr"])
            map_kills[x["map"]].append(x["kills"])
            per_map_history.append({
                "date": x["date"],
                "opponent": x["opponent"],
                "map": x["map"],
                "kills": x["kills"],
                "deaths": x["deaths"],
                "headshots": x["headshots"],
                "rounds": x["rounds"],
                "kpr": round(x["kpr"], 3),
                "dpr": round(x["dpr"], 3),
            })

            if x["rating"] is not None:
                all_ratings.append(x["rating"])
            if x["adr"] is not None:
                all_adr.append(x["adr"])
            if x["kast"] is not None:
                all_kast.append(x["kast"])

        total_k += combined_k
        total_d += combined_d
        total_hs += combined_hs
        total_r += combined_r

        opp = group[0]["opponent"].lower()
        target_opp = opponent.lower().strip()

        if target_opp and target_opp != "n/a" and target_opp in opp:
            h2h_series.append(combined_k)

        strong_teams = [
            "vitality", "natus vincere", "navi", "faze", "mouz",
            "spirit", "g2", "falcons", "aurora", "mongolz",
            "virtus.pro", "astralis", "liquid", "furia"
        ]

        if any(t in opp for t in strong_teams):
            similar_team_series.append(combined_k)

    avg_2map = _mean(final_series_totals)
    median_2map = _median(final_series_totals)
    avg_hs = _mean(final_series_hs_totals)
    median_hs = _median(final_series_hs_totals)

    hits = sum(1 for x in final_series_totals if x > line)
    hit_rate = _pct(hits, len(final_series_totals))

    kpr = total_k / total_r if total_r else 0
    dpr = total_d / total_r if total_r else 0
    hs_rate = _pct(total_hs, total_k)

    short_rounds = 38
    normal_rounds = 44

    short_projection = round(kpr * short_rounds, 1) if kpr else 0
    normal_projection = round(kpr * normal_rounds, 1) if kpr else 0

    expected_kills = round((short_projection * 0.35) + (normal_projection * 0.65), 1)

    std = _stdev(final_series_totals)
    ceiling = _percentile(final_series_totals, 0.90)
    floor = _percentile(final_series_totals, 0.10)

    multi_kill_games = sum(1 for x in final_series_totals if x >= avg_2map + 4)
    multi_kill_pct = _pct(multi_kill_games, len(final_series_totals))

    round_swing_pct = 0.0
    if short_projection:
        round_swing_pct = round(((normal_projection - short_projection) / short_projection) * 100, 1)

    per_map_kpr = {
        m: round(_stats.mean(vals), 3)
        for m, vals in map_kpr.items()
        if vals
    }

    per_map_kill_avg = {
        m: round(_stats.mean(vals), 1)
        for m, vals in map_kills.items()
        if vals
    }

    best_maps = sorted(per_map_kill_avg.items(), key=lambda x: x[1], reverse=True)[:3]
    weak_maps = sorted(per_map_kill_avg.items(), key=lambda x: x[1])[:3]

    return {
        "final_series_totals": final_series_totals,
        "final_series_hs_totals": final_series_hs_totals,
        "individual_map_kills": individual_map_kills[:20],
        "individual_map_hs": individual_map_hs[:20],
        "per_map_history": per_map_history[:20],
        "per_map_kpr": per_map_kpr,
        "per_map_kill_avg": per_map_kill_avg,
        "best_maps": best_maps,
        "weak_maps": weak_maps,
        "avg_2map": avg_2map,
        "median_2map": median_2map,
        "avg_hs": avg_hs,
        "median_hs": median_hs,
        "hit_rate": hit_rate,
        "kpr": round(kpr, 3),
        "dpr": round(dpr, 3),
        "hs_rate": round(hs_rate, 1),
        "short_projection": short_projection,
        "normal_projection": normal_projection,
        "expected_kills": expected_kills,
        "short_rounds": short_rounds,
        "normal_rounds": normal_rounds,
        "std": std,
        "ceiling": ceiling,
        "floor": floor,
        "multi_kill_pct": multi_kill_pct,
        "round_swing_pct": round_swing_pct,
        "similar_team_series": similar_team_series,
        "h2h_series": h2h_series,
        "recent_rating_avg": _mean(all_ratings, "Unavailable from HLTV"),
        "recent_adr_avg": _mean(all_adr, "Unavailable from HLTV"),
        "recent_kast_avg": _mean(all_kast, "Unavailable from HLTV"),
    }


def simulate_probability(expected_kills, line, historical_totals):
    if expected_kills <= 0:
        return 50.0, 50.0, expected_kills

    var_2map = _stats.variance(historical_totals) if len(historical_totals) > 1 else expected_kills * 1.25

    if var_2map <= expected_kills:
        var_2map = expected_kills * 1.25

    p_nb = expected_kills / var_2map
    n_nb = (expected_kills ** 2) / max(var_2map - expected_kills, 0.01)

    p_nb = max(0.01, min(0.99, p_nb))
    n_nb = max(1, int(n_nb))

    sim = np.random.negative_binomial(n_nb, p_nb, 100000)
    over_prob = round((np.sum(sim > line) / 100000) * 100, 1)
    under_prob = round(100.0 - over_prob, 1)

    return over_prob, under_prob, round(float(np.mean(sim)), 2)


def make_decision(line, analysis, over_prob, under_prob):
    avg_2map = analysis["avg_2map"]
    median_2map = analysis["median_2map"]
    hit_rate = analysis["hit_rate"]
    std = analysis["std"]
    ceiling = analysis["ceiling"]
    short_proj = analysis["short_projection"]
    normal_proj = analysis["normal_projection"]

    edge = max(over_prob, under_prob) - 50

    high_variance = std >= 7
    high_ceiling = ceiling >= line + 3
    block_under = high_variance or high_ceiling

    if avg_2map > line and median_2map > line and hit_rate >= 60 and short_proj >= line - 2 and normal_proj > line:
        rec = "OVER"
    elif avg_2map < line and median_2map < line and hit_rate <= 40 and not block_under:
        rec = "UNDER"
    elif avg_2map >= line - 2 and high_ceiling and normal_proj >= line:
        rec = "OVER LEAN"
    else:
        rec = "NO BET"

    if edge >= 25:
        grade = "10/10 (Elite Edge)"
    elif edge >= 20:
        grade = "9/10 (Very Strong Edge)"
    elif edge >= 15:
        grade = "8/10 (Strong Playable Edge)"
    elif edge >= 10:
        grade = "7/10 (Solid Lean)"
    elif edge >= 6:
        grade = "6/10 (Small Edge)"
    elif edge >= 3:
        grade = "5/10 (Thin Edge)"
    else:
        grade = "Below 5/10 (No Bet)"

    if edge < 6 or max(over_prob, under_prob) < 55:
        rec = "NO BET"

    if hit_rate < 40 and high_variance:
        rec = "NO BET"

    if abs(analysis["normal_projection"] - line) >= 3 and hit_rate >= 60:
        mispriced = "YES"
    elif abs(avg_2map - line) >= 4:
        mispriced = "YES"
    else:
        mispriced = "NO"

    if edge >= 10 and std <= 7:
        value = "STRONG VALUE"
    elif edge >= 6:
        value = "MODERATE VALUE"
    else:
        value = "LOW / NO VALUE"

    return rec, grade, mispriced, value, round(edge, 1)


def build_written_analysis(display, opponent, line, analysis, rec):
    avg_2map = analysis["avg_2map"]
    hit_rate = analysis["hit_rate"]
    short_proj = analysis["short_projection"]
    normal_proj = analysis["normal_projection"]
    kpr = analysis["kpr"]
    dpr = analysis["dpr"]
    ceiling = analysis["ceiling"]
    floor = analysis["floor"]

    if rec in ["OVER", "OVER LEAN"]:
        reason = (
            f"{display} leans over because his recent M1+M2 average is {avg_2map} "
            f"against a {line} line, with a {hit_rate}% hit rate. His KPR is {kpr}, "
            f"and the normal-map projection is {normal_proj}. The ceiling is {ceiling}, "
            f"so he has enough upside if the match reaches normal round volume."
        )
    elif rec == "UNDER":
        reason = (
            f"{display} leans under because his recent M1+M2 average is {avg_2map} "
            f"against a {line} line, with only a {hit_rate}% hit rate to the over. "
            f"The short-map projection is {short_proj}, normal projection is {normal_proj}, "
            f"and his floor is {floor}, which creates under risk if maps are one-sided."
        )
    else:
        reason = (
            f"{display} is a no bet because the HLTV sample does not create a clean edge "
            f"against the {line} line. Recent average is {avg_2map}, hit rate is {hit_rate}%, "
            f"short projection is {short_proj}, and normal projection is {normal_proj}."
        )

    return reason


def get_player_info(player_name, line=0.0, opponent="N/A"):
    try:
        line = float(line)

        search_res = search_player(player_name)
        if not search_res:
            return _error_response(
                f"FAIL: Could not find player '{player_name}' on HLTV.",
                player_name,
                line,
                opponent,
            )

        pid, slug, display = search_res
        print(f"TARGET ACQUIRED: {display} ID={pid}")

        profile = parse_player_profile(pid, slug)
        all_maps, err = parse_stats_matches(pid, slug)

        if err:
            return _error_response(err, display, line, opponent)

        if len(all_maps) < 2:
            return _error_response(
                f"FAIL: Found {len(all_maps)} maps. Not enough HLTV match history.",
                display,
                line,
                opponent,
            )

        series_groups = build_series_groups(all_maps)
        analysis = analyze_maps(series_groups, line, opponent)

        if not analysis["final_series_totals"]:
            return _error_response(
                "FAIL: Could not build enough valid M1+M2 BO3 samples.",
                display,
                line,
                opponent,
            )

        over_prob, under_prob, simulated_mean = simulate_probability(
            analysis["expected_kills"],
            line,
            analysis["final_series_totals"],
        )

        rec, grade, mispriced, value, edge = make_decision(
            line,
            analysis,
            over_prob,
            under_prob,
        )

        player_team = profile.get("Team", "Unavailable from HLTV")
        player_team_rank = get_team_rank(player_team)
        opponent_rank = get_team_rank(opponent)
        odds = parse_match_odds(player_team, opponent)

        written = build_written_analysis(display, opponent, line, analysis, rec)

        strengths = []
        weaknesses = []

        if analysis["kpr"] >= 0.75:
            strengths.append("High KPR")
        if analysis["recent_adr_avg"] != "Unavailable from HLTV" and analysis["recent_adr_avg"] >= 80:
            strengths.append("Strong ADR")
        if analysis["hit_rate"] >= 60:
            strengths.append("Strong recent over hit rate")
        if analysis["ceiling"] >= line + 4:
            strengths.append("Strong historical ceiling")
        if analysis["normal_projection"] > line:
            strengths.append("Normal-map projection clears line")

        if analysis["dpr"] >= 0.72:
            weaknesses.append("High DPR")
        if analysis["short_projection"] < line:
            weaknesses.append("Short-map projection below line")
        if analysis["hit_rate"] <= 40:
            weaknesses.append("Weak recent over hit rate")
        if analysis["std"] >= 7:
            weaknesses.append("High volatility")

        if not strengths:
            strengths.append("No clear strength detected from available HLTV sample")
        if not weaknesses:
            weaknesses.append("No major weakness detected from available HLTV sample")

        projected_maps = ", ".join([m[0] for m in analysis["best_maps"]]) if analysis["best_maps"] else "Unavailable from HLTV"

        return {
            "Player": display,
            "Match": f"vs {opponent.title()}",
            "Prop": f"{line} Kills",
            "Prop Line": f"{line} Kills",

            "Team": player_team,
            "Player Team Rank": player_team_rank,
            "Opponent Team Rank": opponent_rank,
            "Match Odds": odds,

            "Rating 3.0": profile.get("Rating 3.0"),
            "Rating 2.1/2.0": profile.get("Rating 2.1/2.0"),
            "Role": profile.get("Role"),
            "KPR": analysis["kpr"],
            "DPR": analysis["dpr"],
            "KAST": analysis["recent_kast_avg"],
            "ADR": analysis["recent_adr_avg"],
            "Impact Rating": profile.get("Impact"),
            "HS %": analysis["hs_rate"],

            "Recent sample used": f"Last {len(analysis['final_series_totals'])} BO3 Series M1+M2",
            "Recent average": analysis["avg_2map"],
            "Recent median": analysis["median_2map"],
            "Hit rate": f"{analysis['hit_rate']}%",
            "Historical ceiling": analysis["ceiling"],
            "Historical floor": analysis["floor"],
            "Standard deviation": analysis["std"],

            "Round Swing %": f"{analysis['round_swing_pct']}%",
            "Multi Kill %": f"{analysis['multi_kill_pct']}%",

            "Projected rounds": analysis["normal_rounds"],
            "Short map projected rounds": analysis["short_rounds"],
            "Normal map projected rounds": analysis["normal_rounds"],
            "Short map projection": analysis["short_projection"],
            "Normal map projection": analysis["normal_projection"],
            "Expected kills": analysis["expected_kills"],
            "Simulated mean": simulated_mean,

            "Over probability": f"{over_prob}%",
            "Under probability": f"{under_prob}%",
            "Edge vs line": f"{edge}%",
            "Value Tag": value,
            "Mispriced or not": mispriced,
            "Final grade": grade,
            "Bet recommendation": rec,
            "Bet Recommendation": rec,

            "Stats against similar teams": analysis["similar_team_series"] or "Unavailable from HLTV sample",
            "Head to head samples": analysis["h2h_series"] or "No recent H2H found in HLTV sample",

            "Map Intelligence": {
                "Projected maps": projected_maps,
                "Best recent maps by kills": analysis["best_maps"],
                "Weak recent maps by kills": analysis["weak_maps"],
                "KPR by map": analysis["per_map_kpr"],
                "Average kills by map": analysis["per_map_kill_avg"],
            },

            "Per map kill history": analysis["per_map_history"],
            "Recent Totals M1+M2 Combined": analysis["final_series_totals"],
            "Recent Totals": analysis["final_series_totals"],
            "Recent Individual Map Kills": analysis["individual_map_kills"],

            "Recent HS Totals M1+M2": analysis["final_series_hs_totals"],
            "Recent HS Average": analysis["avg_hs"],
            "Recent HS Median": analysis["median_hs"],
            "Individual Map HS": analysis["individual_map_hs"],

            "Player strengths": strengths,
            "Opponent strength and weakness": {
                "Opponent": opponent.title(),
                "Opponent Rank": opponent_rank,
                "Note": "Opponent strengths/weaknesses are limited to what HLTV pages expose through the current scrape.",
            },

            "Small Analysis": written,
        }

    except Exception as global_e:
        print(f"CRITICAL SYSTEM BLOCK EXCEPTION: {global_e}")
        return _error_response(
            f"CRITICAL CRASH PREVENTED: {str(global_e)}",
            player_name,
            line,
            opponent,
        )
