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


from curl_cffi import requests

SESSION = requests.Session(
    impersonate="chrome110"
)

from curl_cffi import requests

SESSION = requests.Session(
    impersonate="chrome110"
)

def get_player_data(player, opponent=None):

    result = search_player(player)

    if not result:
        return None

    pid, slug, display = result

    url = (
        f"https://www.hltv.org/results?player={pid}"
    )

    print(
        "REQUESTING:",
        url
    )

    try:

        r = SESSION.get(
            url,
            timeout=20
        )

        print(
            "STATUS:",
            r.status_code
        )

        html = r.text

        print(
            html[:1000]
        )

    except Exception as e:

        print(
            "ERROR:",
            e
        )

        return None

    return {

        "player": display,

        "avg": 1,

        "avg_hs": 1,

        "avg_rating": 1,

        "sample": 1,

        "maps": [
            {"kills": 1}
        ]
    }
