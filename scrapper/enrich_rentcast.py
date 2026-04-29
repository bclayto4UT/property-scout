"""
enrich_rentcast.py — Fills rent_estimate for every property using RentCast.

KEY MANAGEMENT & QUOTA SAFETY:
  - Uses two API keys (defined in config.py RENTCAST_KEYS), each with a 50-call/month limit.
  - Live usage is tracked in data/rentcast_usage.json (auto-created on first run).
  - Keys are used in order: key1 first, key2 only when key1 is exhausted.
  - The script REFUSES to start if the run would exceed the combined remaining budget.
  - On any 429 response, the script immediately switches to the next key rather than failing.
  - To reset usage at the start of a new billing month:
        python3 enrich_rentcast.py --reset-usage

SEARCH STRATEGY:
  - SEARCHES is now ZIP-level (region_type=2), so each area label is of the form
    "28277 Ballantyne". The ZIP is extracted from the label's first token.
  - Duplicate ZIPs across labels are deduplicated — one API call per unique ZIP.

Usage:
    python3 enrich_rentcast.py              # normal run
    python3 enrich_rentcast.py --reset-usage  # zero out usage counts for new month
    python3 enrich_rentcast.py --dry-run    # show call plan and quota status, don't fetch
"""

import os
import sys
import json
import time
import sqlite3
import requests
import csv
from datetime import datetime
from typing import Optional
from config import OUTPUT, FHA, MARKET, SEARCHES, RENTCAST_KEYS

RENTCAST_MARKET_URL = "https://api.rentcast.io/v1/markets"
USAGE_FILE = os.path.join(os.path.dirname(OUTPUT["db_path"]), "rentcast_usage.json")


# ══════════════════════════════════════════════════════════════════════════════
# Usage tracking
# ══════════════════════════════════════════════════════════════════════════════

def _load_usage() -> dict:
    """
    Load usage from the JSON file. If the file doesn't exist yet, seed it from
    the used_so_far values in config.py RENTCAST_KEYS (the starting baseline).
    """
    if os.path.exists(USAGE_FILE):
        with open(USAGE_FILE) as f:
            return json.load(f)

    # First run — seed from config baselines
    data = {
        k["label"]: {"used": k["used_so_far"], "limit": k["limit"]}
        for k in RENTCAST_KEYS
    }
    _save_usage(data)
    return data


def _save_usage(data: dict):
    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _reset_usage():
    data = {k["label"]: {"used": 0, "limit": k["limit"]} for k in RENTCAST_KEYS}
    _save_usage(data)
    print("\n✅ Usage reset. All keys are back to 0/50 for the new billing month.\n")
    for k in RENTCAST_KEYS:
        print(f"   {k['label']}: 0 / {k['limit']}")
    print()


def _print_usage(usage: dict):
    print("\n  📊 RentCast API quota status:")
    total_remaining = 0
    for k in RENTCAST_KEYS:
        label   = k["label"]
        info    = usage.get(label, {"used": 0, "limit": k["limit"]})
        used    = info["used"]
        limit   = info["limit"]
        remain  = limit - used
        total_remaining += max(0, remain)
        bar_filled = int((used / limit) * 20)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        status = "⚠️  LOW" if remain <= 5 else ("✅" if remain > 15 else "🟡")
        print(f"   {label:<20}  [{bar}]  {used:>2}/{limit}  ({remain} remaining)  {status}")
    print(f"   {'TOTAL':20}  {' ' * 22}  {total_remaining} calls remaining across both keys")
    return total_remaining


# ══════════════════════════════════════════════════════════════════════════════
# Key pool — rotates automatically when the active key runs out
# ══════════════════════════════════════════════════════════════════════════════

