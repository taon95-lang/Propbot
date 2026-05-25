import os
import re
import time
import statistics as stats
from collections import defaultdict
from urllib.parse import quote, urljoin

import numpy as np
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests  # type: ignore
except Exception:
    import requests  # type: ignore


HLTV_BASE = "https://www.hltv.org"
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

STATIC_IDS = {
    "donk": ("21167", "donk"),
    "zywoo": ("11893", "zywoo"),
    "m0nesy": ("19230", "m0nesy"),
    "niko": ("3741", "niko"),
    "jl": ("19206", "jl"),
    "xertion": ("20312", "xertion"),
    "ammar": ("21109", "ammar"),
}

MAP_CODE = {
    "anc": "Ancient",
    "anb": "Anubis",
    "d2": "Dust2",
    "inf": "Inferno",
    "mrg": "Mirage",
    "nuke": "Nuke",
    "ovp": "Overpass",
    "vrt": "Vertigo",
    "ancient": "Ancient",
    "anubis": "Anubis",
    "dust2": "Dust2",
    "inferno": "Inferno",
    "mirage": "Mirage",
    "overpass": "Overpass",
    "vertigo": "Vertigo",
}


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def fnum(value, default=0.0):
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value in [None, "", "N/A", "-", "--"]:
            return default
        return int(float(str(value).replace("%", "").replace(",", "").strip()))
    except Exception:
        return default


def visible_lines(html: str):
    soup = BeautifulSoup(html, "html.parser")
    return [clean(x) for x in soup.stripped_strings if clean(x)]


def visible_text(html: str) -> str:
    return " ".join(visible_lines(html))


def fetch(url: str, render: bool = False, timeout: int = 60):
    targets = []

    if SCRAPERAPI_KEY:
        encoded = quote(url, safe="")
        for use_render in (render, not render, True):
            proxy = (
                "http://api.scraperapi.com"
                f"?api_key={SCRAPERAPI_KEY}"
                f"&url={encoded}"
                f"&country_code=us"
                f"&keep_headers=true"
                f"{'&render=true' if use_render else ''}"
            )
            targets.append(proxy)
    else:
        targets.append(url)

    for target in targets:
        try:
            resp = requests.get(
                target,
                headers=HEADERS,
                timeout=timeout,
                allow_redirects=True
            )

            if resp.status_code == 200 and len(resp.text or "") > 800:
                final_url = resp.headers.get("Sa-Final-Url") or getattr(resp, "url", url)
                return resp.text, final_url

        except Exception:
            pass

        time.sleep(1.0)

    return None, None


def search_player(name: str):
    q = norm(name)

    if q in STATIC_IDS:
        pid, slug = STATIC_IDS[q]
        return pid, slug, slug.replace("-", " ").title()

    html, final_url = fetch(
        f"{HLTV_BASE}/search?query={quote(name)}",
        render=True
    )

    if not html:
        return None

    if final_url and "/player/" in final_url:
        m = re.search(r"/player/(\d+)/([^/?#\s]+)", final_url)

        if m:
            pid, slug = m.group(1), m.group(2)
            return pid, slug, slug.replace("-", " ").title()

    soup = BeautifulSoup(html, "html.parser")
    found = []

    for a in soup.find_all("a", href=True):
        m = re.search(r"/player/(\d+)/([a-zA-Z0-9_-]+)", a["href"])

        if m:
            pid, slug = m.group(1), m.group(2)

            if pid not in {x[0] for x in found}:
                found.append((pid, slug))

    if not found:
        return None

    for pid, slug in found:
        if q == norm(slug) or q in norm(slug):
            return pid, slug, slug.replace("-", " ").title()

    pid, slug = found[0]
    return pid, slug, slug.replace("-", " ").title()


def error_response(msg, player_name, line, opponent):
    return {
        "Player": str(player_name).title(),
        "Match": f"vs {str(opponent).title()}",
        "Prop Line": f"{line} Kills",
        "Bet recommendation": "NO BET",
        "error": msg,
    }


