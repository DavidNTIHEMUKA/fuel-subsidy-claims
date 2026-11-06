"""File tracking for the fuel supplier: where each claim is, what happens next, amounts, history."""
import html

import pandas as pd
import streamlit as st

from engine import register as reg
from engine import workflow as wf
from ui import common as ui

STAGES = ["Submission", "System verification", "RRA Staff verification", "Taskforce signatures", "Final approval",
          "Paid"]

# plain-language history (event action -> sentence)
FRIENDLY = {
    "SUBMITTED": "Submission received",
    "WARNINGS CONFIRMED": "You confirmed the file despite warnings",
    "REQUEST AMOUNT": "Amount requested / letter recorded by RRA",
    "PROCESSED": "System verification (EBM) done and verified by RRA staff",
    "IN ROUND": "Included in the submission round",
    "ROUND RETURNED": "Round returned by the taskforce to RRA",
    "APPROVED": "Approved for payment",
    "PARTLY PAID": "Partly paid",
    "PAID": "Paid",
    "PAYMENT": "Payment updated",
    "RETURNED": "Returned to you",
    "PENDING DECIDED": "Pending lines decided by RRA",
}


def _round(con, row):
    if pd.isna(row.round_id):
        return None
    r = wf.rounds(con)
    r = r[r.id == int(row.round_id)]
    return r.iloc[0] if not r.empty else None


def stage(con, row):
    """(done_upto, current, headline, next_step, tone) for one claim."""
    s = row.status
    rnd = _round(con, row)
    pending = float(row.pending_l or 0) if pd.notna(row.pending_l) else 0.0
    if s == "RETURNED":
        return 0, None, f"Returned to you — {row.note or 'see the reason in the history'}", \
            "Correct the file and submit it again under Submission of request.", "orange"
    if s == "SUBMITTED":
        return 0, 1, "Submitted — waiting for system verification (checks against EBM)", \
            "Nothing to do. The system checks every line against EBM, then RRA staff verify the result.", "blue"
    if s == "PROCESSED" and rnd is None:
        return 2, 3, "System verification and RRA Staff verification done — waiting to be included in a submission round", \
            "Nothing to do. The verified claim is grouped with others for the taskforce.", "blue"
    if s == "PROCESSED" and rnd is not None:
        if rnd.status == "SIGNED":
            return 3, 4, f"{rnd['name']}: all taskforce members signed — waiting for the final approval", \
                "Nothing to do.", "blue"
        return 2, 3, (f"{rnd['name']}: taskforce signatures {int(rnd.signed)} of {int(rnd.signatories)}"), \
            "Nothing to do. Each taskforce member signs the round electronically.", "blue"
    paid, due = float(row.paid_amount or 0) if pd.notna(row.paid_amount) else 0.0, float(row.to_reimburse or 0)
    if s == "APPROVED":
        return 4, 5, f"Approved — {ui.money(due, 'RWF')} waiting for payment by Finance", \
            "Nothing to do. Payment is made to the account you gave.", "green"
    if s == "PARTLY PAID":
        return 4, 5, f"Partly paid — {ui.money(paid, 'RWF')} of {ui.money(due, 'RWF')}", \
            "The rest is being paid (for example an appeal award or lines accepted later).", "green"
    if s == "PAID":
        nxt = "Completed." + (f" {pending:,.2f} L are still pending review by RRA." if pending > 0.005 else "")
        return 5, None, f"Paid — {ui.money(paid, 'RWF')}" + (f" · ref {row.payment_ref}" if row.payment_ref else ""), \
            nxt, "green"
    return 0, None, s.title(), "", "navy"


def _history(con, cid, me):
    ev = reg.events(con, cid)
    if ev.empty:
        return ev
    def who(w):
        return "You" if w == me else ("RRA" if w else "")
    def what(a):
        if a.startswith("APPEAL #"):
            return "Appeal " + a.split(" ", 2)[1] + " — " + a.split(" ", 2)[2].title() if a.count(" ") >= 2 else a
        return FRIENDLY.get(a, a.title())
    return pd.DataFrame({"When": ev["at"], "What happened": ev["action"].map(what), "By": ev["who"].map(who),
                         "Details": ev["note"].fillna("")}).iloc[::-1]


