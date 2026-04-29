"""
database.py — SQLite schema, upsert helpers, and CSV export.
"""

import sqlite3
import csv
import os
from datetime import datetime


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sale_properties (
        mls_id              TEXT PRIMARY KEY,
        address             TEXT,
        city                TEXT,
        state               TEXT,
        zip                 TEXT,
        neighborhood        TEXT,
        latitude            REAL,
        longitude           REAL,
        price               REAL,
        beds                INTEGER,
        baths               REAL,
        sqft                REAL,
        lot_size            REAL,
        year_built          INTEGER,
        price_per_sqft      REAL,
        hoa_monthly         REAL,
        days_on_market      INTEGER,
        property_type       TEXT,
        status              TEXT,
        listing_url         TEXT,

        -- FHA mortgage
        down_payment        REAL,
        base_loan           REAL,
        ufmip               REAL,
        total_loan          REAL,
        monthly_pi          REAL,
        monthly_mip         REAL,
        monthly_tax         REAL,
        monthly_insurance   REAL,
        monthly_piti        REAL,
        exceeds_fha_limit   INTEGER,
        fha_rate_used       REAL,

        -- Rent overlay
        rent_estimate       REAL,
        rent_source         TEXT,

        -- Scoring
        cash_flow_now       REAL,
        break_even_year     INTEGER,
        rent_at_1yr         REAL,
        rent_at_2yr         REAL,
        rent_at_5yr         REAL,
        tier                TEXT,

        scraped_at          TEXT,
        area_label          TEXT
    );

    CREATE TABLE IF NOT EXISTS rental_listings (
        mls_id          TEXT PRIMARY KEY,
        address         TEXT,
        city            TEXT,
        state           TEXT,
        zip             TEXT,
        neighborhood    TEXT,
        latitude        REAL,
        longitude       REAL,
        monthly_rent    REAL,
        beds            INTEGER,
        baths           REAL,
        sqft            REAL,
        rent_per_sqft   REAL,
        property_type   TEXT,
        listing_url     TEXT,
        scraped_at      TEXT,
        area_label      TEXT
    );

    CREATE TABLE IF NOT EXISTS rent_profiles (
        zip             TEXT,
        beds            INTEGER,
        count           INTEGER,
        low_rent        REAL,
        median_rent     REAL,
        high_rent       REAL,
        avg_rent        REAL,
        PRIMARY KEY (zip, beds)
    );
    """)
    conn.commit()


# ── Redfin CSV column → our field name mapping ─────────────────────────────────

SALE_COL_MAP = {
    "MLS#":             "mls_id",
    "ADDRESS":          "address",
    "CITY":             "city",
    "STATE OR PROVINCE":"state",
    "ZIP OR POSTAL CODE":"zip",
    "LOCATION":         "neighborhood",
    "LATITUDE":         "latitude",
    "LONGITUDE":        "longitude",
    "PRICE":            "price",
    "BEDS":             "beds",
    "BATHS":            "baths",
    "SQUARE FEET":      "sqft",
    "LOT SIZE":         "lot_size",
    "YEAR BUILT":       "year_built",
    "$/SQUARE FEET":    "price_per_sqft",
    "HOA/MONTH":        "hoa_monthly",
    "DAYS ON MARKET":   "days_on_market",
    "PROPERTY TYPE":    "property_type",
    "STATUS":           "status",
}

RENT_COL_MAP = {
    "MLS#":             "mls_id",
    "ADDRESS":          "address",
    "CITY":             "city",
    "STATE OR PROVINCE":"state",
    "ZIP OR POSTAL CODE":"zip",
    "LOCATION":         "neighborhood",
    "LATITUDE":         "latitude",
    "LONGITUDE":        "longitude",
    "PRICE":            "monthly_rent",
    "BEDS":             "beds",
    "BATHS":            "baths",
    "SQUARE FEET":      "sqft",
    "PROPERTY TYPE":    "property_type",
}


def _map_row(raw: dict, col_map: dict, url_key: str) -> dict:
    """Map raw Redfin CSV columns to our normalized field names."""
    result = {}
    for redfin_col, our_col in col_map.items():
        result[our_col] = (raw.get(redfin_col) or "").strip() or None

    # The URL column has a very long name in Redfin's CSV
    listing_url = None
    for k, v in raw.items():
        if "redfin.com" in k and "URL" in k.upper():
            listing_url = (v or "").strip() or None
            break
    result["listing_url"] = listing_url

    # If MLS# is missing (common for Charlotte/Redfin-only listings), derive
    # a stable ID from the URL path so rows aren't silently dropped.
    # e.g. ".../NC/Charlotte/123-Main-St/home/12345678" -> "url_12345678"
    if not result.get("mls_id") and listing_url:
        slug = listing_url.rstrip("/").split("/")[-1]
        result["mls_id"] = f"url_{slug}" if slug else None

    result["scraped_at"] = datetime.utcnow().isoformat()
    return result


def normalize_sale(raw: dict, area_label: str) -> dict:
    row = _map_row(raw, SALE_COL_MAP, "listing_url")
    row["area_label"] = area_label
    return row


def normalize_rental(raw: dict, area_label: str) -> dict:
    row = _map_row(raw, RENT_COL_MAP, "listing_url")
    row["area_label"] = area_label
    # Compute rent per sqft
    try:
        rent = float(str(row.get("monthly_rent", "") or "").replace(",", "").replace("$", ""))
        sqft = float(str(row.get("sqft", "") or "").replace(",", ""))
        row["rent_per_sqft"] = round(rent / sqft, 2) if sqft > 0 else None
    except (ValueError, TypeError):
        row["rent_per_sqft"] = None
    return row


def upsert_sale(conn: sqlite3.Connection, row: dict):
    if not row.get("mls_id"):
        print(f"    [skip] no mls_id or url for sale row: {row.get('address')}")
        return
    keys = [k for k in row if k in _sale_columns()]
    _upsert(conn, "sale_properties", {k: row[k] for k in keys}, "mls_id")


def upsert_rental(conn: sqlite3.Connection, row: dict):
    if not row.get("mls_id"):
        print(f"    [skip] no mls_id or url for rental row: {row.get('address')}")
        return
    keys = [k for k in row if k in _rental_columns()]
    _upsert(conn, "rental_listings", {k: row[k] for k in keys}, "mls_id")


def _upsert(conn: sqlite3.Connection, table: str, row: dict, pk: str):
    cols = list(row.keys())
    placeholders = ", ".join("?" * len(cols))
    col_str = ", ".join(cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != pk)
    conn.execute(
        f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk}) DO UPDATE SET {updates}",
        list(row.values())
    )


def save_rent_profiles(conn: sqlite3.Connection, profiles: list[dict]):
    for p in profiles:
        conn.execute(
            "INSERT INTO rent_profiles (zip, beds, count, low_rent, median_rent, high_rent, avg_rent) "
            "VALUES (:zip, :beds, :count, :low_rent, :median_rent, :high_rent, :avg_rent) "
            "ON CONFLICT(zip, beds) DO UPDATE SET "
            "count=excluded.count, low_rent=excluded.low_rent, "
            "median_rent=excluded.median_rent, high_rent=excluded.high_rent, "
            "avg_rent=excluded.avg_rent",
            p
        )
    conn.commit()


def export_csvs(conn: sqlite3.Connection, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    tables = [
        ("sale_properties", "sale_properties.csv"),
        ("rental_listings", "rental_listings.csv"),
        ("rent_profiles",   "rent_profiles.csv"),
    ]
    for table, filename in tables:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            print(f"  (no data in {table})")
            continue
        path = os.path.join(out_dir, filename)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows([dict(r) for r in rows])
        print(f"  → {path}  ({len(rows)} rows)")


def _sale_columns():
    return {
        "mls_id","address","city","state","zip","neighborhood",
        "latitude","longitude","price","beds","baths","sqft","lot_size",
        "year_built","price_per_sqft","hoa_monthly","days_on_market",
        "property_type","status","listing_url","down_payment","base_loan",
        "ufmip","total_loan","monthly_pi","monthly_mip","monthly_tax",
        "monthly_insurance","monthly_piti","exceeds_fha_limit","fha_rate_used",
        "rent_estimate","rent_source","cash_flow_now","break_even_year",
        "rent_at_1yr","rent_at_2yr","rent_at_5yr","tier","scraped_at","area_label",
    }

def _rental_columns():
    return {
        "mls_id","address","city","state","zip","neighborhood",
        "latitude","longitude","monthly_rent","beds","baths","sqft",
        "rent_per_sqft","property_type","listing_url","scraped_at","area_label",
    }
