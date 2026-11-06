"""Match cleaned claim lines to EBM invoices and apply the subsidy rules.

Outcome per line:
  ACCEPTED  - all rules passed
  PARTIAL   - accepted up to the EBM quantity, excess rejected
  REJECTED  - clear evidence the line is not eligible (reason given)
  REVIEW    - doubtful; a person must decide (counted as pending, not paid)

Design rule: when the evidence is ambiguous, the engine sends the line to
REVIEW instead of rejecting it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .cleaning import merge_key
from .config import DEFAULT, Settings

FUEL = {"DIESEL", "PETROL", "KEROSENE"}
REFUND_TYPES = {"NR", "CR", "TR"}          # EBM refund receipts
NON_SALE_TYPES = {"TS", "PS"}              # training / proforma

RULES = {
    "R0": "Usable EBM reference",
    "R1": "Invoice exists in EBM",
    "R2": "No duplicate invoice",
    "R3": "Claimed quantity ≤ EBM quantity",
    "R4": "Unit price not below RURA price",
    "R5": "Invoice is taxable (not exempt)",
    "R6": "Product matches EBM",
    "R7": "Seller TIN and consumption interval",
    "R8": "Consumption anomalies (human review)",
    "R9": "Invoice is a valid sale (not refunded/cancelled)",
    "R10": "Invoice issued to the transport operator (buyer TIN)",
}


@dataclass
class ClaimContext:
    claimant_tin: str | None = None
    period_start: pd.Timestamp | None = None
    period_end: pd.Timestamp | None = None
    rura_prices: pd.DataFrame | None = None      # product, effective_from, price
    history_keys: dict = field(default_factory=dict)  # ebm_key -> earlier claim ref


def _edit1(a: str, b: str) -> bool:
    """True if strings differ by at most one insert/delete/substitute."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(x != y for x, y in zip(a, b)) == 1
    if la > lb:
        a, b = b, a
    for i in range(len(b)):
        if a == b[:i] + b[i + 1:]:
            return True
    return False


def _rura_price(prices, product, when):
    """Price in force on `when`: the latest dated price on or before it; otherwise an undated
    price; otherwise the earliest later-dated price (the pipeline notes this case)."""
    if prices is None or prices.empty or when is None or pd.isna(when):
        return None
    p = prices[prices["product"] == product]
    if p.empty:
        return None
    eff = pd.to_datetime(p["effective_from"])
    before = p[eff.notna() & (eff <= when)]
    if not before.empty:
        return float(before.sort_values("effective_from").iloc[-1]["price"])
    undated = p[eff.isna()]
    if not undated.empty:
        return float(undated["price"].iloc[0])
    return float(p.sort_values("effective_from").iloc[0]["price"])


def _in_interval(ctx, *times):
    """True if any given time falls inside the declared interval, False if all
    known times fall outside, None if there is no interval or no time."""
    if ctx.period_start is None or ctx.period_end is None:
        return None
    end = ctx.period_end.normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    known = [t for t in times if t is not None and not pd.isna(t)]
    if not known:
        return None
    return any(ctx.period_start <= t <= end for t in known)


def _interval_text(ctx):
    return f"{ctx.period_start:%d/%m/%Y}–{ctx.period_end:%d/%m/%Y}"


