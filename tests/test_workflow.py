"""Roles, passwords, signatory accounts, submission rounds with e-signatures, payables, appeal steps."""
import io
from pathlib import Path

import pandas as pd
import pytest

from engine import register as reg
from engine import workflow as wf
from engine.pipeline import process
from engine.rules import apply_decisions

DATA = Path(__file__).resolve().parent.parent / "sample_data"


def _f(n):
    b = io.BytesIO((DATA / n).read_bytes()); b.name = n
    return b


def _verified_claim(con, user):
    c = _f("claim_sample.xlsx")
    cid = reg.submit_claim(con, user, "SAMPLE OMC", "2026-06-01", "2026-06-30", "BK", c.getvalue(), c.name)
    lines, _, x = process(reg.claim_file(con, cid), _f("ebm_extract_sample.csv"),
                          {"tin": "100007664", "period_start": "2026-06-01", "period_end": "2026-06-30"},
                          _f("rura_prices.csv"))
    reg.save_processing(con, cid, apply_decisions(lines, {}, "o"), x, "officer", "")
    return cid


def test_admin_passwords_and_signatory_accounts(tmp_path):
    con = reg.connect(tmp_path / "c.db")
    assert reg.login(con, "admin", "admin2026")["role"] == "admin"
    made = wf.seed_signatories(con)
    assert {m["username"] for m in made} >= {"beatha.mukangabo", "eric.mutabazi", "david.ntihemuka", "evariste.rugigana"}
    u = reg.login(con, "beatha.mukangabo", "Change@2026")
    assert u["must_change"] and u["role"] == "taskforce"
    with pytest.raises(ValueError):
        reg.change_password(con, "beatha.mukangabo", "Change@2026", "short")
    reg.change_password(con, "beatha.mukangabo", "Change@2026", "Kigali2026x")
    assert not reg.login(con, "beatha.mukangabo", "Kigali2026x")["must_change"]
    assert reg.login(con, "beatha.mukangabo", "Change@2026") is None
    reg.reset_password(con, "beatha.mukangabo", "Temp1234")                 # admin reset forces a change again
    assert reg.login(con, "beatha.mukangabo", "Temp1234")["must_change"]
    with pytest.raises(ValueError):
        reg.update_user(con, "admin", active=0)                           # last admin stays active
    assert wf.seed_signatories(con) == []                                # no duplicates on re-run


def test_round_signatures_payables_and_appeal_steps(tmp_path):
    con = reg.connect(tmp_path / "c.db")
    wf.seed_signatories(con)
    sup = reg.login(con, "100007664", "omc2026")
    cid = _verified_claim(con, sup)
    rid = wf.create_round(con, [cid], "officer")
    r = wf.rounds(con).iloc[0]
    assert r["name"].startswith("15th submission") and r["status"] == "VERIFIED"
    approver = reg.login(con, "evariste.rugigana", "Change@2026")
    with pytest.raises(ValueError):
        wf.approve_round(con, rid, approver)                              # taskforce must sign first
    sigs = wf.signatories(con)
    for i, s in enumerate(sigs.itertuples()):
        st = wf.sign_round(con, rid, {"username": s.username, "name": s.name, "role": "taskforce"}, True)
        assert st == ("SIGNED" if i == len(sigs) - 1 else "SIGNING")
    with pytest.raises(ValueError):
        wf.sign_round(con, rid, {"username": sigs.username[0], "name": "x", "role": "taskforce"}, True)
    assert wf.approve_round(con, rid, approver) == "APPROVED"
    assert reg.status_of(con, cid) == "APPROVED"
    pay = reg.payables(con)
    assert len(pay) == 1 and pay.kind[0] == "First submission"
    reg.pay_payable(con, int(pay.id[0]), "finance", float(pay.amount[0]), "2026-11-05", "TRF-1")
    assert reg.status_of(con, cid) == "PAID"
    assert wf.setting(con, "next_round_number") == 16

    # appeal: filed -> verified by officer -> approved -> appeal payable -> paid
    rej = reg.lines_for(con, cid).query("rejected_qty > 0").source_row.astype(str).tolist()[:2]
    aid = reg.file_appeal(con, sup, cid, rej, "receipts")
    reg.recommend_appeal(con, aid, "officer", {rej[0]: 5.0, rej[1]: 0.0}, "line 1 verified")
    status, l, rwf = reg.approve_appeal(con, aid, "approver", True, "ok")
    assert status == "PARTLY UPHELD" and l == pytest.approx(5)
    pay = reg.payables(con)
    assert list(pay.kind) == ["First submission", f"Appeal #{aid}"] and reg.status_of(con, cid) == "PARTLY PAID"
    reg.mark_paid(con, cid, "finance", float(pay.outstanding.sum()), "2026-11-06", "TRF-2")
    assert reg.status_of(con, cid) == "PAID"


