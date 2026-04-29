"""
lookup_zip_region_ids.py
━━━━━━━━━━━━━━━━━━━━━━━━
For each ZIP: navigate to redfin.com, type the ZIP, press Enter, wait for the
search results page to load, then extract the region_id from the URL.

Outputs:
  zip_region_map.json   — raw results for debugging
  searches_block.py     — ready-to-paste SEARCHES list for config.py

Usage:
    python3 lookup_zip_region_ids.py
"""

import json
import re
import time
from playwright.sync_api import sync_playwright
from typing import Optional

TARGET_ZIPS = [
    ("28210", "28210 Charlotte SW"),
    ("28211", "28211 Charlotte SE"),
    ("28212", "28212 Charlotte E"),
    ("28213", "28213 Charlotte NE"),
    ("28214", "28214 Charlotte NW"),
    ("28215", "28215 Charlotte NE2"),
    ("28216", "28216 Charlotte N"),
    ("28217", "28217 Charlotte S"),
    ("28226", "28226 Charlotte S2"),
    ("28227", "28227 Mint Hill"),
    ("28269", "28269 Charlotte N2"),
    ("28270", "28270 Charlotte SE2"),
    ("28277", "28277 Ballantyne"),
    ("28278", "28278 Charlotte SW2"),
    ("28134", "28134 Pineville"),
    ("28104", "28104 Matthews"),
    ("28105", "28105 Matthews E"),
    ("28025", "28025 Concord"),
    ("28027", "28027 Concord NE"),
    ("28075", "28075 Harrisburg"),
    ("28078", "28078 Huntersville"),
    ("28031", "28031 Cornelius"),
    ("28036", "28036 Davidson"),
    ("28012", "28012 Belmont"),
    ("28052", "28052 Gastonia"),
    ("28054", "28054 Gastonia E"),
    ("28056", "28056 Gastonia N"),
    ("29708", "29708 Fort Mill Tega Cay SC"),
    ("29707", "29707 Indian Land SC"),
    ("29710", "29710 Lake Wylie SC"),
    ("29730", "29730 Rock Hill SC"),
    ("29732", "29732 Rock Hill N SC"),
    ("29720", "29720 Lancaster SC"),
]

# Redfin search results URLs look like:
#   /zipcode/28210/filter/...   → region_id in the page's data-rf or URL path
#   The gis-filter XHR in the URL contains region_id as a param, but the
#   simplest approach is to read it from window.__reactRedfinServerState or
#   the canonical URL structure after navigation.
#
# Fallback: parse region_id from the URL pattern /zipcode/NNNNN or from
# the JSON blob Redfin embeds in the page as window.__serverData.


def extract_from_url(url: str) -> Optional[str]:
    """Try to pull region_id from a Redfin search results URL."""
    # e.g. /zipcode/28210 — region_id is embedded in server data, not the URL
    # e.g. filter URLs like region_id=XXXXX
    m = re.search(r'[?&]region_id=(\d+)', url)
    if m:
        return m.group(1)
    return None


def extract_from_page(page) -> Optional[str]:
    """
    Pull region_id from the JSON blob Redfin embeds in the page.
    Redfin sets window.__reactRedfinServerState which contains regionId.
    """
    try:
        region_id = page.evaluate("""
            () => {
                // Try the server state blob
                try {
                    const s = window.__reactRedfinServerState;
                    if (s) {
                        const str = JSON.stringify(s);
                        const m = str.match(/"regionId":(\d+)/);
                        if (m) return m[1];
                    }
                } catch(e) {}

                // Try scanning all script tags for regionId
                for (const el of document.querySelectorAll('script')) {
                    const m = (el.textContent || '').match(/"regionId"\s*:\s*(\d+)/);
                    if (m) return m[1];
                }

                // Try the canonical URL meta tag
                const canonical = document.querySelector('link[rel=canonical]');
                if (canonical) {
                    const m = canonical.href.match(/region_id=(\d+)/);
                    if (m) return m[1];
                }

                return null;
            }
        """)
        return str(region_id) if region_id else None
    except Exception:
        return None


def find_search_box(page):
    for selector in [
        "input[data-rf-test-id='search-box-input']",
        "input#search-box-input",
        "input[placeholder*='city']",
        "input[placeholder*='ZIP']",
        "input[placeholder*='Enter']",
        "input[type='search']",
        "input.search-input",
    ]:
        loc = page.locator(selector).first
        try:
            if loc.is_visible(timeout=2_000):
                return loc
        except Exception:
            continue
    raise Exception("No search box found")


