"""Standard Excel forms, so every supplier submits the same structure.

* Claim form   — the 15 columns of the reimbursement request, real date cells,
                 product dropdown, numeric checks, EBM Slip No check, totals
                 formulas and an instructions sheet.
* Appeal form  — prefilled with the rejected lines the supplier selected; the
                 supplier fills the corrected EBM Slip No / quantity and the
                 explanation, and uploads it with the appeal.
"""
from __future__ import annotations

from io import BytesIO

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .cleaning import clean_text, header_key, normalize_slip, parse_number

NAVY, GREEN, ORANGE, GROUND = "0B2B57", "1B7A3E", "E8820E", "EEF3F9"
CLAIM_HEADERS = ["#", "Site-name", "OMC TIN", "Client-name", "Closed at", "Vehicle ID", "Card Number", "Product", " Quantity ",
                 "P.U", "Amount", "subsidy rate", "subsidy Amount", "Net To be Payed", "Served-by", "EBM Slip No"]
HEADER_ROW = 6
FORM_ROWS = 3000
FORM_MARK = "FUEL SUBSIDY CLAIM FORM v3"
FORM_MARKS = ("FUEL SUBSIDY CLAIM FORM v1", "FUEL SUBSIDY CLAIM FORM v2", FORM_MARK)

HELP = {
    "Closed at": "Date and time of the sale as a real Excel date (dd/mm/yyyy hh:mm).",
    "OMC TIN": "TIN of the fuel supplier (OMC) that sold the fuel — your own TIN, 9 digits. It is checked against the seller TIN on the EBM receipt.",
    "Vehicle ID": "Plate number without spaces, e.g. RAH659I.",
    "Product": "Choose AGO (diesel) or PMS (petrol).",
    " Quantity ": "Litres sold, as a number (e.g. 78.73).",
    "P.U": "Pump price per litre in RWF, as a number (e.g. 2927).",
    "subsidy rate": "Subsidy per litre in RWF (e.g. 438).",
    "EBM Slip No": "SDC ID / receipt counter exactly as on the EBM receipt, e.g. SDC010057290/10540.",
}


def _header(ws, row, headers, fill=NAVY):
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=fill)
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")