class KeyPool:
    def __init__(self, usage: dict):
        self.usage       = usage
        self.keys        = RENTCAST_KEYS[:]
        self.idx         = 0          # which key we're currently on
        self._advance_to_usable()

    def _advance_to_usable(self):
        """Skip forward to the first key that still has quota."""
        while self.idx < len(self.keys):
            k     = self.keys[self.idx]
            info  = self.usage.get(k["label"], {"used": 0, "limit": k["limit"]})
            if info["used"] < info["limit"]:
                return
            self.idx += 1

    @property
    def active_key(self) -> Optional[str]:
        if self.idx >= len(self.keys):
            return None
        return self.keys[self.idx]["key"]

    @property
    def active_label(self) -> Optional[str]:
        if self.idx >= len(self.keys):
            return None
        return self.keys[self.idx]["label"]

    def remaining_on_active(self) -> int:
        if self.idx >= len(self.keys):
            return 0
        k    = self.keys[self.idx]
        info = self.usage.get(k["label"], {"used": 0, "limit": k["limit"]})
        return k["limit"] - info["used"]

    def total_remaining(self) -> int:
        total = 0
        for k in self.keys:
            info   = self.usage.get(k["label"], {"used": 0, "limit": k["limit"]})
            total += max(0, k["limit"] - info["used"])
        return total

    def record_call(self):
        """Increment usage for the active key and persist."""
        if self.idx >= len(self.keys):
            return
        label = self.keys[self.idx]["label"]
        self.usage[label]["used"] += 1
        _save_usage(self.usage)

    def rotate(self) -> bool:
        """Move to the next key. Returns True if a new usable key was found."""
        self.idx += 1
        self._advance_to_usable()
        return self.idx < len(self.keys)


# ══════════════════════════════════════════════════════════════════════════════
# ZIP helpers
# ══════════════════════════════════════════════════════════════════════════════

def _zip_from_area(area: dict) -> str:
    label       = area.get("label", "")
    first_token = label.split()[0] if label else ""
    if first_token.isdigit() and len(first_token) == 5:
        return first_token
    return area.get("region_id", "")


# ══════════════════════════════════════════════════════════════════════════════
# RentCast fetch
# ══════════════════════════════════════════════════════════════════════════════

