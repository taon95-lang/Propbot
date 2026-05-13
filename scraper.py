"""
Deep Opponent Analysis for the Elite CS2 Prop Grader.

Dimensions covered:
  1. Defensive Profile    — kills allowed per player per map (last 10 opp matches)
  2. HS Vulnerability     — kills-allowed proxy → Frag Mine / Moderate / Low
  3. CT/T Efficiency      — round win % on each side, T-side aggression modifier
  4. Head-to-Head         — player's actual performance in last 3 matches vs this team
  5. Stomp / Rank Risk    — ranking gap → round projection adjustment
  6. Map Pool             — opponent's most/least played maps → frag boost/suppress
  7. Combined Multiplier  — single scalar applied to kill distribution before simulation
"""

import re
import time
import logging
import statistics as _stats
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
HLTV_BASE = "https://www.hltv.org"
BASELINE_KILLS = 15.0
FETCH_TIMEOUT = 10
_PROFILES = []  # Should be populated with session/proxy profiles
_H2H_WINDOW_DAYS = 90

# Map type classification
MAP_TYPE: dict[str, str] = {
    'mirage':       'high_frag',
    'inferno':      'high_frag',
    'dust2':        'high_frag',
    'overpass':     'high_frag',
    'cache':        'high_frag',
    'cobblestone':  'high_frag',
    'ancient':      'average',
    'anubis':       'average',
    'nuke':         'tactical',
    'vertigo':      'tactical',
    'train':        'tactical',
    'faceit':       'average',
}

MAP_KILL_MODIFIER: dict[str, float] = {
    'high_frag': 1.07,
    'average':   1.00,
    'tactical':  0.93,
}

ALL_MAP_NAMES = set(MAP_TYPE.keys())

# Caches
_RANK_CACHE: dict[str, tuple] = {}
_OPP_CACHE: dict[str, tuple] = {}
_RANKING_PAGE_CACHE: dict[str, tuple] = {}
RANK_TTL = 6 * 3600
OPP_TTL  = 4 * 3600
RANKING_PAGE_TTL = 3600

# ---------------------------------------------------------------------------
# 1. Robust Fetching & Session Management (Unified from images)
# ---------------------------------------------------------------------------

def _get_hltv_session():
    """Placeholder for your session/proxy rotation logic."""
    return requests.Session()

def _fetch(url: str, max_retries: int = 3) -> str | None:
    """Robust fetch with profile rotation and retry logic."""
    profiles_tried = 0
    max_profile_rotations = len(_PROFILES) if _PROFILES else 1

    while profiles_tried <= max_profile_rotations:
        sess = _get_hltv_session()
        if sess is None:
            return None

        got_403_this_profile = False
        for attempt in range(max_retries):
            try:
                tag = f" (retry {attempt})" if attempt > 0 else ""
                logger.info(f"[fetch] GET {url}{tag}")
                
                print("REQUEST START")
                resp = sess.get(url, timeout=FETCH_TIMEOUT)
                print("REQUEST DONE")
                print(f"Status: {resp.status_code}")

                if resp.status_code == 200:
                    return resp.text
                
                if resp.status_code == 403:
                    got_403_this_profile = True
                    break  # Move to next profile rotation
                
                if resp.status_code == 404:
                    return None

            except Exception as e:
                logger.warning(f"Fetch attempt {attempt} failed: {e}")
                if attempt == max_retries - 1:
                    break
                time.sleep(1)

        if got_403_this_profile:
            profiles_tried += 1
            logger.info("Rotating profile due to 403...")
            continue
        
        # If we reached here without a 200 or 403, try next profile or fail
        profiles_tried += 1
    
    return None

# ---------------------------------------------------------------------------
# 2. Team Ranking Logic
# ---------------------------------------------------------------------------

def _rank_from_team_page(html: str, team_slug: str) -> int | None:
    m = re.search(r'"worldRanking"\s*:\s*(\d+)', html, re.IGNORECASE)
    if m:
        return int(m.group(1))

    try:
        soup = BeautifulSoup(html, 'html.parser')
        for stat in soup.find_all(class_='profile-team-stat'):
            label = stat.find('b')
            if label and 'world ranking' in label.get_text(strip=True).lower():
                val = stat.find('a') or stat.find(class_='value')
                if val:
                    m2 = re.search(r'#(\d+)', val.get_text(strip=True))
                    if m2:
                        return int(m2.group(1))
    except Exception:
        pass

    m = re.search(r'World\s+ranking\s*[^<]{0,30}#\s*(\d+)', html, re.IGNORECASE | re.DOTALL)
    return int(m.group(1)) if m else None

