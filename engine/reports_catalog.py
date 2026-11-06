"""Catalogue of reports (Reporting head). Each report returns a table already limited to what the user may see:
a fuel supplier only ever gets the lines of its own TIN."""
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from engine import register as reg

STAFF = ("officer", "admin", "manager", "senior_manager")
EVERYONE = STAFF + ("supplier", "finance", "taskforce", "approver")


@dataclass
class Report:
    key: str
    title: str
    group: str
    description: str
    roles: tuple
    build: Callable


def _claims(con, u):
    df = reg.claims(con)
    if u["role"] == "supplier":
        df = df[df.tin == (u.get("tin") or "~")]
    return df


def _period(df, col, start, end):
    if df.empty or not col or (start is None and end is None):
        return df
    d = pd.to_datetime(df[col], errors="coerce")
    keep = pd.Series(True, index=df.index)
    if start is not None:
        keep &= d >= pd.Timestamp(start)
    if end is not None:
        keep &= d < pd.Timestamp(end) + pd.Timedelta(days=1)
    return df[keep]


STAGE = {"SUBMITTED": "Submission — waiting for system verification", "PROCESSED": "RRA Staff verification done",
         "APPROVED": "Approved — waiting for payment", "PARTLY PAID": "Partly paid", "PAID": "Paid",
         "RETURNED": "Returned to the supplier"}


# --------------------------------------------------------------------------- reports for everyone
def claims_statement(con, u, start=None, end=None, suppliers=None):
    df = _period(_claims(con, u), "submitted_at", start, end)
    if suppliers:
        df = df[df["name"].isin(suppliers)]
    return pd.DataFrame({
        "Claim #": df.id, "TIN": df.tin, "Fuel supplier": df["name"], "Round": df.submission.fillna(""),
        "Consumption from": df.interval_start, "to": df.interval_end, "Submitted": df.submitted_at,
        "Stage": df.status.map(STAGE).fillna(df.status), "Litres claimed": df.claimed_l,
        "Litres accepted": df.accepted_l, "Litres pending": df.pending_l, "Litres rejected": df.rejected_l,
        "Subsidy requested (RWF)": df.requested_rwf, "Subsidy calculated (RWF)": df.calculated_rwf,
        "To reimburse (RWF)": df.to_reimburse, "Paid (RWF)": df.paid_amount.fillna(0),
        "Outstanding (RWF)": df.outstanding, "Payment reference": df.payment_ref.fillna("")})


def payment_statement(con, u, start=None, end=None, suppliers=None):
    p = reg.payables(con)
    if u["role"] == "supplier":
        p = p[p.tin == (u.get("tin") or "~")]
    if suppliers:
        p = p[p["name"].isin(suppliers)]
    p = _period(p, "created_at", start, end)
    return pd.DataFrame({
        "Payment #": p.id, "Claim #": p.claim_id, "TIN": p.tin, "Fuel supplier": p["name"], "Round": p.submission,
        "Type": p.kind, "Amount due (RWF)": p.amount, "Paid (RWF)": p.paid_amount, "Outstanding (RWF)": p.outstanding,
        "Status": p.status, "Paid on": p.paid_at.fillna(""), "Reference": p.payment_ref.fillna(""),
        "Bank account": p.account})


def rejected_lines(con, u, start=None, end=None, suppliers=None):
    lines = reg.all_lines(con)
    if lines.empty:
        return pd.DataFrame()
    if u["role"] == "supplier":
        lines = lines[lines.tin == (u.get("tin") or "~")]
    if suppliers:
        lines = lines[lines.supplier.isin(suppliers)]
    lines = _period(lines, "interval_start", start, end)
    r = lines[lines.rejected_qty > 0]
    return pd.DataFrame({
        "Claim #": r.claim_id, "Fuel supplier": r.supplier, "Row": r.source_row, "Client": r.client,
        "Vehicle": r.vehicle, "Closed at": r.closed_at.astype(str), "EBM Slip No": r.slip_clean,
        "Rejected L": r.rejected_qty, "Rejected subsidy (RWF)": r.rejected_subsidy, "Reason": r.reason})


def appeals_status(con, u, start=None, end=None, suppliers=None):
    a = reg.appeals(con)
    if a.empty:
        return a
    if u["role"] == "supplier":
        a = a[a.tin == (u.get("tin") or "~")]
    if suppliers and "name" in a:
        a = a[a["name"].isin(suppliers)]
    a = _period(a, "submitted_at", start, end)
    keep = [c for c in ("id", "claim_id", "name", "submitted_at", "status", "reason", "award_l", "award_rwf",
                        "decided_at", "decision_note") if c in a]
    return a[keep].rename(columns={"id": "Appeal #", "claim_id": "Claim #", "name": "Fuel supplier",
                                   "submitted_at": "Filed", "status": "Status", "reason": "Reason",
                                   "award_l": "Litres awarded", "award_rwf": "Award (RWF)", "decided_at": "Decided",
                                   "decision_note": "Decision note"})


