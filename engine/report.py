"""Excel output: taskforce summary, accepted, rejected, review, supplier notice."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from io import BytesIO

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .config import Settings
from .indicators import by_vehicle, indicators, match_summary, price_check
from .rules import RULES, summarise

NAVY, GREEN, ORANGE, BLUE = "0B2B57", "1B7A3E", "E8820E", "1460AA"


def _period_text(start, end):
    if start is None or end is None:
        return ""
    return f"{start:%d %b} – {end:%d %b %Y}"


def _fmt_dt(s):
    return s.dt.strftime("%d/%m/%Y %H:%M") if hasattr(s, "dt") else s


def build_tables(lines: pd.DataFrame, meta: dict) -> dict[str, pd.DataFrame]:
    s = summarise(lines)
    period = _period_text(meta.get("period_start"), meta.get("period_end"))

    summary = pd.DataFrame([{
        "TIN": meta.get("tin", ""),
        "Taxpayer name / Fuel supplier": meta.get("name", ""),
        "Period requested": period,
        "Number of vehicles": s["vehicles"],
        "Fuel consumption claimed (L)": s["claimed_qty"],
        "Subsidies claimed (RWF)": round(s["claimed_subsidy"]),
        "Quantity accepted (L)": s["accepted_qty"],
        "Quantity pending/rejected (L)": round(s["pending_qty"] + s["rejected_qty"], 2),
        "Amount to reimburse (RWF)": round(s["accepted_subsidy"]),
        "Account number": meta.get("account", ""),
        "Processing date": datetime.now().strftime("%d/%m/%Y"),
        "Processor": meta.get("processor", ""),
        "Amount to reimburse rejected (RWF)": round(s["rejected_subsidy"] + s["pending_subsidy"]),
    }])

    breakdown = pd.DataFrame([
        ("Accepted", s["accepted_lines"], ""), ("Partly accepted", s["partial_lines"], ""),
        ("Rejected", s["rejected_lines"], ""), ("Pending human review", s["review_lines"],
                                                f"{s['pending_qty']:,.2f} L · {s['pending_subsidy']:,.0f} RWF"),
    ], columns=["Outcome", "Lines", "Pending"])

    reasons = (lines.loc[lines["reason"] != "", ["reason", "rejected_qty", "rejected_subsidy"]]
               .assign(rule=lambda d: d["reason"].str.split(" · ").str[0])
               .groupby("rule").agg(lines=("reason", "size"), litres=("rejected_qty", "sum"),
                                    rwf=("rejected_subsidy", "sum")).reset_index())
    reasons["description"] = reasons["rule"].map(RULES)
    reasons = reasons[["rule", "description", "lines", "litres", "rwf"]].round(2)

    base = ["source_row", "site", "omc_tin", "client", "closed_at", "vehicle", "card", "product_raw", "qty",
            "unit_price", "slip_clean", "invoice_clean", "ebm_qty", "ebm_unit_price", "ebm_datetime", "ebm_tax_type"]
    nice = {"source_row": "Row in file", "site": "Site", "client": "Client", "omc_tin": "OMC TIN", "closed_at": "Closed at",
            "vehicle": "Vehicle", "card": "Card", "product_raw": "Product", "qty": "Claimed L",
            "unit_price": "P.U", "slip_raw": "EBM Slip No (as sent)", "slip_clean": "EBM Slip No",
            "invoice_clean": "EBM invoice", "matched_key": "EBM invoice matched",
            "ebm_qty": "EBM L", "ebm_unit_price": "EBM P.U", "ebm_datetime": "EBM date",
            "ebm_tax_type": "EBM tax type", "accepted_qty": "Accepted L", "accepted_subsidy": "Subsidy to pay",
            "rejected_qty": "Rejected L", "rejected_subsidy": "Subsidy rejected", "reason": "Reason",
            "pending_qty": "Pending L", "pending_subsidy": "Subsidy pending", "review_reason": "Why review",
            "match_method": "Matched by", "match_notes": "Notes", "cleaning_notes": "Cleaning applied",
            "format_issues": "Problem", "warnings": "Warning", "status": "Status"}

    def view(df, cols):
        v = df[cols].copy()
        for c in ("closed_at", "ebm_datetime"):
            if c in v:
                v[c] = pd.to_datetime(v[c]).dt.strftime("%d/%m/%Y %H:%M")
        if "matched_key" in v:
            v["matched_key"] = v["matched_key"].fillna("").str.replace("|", "/", regex=False)
        return v.rename(columns=nice)

    accepted = view(lines[lines["status"].isin(["ACCEPTED", "PARTIAL"])],
                    base + ["accepted_qty", "accepted_subsidy", "match_method", "match_notes"])
    rejected = view(lines[(lines["rejected_qty"] > 0) & (lines["reason"] != "")],
                    base + ["rejected_qty", "rejected_subsidy", "reason"])
    review = view(lines[lines["status"] == "REVIEW"],
                  base + ["pending_qty", "pending_subsidy", "review_reason", "match_method"])
    review["Decision (Accept/Reject)"] = ""
    review["Reviewer note"] = ""

    notice = lines[(lines["format_issues"] != "") | (lines["warnings"] != "") |
                   ((lines["status"] == "REJECTED") & lines["reason"].str.startswith(("R0", "R1")))]
    notice = view(notice, ["source_row", "closed_at", "vehicle", "slip_raw", "slip_clean", "qty", "format_issues",
                           "warnings", "reason"])
    log = view(lines[(lines["cleaning_notes"] != "") | (lines["match_notes"] != "")],
               ["source_row", "vehicle", "slip_raw", "slip_clean", "invoice_clean", "cleaning_notes", "match_notes"])

    paid = lines[lines["status"].isin(["ACCEPTED", "PARTIAL"])].copy()
    paid["day"] = pd.to_datetime(paid["closed_at"]).dt.date
    vday = (paid.groupby(["client", "vehicle", "day"])["accepted_qty"].sum().reset_index()
            .rename(columns={"client": "Transport agency", "vehicle": "Vehicle", "day": "Day",
                             "accepted_qty": "Accepted litres"}))
    agency = (paid.groupby("client").agg(vehicles=("vehicle", "nunique"), litres=("accepted_qty", "sum"),
                                         days=("day", "nunique")).reset_index())
    if not agency.empty:
        vd = paid.groupby(["client", "vehicle", "day"])["accepted_qty"].sum().groupby("client").mean()
        agency["avg L per vehicle-day"] = agency["client"].map(vd).round(1)
    agency = agency.rename(columns={"client": "Transport agency"})

    return {"Summary": summary, "_breakdown": breakdown, "_reasons": reasons, "Accepted": accepted,
            "Rejected": rejected, "Review": review, "Notify supplier": notice, "Cleaning log": log,
            "Vehicle per day": vday, "By agency": agency,
            "_indicators": indicators(lines), "_match": match_summary(lines),
            "By vehicle": by_vehicle(lines), "Price check": price_check(lines)}


def _style(ws, header_row=1, fill=NAVY):
    for cell in ws[header_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=fill)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    last = min(ws.max_row, header_row + 300)          # sample rows for formats and widths
    for i in range(1, ws.max_column + 1):
        sample = [ws.cell(row=r, column=i).value for r in range(header_row, last + 1)]
        width = max((len(str(v)) for v in sample if v is not None), default=8)
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 60)
        body = [v for v in sample[1:] if v is not None]
        fmt = "#,##0.00" if any(isinstance(v, float) for v in body) else (
            "#,##0" if body and all(isinstance(v, int) for v in body) else None)
        if fmt:
            for (cell,) in ws.iter_rows(min_row=header_row + 1, min_col=i, max_col=i):
                cell.number_format = fmt
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)


def to_excel(lines: pd.DataFrame, meta: dict, settings: Settings, problems: list[str] | None = None) -> bytes:
    tables = build_tables(lines, meta)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        title = meta.get("title") or "Fuel subsidy reimbursement — processing result"
        tables["Summary"].to_excel(xw, sheet_name="Summary", index=False, startrow=2)
        ws = xw.sheets["Summary"]
        ws["A1"] = title
        ws["A1"].font = Font(bold=True, size=14, color=NAVY)
        _style(ws, header_row=3)
        r = len(tables["Summary"]) + 6
        interval = meta.get("interval")
        if interval is not None:
            interval.to_excel(xw, sheet_name="Summary", index=False, startrow=r - 1)
            _style_block(ws, r, NAVY)
            r += len(interval) + 3
        tables["_breakdown"].to_excel(xw, sheet_name="Summary", index=False, startrow=r - 1)
        _style_block(ws, r, BLUE)
        r += len(tables["_breakdown"]) + 3
        tables["_reasons"].to_excel(xw, sheet_name="Summary", index=False, startrow=r - 1)
        _style_block(ws, r, ORANGE)
        r += len(tables["_reasons"]) + 3
        for block, fill in (("_indicators", GREEN), ("_match", BLUE)):
            tables[block].to_excel(xw, sheet_name="Summary", index=False, startrow=r - 1)
            _style_block(ws, r, fill)
            r += len(tables[block]) + 3
        for p in problems or []:
            ws.cell(row=r, column=1, value=f"File note: {p}").font = Font(color="A8550A")
            r += 1
        ws.cell(row=r + 1, column=1, value="Verified by Interministerial Taskforce").font = Font(bold=True)
        ws.cell(row=r + 2, column=1, value="Name / Institution / Signature / Date")

        colors = {"Accepted": GREEN, "Rejected": ORANGE, "Review": BLUE, "Notify supplier": ORANGE}
        for name in ["Accepted", "Rejected", "Review", "Notify supplier", "By vehicle", "Price check",
                     "Cleaning log", "Vehicle per day", "By agency"]:
            tables[name].to_excel(xw, sheet_name=name, index=False)
            _style(xw.sheets[name], fill=colors.get(name, NAVY))

        cfg = pd.DataFrame([(k, str(v)) for k, v in asdict(settings).items()], columns=["Setting", "Value"])
        cfg.to_excel(xw, sheet_name="Settings used", index=False)
        _style(xw.sheets["Settings used"])
    return buf.getvalue()


def _style_block(ws, header_row, fill):
    for cell in ws[header_row]:
        if cell.value is not None:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=fill)


# ---------------------------------------------------------------------------
# Taskforce report for one submission round (all suppliers), for signature
# ---------------------------------------------------------------------------
ROUND_COLUMNS = ["TIN", "Taxpayer name / Fuel supplier", "Period requested", "Number of vehicles",
                 "Fuel consumption claimed (L)", "Subsidies claimed (RWF)", "Quantity accepted (L)",
                 "Quantity pending/rejected (L)", "Subsidies calculated (RWF)", "Amount to reimburse (RWF)",
                 "Account number",
                 "Processing date", "Processor", "Amount to reimburse rejected (RWF)"]


def _n(v) -> float:
    return 0.0 if v is None or pd.isna(v) else float(v)


def round_table(claims: pd.DataFrame) -> pd.DataFrame:
    """Subsidies claimed = the amount requested in the letter (or the claim file when none was given);
    amount to reimburse = the lower of that amount and the subsidies calculated from the accepted lines."""
    rows = []
    for _, c in claims.iterrows():
        s, e = pd.Timestamp(c.interval_start), pd.Timestamp(c.interval_end)
        period = f"{s:%d %b} – {e:%d %b %Y}" if s.year == e.year else f"{s:%d %b %Y} – {e:%d %b %Y}"
        rows.append([c.tin, c["name"], period, int(c.vehicles or 0), round(c.claimed_l or 0, 2),
                     round(_n(c.get("requested_rwf")) or _n(c.claimed_rwf)), round(_n(c.accepted_l), 2),
                     round(_n(c.pending_l) + _n(c.rejected_l), 2),
                     round(_n(c.get("calculated_rwf")) or _n(c.to_reimburse)), round(_n(c.to_reimburse)), c.account,
                     pd.Timestamp(c.processed_at).strftime("%d/%m/%Y") if c.processed_at else "", c.processor,
                     round((c.rejected_rwf or 0) + (c.pending_rwf or 0))])
    t = pd.DataFrame(rows, columns=ROUND_COLUMNS)
    if not t.empty:
        total = {c: "" for c in ROUND_COLUMNS}
        total["Taxpayer name / Fuel supplier"] = "TOTAL"
        for c in ROUND_COLUMNS[3:10] + ROUND_COLUMNS[13:]:
            if c != "Account number":
                total[c] = round(t[c].sum(), 2)
        t = pd.concat([t, pd.DataFrame([total])], ignore_index=True)
    return t


def round_excel(table: pd.DataFrame, title: str, signatories: list[str], approver: str,
                accepted: pd.DataFrame | None = None, rejected: pd.DataFrame | None = None) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        table.to_excel(xw, sheet_name="Report", index=False, startrow=3)
        ws = xw.sheets["Report"]
        ws["A1"] = title
        ws["A1"].font = Font(bold=True, size=14, color=NAVY)
        _style(ws, header_row=4)
        last = 4 + len(table)
        for cell in ws[last]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="EEF3F9")
        r = last + 3
        ws.cell(row=r, column=2, value="Verified by Interministerial Taskforce").font = Font(bold=True)
        for i, item in enumerate(signatories, 1):
            name, signed = (item if isinstance(item, tuple) else (item, None))
            ws.cell(row=r + i, column=2, value=name)
            c = ws.cell(row=r + i, column=6, value=signed or "Signature: ____________________")
            if signed:
                c.font = Font(color=GREEN, bold=True)
        r += len(signatories) + 2
        ws.cell(row=r, column=2, value="Approved by:").font = Font(bold=True)
        name, signed = (approver if isinstance(approver, tuple) else (approver, None))
        ws.cell(row=r + 2, column=2, value=name)
        c = ws.cell(row=r + 2, column=6, value=signed or "Signature: ____________________")
        if signed:
            c.font = Font(color=GREEN, bold=True)
        for name, df, fill in (("Accepted details", accepted, GREEN), ("Rejected details", rejected, ORANGE)):
            if df is not None:
                df.to_excel(xw, sheet_name=name, index=False)
                _style(xw.sheets[name], fill=fill)
    return buf.getvalue()