def test_round_returned_releases_claims(tmp_path):
    con = reg.connect(tmp_path / "c.db")
    wf.seed_signatories(con)
    cid = _verified_claim(con, reg.login(con, "100007664", "omc2026"))
    rid = wf.create_round(con, [cid], "officer")
    s = wf.signatories(con).iloc[0]
    with pytest.raises(ValueError):
        wf.sign_round(con, rid, {"username": s.username, "name": s["name"], "role": "taskforce"}, False, "")
    assert wf.sign_round(con, rid, {"username": s.username, "name": s["name"], "role": "taskforce"}, False,
                         "check line 12") == "RETURNED"
    assert cid in set(wf.unassigned_verified(con)["id"])


def _claim_with_request(con, user, requested):
    c = _f("claim_sample.xlsx")
    cid = reg.submit_claim(con, user, "SAMPLE OMC", "2026-06-01", "2026-06-30", "BK", c.getvalue(), c.name,
                           requested_rwf=requested, letter=b"%PDF-1.4 letter", letter_name="letter.pdf")
    lines, _, x = process(reg.claim_file(con, cid), _f("ebm_extract_sample.csv"),
                          {"tin": "100007664", "period_start": "2026-06-01", "period_end": "2026-06-30"},
                          _f("rura_prices.csv"))
    reg.save_processing(con, cid, apply_decisions(lines, {}, "o"), x, "officer", "")
    return cid


def test_pays_the_lower_of_requested_and_calculated(tmp_path):
    con = reg.connect(tmp_path / "c.db")
    sup = reg.login(con, "100007664", "omc2026")
    big = _claim_with_request(con, sup, 10_000_000)                  # asked for more than calculated
    r = reg.claims(con).set_index("id").loc[big]
    assert r.to_reimburse == round(r.calculated_rwf) and r.requested_rwf == 10_000_000
    small = _claim_with_request(con, sup, 1_000)                     # asked for less than calculated
    r2 = reg.claims(con).set_index("id").loc[small]
    assert r2.calculated_rwf > 1_000 and r2.to_reimburse == 1_000
    assert reg.claim_letter(con, small) == (b"%PDF-1.4 letter", "letter.pdf")
    assert reg.lower_of(None, 500) == (500.0, "calculated (no amount requested)")
    from engine.report import round_table
    t = round_table(reg.claims(con).sort_values("id"))
    assert list(t["Subsidies claimed (RWF)"][:2]) == [10_000_000, 1_000]
    assert t["Amount to reimburse (RWF)"].iloc[1] == 1_000


