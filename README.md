# Property Scout — Redfin Investment Property Scraper

Scrapes Redfin for-sale listings across the Charlotte metro area, enriches them
with rent estimates via RentCast, computes FHA mortgage projections, and scores
each property by investment tier. Browsable via a private Streamlit web app.

---

## Project Status

**Fully working and deployed:**

- `main.py` — scrapes Redfin for-sale listings, computes FHA mortgage, writes to SQLite
- `enrich_rentcast.py` — pulls rent estimates from RentCast API (one call per unique ZIP),
  re-scores all properties, re-exports CSVs; tracks quota across two API keys
- `app.py` — Streamlit web app with sidebar filters, summary metrics, tier breakdown,
  Google My Maps embed, property cards with Redfin + Zillow links, a data table, and a
  rent profiles tab
- `scraper.py` — Redfin `gis-csv` endpoint wrapper with Playwright cookie auth, price-band
  paging, deduplication, and improved CSV header parsing
- `favorites.py` — ingests individual Redfin property URLs or a full saved Favorites list
  into the DB, scoring each the same way `main.py` does
- `export_kml.py` — exports properties from the DB to a colour-coded KML file for import
  into Google My Maps (one folder/layer per investment tier)
- `config.py` — all tunable parameters: 70+ ZIP-level and city-level search areas, price
  bands, FHA rate, market assumptions, RentCast API keys, output paths

**Current search coverage** (`config.py`):

Queries run at two levels and deduplicated by MLS#:

- **ZIP-level** (`region_type=2`): 55 ZIP codes covering Charlotte proper, Matthews,
  Mint Hill, Pineville, Waxhaw, Concord, Harrisburg, Kannapolis, Huntersville, Cornelius,
  Davidson, Belmont, Mount Holly, Gastonia, Kings Mountain, Monroe, and York/Lancaster
  County SC (Fort Mill, Tega Cay, Indian Land, Lake Wylie, Clover, Rock Hill, Lancaster)
- **City-level catch-alls** (`region_type=6`): 25 cities to capture listings that fall
  inside a city boundary but outside covered ZIP codes
- **School district** (`region_type=9`): Indian Land High School district, which covers
  the unincorporated SC/NC border zone that neither city nor ZIP queries reach reliably

---

## File Structure

```
redfin_scraper/
├── main.py              # Full pipeline: scrape → score → export
├── enrich_rentcast.py   # RentCast rent enrichment + re-scoring
├── favorites.py         # Ingest individual URLs or saved Favorites list
├── export_kml.py        # Export tier-coded KML for Google My Maps
├── scraper.py           # Redfin gis-csv fetcher (Playwright auth)
├── config.py            # All config: areas, price bands, FHA params, API keys
├── app.py               # Streamlit web app
├── database.py          # SQLite schema + upsert helpers
├── mortgage.py          # FHA mortgage calc + tier classifier
├── rent_profile.py      # Rent profile lookup helpers
├── sensitivity.py       # Sensitivity analysis across interest rate scenarios
├── lookup_zip_region_ids.py  # One-time helper to resolve ZIP → region_id
├── zip_region_map.json  # Output of lookup_zip_region_ids (for reference)
├── README.md            # This file
└── data/
    ├── properties.db        # SQLite database (gitignored)
    ├── rentcast_usage.json  # Live RentCast quota tracking (gitignored)
    └── exports/
        ├── sale_properties.csv
        ├── rental_listings.csv
        ├── rent_profiles.csv
        └── sensitivity_table.csv
```

---

## Setup

**1. Install dependencies**
```bash
pip3 install requests playwright pandas streamlit
playwright install chromium
```

