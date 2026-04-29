"""
favorites.py — Ingest individual Redfin property URLs or a saved Favorites list
into the database, scoring each property the same way main.py does.

Usage:
    # One or more individual property URLs
    python3 favorites.py https://www.redfin.com/NC/Charlotte/16458-Redstone-Mountain-Ln-28277/home/44107948

    # Your Redfin favorites list (must be logged-in session cookie)
    python3 favorites.py --favorites https://www.redfin.com/user/favorites

    # Mix both
    python3 favorites.py --favorites https://www.redfin.com/user/favorites \\
        https://www.redfin.com/SC/Fort-Mill/374-Tall-Oaks-Trl-29715/home/52129106

Requirements:
    - Same REDFIN_COOKIE / Playwright setup as scraper.py
    - For --favorites: the cookie must belong to the account that owns the list
"""

import csv
import re
import sys
import time
import json
from typing import Optional, List, Dict
from datetime import datetime

import database
import scraper
import mortgage


def _safe_float(val, default=0.0):
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return default


# ── Per-property scrape via public listing page ────────────────────────────────

def fetch_property_by_url(listing_url):
    # type: (str) -> Optional[Dict]
    """
    Dispatch to the correct scraper based on the listing domain.
    Returns a normalized dict ready for upsert_sale(), or None on failure.
    """
    if "zillow.com" in listing_url:
        return _fetch_zillow(listing_url)
    return _fetch_redfin(listing_url)


