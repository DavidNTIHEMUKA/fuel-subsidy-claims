"""One call from uploaded files to validated lines and an Excel report."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .cleaning import (clean_text, header_key, CLAIM_COLUMNS, CLAIM_REQUIRED, EBM_COLUMNS, EBM_REQUIRED, clean_claim, clean_ebm,
                       normalize_slip, normalize_tin, normalize_product, parse_datetime, parse_interval,
                       parse_number, read_table)
from .config import DEFAULT, Settings
from .report import to_excel
from .rules import ClaimContext, summarise, validate_claim


DEFAULT_PRICE_FILE = Path(__file__).resolve().parent.parent / "reference" / "rwanda_fuel_pump_prices_nov_2026.xlsx"
_DATE_IN_TEXT = re.compile(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})")


def _price_product(name):
    """Map a price-list product name to the engine's product codes; Mogas and LPG stay separate."""
    s = clean_text(name).upper()
    if not s:
        return None
    if "LPG" in s or "GAS (KG)" in s:
        return "LPG"
    if "MOGAS" in s and not any(k in s for k in ("PMS", "ESSENCE", "GASOLINE")):
        return "MOGAS"
    p = normalize_product(s)
    return p if p != "UNKNOWN" else s


def _price_date(v):
    """'Reported current on 3 Nov 2026', '2026-06-01', a date cell, or empty (= no start date)."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or not clean_text(v):
        return pd.NaT
    t = parse_datetime(v)[0]
    if t is not None:
        return t.normalize()
    m = _DATE_IN_TEXT.search(clean_text(v))
    if m:
        from .cleaning import _MONTHS
        mon = _MONTHS.get(m.group(2).lower())
        if mon:
            return pd.Timestamp(int(m.group(3)), mon, int(m.group(1)))
    return pd.NaT


def load_rura_prices(file) -> pd.DataFrame | None:
    """Price list: one row per product and price, with an optional date.

    Accepts the simple layout (product, effective_from, price) and the ASSIMPER/RURA
    layout (Fuel product, Retail pump price, Unit, Price date/source update, Source,
    Source URL). Rows without a date apply to any transaction date.
    """
    if file is None:
        return None
    name = str(getattr(file, "name", file)).lower()
    df = pd.read_csv(file, dtype=str) if name.endswith(".csv") else pd.read_excel(file, dtype=object)
    cols = {c: header_key(c) for c in df.columns}
    pick = lambda test: next((c for c, k in cols.items() if test(k)), None)
    c_prod = pick(lambda k: "product" in k or k in ("fuel", "item"))
    c_price = pick(lambda k: "price" in k and "date" not in k and "update" not in k)
    c_date = pick(lambda k: k in ("effectivefrom", "date", "pricedate") or "date" in k or "effective" in k)
    c_unit = pick(lambda k: k == "unit")
    c_src = pick(lambda k: k == "source")
    c_url = pick(lambda k: "url" in k)
    if not (c_prod and c_price):
        raise ValueError("Price list needs a product column and a price column")
    out = pd.DataFrame({
        "product_raw": df[c_prod].map(clean_text),
        "product": df[c_prod].map(_price_product),
        "price": df[c_price].map(lambda v: parse_number(v, "price")[0]),
        "effective_from": df[c_date].map(_price_date) if c_date else pd.NaT,
        "unit": df[c_unit].map(clean_text) if c_unit else "",
        "source": df[c_src].map(clean_text) if c_src else "",
        "source_url": df[c_url].map(clean_text) if c_url else "",
    })
    out = out.dropna(subset=["product", "price"])
    out["effective_from"] = pd.to_datetime(out["effective_from"])
    return out.reset_index(drop=True)


def price_note(prices: pd.DataFrame | None, start=None) -> str:
    if prices is None or prices.empty:
        return ""
    parts = []
    for prod in ["DIESEL", "PETROL"]:
        p = prices[prices["product"] == prod]
        if p.empty:
            continue
        dated = p.dropna(subset=["effective_from"])
        undated = p[p["effective_from"].isna()]
        latest = dated.sort_values("effective_from").iloc[-1] if not dated.empty else undated.iloc[0]
        when = f"{latest.effective_from:%d %b %Y}" if pd.notna(latest.effective_from) else "undated"
        parts.append(f"{prod.title()} {latest.price:,.0f} RWF/L ({when})")
    src = ", ".join(sorted({s for s in prices["source"] if s})) or "uploaded list"
    note = f"RURA/pump price reference: {'; '.join(parts)} — source {src}"
    if start is not None:
        earliest = prices.dropna(subset=["effective_from"])["effective_from"].min()
        if pd.notna(earliest) and pd.Timestamp(start) < earliest:
            note += (f". Transactions before {earliest:%d %b %Y} use the closest listed price "
                     "(undated rows, or the earliest dated one) — confirm it was in force for this period")
    return note


def load_history(file) -> dict:
    """Earlier paid lines: any file with an 'EBM Slip No'/'EBM invoice matched' column (+ optional 'claim')."""
    if file is None:
        return {}
    name = str(getattr(file, "name", file)).lower()
    df = pd.read_csv(file, dtype=str) if name.endswith(".csv") else pd.read_excel(file, dtype=str)
    col = next((c for c in df.columns if "ebm" in c.lower() and ("slip" in c.lower() or "invoice" in c.lower())), None)
    if col is None:
        return {}
    ref = next((c for c in df.columns if c.lower() in ("claim", "submission", "claim_ref")), None)
    out = {}
    for _, r in df.iterrows():
        key = normalize_slip(r[col]).key
        if key:
            out[key] = str(r[ref]) if ref else "an earlier claim"
    return out


def process(claim_file, ebm_file, meta: dict, rura_file=None, history_file=None,
            settings: Settings = DEFAULT, register_history: dict | None = None):
    claim_raw, p1 = read_table(claim_file, CLAIM_COLUMNS, CLAIM_REQUIRED, "Claim file")
    ebm_raw, p2 = read_table(ebm_file, EBM_COLUMNS, EBM_REQUIRED, "EBM file")
    problems = p1 + p2
    blocking = [p for p in problems if "not found" in p or "no header" in p or "could not" in p]
    if blocking:
        return None, problems, None

    claim = clean_claim(claim_raw, settings)

    # ---- Consumption interval: declared by the supplier (mandatory) ---------
    first_year = claim["closed_at"].dropna().min().year if claim["closed_at"].notna().any() else None
    file_start, file_end = parse_interval(claim_raw.attrs.get("preamble", ""), default_year=first_year)
    given_start = pd.Timestamp(meta["period_start"]).normalize() if meta.get("period_start") else None
    given_end = pd.Timestamp(meta["period_end"]).normalize() if meta.get("period_end") else None
    if given_start is not None and given_end is not None:
        start, end, source = given_start, given_end, "entered at submission"
        if file_start is not None and (file_start, file_end) != (given_start, given_end):
            problems.append(f"Interval in the claim file ({file_start:%d/%m/%Y}–{file_end:%d/%m/%Y}) differs from the "
                            f"interval entered ({given_start:%d/%m/%Y}–{given_end:%d/%m/%Y}); the entered one was used")
    elif file_start is not None:
        start, end, source = file_start, file_end, "read from the claim file"
    else:
        problems.append("Consumption interval not declared: the supplier must state the period from–to "
                        "(enter it, or put e.g. 'Period: 21/09/2026 - 30/09/2026' above the table)")
        return None, problems, None
    if end < start:
        problems.append(f"Consumption interval ends ({end:%d/%m/%Y}) before it starts ({start:%d/%m/%Y})")
        return None, problems, None

    # Re-read the dates knowing the interval, so dates that can be read both ways are settled correctly
    claim = clean_claim(claim_raw, settings, interval=(start, end))
    if claim.attrs.get("date_summary"):
        problems.append(claim.attrs["date_summary"])
    ebm = clean_ebm(ebm_raw, settings, interval=(start, end))
    if ebm.attrs.get("date_summary"):
        problems.append(ebm.attrs["date_summary"])

    ctx = ClaimContext(
        claimant_tin=normalize_tin(meta.get("tin")),
        period_start=start,
        period_end=end,
        rura_prices=load_rura_prices(rura_file),
        history_keys={**load_history(history_file), **(register_history or {})},
    )
    if ctx.rura_prices is None and DEFAULT_PRICE_FILE.exists():
        ctx.rura_prices = load_rura_prices(DEFAULT_PRICE_FILE)          # built-in reference prices
    if ctx.rura_prices is None:
        problems.append("No RURA price list loaded: under-pricing rule (R4) was skipped")
    else:
        problems.append(price_note(ctx.rura_prices, start))
    if not ctx.claimant_tin:
        problems.append("No supplier TIN given: seller TIN rule (R7) was skipped")
    lines = validate_claim(claim, ebm, ctx, settings)
    meta = dict(meta, period_start=ctx.period_start, period_end=ctx.period_end,
                interval=interval_check(lines, ebm, ctx, source))
    lines.attrs["interval"] = meta["interval"]
    lines.attrs["meta"] = {k: v for k, v in meta.items() if k != "interval"}
    return lines, problems, to_excel(lines, meta, settings, problems)


def interval_check(lines, ebm, ctx, source) -> pd.DataFrame:
    """Declared interval vs the dates actually found in the claim and in EBM."""
    end = ctx.period_end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    closed = pd.to_datetime(lines["closed_at"])
    matched = pd.to_datetime(lines["ebm_datetime"])
    out_claim = int(((closed < ctx.period_start) | (closed > end)).sum())
    out_ebm = int(((matched < ctx.period_start) | (matched > end)).sum())
    days = (ctx.period_end - ctx.period_start).days + 1
    rng = lambda s: f"{s.min():%d/%m/%Y} – {s.max():%d/%m/%Y}" if s.notna().any() else "—"
    return pd.DataFrame([
        ("Consumption interval declared", f"{ctx.period_start:%d/%m/%Y} – {ctx.period_end:%d/%m/%Y} "
                                          f"({days} days, {source})"),
        ("Transaction dates in claim (Closed at)", rng(closed)),
        ("Dates of matched EBM invoices", rng(matched)),
        ("Lines whose Closed at is outside the interval", out_claim),
        ("Lines whose EBM invoice date is outside the interval", out_ebm),
        ("EBM file covers", rng(pd.to_datetime(ebm["sdc_datetime"]))),
    ], columns=["Interval check", "Value"])


__all__ = ["process", "summarise"]
