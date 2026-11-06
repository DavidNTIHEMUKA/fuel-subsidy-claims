"""Summary indicators (as in the IKWIM verification notebook, extended).

One call gives the figures the analyst used to compute by hand:
transactions, plates, invoices, operators, litres and subsidy for all /
accepted / pending / rejected lines, plus per-vehicle totals and a price check.
"""
from __future__ import annotations

import pandas as pd


def _num(s):
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


def indicators(lines: pd.DataFrame) -> pd.DataFrame:
    L = lines.copy()
    invoice = L.get("matched_key", pd.Series(index=L.index, dtype=object)).fillna("")
    invoice = invoice.where(invoice != "", L.get("ebm_key", pd.Series(index=L.index, dtype=object)).fillna(""))
    invoice = invoice.where(invoice != "", L.get("slip_raw", pd.Series(index=L.index, dtype=object)).fillna(""))
    L["_inv"] = invoice
    L["_buyer"] = L.get("ebm_buyer_tin", pd.Series(index=L.index, dtype=object)).fillna("")

    def row(label, mask, litres, rwf):
        g = L[mask]
        return {"Group": label, "Transactions": int(len(g)), "Plates": int(g["vehicle"].nunique()),
                "Invoices": int(g["_inv"].replace("", pd.NA).nunique()),
                "Operators (buyer TINs)": int(g["_buyer"].replace("", pd.NA).nunique()),
                "Litres": round(float(_num(g[litres]).sum()), 2), "Subsidy (RWF)": round(float(_num(g[rwf]).sum()))}

    rows = [
        row("All claimed", pd.Series(True, index=L.index), "qty", "claimed_subsidy"),
        row("Accepted", _num(L["accepted_qty"]) > 0, "accepted_qty", "accepted_subsidy"),
        row("Pending review", _num(L["pending_qty"]) > 0, "pending_qty", "pending_subsidy"),
        row("Rejected", _num(L["rejected_qty"]) > 0, "rejected_qty", "rejected_subsidy"),
    ]
    out = pd.DataFrame(rows)
    claimed = out.loc[0, "Litres"] or 1
    out["% of claimed litres"] = (out["Litres"] / claimed).round(4)
    return out


def match_summary(lines: pd.DataFrame) -> pd.DataFrame:
    n = len(lines)
    mm = lines.get("match_method", pd.Series(index=lines.index, dtype=object)).fillna("")
    exact = int((mm == "exact slip number").sum())
    corrected = int(mm.str.startswith("SDC ID corrected").sum())
    fallback = int(mm.str.startswith("date, product").sum())
    none = int((mm == "").sum())
    dup_claim = int(lines.get("ebm_key", pd.Series(dtype=object)).dropna().duplicated().sum())
    rows = [("Lines in claim", n), ("Matched to EBM by slip number", exact),
            ("Matched after correcting a typo in the SDC ID", corrected),
            ("Matched by date, product and quantity (to confirm)", fallback),
            ("Not found in EBM", none), ("Match rate", f"{(n - none) / n:.2%}" if n else "—"),
            ("Same EBM slip claimed more than once in this file", dup_claim)]
    return pd.DataFrame(rows, columns=["Check", "Value"])


def by_vehicle(lines: pd.DataFrame) -> pd.DataFrame:
    L = lines.copy()
    L["_day"] = pd.to_datetime(L["closed_at"], errors="coerce", dayfirst=True).dt.normalize()
    for c in ["qty", "accepted_qty", "pending_qty", "rejected_qty", "claimed_subsidy", "accepted_subsidy"]:
        L[c] = _num(L[c])
    g = L.groupby(["vehicle", "client"], dropna=False).agg(
        transactions=("qty", "size"), days=("_day", "nunique"), claimed_l=("qty", "sum"),
        accepted_l=("accepted_qty", "sum"), pending_l=("pending_qty", "sum"), rejected_l=("rejected_qty", "sum"),
        claimed_rwf=("claimed_subsidy", "sum"), accepted_rwf=("accepted_subsidy", "sum")).reset_index()
    g["litres_per_active_day"] = (g.claimed_l / g.days.where(g.days > 0)).round(1)
    g = g.round(2).sort_values("claimed_l", ascending=False)
    return g.rename(columns={"vehicle": "Vehicle", "client": "Client", "transactions": "Transactions",
                             "days": "Active days", "claimed_l": "Claimed L", "accepted_l": "Accepted L",
                             "pending_l": "Pending L", "rejected_l": "Rejected L", "claimed_rwf": "Claimed RWF",
                             "accepted_rwf": "Accepted RWF", "litres_per_active_day": "L per active day"})


def price_check(lines: pd.DataFrame) -> pd.DataFrame:
    L = lines.copy()
    for c in ["unit_price", "ebm_unit_price", "rura_price"]:
        if c not in L:
            L[c] = None
    L["Claim P.U"] = _num(L["unit_price"]).round(0)
    L["EBM P.U"] = pd.to_numeric(L["ebm_unit_price"], errors="coerce").round(0)
    L["RURA price"] = pd.to_numeric(L["rura_price"], errors="coerce").round(0)
    g = (L.groupby(["product", "Claim P.U", "EBM P.U", "RURA price"], dropna=False)
         .agg(Lines=("qty", "size"), Litres=("qty", "sum")).reset_index())
    g["Check"] = "ok"
    g.loc[g["EBM P.U"].notna() & (g["Claim P.U"] != g["EBM P.U"]), "Check"] = "claim P.U differs from EBM"
    g.loc[g["RURA price"].notna() & (g["EBM P.U"] < g["RURA price"] - 1), "Check"] = "below RURA price"
    g.loc[g["EBM P.U"].isna(), "Check"] = "no EBM match"
    return g.rename(columns={"product": "Product"}).round(2)
