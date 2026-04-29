"""
scraper.py — Pulls for-sale and rental listings from Redfin's gis-csv endpoint.
No API key required. Respects the 350-listing cap by splitting into price bands.

Cookie strategy (in priority order):
  1. REDFIN_COOKIE env var / hardcoded below  →  used as-is, no browser needed
  2. Playwright (headless Chromium)           →  auto-extracts a fresh session
  3. requests homepage visit                  →  last-resort fallback (often fails)

Install Playwright once:
    pip3 install playwright
    playwright install chromium
"""

import requests
import io
import os
import time
import csv as csv_module
from typing import Optional

# ── Optional: paste a manual cookie here (or set env var REDFIN_COOKIE) ────────
# Leave as "" to let Playwright handle it automatically.
REDFIN_COOKIE = os.environ.get("REDFIN_COOKIE", "")

BASE_URL      = "https://www.redfin.com/stingray/api/gis-csv"
REDFIN_HOME   = "https://www.redfin.com/"

# How long (seconds) a Playwright-extracted cookie is trusted before refresh
COOKIE_TTL    = 60 * 45   # 45 minutes

# Known first column of a real Redfin gis-csv header row.
# Used to skip disclaimer / boilerplate lines that Redfin sometimes prepends.
_CSV_HEADER_STARTS = ("SALE TYPE", "ADDRESS", "MLS#")


# ── Session state ───────────────────────────────────────────────────────────────
_session:          Optional[requests.Session] = None
_session_born_at:  float = 0.0


# ── Playwright cookie extraction ────────────────────────────────────────────────