def claim_form(name: str = "", tin: str = "", start=None, end=None, rate: float = 438) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Claim"
    ws["A1"] = "FUEL SUBSIDY REIMBURSEMENT REQUEST"
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    ws["A2"] = "Fuel supplier (OMC):"
    ws["C2"] = name or "[company name]"
    ws["A3"] = "TIN:"
    ws["C3"] = tin or "[TIN]"
    s = f"{pd.Timestamp(start):%d/%m/%Y}" if start is not None else "dd/mm/yyyy"
    e = f"{pd.Timestamp(end):%d/%m/%Y}" if end is not None else "dd/mm/yyyy"
    ws["A4"] = f"Period: {s} - {e}"
    ws["A4"].font = Font(bold=True)
    ws["H4"] = FORM_MARK
    ws["H4"].font = Font(color="8FA6C4", size=8)
    _header(ws, HEADER_ROW, CLAIM_HEADERS)
    for i, h in enumerate(CLAIM_HEADERS, 1):
        if h in HELP:
            ws.cell(row=HEADER_ROW, column=i).comment = Comment(HELP[h], "RRA")

    first, last = HEADER_ROW + 1, HEADER_ROW + FORM_ROWS
    col = {h: get_column_letter(i) for i, h in enumerate(CLAIM_HEADERS, 1)}
    for r in range(first, last + 1):
        ws[f"{col['Closed at']}{r}"].number_format = "dd/mm/yyyy hh:mm"
        ws[f"{col[' Quantity ']}{r}"].number_format = "#,##0.00"
        ws[f"{col['P.U']}{r}"].number_format = "#,##0.00"
        ws[f"{col['subsidy rate']}{r}"].number_format = "#,##0"
        q, p, rt = (f"{col[' Quantity ']}{r}", f"{col['P.U']}{r}", f"{col['subsidy rate']}{r}")
        ws[f"{col['Amount']}{r}"] = f'=IF(AND(ISNUMBER({q}),ISNUMBER({p})),ROUND({q}*{p},0),"")'
        ws[f"{col['subsidy Amount']}{r}"] = f'=IF(AND(ISNUMBER({q}),ISNUMBER({rt})),ROUND({q}*{rt},2),"")'
        ws[f"{col['Net To be Payed']}{r}"] = (f'=IF(AND(ISNUMBER({col["Amount"]}{r}),ISNUMBER({col["subsidy Amount"]}{r})),'
                                              f'{col["Amount"]}{r}-{col["subsidy Amount"]}{r},"")')
        for c in ("Amount", "subsidy Amount", "Net To be Payed"):
            ws[f"{col[c]}{r}"].number_format = "#,##0.00"
            ws[f"{col[c]}{r}"].fill = PatternFill("solid", fgColor=GROUND)

    def dv(kind, rng, title, msg, **kw):
        v = DataValidation(type=kind, allow_blank=True, showErrorMessage=True, errorTitle=title, error=msg, **kw)
        v.add(rng)
        ws.add_data_validation(v)

    rng = lambda c: f"{col[c]}{first}:{col[c]}{last}"
    dv("date", rng("Closed at"), "Date", "Enter a real date and time, e.g. 07/06/2026 00:14.",
       operator="between", formula1="DATE(2020,1,1)", formula2="DATE(2035,12,31)")
    dv("list", rng("Product"), "Product", "Choose AGO or PMS from the list.", formula1='"AGO,PMS"')
    dv("decimal", rng(" Quantity "), "Quantity", "Litres must be a number above 0.",
       operator="between", formula1="0.01", formula2="2000")
    dv("decimal", rng("P.U"), "Price", "Price per litre in RWF, between 500 and 10 000.",
       operator="between", formula1="500", formula2="10000")
    dv("decimal", rng("subsidy rate"), "Subsidy rate", "Subsidy per litre in RWF.",
       operator="between", formula1="0", formula2="5000")
    t = col["OMC TIN"]
    for r in range(first, last + 1):
        ws[f"{t}{r}"].number_format = "@"                      # text: keeps the 9 digits as typed
    dv("custom", rng("OMC TIN"), "OMC TIN", "The OMC TIN is your 9-digit TIN, e.g. 100007664.",
       formula1=f'AND(LEN({t}{first})=9,ISNUMBER(--{t}{first}))')
    o = col["EBM Slip No"]
    dv("custom", rng("EBM Slip No"), "EBM Slip No", "Write the slip as SDC ID / counter, e.g. SDC010057290/10540.",
       formula1=f'AND(LEFT(UPPER({o}{first}),3)="SDC",ISNUMBER(FIND("/",{o}{first})))')
    ws[f"{col['subsidy rate']}{first}"] = rate

    widths = [6, 22, 12, 22, 18, 12, 18, 10, 11, 10, 12, 10, 13, 15, 20, 22]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=first, column=1)

    hs = wb.create_sheet("Instructions")
    lines = [
        ("How to fill this form", True),
        ("1. Do not rename, move or delete columns; do not add columns before 'EBM Slip No'.", False),
        ("2. Fill the period of consumption in cell A4: 'Period: dd/mm/yyyy - dd/mm/yyyy'.", False),
        ("3. One line per sale. 'Closed at' must be a real date cell (dd/mm/yyyy hh:mm), not text.", False),
        ("4. OMC TIN: your own 9-digit TIN (the fuel supplier that sold the fuel), the same on every line. Client-name: the transport operator.", False),
        ("5. Product: AGO for diesel, PMS for petrol (dropdown).", False),
        ("6. Quantity, P.U and subsidy rate are numbers without 'L' or 'RWF'.", False),
        ("7. Amount, subsidy Amount and Net To be Payed are calculated automatically (grey cells).", False),
        ("8. EBM Slip No exactly as printed on the EBM receipt: SDC ID / receipt counter (SDC010057290/10540).", False),
        ("9. Save as .xlsx and upload it under 'Submission of request'.", False),
        ("Lines with errors are shown before you submit, so you can correct them.", True),
    ]
    for i, (t, bold) in enumerate(lines, 1):
        hs.cell(row=i, column=1, value=t).font = Font(bold=bold, color=NAVY if bold else "14213D")
    hs.column_dimensions["A"].width = 110
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def form_check(raw: pd.DataFrame) -> list[str]:
    """Problems with the structure of an uploaded claim (empty list = follows the form)."""
    problems = []
    needed = {"closed_at": "Closed at", "vehicle": "Vehicle ID", "product": "Product", "qty": "Quantity",
              "unit_price": "P.U", "subsidy_rate": "subsidy rate", "slip": "EBM Slip No", "client": "Client-name",
              "site": "Site-name"}
    missing = [label for k, label in needed.items() if k not in raw.columns]
    if missing:
        problems.append("Not the standard claim form — missing column(s): " + ", ".join(missing) +
                        ". Download the claim form and copy your lines into it.")
    if "omc_tin" not in raw.columns:
        problems.append("No 'OMC TIN' column — add your TIN (fuel supplier, 9 digits) on each line; it is checked "
                        "against the seller TIN on the EBM receipt.")
    if "closed_at" in raw:
        text_dates = raw["closed_at"].map(lambda v: isinstance(v, str) and bool(clean_text(v))).sum()
        if text_dates:
            problems.append(f"{text_dates} 'Closed at' value(s) are typed as text, not Excel dates. They were read, "
                            "but in the claim form please enter real date cells (dd/mm/yyyy hh:mm) to avoid "
                            "day/month confusion.")
    return problems