def build_invoice_index(ebm: pd.DataFrame) -> pd.DataFrame:
    """One row per (ebm_key, product) with fuel quantity and invoice facts.

    Exact duplicate EBM rows (same invoice, item, quantity, price, time and signature —
    an extraction artefact) are counted once, so they cannot inflate the EBM quantity.
    """
    e = ebm.dropna(subset=["ebm_key"]).copy()
    dup_cols = [c for c in ["ebm_key", "item_name", "item_qty", "item_unit_price", "sdc_datetime", "signature",
                            "invoice_type"] if c in e]
    e = e.drop_duplicates(subset=dup_cols)
    e["is_refund"] = e["invoice_type"].isin(REFUND_TYPES)
    e["is_nonsale"] = e["invoice_type"].isin(NON_SALE_TYPES)
    sales = e[~e["is_refund"]].copy()
    sales["product"] = sales["product"].fillna("UNKNOWN")
    sales["tax_type"] = sales["tax_type"].fillna("")
    sales["amount_flag_false"] = sales["match_amount"].map(lambda v: v is False)
    gb = sales.groupby(["ebm_key", "product"], sort=False)
    agg = gb.agg(sdc_id=("sdc_id", "first"), invoice=("invoice", "first"),
                 seller_tin=("seller_tin", "first"), buyer_tin=("buyer_tin", "first"),
                 sdc_datetime=("sdc_datetime", "first"), ebm_qty=("item_qty", "sum"),
                 ebm_unit_price=("item_unit_price", "min"), tax_types=("tax_type", "first"),
                 item_names=("item_name", "first"), amount_flag_false=("amount_flag_false", "any"),
                 nonsale=("is_nonsale", "any"), n_tax=("tax_type", "nunique"),
                 n_items=("item_name", "nunique")).reset_index()
    # Rare multi-value cases: list every tax type / item name (fast path keeps 'first')
    multi = agg["n_tax"].gt(1) | agg["n_items"].gt(1)
    if multi.any():
        keys = set(agg.loc[multi, "ebm_key"])
        sub = sales[sales["ebm_key"].isin(keys)].groupby(["ebm_key", "product"])
        taxes = sub["tax_type"].agg(lambda s: ",".join(sorted({t for t in s if t})))
        names = sub["item_name"].agg(lambda s: " / ".join(sorted(set(s))))
        idx = pd.MultiIndex.from_frame(agg.loc[multi, ["ebm_key", "product"]])
        agg.loc[multi, "tax_types"] = taxes.reindex(idx).values
        agg.loc[multi, "item_names"] = names.reindex(idx).values
    agg["match_amount"] = ~agg["amount_flag_false"]
    agg = agg.drop(columns=["amount_flag_false", "n_tax", "n_items"])
    refunded = set(e.loc[e["is_refund"], "ebm_key"])
    agg["refunded"] = agg["ebm_key"].isin(refunded)
    return agg


def _time_ok(closed, alt, ebm_time, hours):
    """Return (ok, used_alt, gap_hours)."""
    if ebm_time is None or pd.isna(ebm_time) or closed is None or pd.isna(closed):
        return True, False, None
    gap = abs((closed - ebm_time).total_seconds()) / 3600
    if gap <= hours:
        return True, False, gap
    if alt is not None and not pd.isna(alt):
        gap_alt = abs((alt - ebm_time).total_seconds()) / 3600
        if gap_alt <= hours:
            return True, True, gap_alt
    return False, False, gap


