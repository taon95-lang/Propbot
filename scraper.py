import os
import re
import time
import functools
import statistics as _stats
from collections import defaultdict

import numpy as np
from bs4 import BeautifulSoup

print = functools.partial(print, flush=True)

try:
    from curl_cffi import requests as requests
except ImportError:
    import requests

# =========================================================
# HLTV CONFIG
# =========================================================

HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")

VALID_MAPS = {
    "inferno",
    "mirage",
    "ancient",
    "anubis",
    "dust2",
    "nuke",
    "train",
    "vertigo",
    "overpass"
}

STATIC_PLAYERS = {
    "donk": ("21167", "donk"),
    "zywoo": ("11893", "zywoo"),
    "m0nesy": ("19230", "m0nesy"),
    "niko": ("3741", "niko"),
    "jl": ("19206", "jl"),
    "xertion": ("20312", "xertion"),
    "jamyoung": ("19645", "jamyoung"),
    "pointer": ("26666", "pointer"),
    "caleyy": ("27093", "caleyy"),
    "eraa": ("25677", "eraa"),
    "avid": ("25488", "avid"),
    "marix": ("26544", "marix"),
    "keoz": ("25673", "keoz"),
}

# =========================================================
# FETCH
# =========================================================

def _fetch(url, render=False):

    if not SCRAPERAPI_KEY:
        print("❌ SCRAPERAPI_KEY missing")
        return None, None

    for attempt in range(3):

        use_render = render if attempt == 0 else True

        render_param = "&render=true" if use_render else ""

        proxy_url = (
            f"http://api.scraperapi.com"
            f"?api_key={SCRAPERAPI_KEY}"
            f"&url={url}"
            f"{render_param}"
            f"&country_code=us"
        )

        try:

            print(f"🌐 FETCH {attempt+1}/3 -> {url}")

            r = requests.get(
                proxy_url,
                timeout=60,
            )

            print(f"STATUS: {r.status_code}")
            print(f"LENGTH: {len(r.text)}")

            if (
                r.status_code == 200
                and len(r.text) > 1000
                and "cloudflare" not in r.text.lower()
                and "just a moment" not in r.text.lower()
            ):
                return r.text, r.headers.get("Sa-Final-Url", url)

            time.sleep(2)

        except Exception as e:
            print(f"❌ FETCH ERROR: {e}")
            time.sleep(2)

    return None, None

# =========================================================
# PLAYER SEARCH
# =========================================================

def search_player(name: str):

    clean = name.lower().strip()

    if clean in STATIC_PLAYERS:
        pid, slug = STATIC_PLAYERS[clean]
        return pid, slug, slug.title()

    html, final_url = _fetch(
        f"{HLTV_BASE}/search?query={clean}",
        render=False
    )

    if not html:
        return None

    if final_url and "/player/" in final_url:
        m = re.search(r"/player/(\d+)/([^/]+)", final_url)

        if m:
            return (
                m.group(1),
                m.group(2),
                m.group(2).title()
            )

    found = re.findall(
        r"/player/(\d+)/([a-zA-Z0-9_-]+)",
        html
    )

    if found:
        pid, slug = found[0]
        return pid, slug, slug.title()

    return None

# =========================================================
# ERROR RESPONSE
# =========================================================

def _error_response(msg, player_name, line, opponent):

    return {
        "Player": player_name,
        "Match": f"vs {opponent}",
        "Prop Line": f"{line}",
        "Bet recommendation": "NO BET",
        "error": msg
    }

# =========================================================
# ROLE CLASSIFIER
# =========================================================

def classify_role(kpr, dpr, hs):

    kd = kpr / dpr if dpr > 0 else 1.0

    if kpr >= 0.80 and kd >= 1.20:
        return "Star Rifler"

    if kpr >= 0.75 and hs >= 35:
        return "Entry Fragger"

    if kpr >= 0.73 and hs <= 32:
        return "Primary AWPer"

    if kpr <= 0.64:
        return "Support"

    return "Flex"

# =========================================================
# CEILING FLOOR
# =========================================================

def calculate_ceiling_floor(vals):

    if not vals:
        return 0, 0

    ordered = sorted(vals)

    floor = round(_stats.mean(ordered[:3]), 1)
    ceiling = round(_stats.mean(ordered[-3:]), 1)

    return ceiling, floor

# =========================================================
# MAP ANALYSIS
# =========================================================

def analyze_maps(all_maps):

    mp = defaultdict(list)

    for m in all_maps:
        mp[m["map_name"]].append(m["kills"])

    out = {}

    for map_name, kills in mp.items():

        out[map_name] = {
            "avg_kills": round(_stats.mean(kills), 1),
            "sample": len(kills)
        }

    return out