def profile_metrics(profile_html: str):
    text = visible_text(profile_html)

    out = {
        "rating_3": "N/A",
        "firepower": "N/A",
        "entrying": "N/A",
        "trading": "N/A",
        "opening": "N/A",
        "clutching": "N/A",
        "sniping": "N/A",
        "utility": "N/A",
        "all_time_hs_pct": "N/A",
        "team": "N/A",
        "team_url": None,
    }

    m = re.search(
        r"statistics\(Past 3 months.*?Rating 3\.0\s+([0-9]+(?:\.[0-9]+)?)"
        r".*?Firepower\s+(\d+)/100"
        r".*?Entrying\s+(\d+)/100"
        r".*?Trading\s+(\d+)/100"
        r".*?Opening\s+(\d+)/100"
        r".*?Clutching\s+(\d+)/100"
        r".*?Sniping\s+(\d+)/100"
        r".*?Utility\s+(\d+)/100",
        text,
        re.I,
    )

    if m:
        out.update({
            "rating_3": m.group(1),
            "firepower": safe_int(m.group(2)),
            "entrying": safe_int(m.group(3)),
            "trading": safe_int(m.group(4)),
            "opening": safe_int(m.group(5)),
            "clutching": safe_int(m.group(6)),
            "sniping": safe_int(m.group(7)),
            "utility": safe_int(m.group(8)),
        })

    m = re.search(r"Headshots\s+([0-9]+(?:\.[0-9]+)?)%", text, re.I)

    if m:
        out["all_time_hs_pct"] = f"{m.group(1)}%"

    soup = BeautifulSoup(profile_html, "html.parser")

    for a in soup.find_all("a", href=True):
        if re.search(r"^/team/\d+/[^/]+$", a["href"]):
            out["team"] = clean(a.get_text(" "))
            out["team_url"] = urljoin(HLTV_BASE, a["href"])
            break

    return out


def stats_metrics(stats_html: str):
    text = visible_text(stats_html)

    out = {
        "KPR": "N/A",
        "DPR": "N/A",
        "ADR": "N/A",
        "KAST": "N/A",
        "Impact": "N/A",
        "Opening KPR": "N/A",
        "Trade KPR": "N/A",
        "Round Swing": "N/A",
        "Multi-kill %": "N/A",
        "vs_top": {},
    }

    simple_before = {
        "KPR": r"([0-9]+(?:\.[0-9]+)?)\s+KPR\b",
        "DPR": r"([0-9]+(?:\.[0-9]+)?)\s+DPR\b",
        "ADR": r"([0-9]+(?:\.[0-9]+)?)\s+ADR\b",
        "KAST": r"([0-9]+(?:\.[0-9]+)?%)\s+KAST\b",
        "Multi-kill %": r"([0-9]+(?:\.[0-9]+)?%)\s+Rounds with a multi-kill\b",
    }

    for key, rx in simple_before.items():
        m = re.search(rx, text, re.I)

        if m:
            out[key] = m.group(1)

    simple_after = {
        "Impact": r"Impact rating\s+([0-9]+(?:\.[0-9]+)?)",
        "Opening KPR": r"Opening kills per round\s+([0-9]+(?:\.[0-9]+)?)",
        "Trade KPR": r"Trade kills per round\s+([0-9]+(?:\.[0-9]+)?)",
        "Round Swing": r"Round swing\s+([+\-]?[0-9]+(?:\.[0-9]+)?%)",
    }

    for key, rx in simple_after.items():
        m = re.search(rx, text, re.I)

        if m:
            out[key] = m.group(1)

    for cutoff in (5, 10, 20, 30, 50):
        m = re.search(
            rf"([0-9]+(?:\.[0-9]+)?|-)\s+vs top {cutoff} opponents\s+\((\d+) maps\)",
            text,
            re.I
        )

        if m:
            out["vs_top"][cutoff] = {
                "rating": m.group(1),
                "maps": safe_int(m.group(2)),
            }

    return out


def team_rank(team_html: str):
    text = visible_text(team_html)

    out = {
        "HLTV Rank": "N/A",
        "Valve Rank": "N/A"
    }

    m = re.search(r"World ranking\s+#(\d+)", text, re.I)

    if m:
        out["HLTV Rank"] = f"#{m.group(1)}"

    m = re.search(r"Valve ranking\s+Beta\s+#(\d+)", text, re.I)

    if m:
        out["Valve Rank"] = f"#{m.group(1)}"

    return out


def derive_role(profile):
    sniping = safe_int(profile.get("sniping"))
    firepower = safe_int(profile.get("firepower"))
    entrying = safe_int(profile.get("entrying"))
    trading = safe_int(profile.get("trading"))
    opening = safe_int(profile.get("opening"))
    utility = safe_int(profile.get("utility"))

    if sniping >= 55:
        return "Primary AWPer"

    if firepower >= 65 and opening >= 45:
        return "Star Entry Rifler"

    if entrying >= 55 and opening >= 35:
        return "Entry / Space Creator"

    if trading >= 60 and firepower >= 55:
        return "Trade / Lurk Rifler"

    if utility >= 60 and firepower <= 52:
        return "Support / Anchor"

    if firepower >= 58 and trading >= 50:
        return "Flex Rifler"

    return "Flex / Support Rifler"