def validate_claim(claim: pd.DataFrame, ebm: pd.DataFrame, ctx: ClaimContext | None = None,
                   settings: Settings = DEFAULT) -> pd.DataFrame:
    ctx = ctx or ClaimContext()
    inv = build_invoice_index(ebm)
    inv_fuel = inv[inv["product"].isin(FUEL)]
    key_pos = inv.groupby("ebm_key", sort=False).indices    # key -> row positions
    known_sdc = set(inv["sdc_id"].dropna())
    ebm_min = ebm["sdc_datetime"].min() if "sdc_datetime" in ebm else None
    ebm_max = ebm["sdc_datetime"].max() if "sdc_datetime" in ebm else None

    # Subsidy rate used for payment
    claim_rates = claim["subsidy_rate"].dropna()
    modal_rate = float(claim_rates.mode().iloc[0]) if not claim_rates.empty else None
    pay_rate = settings.official_subsidy_rate or modal_rate

    out = claim.copy().reset_index(drop=True)
    cols = {c: None for c in ["matched_key", "match_method", "ebm_qty", "ebm_unit_price", "ebm_datetime",
                              "ebm_tax_type", "ebm_item", "ebm_seller_tin", "ebm_buyer_tin", "rura_price"]}
    for c in cols:
        out[c] = None
    status = ["ACCEPTED"] * len(out)
    reasons = [[] for _ in range(len(out))]
    reviews = [[] for _ in range(len(out))]
    notes = [[] for _ in range(len(out))]
    accepted_qty = out["qty"].fillna(0).astype(float).tolist()

    def reject(i, code, text):
        status[i] = "REJECTED"
        accepted_qty[i] = 0.0
        reasons[i].append(f"{code} · {text}")

    def review(i, code, text):
        reviews[i].append(f"{code} · {text}")

    # Invoices claimed by their exact slip number are never offered to the fallback match
    used_by_fallback = set(k for k in out["ebm_key"].dropna() if k in key_pos)

    # ---------- 1. Find the EBM invoice for every line -------------------------
    for i, r in out.iterrows():
        r = {k: (None if pd.api.types.is_scalar(x) and pd.isna(x) else x) for k, x in r.items()}
        if r["qty"] is None or pd.isna(r["qty"]) or r["qty"] <= 0:
            reject(i, "R0", "quantity missing or not positive")
            continue
        key, method = None, None
        if r["ebm_key"] and r["ebm_key"] in key_pos:
            key, method = r["ebm_key"], "exact slip number"
        elif r["sdc_id"] and r["invoice"]:
            # SDC ID typo: same invoice, SDC ID one digit away, same product & quantity
            d = r["sdc_id"][3:]
            variants = {d, d[1:]} if d.startswith("0") else {d}   # undo an assumed leading zero
            cands = inv_fuel[(inv_fuel["invoice"] == r["invoice"]) &
                             inv_fuel["sdc_id"].map(lambda s: any(_edit1(s[3:], v) for v in variants))]
            cands = cands[(cands["product"] == r["product"]) &
                          ((cands["ebm_qty"] - r["qty"]).abs() <= max(settings.qty_abs_tolerance_l, r["qty"] * settings.qty_rel_tolerance))]
            if len(cands) == 1:
                key, method = cands.iloc[0]["ebm_key"], f"SDC ID corrected to {cands.iloc[0]['sdc_id']}"
        if key is None:
            # Fallback: same product + quantity + time window (+ seller TIN)
            pool = inv_fuel[(inv_fuel["product"] == r["product"]) &
                            ((inv_fuel["ebm_qty"] - r["qty"]).abs() <= 0.011)]
            if ctx.claimant_tin:
                pool = pool[pool["seller_tin"].isna() | (pool["seller_tin"] == ctx.claimant_tin)]
            if r["sdc_id"]:
                same_sdc = pool[pool["sdc_id"] == r["sdc_id"]]
                if not same_sdc.empty:
                    pool = same_sdc
            hits = []
            for t in (r["closed_at"], r["closed_at_alt"]):
                if t is None or pd.isna(t):
                    continue
                w = pd.Timedelta(minutes=settings.fallback_window_minutes)
                h = pool[(pool["sdc_datetime"] >= t - w) & (pool["sdc_datetime"] <= t + w)]
                hits.extend(h["ebm_key"].tolist())
            hits = [h for h in dict.fromkeys(hits) if h not in used_by_fallback]
            if len(hits) == 1:
                key, method = hits[0], "date, product and quantity (slip number unusable)"
                used_by_fallback.add(key)
                review(i, "R0", f"slip '{r['slip_raw']}' did not match; EBM invoice {merge_key(key)} found by date and quantity — confirm")
            elif len(hits) > 1:
                status[i] = "REVIEW"
                review(i, "R0", f"slip '{r['slip_raw']}' did not match; {len(hits)} possible EBM invoices — choose one")
                continue

        if key is None:
            when = r["closed_at"]
            outside = (when is not None and not pd.isna(when) and ebm_min is not None and not pd.isna(ebm_min)
                       and (when < ebm_min - pd.Timedelta(days=1) or when > ebm_max + pd.Timedelta(days=1)))
            claim_in = _in_interval(ctx, r["closed_at"], r["closed_at_alt"])
            if claim_in is False:
                reject(i, "R7", f"Closed at {when:%d/%m/%Y} is outside the declared consumption interval "
                                f"{_interval_text(ctx)} and no EBM invoice was found")
            elif outside:
                status[i] = "REVIEW"
                review(i, "R1", f"EBM file covers {ebm_min:%d/%m/%Y}–{ebm_max:%d/%m/%Y}; transaction date not covered — load EBM for this date")
            elif r["slip_status"] in ("MISSING", "INCOMPLETE", "INVALID"):
                reject(i, "R0", f"EBM slip {r['slip_status'].lower()} ('{r['slip_raw']}') and no matching EBM transaction found")
            else:
                reject(i, "R1", f"invoice {merge_key(r['ebm_key'])} not found in EBM")
            continue

        g = inv.iloc[key_pos[key]]
        out.at[i, "matched_key"] = key
        out.at[i, "match_method"] = method
        if method.startswith("SDC ID corrected"):
            notes[i].append(method)
        fuel_rows = g[g["product"].isin(FUEL)]
        row = fuel_rows[fuel_rows["product"] == r["product"]]
        if row.empty:
            shown = ", ".join(sorted(set(fuel_rows["product"]))) or g["item_names"].iloc[0]
            reject(i, "R6", f"claimed {r['product']}, EBM invoice shows {shown}")
            out.at[i, "ebm_item"] = g["item_names"].iloc[0]
            continue
        e = row.iloc[0]
        out.at[i, "ebm_qty"] = e["ebm_qty"]
        out.at[i, "ebm_unit_price"] = e["ebm_unit_price"]
        out.at[i, "ebm_datetime"] = e["sdc_datetime"]
        out.at[i, "ebm_tax_type"] = e["tax_types"]
        out.at[i, "ebm_item"] = e["item_names"]
        out.at[i, "ebm_seller_tin"] = e["seller_tin"]
        out.at[i, "ebm_buyer_tin"] = e["buyer_tin"]

        # R9 refund / non-sale
        if e["refunded"]:
            reject(i, "R9", "EBM invoice was refunded/cancelled")
            continue
        if e["nonsale"]:
            reject(i, "R9", "EBM receipt is training/proforma, not a sale")
            continue
        # R5 tax type
        taxes = set(filter(None, str(e["tax_types"]).split(",")))
        if taxes & settings.exempt_tax_types:
            reject(i, "R5", f"EBM tax type {','.join(sorted(taxes))} is exempt")
            continue
        # R7 seller TIN (and the OMC TIN written on the line, when the form has it)
        line_tin = out.at[i, "omc_tin"] if "omc_tin" in out else ""
        if ctx.claimant_tin and isinstance(line_tin, str) and line_tin and line_tin != ctx.claimant_tin \
                and e["seller_tin"] == ctx.claimant_tin:
            notes[i].append(f"OMC TIN written {line_tin} (typing error — EBM seller is the claimant)")
        if ctx.claimant_tin and e["seller_tin"] and e["seller_tin"] != ctx.claimant_tin:
            reject(i, "R7", f"invoice issued by TIN {e['seller_tin']}, not the claimant {ctx.claimant_tin}")
            continue
        # R7 consumption interval: the EBM invoice date is the official one
        has_ebm_date = e["sdc_datetime"] is not None and not pd.isna(e["sdc_datetime"])
        when = e["sdc_datetime"] if has_ebm_date else r["closed_at"]
        ebm_in = _in_interval(ctx, when)
        if ebm_in is False:
            side = "before" if when < ctx.period_start else "after"
            reject(i, "R7", f"EBM invoice date {when:%d/%m/%Y} is {side} the declared consumption interval "
                            f"{_interval_text(ctx)}")
            continue
        claim_in = _in_interval(ctx, r["closed_at"], r["closed_at_alt"])
        if has_ebm_date and claim_in is False:
            review(i, "R7", f"Closed at {r['closed_at']:%d/%m/%Y} is outside the interval but the EBM invoice "
                            f"({when:%d/%m/%Y}) is inside — check the date typed by the supplier")
        # R4 under-pricing against RURA
        rura = _rura_price(ctx.rura_prices, r["product"], when)
        out.at[i, "rura_price"] = rura
        price = e["ebm_unit_price"] if e["ebm_unit_price"] is not None and not pd.isna(e["ebm_unit_price"]) else r["unit_price"]
        if rura is not None and price is not None and price < rura - settings.price_tolerance_rwf:
            reject(i, "R4", f"unit price {price:,.0f} below RURA price {rura:,.0f} RWF/L")
            continue
        if r["unit_price"] and e["ebm_unit_price"] and abs(r["unit_price"] - e["ebm_unit_price"]) > settings.price_tolerance_rwf:
            notes[i].append(f"claim P.U {r['unit_price']:,.0f} differs from EBM {e['ebm_unit_price']:,.0f}")
        # Date consistency (review only)
        ok, used_alt, gap = _time_ok(r["closed_at"], r["closed_at_alt"], e["sdc_datetime"], settings.max_time_gap_hours)
        if used_alt:
            notes[i].append("Closed at read as month/day to match EBM")
        elif not ok:
            review(i, "R7", f"Closed at differs from EBM time by {gap:,.0f} h")
        if e["match_amount"] is False:
            review(i, "R1", "EBM flags invoice amount mismatch (MatchInvoiceAmount = FALSE)")
        # R2 history
        if key in ctx.history_keys:
            reject(i, "R2", f"invoice already claimed in {ctx.history_keys[key]}")
            continue

    # ---------- 2. Duplicates and quantity, invoice by invoice -----------------
    out["_order"] = out["closed_at"].fillna(pd.Timestamp.max) if "closed_at" in out else 0
    live = [i for i in range(len(out)) if status[i] != "REJECTED" and out.at[i, "matched_key"]]
    groups = {}
    for i in live:
        groups.setdefault((out.at[i, "matched_key"], out.at[i, "product"]), []).append(i)
    for (key, product), idx in groups.items():
        idx.sort(key=lambda j: (out.at[j, "_order"], j))
        remaining = float(out.at[idx[0], "ebm_qty"] or 0)
        first_row = None
        for j in idx:
            q = float(out.at[j, "qty"])
            tol = max(settings.qty_abs_tolerance_l, q * settings.qty_rel_tolerance)
            if first_row is not None:
                fr = out.loc[first_row]
                same = (fr["vehicle"] == out.at[j, "vehicle"] and abs(fr["qty"] - q) < 0.01)
                if remaining <= tol:
                    reject(j, "R2", f"duplicate of row {fr['source_row']}" if same else
                           f"EBM invoice {merge_key(key)} already used by row {fr['source_row']}")
                    continue
            if q <= remaining + tol:
                accepted_qty[j] = q
                remaining -= min(q, remaining)
            else:
                accepted_qty[j] = round(max(remaining, 0.0), 2)
                if accepted_qty[j] <= 0:
                    reject(j, "R2", f"EBM invoice {merge_key(key)} fully used by earlier rows")
                else:
                    status[j] = "PARTIAL"
                    reasons[j].append(f"R3 · claimed {q:,.2f} L, EBM {float(out.at[j, 'ebm_qty']):,.2f} L — "
                                      f"{q - accepted_qty[j]:,.2f} L rejected")
                remaining = 0.0
            if first_row is None:
                first_row = j

    # ---------- 3. Anomalies on what would be paid -----------------------------
    out["_acc"] = accepted_qty
    out["_day"] = out["closed_at"].dt.normalize() if "closed_at" in out else None
    pay = out[[s in ("ACCEPTED", "PARTIAL") for s in status]]
    if not pay.empty and pay["vehicle"].notna().any():
        vd = pay.groupby(["vehicle", "_day"])["_acc"].sum()
        fence = settings.max_litres_per_vehicle_day
        if len(vd) >= 20:
            q1, q3 = np.percentile(vd, [25, 75])
            fence = max(fence, q3 + settings.iqr_multiplier * (q3 - q1))
        for (veh, day), litres in vd[vd > fence].items():
            for j in pay.index[(pay["vehicle"] == veh) & (pay["_day"] == day)]:
                review(j, "R8", f"{litres:,.0f} L for {veh} on {day:%d/%m/%Y} (limit {fence:,.0f} L/day)")
        for veh, g in pay.sort_values("closed_at").groupby("vehicle"):
            t = g["closed_at"].dropna()
            gaps = t.diff().dt.total_seconds().div(60)
            for j, gmin in gaps.items():
                if gmin is not None and not pd.isna(gmin) and gmin < settings.min_refill_interval_minutes:
                    review(j, "R8", f"{veh} refuelled again after {gmin:,.0f} min")
        if settings.max_plates_per_card and pay["card"].notna().any():
            plates = pay.groupby("card")["vehicle"].nunique()
            for card in plates[plates > settings.max_plates_per_card].index:
                for j in pay.index[pay["card"] == card]:
                    review(j, "R8", f"card {card} used on {plates[card]} vehicles")

    # ---------- 3b. Buyer = the transport operator (R10, review only) ------------
    if settings.check_buyer_tin:
        payable = [i for i in range(len(out)) if status[i] != "REJECTED" and out.at[i, "matched_key"]]
        buyers = out.loc[payable, ["client", "ebm_buyer_tin"]].copy()
        buyers["ebm_buyer_tin"] = buyers["ebm_buyer_tin"].fillna("")
        anonymous = set(settings.anonymous_buyer_tins)
        usual = {}
        for client, g in buyers[~buyers.ebm_buyer_tin.isin(anonymous | {""})].groupby("client"):
            vc = g.ebm_buyer_tin.value_counts()
            if len(vc) and vc.iloc[0] / vc.sum() >= 0.5:
                usual[client] = vc.index[0]
        for i in payable:
            b = out.at[i, "ebm_buyer_tin"] or ""
            client = out.at[i, "client"]
            if b in anonymous or b == "":
                review(i, "R10", f"EBM invoice has no buyer TIN ({b or 'empty'}): not issued to the transport operator")
            elif client in usual and b != usual[client]:
                review(i, "R10", f"EBM invoice issued to buyer TIN {b}; {client}'s invoices usually go to {usual[client]}")

    # ---------- 4. Subsidy rate, final status and money ----------------------
    if settings.official_subsidy_rates:
        official = {k.upper(): float(v) for k, v in settings.official_subsidy_rates.items()}
        fallback = settings.official_subsidy_rate or modal_rate or 0.0
        rate = out["product"].map(lambda p: official.get(str(p).upper(), fallback)).astype(float)
        for i in range(len(out)):
            r_ = out.at[i, "subsidy_rate"]
            if r_ is not None and not pd.isna(r_) and abs(r_ - rate.iat[i]) > 0.01:
                notes[i].append(f"claimed rate {r_} replaced by official rate {rate.iat[i]:g}")
    elif settings.official_subsidy_rate:
        rate = pd.Series(float(settings.official_subsidy_rate), index=out.index)
        for i in range(len(out)):
            r_ = out.at[i, "subsidy_rate"]
            if r_ is not None and not pd.isna(r_) and abs(r_ - settings.official_subsidy_rate) > 0.01:
                notes[i].append(f"claimed rate {r_} replaced by official rate {settings.official_subsidy_rate}")
    else:
        rate = pd.to_numeric(out["subsidy_rate"], errors="coerce").fillna(pay_rate if pay_rate else 0.0)
        for i in range(len(out)):
            r_ = out.at[i, "subsidy_rate"]
            if (status[i] != "REJECTED" and r_ is not None and not pd.isna(r_) and modal_rate
                    and abs(r_ - modal_rate) > 0.01):
                reviews[i].append(f"R0 · subsidy rate {r_} differs from the claim's usual rate {modal_rate}")
    for i in range(len(out)):
        if reviews[i] and status[i] != "REJECTED":
            status[i] = "REVIEW"
    out["status"] = status
    qty = pd.to_numeric(out["qty"], errors="coerce").fillna(0.0)
    out["accepted_qty"] = [round(a, 2) if s in ("ACCEPTED", "PARTIAL") else 0.0 for a, s in zip(accepted_qty, status)]
    # A line in review keeps the quantity it would be paid (excess over EBM stays rejected)
    out["pending_qty"] = [round(min(float(a), float(q)), 2) if s == "REVIEW" else 0.0
                          for a, q, s in zip(accepted_qty, qty, status)]
    out["rejected_qty"] = (qty - out["accepted_qty"] - out["pending_qty"]).round(2)
    out["pay_rate"] = rate
    out["claimed_subsidy"] = pd.to_numeric(out["subsidy_amount"], errors="coerce").fillna(qty * rate).round(2)
    out["accepted_subsidy"] = (out["accepted_qty"] * rate).round(2)
    out["pending_subsidy"] = (out["pending_qty"] * rate).round(2)
    out["rejected_subsidy"] = (out["claimed_subsidy"] - out["accepted_subsidy"] - out["pending_subsidy"]).clip(lower=0).round(2)
    out["reason"] = ["; ".join(r) for r in reasons]
    out["review_reason"] = ["; ".join(r) for r in reviews]
    out["match_notes"] = ["; ".join(n) for n in notes]
    out["invoice_clean"] = out["matched_key"].map(lambda k: merge_key(k) if k else "")
    out["decision"] = ""
    return out.drop(columns=["_order", "_acc", "_day"])


