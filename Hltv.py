import requests
from bs4 import BeautifulSoup

headers = {
“User-Agent”: (
“Mozilla/5.0 “
“(Windows NT 10.0; Win64; x64) “
“AppleWebKit/537.36 “
“(KHTML, like Gecko) “
“Chrome/122.0 Safari/537.36”
)
}

def search_player(player_name):

url = f"https://www.hltv.org/search?term={player_name}"

response = requests.get(url, headers=headers)

if response.status_code != 200:
    return None

try:
    data = response.json()

    players = data[0]["players"]

    if not players:
        return None

    first_player = players[0]

    return {
        "id": first_player["id"],
        "name": first_player["name"]
    }

except Exception as e:
    print("Search Error:", e)
    return None
