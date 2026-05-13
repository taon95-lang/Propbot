"""
HLTV scraper — uses curl_cffi Chrome impersonation against accessible HLTV endpoints.

Discovered accessible paths (no Cloudflare block):
  /search?query={name}          → player/team search (get IDs)
  /player/{id}/{slug}           → player profile (get team, overview)
  /results?player={id}          → player's recent results (get match IDs)
  /results?team={id}            → team's recent results (get match IDs)
  /matches/{id}/{slug}          → match detail page (per-map kill stats)
  /stats/matches/mapstatsid/... → per-map detailed stats with K(hs) column
                                   (requires cookie-warmed session — falls back
                                   gracefully if Cloudflare blocks the request)

Previously blocked but now attempted via session warm-up:
  /stats/players/...            → attempted, falls back if 403
"""

import re
import random
import time
import logging
import statistics as _stats
from datetime import date, timedelta
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HLTV_BASE = "https://www.hltv.org"

# ┌─ RENDER ENVIRONMENT DETECTION ──────────────────────────────────────────────
# On Render, the IP is often blocked by Cloudflare datacenter IP reputation.
# We detect this and apply more aggressive fallback to proxies earlier.
import os
ON_RENDER = "RENDER" in os.environ or "RENDER_GIT_BRANCH" in os.environ
# ─────────────────────────────────────────────────────────────────────────────

# Tuned for Render (shorter timeouts, fewer retries, faster fallback)
if ON_RENDER:
    FETCH_TIMEOUT = 10  # Render worker timeout ~30s total; reduce per-request timeout
    MAX_RETRIES = 2     # Don't waste time on multiple retries per profile
    MAX_PROFILE_ROTATIONS = 2  # 2 profiles max before escalating to proxy
    logger.info("[scraper] Running on Render — aggressive timeout/retry tuning enabled")
else:
    FETCH_TIMEOUT = 25  # Standard timeout for better reliability on unrestricted networks
    MAX_RETRIES = 3
    MAX_PROFILE_ROTATIONS = len([])  # Will be set to len(_PROFILES) later

try:
    from curl_cffi import requests as _cffi_req
    _CFFI_OK = True
except ImportError:
    _CFFI_OK = False
    logger.warning("curl_cffi not available — install it for HLTV access")


_FETCH_RETRY_DELAYS = [1.0, 2.5, 5.0]   # seconds between retries within one profile

# ---------------------------------------------------------------------------
# Impersonation profile rotation
# Tested live — profiles that return 200 from hltv.org are listed first.
# chrome120/chrome124 currently return 403; rotate away from them on failure.
# ---------------------------------------------------------------------------
_PROFILES = ["chrome116", "safari17_0", "chrome107", "chrome110", "chrome99"]
if ON_RENDER and MAX_PROFILE_ROTATIONS == 0:  # sentinel still set
    MAX_PROFILE_ROTATIONS = 2
elif MAX_PROFILE_ROTATIONS == 0:
    MAX_PROFILE_ROTATIONS = len(_PROFILES)

_profile_idx = 0   # index into _PROFILES — advances on repeated 403s

# ---------------------------------------------------------------------------
# Persistent HLTV session — shared across ALL requests so Cloudflare cookies
# accumulate and the IP is treated as a returning browser, not a fresh bot.
# ---------------------------------------------------------------------------
_HLTV_SESSION: "_cffi_req.Session | None" = None
_HLTV_SESSION_WARMED = False
_HLTV_SESSION_PROFILE: str = _PROFILES[0]


def _make_session(profile: str) -> "_cffi_req.Session | None":
    """Create a fresh curl_cffi Session with the given impersonation profile."""
    try:
        sess = _cffi_req.Session(impersonate=profile)
        logger.info(f"[session] Created session with profile={profile}")
        return sess
    except Exception as e:
        logger.warning(f"[session] Could not create session ({profile}): {e}")
        return None


def _get_hltv_session() -> "_cffi_req.Session | None":
    """Return (or lazily create) the shared persistent HLTV curl_cffi Session."""
    global _HLTV_SESSION, _HLTV_SESSION_PROFILE
    if not _CFFI_OK:
        return None
    if _HLTV_SESSION is None:
        _HLTV_SESSION_PROFILE = _PROFILES[_profile_idx]
        _HLTV_SESSION = _make_session(_HLTV_SESSION_PROFILE)
    return _HLTV_SESSION


def _rotate_session() -> "_cffi_req.Session | None":
    """
    Drop the current session and open a new one using the next profile in the
    rotation list.  Called when the current profile starts returning 403.

    Also resets the stats-page circuit-breaker so the new profile gets a clean
    chance to reach /stats/matches/mapstatsid/ pages (they may be accessible
    under a profile that the previous one couldn't use).
    """
    global _HLTV_SESSION, _HLTV_SESSION_WARMED, _HLTV_SESSION_PROFILE, _profile_idx
    global _STATS_SESSION_WARMED, _MAPSTATS_CIRCUIT_BLOCKED
    _profile_idx = (_profile_idx + 1) % len(_PROFILES)
    new_profile = _PROFILES[_profile_idx]
    logger.warning(f"[session] Rotating profile → {new_profile}")
    _HLTV_SESSION = _make_session(new_profile)
    _HLTV_SESSION_PROFILE = new_profile
    _HLTV_SESSION_WARMED = False        # re-warm homepage with new session
    _STATS_SESSION_WARMED = False       # re-warm stats referer with new session
    _MAPSTATS_CIRCUIT_BLOCKED = False   # give mapstats pages a fresh chance
    return _HLTV_SESSION