def test_delete_user_and_claims_keep_an_archive(tmp_path):
    con = reg.connect(tmp_path / "c.db")
    reg.create_user(con, "mgr", "A Manager", "manager", "Manager2026")
    reg.create_user(con, "smgr", "A Senior", "senior_manager", "Senior2026")
    assert reg.login(con, "mgr", "Manager2026")["role"] == "manager"
    sup = reg.login(con, "100007664", "omc2026")
    c = _f("claim_sample.xlsx")
    fresh = reg.submit_claim(con, sup, "SAMPLE OMC", "2026-06-01", "2026-06-30", "BK", c.getvalue(), c.name)
    done = _verified_claim(con, sup)
    with pytest.raises(ValueError):
        reg.delete_claim(con, done, "officer", "officer", "wrong file")           # officer: not after analysis
    with pytest.raises(ValueError):
        reg.delete_claim(con, fresh, "mgr", "manager", "x")                       # manager: never
    reg.delete_claim(con, fresh, "officer", "officer", "duplicate upload")
    reg.delete_claim(con, done, "admin", "admin", "test data")                    # admin: any stage
    assert reg.claims(con).empty and len(reg.deleted_claims(con)) == 2
    with pytest.raises(ValueError):
        reg.delete_user(con, "admin", "admin", "x")                               # not yourself
    kept = reg.delete_user(con, "100007664", "admin", "left the scheme")
    assert "2 claims" not in kept and reg.login(con, "100007664", "omc2026") is None
    assert reg.deleted_users(con).username.tolist() == ["100007664"]
    assert {"USER DELETED", "DELETED"} <= set(reg.events(con).action)


def test_pending_lines_rerouted_case_by_case(tmp_path):
    con = reg.connect(tmp_path / "c.db")
    sup = reg.login(con, "100007664", "omc2026")
    cid = _verified_claim(con, sup)
    pend = reg.pending_lines(con, cid)
    assert len(pend) >= 2, "the sample claim should leave lines pending"
    before = reg.claims(con).set_index("id").loc[cid]
    a, r = str(pend.source_row.iloc[0]), str(pend.source_row.iloc[1])
    with pytest.raises(ValueError):                                     # rejecting needs a reason
        reg.resolve_pending(con, cid, "officer", {a: ("Accept", ""), r: ("Reject", "")})
    res = reg.resolve_pending(con, cid, "officer", {a: ("Accept", "logbook seen"), r: ("Reject", "no EBM receipt")})
    after = reg.claims(con).set_index("id").loc[cid]
    assert after.to_reimburse == pytest.approx(before.to_reimburse + pend.pending_subsidy.iloc[0], abs=1)
    assert after.rejected_l == pytest.approx(before.rejected_l + pend.pending_qty.iloc[1], abs=0.01)
    lines = reg.lines_for(con, cid).set_index(reg.lines_for(con, cid).source_row.astype(str))
    assert lines.loc[a, "pending_qty"] == 0 and "logbook seen" in lines.loc[a, "decision"]
    assert "no EBM receipt" in lines.loc[r, "reason"]
    assert res["extra_payable"] == 0                                     # not approved yet: nothing to Finance
    # on an approved claim, accepting a pending line adds a separate payable
    reg.approve(con, cid, "approver")
    left = reg.pending_lines(con, cid)
    if len(left):
        res = reg.resolve_pending(con, cid, "officer", {str(left.source_row.iloc[0]): ("Accept", "ok")})
        p = reg.payables(con)
        assert (p.kind == "Pending review").sum() == (1 if res["extra_payable"] else 0)
    # blocked while the round is being signed
    sup2 = _verified_claim(con, sup)
    wf.create_round(con, [sup2], "officer")
    left2 = reg.pending_lines(con, sup2)
    with pytest.raises(ValueError):
        reg.resolve_pending(con, sup2, "officer", {str(left2.source_row.iloc[0]): ("Accept", "x")})


def test_return_to_supplier_keeps_the_reason(tmp_path):
    con = reg.connect(tmp_path / "c.db")
    sup = reg.login(con, "100007664", "omc2026")
    c = _f("claim_sample.xlsx")
    cid = reg.submit_claim(con, sup, "SAMPLE OMC", "2026-06-01", "2026-06-30", "BK", c.getvalue(), c.name)
    reg.return_claim(con, cid, "officer", "EBM Slip No missing")
    r = reg.claims(con).set_index("id").loc[cid]
    assert r.status == "RETURNED" and r.note == "EBM Slip No missing"


