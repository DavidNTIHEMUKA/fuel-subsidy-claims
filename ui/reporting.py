"""Reporting: a catalogue of reports for every role (each user sees only what concerns them) and data extraction
for RRA officers and analysts."""
import re
from datetime import date, datetime

import pandas as pd
import streamlit as st

from engine import export as ex
from engine import reports_catalog as rc
from ui import common as ui

EXTRACTION_ROLES = ("officer", "admin")          # RRA officers / analysts


def page():
    con, u = ui.db(), ui.user()
    ui.band("Reporting", "Reports to view and download. Each person sees the reports of their role, "
                         "and a fuel supplier only its own data.")
    reports = rc.available(u["role"])
    names = ["Reports", "Taskforce batch report"] + (["Data extraction"] if u["role"] in EXTRACTION_ROLES else [])
    tabs = st.tabs(names)
    with tabs[0]:
        _reports(con, u, reports)
    with tabs[1]:
        _batch_report(con, u)
    if len(tabs) > 2:
        with tabs[2]:
            data_extraction(con)


BATCH_VIEWS = [  # (key, title, description, who): suppliers see their own OMC profile only
    ("batch_overview", "Scheme overview", "Litres and RWF claimed, accepted and pending / rejected, all batches.", "staff"),
    ("batch_by_batch", "Claimed vs reimbursable, by batch", "Claimed and submitted-for-reimbursement amounts per "
                                                            "batch, with the payout percentage.", "staff"),
    ("batch_by_omc", "Results by oil marketing company", "Batches, litres claimed and accepted, acceptance rate "
                                                         "(low flagged), RWF and share of the total.", "staff"),
    ("batch_coverage", "Batches processed per OMC, with coverage dates", "Which period each OMC was reimbursed "
                                                                          "for in each batch; overlaps marked *.", "staff"),
    ("batch_checks", "Points to check", "Overlapping periods, gaps, unusual rate per litre, low acceptance, no "
                                        "vehicles, round figures, catch-up claims.", "staff"),
    ("batch_profile", "OMC profile", "One company: figures, batch-by-batch table and points to check.", "everyone"),
    ("batch_powerpoint", "Download the report (PowerPoint)", "The whole Taskforce report as slides, built from the "
                                                             "data.", "staff"),
]
BATCH_STAFF = ("officer", "admin", "manager", "senior_manager", "taskforce", "approver", "finance")


def _batch_report(con, u):
    from ui import batch_report as br
    views = [v for v in BATCH_VIEWS if v[3] == "everyone" or u["role"] in BATCH_STAFF]
    if u["role"] == "supplier":
        st.caption("Your company's results in every reimbursement batch.")
    c1, c2 = st.columns([1, 2])
    key = c1.radio("Report", [v[0] for v in views], key="bt_view",
                   format_func=lambda k: next(v[1] for v in views if v[0] == k))
    title, desc = next((v[1], v[2]) for v in views if v[0] == key)
    c2.markdown(f"#### {title}\n{desc}")
    st.divider()
    br.VIEWS[key](con, u)
    ui.footer()


def _reports(con, u, reports):
    if not reports:
        st.info("No report for your role.")
        return
    groups = list(dict.fromkeys(r.group for r in reports))
    c1, c2 = st.columns([1, 2])
    group = c1.radio("Group", groups, key="rep_group")
    choices = [r for r in reports if r.group == group]
    with c2:
        for r in choices:
            st.markdown(f"**{r.title}** — {r.description}")
    rep = st.selectbox("Report", choices, format_func=lambda r: r.title, key=f"rep_pick_{group}")

    with ui.filter_bar() as fb:
        f1, f2, f3 = st.columns([1, 1, 2])
        start = f1.date_input("From (optional)", value=None, format="DD/MM/YYYY", key="rep_from")
        end = f2.date_input("To (optional)", value=None, format="DD/MM/YYYY", key="rep_to")
        sup = None
        if u["role"] != "supplier":
            from engine import register as reg
            allc = reg.claims(con)
            sup = f3.multiselect("Fuel supplier", sorted(allc["name"].dropna().unique()) if not allc.empty else [],
                                 key="rep_sup", placeholder="All suppliers")
        fb.active(bool(start) + bool(end) + bool(sup))
    try:
        df = rep.build(con, u, start, end, sup or None)
    except Exception as e:                   # a report must never break the page
        st.error(f"This report could not be produced: {e}")
        return
    if df is None or df.empty:
        st.info("No data for this report with these filters.")
        return
    money = [c for c in df.columns if "(RWF)" in c]
    st.caption(f"{len(df):,} rows" + (" · " + " · ".join(f"{c.replace(' (RWF)', '')}: {df[c].fillna(0).sum():,.0f} RWF"
                                                          for c in money[:3]) if money else ""))
    st.dataframe(df, hide_index=True, width="stretch", column_config={c: ui.RWF for c in money})
    stamp = f"{datetime.now():%Y%m%d_%H%M}"
    fn = re.sub(r"[^a-z0-9]+", "_", rep.title.lower()).strip("_")
    who = u["name"] + (f" (TIN {u['tin']})" if u.get("tin") else "")
    period = (f"{start:%d/%m/%Y}" if start else "start") + " – " + (f"{end:%d/%m/%Y}" if end else "today")
    head = pd.DataFrame({rep.title: [f"Fuel Subsidy Claims Platform — RURA · RRA · MINECOFIN · MININFRA",
                                     f"Prepared for {who} on {datetime.now():%d/%m/%Y %H:%M}",
                                     f"Period: {period}" + (f" · suppliers: {', '.join(sup)}" if sup else ""), ""]})
    a, b = st.columns(2)
    a.download_button("Download (Excel)", ex.to_excel({"About": head, rep.title[:31]: df}),
                      file_name=f"{fn}_{stamp}.xlsx", type="primary", key=f"rep_x_{rep.key}", width="stretch")
    b.download_button("Download (CSV)", df.to_csv(index=False).encode(), file_name=f"{fn}_{stamp}.csv",
                      key=f"rep_c_{rep.key}", width="stretch")