def summarise(lines: pd.DataFrame) -> dict:
    s = lambda c: float(lines[c].fillna(0).sum())
    return {
        "lines": int(len(lines)),
        "accepted_lines": int((lines["status"] == "ACCEPTED").sum()),
        "partial_lines": int((lines["status"] == "PARTIAL").sum()),
        "rejected_lines": int((lines["status"] == "REJECTED").sum()),
        "review_lines": int((lines["status"] == "REVIEW").sum()),
        "vehicles": int(lines["vehicle"].nunique()),
        "claimed_qty": round(s("qty"), 2),
        "claimed_subsidy": round(s("claimed_subsidy"), 2),
        "accepted_qty": round(s("accepted_qty"), 2),
        "pending_qty": round(s("pending_qty"), 2),
        "rejected_qty": round(s("rejected_qty"), 2),
        "accepted_subsidy": round(s("accepted_subsidy"), 2),
        "pending_subsidy": round(s("pending_subsidy"), 2),
        "rejected_subsidy": round(s("rejected_subsidy"), 2),
    }


def apply_decisions(lines: pd.DataFrame, decisions: dict, who: str) -> pd.DataFrame:
    """Apply reviewer decisions to REVIEW lines.

    decisions: {source_row: ("Accept" | "Reject" | "Pending", note)}
    Accept -> pending litres become accepted; Reject -> become rejected.
    """
    out = lines.copy()
    if "decision" not in out:
        out["decision"] = ""
    for i, r in out.iterrows():
        if r["status"] != "REVIEW":
            continue
        choice, note = decisions.get(r["source_row"], ("Pending", ""))
        note = (note or "").strip()
        if choice == "Accept":
            out.at[i, "accepted_qty"] = round(r["accepted_qty"] + r["pending_qty"], 2)
            out.at[i, "accepted_subsidy"] = round(r["accepted_subsidy"] + r["pending_subsidy"], 2)
            out.at[i, "status"] = "ACCEPTED"
            out.at[i, "decision"] = f"Accepted after review by {who}" + (f": {note}" if note else "")
        elif choice == "Reject":
            out.at[i, "rejected_qty"] = round(r["rejected_qty"] + r["pending_qty"], 2)
            out.at[i, "rejected_subsidy"] = round(r["rejected_subsidy"] + r["pending_subsidy"], 2)
            out.at[i, "accepted_qty"] = 0.0
            out.at[i, "accepted_subsidy"] = 0.0
            out.at[i, "status"] = "REJECTED"
            code = (r["review_reason"] or "R8").split(" · ")[0]
            out.at[i, "reason"] = "; ".join(filter(None, [r["reason"],
                                            f"{code} · rejected after review by {who}" + (f": {note}" if note else "")]))
            out.at[i, "decision"] = f"Rejected after review by {who}" + (f": {note}" if note else "")
        else:
            continue
        out.at[i, "pending_qty"] = 0.0
        out.at[i, "pending_subsidy"] = 0.0
    return out
