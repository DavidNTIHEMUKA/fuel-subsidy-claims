import pandas as pd
import streamlit as st

from engine import register as reg
from engine.report import round_excel, round_table
from ui import common as ui

DEFAULT_SIGNATORIES = """MUKANGABO Beatha (RURA) Chair
Mutabazi Eric (MINECOFIN), Co-chair
Mukamurera Venerande (RURA)
Tuyizere Aimable (RURA)
Rubayiza Noel (RURA)
Ntihemuka David (RRA)
Ndahayo Capiton (MININFRA)
Mugabe Emmanuel (RURA)"""

DETAIL = {"supplier": "Supplier", "claim_id": "Claim #", "source_row": "Row", "omc_tin": "OMC TIN", "client": "Client",
          "vehicle": "Vehicle", "closed_at": "Closed at", "product_raw": "Product", "slip_clean": "EBM Slip No",
          "invoice_clean": "EBM invoice", "qty": "Claimed L", "accepted_qty": "Accepted L",
          "accepted_subsidy": "Subsidy paid (RWF)", "rejected_qty": "Rejected L",
          "rejected_subsidy": "Subsidy rejected (RWF)", "reason": "Reason", "status": "Status",
          "decision": "Decision"}


def page():
    con = ui.db()
    ui.band("Analysis", "Reimbursement report for signature, accepted and rejected details, appeals and audit trail.")
    df = reg.claims(con, status=["PROCESSED", "APPROVED", "PARTLY PAID", "PAID"])
    t = st.tabs(["Reimbursement report", "Accepted details", "Rejected details", "Claim reports", "Appeals", "Audit log"])

    with t[0]:
        from engine import workflow as wf
        from ui.approval import round_report
        r = wf.rounds(con)
        if r.empty:
            st.info("No submission round yet. Rounds are created on the Approval page from verified claims.")
        else:
            rid = st.selectbox("Submission round", r.id.tolist(), key="rep_round",
                               format_func=lambda i: (lambda x: f"{x['name']} · {x.status.title()} · "
                                                                f"{x.signed}/{x.signatories} taskforce approvals")(
                                   r[r.id == i].iloc[0]))
            claims = wf.round_claims(con, rid)
            table = round_table(claims.sort_values("name"))
            money = ["Subsidies claimed (RWF)", "Subsidies calculated (RWF)", "Amount to reimburse (RWF)", "Amount to reimburse rejected (RWF)"]
            st.dataframe(table, hide_index=True, width="stretch", column_config={c: ui.RWF for c in money})
            sig = wf.round_signatures(con, rid)
            if not sig.empty:
                st.dataframe(sig[["name", "title", "decision", "signed_at", "comment"]].rename(
                    columns={"name": "Name", "title": "Role", "decision": "Decision", "signed_at": "Signed",
                             "comment": "Comment"}), hide_index=True, width="stretch")
            st.download_button("Download the report (Excel, with electronic signatures)", round_report(con, rid),
                               file_name=f"round_report_{rid}.xlsx", type="primary")
        rounds = [x for x in df["submission"].dropna().unique().tolist() if x] if not df.empty else []

    lines = reg.all_lines(con)
    for i, (label, mask_col) in ((1, ("accepted", "accepted_qty")), (2, ("rejected", "rejected_qty"))):
        with t[i]:
            if lines.empty:
                st.info("No analysed lines yet.")
                continue
            f1, f2 = st.columns(2)
            sup = f1.multiselect("Supplier", sorted(lines.supplier.unique()), key=f"sup_{i}")
            rnd = f2.multiselect("Submission round", rounds, key=f"rnd_{i}")
            v = lines[lines[mask_col] > 0]
            v = v[v.supplier.isin(sup)] if sup else v
            v = v[v.submission.isin(rnd)] if rnd else v
            d = _detail(v)
            amount = "Subsidy paid (RWF)" if i == 1 else "Subsidy rejected (RWF)"
            st.caption(f"{len(d):,} lines · {v[mask_col].sum():,.2f} L · {d[amount].sum():,.0f} RWF")
            st.dataframe(d, hide_index=True, width="stretch", column_config={amount: ui.RWF})
            if i == 2 and not v.empty:
                by = (v.assign(rule=v.reason.str.extract(r"(R\d)")[0].fillna("—"))
                      .groupby("rule").agg(lines=("rule", "size"), litres=("rejected_qty", "sum"),
                                           rwf=("rejected_subsidy", "sum")).reset_index())
                st.markdown("**By rule**")
                st.dataframe(by, hide_index=True, column_config={"rwf": ui.RWF, "litres": ui.LITRES})
            st.download_button(f"Download {label} details (CSV)", d.to_csv(index=False).encode(),
                               file_name=f"{label}_details.csv", key=f"dl_{i}")

    with t[3]:
        if df.empty:
            st.info("No analysed claims yet.")
        else:
            cid = st.selectbox("Claim", df.id.tolist(),
                               format_func=lambda i: f"#{i} · {df.loc[df.id == i, 'name'].iloc[0]} · "
                                                     f"{df.loc[df.id == i, 'submission'].iloc[0] or ''}")
            st.download_button("Download full analysis (Excel)", reg.report(con, cid), file_name=f"claim_{cid}_analysis.xlsx")
    with t[4]:
        ap = reg.appeals(con)
        st.dataframe(ap.drop(columns=["tin"]), hide_index=True, width="stretch", column_config={"award_rwf": ui.RWF})
    with t[5]:
        ev = reg.events(con)
        st.dataframe(ev, hide_index=True, width="stretch")
        st.download_button("Download audit log (CSV)", ev.to_csv(index=False).encode(), file_name="audit_log.csv")
    ui.footer()


def _report_preview():
    """Show the report layout (empty) so officers see its structure before any claim is analysed."""
    from engine.report import ROUND_COLUMNS
    st.markdown("##### SUBMISSION OF THE [Nth] REIMBURSEMENT REQUESTS OF FUEL SUBSIDIES ([MONTH, YEAR])")
    empty = pd.DataFrame([["" for _ in ROUND_COLUMNS]] * 3 + [["", "TOTAL"] + [""] * (len(ROUND_COLUMNS) - 2)],
                         columns=ROUND_COLUMNS)
    st.dataframe(empty, hide_index=True, width="stretch")
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown("**Verified by Interministerial Taskforce**")
        rows = "".join(f"<div>{n}</div><div>Signature: ____________</div>" for n in DEFAULT_SIGNATORIES.splitlines())
        st.markdown(f'<div style="display:grid;grid-template-columns:minmax(0,1fr) 200px;row-gap:6px">{rows}</div>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown("**Approved by**")
        st.markdown("RUGIGANA Evariste  \nSignature: ____________")
    st.markdown("**The downloaded Excel report has three sheets:**")
    st.markdown("- **Report** — the table above with totals and the signature block\n"
                "- **Accepted details** — every accepted line (supplier, vehicle, date, EBM invoice, litres, subsidy)\n"
                "- **Rejected details** — every rejected line with litres, amount and the reason for rejection")


def _detail(df):
    cols = [c for c in DETAIL if c in df]
    return df[cols].rename(columns=DETAIL)
