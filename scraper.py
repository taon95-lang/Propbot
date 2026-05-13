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
from bs4 import BeautifulSoup

from scraper import (
    _fetch, HLTV_BASE,
    search_team,
    get_player_team,
    get_team_period_stats,
    _parse_match_kills,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Map type classification
# ---------------------------------------------------------------------------

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

# CS2 BO3 baseline: avg kills per player per Map 1+2 only (not including Map 3).
BASELINE_KILLS = 15.0

# ---------------------------------------------------------------------------
# In-memory caches
# ---------------------------------------------------------------------------

_RANK_CACHE: dict[str, tuple] = {}    # team_id → (timestamp, rank | None)
_OPP_CACHE: dict[str, tuple] = {}     # team_id → (timestamp, data_dict)
_RANKING_PAGE_CACHE: dict[str, tuple] = {}  # "page" → (timestamp, html)

RANK_TTL = 6 * 3600
OPP_TTL  = 4 * 3600
RANKING_PAGE_TTL = 3600

# ---------------------------------------------------------------------------
# 1. Team ranking
# ---------------------------------------------------------------------------

def _rank_from_team_page(html: str, team_slug: str) -> int | None:
    """Parse a team's world ranking from their HLTV profile page HTML."""
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
    if m:
        return int(m.group(1))

    m = re.search(r'class=["\'][^"\']*teamRanking[^"\']*["\'][^>]*>(?:[^<]{0,20})?#\s*(\d+)', html, re.IGNORECASE)
    if m:
        return int(m.group(1))

    return None


def _fetch_ranking_page() -> str | None:
    """Fetch (and cache for 1 hour) the HLTV world team ranking page HTML."""
    cached = _RANKING_PAGE_CACHE.get("page")
    if cached:
        ts, html = cached
        if time.time() - ts < RANKING_PAGE_TTL:
            return html
    url = f"{HLTV_BASE}/ranking/teams"
    html = _fetch(url)
    if html:
        _RANKING_PAGE_CACHE["page"] = (time.time(), html)
    return html


def _rank_from_ranking_page(team_id: str) -> int | None:
    """Find a team's world ranking from the HLTV ranking page."""
    html = _fetch_ranking_page()
    if not html:
        return None

    try:
        soup = BeautifulSoup(html, 'html.parser')

        # Primary: data-team-id attribute
        for block in soup.find_all(attrs={"data-team-id": True}):
            if str(block.get("data-team-id")) == str(team_id):
                pos_tag = block.find(class_=re.compile(r'position', re.I))
                if pos_tag:
                    m = re.search(r'(\d+)', pos_tag.get_text())
                    if m:
                        return int(m.group(1))
                m = re.search(r'#\s*(\d+)', block.get_text())
                if m:
                    return int(m.group(1))

        # Secondary: team_id link check
        for block in soup.find_all(class_=re.compile(r'ranked-team', re.I)):
            if f'/team/{team_id}/' in str(block):
                pos_tag = block.find(class_=re.compile(r'position', re.I))
                if pos_tag:
                    m = re.search(r'(\d+)', pos_tag.get_text())
                    if m:
                        return int(m.group(1))
    except Exception as e:
        logger.warning(f"[rank] ranking page parse error: {e}")

    m = re.search(
        rf'data-team-id=["\']?{re.escape(str(team_id))}["\']?[^>]*>(.*?)</div>',
        html, re.IGNORECASE | re.DOTALL
    )
    if m:
        m2 = re.search(r'#\s*(\d+)', m.group(1))
        if m2:
            return int(m2.group(1))

    return None


def get_team_rank(team_id: str, team_slug: str) -> int | None:
    cached = _RANK_CACHE.get(team_id)
    if cached:
        ts, rank = cached
        if time.time() - ts < RANK_TTL:
            return rank

    rank = None
    url = f"{HLTV_BASE}/team/{team_id}/{team_slug}"
    html = _fetch(url)
    if html:
        rank = _rank_from_team_page(html, team_slug)

    if rank is None:
        logger.info(f"[rank] Team page gave no rank for {team_slug} — trying ranking page")
        rank = _rank_from_ranking_page(team_id)

    if rank is not None:
        _RANK_CACHE[team_id] = (time.time(), rank)
        logger.info(f"[rank] {team_slug} → #{rank}")
    else:
        logger.warning(f"[rank] could not determine rank for {team_slug} (team_id={team_id})")
    return rank


_SLUG_RANK_CACHE: dict[str, tuple] = {}


def rank_by_team_slug(team_slug: str) -> int | None:
    """Look up rank using slug only (no team_id required)."""
    slug_norm = re.sub(r'[^a-z0-9]', '', team_slug.lower())
    if not slug_norm:
        return None

    cached = _SLUG_RANK_CACHE.get(slug_norm)
    if cached:
        ts, rank = cached
        if time.time() - ts < RANK_TTL:
            return rank

    html = _fetch_ranking_page()
    if not html:
        return None

    rank = None
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for block in soup.find_all(class_=re.compile(r'ranked-team', re.I)):
            block_str = str(block).lower()
            if slug_norm not in re.sub(r'[^a-z0-9]', '', block_str):
                continue
            for a in block.find_all('a', href=re.compile(r'/team/\d+/', re.I)):
                href_slug = a.get('href', '').rstrip('/').split('/')[-1]
                href_norm = re.sub(r'[^a-z0-9]', '', href_slug.lower())
                if href_norm == slug_norm or slug_norm in href_norm or href_norm in slug_norm:
                    pos_tag = block.find(class_=re.compile(r'position', re.I))
                    if pos_tag:
                        m = re.search(r'(\d+)', pos_tag.get_text())
                        if m:
                            rank = int(m.group(1))
                            break
            if rank is not None:
                break
    except Exception as e:
        logger.warning(f"[rank] rank_by_team_slug({team_slug!r}) error: {e}")

    _SLUG_RANK_CACHE[slug_norm] = (time.time(), rank)
    return rank

# ---------------------------------------------------------------------------
# 2. Map & Score extraction
# ---------------------------------------------------------------------------

def _extract_maps_from_page(html: str) -> list[str]:
    """Return lowercase map names found in the match page (max 3)."""
    soup = BeautifulSoup(html, 'html.parser')
    found: list[str] = []

    for el in soup.find_all(class_=re.compile(r'dynamic-map-name', re.I)):
        text = el.get_text(strip=True).lower()
        if text in ALL_MAP_NAMES and text not in found:
            found.append(text)

    if not found:
        for name in re.findall(
            r'\b(mirage|inferno|nuke|dust2|vertigo|ancient|anubis|overpass|train|cache|cobblestone)\b',
            html, re.IGNORECASE
        ):
            name = name.lower()
            if name not in found:
                found.append(name)

    return found[:3]


def _extract_half_scores(html: str) -> list[dict]:
    """Pull half-by-half round scores (e.g. 8-7; 7-5)."""
    results = []
    for a, b, c, d in re.findall(r'(\d+)-(\d+)\s*[;,]\s*(\d+)-(\d+)', html)[:4]:
        a, b, c, d = int(a), int(b), int(c), int(d)
        if all(0 <= x <= 21 for x in [a, b, c, d]) and (a + b + c + d) >= 16:
            results.append({'h1_a': a, 'h1_b': b, 'h2_a': c, 'h2_b': d,
                            'total': a + b + c + d})
    return results[:2]

# ---------------------------------------------------------------------------
# 3. Opponent deep profile
# ---------------------------------------------------------------------------

def _fetch_opponent_profile(team_id: str, n_matches: int = 10) -> dict:
    """Fetch opponent match pages and aggregate the full defensive profile."""
    cached = _OPP_CACHE.get(team_id)
    if cached:
        ts, data = cached
        if time.time() - ts < OPP_TTL:
            return data

    results_url = f"{HLTV_BASE}/results?team={team_id}"
    html = _fetch(results_url)
    if not html:
        return {}

    match_pairs = re.findall(r'/matches/(\d+)/([\w-]+)', html)
    seen: dict[str, str] = {}
    for mid, slug in match_pairs:
        if mid not in seen and len(mid) >= 6:
            seen[mid] = slug
    match_list = list(seen.items())[:n_matches]
    if not match_list:
        return {}

    opp_kills: list[int] = []
    star_kills: list[int] = []
    ct_wins, ct_total = 0, 0
    t_wins, t_total   = 0, 0
    map_counter: dict[str, int] = {}
    rounds_per_map: list[int] = []

    for match_id, slug in match_list:
        time.sleep(0.35)
        page_html = _fetch(f"{HLTV_BASE}/matches/{match_id}/{slug}")
        if not page_html:
            continue

        soup = BeautifulSoup(page_html, 'html.parser')
        matchstats = soup.find(id='match-stats')

        if matchstats:
            raw = str(matchstats)
            map_ids = re.findall(r'id="(\d{5,7})-content"', raw)
            for map_id in map_ids[:2]:
                content = matchstats.find(id=f'{map_id}-content')
                if not content:
                    continue
                tables = content.find_all('table', class_='totalstats')
                for table in tables:
                    if table.find('a', href=re.compile(rf'/team/{team_id}/')):
                        continue
                    map_kills_this_table: list[int] = []
                    for tr in table.find_all('tr')[1:]:
                        m = re.search(r'(\d+)\s*-\s*\d+', tr.get_text())
                        if m:
                            k = int(m.group(1))
                            if 3 <= k <= 60:
                                opp_kills.append(k)
                                map_kills_this_table.append(k)
                    if map_kills_this_table:
                        star_kills.append(max(map_kills_this_table))

        half_scores = _extract_half_scores(page_html)
        for hs in half_scores:
            total = hs['total']
            if total >= 16:
                rounds_per_map.append(total // 2)
            ct_wins  += hs['h1_a']
            ct_total += hs['h1_a'] + hs['h1_b']
            t_wins   += hs['h2_a']
            t_total  += hs['h2_a'] + hs['h2_b']

        for name in _extract_maps_from_page(page_html):
            map_counter[name] = map_counter.get(name, 0) + 1

    avg_allowed   = round(_stats.mean(opp_kills),  1) if len(opp_kills)  >= 5 else None
    avg_star_kill = round(_stats.mean(star_kills), 1) if len(star_kills) >= 3 else None
    ct_pct = round(ct_wins / ct_total * 100, 1) if ct_total > 0 else None
    t_pct  = round(t_wins  / t_total  * 100, 1) if t_total  > 0 else None
    avg_rounds = round(_stats.mean(rounds_per_map), 1) if rounds_per_map else 22.0

    sorted_maps = sorted(map_counter.items(), key=lambda x: -x[1])
    most_played  = [m for m, _ in sorted_maps[:3]]
    least_played = [m for m, _ in sorted_maps[-2:]] if len(sorted_maps) >= 4 else []

    data = {
        'avg_kills_allowed': avg_allowed,
        'avg_star_kill':     avg_star_kill,
        'star_suppression':  (avg_star_kill is not None and avg_star_kill < 15.0),
        'sample_kills': len(opp_kills),
        'ct_win_pct': ct_pct,
        't_win_pct':  t_pct,
        'avg_rounds_per_map': avg_rounds,
        'most_played_maps':   most_played,
        'least_played_maps':  least_played,
        'map_counter':        map_counter,
    }
    _OPP_CACHE[team_id] = (time.time(), data)
    return data

# ---------------------------------------------------------------------------
# 4. Head-to-Head & Adjustment logic
# ---------------------------------------------------------------------------

_H2H_WINDOW_DAYS = 90

def h2h_adjustment(h2h_matches, recent_model, prop_side):
    """Context layer for H2H — never overrides recent form."""
    valid_h2h = []
    for match in h2h_matches:
        same_core = match.get("same_core_players", 0) >= 3
        recent = match.get("days_old", 999) <= 90
        no_standin = not match.get("standin", False)
        if same_core and recent and no_standin:
            valid_h2h.append(match)

    if not valid_h2h:
        return {
            "h2h_valid": False,
            "h2h_weight": 0,
            "h2h_note": "H2H ignored — no recent same-core sample",
            "decision_modifier": "NONE"
        }

    h2h_weight = 0.25
    stomp_games = sum(1 for m in valid_h2h if m.get("stomp", False))
    overtime_games = sum(1 for m in valid_h2h if m.get("overtime", False))
    flags = []

    if stomp_games >= 1:
        flags.append("H2H stomp risk")
        if prop_side == "OVER":
            recent_model["confidence"] -= 5
            recent_model["grade_cap"] = min(recent_model.get("grade_cap", "A"), "B")

    if overtime_games >= 1:
        flags.append("H2H OT inflation")
        recent_model["confidence"] -= 3

    h2h_avg_rounds = sum(m["rounds_m1_m2"] for m in valid_h2h) / len(valid_h2h)
    if h2h_avg_rounds <= 40:
        flags.append("H2H confirms short-map risk")
        if prop_side == "OVER":
            recent_model["confidence"] -= 5
        else:
            recent_model["confidence"] += 3
    elif h2h_avg_rounds >= 48:
        flags.append("H2H shows long-match environment")
        if prop_side == "OVER":
            recent_model["confidence"] += 3

    return {
        "h2h_valid": True,
        "h2h_weight": h2h_weight,
        "h2h_sample": len(valid_h2h),
        "h2h_avg_rounds": round(h2h_avg_rounds, 1),
        "h2h_flags": flags,
        "recent_model": recent_model,
        "rule": "H2H is capped at 25% and cannot override recent form"
    }


def get_h2h_stats(
    player_id: str,
    player_slug: str,
    player_match_ids: list[tuple[str, str]],
    opponent_team_id: str,
    opponent_slug: str = "",
    n: int = 50,
    line: float = 0.0,
) -> list[dict]:
    """Scan recent match IDs for matches involving the target opponent."""
    _h2h_min_ts = time.time() - (_H2H_WINDOW_DAYS * 86400)
    results: list[dict] = []
    opp_slug_norm = re.sub(r'[^a-z0-9]', '', opponent_slug.lower()) if opponent_slug else ""

    for match_id, slug in player_match_ids:
        if len(results) >= n:
            break

        slug_norm = re.sub(r'[^a-z0-9]', '', slug.lower())
        if opp_slug_norm and opp_slug_norm not in slug_norm:
            continue

        time.sleep(0.35)
        _match_url = f"{HLTV_BASE}/matches/{match_id}/{slug}"
        page_html = _fetch(_match_url)
        if not page_html:
            continue

        if f'/team/{opponent_team_id}/' not in page_html[:8000]:
            continue

        _unix_m = re.search(r'data-unix=["\'](\d{10,13})["\']', page_html)
        _ts: int | None = None
        if _unix_m:
            _ts = int(_unix_m.group(1))
            if _ts > 9_999_999_999:
                _ts //= 1000
            if _ts < _h2h_min_ts:
                continue
        else:
            continue

        parsed = _parse_match_kills(page_html, player_slug, _match_url)
        if not parsed or not parsed.get('maps'):
            continue

        kills_by_map = [m['kills'] for m in parsed['maps'][:2]]
        if not kills_by_map:
            continue

        maps_found   = len(kills_by_map)
        total_kills  = sum(kills_by_map)
        cleared = (maps_found >= 2 and line > 0 and total_kills >= line)
        _days_old = int((time.time() - _ts) / 86400) if _ts else 999

        results.append({
            'match_id':   match_id,
            'kills_by_map': kills_by_map,
            'total_kills': total_kills,
            'avg_kills':  round(_stats.mean(kills_by_map), 1),
            'maps_found': maps_found,
            'cleared':    cleared,
            'partial':    maps_found < 2,
            'match_ts':   _ts,
            'days_old':   _days_old,
        })

    results.sort(key=lambda r: r.get('match_ts') or 0, reverse=True)
    return results

# ---------------------------------------------------------------------------
# 5. Main Orchestrator
# ---------------------------------------------------------------------------

def run_deep_analysis(
    player_id: str,
    player_slug: str,
    player_match_ids: list[tuple[str, str]],
    opponent_name: str,
    stat_type: str,
    baseline_avg: float,
    line: float = 0.0,
    player_team: tuple[str, str] | None = None,
    prop_side: str = "OVER",
) -> dict:
    """Orchestrate all analysis dimensions to produce the scouting profile."""
    out: dict = {
        'opponent_display':       None,
        'combined_multiplier':    1.0,
        'components':             {},
        'defensive_profile':      {},
        'rank_info':              {},
        'map_pool':               {},
        'h2h':                    [],
        'h2h_label':              'No H2H data',
        'hs_vulnerability':       {},
        'scouting':               {},
        'matchup_favorite_bonus': False,
        'summary_bullets':        [],
        'error':                  None,
    }

    team_info = search_team(opponent_name)
    if not team_info:
        out['error'] = f"Team '{opponent_name}' not found on HLTV"
        return out

    opp_id, opp_slug, opp_display = team_info
    out['opponent_display'] = opp_display

    if player_team is None:
        player_team = get_player_team(player_id, player_slug)
    player_team_id   = player_team[0] if player_team else None
    player_team_slug = player_team[1] if player_team else None

    opp_data = _fetch_opponent_profile(opp_id, n_matches=10)

    team_period: dict | None = None
    try:
        team_period = get_team_period_stats(opp_id, opp_slug, days=90)
    except Exception:
        pass
    out['team_period_stats'] = team_period

    opp_rank    = get_team_rank(opp_id, opp_slug)
    player_rank = get_team_rank(player_team_id, player_team_slug) if player_team_id and player_team_slug else None

    h2h = get_h2h_stats(
        player_id, player_slug, player_match_ids, opp_id,
        opponent_slug=opp_slug, n=50, line=line,
    )
    out['h2h'] = h2h

    _h2h_recent_model: dict = {"confidence": 0, "grade_cap": "A"}
    out['h2h_adjustment'] = h2h_adjustment(h2h, _h2h_recent_model, prop_side)

    # ════════════════════════════════════════════════════════════════════════
    # Compute multipliers
    # ════════════════════════════════════════════════════════════════════════
    components: dict[str, float] = {}
    bullets:    list[str]        = []
    combined = 1.0

    # ── [A] Defensive kills allowed ──────────────────────────────────────────
    avg_allowed = opp_data.get('avg_kills_allowed')

    if avg_allowed is None and team_period:
        _tp_kpr = team_period.get("kpr")
        if _tp_kpr and 0.10 <= _tp_kpr <= 2.0:
            _est = BASELINE_KILLS * (1.0 - (_tp_kpr - 0.65) * 0.50)
            avg_allowed = round(max(12.0, min(22.0, _est)), 1)

    if avg_allowed:
        _def_baseline = baseline_avg if (baseline_avg and baseline_avg > 5) else BASELINE_KILLS
        def_adj = avg_allowed / _def_baseline
        def_adj = max(0.75, min(1.25, def_adj))
        components['defensive'] = round(def_adj, 4)
        combined *= def_adj

        def_pct = round((def_adj - 1) * 100, 1)
        sign = '+' if def_pct >= 0 else ''
        _tough_thresh = _def_baseline * 0.85
        _soft_thresh  = _def_baseline * 1.10
        if avg_allowed < _tough_thresh:
            def_label = '🛡️ Tough Defense'
            bullets.append(f"Tough defense — only {avg_allowed} kills/player/map allowed ({sign}{def_pct}%)")
        elif avg_allowed > _soft_thresh:
            def_label = '💨 Soft Defense'
            bullets.append(f"Soft defense — {avg_allowed} kills/player/map allowed ({sign}{def_pct}%)")
        else:
            def_label = '⚖️ Average Defense'
    else:
        def_label = '❓ No Data'

    out['defensive_profile'] = {
        'avg_kills_allowed': avg_allowed,
        'label':      def_label,
        'ct_win_pct': opp_data.get('ct_win_pct'),
        't_win_pct':  opp_data.get('t_win_pct'),
        'avg_rounds': opp_data.get('avg_rounds_per_map', 22.0),
        'sample':     opp_data.get('sample_kills', 0),
    }

    # ── [B] CT/T efficiency modifier ─────────────────────────────────────────
    t_pct = opp_data.get('t_win_pct')
    if t_pct is not None:
        t_adj = 1.0
        if t_pct >= 55:
            t_adj = 1.05
            bullets.append(f"Aggressive T-side ({t_pct}% T-side win rate) → entry openings ↑")
        elif t_pct <= 40:
            t_adj = 0.97
            bullets.append(f"Passive T-side ({t_pct}% T-side win rate) → fewer opening duels")
        if t_adj != 1.0:
            components['t_side'] = round(t_adj, 4)
            combined *= t_adj

    # ── [C] Ranking / stomp risk ─────────────────────────────────────────────
    rank_adj  = 1.0
    stomp     = False
    rank_label = 'Unknown'

    if opp_rank and player_rank:
        diff = opp_rank - player_rank
        rank_label = f"#{player_rank} vs #{opp_rank}"
        if diff >= 20:
            stomp  = True
            rank_adj = 0.88
            bullets.append(f"Stomp risk: #{player_rank} vs #{opp_rank} — fewer projected rounds (↓12%)")
        elif diff <= -20:
            rank_adj = 1.08
            bullets.append(f"Top-calibre matchup: #{player_rank} vs #{opp_rank} — more rounds projected (↑8%)")
        elif abs(diff) <= 5:
            rank_adj = 1.03
            bullets.append(f"Even matchup (#{player_rank} vs #{opp_rank}) — full rounds expected (↑3%)")
    
    combined *= rank_adj
    out['rank_info'] = {
        'player_rank': player_rank, 'opp_rank': opp_rank,
        'label': rank_label, 'stomp_risk': stomp,
        'rank_gap': abs(opp_rank - player_rank) if (opp_rank and player_rank) else None
    }

    # ── [D] Map pool ─────────────────────────────────────────────────────────
    most_played = opp_data.get('most_played_maps', [])
    if most_played:
        types = [MAP_TYPE.get(m, 'average') for m in most_played[:2]]
        modifiers = [MAP_KILL_MODIFIER[t] for t in types]
        map_adj = round(sum(modifiers) / len(modifiers), 4)
        if map_adj != 1.0:
            components['map_pool'] = map_adj
            combined *= map_adj
            bullets.append(f"Map pool ({', '.join(most_played[:2]).title()}) modifier applied")

    # ── [E] H2H performance ───────────────────────────────────────────────────
    if h2h and baseline_avg > 0:
        h2h_avg   = _stats.mean([m['avg_kills'] for m in h2h])
        h2h_ratio = h2h_avg / baseline_avg
        h2h_adj   = max(0.90, min(1.10, h2h_ratio))
        if h2h_adj != 1.0:
            components['h2h'] = round(h2h_adj, 4)
            combined *= h2h_adj
            bullets.append(f"H2H history adjustment ({round(h2h_avg,1)} avg kills)")

    # ── [F] Role Suppression ─────────────────────────────────────────────────
    avg_star_kill = opp_data.get('avg_star_kill')
    star_clamp = opp_data.get('star_suppression', False)
    clamp_active = False

    if avg_star_kill is not None and star_clamp:
        clamp_active = True
        clamp_factor = max(0.80, round((baseline_avg - 1.5) / baseline_avg, 4)) if baseline_avg > 1.5 else 0.88
        components['star_clamp'] = clamp_factor
        combined *= clamp_factor
        bullets.append(f"Opponent clamps star players — avg top kill {avg_star_kill}/map")

    # ── [G] HS Vulnerability ─────────────────────────────────────────────────
    hs_adj = 1.0
    hs_rating = '⚖️ Average'
    if avg_allowed is not None:
        if avg_allowed >= 21: hs_rating = '💀 High Vulnerability'
        elif avg_allowed <= 15: hs_rating = '🛡️ Low Vulnerability'

        if stat_type.lower() == 'hs':
            if avg_allowed >= 21: hs_adj = 1.12
            elif avg_allowed <= 15: hs_adj = 0.92
            if hs_adj != 1.0:
                components['hs_vulnerability'] = hs_adj
                combined *= hs_adj

    # ── [H] Matchup Favorite ─────────────────────────────────────────────────
    h2h_cleared = sum(1 for rec in h2h[:3] if rec.get('cleared') and not rec.get('partial'))
    h2h_of_n = sum(1 for rec in h2h[:3] if not rec.get('partial'))
    matchup_fav = (h2h_of_n >= 2 and h2h_cleared >= 2)
    out['matchup_favorite_bonus'] = matchup_fav

    # ── [I] Economy Impact ───────────────────────────────────────────────────
    ct_pct_val = opp_data.get('ct_win_pct')
    economy_prob_delta = 0.0
    if ct_pct_val:
        if ct_pct_val < 38: economy_prob_delta = +5.0
        elif ct_pct_val > 58: economy_prob_delta = -5.0

    out['scouting'] = {
        'hs_vulnerability': {'rating': hs_rating},
        'role_suppression': {'avg_star_kill': avg_star_kill, 'clamp_active': clamp_active},
        'h2h_line': {'matches_cleared': h2h_cleared, 'of_n': h2h_of_n, 'matchup_favorite': matchup_fav},
        'economy_impact': {'prob_delta': economy_prob_delta, 'ct_win_pct': ct_pct_val},
    }

    combined = max(0.82, min(1.18, combined))
    out['combined_multiplier'] = round(combined, 4)
    out['components'] = components
    out['summary_bullets'] = bullets

    return out
