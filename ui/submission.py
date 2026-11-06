import io

import pandas as pd
import streamlit as st

from engine import register as reg
from engine.cleaning import CLAIM_COLUMNS, CLAIM_REQUIRED, clean_claim, parse_interval, read_table
from ui import common as ui


def _precheck(data: bytes, filename: str):
    """Instant format check before submission (no EBM needed)."""
    b = io.BytesIO(data)
    b.name = filename
    raw, problems = read_table(b, CLAIM_COLUMNS, CLAIM_REQUIRED, "Claim file")
    if raw.empty or any("not found" in p or "no header" in p for p in problems):
        return None, problems, (None, None)
    clean = clean_claim(raw)
    year = clean["closed_at"].dropna().min().year if clean["closed_at"].notna().any() else None
    interval = parse_interval(raw.attrs.get("preamble", ""), default_year=year)
    if interval[0] is not None:
        clean = clean_claim(raw, interval=interval)      # settle day/month using the declared interval
    if clean.attrs.get("date_summary"):
        problems = problems + [clean.attrs["date_summary"]]
    from engine.forms import form_check, is_claim_form
    if not is_claim_form(data):
        problems = problems + form_check(raw)
    return clean, problems, interval


def page():
    con, u = ui.db(), ui.user()
    officer = ui.is_officer()
    ui.band("Submission of request", "Fill the official claim form, upload it with your request letter and the amount "
                                     "requested, check the warnings and submit.")
    if ui.read_only():
        ui.view_only_note()
        return _status(con, u, officer, st.container())
    tab_new, tab_status = st.tabs(["New request", "My requests and status" if not officer else "All requests and status"])

    with tab_new:
        c1, c2 = st.columns([3, 2], gap="large")
        with c2:
            from engine.forms import claim_form
            st.markdown(ui.card("Use the standard claim form", "Claim form",
                                "16 fixed columns incl. OMC TIN, real date cells (dd/mm/yyyy hh:mm), product list, automatic "
                                "amounts, EBM Slip No check — avoids rejected lines caused by formatting", "orange"),
                        unsafe_allow_html=True)
            st.write("")
            st.download_button("Download the claim form (Excel)",
                               claim_form(u["name"] if not officer else "", (u.get("tin") or "") if not officer else ""),
                               file_name="fuel_subsidy_claim_form.xlsx", type="primary", width="stretch")
            st.caption("Fill one line per sale, the period in cell A4, and the EBM Slip No as SDC ID / receipt "
                       "counter (SDC010057290/10540). Each line is later checked against EBM.")
        with c1:
            ui.steps(["1 Upload the claim form", "2 Details", "3 Checks", "4 Confirm and submit"], -1, 0)
            up = st.file_uploader("Claim file (the official claim form, .xlsx)", type=["xlsx", "xls", "csv"])
            if up is None:
                st.info("Download the claim form, fill it and upload it here.")
                return _status(con, u, officer, tab_status)
            data = up.getvalue()
            from engine import workflow as wf
            from engine.forms import is_claim_form
            if not officer and wf.setting(con, "strict_form") and not is_claim_form(data):
                st.error("**This file is not the official claim form, so it cannot be submitted.** Download the claim "
                         "form (right), copy your lines into it without changing the columns, and upload it again.")
                return _status(con, u, officer, tab_status)
            clean, problems, (f_start, f_end) = _precheck(data, up.name)
            for p in problems:
                if p.startswith("Dates in the"):
                    st.info(p)
                elif p.startswith(("Not the standard claim form", "'Closed at'")) or "typed as text" in p:
                    st.warning(p)
                else:
                    st.error(p)
            if clean is None:
                st.error("**Form rejected:** the file cannot be read — the columns of the claim form are missing or "
                         "renamed. Use the official claim form and upload it again.")
                return _status(con, u, officer, tab_status)

        issues = clean[clean["format_issues"] != ""]
        warns = clean[clean["warnings"] != ""]
        dates = clean["closed_at"].dropna()
        ui.cards([
            ("Lines", f"{len(clean):,}", up.name, "navy"),
            ("Fuel claimed", f"{clean['qty'].fillna(0).sum():,.2f} L", f"{clean['vehicle'].nunique()} vehicles", "blue"),
            ("Subsidy claimed", ui.money(clean["subsidy_amount"].fillna(0).sum() or
                                         (clean["qty"].fillna(0) * clean["subsidy_rate"].fillna(0)).sum(), "RWF"), "", "green"),
            ("Lines to fix", f"{len(issues):,}", f"{len(warns)} with amount warnings", "orange"),
        ])
        if not dates.empty:
            st.caption(f"Transaction dates in the file: {dates.min():%d/%m/%Y} – {dates.max():%d/%m/%Y}")
        if len(issues) or len(warns):
            with st.expander(f"Fix before submitting — {len(issues)} lines with problems, {len(warns)} with warnings",
                             expanded=bool(len(issues))):
                show = pd.concat([issues, warns]).drop_duplicates("source_row").sort_values("source_row")
                st.dataframe(show[["source_row", "vehicle", "slip_raw", "slip_clean", "qty", "format_issues",
                                   "warnings"]].rename(
                    columns={"source_row": "Row", "vehicle": "Vehicle", "slip_raw": "EBM Slip No (as sent)",
                             "slip_clean": "EBM Slip No (cleaned)", "qty": "Quantity",
                             "format_issues": "Problem", "warnings": "Warning"}), hide_index=True, width="stretch")

        # ---- 2. details ----
        with st.container(border=True):
            st.markdown("**2 · Details**")
            d1, d2 = st.columns(2)
            start = d1.date_input("Consumption from (required)", value=f_start.date() if f_start is not None else None,
                                  format="DD/MM/YYYY", key=f"s_from_{up.name}")
            end = d2.date_input("Consumption to (required)", value=f_end.date() if f_end is not None else None,
                                format="DD/MM/YYYY", key=f"s_to_{up.name}")
            if f_start is not None:
                st.caption(f"Read from the claim form: {f_start:%d/%m/%Y} – {f_end:%d/%m/%Y}")
            n1, n2 = st.columns(2)
            name = n1.text_input("Taxpayer name / Fuel supplier", value=u["name"] if not officer else "",
                                 key=f"s_name_{up.name}")
            tin = n2.text_input("TIN", value=u.get("tin") or "", disabled=not officer, key=f"s_tin_{up.name}")
            last = con.execute("SELECT account FROM claims WHERE tin=? AND account NOT IN ('', '—') ORDER BY id DESC",
                               ((tin or u.get("tin") or "").strip(),)).fetchone()
            account = st.text_input("Bank and account number for payment", value=last[0] if last else "",
                                    placeholder="e.g. BANK OF KIGALI A/C 1000…", key=f"s_acc_{up.name}")
            st.markdown("**Request letter and amount requested**")
            l1, l2 = st.columns(2)
            file_total = float(clean["subsidy_amount"].fillna(0).sum() or
                               (clean["qty"].fillna(0) * clean["subsidy_rate"].fillna(0)).sum())
            requested = l1.number_input("Amount of subsidies requested (RWF) — as in your letter", min_value=0.0,
                                        value=None, step=1000.0, format="%.0f", key=f"s_req_{up.name}",
                                        placeholder=f"e.g. {file_total:,.0f}")
            letter = l2.file_uploader("Request letter (signed, PDF or image)", type=["pdf", "png", "jpg", "jpeg", "docx"],
                                      key=f"s_letter_{up.name}")
            if requested:
                st.caption(f"Subsidy in the claim form: {file_total:,.0f} RWF · requested: {requested:,.0f} RWF. "
                           "RRA pays the **lower** of the amount requested and the subsidy calculated after the EBM checks.")
                if abs(requested - file_total) > max(1.0, 0.005 * file_total):
                    st.warning(f"The amount requested ({requested:,.0f} RWF) differs from the subsidy in the claim form "
                               f"({file_total:,.0f} RWF) by {requested - file_total:+,.0f} RWF. Check your letter.")
            note = st.text_area("Note to the officers (optional)", height=70, key=f"s_note_{up.name}")

        # ---- 3. checks before confirmation ----
        from engine.precheck import submission_warnings
        from engine.pipeline import DEFAULT_PRICE_FILE, load_rura_prices
        pb, pn, _ = reg.get_setting(con, "rura_prices")
        if pb:
            pf = io.BytesIO(pb); pf.name = pn
            prices = load_rura_prices(pf)
        else:
            prices = load_rura_prices(DEFAULT_PRICE_FILE)
        w = submission_warnings(clean, start, end, wf.subsidy_rates(con), prices,
                                 own_tin=(tin or u.get("tin") or "").strip() or None)
        with st.container(border=True):
            st.markdown("**3 · Checks before you confirm**")
            if w.empty:
                st.success("No warning: interval, subsidy rate and fuel prices are consistent with the official values.")
            else:
                st.warning(f"**{len(w)} warning(s)** — read them before confirming. You can correct the form and upload "
                           "it again, or confirm anyway (lines with problems may be rejected).")
                st.dataframe(w, hide_index=True, width="stretch")
            rates = wf.subsidy_rates(con)
            st.caption("Official subsidy: " + " · ".join(f"{p.title()} {v:,.0f}" for p, v in rates.items()) +
                       " RWF/L · RURA prices: Diesel 2,927 · Petrol 2,938 RWF/L (current reference)")

        # ---- 4. confirm ----
        with st.container(border=True):
            st.markdown("**4 · Confirm and submit**")
            ok = st.checkbox("I confirm the information is correct" + (" and I have read the warnings above"
                                                                     if not w.empty else ""), key=f"s_ok_{up.name}")
            sent = st.button("Submit request", type="primary", disabled=not ok)
        if sent:
            try:
                if not (start and end):
                    raise ValueError("The consumption interval (from–to) is required")
                if not account.strip():
                    raise ValueError("The bank account for payment is required")
                if not officer and not requested:
                    raise ValueError("Give the amount of subsidies requested (RWF), as written in your letter")
                if not officer and letter is None:
                    raise ValueError("Upload the signed request letter")
                who = dict(u, tin=tin.strip() if officer else u.get("tin"))
                cid = reg.submit_claim(con, who, name, start, end, account, data, up.name, note,
                                       requested_rwf=requested or None,
                                       letter=letter.getvalue() if letter else None,
                                       letter_name=letter.name if letter else None)
                if not w.empty:
                    reg.log(con, cid, u["username"], "WARNINGS CONFIRMED",
                            "; ".join(f"{a} ({b})" for a, b in zip(w["Check"], w["Lines"])))
                    con.commit()
                st.success(f"Request submitted as claim #{cid}. Follow it under "
                           f"'{'All' if officer else 'My'} requests and status'.")
            except ValueError as e:
                st.error(str(e))
    _status(con, u, officer, tab_status)


