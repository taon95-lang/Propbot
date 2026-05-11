import re, random, time, logging, os
from datetime import date, timedelta
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as sess_req
    CFFI_OK = True
except ImportError:
    CFFI_OK = False

logger = logging.getLogger(__name__)
HLTV_BASE = "https://www.hltv.org"
PROFILES = ["chrome116", "safari17_0", "chrome107", "chrome110", "chrome99"]

class HLTVState:
    session = None
    profile_idx = 0
    warmed = False
    stats_blocked_until = 0
    mapstats_blocked_until = 0

state = HLTVState()

def _rotate():
    state.profile_idx = (state.profile_idx + 1) % len(PROFILES)
    state.session = sess_req.Session(impersonate=PROFILES[state.profile_idx])
    state.warmed = False
    return state.session

def _fetch(url, referer=None, use_proxy=False):
    if not CFFI_OK: return None
    if "/stats/" in url:
        now = time.time()
        if "mapstatsid" in url and now < state.mapstats_blocked_until: return None
        if "mapstatsid" not in url and now < state.stats_blocked_until: return None

    if not state.session: _rotate()
    
    for _ in range(len(PROFILES)):
        try:
            if not state.warmed:
                state.session.get(HLTV_BASE + "/", timeout=10)
                state.warmed = True
            
            headers = {"Referer": referer or HLTV_BASE + "/"}
            r = state.session.get(url, timeout=20, headers=headers)
            
            if r.status_code == 200 and "Just a moment" not in r.text:
                return r.text
            if r.status_code == 403:
                _rotate()
                continue
        except:
            _rotate()
    
    # Optional: ScraperAPI Fallback if environment key exists
    if os.getenv("SCRAPERAPI_KEY"):
        try:
            params = {"api_key": os.getenv("SCRAPERAPI_KEY"), "url": url}
            import requests
            r = requests.get("https://api.scraperapi.com/", params=params, timeout=30)
            return r.text if r.status_code == 200 else None
        except: return None
    return None

def search_player(name, team_hint=None):
    html = _fetch(f"{HLTV_BASE}/search?query={name}")
    if not html: return None
    matches = re.findall(r'/player/(\d+)/([\w-]+)', html)
    if not matches: return None
    
    # Priority: exact name match or first result
    best = matches[0]
    for pid, slug in matches:
        if name.lower().replace(" ", "") in slug.lower():
            best = (pid, slug)
            break
    return best[0], best[1], best[1].replace("-", " ").title()

def parse_map_stats(html, player_slug):
    soup = BeautifulSoup(html, 'html.parser')
    slug_norm = re.sub(r'[^a-z0-9]', '', player_slug.lower())
    
    # Find player row across any stats table
    for tr in soup.find_all('tr'):
        row_text = tr.get_text().lower()
        if slug_norm not in re.sub(r'[^a-z0-9]', '', row_text): continue
        
        cells = [c.get_text(strip=True) for c in tr.find_all('td')]
        stats = {"kills": None, "hs": None, "deaths": None, "rating": None}
        
        for c in cells:
            # Pattern: 21 (11) for Kills (HS)
            khs = re.search(r'(\d+)\s*\((\d+)\)', c)
            if khs:
                stats["kills"], stats["hs"] = int(khs.group(1)), int(khs.group(2))
            # Pattern: 15-14 for K-D
            kd = re.search(r'^(\d+)\s*[-–]\s*(\d+)$', c)
            if kd and not stats["kills"]:
                stats["kills"], stats["deaths"] = int(kd.group(1)), int(kd.group(2))
            # Pattern: 1.25 for Rating
            rat = re.match(r'^(\d\.\d{2})$', c)
            if rat: stats["rating"] = float(rat.group(1))
            
        return stats
    return None

def get_player_data(name, team_hint=None):
    pid, slug, display = search_player(name)
    # Get recent match results
    res_html = _fetch(f"{HLTV_BASE}/results?player={pid}")
    mids = re.findall(r'/matches/(\d{7,})/([\w-]+)', res_html or "")[:15]
    
    all_maps = []
    for mid, mslug in list(dict.fromkeys(mids))[:10]: # Last 10 BO3s
        m_html = _fetch(f"{HLTV_BASE}/matches/{mid}/{mslug}")
        if not m_html or "best of 3" not in m_html.lower(): continue
        
        # Extract mapstat IDs to get precise HS% data
        ms_ids = re.findall(r'/stats/matches/mapstatsid/(\d+)/', m_html)[:2] # Maps 1 & 2
        for msid in ms_ids:
            ms_html = _fetch(f"{HLTV_BASE}/stats/matches/mapstatsid/{msid}/proxy", referer=f"{HLTV_BASE}/matches/{mid}/{mslug}")
            if ms_html:
                m_data = parse_map_stats(ms_html, slug)
                if m_data:
                    m_data.update({"match_id": mid, "map_id": msid})
                    all_maps.append(m_data)
        if len(all_maps) >= 20: break

    valid_kills = [m['kills'] for m in all_maps if m['kills'] is not None]
    if not valid_kills: return None

    return {
        "player": display,
        "avg": round(sum(valid_kills)/len(valid_kills), 2),
        "sample": len(valid_kills),
        "maps": all_maps
    }

# Logic for Team Defensive Stats
def get_team_conceded(team_name):
    t_info = _fetch(f"{HLTV_BASE}/search?query={team_name}")
    tid = re.search(r'/team/(\d+)/', t_info or "")
    if not tid: return 1.0
    
    # Simplified: Higher rank/winrate team = harder to kill (lower adjustment)
    # In a full build, you'd scrape the last 5 match opponents here.
    return 0.95 # Default "Tough" placeholder for condensed code