# ---------------------------------------------------------------------------
# Appeal form
# ---------------------------------------------------------------------------
APPEAL_HEADERS = ["Claim #", "Row", "Vehicle", "Closed at", "EBM Slip No (claimed)", "Rejected L", "Reason for rejection",
                  "Corrected EBM Slip No", "Corrected quantity (L)", "Explanation"]


def appeal_form(selected: pd.DataFrame) -> bytes:
    """selected: rejected lines with claim_id, source_row, vehicle, closed_at, slip_clean/slip_raw, rejected_qty, reason."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Appeal"
    ws["A1"] = "FUEL SUBSIDY APPEAL FORM"
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    ws["A2"] = ("Fill the orange columns only where something must change: the correct EBM Slip No as printed on the "
                "receipt, the correct quantity, and an explanation for each line.")
    _header(ws, 4, APPEAL_HEADERS[:7], NAVY)
    for i, h in enumerate(APPEAL_HEADERS[7:], 8):
        c = ws.cell(row=4, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=ORANGE)
    for r, (_, x) in enumerate(selected.iterrows(), 5):
        vals = [int(x["claim_id"]), int(float(x["source_row"])), x.get("vehicle", ""), x.get("closed_at", ""),
                x.get("slip_raw", "") or x.get("slip_clean", ""), float(x.get("rejected_qty", 0) or 0),
                x.get("reason", "")]
        for c, v in enumerate(vals, 1):
            ws.cell(row=r, column=c, value=v)
    for i, w in enumerate([8, 6, 11, 17, 22, 10, 50, 24, 16, 50], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A5"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_appeal_form(data: bytes) -> pd.DataFrame:
    """Corrections from an uploaded appeal form: claim_id, row, slip, qty, explanation."""
    raw = pd.read_excel(BytesIO(data), header=None, dtype=object)
    hdr = None
    for r in range(min(15, len(raw))):
        keys = [header_key(v) for v in raw.iloc[r].tolist()]
        if "claim#" in keys and "row" in keys:
            hdr = r
            break
    if hdr is None:
        raise ValueError("This is not the appeal form (columns 'Claim #' and 'Row' not found)")
    body = raw.iloc[hdr + 1:].copy()
    body.columns = [header_key(v) for v in raw.iloc[hdr].tolist()]
    out = []
    for _, r in body.iterrows():
        cid, row = parse_number(r.get("claim#"))[0], parse_number(r.get("row"))[0]
        if cid is None or row is None:
            continue
        slip = clean_text(r.get("correctedebmslipno"))
        qty = parse_number(r.get("correctedquantityl"), "qty")[0]
        out.append({"claim_id": int(cid), "row": str(int(row)),
                    "slip": slip if slip and normalize_slip(slip).key else "",
                    "slip_problem": bool(slip) and not normalize_slip(slip).key,
                    "qty": qty, "explanation": clean_text(r.get("explanation"))})
    return pd.DataFrame(out, columns=["claim_id", "row", "slip", "slip_problem", "qty", "explanation"])


def is_claim_form(data: bytes) -> bool:
    try:
        ws = load_workbook(BytesIO(data), read_only=True).active
        return any(clean_text(c.value) in FORM_MARKS for row in ws.iter_rows(max_row=6) for c in row)
    except Exception:
        return False
