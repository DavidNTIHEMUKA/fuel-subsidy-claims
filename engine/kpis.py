"""KPIs for fuel suppliers and transport agencies: efficiency, compliance, abnormal consumption.

Every KPI is computed from the analysed lines (after EBM matching and the rules), so
it measures what was verified, not what was declared. Each entity is compared with its
peers — suppliers of a similar fleet size and consumption — and flagged when it is
clearly worse than the peer median.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# name, label, group, direction ("high" = higher is worse), format, definition
KPI_DEFS = [
    ("acceptance_rate", "Acceptance rate", "Compliance", "low", "pct",
     "Accepted litres ÷ claimed litres. Low = many lines not supported by EBM or the rules."),
    ("ebm_match_rate", "EBM match rate", "Compliance", "low", "pct",
     "Share of lines whose EBM Slip No was found in EBM."),
    ("not_in_ebm_rate", "Not found in EBM", "Compliance", "high", "pct",
     "Share of lines rejected because the receipt is not in EBM (R0/R1)."),
    ("duplicate_rate", "Duplicate invoices", "Compliance", "high", "pct",
     "Share of lines re-using an invoice already claimed (R2)."),
    ("overclaim_rate", "Over-claimed litres", "Compliance", "high", "pct",
     "Litres claimed above the EBM quantity ÷ claimed litres (R3)."),
    ("invalid_invoice_rate", "Invalid invoices", "Compliance", "high", "pct",
     "Share of lines with exempt, refunded, wrong-product or wrong-period invoices (R5, R6, R7, R9)."),
    ("price_issue_rate", "Price below RURA", "Compliance", "high", "pct",
     "Share of lines sold below the RURA reference price (R4)."),
    ("buyer_tin_issue_rate", "Buyer TIN issues", "Compliance", "high", "pct",
     "Share of lines whose EBM invoice has no or another buyer TIN (R10)."),
    ("litres_per_vehicle_day", "Litres per vehicle per day", "Consumption", "high", "num",
     "Average litres per vehicle on the days it refuelled."),
    ("max_litres_vehicle_day", "Highest vehicle-day", "Abnormality", "high", "num",
     "Largest quantity taken by one vehicle in one day."),
    ("high_day_share", "Vehicle-days above 400 L", "Abnormality", "high", "pct",
     "Share of vehicle-days above 400 litres."),
    ("quick_refuel_rate", "Refuels within 60 min", "Abnormality", "high", "pct",
     "Share of fills made less than an hour after the previous fill of the same vehicle."),
    ("avg_fill", "Average fill (L)", "Consumption", "high", "num", "Litres per transaction."),
    ("subsidy_per_vehicle", "Subsidy per vehicle (RWF)", "Efficiency", "high", "num",
     "Subsidy claimed per vehicle in the period."),
    ("review_rate", "Lines sent to review", "Efficiency", "high", "pct",
     "Share of lines a person had to check (doubtful cases)."),
]
KPI = {k[0]: dict(zip(["name", "label", "group", "direction", "fmt", "definition"], k)) for k in KPI_DEFS}


def _rule(s: pd.Series, codes) -> pd.Series:
    code = s.fillna("").str.extract(r"(R\d+)")[0]
    return code.isin(codes)


def entity_kpis(lines: pd.DataFrame, by: str) -> pd.DataFrame:
    """One row per supplier (by='supplier') or transport agency (by='client')."""
    if lines is None or lines.empty:
        return pd.DataFrame()
    L = lines.copy()
    for c in ["qty", "accepted_qty", "pending_qty", "rejected_qty", "claimed_subsidy"]:
        L[c] = pd.to_numeric(L[c], errors="coerce").fillna(0.0)
    L["ts"] = pd.to_datetime(L["closed_at"], format="%d/%m/%Y %H:%M", errors="coerce")
    L["day"] = L["ts"].dt.normalize()
    L["_notfound"] = _rule(L["reason"], ["R0", "R1"])
    L["_dup"] = _rule(L["reason"], ["R2"])
    L["_over_l"] = np.where(_rule(L["reason"], ["R3"]), L["rejected_qty"], 0.0)
    L["_invalid"] = _rule(L["reason"], ["R5", "R6", "R7", "R9"])
    L["_price"] = _rule(L["reason"], ["R4"])
    L["_buyer"] = L["review_reason"].fillna("").str.contains("R10") | L["reason"].fillna("").str.contains("R10")
    L["_review"] = (L["pending_qty"] > 0) | (L["review_reason"].fillna("") != "")
    L = L.sort_values([by, "vehicle", "ts"])
    gap = L.groupby([by, "vehicle"])["ts"].diff().dt.total_seconds() / 60
    L["_quick"] = gap < 60

    g = L.groupby(by)
    out = pd.DataFrame({
        "vehicles": g["vehicle"].nunique(),
        "transactions": g.size(),
        "claimed_l": g["qty"].sum(),
        "accepted_l": g["accepted_qty"].sum(),
        "claimed_rwf": g["claimed_subsidy"].sum(),
    })
    out["acceptance_rate"] = out.accepted_l / out.claimed_l.where(out.claimed_l > 0)
    out["not_in_ebm_rate"] = g["_notfound"].mean()
    out["ebm_match_rate"] = 1 - out["not_in_ebm_rate"]
    out["duplicate_rate"] = g["_dup"].mean()
    out["overclaim_rate"] = g["_over_l"].sum() / out.claimed_l.where(out.claimed_l > 0)
    out["invalid_invoice_rate"] = g["_invalid"].mean()
    out["price_issue_rate"] = g["_price"].mean()
    out["buyer_tin_issue_rate"] = g["_buyer"].mean()
    out["review_rate"] = g["_review"].mean()
    out["quick_refuel_rate"] = g["_quick"].mean()
    vd = L.dropna(subset=["day"]).groupby([by, "vehicle", "day"])["qty"].sum()
    out["litres_per_vehicle_day"] = vd.groupby(level=0).mean()
    out["max_litres_vehicle_day"] = vd.groupby(level=0).max()
    out["high_day_share"] = (vd > 400).groupby(level=0).mean()
    out["avg_fill"] = out.claimed_l / out.transactions
    out["subsidy_per_vehicle"] = out.claimed_rwf / out.vehicles.where(out.vehicles > 0)
    out = out.reset_index().rename(columns={by: "entity"})
    out["fleet_band"] = pd.cut(out.vehicles, [0, 50, 150, 300, np.inf],
                               labels=["1–50 vehicles", "51–150 vehicles", "151–300 vehicles", "300+ vehicles"])
    if len(out) >= 3:
        out["consumption_band"] = pd.qcut(out.claimed_l.rank(method="first"), 3, labels=["Low", "Medium", "High"])
    else:
        out["consumption_band"] = "All"
    return out


def flag_against_peers(k: pd.DataFrame, peer_col: str | None = "fleet_band") -> pd.DataFrame:
    """Add <kpi>_flag = 'red' / 'amber' / 'green' compared with the peer median
    (same fleet band when it has at least 3 members, otherwise all entities)."""
    if k.empty:
        return k
    k = k.copy()
    for name, d in KPI.items():
        if name not in k:
            continue
        flags = []
        for i, r in k.iterrows():
            peers = k[k[peer_col] == r[peer_col]] if peer_col and (k[peer_col] == r[peer_col]).sum() >= 3 else k
            others = peers.drop(index=i)[name].dropna()
            v = r[name]
            if pd.isna(v) or others.empty:
                flags.append("")
                continue
            med = others.median()
            spread = max((others.quantile(.75) - others.quantile(.25)), abs(med) * 0.10,
                         0.02 if d["fmt"] == "pct" else 1e-9)
            worse = (v - med) if d["direction"] == "high" else (med - v)
            flags.append("red" if worse > 2 * spread else "amber" if worse > spread else "green")
        k[f"{name}_flag"] = flags
        k[f"{name}_peer_median"] = [
            (k[k[peer_col] == r[peer_col]] if peer_col and (k[peer_col] == r[peer_col]).sum() >= 3 else k)
            .drop(index=i)[name].median() for i, r in k.iterrows()]
    k["red_flags"] = k[[c for c in k.columns if c.endswith("_flag")]].eq("red").sum(axis=1)
    k["amber_flags"] = k[[c for c in k.columns if c.endswith("_flag") and c != "red_flags"]].eq("amber").sum(axis=1)
    return k


def fmt(name, v):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:.1%}" if KPI[name]["fmt"] == "pct" else f"{v:,.1f}"
