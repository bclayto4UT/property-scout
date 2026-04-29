"""
rent_profile.py — Builds a neighborhood rent profile from scraped rental listings.
Groups by (zip, beds) and computes low / median / high / avg rent.
"""

from collections import defaultdict
from mortgage import safe_float


def build_profiles(rentals: list[dict]) -> list[dict]:
    """
    Input: list of normalized rental dicts (from database.normalize_rental)
    Output: list of rent_profile dicts ready to insert into the DB
    """
    buckets = defaultdict(list)

    for r in rentals:
        zip_code = r.get("zip")
        beds     = r.get("beds")
        rent     = safe_float(r.get("monthly_rent"))

        if zip_code and rent > 0:
            # Normalize beds: treat None/empty as 0 (studio)
            try:
                bed_count = int(float(beds)) if beds else 0
            except (ValueError, TypeError):
                bed_count = 0

            buckets[(zip_code, bed_count)].append(rent)

    profiles = []
    for (zip_code, beds), rents in buckets.items():
        rents_sorted = sorted(rents)
        n = len(rents_sorted)
        mid = n // 2
        median = (rents_sorted[mid - 1] + rents_sorted[mid]) / 2 if n % 2 == 0 else rents_sorted[mid]

        profiles.append({
            "zip":         zip_code,
            "beds":        beds,
            "count":       n,
            "low_rent":    round(rents_sorted[0], 2),
            "median_rent": round(median, 2),
            "high_rent":   round(rents_sorted[-1], 2),
            "avg_rent":    round(sum(rents_sorted) / n, 2),
        })

    return profiles

from typing import Optional, Tuple  # add this near the top of the file

def lookup_rent(profiles: list[dict], zip_code: str, beds) -> Tuple[Optional[float], str]:
    """
    Find the best rent estimate for a zip+bed combo.
    Falls back to same-zip average if exact match not found.
    Returns (estimate, source_description).
    """
    try:
        bed_count = int(float(beds)) if beds else 0
    except (ValueError, TypeError):
        bed_count = 0

    # Exact match: same zip + same bed count
    for p in profiles:
        if p["zip"] == zip_code and p["beds"] == bed_count:
            return p["median_rent"], f"median of {p['count']} rentals in {zip_code} ({bed_count}bd)"

    # Fallback: same zip, any bed count
    same_zip = [p for p in profiles if p["zip"] == zip_code]
    if same_zip:
        avg = round(sum(p["median_rent"] for p in same_zip) / len(same_zip), 2)
        return avg, f"avg of {len(same_zip)} zip-level profiles in {zip_code} (bed count fallback)"

    return None, "no rent data available"
