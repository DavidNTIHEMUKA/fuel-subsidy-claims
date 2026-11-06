"""Re-analyse appealed lines against EBM, exactly like a new submission.

1. Rebuild the appealed lines from the saved claim.
2. Apply the supplier's corrections from the appeal form (corrected EBM Slip No,
   corrected quantity).
3. Clean, match to the EBM file and run every rule (R0–R10) with the claim's TIN,
   consumption interval and price list.
4. Invoices already used by the claim's other lines, or by other claims, count as
   duplicates (R2), so an appeal can never re-use an invoice.
5. Litres that may be awarded per line = what the analysis accepts, minus what was
   already accepted, capped at what was rejected.
"""
from __future__ import annotations

import pandas as pd

from .cleaning import (EBM_COLUMNS, EBM_REQUIRED, clean_ebm, merge_key, normalize_product, normalize_slip,
                       read_table)
from .config import DEFAULT, Settings
from .rules import ClaimContext, validate_claim


def _rebuild(stored: pd.DataFrame, corrections: pd.DataFrame) -> pd.DataFrame:
    corr = {str(r["row"]): r for _, r in corrections.iterrows()} if corrections is not None else {}
    rows = []
    for _, r in stored.iterrows():
        row = str(r["source_row"])
        c = corr.get(row)
        slip_text = (c["slip"] if c is not None and str(c.get("slip", "")).strip() else r["slip_raw"])
        cq = None if c is None else c.get("qty")
        qty = float(cq) if cq is not None and not pd.isna(cq) and float(cq) > 0 else float(r["qty"])
        sl = normalize_slip(slip_text)
        ts = pd.to_datetime(r["closed_at"], format="%d/%m/%Y %H:%M", errors="coerce")
        product = r.get("product") or normalize_product(r.get("product_raw"))
        price = pd.to_numeric(r.get("unit_price"), errors="coerce")
        rate = pd.to_numeric(r.get("pay_rate"), errors="coerce")
        rows.append({
            "source_row": int(float(row)), "site": "", "client": r.get("client", ""),
            "closed_at": ts if pd.notna(ts) else None, "closed_at_alt": None, "vehicle": r.get("vehicle"),
            "card": None, "product": product, "product_raw": r.get("product_raw", ""), "qty": qty,
            "unit_price": float(price) if pd.notna(price) else None, "amount": None,
            "subsidy_rate": float(rate) if pd.notna(rate) else None, "subsidy_amount": None, "net_payable": None,
            "served_by": "", "slip_raw": slip_text, "slip_clean": merge_key(sl.key) if sl.key else merge_key(slip_text),
            "sdc_id": sl.sdc_id, "invoice": sl.invoice, "ebm_key": sl.key, "slip_status": sl.status,
            "cleaning_notes": "", "format_issues": "", "warnings": "",
            "_corrected_slip": c is not None and bool(str(c.get("slip", "")).strip()),
            "_corrected_qty": c is not None and cq is not None and not pd.isna(cq),
        })
    return pd.DataFrame(rows)


def reanalyse(claim: dict, stored_lines: pd.DataFrame, appealed_rows: list, corrections: pd.DataFrame | None,
              ebm_file, history: dict, rura_prices: pd.DataFrame | None = None,
              settings: Settings = DEFAULT) -> tuple[pd.DataFrame, list[str]]:
    """Return (one row per appealed line with the new outcome and the litres that may be awarded, notes)."""
    start = pd.Timestamp(claim["interval_start"])
    end = pd.Timestamp(claim["interval_end"])
    ebm_raw, problems = read_table(ebm_file, EBM_COLUMNS, EBM_REQUIRED, "EBM file")
    if ebm_raw.empty or any("not found" in p or "no header" in p for p in problems):
        return pd.DataFrame(), problems
    ebm = clean_ebm(ebm_raw, settings, interval=(start, end))
    notes = [p for p in problems] + ([ebm.attrs["date_summary"]] if ebm.attrs.get("date_summary") else [])

    appealed = {str(r) for r in appealed_rows}
    stored = stored_lines.copy()
    stored["source_row"] = stored["source_row"].astype(str)
    target = stored[stored["source_row"].isin(appealed)]
    # invoices already used by the other lines of this claim
    others = stored[~stored["source_row"].isin(appealed) &
                    ((stored["accepted_qty"] > 0) | (stored["pending_qty"] > 0)) & (stored["matched_key"] != "")]
    hist = dict(history)
    for k in others["matched_key"].str.replace("/", "|", regex=False):
        hist.setdefault(k, f"another line of claim #{claim['id']}")

    reclaim = _rebuild(target, corrections)
    ctx = ClaimContext(claimant_tin=claim.get("tin"), period_start=start, period_end=end, rura_prices=rura_prices,
                       history_keys=hist)
    res = validate_claim(reclaim.drop(columns=["_corrected_slip", "_corrected_qty"]), ebm, ctx, settings)

    out = []
    for (_, new), (_, old), (_, rb) in zip(res.iterrows(), target.iterrows(), reclaim.iterrows()):
        orig_qty, orig_acc, orig_rej = float(old["qty"]), float(old["accepted_qty"]), float(old["rejected_qty"])
        payable_now = min(float(new["accepted_qty"]), orig_qty)
        award = max(0.0, min(payable_now - orig_acc, orig_rej))
        rate = float(old["pay_rate"]) or 0.0
        out.append({
            "row": str(old["source_row"]), "vehicle": old["vehicle"], "closed_at": old["closed_at"],
            "slip_claimed": old.get("slip_clean") or old["slip_raw"],
            "slip_used": new["slip_clean"], "corrected": ("slip" if rb["_corrected_slip"] else "")
            + (" + qty" if rb["_corrected_qty"] else ""),
            "claimed_qty": float(new["qty"]), "ebm_qty": float(new["ebm_qty"]) if pd.notna(new["ebm_qty"]) else 0.0,
            "new_status": new["status"], "reason": new["reason"], "review_reason": new["review_reason"],
            "original_reason": old["reason"], "matched_key": new["matched_key"] or "",
            "award_l": round(award, 2), "award_rwf": round(award * rate, 2),
            "ebm_date": str(new.get("ebm_time") or "") if pd.notna(new.get("ebm_time")) else "",
            "ebm_amount": (round(float(new["ebm_qty"]) * float(new["ebm_unit_price"]), 2)
                           if pd.notna(new.get("ebm_qty")) and pd.notna(new.get("ebm_unit_price")) else ""),
            "ebm_buyer_tin": str(new.get("ebm_buyer_tin") or ""),
        })
    return pd.DataFrame(out), notes