def lookup_zip(browser, zip_code: str) -> dict:
    page = browser.new_page()
    try:
        # 1. Load the homepage
        page.goto("https://www.redfin.com", wait_until="domcontentloaded", timeout=30_000)
        time.sleep(1.5)

        # 2. Dismiss modals if present
        for sel in ["button[data-rf-test-id='modal-close-button']",
                    "button:text('Accept')", "button:text('No thanks')"]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=500):
                    btn.click()
            except Exception:
                pass

        # 3. Type ZIP and press Enter
        box = find_search_box(page)
        box.click()
        box.fill(zip_code)
        time.sleep(0.3)

        # 4. Wait for navigation to the results page
        with page.expect_navigation(wait_until="domcontentloaded", timeout=15_000):
            box.press("Enter")

        time.sleep(1.5)  # let JS populate server state

        # 5. Try to get region_id from URL first, then page data
        current_url = page.url
        print(f"       → landed: {current_url[:80]}", flush=True)

        region_id = extract_from_url(current_url) or extract_from_page(page)

        # 6. Also grab the display name from the page title
        try:
            display_name = page.title().split("|")[0].strip()
        except Exception:
            display_name = ""

        if region_id:
            return {
                "zip": zip_code,
                "region_id": region_id,
                "display_name": display_name,
                "status": "ok",
            }
        else:
            return {
                "zip": zip_code,
                "region_id": None,
                "display_name": display_name,
                "status": "not_found",
            }

    except Exception as e:
        return {
            "zip": zip_code, "region_id": None,
            "display_name": "", "status": f"error:{e}",
        }
    finally:
        page.close()


def lookup_all(zip_codes: list) -> list:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )

        for zip_code in zip_codes:
            result = lookup_zip(context, zip_code)
            icon = (
                "✓" if result["status"] == "ok"
                else ("⚠" if result["status"] == "fallback_city" else "✗")
            )
            print(
                f"  {icon} {zip_code}  "
                f"region_id={result.get('region_id') or 'NOT FOUND':>8}  "
                f"{result.get('display_name', '')[:45]:<45}  [{result['status']}]"
            )
            results.append(result)
            time.sleep(0.5)

        browser.close()
    return results


def build_searches_block(results: list, labels: dict) -> str:
    lines = [
        "# Auto-generated by lookup_zip_region_ids.py",
        "# Paste this block into config.py to replace SEARCHES.",
        "",
        "SEARCHES = [",
    ]
    ok     = [r for r in results if r.get("region_id")]
    failed = [r for r in results if not r.get("region_id")]
    nc     = [r for r in ok if r["zip"].startswith("28") or r["zip"].startswith("27")]
    sc     = [r for r in ok if r["zip"].startswith("29")]

    def entry(r):
        label = labels.get(r["zip"], r.get("display_name") or r["zip"])
        flag  = "  # ⚠ city-level fallback" if r["status"] == "fallback_city" else ""
        return (
            f'    {{"label": "{label:<32}", '
            f'"region_id": "{r["region_id"]:<6}", '
            f'"region_type": "2", '
            f'"market": "charlotte"}},{flag}'
        )

    if nc:
        lines.append("    # ── North Carolina ──────────────────────────────────")
        lines.extend(entry(r) for r in nc)
    if sc:
        lines.append("    # ── South Carolina ──────────────────────────────────")
        lines.extend(entry(r) for r in sc)

    lines.append("]")
    if failed:
        lines += [
            "",
            "# ── ZIPs not resolved — manual lookup needed ─────────────────────",
        ]
        for r in failed:
            label = labels.get(r["zip"], r["zip"])
            lines.append(f"#   {r['zip']}  ({label})  status={r['status']}")

    return "\n".join(lines) + "\n"


def main():
    labels    = {z: lbl for z, lbl in TARGET_ZIPS}
    zip_codes = [z for z, _ in TARGET_ZIPS]

    print(f"\nLooking up {len(zip_codes)} ZIP codes via Redfin...\n")
    results = lookup_all(zip_codes)

    with open("zip_region_map.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n✓  zip_region_map.json")

    block = build_searches_block(results, labels)
    with open("searches_block.py", "w") as f:
        f.write(block)
    print("✓  searches_block.py")

    ok  = sum(1 for r in results if r.get("region_id") and r["status"] == "ok")
    bad = sum(1 for r in results if not r.get("region_id"))
    print(f"\n  ✓ Resolved:   {ok}")
    print(f"  ✗ Not found:  {bad}")
    if bad:
        print("  → See searches_block.py comments for manual steps.")
    print()


if __name__ == "__main__":
    main()
