"""
export_kml.py — Export properties from properties.db to a KML file
suitable for import into Google My Maps.

Each investment tier becomes its own named folder (layer) in the KML,
so Google My Maps can colour them independently.

Usage:
    python export_kml.py                     # reads data/properties.db
    python export_kml.py --db my.db          # custom DB path
    python export_kml.py --out pins.kml      # custom output file
    python export_kml.py --tier immediately_rentable rentable_1_2_years

Google My Maps import:
    1. Open your map at https://www.google.com/maps/d/
    2. Click "Import" on any layer (or add a new layer first)
    3. Upload the .kml file — each <Folder> becomes a separate layer
    4. Style each layer's colour/icon inside My Maps after import
"""

import argparse
import os
import sqlite3
import xml.etree.ElementTree as ET
from xml.dom import minidom
import pandas as pd

# ── Tier metadata ──────────────────────────────────────────────────────────────
TIER_META = {
    "immediately_rentable": {
        "label": "✅ Cash Flow+ Today",
        "description": "Cash flow positive from day one at current rents.",
        # KML icon colours (aabbggrr format — Google Maps uses ABGR)
        "kml_color": "ff4ec322",   # green  (#22c34e)
        "icon_url": "https://maps.google.com/mapfiles/ms/icons/green-dot.png",
    },
    "rentable_1_2_years": {
        "label": "🟡 Cash Flow+ in 1–2 Years",
        "description": "Rent growth closes the gap within 1–2 years.",
        "kml_color": "ff08b3ea",   # yellow (#eab308)
        "icon_url": "https://maps.google.com/mapfiles/ms/icons/yellow-dot.png",
    },
    "high_risk": {
        "label": "🔴 High Risk (3+ yrs)",
        "description": "Break-even is 3+ years out at current projections.",
        "kml_color": "ff4444ef",   # red    (#ef4444)
        "icon_url": "https://maps.google.com/mapfiles/ms/icons/red-dot.png",
    },
    "no_rent_data": {
        "label": "⬜ No Rent Data",
        "description": "No rental comps available for this ZIP/bed count.",
        "kml_color": "ffb8a394",   # slate  (#94a3b8)
        "icon_url": "https://maps.google.com/mapfiles/ms/icons/purple-dot.png",
    },
}


def load_properties(db_path: str) -> pd.DataFrame:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT * FROM sale_properties", conn)
    conn.close()
    return df


def fmt_money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def build_description(row: pd.Series) -> str:
    cf = row.get("cash_flow_now") or 0
    cf_str = f"+{fmt_money(cf)}/mo" if cf >= 0 else f"-{fmt_money(abs(cf))}/mo"
    bey = row.get("break_even_year")
    bey_str = f"Year {int(bey)}" if pd.notna(bey) and bey else "—"
    listing_url = row.get("listing_url") or ""
    link_html = f'<a href="{listing_url}">Redfin listing</a>' if listing_url else ""

    lines = [
        f"<b>{row.get('address','')}</b>",
        f"{row.get('city','')}, {row.get('state','')} {row.get('zip','')}",
        "",
        f"<b>Price:</b> {fmt_money(row.get('price'))}",
        f"<b>Beds/Baths:</b> {int(row.get('beds') or 0)}bd / {row.get('baths','?')}ba",
        f"<b>Sqft:</b> {row.get('sqft','—')}",
        f"<b>Days on market:</b> {row.get('days_on_market','—')}",
        "",
        f"<b>Monthly PITI:</b> {fmt_money(row.get('monthly_piti'))}/mo",
        f"<b>Rent estimate:</b> {fmt_money(row.get('rent_estimate'))}/mo",
        f"<b>Cash flow:</b> {cf_str}",
        f"<b>Break-even year:</b> {bey_str}",
        f"<b>Area:</b> {row.get('area_label','—')}",
    ]
    if link_html:
        lines += ["", link_html]
    return "<br>".join(lines)


def build_kml(df: pd.DataFrame, tiers: list[str]) -> str:
    kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = ET.SubElement(kml, "Document")
    ET.SubElement(doc, "name").text = "Investment Properties"
    ET.SubElement(doc, "description").text = (
        "Properties colour-coded by investment tier. "
        "Import into Google My Maps and style each layer."
    )

    # One Style per tier
    for tier_key, meta in TIER_META.items():
        style = ET.SubElement(doc, "Style", id=tier_key)
        icon_style = ET.SubElement(style, "IconStyle")
        ET.SubElement(icon_style, "color").text = meta["kml_color"]
        ET.SubElement(icon_style, "scale").text = "1.1"
        icon = ET.SubElement(icon_style, "Icon")
        ET.SubElement(icon, "href").text = meta["icon_url"]
        label_style = ET.SubElement(style, "LabelStyle")
        ET.SubElement(label_style, "scale").text = "0"   # hide label clutter on map

    # One Folder per tier
    for tier_key in tiers:
        meta = TIER_META.get(tier_key)
        if not meta:
            continue
        tier_df = df[
            (df["tier"] == tier_key)
            & df["latitude"].notna()
            & df["longitude"].notna()
        ]
        if tier_df.empty:
            continue

        folder = ET.SubElement(doc, "Folder")
        ET.SubElement(folder, "name").text = meta["label"]
        ET.SubElement(folder, "description").text = (
            meta["description"] + f" ({len(tier_df)} properties)"
        )

        for _, row in tier_df.iterrows():
            pm = ET.SubElement(folder, "Placemark")
            addr = row.get("address", "") or "Unknown"
            cf = row.get("cash_flow_now") or 0
            cf_str = f"+${cf:,.0f}/mo" if cf >= 0 else f"-${abs(cf):,.0f}/mo"
            ET.SubElement(pm, "name").text = f"{addr} ({cf_str})"
            ET.SubElement(pm, "description").text = build_description(row)
            ET.SubElement(pm, "styleUrl").text = f"#{tier_key}"
            point = ET.SubElement(pm, "Point")
            ET.SubElement(point, "coordinates").text = (
                f"{float(row['longitude']):.6f},{float(row['latitude']):.6f},0"
            )

    # Pretty-print
    raw = ET.tostring(kml, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ")
    # Remove the extra XML declaration minidom adds
    lines = pretty.split("\n")
    if lines[0].startswith("<?xml"):
        lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Export properties to KML for Google My Maps")
    parser.add_argument("--db",  default=os.environ.get("DB_PATH", "data/properties.db"),
                        help="Path to properties.db")
    parser.add_argument("--out", default="properties.kml",
                        help="Output KML file path")
    parser.add_argument("--tier", nargs="+",
                        default=list(TIER_META.keys()),
                        choices=list(TIER_META.keys()),
                        help="Which tiers to include (default: all)")
    args = parser.parse_args()

    print(f"Loading properties from {args.db} …")
    df = load_properties(args.db)
    print(f"  {len(df)} total properties found")

    kml_str = build_kml(df, args.tier)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(kml_str)

    # Summary
    for tier_key in args.tier:
        meta = TIER_META.get(tier_key, {})
        count = len(df[(df["tier"] == tier_key) & df["latitude"].notna() & df["longitude"].notna()])
        print(f"  {meta.get('label', tier_key)}: {count} pins")

    print(f"\n✅ Saved → {args.out}")
    print("\nNext steps:")
    print("  1. Go to https://www.google.com/maps/d/")
    print("  2. Open your map and click 'Import' on a layer")
    print("  3. Upload the .kml file")
    print("  4. Each tier will appear as its own layer with colour-coded pins")


if __name__ == "__main__":
    main()
