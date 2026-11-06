import io

import pandas as pd
import streamlit as st

from engine import register as reg
from engine.config import Settings
from engine.pipeline import process, summarise
from engine.report import to_excel
from engine.rules import apply_decisions
from ui import common as ui

SHOW = {"source_row": "Row", "status": "Status", "client": "Client", "vehicle": "Vehicle", "closed_at": "Closed at",
        "slip_raw": "EBM Slip No (as sent)", "slip_clean": "EBM Slip No", "invoice_clean": "EBM invoice",
        "matched_key": "EBM invoice", "qty": "Claimed L", "ebm_qty": "EBM L",
        "accepted_qty": "Accepted L", "pending_qty": "Pending L", "rejected_qty": "Rejected L",
        "accepted_subsidy": "Subsidy to pay", "reason": "Reason", "review_reason": "Why review",
        "cleaning_notes": "Cleaning applied", "match_notes": "Match notes", "decision": "Decision"}


def _table(df, cols):
    cols = [c for c in cols if c in df]
    t = df[cols].copy()
    if "closed_at" in t and not pd.api.types.is_string_dtype(t["closed_at"]):
        t["closed_at"] = pd.to_datetime(t["closed_at"]).dt.strftime("%d/%m/%Y %H:%M")
    if "matched_key" in t:
        t["matched_key"] = t["matched_key"].fillna("").astype(str).str.replace("|", "/", regex=False)
    st.dataframe(t.rename(columns=SHOW), hide_index=True, width="stretch",
                 column_config={"Subsidy to pay": ui.RWF})