# --------------------------------------------------------------------------- staff reports
def rounds_signatures(con, u, start=None, end=None, suppliers=None):
    from engine import workflow as wf
    r = _period(wf.rounds(con), "created_at", start, end)
    rows = []
    for x in r.itertuples():
        sig = wf.round_signatures(con, x.id)
        tf = sig[sig.title != "Final approver"] if not sig.empty else sig
        fa = sig[sig.title == "Final approver"] if not sig.empty else sig
        rows.append({"Round": x.name, "Created": x.created_at, "Status": x.status.title(), "Claims": x.claims,
                     "To reimburse (RWF)": x.to_reimburse, "Taskforce approvals": f"{x.signed}/{x.signatories}",
                     "Rejections": int((tf.decision != "APPROVED").sum()) if not tf.empty else 0,
                     "Final approval": (f"{fa.iloc[-1]['name']} · {fa.iloc[-1].signed_at}" if not fa.empty else "—"),
                     "Comments": "; ".join(c for c in sig.comment.fillna("") if c) if not sig.empty else ""})
    return pd.DataFrame(rows)


def payment_schedule(con, u, start=None, end=None, suppliers=None):
    p = payment_statement(con, u, start, end, suppliers)
    return p[p["Outstanding (RWF)"] > 0.5].drop(columns=["Paid on", "Reference"]) if not p.empty else p


def monthly_summary(con, u, start=None, end=None, suppliers=None):
    c = _period(reg.claims(con), "submitted_at", start, end)
    if suppliers:
        c = c[c["name"].isin(suppliers)]
    if c.empty:
        return pd.DataFrame()
    c = c.assign(Month=pd.to_datetime(c.submitted_at, errors="coerce").dt.strftime("%Y-%m"))
    g = c.groupby("Month").agg(**{
        "Claims": ("id", "size"), "Suppliers": ("tin", "nunique"), "Litres claimed": ("claimed_l", "sum"),
        "Litres accepted": ("accepted_l", "sum"), "Litres rejected": ("rejected_l", "sum"),
        "Requested (RWF)": ("requested_rwf", "sum"), "Calculated (RWF)": ("calculated_rwf", "sum"),
        "To reimburse (RWF)": ("to_reimburse", "sum"), "Paid (RWF)": ("paid_amount", "sum")}).reset_index()
    g["Acceptance rate (%)"] = (100 * g["Litres accepted"] / g["Litres claimed"].replace(0, pd.NA)).round(1)
    return g


def supplier_compliance(con, u, start=None, end=None, suppliers=None):
    lines = reg.all_lines(con)
    if lines.empty:
        return pd.DataFrame()
    lines = _period(lines, "interval_start", start, end)
    if suppliers:
        lines = lines[lines.supplier.isin(suppliers)]
    lines = lines.assign(rule=lines.reason.fillna("").str.extract(r"(R\d+)")[0])
    rows = []
    for (tin, name), g in lines.groupby(["tin", "supplier"]):
        claimed = g.qty.sum()
        rej = g[g.rejected_qty > 0]
        top = rej.rule.value_counts()
        rows.append({"TIN": tin, "Fuel supplier": name, "Claims": g.claim_id.nunique(), "Lines": len(g),
                     "Vehicles": g.vehicle.nunique(), "Litres claimed": round(claimed, 2),
                     "Accepted (%)": round(100 * g.accepted_qty.sum() / claimed, 1) if claimed else None,
                     "Rejected (%)": round(100 * g.rejected_qty.sum() / claimed, 1) if claimed else None,
                     "Pending (%)": round(100 * g.pending_qty.sum() / claimed, 1) if claimed else None,
                     "Not in EBM (lines)": int(rej.reason.str.contains("R1", na=False).sum()),
                     "Duplicates (lines)": int(rej.reason.str.contains("R2", na=False).sum()),
                     "Main rejection rule": top.index[0] if len(top) else "—"})
    return pd.DataFrame(rows).sort_values("Rejected (%)", ascending=False)


def rejections_by_rule(con, u, start=None, end=None, suppliers=None):
    from engine.rules import RULES
    r = rejected_lines(con, u, start, end, suppliers)
    if r.empty:
        return r
    r = r.assign(Rule=r.Reason.fillna("").str.extract(r"(R\d+)")[0].fillna("—"))
    g = r.groupby("Rule").agg(**{"Lines": ("Rule", "size"), "Rejected L": ("Rejected L", "sum"),
                                 "Rejected subsidy (RWF)": ("Rejected subsidy (RWF)", "sum"),
                                 "Suppliers": ("Fuel supplier", "nunique")}).reset_index()
    g.insert(1, "Rule description", g.Rule.map(lambda x: RULES.get(x, "") if isinstance(RULES, dict) else ""))
    return g.sort_values("Rejected subsidy (RWF)", ascending=False)


