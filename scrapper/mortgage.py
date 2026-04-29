"""
mortgage.py — FHA mortgage calculations and investment tier classification.
"""

from config import FHA, MARKET


def safe_float(value, default=0.0) -> float:
    """Parse a value to float, stripping $, commas, and whitespace."""
    try:
        if value is None:
            return default
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        return float(cleaned) if cleaned else default
    except (ValueError, TypeError):
        return default


def calc_fha_mortgage(purchase_price: float) -> dict:
    """
    Compute a full FHA PITI breakdown for a given purchase price.

    Structure:
      Base loan     = price × (1 - 0.035)
      UFMIP         = base loan × 0.0175  (rolled into loan)
      Total loan    = base loan + UFMIP
      P&I           = standard amortization formula on total loan
      Monthly MIP   = total loan × 0.0055 / 12
      Monthly tax   = price × property_tax_rate / 12
      Monthly ins   = price × insurance_rate / 12
      PITI          = P&I + MIP + tax + ins
    """
    if purchase_price <= 0:
        return {}

    dp_rate     = FHA["down_payment_pct"] / 100
    base_loan   = purchase_price * (1 - dp_rate)
    ufmip       = base_loan * (FHA["upfront_mip_pct"] / 100)
    total_loan  = base_loan + ufmip

    r = (FHA["interest_rate_pct"] / 100) / 12   # monthly interest rate
    n = FHA["loan_term_months"]

    if r == 0:
        pi = total_loan / n
    else:
        pi = total_loan * (r * (1 + r) ** n) / ((1 + r) ** n - 1)

    monthly_mip = total_loan * (FHA["annual_mip_pct"] / 100) / 12
    monthly_tax = purchase_price * (MARKET["property_tax_rate_pct"] / 100) / 12
    monthly_ins = purchase_price * (MARKET["insurance_rate_pct"] / 100) / 12

    piti = pi + monthly_mip + monthly_tax + monthly_ins

    return {
        "down_payment":      round(purchase_price * dp_rate, 2),
        "base_loan":         round(base_loan, 2),
        "ufmip":             round(ufmip, 2),
        "total_loan":        round(total_loan, 2),
        "monthly_pi":        round(pi, 2),
        "monthly_mip":       round(monthly_mip, 2),
        "monthly_tax":       round(monthly_tax, 2),
        "monthly_insurance": round(monthly_ins, 2),
        "monthly_piti":      round(piti, 2),
        "exceeds_fha_limit": int(purchase_price > FHA["county_loan_limit"]),
        "fha_rate_used":     FHA["interest_rate_pct"],
    }


def project_rent(current_rent: float, years: int) -> float:
    """Project rent forward N years at the configured annual growth rate."""
    rate = MARKET["rent_growth_rate_pct"] / 100
    return round(current_rent * (1 + rate) ** years, 2)


def classify(monthly_piti: float, rent_estimate: float) -> dict:
    """
    Determine investment tier based on the break-even year.

    Tiers:
      immediately_rentable  → cash-flow positive today (year 0)
      rentable_1_2_years    → breaks even at projected rent within 1–2 years
      high_risk             → break-even is 3+ years out, or never within 10 years
      no_rent_data          → rent estimate unavailable
    """
    if not rent_estimate or rent_estimate <= 0:
        return {
            "tier":            "no_rent_data",
            "cash_flow_now":   None,
            "break_even_year": None,
            "rent_at_1yr":     None,
            "rent_at_2yr":     None,
            "rent_at_5yr":     None,
        }

    cash_flow_now = round(rent_estimate - monthly_piti, 2)
    break_even_year = None

    for yr in range(0, 11):
        if project_rent(rent_estimate, yr) >= monthly_piti:
            break_even_year = yr
            break

    if break_even_year == 0:
        tier = "immediately_rentable"
    elif break_even_year in (1, 2):
        tier = "rentable_1_2_years"
    else:
        tier = "high_risk"   # covers None (never) and 3+

    return {
        "tier":            tier,
        "cash_flow_now":   cash_flow_now,
        "break_even_year": break_even_year,
        "rent_at_1yr":     project_rent(rent_estimate, 1),
        "rent_at_2yr":     project_rent(rent_estimate, 2),
        "rent_at_5yr":     project_rent(rent_estimate, 5),
    }
