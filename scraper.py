import os
import re
import time
import statistics as stats
from collections import defaultdict
from urllib.parse import quote, urljoin
from datetime import datetime, timedelta
import numpy as np
from bs4 import BeautifulSoup

try:
    from curl_effi import requests # type: ignore
except Exception:
    import requests # type: ignore

HLTV_BASE = "https://www.hltv.org"

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

def fetch(url: str, render: bool = False, timeout: int = 30, retries: int = 2):
    """Fetch URL with retry logic and exponential backoff."""
    for attempt in range(retries):
        targets = []
        if SCRAPERAPI_KEY:
            encoded = quote(url, safe="")
            for use_render in (render, not render, True):
                proxy = (
                    "http://api.scraperapi.com"
                    f"?api_key={SCRAPERAPI_KEY}"
                    f"&url={encoded}"
                    "&country_code=us"
                    "&keep_headers=true"
                    f"{'&render=true' if use_render else ''}"
                )
                targets.append(proxy)
        else:
            targets.append(url)

        for target in targets:
            try:
                print(f"DEBUG: Fetching {target}")
                resp = requests.get(target, headers=HEADERS, timeout=10)
                if resp.status_code == 200 and len(resp.text or "") > 800:
                    final_url = resp.headers.get("Sa-Final-Url") or getattr(resp, "url", target)
                    return resp.text, final_url
            except requests.exceptions.Timeout:
                if attempt < retries - 1:
                    time.sleep(2**attempt)
                break
            except Exception:
                if attempt < retries - 1:
                    time.sleep(1)
                break
    return None, None
