"""
app.py — Streamlit web app for browsing investment property data.
Drop this file alongside your properties.db (or configure DB_PATH below).
"""

import sqlite3
import os
import pandas as pd
import streamlit as st

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
tab_map, tab_table, tab_rent = st.tabs(["🗺️ Map", "📊 Table", "📈 Rent Profiles"])

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
            redfin_link = (
                f'<a href="{row["listing_url"]}" target="_blank" '
                f'style="font-size:0.8rem; color:#38bdf8; text-decoration:none">View on Redfin →</a>'
                if row.get("listing_url") else ""
            )

            st.markdown(f"""
            <div style="background:#1e293b; border-radius:10px; padding:0.9rem 1.1rem;
                        margin-bottom:0.5rem; border-left: 4px solid {meta['color']}">
                <div style="display:flex; justify-content:space-between; align-items:baseline">
                    <b style="color:#f1f5f9; font-size:1rem">{row.get('address','Unknown')}</b>
                    <span style="color:{cf_color}; font-weight:700; font-size:1rem">{cf_str}</span>
                </div>
                <div style="color:#94a3b8; font-size:0.83rem; margin-top:3px">
                    {row.get('city','')}, {row.get('zip','')} &nbsp;·&nbsp;
                    ${row.get('price',0):,.0f} &nbsp;·&nbsp;
                    {int(row.get('beds') or 0)}bd / {row.get('baths','?')}ba &nbsp;·&nbsp;
                    PITI <b style="color:#cbd5e1">${row.get('monthly_piti',0):,.0f}/mo</b>
                    &nbsp;·&nbsp; Rent est. <b style="color:#cbd5e1">${row.get('rent_estimate',0) or 0:,.0f}/mo</b>
                    {"&nbsp;·&nbsp; " + bey_str if bey_str else ""}
                </div>
                <div style="margin-top:5px; display:flex; gap:0.8rem; align-items:center">
                    <span style="background:{meta['color']}22; color:{meta['color']};
                                 font-size:0.72rem; font-weight:600; padding:2px 8px;
                                 border-radius:999px; letter-spacing:0.04em">
                        {meta['icon']} {meta['label']}
                    </span>
                    {redfin_link}
                </div>
            </div>
            """, unsafe_allow_html=True)


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

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("""
<div style="color:#475569; font-size:0.78rem; text-align:center">
    Data sourced from Redfin via your local scraper &nbsp;·&nbsp;
    FHA estimates are projections only, not financial advice &nbsp;·&nbsp;
    Refresh the page to reload data after a new scraper run
</div>
""", unsafe_allow_html=True)
