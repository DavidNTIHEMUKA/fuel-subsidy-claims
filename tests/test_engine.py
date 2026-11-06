import io
from pathlib import Path

import pandas as pd
import pytest

from engine.cleaning import normalize_slip, parse_datetime, parse_number, normalize_product
from engine.pipeline import process, summarise

DATA = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.mark.parametrize("raw,key", [
    ("SDC010057290/10540", "SDC010057290|10540"),
    ("sdc010057290 - 010540 ", "SDC010057290|10540"),
    (" SDC 010 057 290 / 10540", "SDC010057290|10540"),
    ("SDCO10057290/10541", "SDC010057290|10541"),
    ("SDC01005729010540", "SDC010057290|10540"),
    ("010057290/10540", "SDC010057290|10540"),
    ("10540/SDC010057290", "SDC010057290|10540"),
    ("SDC-010057290_10540 NS", "SDC010057290|10540"),
    ("SDC010057290#10540", "SDC010057290|10540"),
    ("SDC007079204-5107", "SDC007079204|5107"),
])
def test_slip_harmonised(raw, key):
    assert normalize_slip(raw).key == key


@pytest.mark.parametrize("raw,status", [
    ("", "MISSING"), ("-", "MISSING"), ("SDC010057290", "INCOMPLETE"),
    ("10540", "INCOMPLETE"), ("abc", "INVALID"), ("SDC0100572/10540", "INVALID"),
])
def test_slip_problems(raw, status):
    assert normalize_slip(raw).status == status


@pytest.mark.parametrize("raw,kind,value", [
    (" 78.73 ", "qty", 78.73), ("2,927.00", "price", 2927), ("2.927", "price", 2927),
    ("230,443", "amount", 230443), ("34,483.78", "amount", 34483.78), ("1.234.567", "amount", 1234567),
    ("78,73", "qty", 78.73), ("78,730", "qty", 78.73), ("RWF 1 200", "amount", 1200),
    ("2 927,50", "price", 2927.5), (" 78.73 L", "qty", 78.73), (2927.0, "price", 2927),
])
def test_numbers(raw, kind, value):
    assert parse_number(raw, kind)[0] == pytest.approx(value)


def test_dates_dayfirst_with_swap_alternative():
    ts, alt, _ = parse_datetime("07/06/2026 00:14")
    assert ts == pd.Timestamp("2026-06-07 00:14") and alt == pd.Timestamp("2026-07-06 00:14")
    assert parse_datetime("2026-06-11 00:45:30")[0] == pd.Timestamp("2026-06-11 00:45:30")
    assert parse_datetime(46184.5)[0] == pd.Timestamp("2026-06-11 12:00")


def test_products():
    assert normalize_product("AGO - 1x") == "DIESEL"
    assert normalize_product("Diesel-Mazout-AGO") == "DIESEL"
    assert normalize_product("Gasoline -Petrol-essence-PMS") == "PETROL"


def _run(**meta_over):
    meta = {"tin": "100007664", "name": "SAMPLE OMC", "period_start": "2026-06-01", "period_end": "2026-06-30"}
    meta.update(meta_over)
    with open(DATA / "claim_sample.xlsx", "rb") as c, open(DATA / "ebm_extract_sample.csv", "rb") as e, \
            open(DATA / "rura_prices.csv", "rb") as r:
        uploads = []
        for f in (c, e, r):
            b = io.BytesIO(f.read())
            b.name = Path(f.name).name     # behaves like a browser upload
            uploads.append(b)
        return process(uploads[0], uploads[1], meta, uploads[2])


def test_every_sample_case_gets_expected_status():
    lines, problems, xlsx = _run()
    expected = pd.read_csv(DATA / "expected.csv")["expect"].str.split().str[0].tolist()
    assert lines["status"].tolist() == expected
    assert xlsx[:2] == b"PK"   # a real .xlsx


def test_money_adds_up():
    lines, _, _ = _run()
    s = summarise(lines)
    assert s["accepted_qty"] + s["pending_qty"] + s["rejected_qty"] == pytest.approx(s["claimed_qty"], abs=0.05)
    row = lines[lines["source_row"] == 6].iloc[0]          # 78.45 L claimed, 69 L in EBM
    assert row["accepted_qty"] == 69.0 and row["rejected_qty"] == pytest.approx(9.45)
    assert row["accepted_subsidy"] == pytest.approx(69 * 438)


