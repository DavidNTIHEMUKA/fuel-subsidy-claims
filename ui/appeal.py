import io
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from engine import register as reg
from engine.forms import appeal_form, read_appeal_form
from ui import common as ui

APPEALABLE = ["PROCESSED", "APPROVED", "PARTLY PAID", "PAID"]
VAT_CHOICES = ["Declared in the VAT annex", "Not in the VAT annex", "Not checked"]


def page():
    con, u = ui.db(), ui.user()
    officer = ui.is_officer()
    ui.band("Appeal", "Submission → System verification (EBM) → RRA Staff verification → approval → payment.")
    ui.steps(STEPS, -1)
    names, fns = [], []
    if u["role"] in ("supplier", "officer", "admin") and not u.get("function"):
        names.append("File an appeal"); fns.append(lambda: _file(con, u, officer))
    if ui.has("officer"):
        names.append("Analyse and verify"); fns.append(lambda: _decide(con, u))
    if ui.has("approver"):
        n = int(con.execute("SELECT COUNT(*) FROM appeals WHERE status='VERIFIED'").fetchone()[0])
        names.append(f"Approve ({n})"); fns.append(lambda: _approve(con, u))
    names.append("All appeals" if officer else "My appeals")
    fns.append(lambda: _list(con, reg.appeals(con) if officer else reg.appeals(con, u["tin"]), officer=officer))
    for tab, fn in zip(st.tabs(names), fns):
        with tab:
            fn()
    ui.footer()


STEPS = ["Submission", "System verification", "RRA Staff verification", "Approved", "Paid"]


def _step_of(con, a) -> int:
    """Index of the last completed step of an appeal."""
    if a["status"] in ("UPHELD", "PARTLY UPHELD", "DISMISSED"):
        paid = con.execute("SELECT status FROM payables WHERE appeal_id=?", (int(a["id"]),)).fetchone()
        return 4 if (paid and paid[0] == "PAID") or a["status"] == "DISMISSED" else 3
    if a["status"] == "VERIFIED":
        return 2
    return 1 if a.get("analysed") else 0


def _step_label(con, a):
    i = _step_of(con, a)
    if a["status"] == "DISMISSED":
        return "Closed — not upheld"
    return STEPS[i] + ("" if i == 4 else f" → next: {STEPS[i + 1]}")


# ---------------------------------------------------------------------------
# Filters shared by the tabs: TIN and submission date
# ---------------------------------------------------------------------------
def _filters(df, officer, key, date_col="submitted_at", date_label="Submission date"):
    fb = ui.filter_bar()
    fb.__enter__()
    c1, c2, c3 = st.columns([2, 1, 1])
    if officer:
        opts = sorted({f"{t} · {n}" for t, n in zip(df["tin"], df["name"])})
        tins = c1.multiselect("TIN", opts, key=f"{key}_tin", placeholder="All TINs")
        tins = [t.split(" · ")[0] for t in tins]
    else:
        c1.markdown(f"**TIN** {df['tin'].iloc[0] if not df.empty else ''}")
        tins = []
    dates = pd.to_datetime(df[date_col], errors="coerce")
    lo = dates.min().date() if dates.notna().any() else date.today() - timedelta(days=90)
    hi = dates.max().date() if dates.notna().any() else date.today()
    d_from = c2.date_input(f"{date_label} from", value=lo, format="DD/MM/YYYY", key=f"{key}_from")
    d_to = c3.date_input(f"{date_label} to", value=hi, format="DD/MM/YYYY", key=f"{key}_to")
    m = pd.Series(True, index=df.index)
    if tins:
        m &= df["tin"].isin(tins)
    if d_from:
        m &= dates >= pd.Timestamp(d_from)
    if d_to:
        m &= dates < pd.Timestamp(d_to) + pd.Timedelta(days=1)
    narrowed = (d_from and d_from > lo) or (d_to and d_to < hi)
    fb.active(bool(tins) + bool(narrowed), f"{int(m.sum())} of {len(df)} shown")
    fb.__exit__(None, None, None)
    return df[m]