def _extract_cookies_via_playwright() -> Optional[str]:
    """
    Launch a headless Chromium, visit Redfin, wait for the gis-csv request to
    fire (so we know the full cookie jar is populated), then return the Cookie
    header string. Returns None if Playwright is unavailable or fails.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("  [auth] Playwright not installed — run: pip3 install playwright && playwright install chromium")
        return None

    print("  [auth] Launching headless browser to extract Redfin session...")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            page = context.new_page()

            # Visit homepage — seeds RF_BROWSER_ID and other session cookies
            page.goto(REDFIN_HOME, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2)

            # Trigger a real search so Redfin's JS sets search-context cookies
            # (some cookies only appear after a map/search interaction)
            try:
                page.goto(
                    "https://www.redfin.com/city/3105/NC/Charlotte",
                    wait_until="networkidle",   # wait for map tiles + XHR to settle
                    timeout=30_000,
                )
                time.sleep(5)   # extra buffer for search-context cookies to populate
            except PWTimeout:
                pass   # homepage cookies are enough most of the time

            # Harvest all cookies for redfin.com
            cookies = context.cookies("https://www.redfin.com")
            browser.close()

        if not cookies:
            print("  [auth] Playwright returned no cookies.")
            return None

        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        print(f"  [auth] Extracted {len(cookies)} cookies via Playwright ✓")
        return cookie_str

    except Exception as e:
        print(f"  [auth] Playwright failed: {e}")
        return None


# ── Session factory ─────────────────────────────────────────────────────────────

def _build_session(cookie_str: Optional[str]) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":             "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":    "en-US,en;q=0.9",
        "Accept-Encoding":    "gzip, deflate, br",
        "Referer":            "https://www.redfin.com/",
        "X-Requested-With":   "XMLHttpRequest",
        "sec-ch-ua":          '"Chromium";v="124", "Google Chrome";v="124"',
        "sec-ch-ua-mobile":   "?0",
        "sec-ch-ua-platform": '"macOS"',
        "Sec-Fetch-Dest":     "empty",
        "Sec-Fetch-Mode":     "cors",
        "Sec-Fetch-Site":     "same-origin",
    })
    if cookie_str:
        session.headers["Cookie"] = cookie_str
    return session


def _get_session(force_refresh: bool = False) -> requests.Session:
    """
    Return a session, refreshing cookies if TTL has expired or forced.
    Priority: manual env cookie → Playwright → homepage visit fallback.
    """
    global _session, _session_born_at

    now     = time.monotonic()
    expired = (now - _session_born_at) > COOKIE_TTL

    if _session is not None and not force_refresh and not expired:
        return _session

    if REDFIN_COOKIE:
        # Manual cookie — trust it as-is (user must update manually when it expires)
        print("  [auth] Using REDFIN_COOKIE from environment")
        _session = _build_session(REDFIN_COOKIE)

    else:
        cookie_str = _extract_cookies_via_playwright()

        if cookie_str is None:
            # Last resort: hit the homepage and hope requests picks up cookies
            print("  [auth] Falling back to homepage session (may not work)...")
            s = _build_session(None)
            try:
                s.get(REDFIN_HOME, timeout=15)
                time.sleep(2)
            except Exception as e:
                print(f"  [auth] Homepage fetch failed: {e}")
            _session = s
        else:
            _session = _build_session(cookie_str)

    _session_born_at = now
    return _session


# ── Core fetch ──────────────────────────────────────────────────────────────────

def _parse_csv_response(text: str) -> list[dict]:
    """
    Parse the raw text from a gis-csv response into a list of row dicts.

    Redfin sometimes prepends disclaimer lines before the real CSV header.
    We find the true header by looking for a line whose first comma-delimited
    token matches a known column name, rather than relying on line position.
    This avoids skipping the header when disclaimer text contains "ADDRESS".
    """
    lines = text.strip().splitlines()

    # Strip UTF-8 BOM from first line if present
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0][1:]

    # Find the first line that looks like the real CSV header
    start = None
    for i, line in enumerate(lines):
        stripped    = line.strip().strip('"')
        first_token = stripped.split(",")[0].strip().strip('"').upper()
        if first_token in (h.upper() for h in _CSV_HEADER_STARTS):
            start = i
            break

    if start is None:
        # No recognisable header found — return empty rather than garbage rows
        return []

    clean_text = "\n".join(lines[start:])
    reader     = csv_module.DictReader(io.StringIO(clean_text))
    return list(reader)


def _fetch_csv(params: dict, label: str) -> list[dict]:
    """
    Hit the Redfin gis-csv endpoint and return rows as a list of dicts.
    Retries up to 3 times; on 401/403 refreshes the session once before giving up.
    """
    session           = _get_session()
    session_refreshed = False

    for attempt in range(3):
        try:
            resp = session.get(BASE_URL, params=params, timeout=20)

            # Keep session warm — honour any Set-Cookie the API sends back
            if resp.cookies:
                existing  = session.headers.get("Cookie", "")
                new_pairs = "; ".join(
                    f"{c.name}={c.value}"
                    for c in resp.cookies
                    if c.name not in existing
                )
                if new_pairs:
                    session.headers["Cookie"] = (existing + "; " + new_pairs).strip("; ")

            if resp.status_code == 200:
                text = resp.content.decode("utf-8", errors="replace")
                rows = _parse_csv_response(text)
                print(f"    ✓ {label}: {len(rows)} listings")
                return rows

            elif resp.status_code in (401, 403) and not session_refreshed:
                print(f"    HTTP {resp.status_code} — session expired, refreshing cookies...")
                session           = _get_session(force_refresh=True)
                session_refreshed = True
                continue   # retry immediately with new session

            elif resp.status_code == 400:
                snippet = resp.text[:300].replace("\n", " ")
                print(f"    HTTP 400 for {label}  |  {snippet}")
                return []

            elif resp.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"    Rate limited. Waiting {wait}s...")
                time.sleep(wait)

            else:
                print(f"    HTTP {resp.status_code} for {label}")
                return []

        except requests.RequestException as e:
            print(f"    Request error: {e}")
            time.sleep(3)

    return []


# ── Public API ──────────────────────────────────────────────────────────────────

def fetch_for_sale(region_id: str, region_type: str, market: str,
                   min_price: int, max_price: int, property_types: str) -> list[dict]:
    """
    Fetch active + coming-soon for-sale listings within a price band.

    Supports region_type 2 (zip), 6 (city), and 9 (school district).

    Parameters restored from old scraper:
      - al=1: required by Redfin's API — omitting it causes HTTP 400 on all regions.
      - sf=1,2,3,5,6,7: status filter bitmask. Contrary to a prior comment, this is
        NOT a sold-history filter in gis-csv context — it controls which listing
        status types are included. Omitting it causes Redfin to use a narrower
        default that silently drops some active listings on certain market shards.
    """
    params = {
        "al":          1,
        "market":      market,
        "min_price":   min_price,
        "max_price":   max_price,
        "num_homes":   350,
        "ord":         "price-asc",
        "page_number": 1,
        "region_id":   region_id,
        "region_type": region_type,
        "sf":          "1,2,3,5,6,7",
        "status":      9,
        "uipt":        property_types,
        "v":           8,
    }
    label = f"sale ${min_price:,}–${max_price:,}"
    return _fetch_csv(params, label)


def fetch_for_rent(region_id: str, region_type: str, market: str,
                   min_price: int, max_price: int, property_types: str) -> list[dict]:
    """
    Fetch active rental listings within a price band.
    Supports region_type 2 (zip), 6 (city), and 9 (school district).
    """
    params = {
        "al":          1,
        "isRentals":   "true",
        "market":      market,
        "min_price":   min_price,
        "max_price":   max_price,
        "num_homes":   350,
        "ord":         "price-asc",
        "page_number": 1,
        "region_id":   region_id,
        "region_type": region_type,
        "sf":          "1,2,3,5,6,7",
        "status":      9,
        "uipt":        property_types,
        "v":           8,
    }
    label = f"rent ${min_price:,}–${max_price:,}/mo"
    return _fetch_csv(params, label)


def deduplicate(rows: list[dict], key_field: str = "MLS#") -> list[dict]:
    """
    Remove duplicate listings across zip, city, and school-district queries.

    Key priority:
      1. MLS# — stable and unique per listing, preferred.
      2. Address + ZIP composite — fallback for new construction and some
         off-market listings that lack an MLS#.
      3. No key at all — kept as-is (can't dedup, better to include than drop).
    """
    seen   = set()
    unique = []
    for row in rows:
        mls  = (row.get(key_field) or "").strip()
        addr = ((row.get("ADDRESS") or "") + "|" + (row.get("ZIP OR POSTAL CODE") or "")).strip()
        key  = mls if mls else addr

        if key and key not in seen:
            seen.add(key)
            unique.append(row)
        elif not key:
            # No usable key — include rather than silently drop
            unique.append(row)

    return unique