@pytest.mark.parametrize("text,year,start,end", [
    ("Period: 01/06/2026 - 30/06/2026", None, "2026-06-01", "2026-06-30"),
    ("28 Sept - 04 Oct 2026", None, "2026-09-28", "2026-10-04"),
    ("21 - 30 Sept 2026", None, "2026-09-21", "2026-09-30"),
    ("29  June - 30 Sept ", 2026, "2026-06-29", "2026-09-30"),
    ("Période du 01 octobre au 15 octobre 2026", None, "2026-10-01", "2026-10-15"),
    ("26 Dec - 05 Jan 2027", None, "2026-12-26", "2027-01-05"),
])
def test_interval_formats(text, year, start, end):
    from engine.cleaning import parse_interval
    s, e = parse_interval(text, default_year=year)
    assert (s, e) == (pd.Timestamp(start), pd.Timestamp(end))


def test_interval_read_from_file_and_required():
    lines, problems, _ = _run(period_start=None, period_end=None)   # read from title row
    assert lines is not None and "01/06/2026" in lines.attrs["interval"].iloc[0, 1]
    blank = io.BytesIO()
    pd.DataFrame({"Closed at": ["07/06/2026 00:14"], "Vehicle ID": ["RAH659I"], "Product": ["AGO"],
                  "Quantity": [10], "P.U": [2927], "EBM Slip No": ["SDC010057290/10540"]}).to_excel(blank, index=False)
    blank.name = "claim.xlsx"; blank.seek(0)
    with open(DATA / "ebm_extract_sample.csv", "rb") as f:
        e = io.BytesIO(f.read()); e.name = "ebm.csv"
    lines, problems, _ = process(blank, e, {"tin": "100007664"})
    assert lines is None and any("interval not declared" in p for p in problems)


def test_full_flow_submit_process_approve_pay_appeal(tmp_path):
    from engine import register as reg
    from engine.rules import apply_decisions
    con = reg.connect(tmp_path / "claims.db")
    supplier = reg.login(con, "100007664", "omc2026")
    assert supplier and supplier["role"] == "supplier" and reg.login(con, "100007664", "wrong") is None
    c_, e_, r_ = _files()
    cid = reg.submit_claim(con, supplier, "SAMPLE OMC", "2026-06-01", "2026-06-30", "BK 123", c_.getvalue(), c_.name)
    assert reg.status_of(con, cid) == "SUBMITTED"
    with pytest.raises(ValueError):                                   # cannot skip analysis
        reg.approve(con, cid, "officer")

    lines, problems, xlsx = process(reg.claim_file(con, cid), e_, {"tin": "100007664", "name": "SAMPLE OMC",
                                    "period_start": "2026-06-01", "period_end": "2026-06-30"}, r_,
                                    register_history=reg.history_keys(con, exclude_claim=cid))
    review_rows = lines.loc[lines.status == "REVIEW", "source_row"].tolist()
    decided = apply_decisions(lines, {review_rows[0]: ("Accept", "logbook ok"),
                                      review_rows[1]: ("Reject", "no proof")}, "officer")
    assert (decided.status == "REVIEW").sum() == len(review_rows) - 2
    reg.save_processing(con, cid, decided, xlsx, "officer", "1st (June 2026)")
    c = reg.claims(con).iloc[0]
    assert c.status == "PROCESSED" and c.to_reimburse == pytest.approx(decided.accepted_subsidy.sum(), abs=1)

    reg.approve(con, cid, "officer")
    due = reg.claims(con).iloc[0].to_reimburse
    reg.mark_paid(con, cid, "finance", due, "2026-11-04", "TRF-1")
    assert reg.status_of(con, cid) == "PAID"

    # appeal on two rejected lines; uphold one -> claim reopens for the extra amount
    rej = reg.lines_for(con, cid).query("rejected_qty > 0")
    rows = rej.source_row.astype(str).tolist()[:2]
    aid = reg.file_appeal(con, supplier, cid, rows, "receipts attached")
    with pytest.raises(ValueError):                                   # same lines twice
        reg.file_appeal(con, supplier, cid, rows[:1], "again")
    status, litres, rwf = reg.decide_appeal(con, aid, "officer", rows[:1], "receipt verified")
    assert status == "PARTLY UPHELD" and rwf > 0
    c = reg.claims(con).iloc[0]
    assert c.status == "PARTLY PAID" and c.outstanding == pytest.approx(rwf, abs=1)
    reg.mark_paid(con, cid, "finance", c.outstanding, "2026-11-05", "TRF-2")
    assert reg.status_of(con, cid) == "PAID"

    # resubmitting the same invoices is blocked by R2
    c2_, e2_, r2_ = _files()
    again, _, _ = process(c2_, e2_, {"tin": "100007664", "period_start": "2026-06-01", "period_end": "2026-06-30"},
                          r2_, register_history=reg.history_keys(con))
    assert again["accepted_qty"].sum() == 0

    # every forbidden jump is refused
    with pytest.raises(ValueError):
        reg.move(con, cid, "SUBMITTED", "x")


def _files():
    out = []
    for n in ("claim_sample.xlsx", "ebm_extract_sample.csv", "rura_prices.csv"):
        b = io.BytesIO((DATA / n).read_bytes()); b.name = n; out.append(b)
    return out