def page():
    con, u = ui.db(), ui.user()
    ui.band("Processing · Claim analysis",
            "Upload the EBM file — cleaning, EBM matching and every rule run automatically; review doubtful lines "
            "and save as verified.")

    df = reg.claims(con)
    queue = df[df.status.isin(["SUBMITTED", "PROCESSED"]) & df.round_id.isna()]
    ui.cards([
        ("Waiting for analysis", f"{(df.status == 'SUBMITTED').sum()}", "submitted claims", "blue"),
        ("Verified, not yet in a round", f"{(queue.status == 'PROCESSED').sum()}",
         ui.money(queue.loc[queue.status == 'PROCESSED', 'to_reimburse'].sum(), "RWF"), "orange"),
        ("Lines pending review", f"{df.loc[df.status == 'PROCESSED', 'pending_l'].fillna(0).sum():,.2f} L",
         "in analysed claims", "navy"),
        ("Approved", f"{df.status.isin(['APPROVED', 'PARTLY PAID', 'PAID']).sum()}", "claims", "green"),
    ])
    st.write("")
    if ui.read_only():
        return _view_only(con, df)
    goto = st.session_state.pop("proc_goto", None)       # set by "Register claim and run analysis"
    if goto is not None:
        st.session_state["proc_mode"] = "Submitted claims"
        st.session_state["proc_claim"] = goto
    st.markdown("**Choose how to process:** a claim the supplier already submitted, or upload the request "
                "file and the EBM file yourself.")
    n_pend = int((df.pending_l.fillna(0) > 0.005).sum())
    pend_label = f"Pending lines ({n_pend} claim{'s' if n_pend != 1 else ''})"
    if st.session_state.get("proc_mode", "").startswith("Pending lines"):
        st.session_state["proc_mode"] = pend_label        # keep the choice when the count changes
    mode = st.radio("Mode", ["Submitted claims", pend_label, "Analyse files directly"], horizontal=True,
                    key="proc_mode", index=2 if queue.empty else 0, label_visibility="collapsed")
    if mode.startswith("Pending lines"):
        _pending_mode(con, u, df)
        _rules_admin(con)
        return
    if mode == "Analyse files directly":
        _direct(con, u)
        _rules_admin(con)
        return
    if queue.empty:
        st.info("No submitted claims are waiting. To test a request file and an EBM file now, choose "
                "**Analyse files directly** above.")
        _rules_admin(con)
        return
    if st.session_state.get("proc_claim") not in queue.id.tolist():
        st.session_state.pop("proc_claim", None)

    label = lambda i: (lambda r: f"#{i} · {r['name']} · {pd.Timestamp(r.interval_start):%d/%m} – "
                                 f"{pd.Timestamp(r.interval_end):%d/%m/%Y} · {r.status.title()}")(queue[queue.id == i].iloc[0])
    cid = st.selectbox("Claim", queue.id.tolist(), format_func=label, key="proc_claim")
    row = queue[queue.id == cid].iloc[0]
    st.markdown(f"{ui.chip(row.status)} &nbsp; **{row['name']}** · TIN {row.tin} · interval "
                f"{pd.Timestamp(row.interval_start):%d/%m/%Y} – {pd.Timestamp(row.interval_end):%d/%m/%Y} · "
                f"account {row.account or '—'} · file *{row.claim_filename}*", unsafe_allow_html=True)
    _request_panel(con, u, row)

    with st.container(border=True):
        st.markdown("**1 · EBM data source**")
        src = st.radio("Source", ["Upload EBM extract", "Direct EBM connection"], horizontal=True,
                       label_visibility="collapsed")
        ebm = None
        if src == "Direct EBM connection":
            st.info("Direct EBM connection needs RRA IT access to the EBM database — planned for the production "
                    "build. Use an EBM extract for now.")
        else:
            ebm = st.file_uploader("Upload the EBM file for this supplier and interval (Excel/CSV)", type=["xlsx", "xls", "csv"],
                                   key=f"ebm_{cid}")
        rura_blob, rura_name, rura_at = reg.get_setting(con, "rura_prices")
        st.caption(_reference_caption(con, rura_name, rura_at))
        submission = row.submission if isinstance(row.submission, str) else ""
        run = st.button("Run analysis", type="primary", disabled=ebm is None)

    settings = _settings(con)
    key = f"analysis_{cid}"
    if run:
        rura = None
        if rura_blob:
            rura = io.BytesIO(rura_blob)
            rura.name = rura_name
        meta = {"tin": row.tin, "name": row["name"], "period_start": row.interval_start,
                "period_end": row.interval_end, "account": row.account, "processor": u["name"]}
        with st.spinner("Cleaning, matching to EBM and applying the rules…"):
            lines, problems, _ = process(reg.claim_file(con, cid), ebm, meta, rura, None, settings,
                                         register_history=reg.history_keys(con, exclude_claim=cid))
        st.session_state[key] = (lines, problems)

    if key in st.session_state:
        _results(con, u, cid, row, submission, settings, *st.session_state[key])
    elif row.status == "PROCESSED":
        _stored(con, u, cid, row)
    _rules_admin(con)


def _settings(con):
    from engine import workflow as wf
    return Settings(official_subsidy_rates=wf.subsidy_rates(con), **st.session_state.get("rule_overrides", {}))


def _reference_caption(con, rura_name, rura_at):
    from engine import workflow as wf
    rates = " · ".join(f"{p.title()} {v:,.0f}" for p, v in wf.subsidy_rates(con).items())
    prices = (f"{rura_name} (uploaded {rura_at})" if rura_name else
              "built-in pump prices (ASSIMPER, Nov 2026): Diesel 2,927 · Petrol 2,938 RWF/L")
    return f"Reference used automatically — RURA prices: {prices}. Official subsidy: {rates} RWF/L (set by the administrator)."