def test_data_export_queries(tmp_path):
    from engine import export as ex
    con = reg.connect(tmp_path / "c.db")
    sup = reg.login(con, "100007664", "omc2026")
    cid = _claim_with_request(con, sup, 1_000)
    for name, sql in ex.READY.items():                      # every ready-made extract runs
        ex.run_query(con, sql)
    lines = ex.run_query(con, ex.READY["All claim lines (accepted, pending, rejected)"])
    assert len(lines) == len(reg.lines_for(con, cid))
    with pytest.raises(ValueError):
        ex.run_query(con, "DELETE FROM claims")
    with pytest.raises(ValueError):
        ex.run_query(con, "SELECT 1; DROP TABLE claims")
    assert "pw" not in ex.run_query(con, "SELECT * FROM users").columns.tolist() or \
        ex.run_query(con, "SELECT pw FROM users").pw.isna().all()          # no password hashes
    assert ex.all_tables_excel(con)[:2] == b"PK"
    assert ex.database_backup(con)[:15] == b"SQLite format 3"
    assert len(reg.claims(con)) == 1                                      # real data untouched


def test_reporting_catalog_scoped_by_role(tmp_path):
    from engine import reports_catalog as rc
    con = reg.connect(tmp_path / "c.db")
    sup = reg.login(con, "100007664", "omc2026")
    cid = _claim_with_request(con, sup, 1_000)
    reg.create_user(con, "200000001", "OTHER OMC", "supplier", "Other2026", tin="200000001")
    other = reg.login(con, "200000001", "Other2026")
    officer = reg.login(con, "officer", "rra2026")
    for r in rc.CATALOG:                                     # every report runs for every role allowed
        for who in (sup, officer):
            if who["role"] in r.roles:
                r.build(con, who)
    assert len(rc.claims_statement(con, sup)) == 1
    assert rc.claims_statement(con, other).empty                    # a supplier never sees another's claims
    assert rc.rejected_lines(con, other).empty
    assert {r.key for r in rc.available("supplier")} == {"claims_statement", "payment_statement", "rejected_lines",
                                                          "appeals_status"}
    assert "pending_review" in {r.key for r in rc.available("officer")}
    assert not rc.monthly_summary(con, officer).empty


def test_batch_report_matches_the_taskforce_deck(tmp_path):
    from engine import batches as bt
    from engine.batch_deck import build_deck
    con = reg.connect(tmp_path / "c.db")
    bt.seed_history(con)
    df = bt.lines(con)
    o = bt.overview(df)
    assert o["batches"] == 15 and o["omcs"] == 8
    assert abs(o["claimed_l"] - 5_185_568) <= 2 and abs(o["accepted_l"] - 4_358_138) <= 2   # deck totals (rounding)
    assert abs(o["reimburse_rwf"] - 1_884_702_406) <= 2 and o["accepted_pct"] == 84.0
    pay = dict(zip(bt.by_batch(df).Batch, bt.by_batch(df).payout_pct.round()))
    assert pay["B2"] == 61 and pay["B13"] == 99 and pay["B15"] == 74
    omc = bt.by_omc(df).set_index("tin")
    assert omc.loc["101835101", "accepted_pct"] == 59.2 and omc.loc["101835101", "low"]       # VIVO
    assert omc.loc["100222174", "share_pct"] == 31.8                                          # Société Pétrolière
    c = bt.checks(df)
    assert ((c.Check == "Overlapping periods") & c.Detail.str.contains("22–26 Jul")).any()   # VIVO B5/B6
    assert ((c.Check == "Rate per litre") & c.Detail.str.contains("B10")).any()             # SP at ~416 RWF/L
    assert ((c.Check == "No vehicles recorded") & (c.TIN == "100025288")).any()              # RUBIS
    assert ((c.Check == "Gap with no claim") & c.Detail.str.contains("11–20 Jul")).any()      # Mount Meru
    assert bt.profile(df, "101968859")["headline"].startswith("Consistent")                   # IKWIM
    assert bt.lines(con, tin="101968859").tin.nunique() == 1                                  # supplier: own only
    assert build_deck(df)[:2] == b"PK"
    # the platform's first round continues the numbering after the history (B16)
    sup = reg.login(con, "100007664", "omc2026")
    cid = _verified_claim(con, sup)
    rid = wf.create_round(con, [cid], "officer")
    assert con.execute("SELECT number FROM rounds WHERE id=?", (rid,)).fetchone()[0] == 16
    assert 16 in set(bt.lines(con).batch)