def test_month_first_file_gives_same_result_as_day_first():
    base, _, _ = _run()
    c = io.BytesIO((DATA / "claim_sample_mmddyyyy.xlsx").read_bytes()); c.name = "claim_mdy.xlsx"
    _, e, r = _files()
    lines, problems, _ = process(c, e, {"tin": "100007664"}, r)          # interval read from the file
    assert any("month/day/year" in p for p in problems)
    assert lines["status"].tolist() == base["status"].tolist()
    assert lines["accepted_qty"].sum() == pytest.approx(base["accepted_qty"].sum())


def test_ambiguous_dates_settled_by_interval_and_excel_swaps():
    import datetime as dt
    from engine.cleaning import harmonize_dates
    J, E = pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-30")
    mdy = [f"06/{d:02d}/2026 08:00" for d in range(1, 13)]
    dmy = [f"{d:02d}/06/2026 08:00" for d in range(1, 13)]
    assert harmonize_dates(mdy, J, E)[1] == "MDY" and harmonize_dates(dmy, J, E)[1] == "DMY"
    assert all(t.month == 6 for t, _, _ in harmonize_dates(mdy, J, E)[0])
    assert harmonize_dates(["6/7/2026 12:14 AM"], J, E)[0][0][0] == pd.Timestamp("2026-06-07 00:14")
    cell = harmonize_dates([dt.datetime(2026, 7, 6)], J, E)[0][0]
    assert cell[0] == pd.Timestamp("2026-06-07") and "swapped" in cell[2]