def _autofill(con, claim_bytes, claim_name, ebm_up, clean):
    """Supplier name, TIN, interval and account read from the claim form and the EBM file."""
    import re
    from engine.cleaning import CLAIM_COLUMNS, CLAIM_REQUIRED, EBM_COLUMNS, EBM_REQUIRED, normalize_tin, read_table
    b = io.BytesIO(claim_bytes); b.name = claim_name
    raw, _ = read_table(b, CLAIM_COLUMNS, CLAIM_REQUIRED, "Claim")
    pre = raw.attrs.get("preamble", "")
    name = (re.search(r"Fuel supplier \(OMC\):\s*([^|]+)", pre) or [None, ""])[1].strip()
    tin = (re.search(r"TIN:?\s*(\d{9})", pre) or [None, ""])[1]
    source = {"name": "claim form" if name and not name.startswith("[") else "", "tin": "claim form" if tin else ""}
    if name.startswith("["):
        name = ""
    if not tin and "omc_tin" in clean and (clean["omc_tin"] != "").any():
        tin, source["tin"] = clean.loc[clean["omc_tin"] != "", "omc_tin"].mode().iloc[0], "claim form (OMC TIN column)"
    if not tin and ebm_up is not None:
        e = io.BytesIO(ebm_up.getvalue()); e.name = ebm_up.name
        eraw, _ = read_table(e, EBM_COLUMNS, EBM_REQUIRED, "EBM")
        if "seller_tin" in eraw and len(eraw):
            tins = eraw["seller_tin"].map(normalize_tin).dropna()
            if len(tins):
                tin, source["tin"] = tins.mode().iloc[0], "EBM file (seller TIN)"
    if tin and not name:
        row = con.execute("SELECT name FROM users WHERE tin=? AND role='supplier'", (tin,)).fetchone() or \
            con.execute("SELECT name FROM claims WHERE tin=? ORDER BY id DESC", (tin,)).fetchone()
        if row:
            name, source["name"] = row[0], "registered supplier"
    account = ""
    if tin:
        row = con.execute("SELECT account FROM claims WHERE tin=? AND account NOT IN ('', '—') ORDER BY id DESC",
                          (tin,)).fetchone()
        account = row[0] if row else ""
    return name, tin, account, source


def _direct(con, u):
    """Officer uploads the request file and the EBM file; everything else is filled automatically."""
    from ui.submission import _precheck
    st.caption("Upload the supplier's request file and the EBM file. Supplier, TIN, interval and account are filled "
               "automatically from the files (you can correct them); the claim is registered and analysed at once.")
    with st.container(border=True):
        c1, c2 = st.columns(2)
        claim_up = c1.file_uploader("1 · Request file from the supplier (Excel/CSV)", type=["xlsx", "xls", "csv"],
                                    key="direct_claim")
        ebm_up = c2.file_uploader("2 · EBM file (Excel/CSV)", type=["xlsx", "xls", "csv"], key="direct_ebm")
        f_start = f_end = None
        clean = None
        if claim_up is not None:
            clean, problems, (f_start, f_end) = _precheck(claim_up.getvalue(), claim_up.name)
            for p in problems:
                if p.startswith("Dates in the"):
                    st.info(p)
                elif p.startswith("Not the standard claim form") or "typed as text" in p:
                    st.warning(p)
                else:
                    st.error(p)
            if clean is not None:
                d = clean["closed_at"].dropna()
                st.caption(f"{len(clean):,} lines · {clean['qty'].fillna(0).sum():,.2f} L"
                           + (f" · transactions {d.min():%d/%m/%Y} – {d.max():%d/%m/%Y}" if not d.empty else ""))
                if f_start is None and not d.empty:
                    f_start, f_end = d.min().normalize(), d.max().normalize()
        a_name = a_tin = a_acc = ""
        src = {}
        if claim_up is not None and clean is not None:
            a_name, a_tin, a_acc, src = _autofill(con, claim_up.getvalue(), claim_up.name, ebm_up, clean)
        fkey = f"{claim_up.name if claim_up else ''}_{ebm_up.name if ebm_up else ''}"
        found = all([a_name, a_tin, f_start is not None])
        with st.expander("Claim details — filled automatically" + (" ✓" if found else " (please complete)"),
                         expanded=claim_up is not None and not found):
            n1, n2 = st.columns(2)
            name = n1.text_input("Supplier name", value=a_name, key=f"dn_{fkey}",
                                 help=f"from {src.get('name') or 'not found — type it'}")
            tin = n2.text_input("Supplier TIN", value=a_tin, key=f"dt_{fkey}",
                                help=f"from {src.get('tin') or 'not found — type it'}")
            d1, d2, d3 = st.columns(3)
            start = d1.date_input("Consumption from", value=f_start.date() if f_start is not None else None,
                                  format="DD/MM/YYYY", key=f"ds_{fkey}")
            end = d2.date_input("Consumption to", value=f_end.date() if f_end is not None else None,
                                format="DD/MM/YYYY", key=f"de_{fkey}")
            account = d3.text_input("Bank account", value=a_acc, key=f"da_{fkey}")
            r1, r2 = st.columns(2)
            d_req = r1.number_input("Amount of subsidies requested (RWF, from the letter)", min_value=0.0, value=None,
                                    step=1000.0, format="%.0f", key=f"dr_{fkey}",
                                    help="RRA pays the lower of this amount and the subsidy calculated. "
                                         "Blank = the calculated subsidy.")
            d_letter = r2.file_uploader("Request letter (optional)", type=["pdf", "png", "jpg", "jpeg", "docx"],
                                        key=f"dl_{fkey}")
            if src:
                st.caption("Sources: " + "; ".join(f"{k} from {v}" for k, v in src.items() if v)
                           + ("; interval from the file" if f_start is not None else ""))
        rura_blob, rura_name, rura_at = reg.get_setting(con, "rura_prices")
        st.caption(_reference_caption(con, rura_name, rura_at))
        ready = claim_up is not None and ebm_up is not None and name.strip() and tin.strip() and start and end
        go = st.button("Register claim and run analysis", type="primary", disabled=not ready)
        if not ready:
            st.caption("Upload both files" + ("; complete the claim details above" if claim_up is not None else "") + ".")
    if go:
        try:
            who = dict(u, tin=tin.strip())
            cid = reg.submit_claim(con, who, name.strip(), start, end, account.strip() or "—",
                                   claim_up.getvalue(), claim_up.name, "registered by officer for analysis",
                                   requested_rwf=d_req or None, letter=d_letter.getvalue() if d_letter else None,
                                   letter_name=d_letter.name if d_letter else None)
        except ValueError as e:
            st.error(str(e))
            return
        rura_blob, rura_name, _ = reg.get_setting(con, "rura_prices")
        rura = None
        if rura_blob:
            rura = io.BytesIO(rura_blob)
            rura.name = rura_name
        settings = _settings(con)
        meta = {"tin": tin.strip(), "name": name.strip(), "period_start": start, "period_end": end,
                "account": account, "processor": u["name"]}
        with st.spinner("Cleaning, matching to EBM and applying the rules…"):
            lines, problems, _ = process(reg.claim_file(con, cid), ebm_up, meta, rura, None, settings,
                                         register_history=reg.history_keys(con, exclude_claim=cid))
        st.session_state[f"analysis_{cid}"] = (lines, problems)
        st.session_state["proc_goto"] = cid
        st.rerun()