def data_extraction(con):
    from datetime import datetime
    from engine import export as ex
    stamp = f"{datetime.now():%Y%m%d_%H%M}"
    st.caption("Extract the data of the platform. Queries run on a copy of the database: they cannot change "
               "anything. Passwords and file contents are never included in extracts.")

    st.markdown("**1 · Ready-made extracts**")
    a, b = st.columns([3, 1])
    name = a.selectbox("Extract", list(ex.READY), key="exp_ready")
    with st.expander("See the SQL of this extract"):
        st.code(ex.READY[name].strip(), language="sql")
    try:
        df = ex.run_query(con, ex.READY[name])
        st.caption(f"{len(df):,} rows")
        st.dataframe(df.head(500), hide_index=True, width="stretch")
        c1, c2 = st.columns(2)
        fn = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        c1.download_button("Download (Excel)", ex.to_excel({name: df}), file_name=f"{fn}_{stamp}.xlsx",
                           type="primary", key="exp_r_x", width="stretch")
        c2.download_button("Download (CSV)", df.to_csv(index=False).encode(), file_name=f"{fn}_{stamp}.csv",
                           key="exp_r_c", width="stretch")
    except ValueError as e:
        st.error(str(e))

    st.divider()
    st.markdown("**2 · Your own query (SQL)**")
    with st.expander("Tables and columns you can use"):
        cols = ex.columns(con)
        for tname, desc in ex.TABLES.items():
            st.markdown(f"**`{tname}`** — {desc}  \n`" + "`, `".join(cols.get(tname, [])) + "`")
    sql = st.text_area("SQL (SELECT only)", height=140, key="exp_sql",
                       value="SELECT tin, name, status, to_reimburse, paid_amount\nFROM claims\nWHERE status = 'PAID'")
    if st.button("Run query", key="exp_run"):
        try:
            st.session_state["exp_result"] = ex.run_query(con, sql)
        except ValueError as e:
            st.session_state.pop("exp_result", None)
            st.error(str(e))
    res = st.session_state.get("exp_result")
    if res is not None:
        st.caption(f"{len(res):,} rows")
        st.dataframe(res.head(1000), hide_index=True, width="stretch")
        c1, c2 = st.columns(2)
        c1.download_button("Download result (Excel)", ex.to_excel({"Query": res}), file_name=f"query_{stamp}.xlsx",
                           type="primary", key="exp_q_x", width="stretch")
        c2.download_button("Download result (CSV)", res.to_csv(index=False).encode(), file_name=f"query_{stamp}.csv",
                           key="exp_q_c", width="stretch")

    st.divider()
    st.markdown("**3 · Everything**")
    if st.button("Prepare all tables (Excel, one sheet per table)", key="exp_all"):
        st.session_state["exp_all_bytes"] = ex.all_tables_excel(con)
    if st.session_state.get("exp_all_bytes"):
        st.download_button("Download all tables (Excel)", st.session_state["exp_all_bytes"],
                           file_name=f"fuel_subsidy_all_tables_{stamp}.xlsx", type="primary", key="exp_all_dl")
