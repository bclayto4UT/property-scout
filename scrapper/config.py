"""
config.py — Edit this before each run.
"""

# ── Search areas ───────────────────────────────────────────────────────────────
# Region IDs confirmed from Redfin URLs:
#   redfin.com/city/XXXXX/...         →  region_id = XXXXX, region_type = 6 (city)
#   redfin.com/zipcode/XXXXX          →  region_id = XXXXX, region_type = 2 (zip)
#   redfin.com/school/XXXXX/...       →  region_id = XXXXX, region_type = 9 (school district)
#
# Strategy: run BOTH zip-level (granular) and city-level (catch-all) queries.
# The Indian Land school district (region_type=9) covers the unincorporated
# SC/NC border zone that has no city boundary of its own.
# Duplicates are collapsed by deduplicate() using MLS# as the key, so overlap
# between layers is harmless.

SEARCHES = [

    # ══════════════════════════════════════════════════════════════════════════
    # ZIP-LEVEL QUERIES  (region_type=2)
    # ══════════════════════════════════════════════════════════════════════════

    # ── Charlotte Proper ──────────────────────────────────────────────────────
    {"label": "28201 Charlotte Downtown",     "region_id": "11344", "region_type": "2", "market": "charlotte"},
    {"label": "28202 Charlotte Uptown",       "region_id": "11345", "region_type": "2", "market": "charlotte"},
    {"label": "28203 Charlotte Southend",     "region_id": "11346", "region_type": "2", "market": "charlotte"},
    {"label": "28204 Charlotte Midtown",      "region_id": "11347", "region_type": "2", "market": "charlotte"},
    {"label": "28205 Charlotte NoDa",         "region_id": "11348", "region_type": "2", "market": "charlotte"},
    {"label": "28207 Charlotte Myers Park",   "region_id": "11350", "region_type": "2", "market": "charlotte"},
    {"label": "28208 Charlotte West",         "region_id": "11351", "region_type": "2", "market": "charlotte"},
    {"label": "28209 Charlotte Dilworth",     "region_id": "11352", "region_type": "2", "market": "charlotte"},
    {"label": "28210 Charlotte SW",           "region_id": "11353", "region_type": "2", "market": "charlotte"},
    {"label": "28211 Charlotte SE",           "region_id": "11354", "region_type": "2", "market": "charlotte"},
    {"label": "28212 Charlotte E",            "region_id": "11355", "region_type": "2", "market": "charlotte"},
    {"label": "28213 Charlotte NE",           "region_id": "11356", "region_type": "2", "market": "charlotte"},
    {"label": "28214 Charlotte NW",           "region_id": "11357", "region_type": "2", "market": "charlotte"},
    {"label": "28215 Charlotte NE2",          "region_id": "11358", "region_type": "2", "market": "charlotte"},
    {"label": "28216 Charlotte N",            "region_id": "11359", "region_type": "2", "market": "charlotte"},
    {"label": "28217 Charlotte S",            "region_id": "11360", "region_type": "2", "market": "charlotte"},
    {"label": "28226 Charlotte S2",           "region_id": "11368", "region_type": "2", "market": "charlotte"},
    {"label": "28227 Mint Hill",              "region_id": "11369", "region_type": "2", "market": "charlotte"},
    {"label": "28262 Charlotte University",   "region_id": "11393", "region_type": "2", "market": "charlotte"},
    {"label": "28269 Charlotte N2",           "region_id": "11397", "region_type": "2", "market": "charlotte"},
    {"label": "28270 Charlotte SE2",          "region_id": "11398", "region_type": "2", "market": "charlotte"},
    {"label": "28273 Charlotte SW3",          "region_id": "11401", "region_type": "2", "market": "charlotte"},
    {"label": "28277 Ballantyne",             "region_id": "11404", "region_type": "2", "market": "charlotte"},
    {"label": "28278 Charlotte SW2",          "region_id": "11405", "region_type": "2", "market": "charlotte"},

    # ── South / Pineville / Matthews ─────────────────────────────────────────
    {"label": "28134 Pineville",              "region_id": "11320", "region_type": "2", "market": "charlotte"},
    {"label": "28104 Matthews",               "region_id": "11297", "region_type": "2", "market": "charlotte"},
    {"label": "28105 Matthews E",             "region_id": "11298", "region_type": "2", "market": "charlotte"},
    {"label": "28173 Waxhaw",                 "region_id": "11342", "region_type": "2", "market": "charlotte"},

    # ── East / Cabarrus County ────────────────────────────────────────────────
    {"label": "28025 Concord",                "region_id": "11250", "region_type": "2", "market": "charlotte"},
    {"label": "28027 Concord NE",             "region_id": "11252", "region_type": "2", "market": "charlotte"},
    {"label": "28075 Harrisburg",             "region_id": "11276", "region_type": "2", "market": "charlotte"},
    {"label": "28083 Kannapolis",             "region_id": "11284", "region_type": "2", "market": "charlotte"},

    # ── North / Lake Norman ───────────────────────────────────────────────────
    {"label": "28078 Huntersville",           "region_id": "11279", "region_type": "2", "market": "charlotte"},
    {"label": "28031 Cornelius",              "region_id": "11253", "region_type": "2", "market": "charlotte"},
    {"label": "28036 Davidson",               "region_id": "11258", "region_type": "2", "market": "charlotte"},

    # ── West / Gaston County ─────────────────────────────────────────────────
    {"label": "28012 Belmont",                "region_id": "11241", "region_type": "2", "market": "charlotte"},
    {"label": "28120 Mount Holly",            "region_id": "11310", "region_type": "2", "market": "charlotte"},
    {"label": "28052 Gastonia",               "region_id": "11266", "region_type": "2", "market": "charlotte"},
    {"label": "28054 Gastonia E",             "region_id": "11268", "region_type": "2", "market": "charlotte"},
    {"label": "28056 Gastonia N",             "region_id": "11270", "region_type": "2", "market": "charlotte"},
    {"label": "28086 Kings Mountain",         "region_id": "11285", "region_type": "2", "market": "charlotte"},

    # ── SE / Union County NC ─────────────────────────────────────────────────
    {"label": "28110 Monroe",                 "region_id": "11303", "region_type": "2", "market": "charlotte"},
    {"label": "28112 Monroe S",               "region_id": "11305", "region_type": "2", "market": "charlotte"},

    # ── South Carolina — York County ─────────────────────────────────────────
    {"label": "29708 Fort Mill Tega Cay SC",  "region_id": "12262", "region_type": "2", "market": "charlotte"},
    {"label": "29715 Fort Mill SC",           "region_id": "12267", "region_type": "2", "market": "charlotte"},
    {"label": "29707 Indian Land SC",         "region_id": "41796", "region_type": "2", "market": "charlotte"},
    {"label": "29710 Clover Lake Wylie SC",   "region_id": "12264", "region_type": "2", "market": "charlotte"},
    {"label": "29712 Lesslie SC",             "region_id": "12265", "region_type": "2", "market": "charlotte"},
    {"label": "29717 Clover SC",              "region_id": "12269", "region_type": "2", "market": "charlotte"},
    {"label": "29726 McConnells SC",          "region_id": "12275", "region_type": "2", "market": "charlotte"},
    {"label": "29730 Rock Hill SC",           "region_id": "12279", "region_type": "2", "market": "charlotte"},
    {"label": "29732 Rock Hill N SC",         "region_id": "12281", "region_type": "2", "market": "charlotte"},
    {"label": "29734 Rock Hill W SC",         "region_id": "12283", "region_type": "2", "market": "charlotte"},
    {"label": "29742 Sharon SC",              "region_id": "12285", "region_type": "2", "market": "charlotte"},
    {"label": "29743 Smyrna SC",              "region_id": "12286", "region_type": "2", "market": "charlotte"},
    {"label": "29745 York SC",                "region_id": "12288", "region_type": "2", "market": "charlotte"},
    {"label": "29704 Catawba SC",             "region_id": "12260", "region_type": "2", "market": "charlotte"},

    # ── South Carolina — Lancaster County ────────────────────────────────────
    {"label": "29720 Lancaster SC",           "region_id": "12271", "region_type": "2", "market": "charlotte"},

    # ══════════════════════════════════════════════════════════════════════════
    # CITY-LEVEL CATCH-ALL QUERIES  (region_type=6)
    # Run after zip queries. deduplicate() collapses any MLS# overlap.
    # City boundaries on Redfin are broader than strict municipal limits —
    # Fort Mill and Lancaster intentionally pull surrounding unincorporated areas.
    # Region IDs verified from user-supplied Redfin city URLs.
    # ══════════════════════════════════════════════════════════════════════════

    # ── Mecklenburg County, NC ────────────────────────────────────────────────
    {"label": "City Charlotte",      "region_id": "3105",  "region_type": "6", "market": "charlotte"},
    {"label": "City Huntersville",   "region_id": "8466",  "region_type": "6", "market": "charlotte"},
    {"label": "City Cornelius",      "region_id": "3809",  "region_type": "6", "market": "charlotte"},
    {"label": "City Davidson",       "region_id": "35709", "region_type": "6", "market": "charlotte"},
    {"label": "City Mint Hill",      "region_id": "11076", "region_type": "6", "market": "charlotte"},
    {"label": "City Matthews",       "region_id": "10672", "region_type": "6", "market": "charlotte"},
    {"label": "City Pineville",      "region_id": "13468", "region_type": "6", "market": "charlotte"},

    # ── Cabarrus County, NC ───────────────────────────────────────────────────
    {"label": "City Concord",        "region_id": "3663",  "region_type": "6", "market": "charlotte"},
    {"label": "City Kannapolis",     "region_id": "8955",  "region_type": "6", "market": "charlotte"},
    {"label": "City Harrisburg",     "region_id": "7596",  "region_type": "6", "market": "charlotte"},

    # ── Iredell County, NC ────────────────────────────────────────────────────
    {"label": "City Mooresville",    "region_id": "11265", "region_type": "6", "market": "charlotte"},

    # ── Gaston County, NC ─────────────────────────────────────────────────────
    {"label": "City Gastonia",       "region_id": "6588",  "region_type": "6", "market": "charlotte"},
    {"label": "City Belmont",        "region_id": "1279",  "region_type": "6", "market": "charlotte"},
    {"label": "City Mount Holly",    "region_id": "11449", "region_type": "6", "market": "charlotte"},

    # ── Union County, NC ──────────────────────────────────────────────────────
    {"label": "City Indian Trail",   "region_id": "8591",  "region_type": "6", "market": "charlotte"},
    {"label": "City Monroe",         "region_id": "11185", "region_type": "6", "market": "charlotte"},
    {"label": "City Waxhaw",         "region_id": "18253", "region_type": "6", "market": "charlotte"},
    {"label": "City Stallings",      "region_id": "16517", "region_type": "6", "market": "charlotte"},

    # ── York County, SC ───────────────────────────────────────────────────────
    {"label": "City Fort Mill SC",   "region_id": "6873",  "region_type": "6", "market": "charlotte"},
    {"label": "City Tega Cay SC",    "region_id": "18239", "region_type": "6", "market": "charlotte"},
    {"label": "City Lake Wylie SC",  "region_id": "23717", "region_type": "6", "market": "charlotte"},
    {"label": "City Rock Hill SC",   "region_id": "15797", "region_type": "6", "market": "charlotte"},

    # ── Lancaster County, SC ──────────────────────────────────────────────────
    {"label": "City Lancaster SC",   "region_id": "10168", "region_type": "6", "market": "charlotte"},

    # ══════════════════════════════════════════════════════════════════════════
    # SCHOOL DISTRICT QUERY  (region_type=9)
    # Indian Land High School district covers the unincorporated SC/NC border
    # zone that has no city boundary. This is the primary workaround for
    # capturing listings in that area that city and zip queries both miss.
    # ══════════════════════════════════════════════════════════════════════════
    {"label": "Indian Land High School District", "region_id": "53530", "region_type": "9", "market": "charlotte"},
]