# ---------------------------------------------------------------------------
# File an appeal (supplier or officer on the supplier's behalf)
# ---------------------------------------------------------------------------
def _file(con, u, officer):
    claims = reg.claims(con, None if officer else u["tin"], status=APPEALABLE)
    claims = claims[claims.rejected_l.fillna(0) > 0]
    if claims.empty:
        st.info("There are no claims with rejected lines to appeal.")
        return
    claims = _filters(claims, officer, "file")
    if claims.empty:
        st.info("No claim with rejected lines matches these filters.")
        return

    frames = []
    open_rows = {}
    for r in reg.appeals(con, status="OPEN").itertuples():
        open_rows.setdefault(r.claim_id, set()).update(r.rows.split(","))
    for c in claims.itertuples():
        L = reg.lines_for(con, c.id)
        L = L[L.rejected_qty > 0].copy()
        if L.empty:
            continue
        L["claim_id"], L["submitted"], L["tin"], L["supplier"] = c.id, str(c.submitted_at)[:10], c.tin, c.name
        L["open_appeal"] = L.source_row.astype(str).isin(open_rows.get(c.id, set()))
        frames.append(L)
    if not frames:
        st.info("No rejected lines in these claims.")
        return
    lines = pd.concat(frames, ignore_index=True)
    free = lines[~lines.open_appeal]

    a, b = st.columns([1, 3])
    tick_all = a.checkbox("Tick all lines shown", key="appeal_tick_all")
    b.caption(f"{len(free):,} rejected line(s) can be appealed in {free.claim_id.nunique()} claim(s) · "
              f"{free.rejected_qty.sum():,.2f} L · {free.rejected_subsidy.sum():,.0f} RWF"
              + (f" · {int(lines.open_appeal.sum())} line(s) already under appeal (not shown)" if lines.open_appeal.any() else ""))
    ed = pd.DataFrame({
        "Appeal ✓": tick_all, "Claim #": free.claim_id, "Submitted": free.submitted, "TIN": free.tin,
        "Supplier": free.supplier, "Row": free.source_row, "Vehicle": free.vehicle, "Closed at": free.closed_at,
        "EBM Slip No": free.slip_clean, "Rejected L": free.rejected_qty, "Rejected RWF": free.rejected_subsidy,
        "Reason": free.reason})
    if not officer:
        ed = ed.drop(columns=["TIN", "Supplier"])
    out = st.data_editor(ed, hide_index=True, width="stretch", key=f"ap_editor_{tick_all}_{len(ed)}",
                         disabled=[c for c in ed.columns if c != "Appeal ✓"],
                         column_config={"Rejected RWF": ui.RWF, "Rejected L": ui.LITRES,
                                        "Appeal ✓": st.column_config.CheckboxColumn()})
    chosen = out[out["Appeal ✓"]]
    picked = free.loc[chosen.index]
    st.markdown(f"**Selected:** {len(chosen)} line(s) in {chosen['Claim #'].nunique()} claim(s) · "
                f"{chosen['Rejected L'].sum():,.2f} L · {chosen['Rejected RWF'].sum():,.0f} RWF")

    with st.container(border=True):
        st.markdown("**Appeal form (recommended)** — download it with the selected lines, fill the corrected EBM "
                    "Slip No / quantity and an explanation per line, then upload it here.")
        c1, c2 = st.columns(2)
        c1.download_button("Download appeal form for the selected lines",
                           appeal_form(picked.rename(columns={"claim_id": "claim_id"})) if len(picked) else b"",
                           file_name="appeal_form.xlsx", disabled=picked.empty, width="stretch")
        form_up = c2.file_uploader("Upload the completed appeal form", type=["xlsx"], key="appeal_form_up")
        corrections = None
        if form_up is not None:
            try:
                corrections = read_appeal_form(form_up.getvalue())
                bad = corrections[corrections.slip_problem]
                st.caption(f"Form read: {len(corrections)} line(s), {int((corrections.slip != '').sum())} corrected "
                           f"slip number(s), {int(corrections.qty.notna().sum())} corrected quantity(ies).")
                if len(bad):
                    st.warning(f"{len(bad)} corrected EBM Slip No could not be read (rows "
                               f"{', '.join(bad.row)}); write them as SDC ID / counter, e.g. SDC010057290/10540.")
            except ValueError as e:
                st.error(str(e))
    with st.form("appeal"):
        reason = st.text_area("General explanation", height=90,
                              placeholder="e.g. The receipts were issued from our second SDC device; corrected slip "
                                          "numbers are in the appeal form, receipt copies attached.")
        ev = st.file_uploader("Evidence (EBM receipts, logbook — PDF, images or Excel)",
                              type=["pdf", "png", "jpg", "jpeg", "xlsx", "csv", "zip"])
        sent = st.form_submit_button("Submit appeal", type="primary")
    if sent:
        if chosen.empty and corrections is not None and not corrections.empty:
            rows_by_claim = corrections.groupby("claim_id")["row"].apply(list).to_dict()   # lines from the form
        else:
            rows_by_claim = chosen.groupby("Claim #")["Row"].apply(lambda s: [str(x) for x in s]).to_dict()
        if not rows_by_claim:
            st.error("Tick at least one line, or upload a completed appeal form.")
            return
        done, errs = [], []
        for cid, rows in rows_by_claim.items():
            corr = None if corrections is None else corrections[corrections.claim_id == int(cid)]
            try:
                aid = reg.file_appeal(con, u, int(cid), rows, reason, ev.getvalue() if ev else None,
                                      ev.name if ev else None, corr)
                done.append(f"#{aid} (claim #{cid}, {len(rows)} line(s))")
            except ValueError as e:
                errs.append(str(e))
        for e in errs:
            st.error(e)
        if done:
            st.success("Appeal(s) submitted: " + ", ".join(done))