def test_function_data_scientist_and_appeal_assignment(tmp_path):
    con = reg.connect(tmp_path / "c.db")
    reg.create_user(con, "aline.ds", "Aline (Data Scientist)", "data_scientist", "Datasci2026")
    u = reg.login(con, "aline.ds", "Datasci2026")
    assert u["role"] == "officer" and u["function"] == "data_scientist" and u["function_label"] == "Data Scientist"
    assert "appeal" in u["heads"] and "processing" not in u["heads"] and "payment" not in u["heads"]
    # the administrator can define another function
    fns = reg.functions(con)
    fns["vat_auditor"] = {"label": "VAT Auditor", "acts_as": "manager", "heads": ["reporting", "insights"]}
    reg.save_functions(con, fns, "admin")
    reg.create_user(con, "vat.aud", "VAT Auditor", "vat_auditor", "Vataudit2026")
    v = reg.login(con, "vat.aud", "Vataudit2026")
    assert v["role"] == "manager" and v["heads"] == ["home", "reporting", "insights", "account"]
    with pytest.raises(ValueError):
        reg.save_functions(con, {"x": {"label": "X", "acts_as": "admin", "heads": ["home"]}}, "admin")
    # appeal case assigned to the data scientist
    sup = reg.login(con, "100007664", "omc2026")
    cid = _verified_claim(con, sup)
    rej = reg.lines_for(con, cid).query("rejected_qty > 0").source_row.astype(str).tolist()[:1]
    aid = reg.file_appeal(con, sup, cid, rej, "receipt exists")
    reg.assign_appeal(con, aid, "aline.ds", "officer")
    ap = reg.appeals(con).set_index("id").loc[aid]
    assert ap.assigned_to == "aline.ds"
    assert wf.awaiting(con, u)["appeals_assigned"] == 1


def test_vat_annex_check():
    import pandas as pd
    from engine.cleaning import merge_key
    from engine.vat_annex import check, read_annex
    annex, problems = read_annex(_f("ebm_extract_real_layout.csv"))        # same layout as an EBM extract
    assert not annex.empty and (annex.key != "").all()
    k0 = annex.key.iloc[0]
    d0, a0 = annex.date.iloc[1], annex.amount.iloc[1]
    analysis = pd.DataFrame([
        {"row": "1", "matched_key": k0},                                   # same receipt → declared
        {"row": "2", "matched_key": "SDC999999999|1", "ebm_date": str(d0), "ebm_amount": a0,
         "ebm_buyer_tin": annex.buyer_tin.iloc[1]},                         # unknown receipt, same date/amount/buyer
        {"row": "3", "matched_key": "SDC999999999|2", "ebm_date": "2020-01-01", "ebm_amount": 5},   # not declared
        {"row": "4", "matched_key": ""},                                    # no EBM sale found
    ])
    out = check(analysis, annex).set_index("row")
    assert out.at["1", "vat_status"] == "Declared in the VAT annex" and out.at["1", "vat_match"] == "EBM receipt number"
    assert out.at["2", "vat_status"] == "Declared in the VAT annex"
    assert out.at["3", "vat_status"] == "Not in the VAT annex"
    assert out.at["4", "vat_status"] == "No EBM sale to look for"
