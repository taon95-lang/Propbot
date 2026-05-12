import re
from bs4 import BeautifulSoup
from curl_cffi import requests

# =====================================================
# HLTV CONFIG
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

SESSION = requests.Session(
    impersonate="chrome110"
)

# =====================================================
# SEARCH PLAYER
# =====================================================

def search_player(name, team_hint=None):

    try:

        url = (
            f"{HLTV_BASE}/search?term={name}"
        )

        r = SESSION.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        print(
            "SEARCH STATUS:",
            r.status_code
        )

        # =========================================
        # JSON SEARCH
        # =========================================

        try:

            data = r.json()

            print(
                "JSON DATA FOUND"
            )

        except Exception as e:

            print(
                "JSON ERROR:",
                e
            )

            print(
                "RAW HTML:",
                r.text[:500]
            )

            return None

        # =========================================
        # FIND PLAYERS
        # =========================================

        players = []

        for section in data:

            if (
                isinstance(section, dict)
                and section.get("players")
            ):

                players = section["players"]

                break

        print(
            "PLAYERS:",
            players[:3]
        )

        if not players:
            return None

        player = players[0]

        pid = player.get("id")

        slug = (
            player.get("slug")
            or player.get("name")
            or name
        )

        display = (
            player.get("name")
            or slug
        )

        return (
            str(pid),
            slug,
            display
        )

    except Exception as e:

        print(
            "SEARCH ERROR:",
            e
        )

        return None

# =====================================================
# PARSE MAP STATS
# =====================================================

def parse_map_stats(html, player_slug):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    slug_clean = re.sub(
        r"[^a-z0-9]",
        "",
        player_slug.lower()
    )

    for row in soup.find_all("tr"):

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

        stats = {
            "kills": None,
            "deaths": None,
            "hs": None,
            "rating": None,
            "adr": None,
            "kast": None,
        }

        for cell in row.find_all("td"):

            txt = cell.get_text(
                " ",
                strip=True
            )

            # =====================================
            # KILLS + HS
            # =====================================

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

            # =====================================
            # KD
            # =====================================

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

            # =====================================
            # RATING
            # =====================================

            rating = re.match(
                r"^(\d\.\d{2})$",
                txt
            )

            if rating:

                stats["rating"] = float(
                    rating.group(1)
                )

            # =====================================
            # ADR
            # =====================================

            adr = re.match(
                r"^(\d{2,3}\.\d)$",
                txt
            )

            if adr:

                val = float(
                    adr.group(1)
                )

                if 30 <= val <= 200:

                    stats["adr"] = val

            # =====================================
            # KAST
            # =====================================

            kast = re.match(
                r"^(\d{1,3}\.\d)%$",
                txt
            )

            if kast:

                stats["kast"] = float(
                    kast.group(1)
                )

        if stats["kills"] is not None:

            return stats

    return None

# =====================================================
# GET PLAYER DATA
# =====================================================

def get_player_data(name, team_hint=None):

    player = search_player(name)

    print(
        "SEARCH PLAYER RESULT:",
        player
    )

    if not player:
        return None

    pid, slug, display = player

    # =============================================
    # RESULTS PAGE
    # =============================================

    try:

        results_url = (
            f"{HLTV_BASE}/results?player={pid}"
        )

        r = SESSION.get(
            results_url,
            headers=HEADERS,
            timeout=20
        )

        html = r.text

    except Exception as e:

        print(
            "RESULTS ERROR:",
            e
        )

        return None

    # =============================================
    # MATCH LINKS
    # =============================================

    match_links = re.findall(
        r"/matches/(\d+)/([\w-]+)",
        html
    )

    match_links = list(
        dict.fromkeys(match_links)
    )

    print(
        "MATCH LINKS:",
        match_links[:5]
    )

    if not match_links:
        return None

    all_maps = []

    # =============================================
    # RECENT MATCHES
    # =============================================

    for match_id, match_slug in match_links[:10]:

        match_url = (
            f"{HLTV_BASE}/matches/"
            f"{match_id}/{match_slug}"
        )

        try:

            r = SESSION.get(
                match_url,
                headers=HEADERS,
                timeout=20
            )

            match_html = r.text

        except Exception as e:

            print(
                "MATCH ERROR:",
                e
            )

            continue

        # =========================================
        # BO3 ONLY
        # =========================================

        if "best of 3" not in match_html.lower():
            continue

        # =========================================
        # MAP IDS
        # =========================================

        map_ids = re.findall(
            r"/stats/matches/mapstatsid/(\d+)/",
            match_html
        )

        map_ids = list(
            dict.fromkeys(map_ids)
        )[:2]

        print(
            "MAP IDS:",
            map_ids
        )

        # =========================================
        # MAPSTATS
        # =========================================

        for map_id in map_ids:

            stats_url = (
                f"{HLTV_BASE}/stats/matches/"
                f"mapstatsid/{map_id}/match"
            )

            try:

                stats_r = SESSION.get(
                    stats_url,
                    headers=HEADERS,
                    timeout=20
                )

                parsed = parse_map_stats(
                    stats_r.text,
                    slug
                )

                print(
                    "PARSED:",
                    parsed
                )

            except Exception as e:

                print(
                    "MAPSTATS ERROR:",
                    e
                )

                continue

            if parsed:

                parsed["match_id"] = match_id

                parsed["map_id"] = map_id

                all_maps.append(
                    parsed
                )

        if len(all_maps) >= 20:
            break

    print(
        "TOTAL MAPS:",
        len(all_maps)
    )

    if not all_maps:
        return None

    # =============================================
    # REAL DATA
    # =============================================

    kills = [
        m["kills"]
        for m in all_maps
        if m["kills"] is not None
    ]

    hs = [
        m["hs"]
        for m in all_maps
        if m["hs"] is not None
    ]

    ratings = [
        m["rating"]
        for m in all_maps
        if m["rating"] is not None
    ]

    adr = [
        m["adr"]
        for m in all_maps
        if m["adr"] is not None
    ]

    kast = [
        m["kast"]
        for m in all_maps
        if m["kast"] is not None
    ]

    if not kills:
        return None

    return {

        "player": display,

        "avg": round(
            sum(kills) / len(kills),
            2
        ),

        "avg_hs": round(
            sum(hs) / len(hs),
            2
        ) if hs else 0,

        "avg_rating": round(
            sum(ratings) / len(ratings),
            2
        ) if ratings else 0,

        "avg_adr": round(
            sum(adr) / len(adr),
            2
        ) if adr else 0,

        "avg_kast": round(
            sum(kast) / len(kast),
            2
        ) if kast else 0,

        "sample": len(kills),

        "maps": all_maps
    }

# =====================================================
# TEAM DEFENSE PLACEHOLDER
# =====================================================

def get_team_conceded(team_name):

    return 0.95