def bootstrap(values, line):
    if not values:
        return {
            "mean": "N/A",
            "median": "N/A",
            "std": "N/A",
            "q25": "N/A",
            "q75": "N/A",
            "over": "N/A",
            "under": "N/A",
            "edge": "N/A"
        }

    arr = np.array(values, dtype=np.int32)

    np.random.seed(42)

    sims = np.random.choice(arr, 100000, replace=True)

    over = round(float((sims > line).mean() * 100), 1)

    return {
        "mean": round(float(np.mean(sims)), 2),
        "median": round(float(np.median(sims)), 2),
        "std": round(float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0, 2),
        "q25": round(float(np.percentile(sims, 25)), 1),
        "q75": round(float(np.percentile(sims, 75)), 1),
        "over": f"{over}%",
        "under": f"{round(100 - over, 1)}%",
        "edge": f"{round(over - 50, 1)}%",
    }


def weighted_projection(values):
    if not values:
        return 0.0

    recent = values[:5]
    earlier = values[5:10]

    if not earlier:
        return round(stats.mean(recent), 1)

    return round(
        (stats.mean(recent) * 0.6) +
        (stats.mean(earlier) * 0.4),
        1
    )


def ceiling_floor(values):
    if not values:
        return "N/A", "N/A"

    if len(values) < 3:
        return max(values), min(values)

    s = sorted(values)

    return (
        round(stats.mean(s[-3:]), 1),
        round(stats.mean(s[:3]), 1)
    )


def grade_pick(proj, median_val, hit_rate, line, role, h2h_avg, moneyline):
    side = "NO BET"

    if (
        proj >= line + 1.5 and
        median_val >= line + 1.0 and
        hit_rate >= 60
    ):
        side = "OVER"

    elif (
        proj <= line - 1.5 and
        median_val <= line - 1.0 and
        hit_rate <= 40
    ):
        side = "UNDER"

    score = 5.0

    score += min(2.0, abs(proj - line) / 2.0)
    score += min(1.25, abs(median_val - line) / 3.0)

    if hit_rate >= 70:
        score += 1.5

    elif hit_rate >= 60:
        score += 1.0

    elif hit_rate <= 30:
        score += 1.0

    elif hit_rate <= 40:
        score += 0.5

    if (
        side == "OVER" and
        role in {
            "Primary AWPer",
            "Star Entry Rifler",
            "Entry / Space Creator",
            "Flex Rifler"
        }
    ):
        score += 0.4

    if side == "UNDER" and role == "Support / Anchor":
        score += 0.4

    if h2h_avg is not None:
        if side == "OVER" and h2h_avg > line:
            score += 0.4

        if side == "UNDER" and h2h_avg < line:
            score += 0.4

    ml = fnum(moneyline, 0.0)

    if ml:
        if side == "OVER" and ml <= 1.45:
            score -= 0.35

        if side == "UNDER" and ml <= 1.45:
            score += 0.25

    if side == "NO BET":
        score = max(4.8, min(score, 6.0))

    score = round(max(1.0, min(10.0, score)), 1)

    if score >= 8.5:
        label = "🔥 ELITE EDGE"

    elif score >= 7.5:
        label = "✅ STRONG PLAY"

    elif score >= 6.5:
        label = "👍 SOLID LEAN"

    elif score >= 5.5:
        label = "⚖️ SMALL EDGE"

    else:
        label = "❌ NO BET"

    return side, f"{score}/10 {label}", score


def get_player_info(player_name, line=0.0, opponent="N/A"):
    try:
        line = float(line)

        found = search_player(player_name)

        if not found:
            return error_response(
                f"Could not find player '{player_name}' on HLTV.",
                player_name,
                line,
                opponent
            )

        pid, slug, display = found

        profile_html, _ = fetch(
            f"{HLTV_BASE}/player/{pid}/{slug}",
            render=True
        )

        if not profile_html:
            return error_response(
                "Profile page blocked or unavailable.",
                display,
                line,
                opponent
            )

        profile = profile_metrics(profile_html)

        role = derive_role(profile)

        return {
            "Player": display,
            "Role": role,
            "Rating 3.0": profile["rating_3"],
            "Firepower": profile["firepower"],
            "Entrying": profile["entrying"],
            "Trading": profile["trading"],
            "Opening": profile["opening"],
            "Clutching": profile["clutching"],
            "Sniping": profile["sniping"],
            "Utility": profile["utility"],
            "All-time profile HS %": profile["all_time_hs_pct"],
            "Bet recommendation": "WORKING",
            "error": None,
        }

    except Exception as exc:
        return error_response(
            f"System crash: {str(exc)}",
            player_name,
            line,
            opponent
        )