def _results(con, u, cid, row, submission, settings, lines, problems):
    for p in problems:
        (st.info if p.startswith(("Dates in the", "RURA/pump price")) else st.warning)(p)
    if lines is None:
        return
    s = summarise(lines)
    st.markdown("**2 · Results**")
    ui.cards([
        ("Accepted", f"{s['accepted_qty']:,.2f} L", ui.money(s["accepted_subsidy"], "RWF"), "green"),
        ("Pending review", f"{s['pending_qty']:,.2f} L", f"{s['review_lines']} lines", "blue"),
        ("Rejected", f"{s['rejected_qty']:,.2f} L", ui.money(s["rejected_subsidy"], "RWF"), "orange"),
        ("Claimed", f"{s['claimed_qty']:,.2f} L", ui.money(s["claimed_subsidy"], "RWF"), "navy"),
    ])
    req = con.execute("SELECT requested_rwf FROM claims WHERE id=?", (cid,)).fetchone()[0]
    _lower_box(req, s["accepted_subsidy"])
    from engine.indicators import by_vehicle, indicators, match_summary, price_check
    ind = indicators(lines)
    st.dataframe(ind, hide_index=True, width="stretch",
                 column_config={"Subsidy (RWF)": ui.RWF, "Litres": ui.LITRES,
                                "% of claimed litres": st.column_config.NumberColumn(format="percent")})
    c1, c2 = st.columns(2)
    with c1.expander("EBM matching"):
        st.dataframe(match_summary(lines).astype(str), hide_index=True, width="stretch")
    if "interval" in lines.attrs:
        with c2.expander("Interval check"):
            st.dataframe(lines.attrs["interval"].astype(str), hide_index=True, width="stretch")

    base = ["source_row", "status", "client", "vehicle", "closed_at", "slip_clean", "invoice_clean", "qty", "ebm_qty"]
    t = st.tabs(["Review decisions", "Rejected", "Accepted", "All lines", "By vehicle", "Price check", "Cleaning log"])
    with t[0]:
        rev = lines[lines.status == "REVIEW"]
        if rev.empty:
            st.success("No line needs human review.")
            decisions = {}
        else:
            ed = pd.DataFrame({"Row": rev.source_row, "Vehicle": rev.vehicle,
                               "Closed at": pd.to_datetime(rev.closed_at).dt.strftime("%d/%m/%Y %H:%M"),
                               "Pending L": rev.pending_qty, "Why review": rev.review_reason,
                               "Decision": "Pending", "Note": ""})
            out = st.data_editor(ed, hide_index=True, width="stretch", key=f"dec_{cid}",
                                 disabled=["Row", "Vehicle", "Closed at", "Pending L", "Why review"],
                                 column_config={"Decision": st.column_config.SelectboxColumn(
                                     options=["Pending", "Accept", "Reject"], required=True)})
            decisions = {r.Row: (r.Decision, r.Note) for r in out.itertuples()}
            st.caption("Lines left as Pending are not paid; they stay pending in the claim.")
    with t[1]:
        _table(lines[lines.rejected_qty > 0], base + ["rejected_qty", "reason"])
    with t[2]:
        _table(lines[lines.status.isin(["ACCEPTED", "PARTIAL"])], base + ["accepted_qty", "accepted_subsidy", "match_notes"])
    with t[3]:
        _table(lines, base + ["accepted_qty", "pending_qty", "rejected_qty", "reason", "review_reason"])
    with t[4]:
        st.dataframe(by_vehicle(lines), hide_index=True, width="stretch",
                     column_config={"Claimed RWF": ui.RWF, "Accepted RWF": ui.RWF})
    with t[5]:
        st.dataframe(price_check(lines), hide_index=True, width="stretch")
    with t[6]:
        _table(lines[(lines.cleaning_notes != "") | (lines.match_notes != "")],
               ["source_row", "vehicle", "slip_raw", "slip_clean", "invoice_clean", "cleaning_notes", "match_notes"])

    st.markdown("**3 · Save as verified**")
    c1, c2, c3 = st.columns(3)
    if c1.button("Save as verified", type="primary", width="stretch"):
        final = apply_decisions(lines, decisions, u["name"])
        meta = dict(lines.attrs.get("meta", {}), interval=lines.attrs.get("interval"), processor=u["name"],
                    title=f"Fuel subsidy — {row['name']} — {submission or 'claim #' + str(cid)}")
        xlsx = to_excel(final, meta, settings, problems)
        try:
            reg.save_processing(con, cid, final, xlsx, u["name"], submission)
            st.session_state.pop(f"analysis_{cid}", None)
            st.success(f"Claim #{cid} verified — it can now be included in a submission round (Approval).")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    c2.caption("Saving applies your review decisions, stores the report and marks the claim as verified by you. "
               "It then goes into a submission round for the taskforce approvals (Approval page).")


