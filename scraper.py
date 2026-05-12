import re
import requests
import logging

from bs4 import BeautifulSoup

# =====================================================
# LOGGER
# =====================================================

logger = logging.getLogger(__name__)

# =====================================================
# HLTV
# =====================================================

HLTV_BASE = "https://www.hltv.org"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/122 Safari/537.36"
    )
}

# =====================================================
# SEARCH PLAYER
# =====================================================

def search_player(name, team_hint=None):

    search_url = (
        f"{HLTV_BASE}/search?term={name}"
    )

    try:

        r = requests.get(
            search_url,
            headers=HEADERS,
            timeout=20
        )

        text = r.text

        matches = re.findall(
            r"/player/(\d+)/([\w-]+)",
            text
        )

        if not matches:
            return None

        pid, slug = matches[0]

        display = (
            slug
            .replace("-", " ")
            .title()
        )

        return (
            pid,
            slug,
            display
        )

    except Exception as e:

        print("SEARCH ERROR:", e)

        return None

# =====================================================
# PARSE REAL MAP STATS
# =====================================================

def parse_map_stats(stats_html, player_slug):

    soup = BeautifulSoup(
        stats_html,
        "html.parser"
    )

    slug_clean = re.sub(
        r"[^a-z0-9]",
        "",
        player_slug.lower()
    )

    all_rows = soup.find_all("tr")

    for row in all_rows:

        row_text = row.get_text(
            " ",
            strip=True
        ).lower()

        row_clean = re.sub(
            r"[^a-z0-9]",
            "",
            row_text
        )

        if slug_clean not in row_clean:
            continue

        cells = row.find_all("td")

        stats = {
            "kills": None,
            "deaths": None,
            "hs": None,
            "rating": None,
            "adr": None,
            "kast": None
        }

        for cell in cells:

            txt = cell.get_text(
                " ",
                strip=True
            )

            # =========================================
            # KILLS (HS)
            # Example:
            # 23 (11)
            # =========================================

            khs = re.search(
                r"(\d+)\s*\((\d+)\)",
                txt
            )

            if khs:

                stats["kills"] = int(
                    khs.group(1)
                )

                stats["hs"] = int(
                    khs.group(2)
                )

            # =========================================
            # K-D
            # Example:
            # 23-14
            # =========================================

            kd = re.search(
                r"^(\d+)[-–](\d+)$",
                txt
            )

            if kd:

                stats["kills"] = int(
                    kd.group(1)
                )

                stats["deaths"] = int(
                    kd.group(2)
                )

            # =========================================
            # RATING
            # =========================================

            rating_match = re.match(
                r"^(\d\.\d{2})$",
                txt
            )

            if rating_match:

                rating = float(
                    rating_match.group(1)
                )

                if (
                    rating >= 0.30
                    and rating <= 3.00
                ):

                    stats["rating"] = rating

            # =========================================
            # ADR
            # =========================================

            adr_match = re.match(
                r"^(\d{2,3}\.\d)$",
                txt
            )

            if adr_match:

                adr = float(
                    adr_match.group(1)
                )

                if adr >= 30 and adr <= 200:

                    stats["adr"] = adr

            # =========================================
            # KAST
            # =========================================

            kast_match = re.match(
                r"^(\d{1,3}\.\d)%$",
                txt
            )

            if kast_match:

                kast = float(
                    kast_match.group(1)
                )

                stats["kast"] = kast

        if stats["kills"] is not None:

            return stats

    return None

# =====================================================
# GET REAL PLAYER DATA
# =====================================================