def _is_cloudflare_challenge(resp) -> bool:
    """
    Detect Cloudflare challenge pages more aggressively.
    Returns True if the response appears to be a CF challenge, False otherwise.
    """
    # Status codes that indicate Cloudflare block
    if resp.status_code in (403, 429, 503):
        return True
    
    # Check for Cloudflare markers in response body
    cf_markers = [
        "Just a moment",
        "__cf_bm",
        "cf.challenge-compat.js",
        "cf_clearance",
        "Checking your browser",
    ]
    return any(marker in resp.text for marker in cf_markers)


def _warm_hltv_session() -> None:
    """
    Visit the HLTV homepage to seed Cloudflare cookies in the session.
    Tries every profile in the rotation until one succeeds.
    """
    global _HLTV_SESSION_WARMED
    if _HLTV_SESSION_WARMED:
        return
    if not _CFFI_OK:
        return

    for _ in range(len(_PROFILES)):
        sess = _get_hltv_session()
        if sess is None:
            return
        try:
            r = sess.get(HLTV_BASE + "/", timeout=15)
            logger.info(
                f"[session] Homepage warm-up: {r.status_code} "
                f"(profile={_HLTV_SESSION_PROFILE})"
            )
            if r.status_code == 200 and not _is_cloudflare_challenge(r):
                _HLTV_SESSION_WARMED = True
                time.sleep(0.5)
                return
            # This profile is blocked — rotate and try next
            logger.warning(
                f"[session] Warm-up 403/CF with {_HLTV_SESSION_PROFILE} — rotating"
            )
            _rotate_session()
        except Exception as e:
            logger.warning(f"[session] Warm-up error ({_HLTV_SESSION_PROFILE}): {e}")
            _rotate_session()

    logger.warning("[session] All profiles failed warm-up — proceeding without cookie seed")


def _fetch(url: str, max_retries: int = None) -> str | None:
    """
    Fetch a URL using the persistent HLTV session with automatic profile rotation.
    
    On Render, escalates to proxy services aggressively on first 403.
    """
    if max_retries is None:
        max_retries = MAX_RETRIES
    
    if not _CFFI_OK:
        logger.warning(f"[fetch] curl_cffi not available, skipping {url}")
        return None

    if _is_stats_blocked(url):
        logger.debug(f"[fetch] /stats/ circuit open — skipping {url}")
        return None

    _warm_hltv_session()

    profiles_tried = 0
    max_profile_rotations = MAX_PROFILE_ROTATIONS

    while profiles_tried <= max_profile_rotations:
        sess = _get_hltv_session()

        if sess is None:
            return None

        got_403_this_profile = False

        for attempt in range(max_retries):
            try:
                tag = f" (retry {attempt})" if attempt else ""
                logger.info(f"[fetch] GET {url}{tag}")

                resp = sess.get(
                    url,
                    timeout=FETCH_TIMEOUT
                )

                logger.info(f"[fetch] Response status={resp.status_code} len={len(resp.text) if resp.text else 0}")

                if resp.status_code == 200 and not _is_cloudflare_challenge(resp) and len(resp.text) > 3000:
                    logger.info(
                        f"[fetch] OK — {len(resp.text):,} chars "
                        f"[{_HLTV_SESSION_PROFILE}]"
                    )
                    return resp.text

                logger.warning(
                    f"[fetch] status={resp.status_code} "
                    f"[{_HLTV_SESSION_PROFILE}]"
                    + (
                        f" — retrying in "
                        f"{_FETCH_RETRY_DELAYS[min(attempt, len(_FETCH_RETRY_DELAYS)-1)]}s"
                        if attempt < max_retries - 1
                        else " — profile exhausted"
                    )
                )

                if resp.status_code == 403:
                    got_403_this_profile = True
                    
                    # On Render, escalate to proxy immediately on first 403
                    if ON_RENDER and '/stats/' in url and profiles_tried == 0:
                        logger.warning(
                            f"[fetch] Render IP flagged (403 on /stats/) — "
                            f"escalating to ScraperAPI immediately"
                        )
                        return _fetch_via_scraperapi(url, referer=HLTV_BASE + "/")

                    if attempt < max_retries - 1:
                        time.sleep(_FETCH_RETRY_DELAYS[attempt])
                    else:
                        break
                else:
                    if attempt < max_retries - 1:
                        time.sleep(_FETCH_RETRY_DELAYS[attempt])

            except Exception as e:
                logger.warning(
                    f"[fetch] {type(e).__name__}: {e} "
                    f"[{_HLTV_SESSION_PROFILE}]"
                )

                if attempt < max_retries - 1:
                    time.sleep(_FETCH_RETRY_DELAYS[attempt])
                else:
                    break

        if got_403_this_profile:
            profiles_tried += 1

            if profiles_tried <= max_profile_rotations:
                _rotate_session()
                time.sleep(0.8)

            continue

        break

    if '/stats/' in url and profiles_tried >= max_profile_rotations:
        _trip_stats_circuit(url)

    logger.warning(
        f"[fetch] Giving up on {url} after trying "
        f"{profiles_tried} profile(s)"
    )

    return None