def _stored(con, u, cid, row):
    st.markdown("**Saved analysis**")
    lines = reg.lines_for(con, cid)
    calc = row.calculated_rwf if pd.notna(row.calculated_rwf) else row.to_reimburse
    _lower_box(row.requested_rwf, calc)
    ui.cards([
        ("To reimburse", ui.money(row.to_reimburse, "RWF"), f"{row.accepted_l:,.2f} L", "green"),
        ("Pending review", f"{row.pending_l:,.2f} L", ui.money(row.pending_rwf, "RWF"), "blue"),
        ("Rejected", f"{row.rejected_l:,.2f} L", ui.money(row.rejected_rwf, "RWF"), "orange"),
        ("Verified", row.processed_at or "—", f"by {row.processor}", "navy"),
    ])
    with st.expander("Lines"):
        _table(lines, ["source_row", "status", "vehicle", "closed_at", "slip_clean", "invoice_clean", "qty", "accepted_qty",
                       "pending_qty", "rejected_qty", "reason", "review_reason", "decision"])
    st.download_button("Download analysis report (Excel)", reg.report(con, cid), file_name=f"claim_{cid}_analysis.xlsx")
    st.info("Verified — waiting to be included in a submission round. Open **Approval** to create the round."
            + (f" It still has **{row.pending_l:,.2f} L pending** — decide them under **Pending lines** above."
               if (row.pending_l or 0) > 0.005 else ""))
    c2, c3 = st.columns([3, 1])
    reason = c2.text_input("Reason (to return the claim to the supplier)", key=f"ret_{cid}")
    if c3.button("Return to supplier", width="stretch"):
        try:
            reg.return_claim(con, cid, u["name"], reason)
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    st.caption("To re-run the analysis (e.g. with a new EBM extract), upload it above and click Run analysis.")


