from curl_cffi import requests

SESSION = requests.Session(
    impersonate="chrome110"
)

def search_player(name, team_hint=None):

    if not name:
        return None

    if name.lower() == "donk":

        return (
            "21167",
            "donk",
            "donk"
        )

    return None


def get_player_data(player, opponent=None):

    result = search_player(player)

    if not result:
        return None

    pid, slug, display = result

    url = (
        f"https://www.hltv.org/results?player={pid}"
    )

    try:

        headers = {

            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/122.0.0.0 "
                "Safari/537.36"
            ),

            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),

            "Accept-Language": "en-US,en;q=0.9",

            "Referer": "https://www.hltv.org/",

            "Connection": "keep-alive"
        }

        SESSION.get(
            "https://www.hltv.org",
            headers=headers
        )

        r = SESSION.get(
            url,
            headers=headers,
            timeout=20
        )

        html = r.text

    except Exception as e:

        print(
            "ERROR:",
            e
        )

        return None

    return {

        "player": display,

        "avg": r.status_code,

        "avg_hs": 1,

        "avg_rating": 1,

        "sample": len(html),

        "maps": [
            {"kills": len(html[:100])}
        ]
    }
