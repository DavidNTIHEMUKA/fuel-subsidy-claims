"""Payment (finance officer): each amount to pay is a first submission or an appeal award."""
from datetime import date

import pandas as pd
import streamlit as st

from engine import register as reg
from ui import common as ui


def page():
    con, u = ui.db(), ui.user()
    ui.band("Payment", "Approved amounts waiting for transfer — first submissions and appeal awards shown separately. "
                       "Tick each one paid with its reference.")
    pay = reg.payables(con)
    due = pay[pay.status != "PAID"]
    first = due[due.kind == "First submission"]
    appeal = due[due.kind != "First submission"]          # appeal awards and pending lines accepted later
    ui.cards([
        ("First submissions to pay", f"{len(first)}", ui.money(first.outstanding.sum(), "RWF"), "blue"),
        ("Appeal / pending-review awards", f"{len(appeal)}", ui.money(appeal.outstanding.sum(), "RWF"), "orange"),
        ("Paid", f"{int((pay.status == 'PAID').sum())}", ui.money(pay.paid_amount.sum(), "RWF"), "green"),
        ("Rejected after approval", ui.money(_rejected_total(con)), "RWF not payable (see Rejections)", "navy"),
    ])
    st.write("")
    if ui.read_only():
        ui.view_only_note()
        t2, t3 = st.tabs(["Payment register", "Rejections (not payable)"])
        with t2:
            _register(pay)
        with t3:
            _rejections(con)
        return ui.footer()
    t1, t2, t3, t4 = st.tabs(["Tick payments", "Payment register", "Rejections (not payable)", "Undo a payment"])
    with t1:
        _tick(con, u, due)
    with t2:
        _register(pay)
    with t3:
        _rejections(con)
    with t4:
        _undo(con, u, pay)
    ui.footer()


def _filters(df, key):
    with ui.filter_bar() as fb:
        c1, c2, c3 = st.columns([2, 1, 1])
        sup = c1.multiselect("Supplier", sorted(df["name"].dropna().unique()), key=f"{key}_sup",
                             placeholder="All suppliers")
        kind = c2.selectbox("Type", ["All", "First submission", "Appeal", "Pending review"], key=f"{key}_kind")
        rnd = c3.multiselect("Submission round", sorted(df["submission"].dropna().unique()), key=f"{key}_rnd",
                             placeholder="All rounds")
        fb.active(bool(sup) + (kind != "All") + bool(rnd))
    v = df
    if sup:
        v = v[v["name"].isin(sup)]
    if kind == "First submission":
        v = v[v.kind == "First submission"]
    elif kind == "Appeal":
        v = v[v.kind.str.startswith("Appeal")]
    elif kind == "Pending review":
        v = v[v.kind == "Pending review"]
    if rnd:
        v = v[v.submission.isin(rnd)]
    return v


def _tick(con, u, due):
    if due.empty:
        st.success("Nothing waiting for payment.")
        return
    v = _filters(due, "tick")
    a, b = st.columns([1, 3])
    all_ = a.checkbox("Tick all shown", key="pay_all")
    ed = pd.DataFrame({
        "Paid ✓": all_, "Pay #": v.id, "Type": v.kind, "Claim #": v.claim_id, "Supplier": v["name"],
        "Round": v.submission, "Account": v.account, "Due (RWF)": v.amount, "Already paid (RWF)": v.paid_amount,
        "Amount paid now (RWF)": v.outstanding, "Paid on": date.today(), "Payment ref": "",
    })
    out = st.data_editor(
        ed, hide_index=True, width="stretch", key=f"pay_ed_{all_}_{len(ed)}",
        disabled=["Pay #", "Type", "Claim #", "Supplier", "Round", "Account", "Due (RWF)", "Already paid (RWF)"],
        column_config={
            "Paid ✓": st.column_config.CheckboxColumn(help="Tick when the transfer is done"),
            "Due (RWF)": ui.RWF, "Already paid (RWF)": ui.RWF,
            "Amount paid now (RWF)": st.column_config.NumberColumn(format="%,.0f", min_value=0),
            "Paid on": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Payment ref": st.column_config.TextColumn(help="Bank transfer / IFMIS reference (required)"),
        })
    ticked = out[out["Paid ✓"]]
    b.caption(f"{len(ticked)} ticked · {ticked['Amount paid now (RWF)'].sum():,.0f} RWF")
    same_ref = st.text_input("One payment reference for all ticked lines (optional)", key="pay_ref_all")
    if st.button("Save payments", type="primary", disabled=ticked.empty):
        done, errs = [], []
        for r in ticked.itertuples(index=False):
            ref = (str(r[11]).strip() or same_ref.strip())
            try:
                reg.pay_payable(con, int(r[1]), u["name"], float(r[9]), r[10], ref)
                done.append(f"#{r[1]}")
            except ValueError as e:
                errs.append(f"Pay #{r[1]} ({r[2]}, claim #{r[3]}): {e}")
        for e in errs:
            st.error(e)
        if done:
            st.success(f"Payment recorded for {', '.join(done)}.")
            st.rerun()