def _fetch_zillow(listing_url):
    # type: (str) -> Optional[Dict]
    """
    Fetch a Zillow listing page using Playwright (Zillow blocks plain requests).
    Extracts property data from the embedded __NEXT_DATA__ JSON blob.
    Returns a normalized dict or None on failure.
    """
    import random
    print("  Fetching (Zillow): {}".format(listing_url))

    html = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            # Use a persistent context to look more like a real browser
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="America/New_York",
                viewport={"width": 1366, "height": 768},
                # Spoof realistic screen/hardware info
                color_scheme="light",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"macOS"',
                    "Upgrade-Insecure-Requests": "1",
                },
            )

            # Hide webdriver flag — key Zillow bot detection signal
            ctx.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = { runtime: {} };
            """)

            page = ctx.new_page()

            # Do NOT block resources — Zillow checks that fonts/images load
            # to distinguish real browsers from scrapers.

            # First visit zillow.com homepage to warm up cookies, like a real user
            try:
                page.goto("https://www.zillow.com/", wait_until="domcontentloaded", timeout=20000)
                time.sleep(random.uniform(1.5, 3.0))
            except Exception:
                pass  # Non-fatal — proceed to the listing

            # Navigate to the listing
            page.goto(listing_url, wait_until="networkidle", timeout=45000)

            # Human-like random delay before reading DOM
            time.sleep(random.uniform(2.5, 4.5))

            # Try to wait for __NEXT_DATA__ script tag
            try:
                page.wait_for_selector("#__NEXT_DATA__", timeout=12000)
            except Exception:
                # May still be present even if selector times out
                pass

            html = page.content()

            # If blocked, Zillow often redirects to a CAPTCHA or shows no data
            if "captcha" in html.lower() or "robot" in html.lower():
                print("    [skip] Zillow returned a CAPTCHA/bot-detection page")
                browser.close()
                return None

            browser.close()
    except Exception as e:
        print("    Playwright error: {}".format(e))
        return None

    if not html:
        print("    [skip] Empty page from Playwright")
        return None

    m = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
                  html, re.DOTALL)
    if not m:
        # Zillow sometimes inlines the data differently — try a fallback pattern
        m = re.search(r'__NEXT_DATA__\s*=\s*(\{.*?\})(?:\s*;|\s*</script>)',
                      html, re.DOTALL)
    if not m:
        print("    [skip] __NEXT_DATA__ not found in rendered page")
        print("    Tip: Zillow aggressively blocks bots. Try:")
        print("      1. Add a ZILLOW_COOKIE env var from your logged-in browser session")
        print("      2. Use a residential proxy")
        print("      3. Paste the Redfin equivalent URL instead")
        return None

    try:
        next_data = json.loads(m.group(1))
    except ValueError as e:
        print("    [skip] JSON parse error: {}".format(e))
        return None

    props = next_data.get("props", {}).get("pageProps", {})

    # Zillow stores listing data in gdpClientCache (keyed by zpid path)
    gdp = (
        props.get("gdpClientCache") or
        props.get("initialReduxState", {}).get("gdp", {}).get("gdpClientCache")
    )

    listing = None
    if isinstance(gdp, dict):
        for val in gdp.values():
            if isinstance(val, dict) and "property" in val:
                listing = val["property"]
                break
    if not listing:
        listing = props.get("listing") or props.get("property")

    if not listing:
        print("    [skip] Could not locate property node in __NEXT_DATA__")
        return None

    def _f(val):
        try:
            return float(str(val).replace(",", "").replace("$", "").strip())
        except (ValueError, TypeError):
            return None

    addr_obj   = listing.get("address") or {}
    price_raw  = listing.get("price") or listing.get("zestimate")
    street     = addr_obj.get("streetAddress") or listing.get("streetAddress")
    city       = addr_obj.get("city") or listing.get("city")
    state      = addr_obj.get("state") or listing.get("state")
    zip_       = addr_obj.get("zipcode") or listing.get("zipcode")
    beds       = listing.get("bedrooms") or listing.get("beds")
    baths      = listing.get("bathrooms") or listing.get("baths")
    sqft_raw   = listing.get("livingArea") or listing.get("livingAreaValue")
    year_built = listing.get("yearBuilt")
    lot_raw    = listing.get("lotSize") or listing.get("lotAreaValue")
    hoa_raw    = (listing.get("hoaFee") or
                  (listing.get("resoFacts") or {}).get("associationFee"))
    dom        = listing.get("daysOnZillow")
    status     = listing.get("homeStatus") or listing.get("listingStatus")
    prop_type  = listing.get("homeType") or listing.get("propertyTypeDimension")
    zpid       = listing.get("zpid")
    mls_id     = (listing.get("mlsid") or
                  (listing.get("attributionInfo") or {}).get("mlsId") or
                  ("zpid_{}".format(zpid) if zpid else None))
    nbhd       = (listing.get("neighborhoodRegion") or {}).get("name")

    price = _f(price_raw)
    sqft  = _f(sqft_raw)

    row = {
        "mls_id":         str(mls_id) if mls_id else None,
        "address":        street,
        "city":           city,
        "state":          state,
        "zip":            str(zip_) if zip_ else None,
        "latitude":       listing.get("latitude"),
        "longitude":      listing.get("longitude"),
        "price":          price,
        "beds":           beds,
        "baths":          baths,
        "sqft":           sqft,
        "year_built":     year_built,
        "property_type":  prop_type,
        "hoa_monthly":    _f(hoa_raw),
        "days_on_market": dom,
        "neighborhood":   nbhd,
        "lot_size":       _f(lot_raw),
        "status":         status,
        "listing_url":    listing_url,
        "area_label":     "favorites",
        "scraped_at":     datetime.utcnow().isoformat(),
        "price_per_sqft": round(price / sqft, 2) if price and sqft else None,
    }

    if not row["mls_id"]:
        slug = listing_url.rstrip("/").split("/")[-1]
        row["mls_id"] = "url_{}".format(slug)

    addr  = row.get("address") or listing_url
    price = row.get("price")
    print("    ✓ {}  ${:,.0f}".format(addr, price) if price else "    ✓ {}".format(addr))
    return row


def _fetch_redfin(listing_url):
    # type: (str) -> Optional[Dict]
    """
    Fetch a Redfin listing page and extract property data from the embedded
    JSON state blob. Falls back to meta tag / regex scraping if needed.
    Returns a normalized dict ready for upsert_sale(), or None on failure.
    """
    print("  Fetching (Redfin): {}".format(listing_url))
    session = scraper._get_session()

    try:
        resp = session.get(listing_url, timeout=20)
    except Exception as e:
        print("    Request error: {}".format(e))
        return None

    if resp.status_code == 403:
        # Playwright session sometimes triggers 403 on direct page fetches.
        # Retry with a plain cookieless session which Redfin tolerates more.
        print("    403 with session — retrying without cookie (Redfin)...")
        try:
            plain = scraper._build_session(None)
            resp  = plain.get(listing_url, timeout=20)
        except Exception as e:
            print("    Retry error: {}".format(e))
            return None

    if resp.status_code != 200:
        print("    HTTP {} — skipping".format(resp.status_code))
        return None

    html = resp.text
    row  = (
        _parse_from_json_blob(html) or
        _parse_from_meta_tags(html, listing_url)
    )

    if not row:
        print("    [skip] Could not parse property data from page")
        return None

    row["listing_url"] = listing_url
    row["area_label"]  = "favorites"
    row["scraped_at"]  = datetime.utcnow().isoformat()

    if not row.get("mls_id"):
        slug = listing_url.rstrip("/").split("/")[-1]
        row["mls_id"] = "url_{}".format(slug)

    try:
        p = float(str(row.get("price") or 0))
        s = float(str(row.get("sqft") or 0).replace(",", ""))
        row["price_per_sqft"] = round(p / s, 2) if s > 0 else None
    except (ValueError, TypeError):
        row["price_per_sqft"] = None

    addr  = row.get("address") or listing_url
    price = row.get("price")
    print("    ✓ {}  ${:,.0f}".format(addr, price) if price else "    ✓ {}".format(addr))
    return row


def _parse_from_json_blob(html):
    # type: (str) -> Optional[Dict]
    """
    Extract property fields from Redfin's embedded JSON bootstrap data.
    Tries schema.org JSON-LD first (most stable), then React server state.
    """
    # ── schema.org JSON-LD ───────────────────────────────────────────────────
    ld_matches = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    for blob in ld_matches:
        try:
            data = json.loads(blob.strip())
            if isinstance(data, dict) and data.get("@type") in (
                "SingleFamilyResidence", "Apartment", "House",
                "Residence", "RealEstateListing", "Product"
            ):
                result = _extract_from_ld_json(data)
                if result and result.get("price"):
                    return result
        except (ValueError, KeyError):
            continue

    # ── React / script tag JSON blobs ────────────────────────────────────────
    script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    for block in script_blocks:
        if '"propertyId"' not in block or '"price"' not in block:
            continue
        start = block.find("{")
        if start == -1:
            continue
        depth = 0
        end   = start
        for i, ch in enumerate(block[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        try:
            data   = json.loads(block[start:end + 1])
            result = _extract_from_react_state(data)
            if result and result.get("price"):
                return result
        except (ValueError, KeyError):
            continue

    return None


def _extract_from_ld_json(data):
    # type: (Dict) -> Optional[Dict]
    """Extract fields from a schema.org JSON-LD object."""
    try:
        addr_obj  = data.get("address") or {}
        price_raw = (
            (data.get("offers") or {}).get("price") or
            data.get("price") or
            data.get("floorPrice")
        )
        ident = data.get("identifier")
        mls   = ident.get("value") if isinstance(ident, dict) else ident
        floor = data.get("floorSize")
        sqft  = floor.get("value") if isinstance(floor, dict) else None
        geo   = data.get("geo") or {}
        return {
            "mls_id":         str(mls) if mls else None,
            "address":        data.get("name") or addr_obj.get("streetAddress"),
            "city":           addr_obj.get("addressLocality"),
            "state":          addr_obj.get("addressRegion"),
            "zip":            addr_obj.get("postalCode"),
            "latitude":       geo.get("latitude"),
            "longitude":      geo.get("longitude"),
            "price":          _safe_float(price_raw) if price_raw else None,
            "beds":           data.get("numberOfBedrooms") or data.get("numberOfRooms"),
            "baths":          data.get("numberOfBathroomsTotal"),
            "sqft":           sqft,
            "year_built":     data.get("yearBuilt"),
            "property_type":  data.get("@type"),
            "neighborhood":   None,
            "lot_size":       None,
            "hoa_monthly":    None,
            "days_on_market": None,
            "status":         None,
        }
    except Exception:
        return None


def _extract_from_react_state(data):
    # type: (Dict) -> Optional[Dict]
    """
    Recursively search a Redfin React state blob for known property keys.
    The nesting structure varies across Redfin deploys.
    """
    def find(obj, *keys):
        if isinstance(obj, dict):
            node = obj
            for k in keys:
                if not isinstance(node, dict) or k not in node:
                    node = None
                    break
                node = node[k]
            if node is not None:
                return node
            for v in obj.values():
                r = find(v, *keys)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for item in obj:
                r = find(item, *keys)
                if r is not None:
                    return r
        return None

    try:
        price = (
            find(data, "listingPrice", "amount", "value") or
            find(data, "price", "amount", "value") or
            find(data, "displayedPrice")
        )
        street = (
            find(data, "streetAddress", "assembledAddress") or
            find(data, "address", "street")
        )
        return {
            "mls_id":         find(data, "mlsId", "value") or find(data, "mlsNumber"),
            "address":        street,
            "city":           find(data, "city"),
            "state":          find(data, "state"),
            "zip":            find(data, "zip") or find(data, "postalCode"),
            "latitude":       find(data, "latitude") or find(data, "lat"),
            "longitude":      find(data, "longitude") or find(data, "lng"),
            "price":          _safe_float(price) if price else None,
            "beds":           find(data, "beds") or find(data, "numBeds"),
            "baths":          find(data, "baths") or find(data, "numBaths"),
            "sqft":           find(data, "sqFt", "value") or find(data, "squareFeet"),
            "year_built":     find(data, "yearBuilt"),
            "property_type":  find(data, "propertyType") or find(data, "propertyTypeName"),
            "hoa_monthly":    find(data, "hoa", "feeAmount") or find(data, "hoaFee"),
            "days_on_market": find(data, "daysOnMarket") or find(data, "dom"),
            "neighborhood":   find(data, "neighborhoodName"),
            "lot_size":       find(data, "lotSize", "value"),
            "status":         find(data, "listingStatus") or find(data, "mlsStatus"),
        }
    except Exception:
        return None


def _parse_from_meta_tags(html, listing_url):
    # type: (str, str) -> Optional[Dict]
    """
    Last-resort fallback: extract basic fields from Open Graph meta tags
    and visible text patterns in the HTML.
    """
    def meta(prop):
        m = re.search(
            r'<meta[^>]+(?:property|name)=["\']{}["\'][^>]+content=["\']([^"\']+)["\']'.format(
                re.escape(prop)),
            html
        )
        return m.group(1).strip() if m else None

    title   = meta("og:title") or meta("twitter:title") or ""
    desc    = meta("og:description") or meta("twitter:description") or ""
    address = title.split("|")[0].strip() if "|" in title else None

    price_m = re.search(r"\$([0-9]{2,3}(?:,[0-9]{3})+)", desc or html[:5000])
    price   = _safe_float(price_m.group(1)) if price_m else None
    beds_m  = re.search(r"(\d+)\s*bed", desc or "", re.I)
    baths_m = re.search(r"(\d+(?:\.\d)?)\s*bath", desc or "", re.I)
    sqft_m  = re.search(r"([\d,]+)\s*sq\.?\s*ft", desc or "", re.I)
    zip_m   = re.search(r"-(\d{5})/", listing_url)
    state_m = re.search(r"redfin\.com/([A-Z]{2})/", listing_url)
    city_m  = re.search(r"redfin\.com/[A-Z]{2}/([^/]+)/", listing_url)

    if not price and not address:
        return None

    return {
        "mls_id":         None,
        "address":        address,
        "city":           city_m.group(1).replace("-", " ") if city_m else None,
        "state":          state_m.group(1) if state_m else None,
        "zip":            zip_m.group(1) if zip_m else None,
        "latitude":       None,
        "longitude":      None,
        "price":          price,
        "beds":           int(beds_m.group(1)) if beds_m else None,
        "baths":          float(baths_m.group(1)) if baths_m else None,
        "sqft":           sqft_m.group(1).replace(",", "") if sqft_m else None,
        "year_built":     None,
        "property_type":  None,
        "hoa_monthly":    None,
        "days_on_market": None,
        "neighborhood":   None,
        "lot_size":       None,
        "status":         "Active",
    }


# ── Favorites list scrape ──────────────────────────────────────────────────────

def fetch_favorites_urls(favorites_page_url):
    # type: (str) -> List[str]
    """
    Fetch the user's Redfin favorites list and return listing URLs.
    Tries the JSON API first, falls back to HTML scraping.
    """
    session = scraper._get_session()

    api_url = "https://www.redfin.com/stingray/api/user/favorites"
    try:
        resp = session.get(api_url, params={"v": 1}, timeout=20)
        if resp.status_code == 200:
            text = resp.text
            if text.startswith("{}&&"):
                text = text[4:]
            data  = json.loads(text)
            homes = (data.get("payload") or {}).get("homes") or []
            urls  = []
            for h in homes:
                url = h.get("url") or h.get("listingUrl") or h.get("propertyUrl")
                if url:
                    if not url.startswith("http"):
                        url = "https://www.redfin.com" + url
                    urls.append(url)
            if urls:
                print("  Found {} favorites via API".format(len(urls)))
                return urls
            print("  Favorites API returned 0 homes — trying page scrape...")
    except Exception as e:
        print("  Favorites API error: {}".format(e))

    try:
        resp = session.get(favorites_page_url, timeout=20)
        if resp.status_code != 200:
            print("  HTTP {} fetching favorites page".format(resp.status_code))
            return []
        matches = re.findall(
            r'"(https://www\.redfin\.com/[A-Z]{2}/[^"]+/home/\d+)"', resp.text)
        rel_matches = re.findall(r'"(/[A-Z]{2}/[^"]+/home/\d+)"', resp.text)
        urls = list(dict.fromkeys(
            matches + ["https://www.redfin.com" + u for u in rel_matches]
        ))
        print("  Found {} favorites via page scrape".format(len(urls)))
        return urls
    except Exception as e:
        print("  Page scrape error: {}".format(e))
        return []


# ── CSV ingest ────────────────────────────────────────────────────────────────

def fetch_from_csv(csv_path):
    # type: (str) -> List[Dict]
    """
    Parse a Redfin favorites CSV export and return a list of normalized
    property dicts ready for score_property() / upsert_sale().
    Skips past sales and rentals — only includes active/pre-market MLS listings.
    """
    rows = []
    url_col = None

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            sale_type = (raw.get("SALE TYPE") or "").strip()
            status    = (raw.get("STATUS") or "").strip()

            # Skip past sales and rentals — they can't be purchased at list price
            if sale_type in ("PAST SALE", "RENTAL"):
                continue

            # Find the URL column (header name is very long in the export)
            if url_col is None:
                url_col = next(
                    (k for k in raw if k.upper().startswith("URL")), None
                )

            listing_url = (raw.get(url_col) or "").strip() if url_col else ""

            def _v(key, default=None):
                val = (raw.get(key) or "").strip()
                return val if val else default

            price    = _safe_float(_v("PRICE"))
            sqft     = _safe_float(_v("SQUARE FEET"))
            lot_raw  = _safe_float(_v("LOT SIZE"))
            hoa      = _safe_float(_v("HOA/MONTH"))
            beds_raw = _v("BEDS")
            baths_raw= _v("BATHS")
            yr_raw   = _v("YEAR BUILT")
            dom_raw  = _v("DAYS ON MARKET")
            lat_raw  = _v("LATITUDE")
            lng_raw  = _v("LONGITUDE")
            mls_id   = _v("MLS#")

            try:
                beds = int(float(beds_raw)) if beds_raw else None
            except (ValueError, TypeError):
                beds = None
            try:
                baths = float(baths_raw) if baths_raw else None
            except (ValueError, TypeError):
                baths = None
            try:
                year_built = int(float(yr_raw)) if yr_raw else None
            except (ValueError, TypeError):
                year_built = None
            try:
                dom = int(float(dom_raw)) if dom_raw else None
            except (ValueError, TypeError):
                dom = None
            try:
                lat = float(lat_raw) if lat_raw else None
            except (ValueError, TypeError):
                lat = None
            try:
                lng = float(lng_raw) if lng_raw else None
            except (ValueError, TypeError):
                lng = None

            if not mls_id and listing_url:
                slug   = listing_url.rstrip("/").split("/")[-1]
                mls_id = "url_{}".format(slug)

            address = _v("ADDRESS")
            city    = _v("CITY")
            state   = _v("STATE OR PROVINCE")
            zip_    = _v("ZIP OR POSTAL CODE")

            row = {
                "mls_id":         mls_id,
                "address":        address,
                "city":           city,
                "state":          state,
                "zip":            zip_,
                "latitude":       lat,
                "longitude":      lng,
                "price":          price or None,
                "beds":           beds,
                "baths":          baths,
                "sqft":           sqft or None,
                "year_built":     year_built,
                "property_type":  _v("PROPERTY TYPE"),
                "hoa_monthly":    hoa or None,
                "days_on_market": dom,
                "neighborhood":   _v("LOCATION"),
                "lot_size":       lot_raw or None,
                "status":         status or "Active",
                "listing_url":    listing_url,
                "area_label":     "favorites",
                "scraped_at":     datetime.utcnow().isoformat(),
                "price_per_sqft": round(price / sqft, 2) if price and sqft else None,
            }
            rows.append(row)

    print("  Loaded {} active listings from CSV (skipped past sales/rentals)".format(len(rows)))
    return rows


# ── Main ───────────────────────────────────────────────────────────────────────

def run(args):
    # type: (List[str]) -> None
    from config import OUTPUT
    import main as main_module

    conn     = database.connect(OUTPUT["db_path"])
    profiles = main_module.load_rent_profiles(conn)

    profile_count = sum(len(v) for v in profiles.values())
    if profile_count == 0:
        print("\n  ⚠️  No rent profiles in DB — properties saved but scored as no_rent_data.")
        print("  Run enrich_rentcast.py first for accurate scoring.\n")
    else:
        print("\n  ✓ Loaded {} rent profiles ({} ZIPs)".format(profile_count, len(profiles)))

    urls          = []
    favorites_url = None
    csv_path      = None
    i = 0
    while i < len(args):
        if args[i] == "--favorites" and i + 1 < len(args):
            favorites_url = args[i + 1]
            i += 2
        elif args[i] == "--csv" and i + 1 < len(args):
            csv_path = args[i + 1]
            i += 2
        elif args[i].startswith("http"):
            urls.append(args[i])
            i += 1
        else:
            i += 1

    # ── CSV fast-path: no scraping needed ─────────────────────────────────────
    if csv_path:
        import os
        if not os.path.isfile(csv_path):
            print("  CSV file not found: {}".format(csv_path))
            conn.close()
            return

        print("\n  Importing favorites from CSV: {}".format(csv_path))
        csv_rows = fetch_from_csv(csv_path)

        saved = skipped = 0
        tier_counts = {"immediately_rentable": 0, "rentable_1_2_years": 0,
                       "high_risk": 0, "no_rent_data": 0}
        icons = {"immediately_rentable": "✅", "rentable_1_2_years": "🟡",
                 "high_risk": "🔴", "no_rent_data": "⬜"}

        print("\n  Scoring {} properties...\n".format(len(csv_rows)))
        for row in csv_rows:
            if not row.get("price"):
                skipped += 1
                continue
            row  = main_module.score_property(row, profiles)
            database.upsert_sale(conn, row)

            tier = row.get("tier", "no_rent_data")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            saved += 1

            addr  = row.get("address") or ""
            price = row.get("price")
            rent  = row.get("rent_estimate")
            piti  = row.get("monthly_piti")
            icon  = icons.get(tier, "?")

            if price and piti and rent:
                print("    {} {}  |  ${:,.0f}  PITI ${:,.0f}/mo  rent ~${:,.0f}/mo  [{}]".format(
                    icon, addr, price, piti, rent, tier))
            else:
                print("    {} {}  [{}]".format(icon, addr, tier))

        conn.commit()
        database.export_csvs(conn, OUTPUT["csv_dir"])
        conn.close()

        print("\n" + "=" * 55)
        print("  Saved: {}  |  Skipped (no price): {}".format(saved, skipped))
        for tier, count in tier_counts.items():
            if count:
                print("  {} {:<25} {:>3}".format(icons.get(tier, ""), tier, count))
        print("=" * 55 + "\n")
        return

    if favorites_url:
        print("\n  Fetching favorites from: {}".format(favorites_url))
        fav_urls = fetch_favorites_urls(favorites_url)
        urls     = list(dict.fromkeys(fav_urls + urls))

    if not urls:
        print("  No URLs to process.")
        print("  Usage: python3 favorites.py [--csv <file>] [--favorites <url>] [url1 ...]")
        conn.close()
        return

    print("\n  Processing {} propert{}...\n".format(
        len(urls), "y" if len(urls) == 1 else "ies"))

    tier_counts = {"immediately_rentable": 0, "rentable_1_2_years": 0,
                   "high_risk": 0, "no_rent_data": 0}
    saved = skipped = 0
    icons = {"immediately_rentable": "✅", "rentable_1_2_years": "🟡",
             "high_risk": "🔴", "no_rent_data": "⬜"}

    for url in urls:
        row = fetch_property_by_url(url)
        if not row:
            skipped += 1
            continue

        row  = main_module.score_property(row, profiles)
        database.upsert_sale(conn, row)

        tier = row.get("tier", "no_rent_data")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        saved += 1

        addr  = row.get("address") or url
        price = row.get("price")
        rent  = row.get("rent_estimate")
        piti  = row.get("monthly_piti")
        icon  = icons.get(tier, "?")

        if price and piti and rent:
            print("    {} {}  |  ${:,.0f}  PITI ${:,.0f}/mo  rent ~${:,.0f}/mo  [{}]".format(
                icon, addr, price, piti, rent, tier))
        else:
            print("    {} {}  [{}]".format(icon, addr, tier))

        time.sleep(0.75)

    conn.commit()
    database.export_csvs(conn, OUTPUT["csv_dir"])
    conn.close()

    print("\n" + "=" * 55)
    print("  Saved: {}  |  Skipped: {}".format(saved, skipped))
    for tier, count in tier_counts.items():
        if count:
            print("  {} {:<25} {:>3}".format(icons.get(tier, ""), tier, count))
    print("=" * 55 + "\n")


if __name__ == "__main__":
    run(sys.argv[1:])