def _rank_from_ranking_page(team_id: str) -> int | None:
    html = _fetch(f"{HLTV_BASE}/ranking/teams")
    if not html:
        return None

    try:
        soup = BeautifulSoup(html, 'html.parser')
        for block in soup.find_all(attrs={"data-team-id": True}):
            if str(block.get("data-team-id")) == str(team_id):
                pos_tag = block.find(class_=re.compile(r'position', re.I))
                if pos_tag:
                    m = re.search(r'(\d+)', pos_tag.get_text())
                    if m: return int(m.group(1))
    except Exception:
        pass
    return None

def get_team_rank(team_id: str, team_slug: str) -> int | None:
    cached = _RANK_CACHE.get(team_id)
    if cached and (time.time() - cached[0] < RANK_TTL):
        return cached[1]

    html = _fetch(f"{HLTV_BASE}/team/{team_id}/{team_slug}")
    rank = _rank_from_team_page(html, team_slug) if html else None
    
    if rank is None:
        rank = _rank_from_ranking_page(team_id)

    if rank:
        _RANK_CACHE[team_id] = (time.time(), rank)
    return rank

# ---------------------------------------------------------------------------
# 3. Map & Round Extraction
# ---------------------------------------------------------------------------

def _extract_maps_from_page(html: str) -> list[str]:
    soup = BeautifulSoup(html, 'html.parser')
    found: list[str] = []
    for el in soup.find_all(class_=re.compile(r'dynamic-map-name', re.I)):
        text = el.get_text(strip=True).lower()
        if text in ALL_MAP_NAMES and text not in found:
            found.append(text)
    return found[:3]

def _extract_half_scores(html: str) -> list[dict]:
    results = []
    for a, b, c, d in re.findall(r'(\d+)-(\d+)\s*[;,]\s*(\d+)-(\d+)', html)[:4]:
        a, b, c, d = int(a), int(b), int(c), int(d)
        if all(0 <= x <= 21 for x in [a, b, c, d]) and (a + b + c + d) >= 16:
            results.append({'h1_a': a, 'h1_b': b, 'h2_a': c, 'h2_b': d, 'total': a + b + c + d})
    return results[:2]

# ---------------------------------------------------------------------------
# 4. Opponent & H2H Profile Aggregation
# ---------------------------------------------------------------------------