# ---------------------------------------------------------------------------
# Officer: re-match with EBM, then decide
# ---------------------------------------------------------------------------
def _decide(con, u):
    ap = reg.appeals(con, status="OPEN")
    if ap.empty:
        st.success("No open appeals.")
        return
    mine = ap[ap.assigned_to == u["username"]]
    who = st.radio("Show", ["Assigned to me", "All open appeals", "Not assigned yet"], horizontal=True,
                   index=0 if len(mine) else 1, key="dec_who",
                   format_func=lambda x: f"{x} ({len(mine) if x == 'Assigned to me' else len(ap) if x.startswith('All') else int(ap.assigned_to.isna().sum() + (ap.assigned_to == '').sum())})")
    ap = mine if who == "Assigned to me" else (ap[ap.assigned_to.isna() | (ap.assigned_to == "")] if who.startswith("Not") else ap)
    ap = _filters(ap, True, "dec", date_col="submitted_at", date_label="Appeal date")
    if ap.empty:
        st.info("No open appeal matches these filters.")
        return
    st.caption(f"{len(ap)} open appeal(s) · {sum(len(r.split(',')) for r in ap.rows)} line(s)")
    aid = st.selectbox("Open appeal", ap.id.tolist(), key="dec_appeal",
                       format_func=lambda i: (lambda r: f"Appeal #{i} · {r['name']} (TIN {r.tin}) · claim #{r.claim_id} · "
                                                        f"{len(r.rows.split(','))} line(s) · filed {r.submitted_at}")(ap[ap.id == i].iloc[0]))
    a = ap[ap.id == aid].iloc[0]
    _assign(con, u, a)
    claim = reg.claims(con).set_index("id").loc[int(a.claim_id)]
    claim = dict(claim, id=int(a.claim_id))
    st.markdown(f"**Supplier's explanation:** {a.reason}")
    blob, name = reg.evidence(con, aid)
    corr = reg.appeal_corrections(con, aid)
    c1, c2 = st.columns(2)
    if blob:
        c1.download_button(f"Download evidence ({name})", blob, file_name=name)
    if not corr.empty:
        with c2.expander(f"Corrections from the appeal form ({len(corr)})"):
            st.dataframe(corr.rename(columns={"row": "Row", "slip": "Corrected EBM Slip No", "qty": "Corrected L",
                                              "explanation": "Explanation"}), hide_index=True, width="stretch")

    # ---- 1. Re-analysis against EBM ----
    with st.container(border=True):
        st.markdown("**1 · Re-match the appealed lines with EBM** — same cleaning and rules as a submission, with the "
                    "supplier's corrections applied.")
        ebm = st.file_uploader("EBM file covering the claim's interval (Excel/CSV)", type=["xlsx", "xls", "csv"],
                               key=f"ap_ebm_{aid}")
        if st.button("Run analysis on the appealed lines", type="primary", disabled=ebm is None, key=f"ap_run_{aid}"):
            from engine.appeal_analysis import reanalyse
            from engine.config import Settings
            from engine.pipeline import DEFAULT_PRICE_FILE, load_rura_prices
            pb, pn, _ = reg.get_setting(con, "rura_prices")
            if pb:
                pf = io.BytesIO(pb); pf.name = pn
                prices = load_rura_prices(pf)
            else:
                prices = load_rura_prices(DEFAULT_PRICE_FILE)
            settings = Settings(**st.session_state.get("rule_overrides", {}))
            with st.spinner("Matching appealed lines with EBM…"):
                res, notes = reanalyse(claim, reg.lines_for(con, int(a.claim_id)), a.rows.split(","), corr, ebm,
                                       reg.history_keys(con, exclude_claim=int(a.claim_id)), prices, settings)
            for n in notes:
                st.info(n)
            if not res.empty:
                reg.save_appeal_analysis(con, aid, res, u["name"])
                st.rerun()
    res = reg.appeal_analysis(con, aid)

    # ---- 2. VAT declaration annex ----
    with st.container(border=True):
        st.markdown("**2 · Check the VAT declaration annex (e-Tax)** — is each EBM sale behind an appealed line "
                    "declared in the sales annex the supplier attached to its VAT declaration in e-Tax? The annex has "
                    "the same format as the EBM file (TIN, ClientsTIN, SdcId, SdcReceiptTypeCounter, SdcDateTime, "
                    "amounts…): the EBM file is what the machines recorded, the annex is what was declared.")
        st.caption("Automatic: upload the annex below. Manual: set each line's VAT annex status in the table of "
                   "step 3 after checking the declaration yourself.")
        if res is None:
            st.caption("For the automatic check, run step 1 first: the annex is checked against the EBM sales found there.")
        else:
            annex = st.file_uploader("VAT declaration annex from e-Tax — sales, same format as the EBM file (Excel/CSV)", type=["xlsx", "xls", "csv"],
                                     key=f"ap_vat_{aid}")
            if st.button("Check the annex", type="primary", disabled=annex is None, key=f"ap_vat_run_{aid}"):
                from engine.vat_annex import check, read_annex
                ann, probs = read_annex(annex)
                for p_ in probs:
                    st.info(p_)
                if ann.empty:
                    st.error("The annex could not be read: no date column found.")
                else:
                    reg.save_appeal_vat_check(con, aid, check(res, ann, a.tin), u["name"], annex.name)
                    st.rerun()
            if "vat_status" in res:
                v = res.vat_status.value_counts()
                st.markdown(" · ".join(f"**{k}**: {n}" for k, n in v.items()))

    # ---- 3. Decide ----
    lines = reg.lines_for(con, int(a.claim_id))
    sel = lines[lines.source_row.astype(str).isin(a.rows.split(","))].copy()
    sel["source_row"] = sel.source_row.astype(str)
    if res is not None:
        res = res.set_index("row")
        sel["Analysis"] = sel.source_row.map(res["new_status"])
        sel["Slip used"] = sel.source_row.map(res["slip_used"])
        sel["Corrected"] = sel.source_row.map(res["corrected"])
        sel["EBM L"] = sel.source_row.map(res["ebm_qty"])
        sel["Can award L"] = sel.source_row.map(res["award_l"]).fillna(0.0)
        if "vat_status" in res:
            sel["VAT annex"] = sel.source_row.map(res["vat_status"]).fillna("")
            sel["VAT period"] = sel.source_row.map(res["vat_period"]).fillna("")
        sel["Analysis reason"] = sel.source_row.map(
            lambda r: "; ".join(x for x in [res.at[r, "reason"], res.at[r, "review_reason"]] if x) or "all rules passed")
        default = sel["Can award L"] > 0
        ok, n = int(default.sum()), len(sel)
        vat_cards = []
        if "VAT annex" in sel:
            declared = sel["VAT annex"] == "Declared in the VAT annex"
            default = default & declared            # upheld by default only when in EBM AND declared for VAT
            vat_cards = [("Declared in the VAT annex", f"{int(declared.sum())} of {n}",
                          f"{int((default).sum())} supported by both checks", "blue")]
        ui.cards([
            ("Supported by EBM", f"{ok} of {n}", f"{sel['Can award L'].sum():,.2f} L can be accepted", "green"),
            *vat_cards,
            ("Not supported", f"{n - ok}", "see the analysis reason", "orange"),
            ("Rejected litres appealed", f"{sel.rejected_qty.sum():,.2f} L", ui.money(sel.rejected_subsidy.sum(), "RWF"), "navy"),
        ])
    else:
        st.info("No analysis yet — upload the EBM file and run it, or decide from the evidence alone.")
        sel["Can award L"] = sel.rejected_qty
        default = pd.Series(False, index=sel.index)

    if "VAT annex" not in sel:
        sel["VAT annex"] = "Not checked"
    sel["VAT annex"] = sel["VAT annex"].where(sel["VAT annex"].isin(VAT_CHOICES), "Not checked")
    st.markdown("**3 · Verify** — propose the litres to accept per line; the approver gives the final approval. "
                "*As the analysis suggests* ticks the lines found in EBM" + (" and declared in the VAT annex."
                                                                             if "VAT annex" in sel else "."))
    tick = st.radio("Tick", ["As the analysis suggests", "Tick all", "Untick all"], horizontal=True,
                    key=f"tick_{aid}", label_visibility="collapsed")
    initial = default if tick == "As the analysis suggests" else pd.Series(tick == "Tick all", index=sel.index)
    cols = {"Uphold ✓": initial.values, "Row": sel.source_row.values, "Vehicle": sel.vehicle.values,
            "Closed at": sel.closed_at.values, "EBM Slip No": sel.slip_clean.values,
            "Rejected L": sel.rejected_qty.values, "Original reason": sel.reason.values}
    for c in ["Analysis", "VAT annex", "VAT period", "Slip used", "Corrected", "EBM L", "Analysis reason"]:
        if c in sel:
            cols[c] = sel[c].values
    cols["Award L"] = sel["Can award L"].values
    ed = pd.DataFrame(cols)
    out = st.data_editor(ed, hide_index=True, width="stretch", key=f"dec_ed_{aid}_{tick}_{res is not None}",
                         disabled=[c for c in ed.columns if c not in ("Uphold ✓", "Award L", "VAT annex")],
                         column_config={"VAT annex": st.column_config.SelectboxColumn(
                                            options=VAT_CHOICES, required=True,
                                            help="Filled by the automatic check (step 2) or set by hand after "
                                                 "checking the VAT declaration"),"Rejected L": ui.LITRES, "EBM L": ui.LITRES,
                                        "Award L": st.column_config.NumberColumn(format="%,.2f", min_value=0.0,
                                                                                help="Litres to accept (max = rejected L)")})
    up = out[out["Uphold ✓"]]
    rate = (sel.rejected_subsidy / sel.rejected_qty.where(sel.rejected_qty > 0)).fillna(0).values
    rwf = float((out["Award L"].clip(upper=out["Rejected L"]) * rate)[out["Uphold ✓"]].sum())
    st.caption(f"Upholding {len(up)} of {len(out)} line(s): {up['Award L'].clip(upper=up['Rejected L']).sum():,.2f} L · "
               f"{rwf:,.0f} RWF added to the claim's amount to reimburse")
    if res is not None and (up["Award L"] > up.get("EBM L", up["Award L"]) + 0.01).any():
        st.warning("Some awards are above the EBM quantity — check before recording.")
    if "VAT annex" in up and (up["VAT annex"] != "Declared in the VAT annex").any():
        st.warning(f"{int((up['VAT annex'] != 'Declared in the VAT annex').sum())} upheld line(s) are not found in the "
                   "VAT annex — explain why in the note.")
    note = st.text_area("Verification note (sent to the approver and the supplier)", height=80, key=f"note_{aid}")
    if st.button("Record verification", type="primary", key=f"rec_{aid}"):
        awards = dict(zip(up["Row"].astype(str), up["Award L"].astype(float)))
        new_keys = {}
        if res is not None:
            for r in up["Row"].astype(str):
                k = res.at[r, "matched_key"] if r in res.index else ""
                if k and res.at[r, "corrected"]:
                    new_keys[r] = k
        awards_all = {str(r): (float(a) if str(r) in awards else 0.0) for r, a in zip(out["Row"], out["Award L"])}
        vat = dict(zip(out["Row"].astype(str), out["VAT annex"]))
        counts = pd.Series(list(vat.values())).value_counts()
        note = (note + " " if note else "") + "[VAT annex: " + ", ".join(f"{k.lower()}: {n}" for k, n in counts.items()) + "]"
        if res is not None:
            final = res.reset_index().copy()
            auto = final.get("vat_status", pd.Series("", index=final.index)).fillna("")
            final["vat_status"] = final["row"].astype(str).map(vat).fillna(auto)
            final["vat_match"] = [m if a_ == f else "set by hand" for a_, f, m in
                                  zip(auto, final["vat_status"], final.get("vat_match", pd.Series("", index=final.index)).fillna(""))]
            reg.save_appeal_vat_check(con, aid, final, u["name"], "verification")
        try:
            reg.recommend_appeal(con, aid, u["name"], awards_all, note, new_keys)
            st.success(f"Appeal #{aid} verified — it now waits for the approver.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))


def _approve(con, u):
    ap = reg.appeals(con, status="VERIFIED")
    if ap.empty:
        st.success("No appeal waiting for approval.")
        return
    ap = _filters(ap, True, "appr", date_col="submitted_at", date_label="Appeal date")
    if ap.empty:
        st.info("No verified appeal matches these filters.")
        return
    aid = st.selectbox("Verified appeal", ap.id.tolist(), key="appr_sel",
                       format_func=lambda i: (lambda r: f"Appeal #{i} · {r['name']} (TIN {r.tin}) · claim #{r.claim_id}")(
                           ap[ap.id == i].iloc[0]))
    a = ap[ap.id == aid].iloc[0]
    ui.steps(STEPS, 2, 3)
    rec = reg.appeal_recommendation(con, aid)
    lines = reg.lines_for(con, int(a.claim_id))
    sel = lines[lines.source_row.astype(str).isin(a.rows.split(","))].copy()
    sel["Proposed L"] = sel.source_row.astype(str).map(lambda r: rec["awards"].get(r, 0.0))
    rate = (sel.rejected_subsidy / sel.rejected_qty.where(sel.rejected_qty > 0)).fillna(0)
    sel["Proposed RWF"] = (sel["Proposed L"].clip(upper=sel.rejected_qty) * rate).round(0)
    res = reg.appeal_analysis(con, aid)
    if res is not None:
        sel["EBM re-match"] = sel.source_row.astype(str).map(res.set_index("row")["new_status"])
    st.markdown(f"**Supplier:** {a.reason}  \n**Verified by** {rec['by']} on {rec['at']}: {rec['note']}")
    cols = ["source_row", "vehicle", "closed_at", "slip_clean", "rejected_qty", "reason"] + \
        (["EBM re-match"] if "EBM re-match" in sel else []) + ["Proposed L", "Proposed RWF"]
    st.dataframe(sel[cols].rename(columns={"source_row": "Row", "vehicle": "Vehicle", "closed_at": "Closed at",
                                           "slip_clean": "EBM Slip No", "rejected_qty": "Rejected L",
                                           "reason": "Original reason"}),
                 hide_index=True, width="stretch", column_config={"Proposed RWF": ui.RWF})
    ui.cards([("Proposed to accept", f"{sel['Proposed L'].sum():,.2f} L", ui.money(sel["Proposed RWF"].sum(), "RWF"),
               "green"),
              ("Lines", f"{int((sel['Proposed L'] > 0).sum())} of {len(sel)}", "with an award", "navy")])
    note = st.text_input("Comment (required if not approved)", key=f"appr_note_{aid}")
    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("Approve", type="primary", key=f"appr_ok_{aid}"):
        status, l, rwf = reg.approve_appeal(con, aid, u["name"], True, note)
        st.success(f"Appeal #{aid} approved ({status.lower()}): {l:,.2f} L, {rwf:,.0f} RWF — sent to Payment.")
        st.rerun()
    if c2.button("Do not approve", key=f"appr_no_{aid}"):
        if not note.strip():
            st.error("Write the reason in the comment.")
        else:
            reg.approve_appeal(con, aid, u["name"], False, note)
            st.warning(f"Appeal #{aid} not approved.")
            st.rerun()


# ---------------------------------------------------------------------------
def _list(con, ap, officer):
    if ap.empty:
        st.info("No appeals yet.")
        return
    ap = _filters(ap, officer, "list" if officer else "mylist", date_col="submitted_at", date_label="Appeal date")
    counts = " &nbsp; ".join(f"{ui.chip(s)} {int((ap.status == s).sum())}"
                             for s in ["OPEN", "UPHELD", "PARTLY UPHELD", "DISMISSED"])
    st.markdown(counts, unsafe_allow_html=True)
    t = ap.copy()
    t["analysed"] = t["analysed"].map({1: "yes", 0: ""})
    t["step"] = [_step_label(con, r) for _, r in ap.iterrows()]
    cols = {"id": "Appeal #", "claim_id": "Claim #", "tin": "TIN", "name": "Supplier", "submitted_at": "Filed",
            "rows": "Rows", "reason": "Explanation", "step": "Step", "status": "Status", "analysed": "EBM re-match",
            "decided_at": "Decided", "decision_note": "Decision note", "award_l": "Litres accepted",
            "award_rwf": "RWF added"}
    if not officer:
        cols.pop("name"), cols.pop("tin")
    st.dataframe(t[list(cols)].rename(columns=cols), hide_index=True, width="stretch",
                 column_config={"RWF added": ui.RWF, "Litres accepted": ui.LITRES})
    if not ap.empty:
        aid = st.selectbox("Follow an appeal", ap.id.tolist(), key=f"follow_{officer}",
                           format_func=lambda i: f"Appeal #{i} — claim #{ap.loc[ap.id == i, 'claim_id'].iloc[0]}")
        a = ap[ap.id == aid].iloc[0]
        i = _step_of(con, a)
        ui.steps(STEPS, i, None if i == 4 else i + 1)
        if a.status in ("UPHELD", "PARTLY UPHELD", "DISMISSED"):
            st.caption(f"{a.status.title()}: {a.decision_note or ''} · {a.award_l or 0:,.2f} L · "
                       f"{a.award_rwf or 0:,.0f} RWF")
    if officer and not ap.empty:
        st.download_button("Download appeals (CSV)", t[list(cols)].rename(columns=cols).to_csv(index=False).encode(),
                           file_name="appeals.csv")


def _assign(con, u, a):
    """Who works on this appeal case: RRA officers and the functions that analyse appeals (e.g. Data Scientist)."""
    fns = reg.functions(con)
    analysts = [k for k, f in fns.items() if f["acts_as"] == "officer" and "appeal" in f["heads"]]
    people = pd.read_sql_query("SELECT username, name, role FROM users WHERE active=1 AND role IN ({}) ORDER BY name"
                               .format(",".join("?" * (len(analysts) + 2))), con, params=["officer", "admin"] + analysts)
    current = a.assigned_to if isinstance(a.assigned_to, str) and a.assigned_to else ""
    label = {r.username: f"{r.name} · {reg.role_label(con, r.role)}" for r in people.itertuples()}
    c1, c2 = st.columns([3, 1])
    c1.markdown(f"**Assigned to:** {label.get(current, current) if current else '— nobody yet'}"
                + (f" (since {a.assigned_at})" if current and isinstance(a.assigned_at, str) else ""))
    if u.get("function"):
        return                               # a data scientist works on the cases given to him or her
    with c2.popover("Assign", use_container_width=True):
        opts = [""] + people.username.tolist()
        pick = st.selectbox("Give this appeal to", opts, index=opts.index(current) if current in opts else 0,
                            format_func=lambda x: label.get(x, "— nobody") if x else "— nobody", key=f"asg_{a.id}")
        if st.button("Save", type="primary", key=f"asg_s_{a.id}"):
            reg.assign_appeal(con, int(a.id), pick, u["username"])
            st.rerun()