**2. Configure `config.py`:**
- `SEARCHES` — ZIP + city area list (already populated; see Coverage section above)
- `FHA["interest_rate_pct"]` — update to current 30-yr FHA rate before each run
  (check [mortgagenewsdaily.com](https://www.mortgagenewsdaily.com/mortgage-rates/fha-30-year-fixed))
- `RENTCAST_KEYS` — list your RentCast API keys with per-key limits and usage baseline
- `MARKET` — property tax rate, insurance rate, rent growth assumption

**3. Run the scraper**
```bash
python3 main.py                   # scrape Redfin, score, write to SQLite, export CSVs
python3 main.py --rescore         # skip scrape, re-score all existing properties
python3 enrich_rentcast.py        # add/refresh rent estimates from RentCast
python3 enrich_rentcast.py --dry-run     # preview quota usage without making API calls
python3 enrich_rentcast.py --reset-usage # zero out quota counters at billing month start
```

**4. Ingest favorites or specific listings**
```bash
# One or more individual Redfin property URLs
python3 favorites.py https://www.redfin.com/NC/Charlotte/123-Main-St-28277/home/12345678

# Your saved Redfin Favorites list (requires logged-in session cookie)
python3 favorites.py --favorites https://www.redfin.com/user/favorites

# A downloaded CSV export from Redfin favorites
python3 favorites.py --csv redfin-favorites_2026-04-28.csv
```

**5. Export to Google My Maps**
```bash
python3 export_kml.py             # exports all tiers → properties.kml
python3 export_kml.py --tier immediately_rentable rentable_1_2_years  # subset
```
Then import the `.kml` at [google.com/maps/d](https://www.google.com/maps/d/) — each tier becomes its own named layer.

**6. Run the web app locally**
```bash
streamlit run app.py
```

---

## Investment Tiers

| Tier | Icon | Meaning |
|---|---|---|
| `immediately_rentable` | ✅ | Monthly PITI < current median rent — cash flow positive today |
| `rentable_1_2_years` | 🟡 | Cash flow positive within 1–2 years at projected rent growth |
| `high_risk` | 🔴 | Won't be cash flow positive for 3+ years |
| `no_rent_data` | ⬜ | No rental comps found for this ZIP/bed combo |

---

## FHA Mortgage Model

All properties are scored assuming an FHA loan with the parameters in `config.py`:

| Parameter | Default | Notes |
|---|---|---|
| Down payment | 3.5% | FHA minimum |
| Upfront MIP | 1.75% | Rolled into loan balance |
| Annual MIP | 0.55% | Paid monthly |
| Interest rate | 6.5% | **Update before each run** |
| Loan term | 30 years | 360 months |
| Property tax | 1.0% / yr | Conservative NC rate; SC properties modeled conservatively |
| Insurance | 0.6% / yr | — |
| FHA loan limit | $524,225 | 2025 limit for both Mecklenburg NC and York County SC |

Monthly PITI = P&I + monthly MIP + property tax + insurance.

---

## Key Columns in `sale_properties`

| Column | Description |
|---|---|
| `price` | Listing price |
| `monthly_piti` | Full FHA payment (P&I + MIP + tax + insurance) |
| `down_payment` | 3.5% FHA down payment required |
| `total_loan` | Loan amount including rolled-in UFMIP |
| `exceeds_fha_limit` | 1 if price > county FHA loan limit |
| `rent_estimate` | Median rent for matching ZIP + bed count (from RentCast) |
| `rent_source` | `rentcast_exact`, `rentcast_fallback_Nbd`, or `no_data` |
| `cash_flow_now` | `rent_estimate − monthly_piti` (negative = monthly loss) |
| `break_even_year` | Year projected rent exceeds PITI (0 = today) |
| `rent_at_1yr/2yr/5yr` | Projected rent at 1, 2, and 5 years (4% annual growth) |
| `tier` | Investment classification |
| `area_label` | Source search area label from `config.py` |

---

## RentCast API Quota Management

`enrich_rentcast.py` uses one API call per unique ZIP code. With ~55 ZIPs in the
current search list, one full enrichment run costs ~55 calls.

Key safety features:
- Tracks live usage in `data/rentcast_usage.json` across two API keys (50 calls/month each)
- Uses key 1 first; automatically switches to key 2 on exhaustion or a 429 response
- Refuses to start if the run would exceed the combined remaining budget
- Run `--dry-run` to preview the call plan before committing
- Run `--reset-usage` at the start of each billing month

---

## Sensitivity Analysis

`sensitivity.py` (called automatically by `main.py`) recalculates PITI, cash flow,
and investment tier for each property across five interest rate scenarios:

| Scenario | Rate |
|---|---|
| Current | per `config.py` |
| rate_6_5 | 6.5% |
| rate_6_0 | 6.0% |
| rate_5_5 | 5.5% |
| rate_5_0 | 5.0% |

Output is written to `data/exports/sensitivity_table.csv` and a `sensitivity_table`
SQLite table for filtering in DB Browser or Google Sheets.

---

## Operational Notes

- Redfin caps results at 350 per request — the price band paging in `config.py`
  works around this. Current bands cover $0–$420k in six overlapping steps.
- A 1–2 second sleep between requests is built in to avoid rate limiting.
- Re-run `main.py` anytime to refresh data — upserts by MLS# prevent duplicates.
- The `data/` folder is gitignored by default — don't commit your database or API keys.
- RentCast free tier: 50 calls/month per key. With ~55 unique ZIPs, you need both
  keys to cover a full enrichment run (~6 full runs/month across both keys combined).

---

## Planned / In-Progress Work

### 1. Threshold Price Calculator (New Tab in `app.py`)

A new tab that lets you enter specs for any property (ZIP, beds, baths, sqft, rate)
and instantly calculates the maximum purchase price for immediate / 1-year / 2-year
cash flow break-even, using rent data already in the DB. Useful for evaluating
off-market or pocket listings not in the scraper results.

### 2. New Rent Estimate API

A second rent data provider is planned to supplement or replace RentCast. Once the
API key is available, a new fetch function will be added to `enrich_rentcast.py` with
a fallback chain: new API → RentCast → no_data.

### 3. Dynamic Property Map in the Web App

Replace (or supplement) the static Google My Maps iframe with a `folium` or `pydeck`
map that plots the filtered property pins directly from the DB, colour-coded by tier
with address/price/cash-flow tooltips. Requires `streamlit-folium` added to
`requirements.txt`.

### 4. "Refresh Data" Button

A sidebar button in `app.py` that calls `st.cache_data.clear()` and reruns the app
so family members can bust the 5-minute cache without redeploying.
