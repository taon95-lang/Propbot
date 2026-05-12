def search_player(name, team_hint=None):

    if name.lower() == "donk":

        return (
            "21167",
            "donk",
            "donk"
        )

    return None
from curl_cffi import requests
import re

SESSION = requests.Session(
    impersonate="chrome110"
)

def get_player_data(player, opponent=None):

    result = search_player(player)

    if not result:
        return None

    pid, slug, display = result

    results_url = (
        f"https://www.hltv.org/results?player={pid}"
    )

    print(
        "RESULTS URL:",
        results_url
    )

    try:

        r = SESSION.get(
            results_url,
            timeout=20
        )

        html = r.text

        print(html[:2000])

        print(
            "RESULTS STATUS:",
            r.status_code
        )

    except Exception as e:

        print(
            "REQUEST ERROR:",
            e
        )

        return None

    match_links = re.findall(
        r'/matches/(\d+)/([\w-]+)',
        html
    )

    print(
        "MATCH LINKS:",
        match_links[:10]
    )

    if not match_links:
        return None

    return {

        "player": display,

        "avg": 0,

        "avg_hs": 0,

        "avg_rating": 0,

        "sample": len(match_links),

        "maps": [
            {"kills": 0}
        ]
    }