# ---------------------------------------------------------------------------
# Player ID cache — avoids re-running HLTV search on every command
# ---------------------------------------------------------------------------
# Pre-seeded with verified HLTV IDs for commonly graded CS2 players.
# Keys are lowercase normalised nicknames for robust matching.
# Cache grows automatically when new players are successfully looked up.

_PLAYER_ID_CACHE: dict[str, tuple[str, str, str]] = {
    # key            player_id   slug              display_name
    # NOTE: All IDs below verified against /player/<id>/<slug> on 2026-04-23.
    # 23 of the original 32 entries had wrong IDs (HLTV reassigned them);
    # IDs are now resolved via search and verified by profile-page title.
    "lake":         ("22921",   "lake",            "Lake"),
    "zywoo":        ("11893",   "zywoo",           "ZywOo"),
    "donk":         ("21167",   "donk",            "donk"),
    "niko":         ("3741",    "niko",            "NiKo"),
    "m0nesy":       ("19230",   "m0nesy",          "m0NESY"),
    "sh1ro":        ("16920",   "sh1ro",           "sh1ro"),
    "b1t":          ("18987",   "b1t",             "b1t"),
    "simple":       ("7998",    "simple",          "s1mple"),
    "s1mple":       ("7998",    "simple",          "s1mple"),
    "twistzz":      ("10394",   "twistzz",         "Twistzz"),
    "elige":        ("8738",    "elige",           "EliGE"),
    "ropz":         ("11816",   "ropz",            "ropz"),
    "yekindar":     ("13915",   "yekindar",        "YEKINDAR"),
    "naf":          ("8520",    "naf",             "NAF"),
    "perfecto":     ("16947",   "perfecto",        "Perfecto"),
    "electronic":   ("8918",    "electronic",      "electroNic"),
    "broky":        ("18053",   "broky",           "broky"),
    "rain":         ("8183",    "rain",            "rain"),
    "karrigan":     ("429",     "karrigan",        "karrigan"),
    "frozen":       ("9960",    "frozen",          "frozen"),
    "degster":      ("17306",   "degster",         "degster"),
    "torzsi":       ("18072",   "torzsi",          "torzsi"),
    "idisbalance":  ("14273",   "idisbalance",     "iDISBALANCE"),
    "xant3r":       ("20387",   "xant3r",          "Xant3r"),
    "jl":           ("19206",   "jl",              "jL"),
    "malbsmd":      ("11617",   "malbsmd",         "malbsMd"),
    "grim":         ("13578",   "grim",            "Grim"),
    "coldzera":     ("9216",    "coldzera",        "coldzera"),
    "fallen":       ("2023",    "fallen",          "FalleN"),
    "device":       ("7592",    "device",          "device"),
    "dupreeh":      ("7398",    "dupreeh",         "dupreeh"),
    "magisk":       ("9032",    "magisk",          "Magisk"),
}