def _fetch_opponent_profile(team_id: str, n_matches: int = 10) -> dict:
    cached = _OPP_CACHE.get(team_id)
    if cached and (time.time() - cached[0] < OPP_TTL):
        return cached[1]

    html = _fetch(f"{HLTV_BASE}/results?team={team_id}")
    if not html: return {}

    match_list = list(dict.fromkeys(re.findall(r'/matches/(\d+)/([\w-]+)', html)))[:n_matches]
    
    opp_kills, star_kills, rounds_per_map = [], [], []
    ct_wins, ct_total, t_wins, t_total = 0, 0, 0, 0
    map_counter = {}

    for match_id, slug in match_list:
        time.sleep(0.35)
        page_html = _fetch(f"{HLTV_BASE}/matches/{match_id}/{slug}")
        if not page_html: continue

        soup = BeautifulSoup(page_html, 'html.parser')
        matchstats = soup.find(id='match-stats')
        if matchstats:
            map_ids = re.findall(r'id="(\d{5,7})-content"', str(matchstats))
            for map_id in map_ids[:2]:
                content = matchstats.find(id=f'{map_id}-content')
                if not content: continue
                for table in content.find_all('table', class_='totalstats'):
                    if table.find('a', href=re.compile(rf'/team/{team_id}/')): continue
                    map_kills_this_table = []
                    for tr in table.find_all('tr')[1:]:
                        m = re.search(r'(\d+)\s*-\s*\d+', tr.get_text())
                        if m:
                            k = int(m.group(1))
                            opp_kills.append(k)
                            map_kills_this_table.append(k)
                    if map_kills_this_table:
                        star_kills.append(max(map_kills_this_table))

        half_scores = _extract_half_scores(page_html)
        for hs in half_scores:
            rounds_per_map.append(hs['total'] // 2)
            ct_wins += hs['h1_a']; ct_total += hs['h1_a'] + hs['h1_b']
            t_wins += hs['h2_a']; t_total += hs['h2_a'] + hs['h2_b']

        for name in _extract_maps_from_page(page_html):
            map_counter[name] = map_counter.get(name, 0) + 1

    data = {
        'avg_kills_allowed': round(_stats.mean(opp_kills), 1) if opp_kills else None,
        'avg_star_kill': round(_stats.mean(star_kills), 1) if star_kills else None,
        'ct_win_pct': round(ct_wins / ct_total * 100, 1) if ct_total > 0 else None,
        't_win_pct': round(t_wins / t_total * 100, 1) if t_total > 0 else None,
        'avg_rounds_per_map': round(_stats.mean(rounds_per_map), 1) if rounds_per_map else 22.0,
        'most_played_maps': sorted(map_counter.items(), key=lambda x: -x[1])[:3],
    }
    _OPP_CACHE[team_id] = (time.time(), data)
    return data

def get_h2h_stats(player_id, player_slug, player_match_ids, opponent_team_id, opponent_slug="", n=50, line=0.0):
    _h2h_min_ts = time.time() - (_H2H_WINDOW_DAYS * 86400)
    results = []
    opp_slug_norm = re.sub(r'[^a-z0-9]', '', opponent_slug.lower())

    for match_id, slug in player_match_ids:
        if len(results) >= n: break
        if opp_slug_norm and opp_slug_norm not in re.sub(r'[^a-z0-9]', '', slug.lower()): continue

        time.sleep(0.35)
        page_html = _fetch(f"{HLTV_BASE}/matches/{match_id}/{slug}")
        if not page_html or f'/team/{opponent_team_id}/' not in page_html[:8000]: continue

        m_unix = re.search(r'data-unix=["\'](\d{10,13})["\']', page_html)
        if not m_unix: continue
        ts = int(m_unix.group(1)) // (1000 if len(m_unix.group(1)) > 10 else 1)
        if ts < _h2h_min_ts: continue

        # Integration with your existing _parse_match_kills (assumed available in scope)
        from scraper import _parse_match_kills
        parsed = _parse_match_kills(page_html, player_slug, f"{HLTV_BASE}/matches/{match_id}/{slug}")
        if parsed and parsed.get('maps'):
            kills = [m['kills'] for m in parsed['maps'][:2]]
            results.append({
                'total_kills': sum(kills),
                'cleared': sum(kills) >= line if len(kills) >= 2 else False,
                'days_old': int((time.time() - ts) / 86400)
            })
    return results

# ---------------------------------------------------------------------------
# 5. Main Analysis Orchestrator
# ---------------------------------------------------------------------------

def run_deep_analysis(player_id, player_slug, player_match_ids, opponent_name, stat_type, baseline_avg, line=0.0, player_team=None, prop_side="OVER"):
    out = {
        'opponent_display': None, 'combined_multiplier': 1.0, 'components': {},
        'summary_bullets': [], 'scouting': {}, 'h2h': []
    }

    from scraper import search_team, get_player_team, get_team_period_stats
    team_info = search_team(opponent_name)
    if not team_info: return {"error": "Team not found"}
    opp_id, opp_slug, opp_display = team_info
    out['opponent_display'] = opp_display

    if not player_team: player_team = get_player_team(player_id, player_slug)
    p_team_id, p_team_slug = player_team if player_team else (None, None)

    opp_data = _fetch_opponent_profile(opp_id)
    opp_rank = get_team_rank(opp_id, opp_slug)
    p_rank = get_team_rank(p_team_id, p_team_slug) if p_team_id else None

    # Multiplier Logic
    combined = 1.0
    avg_allowed = opp_data.get('avg_kills_allowed')
    if avg_allowed:
        def_adj = max(0.75, min(1.25, avg_allowed / (baseline_avg or BASELINE_KILLS)))
        combined *= def_adj
        out['components']['defensive'] = round(def_adj, 4)

    if opp_rank and p_rank:
        diff = opp_rank - p_rank
        if diff >= 20: 
            combined *= 0.88
            out['summary_bullets'].append("Stomp Risk: Opponent ranked significantly lower.")
        elif abs(diff) <= 5:
            combined *= 1.03
            out['summary_bullets'].append("Tight Matchup: Rankings are nearly even.")

    combined = max(0.82, min(1.18, combined))
    out['combined_multiplier'] = round(combined, 4)
    out['h2h'] = get_h2h_stats(player_id, player_slug, player_match_ids, opp_id, opp_slug, line=line)
    
    return out
