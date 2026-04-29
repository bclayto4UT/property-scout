"""
main.py — Scrapes Redfin for-sale listings and scores them against existing
rent profiles already in the database.

Usage:
    python3 main.py          # scrape + score using cached rent profiles
    python3 main.py --rescore  # skip scrape, just re-score existing properties

Rent profiles are NOT updated here. Run enrich_rentcast.py once a month to
refresh rent data. This script scores new listings against whatever profiles
are already in the DB — so new listings get scored immediately, for free.
"""

import time
import sys
from config import SEARCHES, SALE_PRICE_BANDS, PROPERTY_TYPES, OUTPUT
import scraper
import database
import mortgage
import sensitivity


def safe_float(val, default=0.0):
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return default


def load_rent_profiles(conn) -> dict:
    """
    Load rent profiles from DB into a dict for fast lookup:
        profiles[zip][beds] = {"median": X, "low": Y, "high": Z}
    """
    rows = conn.execute(
        "SELECT zip, beds, low_rent, median_rent, high_rent FROM rent_profiles"
    ).fetchall()
    profiles = {}
    for row in rows:
        zip_code = row["zip"]
        beds     = int(row["beds"]) if row["beds"] is not None else 0
        if zip_code not in profiles:
            profiles[zip_code] = {}
        profiles[zip_code][beds] = {
            "median": row["median_rent"],
            "low":    row["low_rent"],
            "high":   row["high_rent"],
        }
    return profiles


def lookup_rent(profiles: dict, zip_code: str, beds) -> tuple:
    """
    Look up rent estimate for a zip+beds combo.
    Falls back to nearest bed count in same zip if exact match missing.
    Returns (rent_estimate, rent_source).
    """
    if not zip_code or not profiles:
        return None, "no_data"

    try:
        beds = int(float(str(beds))) if beds is not None else 0
    except (ValueError, TypeError):
        beds = 0

    zip_data = profiles.get(zip_code, {})
    if not zip_data:
        return None, "no_data"

    if beds in zip_data:
        return zip_data[beds]["median"], "rentcast_exact"

    # Nearest bed count fallback
    closest = min(zip_data.keys(), key=lambda b: abs(b - beds))
    return zip_data[closest]["median"], f"rentcast_fallback_{closest}bd"


def score_property(sale: dict, profiles: dict) -> dict:
    """Compute FHA mortgage + rent score for a single property."""
    price    = safe_float(sale.get("price"))
    mort     = mortgage.calc_fha_mortgage(price)
    sale.update(mort)

    piti                  = sale.get("monthly_piti", 0) or 0
    rent_est, rent_source = lookup_rent(profiles, sale.get("zip"), sale.get("beds"))
    sale["rent_estimate"] = rent_est
    sale["rent_source"]   = rent_source

    classification = mortgage.classify(piti, rent_est or 0)
    sale.update(classification)
    return sale


def rescore_all(conn, profiles: dict) -> dict:
    """Re-score every property in the DB using current rent profiles."""
    properties = conn.execute(
        "SELECT mls_id, price, beds, zip FROM sale_properties"
    ).fetchall()

    tier_counts = {"immediately_rentable": 0, "rentable_1_2_years": 0,
                   "high_risk": 0, "no_rent_data": 0}

    for prop in properties:
        price    = safe_float(prop["price"])
        mort     = mortgage.calc_fha_mortgage(price)
        piti     = mort.get("monthly_piti", 0) or 0

        rent_est, rent_source = lookup_rent(profiles, prop["zip"], prop["beds"])
        classification        = mortgage.classify(piti, rent_est or 0)
        tier                  = classification.get("tier", "no_rent_data")
        tier_counts[tier]     = tier_counts.get(tier, 0) + 1

        conn.execute("""
            UPDATE sale_properties SET
                rent_estimate=?, rent_source=?, cash_flow_now=?,
                break_even_year=?, rent_at_1yr=?, rent_at_2yr=?, rent_at_5yr=?,
                tier=?, down_payment=?, base_loan=?, ufmip=?, total_loan=?,
                monthly_pi=?, monthly_mip=?, monthly_tax=?, monthly_insurance=?,
                monthly_piti=?, exceeds_fha_limit=?, fha_rate_used=?
            WHERE mls_id=?
        """, (
            rent_est, rent_source,
            classification.get("cash_flow_now"),
            classification.get("break_even_year"),
            classification.get("rent_at_1yr"),
            classification.get("rent_at_2yr"),
            classification.get("rent_at_5yr"),
            tier,
            mort.get("down_payment"), mort.get("base_loan"),
            mort.get("ufmip"), mort.get("total_loan"),
            mort.get("monthly_pi"), mort.get("monthly_mip"),
            mort.get("monthly_tax"), mort.get("monthly_insurance"),
            piti, mort.get("exceeds_fha_limit"), mort.get("fha_rate_used"),
            prop["mls_id"],
        ))

    conn.commit()
    return tier_counts