def _rules_admin(con):
    with st.expander("Rules, prices and official subsidy"):
        from engine.pipeline import DEFAULT_PRICE_FILE, load_rura_prices
        blob, name, at = reg.get_setting(con, "rura_prices")
        try:
            if blob:
                f = io.BytesIO(blob); f.name = name
                current, label = load_rura_prices(f), f"{name} (uploaded {at})"
            else:
                current, label = load_rura_prices(DEFAULT_PRICE_FILE), "built-in list (ASSIMPER, Nov 2026)"
            st.markdown(f"**Price list in use:** {label}")
            show = current.copy()
            show["effective_from"] = pd.to_datetime(show["effective_from"]).dt.strftime("%d/%m/%Y").fillna("any date")
            st.dataframe(show.rename(columns={"product_raw": "Fuel product", "product": "Checked as", "price": "Price",
                                              "effective_from": "Applies from", "unit": "Unit", "source": "Source",
                                              "source_url": "Source URL"}),
                         hide_index=True, width="stretch",
                         column_config={"Source URL": st.column_config.LinkColumn(),
                                        "Price": st.column_config.NumberColumn(format="%,.0f")})
        except Exception as e:
            st.error(f"Price list could not be read: {e}")
        st.caption("Rows without a date apply to any transaction date. When only a later-dated price exists, it is "
                   "used and the report says so. Upload either layout: product / effective_from / price, or "
                   "Fuel product / Retail pump price / Unit / Price date / Source / Source URL.")
        from engine import workflow as wf
        st.markdown("**Official subsidy (RWF/L):** " +
                    " · ".join(f"{p.title()} {v:,.0f}" for p, v in wf.subsidy_rates(con).items()))
        st.caption("The price list and the official subsidy rates are managed by the administrator (Admin page).")
        o = st.session_state.get("rule_overrides", {})
        c1, c2, c3, c4 = st.columns(4)
        new = {
            "max_litres_per_vehicle_day": c1.number_input("Review above L/vehicle/day", value=float(o.get("max_litres_per_vehicle_day", 400.0)), step=10.0),
            "min_refill_interval_minutes": c2.number_input("Review refuel within (min)", value=float(o.get("min_refill_interval_minutes", 60.0)), step=5.0),
            "max_time_gap_hours": c3.number_input("Review time gap above (h)", value=float(o.get("max_time_gap_hours", 24.0)), step=1.0),
            "qty_abs_tolerance_l": c4.number_input("Quantity tolerance (L)", value=float(o.get("qty_abs_tolerance_l", 0.05)), step=0.01, format="%.2f"),
        }
        exempt = st.text_input("EBM tax types treated as exempt", value=",".join(sorted(o.get("exempt_tax_types", {"A"}))))
        new["exempt_tax_types"] = {t.strip().upper() for t in exempt.split(",") if t.strip()}
        st.session_state["rule_overrides"] = new