def processing_time(con, u, start=None, end=None, suppliers=None):
    c = _period(reg.claims(con), "submitted_at", start, end)
    if suppliers:
        c = c[c["name"].isin(suppliers)]
    now = pd.Timestamp.now()
    def days(a, b):
        a, b = pd.to_datetime(a, errors="coerce"), pd.to_datetime(b, errors="coerce")
        return (b - a).dt.days
    sub = pd.to_datetime(c.submitted_at, errors="coerce")
    open_ = ~c.status.isin(["PAID", "RETURNED"])
    return pd.DataFrame({
        "Claim #": c.id, "Fuel supplier": c["name"], "Stage": c.status.map(STAGE).fillna(c.status),
        "Submitted": c.submitted_at, "Days to RRA Staff verification": days(c.submitted_at, c.processed_at),
        "Days verification → approval": days(c.processed_at, c.approved_at),
        "Days approval → payment": days(c.approved_at, c.paid_at),
        "Total days (to payment or today)": [(pd.to_datetime(p, errors="coerce") if not o else now) - s
                                             for s, p, o in zip(sub, c.paid_at, open_)],
    }).assign(**{"Total days (to payment or today)": lambda d: d["Total days (to payment or today)"].dt.days})


def high_consumption(con, u, start=None, end=None, suppliers=None, limit_l=400):
    lines = reg.all_lines(con)
    if lines.empty:
        return pd.DataFrame()
    if suppliers:
        lines = lines[lines.supplier.isin(suppliers)]
    lines = _period(lines, "interval_start", start, end)
    lines = lines.assign(Day=pd.to_datetime(lines.closed_at, errors="coerce").dt.strftime("%d/%m/%Y"))
    g = lines.groupby(["supplier", "client", "vehicle", "Day"]).agg(
        Refuels=("qty", "size"), Litres=("qty", "sum"), Accepted=("accepted_qty", "sum")).reset_index()
    g = g[g.Litres > limit_l].sort_values("Litres", ascending=False)
    return g.rename(columns={"supplier": "Fuel supplier", "client": "Client", "vehicle": "Vehicle",
                             "Litres": "Litres claimed that day", "Accepted": "Litres accepted"})


def pending_review(con, u, start=None, end=None, suppliers=None):
    lines = reg.all_lines(con)
    if lines.empty:
        return pd.DataFrame()
    if suppliers:
        lines = lines[lines.supplier.isin(suppliers)]
    lines = _period(lines, "interval_start", start, end)
    p = lines[lines.pending_qty > 0.005]
    return pd.DataFrame({"Claim #": p.claim_id, "Fuel supplier": p.supplier, "Row": p.source_row,
                         "Vehicle": p.vehicle, "Closed at": p.closed_at.astype(str), "EBM Slip No": p.slip_clean,
                         "Pending L": p.pending_qty, "Pending subsidy (RWF)": p.pending_subsidy,
                         "Why pending": p.review_reason})


CATALOG = [
    Report("claims_statement", "Claims statement", "Claims and payments",
           "Every claim with its stage, litres, subsidy requested / calculated / to reimburse, paid and outstanding.",
           EVERYONE, claims_statement),
    Report("payment_statement", "Payment statement", "Claims and payments",
           "Every amount due (first submission, appeal award, pending lines accepted later), paid or not, with reference.",
           EVERYONE, payment_statement),
    Report("rejected_lines", "Rejected lines and reasons", "Claims and payments",
           "Every rejected line with litres, subsidy and the reason — the basis for an appeal.",
           EVERYONE, rejected_lines),
    Report("appeals_status", "Appeals status", "Claims and payments",
           "Appeals filed, their stage, the award and the decision.", EVERYONE, appeals_status),
    Report("payment_schedule", "Payment schedule (to pay)", "Finance",
           "Amounts approved and not yet paid, with the bank account — the list Finance pays from.",
           STAFF + ("finance", "approver"), payment_schedule),
    Report("rounds_signatures", "Submission rounds and signatures", "Approval",
           "Each round with claims, amount, taskforce approvals and rejections, and the final approval.",
           STAFF + ("finance", "taskforce", "approver"), rounds_signatures),
    Report("monthly_summary", "Monthly summary", "Management",
           "Per month: claims, suppliers, litres claimed / accepted / rejected, RWF requested, calculated, paid.",
           STAFF + ("finance", "taskforce", "approver"), monthly_summary),
    Report("supplier_compliance", "Supplier compliance", "Management",
           "Per fuel supplier: accepted / rejected / pending share, lines not in EBM, duplicates, main rejection rule.",
           STAFF + ("taskforce", "approver"), supplier_compliance),
    Report("rejections_by_rule", "Rejections by rule", "Management",
           "Lines, litres and RWF rejected per verification rule.", STAFF + ("taskforce", "approver"),
           rejections_by_rule),
    Report("processing_time", "Processing time", "Management",
           "Days from submission to RRA Staff verification, approval and payment, per claim.",
           STAFF + ("approver",), processing_time),
    Report("high_consumption", "Vehicles above 400 L a day", "Risk",
           "Vehicle-days with more than 400 litres claimed — to check for abnormal consumption.",
           STAFF + ("taskforce", "approver"), high_consumption),
    Report("pending_review", "Pending lines awaiting decision", "Risk",
           "Lines left pending at analysis and not yet re-routed to accepted or rejected.", STAFF, pending_review),
]


def available(role):
    return [r for r in CATALOG if role in r.roles]