def _register(pay):
    if pay.empty:
        st.info("No payment yet.")
        return
    v = _filters(pay, "reg")
    cols = {"id": "Pay #", "kind": "Type", "claim_id": "Claim #", "name": "Supplier", "submission": "Round",
            "amount": "Due (RWF)", "paid_amount": "Paid (RWF)", "outstanding": "Outstanding (RWF)", "status": "Status",
            "paid_at": "Paid on", "payment_ref": "Payment ref", "paid_by": "Paid by"}
    t = v[list(cols)].rename(columns=cols)
    st.dataframe(t, hide_index=True, width="stretch",
                 column_config={c: ui.RWF for c in ["Due (RWF)", "Paid (RWF)", "Outstanding (RWF)"]})
    st.download_button("Download payment register (CSV)", t.to_csv(index=False).encode(), file_name="payments.csv")


def _rejected_total(con):
    c = reg.claims(con, status=["APPROVED", "PARTLY PAID", "PAID"])
    return float((c.rejected_rwf.fillna(0) + c.pending_rwf.fillna(0)).sum())


def _rejections(con):
    st.caption("What was claimed but is not payable after approval — the supplier sees the same reasons and can appeal.")
    c = reg.claims(con, status=["APPROVED", "PARTLY PAID", "PAID"])
    if c.empty:
        st.info("No approved claim yet.")
        return
    t = pd.DataFrame({"Claim #": c.id, "Supplier": c["name"], "Round": c.submission, "Claimed (RWF)": c.claimed_rwf,
                      "Approved (RWF)": c.to_reimburse, "Rejected (RWF)": c.rejected_rwf,
                      "Pending review (RWF)": c.pending_rwf, "Added on appeal (RWF)": c.appeal_award})
    st.dataframe(t, hide_index=True, width="stretch", column_config={x: ui.RWF for x in t.columns if "RWF" in x})
    cid = st.selectbox("Rejection reasons of claim", c.id.tolist(),
                       format_func=lambda i: f"#{i} · {c.loc[c.id == i, 'name'].iloc[0]}")
    L = reg.lines_for(con, cid)
    L = L[L.rejected_qty > 0]
    if L.empty:
        st.success("No rejected line.")
        return
    by = (L.assign(rule=L.reason.str.extract(r"(R\d+)")[0].fillna("—"))
          .groupby("rule").agg(lines=("rule", "size"), litres=("rejected_qty", "sum"), rwf=("rejected_subsidy", "sum"))
          .reset_index())
    st.dataframe(by, hide_index=True, column_config={"rwf": ui.RWF, "litres": ui.LITRES})


def _undo(con, u, pay):
    paid = pay[pay.paid_amount > 0]
    if paid.empty:
        st.info("No payment recorded yet.")
        return
    cid = st.selectbox("Claim", sorted(paid.claim_id.unique()),
                       format_func=lambda i: f"#{i} · {paid.loc[paid.claim_id == i, 'name'].iloc[0]}")
    reason = st.text_input("Reason (required)", key="undo_reason")
    if st.button("Undo the payments of this claim"):
        try:
            reg.unmark_paid(con, int(cid), u["name"], reason)
            st.rerun()
        except ValueError as e:
            st.error(str(e))
