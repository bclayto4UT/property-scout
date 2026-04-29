"""
sensitivity.py — Recalculates mortgage, cash flow, and tier for each property
across multiple interest rate scenarios. Outputs a sensitivity table to CSV
and SQLite so you can sort/filter in Sheets or DB Browser.
"""

import csv
import os
import sqlite3
from mortgage import calc_fha_mortgage, classify
from config import FHA, OUTPUT

# ── Rate scenarios to model ────────────────────────────────────────────────────
# Add or remove scenarios here. Label is used as a column prefix in the output.
RATE_SCENARIOS = [
    {"label": "current",  "rate": FHA["interest_rate_pct"]},
    {"label": "rate_6_5", "rate": 6.5},
    {"label": "rate_6_0", "rate": 6.0},
    {"label": "rate_5_5", "rate": 5.5},
    {"label": "rate_5_0", "rate": 5.0},
]


def _calc_at_rate(price: float, rent_estimate: float, rate: float) -> dict:
    """Run mortgage calc and classify at a specific interest rate."""
    original_rate = FHA["interest_rate_pct"]
    FHA["interest_rate_pct"] = rate
    mort = calc_fha_mortgage(price)
    result = classify(mort["monthly_piti"], rent_estimate)
    FHA["interest_rate_pct"] = original_rate  # restore

    return {
        "piti":           mort["monthly_piti"],
        "cash_flow":      result["cash_flow_now"],
        "break_even_yr":  result["break_even_year"],
        "tier":           result["tier"],
    }


def build_sensitivity_table(conn: sqlite3.Connection) -> list[dict]:
    """
    Pull all scored sale properties from DB, recalculate across all rate
    scenarios, and return as a flat list of dicts ready to write to CSV.
    """
    rows = conn.execute("""
        SELECT mls_id, address, city, state, zip, price, beds, baths, sqft,
               price_per_sqft, property_type, hoa_monthly, days_on_market,
               rent_estimate, rent_source, listing_url, area_label,
               monthly_piti, tier, cash_flow_now, break_even_year
        FROM sale_properties
        WHERE price IS NOT NULL AND price > 0
        ORDER BY price ASC
    """).fetchall()

    if not rows:
        return []

    table = []
    for row in rows:
        price       = float(row["price"] or 0)
        rent_est    = float(row["rent_estimate"] or 0)

        record = {
            "mls_id":         row["mls_id"],
            "address":        row["address"],
            "city":           row["city"],
            "state":          row["state"],
            "zip":            row["zip"],
            "area":           row["area_label"],
            "price":          price,
            "beds":           row["beds"],
            "baths":          row["baths"],
            "sqft":           row["sqft"],
            "price_per_sqft": row["price_per_sqft"],
            "property_type":  row["property_type"],
            "hoa_monthly":    row["hoa_monthly"],
            "days_on_market": row["days_on_market"],
            "rent_estimate":  rent_est,
            "rent_source":    row["rent_source"],
            "listing_url":    row["listing_url"],
        }

        # Add columns for each scenario
        for scenario in RATE_SCENARIOS:
            if price > 0 and rent_est > 0:
                s = _calc_at_rate(price, rent_est, scenario["rate"])
            else:
                s = {"piti": None, "cash_flow": None, "break_even_yr": None, "tier": "no_rent_data"}

            prefix = scenario["label"]
            record[f"{prefix}_rate"]         = scenario["rate"]
            record[f"{prefix}_piti"]         = s["piti"]
            record[f"{prefix}_cash_flow"]    = s["cash_flow"]
            record[f"{prefix}_break_even"]   = s["break_even_yr"]
            record[f"{prefix}_tier"]         = s["tier"]

        table.append(record)

    return table


def export_sensitivity_csv(table: list[dict], out_dir: str):
    """Write the sensitivity table to CSV."""
    if not table:
        print("  (no properties to export)")
        return

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "sensitivity_table.csv")

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=table[0].keys())
        writer.writeheader()
        writer.writerows(table)

    print(f"  → {path}  ({len(table)} properties × {len(RATE_SCENARIOS)} rate scenarios)")


def save_sensitivity_db(conn: sqlite3.Connection, table: list[dict]):
    """Save sensitivity table to its own SQLite table for easy querying."""
    if not table:
        return

    # Build CREATE TABLE dynamically from the first row's keys
    sample = table[0]
    col_defs = []
    for k in sample.keys():
        if k == "mls_id":
            col_defs.append("mls_id TEXT PRIMARY KEY")
        elif any(k.endswith(s) for s in ("_rate", "_piti", "_cash_flow", "price", "sqft",
                                          "price_per_sqft", "hoa_monthly", "rent_estimate")):
            col_defs.append(f"{k} REAL")
        elif any(k.endswith(s) for s in ("beds", "days_on_market", "_break_even")):
            col_defs.append(f"{k} INTEGER")
        else:
            col_defs.append(f"{k} TEXT")

    conn.execute(f"DROP TABLE IF EXISTS sensitivity_table")
    conn.execute(f"CREATE TABLE sensitivity_table ({', '.join(col_defs)})")

    for row in table:
        keys = list(row.keys())
        placeholders = ", ".join("?" * len(keys))
        conn.execute(
            f"INSERT INTO sensitivity_table ({', '.join(keys)}) VALUES ({placeholders})",
            list(row.values())
        )

    conn.commit()
    print(f"  → SQLite table 'sensitivity_table' ({len(table)} rows)")


def print_summary(table: list[dict]):
    """Print a readable summary of tier counts across scenarios to the terminal."""
    if not table:
        return

    tier_order = ["immediately_rentable", "rentable_1_2_years", "high_risk", "no_rent_data"]
    tier_icons = {
        "immediately_rentable": "✅",
        "rentable_1_2_years":   "🟡",
        "high_risk":            "🔴",
        "no_rent_data":         "⬜",
    }

    print(f"\n  {'Tier':<25}", end="")
    for s in RATE_SCENARIOS:
        label = f"{s['rate']}%"
        print(f"  {label:>8}", end="")
    print()
    print("  " + "-" * (25 + 10 * len(RATE_SCENARIOS)))

    for tier in tier_order:
        print(f"  {tier_icons.get(tier,'')} {tier:<23}", end="")
        for scenario in RATE_SCENARIOS:
            prefix = scenario["label"]
            count = sum(1 for r in table if r.get(f"{prefix}_tier") == tier)
            print(f"  {count:>8}", end="")
        print()

    # Also print the best cash flow at each rate
    print(f"\n  Best cash flow at each rate (top property):")
    for scenario in RATE_SCENARIOS:
        prefix = scenario["label"]
        best = max(
            (r for r in table if r.get(f"{prefix}_cash_flow") is not None),
            key=lambda r: r[f"{prefix}_cash_flow"],
            default=None
        )
        if best:
            cf = best[f"{prefix}_cash_flow"]
            print(f"    {scenario['rate']}%:  ${cf:+,.0f}/mo  — {best['address']}, {best['city']} "
                  f"(${best['price']:,.0f}, {best['beds']}bd)")


def run(conn: sqlite3.Connection):
    """Entry point — call this from main.py after the main scrape completes."""
    print("\n── Sensitivity analysis ──")
    print(f"  Modeling {len(RATE_SCENARIOS)} rate scenarios: "
          + ", ".join(f"{s['rate']}%" for s in RATE_SCENARIOS))

    table = build_sensitivity_table(conn)

    if not table:
        print("  No properties found in DB. Run the main scrape first.")
        return

    export_sensitivity_csv(table, OUTPUT["csv_dir"])
    save_sensitivity_db(conn, table)
    print_summary(table)