def fetch_market_stats(zip_code: str, pool: KeyPool) -> dict:
    """
    Fetch rental market stats for a single ZIP. Rotates to the next key on 429.
    Returns {beds(int): {median, low, high, count}} or {} on failure.
    """
    if pool.active_key is None:
        print("✗ All API keys exhausted — cannot fetch.")
        return {}

    params  = {"zipCode": zip_code, "dataType": "All", "historyRange": 1}
    headers = {"X-Api-Key": pool.active_key, "Accept": "application/json"}

    try:
        resp = requests.get(RENTCAST_MARKET_URL, params=params,
                            headers=headers, timeout=15)

        if resp.status_code == 200:
            pool.record_call()
            dbb = resp.json().get("rentalData", {}).get("dataByBedrooms", [])
            if not dbb:
                return {}
            result = {}
            for seg in dbb:
                beds   = seg.get("bedrooms")
                median = seg.get("medianRent") or seg.get("averageRent")
                if beds is not None and median:
                    result[int(beds)] = {
                        "median": round(median, 2),
                        "low":    round(seg.get("minRent", median * 0.9), 2),
                        "high":   round(seg.get("maxRent", median * 1.1), 2),
                        "count":  seg.get("totalListings", 0),
                    }
            return result

        elif resp.status_code == 429:
            print(f"\n  ⚠️  Rate limit hit on {pool.active_label} — rotating key...")
            # Mark current key as fully used so it won't be retried
            label = pool.active_label
            pool.usage[label]["used"] = pool.usage[label].get("limit", 50)
            _save_usage(pool.usage)
            if pool.rotate():
                print(f"  → Switched to {pool.active_label}")
                return fetch_market_stats(zip_code, pool)   # retry with new key
            else:
                print("  ✗ No more keys available.")
                return {}

        elif resp.status_code == 401:
            print(f"\n  ✗ Invalid API key: {pool.active_label}")
            if pool.rotate():
                return fetch_market_stats(zip_code, pool)
            return {}

        elif resp.status_code == 404:
            pool.record_call()   # 404 still counts as a call
            return {}

        else:
            pool.record_call()
            print(f"HTTP {resp.status_code}: {resp.text[:80]}")
            return {}

    except requests.RequestException as e:
        print(f"request error: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# Mortgage + scoring (duplicated from main pipeline for standalone use)
# ══════════════════════════════════════════════════════════════════════════════

def safe_float(val, default=0.0):
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return default


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def calc_fha_mortgage(price: float) -> dict:
    if not price or price <= 0:
        return {}
    dp_pct       = FHA["down_payment_pct"] / 100
    ufmip_pct    = FHA["upfront_mip_pct"] / 100
    annual_mip   = FHA["annual_mip_pct"] / 100
    rate_monthly = (FHA["interest_rate_pct"] / 100) / 12
    n            = FHA["loan_term_months"]
    limit        = FHA["county_loan_limit"]
    tax_rate     = MARKET["property_tax_rate_pct"] / 100
    ins_rate     = MARKET["insurance_rate_pct"] / 100

    down_payment = round(price * dp_pct, 2)
    base_loan    = price - down_payment
    ufmip        = round(base_loan * ufmip_pct, 2)
    total_loan   = base_loan + ufmip
    if rate_monthly > 0:
        monthly_pi = total_loan * (rate_monthly * (1 + rate_monthly) ** n) \
                     / ((1 + rate_monthly) ** n - 1)
    else:
        monthly_pi = total_loan / n
    monthly_mip       = round((total_loan * annual_mip) / 12, 2)
    monthly_tax       = round((price * tax_rate) / 12, 2)
    monthly_insurance = round((price * ins_rate) / 12, 2)
    monthly_piti      = round(monthly_pi + monthly_mip + monthly_tax + monthly_insurance, 2)
    return {
        "down_payment": round(down_payment, 2), "base_loan": round(base_loan, 2),
        "ufmip": ufmip, "total_loan": round(total_loan, 2),
        "monthly_pi": round(monthly_pi, 2), "monthly_mip": monthly_mip,
        "monthly_tax": monthly_tax, "monthly_insurance": monthly_insurance,
        "monthly_piti": monthly_piti,
        "exceeds_fha_limit": 1 if base_loan > limit else 0,
        "fha_rate_used": FHA["interest_rate_pct"],
    }


def classify(piti: float, rent: float) -> dict:
    if not rent or rent <= 0:
        return {"tier": "no_rent_data", "cash_flow_now": None,
                "break_even_year": None,
                "rent_at_1yr": None, "rent_at_2yr": None, "rent_at_5yr": None}
    growth        = MARKET["rent_growth_rate_pct"] / 100
    cash_flow_now = round(rent - piti, 2)
    rent_at       = {yr: round(rent * (1 + growth) ** yr, 2) for yr in (1, 2, 5)}
    break_even    = next((yr for yr in range(1, 31)
                          if rent * (1 + growth) ** yr >= piti), None)
    if cash_flow_now >= 0:
        tier = "immediately_rentable"
    elif break_even and break_even <= 2:
        tier = "rentable_1_2_years"
    else:
        tier = "high_risk"
    return {"tier": tier, "cash_flow_now": cash_flow_now,
            "break_even_year": break_even,
            "rent_at_1yr": rent_at[1], "rent_at_2yr": rent_at[2],
            "rent_at_5yr": rent_at[5]}


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def run(dry_run: bool = False):
    print("\n" + "=" * 60)
    print("  RentCast Enrichment")
    print("=" * 60)

    # ── Load usage and initialise key pool ────────────────────────────────────
    usage = _load_usage()
    pool  = KeyPool(usage)

    total_remaining = _print_usage(usage)
    print()

    if total_remaining == 0:
        print("✗ Both API keys are exhausted for this month.")
        print("  Run with --reset-usage on the 1st of next month.")
        sys.exit(1)

    # ── Build deduplicated call plan ──────────────────────────────────────────
    seen_zips   = {}
    call_plan   = []
    area_to_zip = {}

    for area in SEARCHES:
        label = area["label"]
        z     = _zip_from_area(area)
        if not z:
            print(f"  ⚠️  Could not determine ZIP for '{label}' — skipping")
            continue
        area_to_zip[label] = z
        if z not in seen_zips:
            seen_zips[z] = label
            call_plan.append((label, z))
        else:
            pass  # silently deduplicated

    calls_needed = len(call_plan)

    print(f"  Search areas : {len(SEARCHES)}")
    print(f"  Unique ZIPs  : {calls_needed}  (duplicates removed)")
    print(f"  Quota left   : {total_remaining} calls across both keys")

    # Show which key(s) will be used and how many from each
    key1_label    = RENTCAST_KEYS[0]["label"]
    key1_info     = usage.get(key1_label, {"used": 0, "limit": 50})
    key1_remain   = key1_info["limit"] - key1_info["used"]
    from_key1     = min(calls_needed, max(0, key1_remain))
    from_key2     = calls_needed - from_key1

    print(f"\n  Planned usage:")
    print(f"    {RENTCAST_KEYS[0]['label']:<20} {from_key1} calls  "
          f"({key1_info['used']} → {key1_info['used'] + from_key1} / {key1_info['limit']})")
    if from_key2 > 0:
        key2_label  = RENTCAST_KEYS[1]["label"]
        key2_info   = usage.get(key2_label, {"used": 0, "limit": 50})
        print(f"    {key2_label:<20} {from_key2} calls  "
              f"({key2_info['used']} → {key2_info['used'] + from_key2} / {key2_info['limit']})")

    if calls_needed > total_remaining:
        print(f"\n  ✗ ABORTED — need {calls_needed} calls but only {total_remaining} remain.")
        print("    Remove some ZIPs from SEARCHES or wait for next billing month.")
        sys.exit(1)

    if dry_run:
        print("\n  [dry-run] No API calls made. Exiting.")
        sys.exit(0)

    print()

    # ── Fetch ─────────────────────────────────────────────────────────────────
    zip_profiles  = {}
    area_profiles = {}

    for i, (label, zip_code) in enumerate(call_plan, 1):
        active_label = pool.active_label or "???"
        print(f"  [{i:>2}/{calls_needed}] ZIP {zip_code}  ({label})  "
              f"[key: {active_label}]  ", end="", flush=True)

        stats = fetch_market_stats(zip_code, pool)

        if stats:
            beds_str = "  ".join(
                f"{b}bd=${stats[b]['median']:,.0f}(n={stats[b]['count']})"
                for b in sorted(stats)
            )
            print(f"✓  {beds_str}")
            zip_profiles[zip_code] = stats
        else:
            print("✗  no data")

        time.sleep(0.4)

    # Map every area label to its profile
    for label, z in area_to_zip.items():
        if z in zip_profiles:
            area_profiles[label] = zip_profiles[z]

    if not area_profiles:
        print("\n✗ No profiles fetched — nothing to save.")
        sys.exit(1)

    print(f"\n  Areas with rent data: {len(area_profiles)}/{len(SEARCHES)}")

    # ── Print updated usage ───────────────────────────────────────────────────
    usage = _load_usage()   # reload to show final state
    _print_usage(usage)

    # ── Save profiles to DB ───────────────────────────────────────────────────
    conn = connect(OUTPUT["db_path"])
    print("\n  Saving rent profiles to DB...")
    for label, bed_map in area_profiles.items():
        zip_code = area_to_zip.get(label, "00000")
        for beds, rents in bed_map.items():
            conn.execute("""
                INSERT INTO rent_profiles (zip, beds, count, low_rent, median_rent,
                                           high_rent, avg_rent)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(zip, beds) DO UPDATE SET
                    count=excluded.count, low_rent=excluded.low_rent,
                    median_rent=excluded.median_rent, high_rent=excluded.high_rent,
                    avg_rent=excluded.avg_rent
            """, (zip_code, beds, rents["count"],
                  rents["low"], rents["median"], rents["high"], rents["median"]))
    conn.commit()

    # ── Re-score every property ───────────────────────────────────────────────
    print("  Re-scoring properties...")
    properties = conn.execute(
        "SELECT mls_id, price, beds, zip, area_label, monthly_piti "
        "FROM sale_properties"
    ).fetchall()

    tier_counts      = {"immediately_rentable": 0, "rentable_1_2_years": 0,
                        "high_risk": 0, "no_rent_data": 0}
    no_profile_areas = set()

    for prop in properties:
        area_label = prop["area_label"] or ""
        beds       = int(prop["beds"]) if prop["beds"] is not None else 3
        price      = safe_float(prop["price"])
        mort       = calc_fha_mortgage(price)
        piti       = mort.get("monthly_piti") or safe_float(prop["monthly_piti"])

        # Lookup priority: exact ZIP match → nearest bed count in same ZIP →
        # cross-ZIP fallback (nearest ZIP that has data for this bed count)
        profile     = area_profiles.get(area_label, {}).get(beds)
        rent_source = "rentcast_exact"

        if not profile:
            area_map = area_profiles.get(area_label, {})
            if area_map:
                best        = min(area_map, key=lambda b: abs(b - beds))
                profile     = area_map[best]
                rent_source = f"rentcast_fallback_{best}bd"

        if not profile:
            # Try to match by the raw ZIP stored on the property row
            prop_zip = (prop["zip"] or "").strip()
            if prop_zip in zip_profiles:
                pmap = zip_profiles[prop_zip]
                if beds in pmap:
                    profile     = pmap[beds]
                    rent_source = f"rentcast_zip_{prop_zip}"
                elif pmap:
                    best        = min(pmap, key=lambda b: abs(b - beds))
                    profile     = pmap[best]
                    rent_source = f"rentcast_zip_{prop_zip}_fallback_{best}bd"

        if not profile:
            for other_label, other_map in area_profiles.items():
                if beds in other_map:
                    profile     = other_map[beds]
                    rent_source = f"rentcast_xarea_{other_label}"
                    break

        if not profile:
            no_profile_areas.add(area_label)
            rent_est    = None
            rent_source = "no_data"
        else:
            rent_est = profile["median"]

        scoring = classify(piti, rent_est)
        tier    = scoring.get("tier", "no_rent_data")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

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
            scoring.get("cash_flow_now"), scoring.get("break_even_year"),
            scoring.get("rent_at_1yr"), scoring.get("rent_at_2yr"),
            scoring.get("rent_at_5yr"), tier,
            mort.get("down_payment"), mort.get("base_loan"), mort.get("ufmip"),
            mort.get("total_loan"), mort.get("monthly_pi"), mort.get("monthly_mip"),
            mort.get("monthly_tax"), mort.get("monthly_insurance"),
            piti, mort.get("exceeds_fha_limit"), mort.get("fha_rate_used"),
            prop["mls_id"],
        ))

    conn.commit()

    # ── Re-export CSVs ────────────────────────────────────────────────────────
    print("  Re-exporting CSVs...")
    out_dir = OUTPUT["csv_dir"]
    os.makedirs(out_dir, exist_ok=True)
    for table, filename in [("sale_properties", "sale_properties.csv"),
                             ("rent_profiles",   "rent_profiles.csv")]:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            continue
        path = os.path.join(out_dir, filename)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows([dict(r) for r in rows])
        print(f"    → {path}  ({len(rows)} rows)")

    conn.close()

    # ── Final summary ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Results")
    print("=" * 60)
    icons = {"immediately_rentable": "✅", "rentable_1_2_years": "🟡",
             "high_risk": "🔴", "no_rent_data": "⬜"}
    total = sum(tier_counts.values())
    for tier, count in tier_counts.items():
        pct = (count / total * 100) if total else 0
        print(f"  {icons.get(tier,'')} {tier:<25} {count:>4}  ({pct:.0f}%)")
    print(f"\n  Total re-scored : {total}")
    print(f"  API calls made  : {calls_needed} total  "
          f"({from_key1} key1, {max(0, calls_needed - from_key1)} key2)")
    if no_profile_areas:
        print(f"  ⚠️  No rent data for: {', '.join(sorted(no_profile_areas))}")
    print()


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--reset-usage" in args:
        _reset_usage()
        sys.exit(0)

    dry_run = "--dry-run" in args
    run(dry_run=dry_run)