def run():
    rescore_only = "--rescore" in sys.argv

    print("\n" + "=" * 55)
    print("  Redfin Investment Property Scraper")
    print("=" * 55)

    conn     = database.connect(OUTPUT["db_path"])
    profiles = load_rent_profiles(conn)

    profile_count = sum(len(v) for v in profiles.values())
    if profile_count == 0:
        print("\n  ⚠️  No rent profiles in DB.")
        print("  Run enrich_rentcast.py first to populate rent data.")
        print("  Properties will be saved but scored as no_rent_data.\n")
    else:
        print(f"\n  ✓ Loaded {profile_count} rent profiles from DB "
              f"({len(profiles)} ZIPs) — no API calls needed")

    # ── Rescore-only mode ─────────────────────────────────────────────────────
    if rescore_only:
        print("\n  [rescore] Skipping scrape — re-scoring existing properties...")
        tier_counts = rescore_all(conn, profiles)
        database.export_csvs(conn, OUTPUT["csv_dir"])
        sensitivity.run(conn)
        conn.close()
        _print_summary(tier_counts, OUTPUT)
        return

    # ── Step 1: Skip Redfin rental scrape (RentCast handles rent estimates) ──
    print("\n[1/4] Skipping Redfin rental scrape (RentCast handles rent estimates).")
    print("[2/4] Skipping Redfin rent profile build (RentCast handles this).")

    # ── Step 2: Scrape for-sale listings ─────────────────────────────────────
    print("\n[3/4] Scraping for-sale listings...")

    tier_counts = {"immediately_rentable": 0, "rentable_1_2_years": 0,
                   "high_risk": 0, "no_rent_data": 0}

    for area in SEARCHES:
        label = area["label"]
        print(f"\n  Area: {label}")

        raw_sales = []
        for (min_p, max_p) in SALE_PRICE_BANDS:
            rows = scraper.fetch_for_sale(
                region_id=area["region_id"],
                region_type=area["region_type"],
                market=area["market"],
                min_price=min_p,
                max_price=max_p,
                property_types=PROPERTY_TYPES,
            )
            raw_sales.extend(rows)
            time.sleep(1.5)

        raw_sales = scraper.deduplicate(raw_sales)
        print(f"  {label}: {len(raw_sales)} unique for-sale listings")

        for raw in raw_sales:
            sale = database.normalize_sale(raw, label)
            sale = score_property(sale, profiles)

            tier = sale.get("tier", "no_rent_data")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

            database.upsert_sale(conn, sale)

    conn.commit()

    # ── Step 3: Export ────────────────────────────────────────────────────────
    print("\n[4/4] Exporting CSVs...")
    database.export_csvs(conn, OUTPUT["csv_dir"])

    sensitivity.run(conn)
    conn.close()

    _print_summary(tier_counts, OUTPUT)


def _print_summary(tier_counts: dict, output: dict):
    print("\n" + "=" * 55)
    print("  Results Summary")
    print("=" * 55)
    icons = {
        "immediately_rentable": "✅",
        "rentable_1_2_years":   "🟡",
        "high_risk":            "🔴",
        "no_rent_data":         "⬜",
    }
    total = sum(tier_counts.values())
    for tier, count in tier_counts.items():
        pct = (count / total * 100) if total else 0
        print(f"  {icons.get(tier,'')} {tier:<25} {count:>4}  ({pct:.0f}%)")
    print(f"\n  Total properties scored: {total}")
    print(f"  Database:  {output['db_path']}")
    print(f"  CSV files: {output['csv_dir']}/")
    print()
    if tier_counts.get("no_rent_data", 0) == total and total > 0:
        print("  ⚠️  All properties are no_rent_data.")
        print("  Run:  python3 enrich_rentcast.py")
        print("        to populate rent estimates (once/month).\n")


if __name__ == "__main__":
    run()
