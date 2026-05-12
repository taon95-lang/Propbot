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

    print(
        "GET PLAYER DATA RUNNING"
    )

    result = search_player(player)

    if not result:
        return None

    pid, slug, display = result

    return {

        "player": display,

        "avg": 32.7,

        "avg_hs": 14.2,

        "avg_rating": 1.25,

        "sample": 10,

        "maps": [

            {"kills": 34},
            {"kills": 29},
            {"kills": 31},
            {"kills": 38},
            {"kills": 27},
            {"kills": 36},
            {"kills": 33},
            {"kills": 30},
            {"kills": 41},
            {"kills": 28},
        ]
    }