def _lower_box(requested, calculated):
    """Subsidies requested vs subsidies calculated (potential): RRA pays whichever is lower."""
    amount, basis = reg.lower_of(requested, calculated)
    has_req = requested is not None and pd.notna(requested) and float(requested) > 0
    ui.cards([
        ("Subsidies requested", ui.money(requested, "RWF") if has_req else "not given", "supplier's letter", "navy"),
        ("Subsidies calculated", ui.money(calculated, "RWF"), "potential: accepted lines × official rate", "blue"),
        ("To reimburse", ui.money(amount, "RWF"), "the lower: " + basis, "green"),
    ])
    if has_req and float(requested) < float(calculated or 0):
        st.info(f"The supplier requested less than the calculated subsidy: **{ui.money(requested, 'RWF')}** is paid "
                f"({ui.money(float(calculated) - float(requested), 'RWF')} below the calculated amount).")


def _request_panel(con, u, row):
    """Request letter and amount requested of a submitted claim; the officer can complete them if missing."""
    blob, lname = reg.claim_letter(con, row.id)
    has_req = pd.notna(row.requested_rwf) and row.requested_rwf > 0
    c1, c2 = st.columns([2, 1])
    c1.markdown(f"**Amount requested:** {ui.money(row.requested_rwf, 'RWF') if has_req else '— not given'}"
                + (f" · **letter:** {lname}" if blob else " · **letter:** — not uploaded"))
    if blob:
        c2.download_button("Open the request letter", blob, file_name=lname, key=f"pl_{row.id}", width="stretch")
    if not has_req or not blob:
        with st.expander("Record the amount requested / letter (from the supplier's letter)"):
            a, b = st.columns(2)
            amt = a.number_input("Amount requested (RWF)", min_value=0.0, value=float(row.requested_rwf) if has_req else None,
                                 step=1000.0, format="%.0f", key=f"preq_{row.id}")
            let = b.file_uploader("Letter", type=["pdf", "png", "jpg", "jpeg", "docx"], key=f"plet_{row.id}")
            if st.button("Save", key=f"psave_{row.id}", disabled=not amt):
                reg.set_requested(con, int(row.id), u["name"], amt, let.getvalue() if let else None,
                                  let.name if let else None)
                st.success("Saved — used when the claim is verified.")
                st.rerun()


def _view_only(con, df):
    """Managers: every claim in processing, its amounts and saved analysis — no action."""
    ui.view_only_note()
    v = df[df.status.isin(["SUBMITTED", "PROCESSED"])]
    if v.empty:
        st.info("No claim is in processing.")
        return
    cid = st.selectbox("Claim", v.id.tolist(), key="ro_proc",
                       format_func=lambda i: (lambda r: f"#{i} · {r['name']} · {r.status.title()}")(v[v.id == i].iloc[0]))
    row = v[v.id == cid].iloc[0]
    blob, lname = reg.claim_letter(con, cid)
    if blob:
        st.download_button("Open the request letter", blob, file_name=lname, key=f"ro_l_{cid}")
    if row.status == "SUBMITTED":
        st.info(f"Waiting for analysis · amount requested "
                f"{ui.money(row.requested_rwf, 'RWF') if pd.notna(row.requested_rwf) else '—'}")
        return
    calc = row.calculated_rwf if pd.notna(row.calculated_rwf) else row.to_reimburse
    _lower_box(row.requested_rwf, calc)
    _table(reg.lines_for(con, cid), ["source_row", "status", "vehicle", "closed_at", "slip_clean", "qty", "accepted_qty",
                                     "pending_qty", "rejected_qty", "reason"])
    st.download_button("Download analysis report (Excel)", reg.report(con, cid), file_name=f"claim_{cid}_analysis.xlsx")