# =========================================================
# OPPONENT STRENGTH
# =========================================================

def opponent_factor(name):

    elite = {
        "vitality": 0.86,
        "spirit": 0.87,
        "faze": 0.88,
        "navi": 0.88,
        "mouz": 0.92,
        "g2": 0.92,
    }

    lower = name.lower()

    for t, f in elite.items():
        if t in lower:
            return f

    return 1.02

# =========================================================
# GRADE
# =========================================================

def calculate_grade(
    avg,
    line,
    hit_rate,
    over_prob
):

    diff = avg - line

    if over_prob >= 70 and diff >= 5:
        return "9.5/10 🔥 ELITE"

    if over_prob >= 65 and diff >= 3:
        return "8.5/10 ⭐ STRONG"

    if over_prob >= 58:
        return "7.5/10 ✅ GOOD"

    if over_prob >= 53:
        return "6.5/10 👍 LEAN"

    return "5.0/10 ❌ NO BET"

# =========================================================
# MAIN
# =========================================================

def get_player_info(player_name, line=0.0, opponent="N/A"):

    try:

        search = search_player(player_name)

        if not search:
            return _error_response(
                "Player not found",
                player_name,
                line,
                opponent
            )

        pid, slug, display = search

        print(f"✅ PLAYER: {display} ({pid})")

        # =====================================================
        # RESULTS PAGE
        # =====================================================

        results_url = f"{HLTV_BASE}/results?player={pid}"

        print(f"📍 RESULTS URL: {results_url}")

        html, _ = _fetch(
            results_url,
            render=True
        )

        if not html:
            return _error_response(
                "Failed to fetch HLTV results page",
                display,
                line,
                opponent
            )

        print(html[:1200])

        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select("table tbody tr")

        print(f"📊 PROCESSING {len(rows)} ROWS")

        all_maps = []

        # =====================================================
        # ROW PARSER
        # =====================================================

        for i, row in enumerate(rows):

            try:

                text = row.get_text(
                    " ",
                    strip=True
                ).lower()

                if not any(
                    m in text
                    for m in VALID_MAPS
                ):
                    continue

                cols = row.find_all("td")

                if len(cols) < 5:
                    continue

                if i <= 3:
                    print(f"📍 ROW {i}: {text[:250]}")

                map_name = "unknown"

                for m in VALID_MAPS:
                    if m in text:
                        map_name = m
                        break

                opponent_name = "unknown"

                team_links = row.select(
                    "a[href*='/team/']"
                )

                if team_links:
                    opponent_name = (
                        team_links[-1]
                        .text
                        .strip()
                        .lower()
                    )

                kd_match = re.search(
                    r'(\d+)(?:\((\d+)\))?\s*[-–]\s*(\d+)',
                    text
                )

                if not kd_match:
                    continue

                kills = int(kd_match.group(1))

                hs = (
                    int(kd_match.group(2))
                    if kd_match.group(2)
                    else int(kills * 0.37)
                )

                deaths = int(kd_match.group(3))

                if kills <= 0 or deaths <= 0:
                    continue

                score_match = re.search(
                    r'(\d+)\s*[:\-]\s*(\d+)',
                    text
                )

                rounds_played = 22

                if score_match:

                    a = int(score_match.group(1))
                    b = int(score_match.group(2))

                    total_rounds = a + b

                    if 10 <= total_rounds <= 60:
                        rounds_played = total_rounds

                all_maps.append({
                    "date": "N/A",
                    "opponent": opponent_name,
                    "map_name": map_name,
                    "kills": kills,
                    "deaths": deaths,
                    "headshots": hs,
                    "rounds": rounds_played
                })

                print(
                    f"✅ {map_name} | "
                    f"{kills}-{deaths} | "
                    f"{opponent_name}"
                )

            except Exception as e:
                print(f"⚠️ ROW ERROR: {e}")

        # =====================================================
        # CHECK
        # =====================================================

        print(f"✅ EXTRACTED {len(all_maps)} MAPS")

        if len(all_maps) < 2:

            return _error_response(
                f"Found only {len(all_maps)} maps",
                display,
                line,
                opponent
            )

        # =====================================================
        # GROUP MAPS INTO BO3 SERIES
        # =====================================================

        grouped = []

        current = []

        for mp in all_maps:

            if not current:
                current.append(mp)
                continue

            same_team = (
                mp["opponent"]
                == current[-1]["opponent"]
            )

            if same_team:
                current.append(mp)
            else:
                grouped.append(current)
                current = [mp]

        if current:
            grouped.append(current)

        series_totals = []
        hs_totals = []

        paired_rows = []

        for g in grouped:

            if len(g) < 2:
                continue

            m1 = g[0]
            m2 = g[1]

            kills = m1["kills"] + m2["kills"]
            hs = m1["headshots"] + m2["headshots"]
            rounds = m1["rounds"] + m2["rounds"]

            series_totals.append(kills)
            hs_totals.append(hs)

            paired_rows.append({
                "opponent": m1["opponent"],
                "kills": kills,
                "headshots": hs,
                "rounds": rounds,
                "maps": [
                    m1["map_name"],
                    m2["map_name"]
                ]
            })

        if not series_totals:

            return _error_response(
                "No valid BO3 pairings",
                display,
                line,
                opponent
            )

        # =====================================================
        # CORE STATS
        # =====================================================

        avg_2map = round(
            _stats.mean(series_totals),
            2
        )

        median_2map = round(
            _stats.median(series_totals),
            2
        )

        hit_rate = round(
            (
                sum(
                    1 for x in series_totals
                    if x > line
                ) / len(series_totals)
            ) * 100,
            1
        )

        total_k = sum(
            x["kills"]
            for x in all_maps
        )

        total_d = sum(
            x["deaths"]
            for x in all_maps
        )

        total_r = sum(
            x["rounds"]
            for x in all_maps
        )

        total_hs = sum(
            x["headshots"]
            for x in all_maps
        )

        kpr = round(
            total_k / total_r,
            3
        ) if total_r else 0.68

        dpr = round(
            total_d / total_r,
            3
        ) if total_r else 0.65

        hs_rate = round(
            (total_hs / total_k) * 100,
            1
        ) if total_k else 38.0

        role = classify_role(
            kpr,
            dpr,
            hs_rate
        )

        ceiling, floor = calculate_ceiling_floor(
            series_totals
        )

        # =====================================================
        # PROJECTIONS
        # =====================================================

        opp_factor = opponent_factor(opponent)

        expected_kills = round(
            kpr * 44 * opp_factor,
            1
        )

        variance = (
            _stats.variance(series_totals)
            if len(series_totals) > 1
            else expected_kills * 1.25
        )

        if variance <= expected_kills:
            variance = expected_kills * 1.25

        p_nb = expected_kills / variance

        p_nb = max(0.01, min(0.99, p_nb))

        n_nb = (
            (expected_kills ** 2)
            / (variance - expected_kills)
        )

        n_nb = max(1, int(n_nb))

        np.random.seed(42)

        sim = np.random.negative_binomial(
            n_nb,
            p_nb,
            100000
        )

        over_prob = round(
            (
                np.sum(sim > line)
                / 100000
            ) * 100,
            1
        )

        under_prob = round(
            100 - over_prob,
            1
        )

        # =====================================================
        # BET LOGIC
        # =====================================================

        if (
            avg_2map > line
            and median_2map > line
            and hit_rate >= 60
        ):
            bet = "OVER"

        elif (
            avg_2map < line
            and median_2map < line
            and hit_rate <= 40
        ):
            bet = "UNDER"

        else:
            bet = "NO BET"

        grade = calculate_grade(
            avg_2map,
            line,
            hit_rate,
            over_prob
        )

        # =====================================================
        # RETURN
        # =====================================================

        return {

            "Player": display,

            "Match": f"vs {opponent}",

            "Prop Line": f"{line} Kills",

            "Bet recommendation": bet,

            "Final grade": grade,

            "Recent sample": f"{len(series_totals)} BO3 series",

            "Recent Totals M1+M2": series_totals,

            "Recent HS Totals": hs_totals,

            "Average": avg_2map,

            "Median": median_2map,

            "Hit Rate": f"{hit_rate}%",

            "Expected Kills": expected_kills,

            "Over Probability": f"{over_prob}%",

            "Under Probability": f"{under_prob}%",

            "Role": role,

            "KPR": kpr,

            "DPR": dpr,

            "HS%": hs_rate,

            "Rating 3.0": round(
                1 + ((kpr - 0.68) * 2),
                2
            ),

            "Impact": round(
                1 + ((kpr - 0.68) * 1.5),
                2
            ),

            "Ceiling": ceiling,

            "Floor": floor,

            "Std Dev": round(
                _stats.stdev(series_totals),
                2
            ) if len(series_totals) > 1 else 0,

            "Opponent Factor": opp_factor,

            "Per Map Stats": analyze_maps(all_maps),

            "Paired Series": paired_rows,

            "Raw Maps": all_maps[:25]
        }

    except Exception as e:

        print(f"💥 CRITICAL ERROR: {e}")

        return _error_response(
            str(e),
            player_name,
            line,
            opponent
        )