def _status(con, u, officer, tab):
    with tab:
        df = reg.claims(con) if officer else reg.claims(con, u["tin"])
        if df.empty:
            st.info("No requests yet.")
            return
        order = ["SUBMITTED", "PROCESSED", "APPROVED", "PARTLY PAID", "PAID", "RETURNED"]
        counts = " &nbsp; ".join(f"{ui.chip(s)} {int((df.status == s).sum())}" for s in order)
        st.markdown(counts, unsafe_allow_html=True)
        st.write("")
        ui.claims_grid(df, supplier=not officer, key="sub_grid")
        st.markdown("#### Track a file")
        cid = st.selectbox("Claim", df.id.tolist(), key="track_claim",
                           format_func=lambda i: (lambda r: f"Claim #{i} · {pd.Timestamp(r.interval_start):%d/%m} – "
                                                            f"{pd.Timestamp(r.interval_end):%d/%m/%Y} · "
                                                            f"{r.status.title()}")(df[df.id == i].iloc[0]))
        row = df[df.id == cid].iloc[0]
        from ui import tracking
        tracking.track(con, row, u["username"])
        blob, lname = reg.claim_letter(con, cid)
        if blob:
            st.download_button(f"Request letter ({lname})", blob, file_name=lname, key=f"letter_{cid}")
        _delete(con, u, row)


def _delete(con, u, row):
    """RRA officer: delete a file before analysis (Submitted / Returned). Administrator: at any stage."""
    can = u["role"] == "admin" or (u["role"] == "officer" and row.status in reg.DELETABLE_BY_OFFICER)
    if not can:
        return
    with st.expander(f"🗑 Delete claim #{row.id}"):
        if row.status not in reg.DELETABLE_BY_OFFICER:
            st.warning(f"This claim is **{row.status}** — deleting it also removes it from its round, payments and "
                       "appeals. A full copy is kept in Admin › Deleted records.")
        reason = st.text_input("Reason (required)", key=f"del_reason_{row.id}")
        sure = st.checkbox(f"I want to delete claim #{row.id} of {row['name']}", key=f"del_ok_{row.id}")
        if st.button("Delete the submission", disabled=not sure, key=f"del_{row.id}"):
            try:
                reg.delete_claim(con, int(row.id), u["username"], u["role"], reason)
                st.success(f"Claim #{row.id} deleted (archived copy kept).")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