def get_player_data(name, team_hint=None):

    # =============================================
    # PLAYER SEARCH
    # =============================================

    player = search_player(name)

    if not player:
        return None

    pid, slug, display = player

    # =============================================
    # RESULTS PAGE
    # =============================================

    results_url = (
        f"{HLTV_BASE}/results?player={pid}"
    )

    try:

        r = requests.get(
            results_url,
            headers=HEADERS,
            timeout=20
        )

        html = r.text

    except Exception as e:

        print("RESULTS ERROR:", e)

        return None

    # =============================================
    # RECENT MATCH LINKS
    # =============================================

    match_links = re.findall(
        r"/matches/(\d+)/([\w-]+)",
        html
    )

    match_links = list(
        dict.fromkeys(match_links)
    )

    if not match_links:
        return None

    all_maps = []

    # =============================================
    # RECENT BO3S ONLY
    # =============================================

    for match_id, match_slug in match_links[:10]:

        match_url = (
            f"{HLTV_BASE}/matches/"
            f"{match_id}/{match_slug}"
        )

        try:

            r = requests.get(
                match_url,
                headers=HEADERS,
                timeout=20
            )

            match_html = r.text

        except Exception as e:

            print("MATCH ERROR:", e)

            continue

        # =========================================
        # BO3 FILTER
        # =========================================

        if "best of 3" not in match_html.lower():
            continue

        # =========================================
        # MAPSTATS IDS
        # =========================================

        map_ids = re.findall(
            r"/stats/matches/mapstatsid/(\d+)/",
            match_html
        )

        map_ids = list(
            dict.fromkeys(map_ids)
        )

        # =========================================
        # MAPS 1–2 ONLY
        # =========================================

        map_ids = map_ids[:2]

        # =========================================
        # OPEN MAPSTATS PAGE
        # =========================================

        for map_id in map_ids:

            stats_url = (
                f"{HLTV_BASE}/stats/matches/"
                f"mapstatsid/{map_id}/match"
            )

            try:

                stats_r = requests.get(
                    stats_url,
                    headers=HEADERS,
                    timeout=20
                )

                stats_html = stats_r.text

            except Exception as e:

                print(
                    "MAPSTATS ERROR:",
                    e
                )

                continue

            # =====================================
            # PARSE REAL STATS
            # =====================================

            parsed = parse_map_stats(
                stats_html,
                slug
            )

            if parsed:

                parsed.update({

                    "match_id": match_id,

                    "map_id": map_id
                })

                all_maps.append(parsed)

        if len(all_maps) >= 20:
            break

    # =============================================
    # NO REAL DATA
    # =============================================

    if not all_maps:
        return None

    # =============================================
    # REAL CALCULATIONS
    # =============================================

    valid_kills = [
        m["kills"]
        for m in all_maps
        if m["kills"] is not None
    ]

    valid_hs = [
        m["hs"]
        for m in all_maps
        if m["hs"] is not None
    ]

    valid_rating = [
        m["rating"]
        for m in all_maps
        if m["rating"] is not None
    ]

    valid_adr = [
        m["adr"]
        for m in all_maps
        if m["adr"] is not None
    ]

    valid_kast = [
        m["kast"]
        for m in all_maps
        if m["kast"] is not None
    ]

    if not valid_kills:
        return None

    avg_kills = round(
        sum(valid_kills)
        / len(valid_kills),
        2
    )

    avg_hs = round(
        sum(valid_hs)
        / len(valid_hs),
        2
    ) if valid_hs else 0

    avg_rating = round(
        sum(valid_rating)
        / len(valid_rating),
        2
    ) if valid_rating else 0

    avg_adr = round(
        sum(valid_adr)
        / len(valid_adr),
        2
    ) if valid_adr else 0

    avg_kast = round(
        sum(valid_kast)
        / len(valid_kast),
        2
    ) if valid_kast else 0

    # =============================================
    # RETURN REAL DATA
    # =============================================

    return {

        "player": display,

        "avg": avg_kills,

        "avg_hs": avg_hs,

        "avg_rating": avg_rating,

        "avg_adr": avg_adr,

        "avg_kast": avg_kast,

        "sample": len(valid_kills),

        "maps": all_maps
    }

# =====================================================
# TEAM DEFENSE PLACEHOLDER
# =====================================================

def get_team_conceded(team_name):

    return 0.95
