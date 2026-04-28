"""
app.py — Streamlit web app for browsing investment property data.
Drop this file alongside your properties.db (or configure DB_PATH below).
"""

import sqlite3
import os
import pandas as pd
import streamlit as st
from urllib.parse import quote_plus

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "data/properties.db")

TIER_META = {
    "immediately_rentable": {"icon": "✅", "label": "Cash Flow+  Today",  "color": "#22c55e"},
    "rentable_1_2_years":   {"icon": "🟡", "label": "CF+ in 1–2 Years",   "color": "#eab308"},
    "high_risk":            {"icon": "🔴", "label": "High Risk (3+ yrs)", "color": "#ef4444"},
    "no_rent_data":         {"icon": "⬜", "label": "No Rent Data",        "color": "#94a3b8"},
}

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Property Scout",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
h1, h2, h3 { font-family: 'DM Serif Display', serif; }

.metric-card {
    background: #1e293b;
    border-radius: 12px;
    padding: 1.1rem 1.3rem;
    margin-bottom: 0.5rem;
    border-left: 4px solid #38bdf8;
}
.metric-card .label { font-size: 0.72rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.08em; }
.metric-card .value { font-size: 1.6rem; font-weight: 600; color: #f1f5f9; }

.tier-pill {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.03em;
}
.stDataFrame { border-radius: 10px; overflow: hidden; }

section[data-testid="stSidebar"] { background: #0f172a; }
section[data-testid="stSidebar"] * { color: #cbd5e1 !important; }
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stSlider label { color: #94a3b8 !important; font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)


# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_data():
    if not os.path.exists(DB_PATH):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    sales   = pd.read_sql("SELECT * FROM sale_properties",  conn)
    rentals = pd.read_sql("SELECT * FROM rental_listings",  conn)
    profiles= pd.read_sql("SELECT * FROM rent_profiles",    conn)
    conn.close()
    return sales, rentals, profiles


sales, rentals, profiles = load_data()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("# 🏠 Property Scout")
st.markdown("*Investment property explorer — filter, compare, and map listings*")
st.divider()

if sales.empty:
    st.warning(f"No data found. Make sure `{DB_PATH}` exists and the scraper has been run.")
    st.stop()

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🔍 Filters")

    # Tier filter
    all_tiers = [t for t in TIER_META if t in sales["tier"].unique()]
    selected_tiers = st.multiselect(
        "Investment Tier",
        options=list(TIER_META.keys()),
        default=all_tiers,
        format_func=lambda t: f"{TIER_META[t]['icon']} {TIER_META[t]['label']}",
    )

    # Area filter
    areas = sorted(sales["area_label"].dropna().unique())
    selected_areas = st.multiselect("Area / Neighborhood", options=areas, default=areas)

    # Price range
    min_price = int(sales["price"].min() or 0)
    max_price = int(sales["price"].max() or 2_000_000)
    price_range = st.slider(
        "Price Range ($)",
        min_value=min_price,
        max_value=max_price,
        value=(min_price, max_price),
        step=10_000,
        format="$%d",
    )

    # Beds
    bed_opts = sorted(sales["beds"].dropna().unique().astype(int))
    selected_beds = st.multiselect("Bedrooms", options=bed_opts, default=bed_opts,
                                   format_func=lambda b: f"{b} bd")

    # Cash flow toggle
    cf_only = st.checkbox("Show cash flow+ only", value=False)

    st.divider()
    st.markdown("### 📋 Columns to show")
    show_mortgage = st.checkbox("Mortgage details", value=False)
    show_rent     = st.checkbox("Rent projection", value=True)
    show_location = st.checkbox("Location fields",  value=False)

    st.divider()

    # ── Data refresh ──────────────────────────────────────────────────────────
    # Shows when data was last loaded and lets anyone bust the cache instantly.
    # Does NOT re-run the scraper — that still runs locally. This just forces
    # the app to re-read the database so the latest scraper output is visible.
    import datetime as _dt
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = _dt.datetime.now().strftime("%-I:%M %p")

    st.markdown(
        f"<div style='font-size:0.72rem; color:#64748b; margin-bottom:0.5rem'>"
        f"Data loaded at {st.session_state.last_refresh}</div>",
        unsafe_allow_html=True,
    )

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.session_state.last_refresh = _dt.datetime.now().strftime("%-I:%M %p")
        st.rerun()

# ── Apply filters ─────────────────────────────────────────────────────────────
df = sales.copy()

if selected_tiers:
    df = df[df["tier"].isin(selected_tiers)]
if selected_areas:
    df = df[df["area_label"].isin(selected_areas)]
if selected_beds:
    df = df[df["beds"].isin(selected_beds)]

df = df[(df["price"] >= price_range[0]) & (df["price"] <= price_range[1])]

if cf_only:
    df = df[df["cash_flow_now"] > 0]

# ── Summary metrics ───────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)

def metric_card(col, label, value):
    col.markdown(f"""
    <div class="metric-card">
        <div class="label">{label}</div>
        <div class="value">{value}</div>
    </div>""", unsafe_allow_html=True)

metric_card(col1, "Properties shown", f"{len(df):,}")
metric_card(col2, "Avg price",
    f"${df['price'].mean():,.0f}" if not df.empty else "—")
metric_card(col3, "Avg monthly PITI",
    f"${df['monthly_piti'].mean():,.0f}" if not df.empty else "—")
metric_card(col4, "Avg cash flow/mo",
    f"${df['cash_flow_now'].mean():,.0f}" if "cash_flow_now" in df and not df.empty else "—")

st.markdown("")

# ── Tier breakdown ────────────────────────────────────────────────────────────
tier_cols = st.columns(len(TIER_META))
for i, (tier, meta) in enumerate(TIER_META.items()):
    count = len(df[df["tier"] == tier]) if "tier" in df.columns else 0
    tier_cols[i].markdown(f"""
    <div style="text-align:center; background:#1e293b; border-radius:10px; padding:0.8rem 0.5rem; margin-bottom:1rem;">
        <div style="font-size:1.5rem">{meta['icon']}</div>
        <div style="font-size:1.4rem; font-weight:700; color:{meta['color']}">{count}</div>
        <div style="font-size:0.7rem; color:#94a3b8; text-transform:uppercase; letter-spacing:0.06em">{meta['label']}</div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ── Tabs: Map / Table / Rent Profiles ─────────────────────────────────────────
tab_map, tab_table, tab_rent, tab_calc = st.tabs(["🗺️ Map", "📊 Table", "📈 Rent Profiles", "🧮 Threshold Calculator"])

# ── MAP TAB ───────────────────────────────────────────────────────────────────
# Google My Maps embed URL — edit the `mid=` value if you ever create a new map
GOOGLE_MAP_EMBED_URL = (
    "https://www.google.com/maps/d/u/0/embed"
    "?mid=14ZUn3qDQoLP_SCuNq8ErT3aADL4Juwc"
    "&ehbc=2E312F"
)

with tab_map:
    st.markdown(
        f"""
        <iframe
            src="{GOOGLE_MAP_EMBED_URL}"
            width="100%"
            height="560"
            style="border:none; border-radius:12px;"
            allowfullscreen
            loading="lazy"
        ></iframe>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        "Your Google My Maps — neighbourhood overlays and commute zones are all in there. "
        "Click any pin for details, or use the layer panel (top-left of map) to toggle KMZ layers. "
        "**[Open full map ↗](https://www.google.com/maps/d/u/0/viewer?mid=14ZUn3qDQoLP_SCuNq8ErT3aADL4Juwc)**"
    )

    # ── Folium property pin map ───────────────────────────────────────────────
    st.markdown("#### 📍 Filtered Properties")
    st.markdown(
        "<p style='color:#94a3b8; font-size:0.85rem; margin-top:-0.5rem'>"
        "Pins are colour-coded by investment tier. Click any pin for details.</p>",
        unsafe_allow_html=True,
    )

    map_df = df[df["latitude"].notna() & df["longitude"].notna()].copy()

    if map_df.empty:
        st.info("No properties with coordinates match your current filters.")
    else:
        import pydeck as pdk

        # Tier → RGB colour tuple for PyDeck
        TIER_COLORS_RGB = {
            "immediately_rentable": [34, 197, 94],    # #22c55e green
            "rentable_1_2_years":   [234, 179, 8],    # #eab308 yellow
            "high_risk":            [239, 68, 68],     # #ef4444 red
            "no_rent_data":         [148, 163, 184],   # #94a3b8 slate
        }

        map_df["color"] = map_df["tier"].map(
            lambda t: TIER_COLORS_RGB.get(t, TIER_COLORS_RGB["no_rent_data"])
        )
        map_df["cf"]       = map_df.get("cash_flow_now", pd.Series(0, index=map_df.index)).fillna(0)
        map_df["cf_str"]   = map_df["cf"].apply(
            lambda v: f"+${v:,.0f}/mo" if v >= 0 else f"-${abs(v):,.0f}/mo"
        )
        map_df["price"]    = map_df["price"].fillna(0)
        map_df["piti"]     = map_df.get("monthly_piti", pd.Series(0, index=map_df.index)).fillna(0)
        map_df["rent_est"] = map_df.get("rent_estimate", pd.Series(0, index=map_df.index)).fillna(0)
        map_df["beds"]     = map_df["beds"].fillna(0).astype(int)
        map_df["tier_label"] = map_df["tier"].map(
            lambda t: TIER_META.get(t, TIER_META["no_rent_data"])["label"]
        )
        map_df["tooltip"] = map_df.apply(
            lambda r: (
                f"{r.get('address','')} — {r['tier_label']}\n"
                f"Price: ${r['price']:,.0f} · {r['beds']}bd\n"
                f"PITI: ${r['piti']:,.0f}/mo · Rent: ${r['rent_est']:,.0f}/mo\n"
                f"Cash flow: {r['cf_str']}"
            ),
            axis=1,
        )

        layer = pdk.Layer(
            "ScatterplotLayer",
            data=map_df,
            get_position=["longitude", "latitude"],
            get_fill_color="color",
            get_radius=120,
            pickable=True,
            opacity=0.85,
            stroked=True,
            get_line_color=[255, 255, 255, 60],
            line_width_min_pixels=1,
        )

        view = pdk.ViewState(
            latitude=map_df["latitude"].mean(),
            longitude=map_df["longitude"].mean(),
            zoom=11,
            pitch=0,
        )

        st.pydeck_chart(
            pdk.Deck(
                layers=[layer],
                initial_view_state=view,
                map_style="mapbox://styles/mapbox/dark-v10",
                tooltip={"text": "{tooltip}"},
            ),
            use_container_width=True,
        )

    # Property cards below map so users can cross-reference
    st.markdown("#### 📋 Properties matching your filters")
    st.markdown(
        "<p style='color:#94a3b8; font-size:0.85rem; margin-top:-0.5rem'>"
        "Use the sidebar filters to narrow this list, then find the address on the map above.</p>",
        unsafe_allow_html=True,
    )

    prop_df = df.copy()

    if prop_df.empty:
        st.info("No properties match your current filters.")
    else:
        # Sort: best cash flow first
        prop_df = prop_df.sort_values("cash_flow_now", ascending=False)

        for _, row in prop_df.iterrows():
            tier = row.get("tier", "no_rent_data")
            meta = TIER_META.get(tier, TIER_META["no_rent_data"])
            cf   = row.get("cash_flow_now", 0) or 0
            cf_str   = f"+${cf:,.0f}/mo" if cf >= 0 else f"-${abs(cf):,.0f}/mo"
            cf_color = "#22c55e" if cf >= 0 else "#ef4444"
            bey  = row.get("break_even_year")
            bey_str  = f"Break-even yr {int(bey)}" if pd.notna(bey) and bey else ""

            # ── Redfin link: stored URL first, fallback to search ─────────────
            addr    = row.get("address", "") or ""
            city    = row.get("city", "") or ""
            state   = row.get("state", "NC") or "NC"
            if row.get("listing_url"):
                redfin_url = row["listing_url"]
            else:
                redfin_search = quote_plus(f"{addr}, {city}, {state}")
                redfin_url = f"https://www.redfin.com/search#combined?location={redfin_search}"

            # ── Zillow link: address-based search URL ─────────────────────────
            zillow_slug = quote_plus(f"{addr} {city} {state}").replace("+", "-")
            zillow_url  = f"https://www.zillow.com/homes/{zillow_slug}_rb/"

            listing_buttons = (
                f'<a href="{redfin_url}" target="_blank" style="'
                f'font-size:0.78rem; color:#38bdf8; text-decoration:none; '
                f'background:#38bdf811; border:1px solid #38bdf844; '
                f'padding:3px 10px; border-radius:6px; white-space:nowrap">🔴 Redfin →</a>'
                f'&nbsp;'
                f'<a href="{zillow_url}" target="_blank" style="'
                f'font-size:0.78rem; color:#60a5fa; text-decoration:none; '
                f'background:#60a5fa11; border:1px solid #60a5fa44; '
                f'padding:3px 10px; border-radius:6px; white-space:nowrap">🏠 Zillow →</a>'
            )

            bey_snippet = ("&nbsp;·&nbsp; " + bey_str) if bey_str else ""
            tier_pill = (
                '<span style="background:' + meta["color"] + '22; color:' + meta["color"] + '; '
                'font-size:0.72rem; font-weight:600; padding:2px 8px; '
                'border-radius:999px; letter-spacing:0.04em">'
                + meta["icon"] + " " + meta["label"] + '</span>'
            )
            card_html = (
                '<div style="background:#1e293b; border-radius:10px; padding:0.9rem 1.1rem; '
                'margin-bottom:0.5rem; border-left: 4px solid ' + meta["color"] + '">'
                '<div style="display:flex; justify-content:space-between; align-items:baseline">'
                '<b style="color:#f1f5f9; font-size:1rem">' + (addr or "Unknown") + '</b>'
                '<span style="color:' + cf_color + '; font-weight:700; font-size:1rem">' + cf_str + '</span>'
                '</div>'
                '<div style="color:#94a3b8; font-size:0.83rem; margin-top:3px">'
                + city + ", " + str(row.get("zip", "")) + ' &nbsp;·&nbsp; '
                '$' + f'{row.get("price", 0):,.0f}' + ' &nbsp;·&nbsp; '
                + str(int(row.get("beds") or 0)) + 'bd / ' + str(row.get("baths", "?")) + 'ba &nbsp;·&nbsp; '
                'PITI <b style="color:#cbd5e1">$' + f'{row.get("monthly_piti", 0):,.0f}' + '/mo</b>'
                '&nbsp;·&nbsp; Rent est. <b style="color:#cbd5e1">$' + f'{row.get("rent_estimate", 0) or 0:,.0f}' + '/mo</b>'
                + bey_snippet +
                '</div>'
                '<div style="margin-top:6px; display:flex; gap:0.6rem; align-items:center; flex-wrap:wrap">'
                + tier_pill + '&nbsp;' + listing_buttons +
                '</div></div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)


# ── TABLE TAB ─────────────────────────────────────────────────────────────────
with tab_table:
    base_cols = ["address", "city", "zip", "beds", "baths", "sqft",
                 "price", "tier", "monthly_piti", "rent_estimate",
                 "cash_flow_now", "break_even_year", "days_on_market", "area_label"]

    if show_mortgage:
        base_cols += ["down_payment", "monthly_pi", "monthly_mip", "monthly_tax",
                      "monthly_insurance", "exceeds_fha_limit", "fha_rate_used"]
    if show_rent:
        base_cols += ["rent_at_1yr", "rent_at_2yr", "rent_at_5yr", "rent_source"]
    if show_location:
        base_cols += ["neighborhood", "latitude", "longitude", "listing_url"]

    display_cols = [c for c in base_cols if c in df.columns]
    display_df = df[display_cols].copy()

    # Format money columns
    money_cols = ["price", "monthly_piti", "rent_estimate", "cash_flow_now",
                  "down_payment", "monthly_pi", "monthly_mip", "monthly_tax",
                  "monthly_insurance", "rent_at_1yr", "rent_at_2yr", "rent_at_5yr"]
    for col in money_cols:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(
                lambda v: f"${v:,.0f}" if pd.notna(v) else "—"
            )

    # Tier → readable label
    if "tier" in display_df.columns:
        display_df["tier"] = display_df["tier"].apply(
            lambda t: f"{TIER_META.get(t, {}).get('icon','?')} {TIER_META.get(t, {}).get('label', t)}"
            if pd.notna(t) else "—"
        )

    st.dataframe(display_df, use_container_width=True, height=520)

    # CSV download
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download filtered results as CSV",
        data=csv_bytes,
        file_name="filtered_properties.csv",
        mime="text/csv",
    )

# ── RENT PROFILES TAB ────────────────────────────────────────────────────────
with tab_rent:
    if profiles.empty:
        st.info("No rent profile data found.")
    else:
        st.markdown("### Rent comps by ZIP code + bedroom count")
        st.caption("These are the medians used to score each property.")

        area_filter = st.selectbox("Filter by area (optional)", ["All"] + sorted(profiles["zip"].dropna().unique()))
        pf = profiles if area_filter == "All" else profiles[profiles["zip"] == area_filter]

        pf_display = pf.copy()
        for col in ["low_rent", "median_rent", "high_rent", "avg_rent"]:
            if col in pf_display.columns:
                pf_display[col] = pf_display[col].apply(lambda v: f"${v:,.0f}" if pd.notna(v) else "—")

        pf_display.columns = [c.replace("_", " ").title() for c in pf_display.columns]
        st.dataframe(pf_display, use_container_width=True)

        csv_p = profiles.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download rent profiles CSV", data=csv_p,
                           file_name="rent_profiles.csv", mime="text/csv")

# ── THRESHOLD CALCULATOR TAB ──────────────────────────────────────────────────
with tab_calc:
    st.markdown("### 🧮 Threshold Price Calculator")
    st.markdown(
        "<p style='color:#94a3b8; font-size:0.9rem; margin-top:-0.5rem'>"
        "Not every listing is on Redfin. Enter a property's specs to find the "
        "<b style='color:#cbd5e1'>maximum purchase price</b> where it breaks even "
        "on cash flow — today and at 1 and 2 years of rent growth.</p>",
        unsafe_allow_html=True,
    )

    st.divider()

    # ── Inputs ────────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    with c1:
        calc_beds  = st.selectbox("Bedrooms", [1, 2, 3, 4, 5], index=2)
        calc_baths = st.selectbox("Bathrooms", [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0], index=2)
        calc_sqft  = st.number_input("Square footage", min_value=400, max_value=6000,
                                     value=1800, step=50)
    with c2:
        # Pull ZIPs that have rent data
        if not profiles.empty and "zip" in profiles.columns:
            zip_opts = sorted(profiles["zip"].dropna().astype(str).unique())
        else:
            zip_opts = []
        calc_zip = st.selectbox("ZIP code", zip_opts if zip_opts else ["(no data)"])

        calc_apr = st.number_input("Interest rate (APR %)", min_value=2.0, max_value=15.0,
                                   value=6.5, step=0.125, format="%.3f")
        calc_loan_type = st.radio("Loan type", ["FHA (3.5% down)", "Conventional (20% down)"],
                                  horizontal=True)
    with c3:
        calc_tax_rate = st.number_input("Property tax rate (%/yr)", min_value=0.1,
                                        max_value=3.0, value=1.0, step=0.05, format="%.2f")
        calc_ins_rate = st.number_input("Insurance rate (%/yr)", min_value=0.1,
                                        max_value=2.0, value=0.6, step=0.05, format="%.2f")
        calc_rent_growth = st.number_input("Rent growth (%/yr)", min_value=0.0,
                                           max_value=10.0, value=4.0, step=0.5, format="%.1f")

    st.markdown("")

    # ── Rent lookup ───────────────────────────────────────────────────────────
    rent_est    = None
    rent_note   = ""

    if not profiles.empty and calc_zip and calc_zip != "(no data)":
        zip_prof = profiles[profiles["zip"].astype(str) == str(calc_zip)]
        if not zip_prof.empty:
            exact = zip_prof[zip_prof["beds"] == calc_beds]
            if not exact.empty:
                rent_est  = float(exact.iloc[0]["median_rent"])
                rent_note = f"Exact match: {calc_beds}bd in ZIP {calc_zip}"
            else:
                # nearest bed count
                zip_prof = zip_prof.copy()
                zip_prof["_diff"] = (zip_prof["beds"] - calc_beds).abs()
                nearest  = zip_prof.sort_values("_diff").iloc[0]
                rent_est  = float(nearest["median_rent"])
                rent_note = (f"No {calc_beds}bd data in {calc_zip} — "
                             f"using {int(nearest['beds'])}bd median (${rent_est:,.0f}/mo)")

    # ── PITI formula for a given price ───────────────────────────────────────
    def calc_piti(price: float, apr: float, loan_type: str,
                  tax_rate: float, ins_rate: float) -> dict:
        if loan_type.startswith("FHA"):
            dp_pct   = 0.035
            ufmip    = 0.0175
            ann_mip  = 0.0055
        else:
            dp_pct   = 0.20
            ufmip    = 0.0
            ann_mip  = 0.0

        down      = price * dp_pct
        base_loan = price - down
        total_loan= base_loan * (1 + ufmip)
        r         = (apr / 100) / 12
        n         = 360
        if r > 0:
            monthly_pi = total_loan * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
        else:
            monthly_pi = total_loan / n
        monthly_mip = (total_loan * ann_mip) / 12
        monthly_tax = (price * tax_rate / 100) / 12
        monthly_ins = (price * ins_rate / 100) / 12
        piti = monthly_pi + monthly_mip + monthly_tax + monthly_ins
        return {
            "piti":       round(piti, 2),
            "down":       round(down, 2),
            "base_loan":  round(base_loan, 2),
            "monthly_pi": round(monthly_pi, 2),
            "monthly_mip":round(monthly_mip, 2),
            "monthly_tax":round(monthly_tax, 2),
            "monthly_ins":round(monthly_ins, 2),
        }

    # ── Solve for threshold price: find price where PITI = target_rent ───────
    # PITI is ~linear in price, so bisection converges in <30 iterations.
    def find_threshold_price(target_rent: float, apr: float, loan_type: str,
                             tax_rate: float, ins_rate: float) -> float:
        lo, hi = 50_000.0, 2_000_000.0
        for _ in range(60):
            mid  = (lo + hi) / 2
            piti = calc_piti(mid, apr, loan_type, tax_rate, ins_rate)["piti"]
            if piti < target_rent:
                lo = mid
            else:
                hi = mid
            if hi - lo < 10:
                break
        return round((lo + hi) / 2, -2)   # round to nearest $100

    # ── Run calculation ───────────────────────────────────────────────────────
    if rent_est:
        growth  = calc_rent_growth / 100
        rent_1yr = rent_est * (1 + growth) ** 1
        rent_2yr = rent_est * (1 + growth) ** 2

        thresh_now = find_threshold_price(rent_est,  calc_apr, calc_loan_type,
                                          calc_tax_rate, calc_ins_rate)
        thresh_1yr = find_threshold_price(rent_1yr,  calc_apr, calc_loan_type,
                                          calc_tax_rate, calc_ins_rate)
        thresh_2yr = find_threshold_price(rent_2yr,  calc_apr, calc_loan_type,
                                          calc_tax_rate, calc_ins_rate)

        piti_now = calc_piti(thresh_now, calc_apr, calc_loan_type,
                             calc_tax_rate, calc_ins_rate)
        piti_1yr = calc_piti(thresh_1yr, calc_apr, calc_loan_type,
                             calc_tax_rate, calc_ins_rate)
        piti_2yr = calc_piti(thresh_2yr, calc_apr, calc_loan_type,
                             calc_tax_rate, calc_ins_rate)

        # ── Rent context box ──────────────────────────────────────────────────
        if rent_note:
            st.caption(f"ℹ️ {rent_note}")

        st.markdown(
            f"<div style='background:#1e293b; border-radius:10px; padding:0.8rem 1.2rem; "
            f"margin-bottom:1rem; border-left:4px solid #38bdf8'>"
            f"<span style='color:#94a3b8; font-size:0.8rem'>Rent estimate for {calc_beds}bd in ZIP {calc_zip}</span><br>"
            f"<span style='color:#f1f5f9; font-size:1.3rem; font-weight:700'>${rent_est:,.0f}/mo today</span>"
            f"&nbsp;&nbsp;<span style='color:#64748b; font-size:0.85rem'>"
            f"→ ${rent_1yr:,.0f} in 1yr &nbsp; → ${rent_2yr:,.0f} in 2yr "
            f"(at {calc_rent_growth:.1f}%/yr growth)</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ── Three threshold cards ─────────────────────────────────────────────
        tc1, tc2, tc3 = st.columns(3)

        def threshold_card(col, horizon_label, icon, color, thresh_price,
                           rent_at_horizon, piti_detail):
            down_pct_label = "3.5% down (FHA)" if calc_loan_type.startswith("FHA") else "20% down"
            col.markdown(f"""
            <div style="background:#1e293b; border-radius:12px; padding:1.1rem 1.2rem;
                        border-top:4px solid {color}; height:100%">
                <div style="font-size:0.72rem; color:#94a3b8; text-transform:uppercase;
                            letter-spacing:0.08em; margin-bottom:0.3rem">
                    {icon} {horizon_label}
                </div>
                <div style="font-size:1.8rem; font-weight:700; color:{color}; line-height:1.1">
                    ${thresh_price:,.0f}
                </div>
                <div style="font-size:0.78rem; color:#64748b; margin:0.4rem 0 0.6rem 0">
                    max purchase price
                </div>
                <hr style="border-color:#334155; margin:0.5rem 0">
                <div style="font-size:0.8rem; color:#94a3b8; line-height:1.7">
                    Down payment &nbsp;<b style="color:#cbd5e1">${piti_detail['down']:,.0f}</b>
                    <span style="color:#475569"> ({down_pct_label})</span><br>
                    Monthly PITI &nbsp;<b style="color:#cbd5e1">${piti_detail['piti']:,.0f}/mo</b><br>
                    Rent at horizon &nbsp;<b style="color:#cbd5e1">${rent_at_horizon:,.0f}/mo</b><br>
                    Cash flow &nbsp;<b style="color:#22c55e">≈ $0/mo</b>
                    <span style="color:#475569"> (break-even)</span>
                </div>
                <hr style="border-color:#334155; margin:0.5rem 0">
                <div style="font-size:0.72rem; color:#475569; line-height:1.6">
                    P&I ${piti_detail['monthly_pi']:,.0f} &nbsp;+&nbsp;
                    MIP ${piti_detail['monthly_mip']:,.0f} &nbsp;+&nbsp;
                    Tax ${piti_detail['monthly_tax']:,.0f} &nbsp;+&nbsp;
                    Ins ${piti_detail['monthly_ins']:,.0f}
                </div>
            </div>
            """, unsafe_allow_html=True)

        threshold_card(tc1, "Immediate Cash Flow+", "✅", "#22c55e",
                       thresh_now, rent_est,  piti_now)
        threshold_card(tc2, "Break-even at 1 Year", "🟡", "#eab308",
                       thresh_1yr, rent_1yr, piti_1yr)
        threshold_card(tc3, "Break-even at 2 Years", "🟠", "#f97316",
                       thresh_2yr, rent_2yr, piti_2yr)

        # ── What this means summary ───────────────────────────────────────────
        st.markdown("")
        st.markdown(
            f"<div style='background:#0f172a; border-radius:10px; padding:0.9rem 1.2rem; "
            f"font-size:0.85rem; color:#94a3b8; margin-top:0.5rem'>"
            f"💡 <b style='color:#cbd5e1'>How to use this:</b> If you find a listing at or below "
            f"<b style='color:#22c55e'>${thresh_now:,.0f}</b>, it's cash flow positive from day one. "
            f"Between <b style='color:#22c55e'>${thresh_now:,.0f}</b> and "
            f"<b style='color:#eab308'>${thresh_1yr:,.0f}</b>, rent growth closes the gap within a year. "
            f"Up to <b style='color:#f97316'>${thresh_2yr:,.0f}</b> and you're break-even by year 2. "
            f"Above that it's high-risk territory at current rents."
            f"</div>",
            unsafe_allow_html=True,
        )

    else:
        st.info(
            "Select a ZIP code that has rent data to calculate thresholds. "
            "Run `enrich_rentcast.py` first to populate rent profiles, "
            "then pick a ZIP and bedroom count above."
        )

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("""
<div style="color:#475569; font-size:0.78rem; text-align:center">
    Data sourced from Redfin via your local scraper &nbsp;·&nbsp;
    FHA estimates are projections only, not financial advice &nbsp;·&nbsp;
    Refresh the page to reload data after a new scraper run
</div>
""", unsafe_allow_html=True)