def test_real_ebm_layout_receipt_counter_and_spaces():
    """EBM 2.1 extract: no invoice_number; key = SdcId + SdcReceiptTypeCounter, spaces removed."""
    from engine.cleaning import EBM_COLUMNS, EBM_REQUIRED, clean_ebm, read_table
    e = io.BytesIO((DATA / "ebm_extract_real_layout.csv").read_bytes()); e.name = "ebm_real.csv"
    raw, problems = read_table(e, EBM_COLUMNS, EBM_REQUIRED, "EBM")
    assert not problems
    ebm = clean_ebm(raw, interval=(pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-30")))
    assert "SDC010057290|10540" in set(ebm.ebm_key) and "SDC010002825|1046" in set(ebm.ebm_key)
    assert ebm.loc[ebm.ebm_key == "SDC010002825|1046", "sdc_datetime"].iloc[0] == pd.Timestamp("2026-06-07 17:20")
    base, _, _ = _run()
    c, _, r = _files()
    e.seek(0)
    lines, _, _ = process(c, e, {"tin": "100007664", "period_start": "2026-06-01", "period_end": "2026-06-30"}, r)
    assert lines.status.tolist() == base.status.tolist()


def test_builtin_pump_price_list_is_used_and_catches_underpricing():
    from engine.pipeline import DEFAULT_PRICE_FILE, load_rura_prices
    prices = load_rura_prices(DEFAULT_PRICE_FILE)
    assert set(prices["product"]) >= {"DIESEL", "PETROL", "MOGAS", "LPG"}
    assert prices.loc[prices["product_raw"] == "Mogas Petroleum", "product"].iloc[0] == "MOGAS"   # not mixed with petrol
    c, e, _ = _files()
    lines, problems, _ = process(c, e, {"tin": "100007664", "period_start": "2026-06-01",
                                        "period_end": "2026-06-30"})            # no price file given
    assert any(p.startswith("RURA/pump price reference") for p in problems)
    assert not any("R4) was skipped" in p for p in problems)
    under = lines[lines.source_row == 11].iloc[0]                                # sold at 2,700 vs 2,927
    assert under.status == "REJECTED" and under.reason.startswith("R4")


def test_claim_form_is_read_with_real_dates_and_interval():
    import datetime as dt
    from openpyxl import load_workbook
    from engine.forms import claim_form, form_check, is_claim_form
    from engine.cleaning import CLAIM_COLUMNS, CLAIM_REQUIRED, read_table
    wb = load_workbook(io.BytesIO(claim_form("SAMPLE OMC", "100007664", "2026-06-01", "2026-06-30")))
    ws = wb["Claim"]
    rows = [[1, "RWAMAGANA", "100007664", "Stella Express Ltd", dt.datetime(2026, 6, 7, 0, 14), "RAH659I", "19xx",
             "AGO", 78.73, 2927, None, 438, None, None, "Eric", "SDC010057290/10540"],
            [2, "RWAMAGANA", "100007665", "Stella Express Ltd", dt.datetime(2026, 6, 7, 0, 54), "RAG840V", "19xx",
             "AGO", 69, 2927, None, 438, None, None, "Eric", "SDC010057290/10541"]]
    for r, vals in enumerate(rows, 7):
        for c, v in enumerate(vals, 1):
            if v is not None:
                ws.cell(row=r, column=c, value=v)
    out = io.BytesIO(); wb.save(out); data = out.getvalue()
    f = io.BytesIO(data); f.name = "form.xlsx"
    raw, problems = read_table(f, CLAIM_COLUMNS, CLAIM_REQUIRED, "Claim")
    assert is_claim_form(data) and not problems and not form_check(raw) and len(raw) == 2
    _, e, r = _files()
    f.seek(0)
    lines, notes, _ = process(f, e, {"tin": "100007664"}, r)          # interval read from cell A4
    assert list(lines.omc_tin) == ["100007664", "100007665"]
    assert lines.iloc[0].status == "ACCEPTED" and lines.iloc[0].accepted_subsidy == pytest.approx(78.73 * 438)
    # a mistyped OMC TIN does not reject a sale the EBM shows was made by the claimant; it is noted
    assert "OMC TIN written 100007665" in lines.iloc[1].match_notes
    from engine.precheck import submission_warnings
    from engine.cleaning import clean_claim
    w = submission_warnings(clean_claim(raw), "2026-06-01", "2026-06-30", {"DIESEL": 438}, None, own_tin="100007664")
    assert "OMC TIN different from your TIN" in set(w.Check)


def test_appeal_reanalysis_with_corrected_slip(tmp_path):
    """Supplier corrects a wrong slip number in the appeal form; the re-match finds the real invoice."""
    from engine import register as reg
    from engine.appeal_analysis import reanalyse
    from engine.forms import appeal_form, read_appeal_form
    from engine.pipeline import load_rura_prices
    from engine.rules import apply_decisions
    from openpyxl import load_workbook
    con = reg.connect(tmp_path / "c.db")
    sup = reg.login(con, "100007664", "omc2026")
    c, e, r = _files()
    cid = reg.submit_claim(con, sup, "SAMPLE OMC", "2026-06-01", "2026-06-30", "BK", c.getvalue(), c.name)
    lines, _, x = process(reg.claim_file(con, cid), e, {"tin": "100007664", "period_start": "2026-06-01",
                                                        "period_end": "2026-06-30"}, r)
    reg.save_processing(con, cid, apply_decisions(lines, {}, "o"), x, "o", "1st")
    stored = reg.lines_for(con, cid)
    assert stored.loc[stored.source_row == "24", "reason"].iloc[0].startswith("R1")       # 35 L, slip not in EBM

    # EBM file that also contains the real receipt of row 24
    ebm = pd.read_csv(DATA / "ebm_extract_sample.csv", dtype=str)
    extra = ebm.iloc[[0]].copy()
    extra[["invoice_number", "SdcDateTime", "ItemQuantity"]] = ["10700", "2026-06-12 12:00:30", "35"]
    ebm2 = io.BytesIO(pd.concat([ebm, extra]).to_csv(index=False).encode()); ebm2.name = "ebm.csv"

    sel = stored[stored.source_row.isin(["24", "6"])].assign(claim_id=cid)
    wb = load_workbook(io.BytesIO(appeal_form(sel)))
    ws = wb.active
    for row in ws.iter_rows(min_row=5):
        if str(row[1].value) == "24":
            row[7].value = "SDC010057290/10700"
    o = io.BytesIO(); wb.save(o)
    corr = read_appeal_form(o.getvalue())
    aid = reg.file_appeal(con, sup, cid, ["24", "6"], "wrong counter typed", corrections=corr)

    claim = dict(reg.claims(con).set_index("id").loc[cid], id=cid)
    res, _ = reanalyse(claim, stored, ["24", "6"], reg.appeal_corrections(con, aid), ebm2,
                       reg.history_keys(con, exclude_claim=cid), load_rura_prices(DATA / "rura_prices.csv"))
    res = res.set_index("row")
    assert res.at["24", "new_status"] == "ACCEPTED" and res.at["24", "award_l"] == pytest.approx(35)
    assert res.at["6", "award_l"] == 0                                     # EBM still shows only 69 L
    reg.save_appeal_analysis(con, aid, res.reset_index(), "o")
    before = reg.claims(con).iloc[0].to_reimburse
    status, l, rwf = reg.decide_appeal(con, aid, "o", ["24"], "receipt verified",
                                       awards={"24": 35.0, "6": 0.0}, new_keys={"24": res.at["24", "matched_key"]})
    assert status == "PARTLY UPHELD" and l == pytest.approx(35)
    assert reg.claims(con).iloc[0].to_reimburse == pytest.approx(before + 35 * 438, abs=1)
    after = reg.lines_for(con, cid).set_index("source_row")
    assert after.at["24", "invoice_clean"] == "SDC01005729010700"
    assert "SDC010057290|10700" in reg.history_keys(con)                  # the corrected invoice is now blocked
