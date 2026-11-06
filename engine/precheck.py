"""Checks shown to the supplier before the request is confirmed (no EBM needed)."""
from __future__ import annotations

import pandas as pd

from .rules import _rura_price


def submission_warnings(clean: pd.DataFrame, start, end, official_rates: dict, prices: pd.DataFrame | None,
                        own_tin: str | None = None):
    """Return a table: Check, Lines, What to do — empty when everything is consistent."""
    rows = []
    n = len(clean)
    dates = pd.to_datetime(clean["closed_at"], errors="coerce")

    # 1. consumption interval
    if start is None or end is None:
        rows.append(("Consumption interval", n, "No interval declared — enter the period from–to."))
    else:
        s, e = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        out = dates.notna() & ((dates < s) | (dates > e))
        if out.any():
            rows.append(("Dates outside the interval", int(out.sum()),
                         f"{int(out.sum())} sale(s) are dated outside {pd.Timestamp(start):%d/%m/%Y}–"
                         f"{pd.Timestamp(end):%d/%m/%Y} (e.g. row {int(clean.loc[out, 'source_row'].iloc[0])}). "
                         "They will be rejected: correct the dates or the interval."))
        if pd.Timestamp(end) > pd.Timestamp.now():
            rows.append(("Interval in the future", 0, f"The interval ends after today ({pd.Timestamp.now():%d/%m/%Y})."))
    future = dates > pd.Timestamp.now()
    if future.any():
        rows.append(("Sales dated in the future", int(future.sum()), "Check the 'Closed at' dates."))

    # 2. subsidy rate vs official
    if official_rates:
        off = clean["product"].map(lambda p: official_rates.get(str(p).upper()))
        rate = pd.to_numeric(clean["subsidy_rate"], errors="coerce")
        diff = rate.notna() & off.notna() & ((rate - off).abs() > 0.01)
        if diff.any():
            found = ", ".join(f"{v:g}" for v in sorted(rate[diff].unique())[:4])
            want = ", ".join(f"{p.title()} {v:g}" for p, v in official_rates.items())
            rows.append(("Subsidy rate different from the official rate", int(diff.sum()),
                         f"Claimed rate(s) {found}; official: {want} RWF/L. Payment is made at the official rate."))
        missing = rate.isna()
        if missing.any():
            rows.append(("Subsidy rate missing", int(missing.sum()), "Fill 'subsidy rate' for every line."))

    # 3. pump price vs RURA price
    if prices is not None and not prices.empty:
        ref = [(_rura_price(prices, p, d) if pd.notna(d) else None) for p, d in zip(clean["product"], dates)]
        ref = pd.Series(ref, index=clean.index, dtype="float")
        pu = pd.to_numeric(clean["unit_price"], errors="coerce")
        below = pu.notna() & ref.notna() & (pu < ref - 1)
        above = pu.notna() & ref.notna() & (pu > ref + 1)
        if below.any():
            rows.append(("Fuel price below the RURA price", int(below.sum()),
                         f"P.U below the reference ({', '.join(f'{v:,.0f}' for v in sorted(pu[below].unique())[:3])}); "
                         "these lines will be rejected unless the price is correct."))
        if above.any():
            rows.append(("Fuel price above the RURA price", int(above.sum()),
                         f"P.U above the reference ({', '.join(f'{v:,.0f}' for v in sorted(pu[above].unique())[:3])}); "
                         "check the price."))

    # 4. OMC TIN (the fuel supplier's own TIN on every line)
    if "omc_tin" in clean:
        ot = clean["omc_tin"].fillna("")
        if (ot == "").any():
            rows.append(("OMC TIN missing", int((ot == "").sum()),
                         "Write your TIN (fuel supplier) on every line; it is checked against the seller on the EBM receipt."))
        if own_tin:
            other = (ot != "") & (ot != str(own_tin).strip())
            if other.any():
                rows.append(("OMC TIN different from your TIN", int(other.sum()),
                             f"These lines give TIN {', '.join(sorted(ot[other].unique())[:3])}, not {own_tin}. "
                             "Only fuel sold by you can be claimed — correct the TIN or remove the lines."))
        elif ot[ot != ""].nunique() > 1:
            rows.append(("Several OMC TINs in one claim", int((ot != "").sum()),
                         "A claim covers one fuel supplier: use one OMC TIN."))

    # 5. products, slips, arithmetic
    bad_prod = ~clean["product"].isin(["DIESEL", "PETROL"])
    if bad_prod.any():
        rows.append(("Product not subsidised or not recognised", int(bad_prod.sum()), "Use AGO (diesel) or PMS (petrol)."))
    slips = clean["slip_clean"].replace("", pd.NA).dropna()
    dup = slips.duplicated(keep=False)
    if dup.any():
        rows.append(("Same EBM Slip No on several lines", int(dup.sum()), "Each sale needs its own EBM receipt."))
    fmt = clean["format_issues"] != ""
    if fmt.any():
        rows.append(("Lines with missing or wrong data", int(fmt.sum()), "See 'Fix before submitting'."))
    amt = clean["warnings"] != ""
    if amt.any():
        rows.append(("Amount or subsidy not equal to quantity × price/rate", int(amt.sum()), "Check the amounts."))
    return pd.DataFrame(rows, columns=["Check", "Lines", "What to do"])