def track(con, row, me):
    """Full tracker for one claim (supplier view)."""
    done, current, headline, nxt, tone = stage(con, row)
    color = {"green": ui.GREEN, "orange": ui.ORANGE, "blue": "#1F5FA8", "navy": ui.NAVY}[tone]
    period = f"{pd.Timestamp(row.interval_start):%d/%m/%Y} – {pd.Timestamp(row.interval_end):%d/%m/%Y}"
    st.markdown(
        f'<div style="border-left:6px solid {color};background:#fff;border-radius:10px;padding:14px 18px;'
        f'box-shadow:0 1px 3px rgba(11,43,87,.12);margin:6px 0 10px">'
        f'<div style="font-size:13px;color:#5A6B85">Claim #{row.id} · consumption {period} · submitted '
        f'{row.submitted_at}</div>'
        f'<div style="font-size:21px;font-weight:800;color:{color};margin:4px 0">{html.escape(headline)}</div>'
        f'<div style="font-size:14px;color:{ui.NAVY}"><b>Next:</b> {html.escape(nxt)}</div></div>',
        unsafe_allow_html=True)
    if row.status != "RETURNED":
        ui.steps(STAGES, done, current)

    req = row.requested_rwf if pd.notna(row.requested_rwf) else None
    calc = row.calculated_rwf if pd.notna(row.calculated_rwf) else (row.to_reimburse if pd.notna(row.to_reimburse) else None)
    analysed = row.status not in ("SUBMITTED", "RETURNED")
    ui.cards([
        ("Requested", ui.money(req, "RWF") if req else "—", "your letter", "navy"),
        ("Calculated by RRA", ui.money(calc, "RWF") if analysed else "after analysis",
         "accepted lines × official rate", "blue"),
        ("To reimburse", ui.money(row.to_reimburse, "RWF") if analysed else "—", "the lower of the two", "green"),
        ("Paid", ui.money(row.paid_amount or 0, "RWF"),
         f"outstanding {ui.money(row.outstanding, 'RWF')}" if analysed else "", "orange"),
    ])

    if analysed:
        lines = reg.lines_for(con, row.id)
        acc = lines[lines.accepted_qty > 0]
        pen = lines[lines.pending_qty > 0.005]
        rej = lines[lines.rejected_qty > 0]
        st.markdown(f"**Your lines:** ✅ {len(acc)} accepted ({acc.accepted_qty.sum():,.2f} L) · "
                    f"⏳ {len(pen)} pending review ({pen.pending_qty.sum():,.2f} L) · "
                    f"❌ {len(rej)} rejected ({rej.rejected_qty.sum():,.2f} L)")
        t1, t2, t3 = st.tabs([f"Rejected ({len(rej)})", f"Pending review ({len(pen)})", f"Accepted ({len(acc)})"])
        with t1:
            if rej.empty:
                st.caption("No rejected line.")
            else:
                st.caption("You can contest rejected lines under **Appeal**.")
                st.dataframe(rej[["source_row", "vehicle", "closed_at", "slip_clean", "rejected_qty",
                                  "rejected_subsidy", "reason"]].rename(columns={
                    "source_row": "Row", "vehicle": "Vehicle", "closed_at": "Closed at", "slip_clean": "EBM Slip No",
                    "rejected_qty": "Rejected L", "rejected_subsidy": "Rejected RWF", "reason": "Reason"}),
                    hide_index=True, width="stretch", column_config={"Rejected RWF": ui.RWF, "Rejected L": ui.LITRES})
        with t2:
            if pen.empty:
                st.caption("No pending line.")
            else:
                st.caption("RRA decides these lines case by case; they are paid if accepted.")
                st.dataframe(pen[["source_row", "vehicle", "closed_at", "slip_clean", "pending_qty",
                                  "pending_subsidy"]].rename(columns={
                    "source_row": "Row", "vehicle": "Vehicle", "closed_at": "Closed at", "slip_clean": "EBM Slip No",
                    "pending_qty": "Pending L", "pending_subsidy": "Pending RWF"}),
                    hide_index=True, width="stretch", column_config={"Pending RWF": ui.RWF, "Pending L": ui.LITRES})
        with t3:
            st.dataframe(acc[["source_row", "vehicle", "closed_at", "slip_clean", "accepted_qty",
                              "accepted_subsidy"]].rename(columns={
                "source_row": "Row", "vehicle": "Vehicle", "closed_at": "Closed at", "slip_clean": "EBM Slip No",
                "accepted_qty": "Accepted L", "accepted_subsidy": "Subsidy RWF"}),
                hide_index=True, width="stretch", column_config={"Subsidy RWF": ui.RWF, "Accepted L": ui.LITRES})

    ap = reg.appeals(con)
    ap = ap[ap.claim_id == row.id]
    if not ap.empty:
        st.markdown("**Appeals on this claim**")
        from ui.appeal import _step_label
        for _, a in ap.iterrows():
            st.markdown(f"Appeal #{a['id']} · filed {a.submitted_at} · **{_step_label(con, a)}**"
                        + (f" · award {ui.money(a.award_rwf, 'RWF')}" if pd.notna(a.award_rwf) and a.award_rwf else ""))
    with st.expander("History of the file", expanded=False):
        st.dataframe(_history(con, row.id, me), hide_index=True, width="stretch")


def overview(con, df):
    """One line per claim with its current stage (supplier Home)."""
    for r in df.head(8).itertuples():
        done, current, headline, _, tone = stage(con, r)
        pct = int(100 * (done + 1) / len(STAGES)) if r.status != "RETURNED" else 100
        color = {"green": ui.GREEN, "orange": ui.ORANGE, "blue": "#1F5FA8", "navy": ui.NAVY}[tone]
        st.markdown(
            f'<div style="background:#fff;border:1px solid #DCE4EF;border-radius:10px;padding:10px 14px;margin:6px 0">'
            f'<div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap">'
            f'<b style="color:{ui.NAVY}">Claim #{r.id} · {pd.Timestamp(r.interval_start):%d/%m} – '
            f'{pd.Timestamp(r.interval_end):%d/%m/%Y}</b>'
            f'<span style="color:{color};font-weight:700">{html.escape(headline)}</span></div>'
            f'<div style="height:8px;background:#EEF3F9;border-radius:6px;margin-top:8px">'
            f'<div style="width:{pct}%;height:8px;background:{color};border-radius:6px"></div></div></div>',
            unsafe_allow_html=True)