# ── Price bands ────────────────────────────────────────────────────────────────
# Max purchase price $400k. Bands split to work around Redfin's 350-listing cap.
# Slight $420k buffer to catch listings you could negotiate down.

SALE_PRICE_BANDS = [
    (0,       225_000),
    (225_000, 300_000),
    (300_000, 325_000),
    (325_000, 350_000),
    (350_000, 400_000),
    (400_000, 420_000),
]

RENT_PRICE_BANDS = [
    (0,     1_200),
    (1_200, 1_800),
    (1_800, 2_500),
    (2_500, 3_500),
    (3_500, 9_999),
]

# 1=house, 2=condo, 3=townhouse, 4=multi-family
PROPERTY_TYPES = "1,2,3,4"

# ── FHA loan parameters ────────────────────────────────────────────────────────
FHA = {
    "down_payment_pct":  3.5,
    "upfront_mip_pct":   1.75,
    "annual_mip_pct":    0.55,
    "interest_rate_pct": 6.5,     # ← Update before running
                                   #   https://www.mortgagenewsdaily.com/mortgage-rates/fha-30-year-fixed
    "loan_term_months":  360,

    # Both Mecklenburg County NC and York County SC have the same
    # 2025 FHA limit of $524,225 — well above your $400k ceiling.
    "county_loan_limit": 524_225,
}

# ── Local market assumptions ───────────────────────────────────────────────────
MARKET = {
    # Mecklenburg County NC ~1.0% | York County SC ~0.5-0.6% (primary residence)
    # Using NC rate as conservative default — SC properties will look slightly
    # better than modeled, which is fine.
    "property_tax_rate_pct": 1.0,
    "insurance_rate_pct":    0.6,
    "rent_growth_rate_pct":  4.0,  # Charlotte metro has run 4-6%/yr recently
}

# ── Buyer context ──────────────────────────────────────────────────────────────
BUYER = {
    "gross_annual_income": 120_000,
    "max_purchase_price":  400_000,
    # ~33% of $10k gross monthly income. FHA allows 43% DTI but 33% is safer.
    "max_monthly_piti":    3_300,
}

# ── Output ─────────────────────────────────────────────────────────────────────
OUTPUT = {
    "db_path":  "data/properties.db",
    "csv_dir":  "data/exports",
}