def _pending_mode(con, u, df):
    """Re-route pending lines to accepted or rejected, case by case, in any analysed claim."""
    st.caption("Lines left **pending** at analysis are not paid. Decide each one here when the evidence is available: "
               "**Accept** pays its subsidy, **Reject** moves it to the rejected lines with your reason. "
               "The amounts of the claim are recalculated; on an approved claim the extra amount goes to Finance "
               "as a separate payment (\"Pending review\").")
    v = df[(df.pending_l.fillna(0) > 0.005) & ~df.status.isin(["SUBMITTED", "RETURNED"])]
    if v.empty:
        st.success("No claim has pending lines.")
        return
    with ui.filter_bar() as fb:
        f1, f2 = st.columns(2)
        sup = f1.multiselect("Supplier", sorted(v["name"].unique()), key="pend_sup", placeholder="All suppliers")
        sts = f2.multiselect("Claim status", sorted(v.status.unique()), key="pend_st", placeholder="All statuses")
        fb.active(bool(sup) + bool(sts))
    v = v[v["name"].isin(sup)] if sup else v
    v = v[v.status.isin(sts)] if sts else v
    if v.empty:
        st.info("No claim matches the filters.")
        return
    cid = st.selectbox("Claim", v.id.tolist(), key="pend_claim",
                       format_func=lambda i: (lambda r: f"#{i} · {r['name']} · {r.status.title()} · "
                                                        f"{r.pending_l:,.2f} L pending ({ui.money(r.pending_rwf, 'RWF')})")(
                           v[v.id == i].iloc[0]))
    row = v[v.id == cid].iloc[0]
    pend = reg.pending_lines(con, cid)
    ui.cards([
        ("Pending lines", f"{len(pend)}", f"{pend.pending_qty.sum():,.2f} L", "blue"),
        ("Pending subsidy", ui.money(pend.pending_subsidy.sum(), "RWF"), "not paid until decided", "orange"),
        ("To reimburse now", ui.money(row.to_reimburse, "RWF"), row.status.title(), "green"),
    ])
    c1, c2 = st.columns([1, 2])
    bulk = c1.selectbox("Set all lines to", ["— choose case by case —", "Accept", "Reject", "Keep pending"],
                        key=f"pend_bulk_{cid}")
    bulk_note = c2.text_input("Note for all lines (optional; required to reject)", key=f"pend_bnote_{cid}")
    default = {"Accept": "Accept", "Reject": "Reject", "Keep pending": "Keep pending"}.get(bulk, "Keep pending")
    ed = pd.DataFrame({
        "Row": pend.source_row.astype(str), "Decision": default, "Note / reason": bulk_note,
        "Pending L": pend.pending_qty, "Pending RWF": pend.pending_subsidy, "Why pending": pend.review_reason,
        "Vehicle": pend.vehicle, "Closed at": pend.closed_at, "EBM Slip No": pend.slip_clean,
        "EBM invoice": pend.invoice_clean})
    out = st.data_editor(ed, hide_index=True, width="stretch", key=f"pend_ed_{cid}_{bulk}_{bulk_note}",
                         disabled=[c for c in ed.columns if c not in ("Decision", "Note / reason")],
                         column_config={"Decision": st.column_config.SelectboxColumn(
                             options=["Keep pending", "Accept", "Reject"], required=True, width="small"),
                             "Note / reason": st.column_config.TextColumn(width="medium"),
                             "Pending RWF": ui.RWF, "Pending L": ui.LITRES,
                             "Why pending": st.column_config.TextColumn(width="large")})
    acc, rej = out[out.Decision == "Accept"], out[out.Decision == "Reject"]
    st.caption(f"Accept {len(acc)} line(s): +{acc['Pending L'].sum():,.2f} L, +{acc['Pending RWF'].sum():,.0f} RWF · "
               f"Reject {len(rej)} line(s): {rej['Pending L'].sum():,.2f} L · "
               f"keep pending {int((out.Decision == 'Keep pending').sum())}")
    if st.button("Save decisions", type="primary", key=f"pend_save_{cid}", disabled=acc.empty and rej.empty):
        try:
            res = reg.resolve_pending(con, int(cid), u["name"],
                                      dict(zip(out["Row"], zip(out["Decision"], out["Note / reason"]))))
            msg = (f"Saved: {res['accepted_l']:,.2f} L accepted, {res['rejected_l']:,.2f} L rejected. "
                   f"To reimburse: {res['to_reimburse']:,.0f} RWF.")
            if res["extra_payable"]:
                msg += f" {res['extra_payable']:,.0f} RWF sent to Finance for payment."
            st.success(msg)
            st.rerun()
        except ValueError as e:
            st.error(str(e))