def _normalise_player_key(name: str) -> str:
    """Normalise a player name to a cache key (lowercase, alphanumeric only)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


# ---------------------------------------------------------------------------
# Session-based fetcher for /stats/ pages (requires warm cookie session)
# ---------------------------------------------------------------------------

_STATS_SESSION: "_cffi_req.Session | None" = None
_STATS_SESSION_WARMED = False
_STATS_PAGES_BLOCKED = False  # legacy per-fetch circuit-breaker (HS mapstats)

# Cache for mapstatsid HTML so each URL is only fetched once per bot session
_MAPSTATS_HTML_CACHE: dict[str, str] = {}

# ── TWO separate /stats/ circuit-breakers ─────────────────────────────────────
#
#  1. PLAYER/TEAM stats circuit  (/stats/players/, /stats/teams/, /stats/search/)
#     These return 403 from Replit datacenter IPs immediately.
#     TTL = 30 min.
#
#  2. MAPSTATS circuit  (/stats/matches/mapstatsid/)
#     These are the per-map pages containing the K (hs) column.
#     They are fetched with a full browser warm-up and may succeed even when
#     the player-stats circuit is open.  Separate TTL = 5 min so they retry
#     more often.
#
# Keeping them separate means a 403 on a player stats page does NOT block
# mapstatsid page fetches (which is where live HS data comes from).

_STATS_SUBDOMAIN_BLOCKED: bool = False
_STATS_SUBDOMAIN_BLOCKED_AT: float = 0.0
_STATS_SUBDOMAIN_BLOCK_TTL: int = 5 * 60   # 5 minutes (player/team stats) — was 30 min, reduced for faster recovery now that the circuit only trips after exhausting all 5 profiles

_MAPSTATS_CIRCUIT_BLOCKED: bool = False
_MAPSTATS_CIRCUIT_BLOCKED_AT: float = 0.0
_MAPSTATS_CIRCUIT_BLOCK_TTL: int = 5 * 60   # 5 minutes (mapstatsid HS pages)


def _is_mapstats_url(url: str) -> bool:
    return '/stats/matches/mapstatsid/' in url


def _is_stats_blocked(url: str) -> bool:
    """
    Return True if the relevant circuit-breaker is active for this URL.
    mapstatsid URLs use their own narrower circuit; everything else uses
    the global /stats/ circuit.
    """
    global _STATS_SUBDOMAIN_BLOCKED, _STATS_SUBDOMAIN_BLOCKED_AT
    global _MAPSTATS_CIRCUIT_BLOCKED, _MAPSTATS_CIRCUIT_BLOCKED_AT

    if '/stats/' not in url:
        return False

    if _is_mapstats_url(url):
        # mapstatsid has its own 5-min circuit
        if not _MAPSTATS_CIRCUIT_BLOCKED:
            return False
        elapsed = time.time() - _MAPSTATS_CIRCUIT_BLOCKED_AT
        if elapsed > _MAPSTATS_CIRCUIT_BLOCK_TTL:
            _MAPSTATS_CIRCUIT_BLOCKED = False
            logger.info("[circuit] mapstatsid circuit expired — retrying HS pages")
            return False
        return True
    else:
        # Player/team/search stats — 30-min circuit
        if not _STATS_SUBDOMAIN_BLOCKED:
            return False
        elapsed = time.time() - _STATS_SUBDOMAIN_BLOCKED_AT
        if elapsed > _STATS_SUBDOMAIN_BLOCK_TTL:
            _STATS_SUBDOMAIN_BLOCKED = False
            logger.info("[circuit] /stats/ block TTL expired — will retry stats URLs")
            return False
        return True


def _trip_stats_circuit(url: str) -> None:
    """Trip the appropriate circuit-breaker on first 403 from a /stats/ URL."""
    global _STATS_SUBDOMAIN_BLOCKED, _STATS_SUBDOMAIN_BLOCKED_AT
    global _MAPSTATS_CIRCUIT_BLOCKED, _MAPSTATS_CIRCUIT_BLOCKED_AT

    if '/stats/' not in url:
        return

    if _is_mapstats_url(url):
        if not _MAPSTATS_CIRCUIT_BLOCKED:
            _MAPSTATS_CIRCUIT_BLOCKED = True
            _MAPSTATS_CIRCUIT_BLOCKED_AT = time.time()
            logger.warning(
                "[circuit] mapstatsid circuit TRIPPED (403 on HS page) — "
                "retrying in 5 min. HS will use calibrated fallback."
            )
    else:
        if not _STATS_SUBDOMAIN_BLOCKED:
            _STATS_SUBDOMAIN_BLOCKED = True
            _STATS_SUBDOMAIN_BLOCKED_AT = time.time()
            logger.warning(
                "[circuit] /stats/ circuit-breaker TRIPPED — player/team stats "
                "blocked for 30 min. Kill data unaffected (comes from match pages)."
            )


def _get_stats_session() -> "_cffi_req.Session | None":
    """
    Return the shared persistent HLTV session for stats page requests.
    Reuses _HLTV_SESSION so all requests share the same Cloudflare cookies.
    """
    return _get_hltv_session()


def _warm_stats_session(match_url: str) -> bool:
    """
    Warm the shared HLTV session for stats page access by visiting
    the match page (homepage is already done by _warm_hltv_session).
    Returns True when the session is ready.
    """
    global _STATS_SESSION_WARMED, _HLTV_SESSION_WARMED
    if _STATS_SESSION_WARMED:
        return True
    sess = _get_stats_session()
    if sess is None:
        return False
    # Ensure homepage warm-up has happened (sets _HLTV_SESSION_WARMED)
    _warm_hltv_session()
    try:
        r2 = sess.get(match_url, timeout=FETCH_TIMEOUT)
        logger.info(f"[stats_session] Warm-up match page: {r2.status_code} len={len(r2.text)}")
        if r2.status_code == 200:
            _STATS_SESSION_WARMED = True
            return True
    except Exception as e:
        logger.warning(f"[stats_session] Warm-up failed: {e}")
    return False


def _fetch_via_scraperapi(url: str, referer: str = "") -> str | None:
    """
    Fetch a URL through ScraperAPI (https://www.scraperapi.com).
    Free tier = 1,000 req/month. Handles Cloudflare/JS rendering automatically.
    Returns HTML on success, None on failure.
    """
    import os
    import requests as _requests

    if url in _MAPSTATS_HTML_CACHE:
        return _MAPSTATS_HTML_CACHE[url]

    key = os.environ.get("SCRAPERAPI_KEY", "").strip()
    if not key:
        return None

    api_url = "https://api.scraperapi.com/"
    params = {
        "api_key":         key,
        "url":             url,
        "keep_headers":    "true",
        # render=false is enough for HLTV (no JS-gated content) and saves credits
    }
    headers = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer":         referer or "https://www.hltv.org/",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        logger.info(f"[scraperapi] Fetching: {url[-70:]}")
        resp = _requests.get(api_url, params=params, headers=headers, timeout=70)
        if resp.status_code == 200 and len(resp.text) > 3000 and "Just a moment" not in resp.text:
            logger.info(f"[scraperapi] Success — {len(resp.text):,} chars")
            _MAPSTATS_HTML_CACHE[url] = resp.text
            return resp.text
        if resp.status_code == 401:
            logger.warning("[scraperapi] 401 — invalid SCRAPERAPI_KEY")
        elif resp.status_code == 403:
            logger.warning("[scraperapi] 403 — out of credits or plan limit")
        else:
            logger.warning(f"[scraperapi] status={resp.status_code} len={len(resp.text)}")
        return None
    except Exception as e:
        logger.warning(f"[scraperapi] {type(e).__name__}: {str(e)[:140]}")
        return None


def _fetch_via_apify_proxy(url: str, referer: str = "") -> str | None:
    """
    Fetch a URL through the Apify residential proxy network.

    Tries multiple credential formats so the correct one works regardless
    of whether APIFY_TOKEN is an API key or proxy password.
    Returns HTML on success, None on any failure (no circuit tripping).
    """
    import os
    import requests as _requests
    from requests.auth import HTTPProxyAuth

    if url in _MAPSTATS_HTML_CACHE:
        return _MAPSTATS_HTML_CACHE[url]

    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        logger.warning("[apify] APIFY_TOKEN not set — skipping proxy fetch")
        return None

    headers = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer":         referer or "https://www.hltv.org/",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest":  "document",
        "Sec-Fetch-Mode":  "navigate",
        "Sec-Fetch-Site":  "same-origin",
    }

    # Try multiple auth formats — Apify changed how they handle credentials
    proxy_candidates = [
        f"http://auto:{token}@proxy.apify.com:8000",
        f"http://groups-BUYPROXIES94952:{token}@proxy.apify.com:8000",
        f"http://groups-RESIDENTIAL:{token}@proxy.apify.com:8000",
        f"http://{token}:@proxy.apify.com:8000",
    ]

    for proxy_url in proxy_candidates:
        proxies = {"http": proxy_url, "https": proxy_url}
        try:
            logger.info(f"[apify] Trying proxy ({proxy_url.split('@')[0].split('//')[1][:12]}…): {url[-60:]}")
            sess = _requests.Session()
            sess.proxies = proxies
            resp = sess.get(url, headers=headers, timeout=18, verify=False)
            if resp.status_code == 200 and len(resp.text) > 3000 and "Just a moment" not in resp.text:
                logger.info(f"[apify] Success — {len(resp.text):,} chars")
                _MAPSTATS_HTML_CACHE[url] = resp.text
                return resp.text
            if resp.status_code == 407:
                logger.warning(f"[apify] 407 Proxy Auth failed for this format — trying next")
                continue
            logger.warning(f"[apify] status={resp.status_code} len={len(resp.text)} — giving up")
            return None
        except Exception as e:
            err = str(e)
            if "407" in err or "Authentication Required" in err:
                logger.warning(f"[apify] 407 in exception — trying next format")
                continue
            logger.warning(f"[apify] {type(e).__name__}: {err[:120]}")
            return None

    logger.warning("[apify] All proxy credential formats failed (407)")
    return None


def _fetch_stats_page(stats_url: str, match_url: str) -> str | None:
    """
    Fetch an HLTV /stats/matches/mapstatsid/ page.

    Strategy for mapstatsid URLs (HS data):
      - All tls_client profiles get an immediate 403 from HLTV for /stats/ paths
        — cycling through them wastes 20+ seconds per URL with no benefit.
      - Go straight to Apify residential proxy.
      - On failure, return None without tripping any circuit so each URL
        gets its own independent attempt next time.

    Strategy for all other /stats/ URLs (player/team stats):
      - Use the existing profile-cycling approach with circuit-breaker.
    """
    # Check cache first
    if stats_url in _MAPSTATS_HTML_CACHE:
        return _MAPSTATS_HTML_CACHE[stats_url]

    # ── fast-path: circuit-breaker for player/team stats only ─────────────────
    if not _is_mapstats_url(stats_url) and _is_stats_blocked(stats_url):
        logger.info(f"[stats_fetch] /stats/ circuit open — skipping {stats_url[-60:]}")
        return None

    # ── mapstatsid URLs: ONE direct attempt only, no profile cycling ─────────
    # Empirically all 5 cffi profiles uniformly 403 on /stats/matches/mapstatsid/
    # paths (HLTV protects these harder than match pages). Cycling all profiles
    # × 3 retries = 15 attempts of dead time per HS page × 10 series × 2 maps
    # = 300 dead requests per !grade. Now: one quick attempt, fail fast,
    # let the calibrated HS% fallback take over.
    if _is_mapstats_url(stats_url):
        # Tier 1 — Direct cffi (fast path, almost always 403 but free if it works)
        sess = _get_hltv_session()
        if sess is not None:
            try:
                resp = sess.get(stats_url, timeout=10, headers={"Referer": match_url})
                if resp.status_code == 200 and "Just a moment" not in resp.text:
                    logger.info(f"[hs_fetch] ✅ Tier 1 (direct cffi) — {len(resp.text):,} chars · {stats_url[-50:]}")
                    _MAPSTATS_HTML_CACHE[stats_url] = resp.text
                    return resp.text
                logger.debug(f"[hs_fetch] Tier 1 failed (status={resp.status_code}) — escalating")
            except Exception as e:
                logger.debug(f"[hs_fetch] Tier 1 exception ({type(e).__name__}) — escalating")

        # Tier 2 — ScraperAPI (paid credits, usually works on HLTV)
        html = _fetch_via_scraperapi(stats_url, referer=match_url)
        if html:
            logger.info(f"[hs_fetch] ✅ Tier 2 (ScraperAPI) — {stats_url[-50:]}")
            return html

        # Tier 3 — Apify residential proxy (last resort — different IP pool)
        # Re-enabled after Tier 2 became unreliable. Even if free-plan creds
        # 407 on most attempts, the function tries 4 credential formats so
        # one paid/upgraded plan format may succeed.
        html = _fetch_via_apify_proxy(stats_url, referer=match_url)
        if html:
            logger.info(f"[hs_fetch] ✅ Tier 3 (Apify) — {stats_url[-50:]}")
            return html

        logger.warning(f"[hs_fetch] ❌ ALL TIERS FAILED for {stats_url[-60:]} — falling back to estimated HS")
        return None

    # ── non-mapstats /stats/ URLs: direct cffi profile-cycling FIRST ─────────
    # (Was scraperapi-first, which burned credits even when direct works.)
    global _STATS_SESSION_WARMED

    all_profiles = list(_PROFILES)
    start_idx = _profile_idx
    ordered = all_profiles[start_idx:] + all_profiles[:start_idx]

    for profile_attempt, profile in enumerate(ordered):
        global _HLTV_SESSION, _HLTV_SESSION_PROFILE, _HLTV_SESSION_WARMED
        if _HLTV_SESSION_PROFILE != profile or _HLTV_SESSION is None:
            _HLTV_SESSION = _make_session(profile)
            _HLTV_SESSION_PROFILE = profile
            _HLTV_SESSION_WARMED = False
            _STATS_SESSION_WARMED = False

        sess = _HLTV_SESSION
        if sess is None:
            continue

        try:
            if not _HLTV_SESSION_WARMED:
                r_home = sess.get(HLTV_BASE + "/", timeout=12)
                if r_home.status_code == 200 and "Just a moment" not in r_home.text:
                    _HLTV_SESSION_WARMED = True
                    logger.info(f"[stats_fetch] Homepage warm-up OK [{profile}]")
                    time.sleep(random.uniform(0.4, 0.9))

            if not _STATS_SESSION_WARMED and match_url:
                r_match = sess.get(match_url, timeout=15)
                if r_match.status_code == 200:
                    _STATS_SESSION_WARMED = True
                    logger.info(f"[stats_fetch] Match-page warm-up OK [{profile}]")
                    time.sleep(random.uniform(0.3, 0.7))

            logger.info(
                f"[stats_fetch] GET {stats_url} [{profile}]"
                + (f" (attempt {profile_attempt + 1}/{len(ordered)})" if profile_attempt else "")
            )
            resp = sess.get(
                stats_url,
                headers={
                    "Referer":                   match_url or HLTV_BASE + "/",
                    "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language":           "en-US,en;q=0.9",
                    "Accept-Encoding":           "gzip, deflate, br",
                    "Sec-Fetch-Dest":            "document",
                    "Sec-Fetch-Mode":            "navigate",
                    "Sec-Fetch-Site":            "same-origin",
                    "Sec-Fetch-User":            "?1",
                    "Upgrade-Insecure-Requests": "1",
                },
                timeout=15,
            )

            if resp.status_code == 200 and len(resp.text) > 3000 and "Just a moment" not in resp.text:
                logger.info(f"[stats_fetch] OK — {len(resp.text):,} chars [{profile}]")
                return resp.text

            if resp.status_code == 403:
                # Don't trip the circuit on a single 403 — try the next profile.
                # Only trip after we've exhausted all profiles (handled below).
                _STATS_SESSION_WARMED = False
                delay = min(1.0 + profile_attempt * 1.0, 4.0) + random.uniform(0, 0.5)
                time.sleep(delay)
                continue

            logger.warning(f"[stats_fetch] status={resp.status_code} len={len(resp.text)}")
            return None

        except Exception as e:
            logger.warning(f"[stats_fetch] {type(e).__name__}: {e} [{profile}]")
            time.sleep(1.0)
            continue

    # All 5 profiles 403'd — NOW trip the circuit and try ScraperAPI fallback
    _trip_stats_circuit(stats_url)
    logger.info(f"[stats_fetch] All profiles 403'd — falling back to ScraperAPI for {stats_url[-60:]}")
    html = _fetch_via_scraperapi(stats_url, referer=match_url)
    if html:
        logger.info("[stats_fetch] ScraperAPI player-stats fetch succeeded.")
        return html
    logger.warning(f"[stats_fetch] All paths exhausted for {stats_url[-60:]}")
    return None


def _parse_map_stats_hs(
    html: str,
    player_slug: str,
    series_num: int = 0,
    map_num: int = 0,
) -> tuple[int | None, int | None]:
    """
    STRICT extraction of kills and headshots from a /stats/matches/mapstatsid/ page.

    Strict Map-by-Map Path (per user specification):
      1. Locate the stats table on the page (class="stats-table").
      2. Identify the column whose header contains "K" and "hs" — the "K (hs)" column.
      3. Find the row whose player name matches player_slug.
      4. Parse the cell using EXACTLY:
           headshots = int(raw_text.split('(')[1].split(')')[0])
           kills     = int(raw_text.split('(')[0].strip())
      5. If the "(hs)" format is absent from the cell — do NOT guess.
         Emit [ERROR] and return (None, None).

    Returns (kills, headshots) or (None, None) with explicit error logging.
    """
    soup = BeautifulSoup(html, 'html.parser')
    slug_norm = re.sub(r'[^a-z0-9]', '', player_slug.lower())
    ctx = f"Series {series_num} Map {map_num}"  # for audit / error messages

    # ── Step 1: Locate the stats table ────────────────────────────────────────
    # Priority: class="stats-table" → any table with "stats" in class → all tables
    stats_tables = (
        soup.find_all(class_='stats-table') or
        soup.find_all('table', class_=re.compile(r'stats', re.I)) or
        soup.find_all('table')
    )

    if not stats_tables:
        logger.error(
            f"[HS][{ctx}] No tables found on stats page for {player_slug!r}"
        )
        return None, None

    # ── Pre-filter: skip tables with fewer than 5 rows (summary / scoreline junk)
    # and prefer tables that explicitly have a K(hs) header.  Sort: labelled first.
    def _tbl_has_khs_header(t: object) -> bool:
        hr = t.find('tr')  # type: ignore[attr-defined]
        if not hr:
            return False
        for hdr in hr.find_all(['th', 'td']):
            ht = hdr.get_text(strip=True).lower()
            if re.search(r'k[^a-z]*\(?hs|hs.*\)', ht):
                return True
        return False

    stats_tables = sorted(stats_tables, key=lambda t: (not _tbl_has_khs_header(t), -len(t.find_all('tr'))))

    for tbl in stats_tables:
        all_rows = tbl.find_all('tr')
        # Skip tiny tables (scoreboard headers, overview blocks, etc.)
        if len(all_rows) < 5:
            continue

        header_row = all_rows[0]
        headers    = header_row.find_all(['th', 'td'])

        # ── Step 2: Identify the K (hs) column ────────────────────────────────
        khs_col = None
        for ci, hdr in enumerate(headers):
            ht = hdr.get_text(strip=True).lower()
            # Matches: "k (hs)", "k(hs)", "kills (hs)", "k / hs", etc.
            if re.search(r'k[^a-z]*\(?hs|hs.*\)', ht):
                khs_col = ci
                logger.debug(f"[HS][{ctx}] K(hs) column found at index {ci}, header={ht!r}")
                break

        # Fallback: scan ALL data rows (not just the first) for "N (N)" pattern
        # and require that the same column is consistent across ≥2 rows.
        if khs_col is None:
            all_headers_text = [h.get_text(strip=True) for h in headers]
            logger.debug(f"[HS][{ctx}] No K(hs) header in: {all_headers_text}")
            col_hits: dict[int, int] = {}
            for dr in all_rows[1:6]:   # check up to 5 data rows
                data_cells = dr.find_all('td')
                for probe in range(min(len(data_cells), 8)):
                    ct = data_cells[probe].get_text(strip=True)
                    if re.search(r'^\d+\s*\(\d+\)$', ct):
                        # Extra guard: HS value (inside parens) must be ≤ kills value
                        try:
                            _k = int(ct.split('(')[0].strip())
                            _h = int(ct.split('(')[1].rstrip(')').strip())
                            if _h <= _k:       # valid K(hs) cell
                                col_hits[probe] = col_hits.get(probe, 0) + 1
                        except (ValueError, IndexError):
                            pass
            if col_hits:
                # Pick the column with the most consistent hits
                khs_col = max(col_hits, key=lambda c: col_hits[c])
                logger.debug(
                    f"[HS][{ctx}] K(hs) column probed at index {khs_col} "
                    f"(consistency hits={col_hits[khs_col]})"
                )

        if khs_col is None:
            logger.debug(f"[HS][{ctx}] K(hs) column not found in this table — trying next")
            continue

        # ── Step 3: Find the player's row ─────────────────────────────────────
        player_row_found = False
        for tr in all_rows[1:]:
            row_text = tr.get_text()
            row_norm = re.sub(r'[^a-z0-9]', '', row_text.lower())
            if slug_norm not in row_norm:
                continue

            player_row_found = True
            cells = tr.find_all('td')
            if khs_col >= len(cells):
                logger.error(
                    f"[HS][{ctx}] {player_slug!r} row found but K(hs) col {khs_col} "
                    f"out of range (row has {len(cells)} cells)"
                )
                return None, None

            raw_text = cells[khs_col].get_text(strip=True)
            logger.info(f"[HS][{ctx}] K(hs) cell for {player_slug!r}: {raw_text!r}")

            # ── Step 4: Strict parse — "21 (11)" format ONLY ──────────────────
            if '(' not in raw_text or ')' not in raw_text:
                # The (hs) format is missing — do NOT guess
                logger.error(
                    f"[ERROR] Missing HS data for Map {map_num} of Series {series_num} "
                    f"— cell was {raw_text!r}, expected format '21 (11)'"
                )
                print(
                    f"[ERROR] Missing HS data for Map {map_num} of Series {series_num} "
                    f"(player={player_slug}, cell={raw_text!r})"
                )
                return None, None

            try:
                headshots = int(raw_text.split('(')[1].split(')')[0].strip())
                kills_str = raw_text.split('(')[0].strip()
                kills_m   = re.search(r'(\d+)', kills_str)
                kills_hs  = int(kills_m.group(1)) if kills_m else None

                # ── Sanity check: headshots can never exceed kills ─────────────
                if kills_hs is not None and headshots > kills_hs:
                    logger.error(
                        f"[HS][{ctx}] Sanity FAIL — HS ({headshots}) > kills ({kills_hs}) "
                        f"for {player_slug!r}, cell={raw_text!r} — wrong column, discarding"
                    )
                    return None, None

                # Headshots in a single CS2 map realistically cap around 30
                if headshots > 35:
                    logger.error(
                        f"[HS][{ctx}] Sanity FAIL — HS ({headshots}) implausibly high "
                        f"for {player_slug!r} — discarding"
                    )
                    return None, None

                logger.info(
                    f"[HS][{ctx}] Parsed — kills={kills_hs}  headshots={headshots}"
                )
                return kills_hs, headshots

            except (IndexError, ValueError) as e:
                logger.error(
                    f"[ERROR] Missing HS data for Map {map_num} of Series {series_num} "
                    f"— parse error on {raw_text!r}: {e}"
                )
                print(
                    f"[ERROR] Missing HS data for Map {map_num} of Series {series_num} "
                    f"(player={player_slug}, cell={raw_text!r}, err={e})"
                )
                return None, None

        if not player_row_found:
            logger.warning(
                f"[HS][{ctx}] Player {player_slug!r} (norm={slug_norm!r}) not found "
                f"in any data row of this table"
            )

    logger.error(
        f"[ERROR] Missing HS data for Map {map_num} of Series {series_num} "
        f"— player {player_slug!r} not found or no K(hs) column on stats page"
    )
    print(
        f"[ERROR] Missing HS data for Map {map_num} of Series {series_num} "
        f"(player={player_slug})"
    )
    return None, None


def _parse_map_stats_mks(
    html: str,
    player_slug: str,
    series_num: int = 0,
    map_num: int = 0,
) -> int | None:
    """
    Extract the multikill count (MKs) for a player from a per-map
    /stats/matches/mapstatsid/ page.

    HLTV's per-player row on this page has columns roughly:
        Player | Op K-D | MKs | KAST | 1vsX | K (hs) | A (f) | D (t) | ADR | Swing | Rating
    The MKs cell can be:
        • A single integer count of multi-kill rounds in the map (e.g. "5")
        • A breakdown string like "3/2/1/0" (2K/3K/4K/5K) — we sum it
        • Empty / "-" for players with no multikills

    Returns total multikill count (int) or None if not parsable.
    """
    soup = BeautifulSoup(html, 'html.parser')
    slug_norm = re.sub(r'[^a-z0-9]', '', player_slug.lower())
    ctx = f"Series {series_num} Map {map_num}"

    stats_tables = (
        soup.find_all(class_='stats-table') or
        soup.find_all('table', class_=re.compile(r'stats', re.I)) or
        soup.find_all('table')
    )

    for tbl in stats_tables:
        rows = tbl.find_all('tr')
        if len(rows) < 5:
            continue
        headers = rows[0].find_all(['th', 'td'])

        # Locate MKs column by header.  Match "MKs", "MK", "Multi-kills".
        mk_col = None
        for ci, hdr in enumerate(headers):
            ht = hdr.get_text(strip=True).lower().replace(' ', '')
            if ht in ('mks', 'mk', 'multikills', 'multi-kills'):
                mk_col = ci
                break
        if mk_col is None:
            continue

        # Find the player row and extract.
        for tr in rows[1:]:
            row_norm = re.sub(r'[^a-z0-9]', '', tr.get_text().lower())
            if slug_norm not in row_norm:
                continue
            cells = tr.find_all('td')
            if mk_col >= len(cells):
                continue
            raw = cells[mk_col].get_text(strip=True)
            if not raw or raw in ('-', '–', '0'):
                logger.debug(f"[MK][{ctx}] {player_slug!r}: cell={raw!r} → 0")
                return 0
            # Slash-separated breakdown (2K/3K/4K/5K)
            if '/' in raw:
                try:
                    parts = [int(p.strip()) for p in raw.split('/') if p.strip().isdigit()]
                    total = sum(parts)
                    logger.debug(f"[MK][{ctx}] {player_slug!r}: cell={raw!r} → sum={total}")
                    return total
                except ValueError:
                    pass
            # Single integer
            m = re.match(r'^(\d{1,2})$', raw)
            if m:
                val = int(m.group(1))
                if 0 <= val <= 30:        # sanity bound — never more than ~30 multi-kill rounds in a map
                    logger.debug(f"[MK][{ctx}] {player_slug!r}: cell={raw!r} → {val}")
                    return val
    logger.debug(f"[MK][{ctx}] no MKs column found for {player_slug!r}")
    return None



