import re
import time
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests
except ImportError:
    import requests

HLTV_BASE = "https://www.hltv.org"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
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
    "spirit": ("23920", "spirit"),
    "chopper": ("20008", "chopper"),
    "marix": ("16667", "marix"),
    "keoz": ("14049", "keoz"),
    "eraa": ("21269", "eraa"),
    "tomate": ("20033", "tomate"),
    "avid": ("21353", "avid"),
    "8juho8": ("21508", "8juho8"),
    "matys": ("19088", "matys"),
    "forsyy": ("21184", "forsyy"),
    "h4san4tor": ("21521", "h4san4tor"),
    "kaide": ("20999", "kaide"),
    "glowiing": ("21556", "glowiing"),
    "caleyy": ("14154", "caleyy"),
}


def normalize(value):
    """Normalize string for comparison."""
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def clean_text(value):
    """Clean whitespace from text."""
    return re.sub(r"\s+", " ", value or "").strip()


def fetch(url, render=False, timeout=60):
    """Fetch a URL with retry logic and optional rendering."""
    if not url:
        return None, None
    
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True
        )
        
        if response.status_code == 200 and len(response.text or "") > 500:
            return response.text, response.url
        
    except requests.RequestException as e:
        print(f"Fetch error for {url}: {e}")
    except Exception as e:
        print(f"Unexpected error fetching {url}: {e}")
    
    time.sleep(0.5)
    return None, None


def search_player(player_name):
    """
    Search for a player on HLTV using the search endpoint.
    Returns a dict with 'id', 'name', 'slug', or None if not found.
    """
    if not player_name or not isinstance(player_name, str):
        return None
    
    player_name = player_name.strip()
    q = normalize(player_name)
    
    # Check static IDs first (cached common players)
    if q in STATIC_IDS:
        pid, slug = STATIC_IDS[q]
        return {
            "id": pid,
            "name": slug.replace("-", " ").title(),
            "slug": slug
        }
    
    # Try HLTV search
    search_url = f"{HLTV_BASE}/search?query={quote(player_name)}"
    html, final_url = fetch(search_url, render=False)
    
    if not html:
        print(f"Could not fetch search results for '{player_name}'")
        return None
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # Check if we got redirected to a player profile
        if final_url and "/player/" in final_url:
            match = re.search(r"/player/(\d+)/([^/?#\s]+)", final_url)
            if match:
                pid, slug = match.group(1), match.group(2)
                return {
                    "id": pid,
                    "name": slug.replace("-", " ").title(),
                    "slug": slug
                }
        
        # Parse search results from page
        found = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            match = re.search(r"/player/(\d+)/([a-zA-Z0-9_-]+)", href)
            if match:
                pid, slug = match.group(1), match.group(2)
                display_name = clean_text(a.get_text(" "))
                
                # Avoid duplicates
                if pid not in [x["id"] for x in found]:
                    found.append({
                        "id": pid,
                        "name": display_name or slug.replace("-", " ").title(),
                        "slug": slug
                    })
        
        if not found:
            print(f"No players found for '{player_name}'")
            return None
        
        # Prefer exact or close matches
        for player in found:
            if normalize(player["slug"]) == q or q in normalize(player["slug"]):
                return player
        
        # Return first result if no close match
        return found[0]
    
    except Exception as e:
        print(f"Search parsing error: {e}")
        return None


def get_player_profile(player_id, slug):
    """Fetch player profile page from HLTV."""
    if not player_id or not slug:
        return None
    
    url = f"{HLTV_BASE}/player/{player_id}/{slug}"
    html, _ = fetch(url, render=False)
    return html


def get_player_stats(player_id, slug):
    """Fetch player stats page from HLTV."""
    if not player_id or not slug:
        return None
    
    url = f"{HLTV_BASE}/stats/players/{player_id}/{slug}"
    html, _ = fetch(url, render=False)
    return html


def get_match_page(match_id):
    """Fetch a specific match page from HLTV."""
    if not match_id:
        return None
    
    url = f"{HLTV_BASE}/matches/{match_id}"
    html, _ = fetch(url, render=False)
    return html


def extract_player_metrics(stats_html):
    """Extract key metrics from player stats page."""
    if not stats_html:
        return {}
    
    try:
        soup = BeautifulSoup(stats_html, "html.parser")
        text = soup.get_text()
        
        metrics = {
            "KPR": "N/A",
            "DPR": "N/A",
            "ADR": "N/A",
            "Rating": "N/A",
        }
        
        # Extract KPR
        kpr_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s+KPR", text, re.I)
        if kpr_match:
            metrics["KPR"] = kpr_match.group(1)
        
        # Extract DPR
        dpr_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s+DPR", text, re.I)
        if dpr_match:
            metrics["DPR"] = dpr_match.group(1)
        
        # Extract ADR
        adr_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s+ADR", text, re.I)
        if adr_match:
            metrics["ADR"] = adr_match.group(1)
        
        # Extract Rating 3.0
        rating_match = re.search(r"Rating\s+([0-9]+(?:\.[0-9]+)?)", text, re.I)
        if rating_match:
            metrics["Rating"] = rating_match.group(1)
        
        return metrics
    
    except Exception as e:
        print(f"Error extracting metrics: {e}")
        return {}


def extract_player_info(profile_html):
    """Extract player info from profile page."""
    if not profile_html:
        return {}
    
    try:
        soup = BeautifulSoup(profile_html, "html.parser")
        text = soup.get_text()
        
        info = {
            "team": "N/A",
            "country": "N/A",
            "role": "N/A",
        }
        
        # Extract team (look for team link)
        for a in soup.find_all("a", href=True):
            if re.search(r"^/team/\d+/", a["href"]):
                info["team"] = clean_text(a.get_text())
                break
        
        # Extract country (look for country indicator)
        country_match = re.search(r"Country:\s*([A-Za-z\s]+)", text, re.I)
        if country_match:
            info["country"] = country_match.group(1).strip()
        
        return info
    
    except Exception as e:
        print(f"Error extracting player info: {e}")
        return {}


def search_player_simple(player_name):
    """
    Simple wrapper that just returns id and name.
    Use this if you want the same interface as the old broken version.
    """
    result = search_player(player_name)
    if result:
        return {
            "id": result.get("id"),
            "name": result.get("name")
        }
    return None


# Main execution example
if __name__ == "__main__":
    # Test the search function
    test_players = ["spirit", "zywoo", "donk", "niko", "eraa"]
    
    for player in test_players:
        print(f"\nSearching for: {player}")
        result = search_player(player)
        
        if result:
            print(f"  Found: {result['name']} (ID: {result['id']})")
            
            # Optionally fetch profile
            profile = get_player_profile(result["id"], result["slug"])
            if profile:
                info = extract_player_info(profile)
                print(f"  Team: {info.get('team', 'N/A')}")
            
            # Optionally fetch stats
            stats = get_player_stats(result["id"], result["slug"])
            if stats:
                metrics = extract_player_metrics(stats)
                print(f"  KPR: {metrics.get('KPR', 'N/A')}")
        else:
            print(f"  Not found")
        
        time.sleep(1)
