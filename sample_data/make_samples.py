"""Build a messy claim file, an EBM extract and a RURA price list for testing.

Run:  python sample_data/make_samples.py
Each claim line's 'expect' (kept only in this script) documents the case.
"""
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

HERE = Path(__file__).parent
SELLER = "100007664"
SDC = "SDC010057290"

# ---------------- EBM extract (one row per item) ----------------------------
ebm = [
    # TIN, ClientsTIN, SdcId, invoice, SdcDateTime, InvoiceType, ItemName, PU, Qty, TaxType
    (SELLER, "106880641", SDC, 10540, "2026-06-07 00:14:10", "NS", "Diesel-Mazout-AGO", 2927, 78.73, "B"),
    (SELLER, "106880641", SDC, 10541, "2026-06-07 00:54:30", "NS", "Diesel-Mazout-AGO", 2927, 69, "B"),
    (SELLER, "106880641", SDC, 10600, "2026-06-08 08:00:00", "NS", "Diesel-Mazout-AGO", 2927, 100, "B"),
    (SELLER, "106880641", SDC, 10601, "2026-06-08 09:00:00", "NS", "Diesel-Mazout-AGO", 2927, 50, "A"),
    (SELLER, "106880641", SDC, 10602, "2026-06-08 10:00:00", "NS", "Gasoline -Petrol-essence-PMS", 2938, 40, "B"),
    (SELLER, "106880641", SDC, 10603, "2026-06-08 11:00:00", "NS", "Diesel-Mazout-AGO", 2700, 60, "B"),
    (SELLER, "106880641", SDC, 10604, "2026-06-08 12:00:00", "NS", "Diesel-Mazout-AGO", 2927, 80, "B"),
    (SELLER, "106880641", SDC, 10604, "2026-06-08 12:30:00", "NR", "Diesel-Mazout-AGO", 2927, 80, "B"),
    (SELLER, "106880641", SDC, 10605, "2026-06-09 10:00:00", "NS", "Diesel-Mazout-AGO", 2927, 45.5, "B"),
    (SELLER, "106880641", SDC, 10606, "2026-06-09 11:00:00", "NS", "Diesel-Mazout-AGO", 2927, 70, "B"),
    (SELLER, "106880641", SDC, 10607, "2026-06-10 06:00:00", "NS", "Diesel-Mazout-AGO", 2927, 220, "B"),
    (SELLER, "106880641", SDC, 10608, "2026-06-10 18:00:00", "NS", "Diesel-Mazout-AGO", 2927, 220, "B"),
    (SELLER, "106880641", SDC, 10609, "2026-06-11 09:00:00", "NS", "Diesel-Mazout-AGO", 2927, 60, "B"),
    (SELLER, "106880641", SDC, 10610, "2026-06-11 09:30:00", "NS", "Diesel-Mazout-AGO", 2927, 55, "B"),
    (SELLER, "106880641", SDC, 10611, "2026-07-02 08:00:00", "NS", "Diesel-Mazout-AGO", 2927, 30, "B"),
    ("100099999", "106880641", "SDC020000001", 10612, "2026-06-12 08:00:00", "NS", "Diesel-Mazout-AGO", 2927, 50, "B"),
    (SELLER, "106880641", SDC, 10613, "2026-06-12 09:00:00", "NS", "Diesel-Mazout-AGO", 2927, 65, "B"),
    (SELLER, "106880641", SDC, 10614, "2026-06-12 10:00:00", "NS", "Diesel-Mazout-AGO", 2927, 40, "B"),
    (SELLER, "106880641", SDC, 10615, "2026-06-12 11:00:00", "NS", "Diesel-Mazout-AGO", 2927, 50, "B"),
    (SELLER, "106880641", SDC, 10615, "2026-06-12 11:00:00", "NS", "Engine oil 1L", 9000, 1, "B"),
    (SELLER, "106880641", SDC, 10616, "2026-06-13 09:00:00", "NS", "Diesel-Mazout-AGO", 2927, 25, "B"),
    # rows from the real EBM sample
    (SELLER, "106880641", "SDC007079204", 5107, "2026-06-11 00:45:30", "NS", "Gasoline -Petrol-essence-PMS", 2938, 50, "B"),
    (SELLER, "107490528", "SDC007079204", 5108, "2026-06-11 00:48:54", "NS", "Diesel-Mazout-AGO", 2927, 69, "B"),
]
rows = []
for tin, ctin, sdc, inv, dt, itype, item, pu, qty, tax in ebm:
    rows.append({"TIN": tin, "ClientsTIN": ctin, "SdcId": sdc, "invoice_number": inv, "SdcDateTime": dt,
                 "InvoiceType": itype, "ItemName": item, "ItemUnitPrice": pu, "ItemQuantity": qty,
                 "ItemTotalPrice": round(pu * qty), "TaxType": tax, "SdcReceiptSignature": "SIG",
                 "TotalAmount": round(pu * qty), "MatchInvoiceAmount": "TRUE",
                 "ItemCode": "RW-2TYXL10-00001", "QuantityUnitCode": "LTR", "PackageUnitCode": "TY"})
pd.DataFrame(rows).to_csv(HERE / "ebm_extract_sample.csv", index=False)

# ---------------- Claim file (supplier format, messy on purpose) --------------
H = ["#", "Site-name", "Client-name", "Closed at", "Vehicle ID", "Card Number", "Product", " Quantity ",
     "P.U", "Amount", "subsidy rate", "subsidy Amount", "Net To be Payed", "Served-by", "EBM Slip No"]
claim = [
    # closed_at, vehicle, product, qty, pu, slip, rate, expect
    ("07/06/2026 00:14", "RAH659I", "AGO - 1x", " 78.73 ", "2,927.00", "SDC010057290/10540", 438, "ACCEPTED (real sample row)"),
    ("07/06/2026 00:54", "RAG840V", "AGO - 1x", "78.45", "2,927.00", "SDC010057290/10541", 438, "PARTIAL 69 L (EBM 69)"),
    ("07/06/2026 00:14", "RAH659I", "AGO - 1x", "78.73", "2927", "SDC010057290/10540", 438, "REJECTED duplicate line"),
    ("08/06/2026 08:01", "rah 100-k", "AGO", "100", "2.927", "sdc010057290 - 010600 ", 438, "ACCEPTED (format repaired)"),
    ("08/06/2026 09:00", "RAB201C", "AGO", "50", "2927", "SDC010057290/10601", 438, "REJECTED exempt A"),
    ("08/06/2026 10:00", "RAB202C", "AGO", "40", "2938", "SDC010057290/10602", 438, "REJECTED product mismatch"),
    ("08/06/2026 11:00", "RAB203C", "AGO", "60", "2700", "SDC010057290/10603", 438, "REJECTED under RURA price"),
    ("08/06/2026 12:00", "RAB204C", "AGO", "80", "2927", "SDC010057290/10604", 438, "REJECTED refunded"),
    ("06/09/2026 10:00", "RAB205C", "AGO", "45,5", "2927", "", 438, "REVIEW found by date/qty, date mm/dd"),
    ("09/06/2026 11:00", "RAB206C", "AGO", "70", "2927", "SDCO10057290/010606", 438, "ACCEPTED (O->0, zeros)"),
    ("10/06/2026 06:00", "RAC552I", "AGO", "220", "2927", "SDC010057290/10607", 438, "REVIEW 440 L/day"),
    ("10/06/2026 18:00", "RAC552I", "AGO", "220", "2927", "SDC010057290/10608", 438, "REVIEW 440 L/day"),
    ("11/06/2026 09:00", "RAD112K", "AGO", "60", "2927", "SDC010057290/10609", 438, "ACCEPTED"),
    ("11/06/2026 09:30", "RAD112K", "AGO", "55", "2927", "SDC010057290/10610", 438, "REVIEW refill after 30 min"),
    ("02/07/2026 08:00", "RAB207C", "AGO", "30", "2927", "SDC010057290/10611", 438, "REJECTED outside period"),
    ("12/06/2026 08:00", "RAB208C", "AGO", "50", "2927", "SDC020000001/10612", 438, "REJECTED other seller TIN"),
    ("12/06/2026 09:00", "RAB209C", "AGO", "65", "2927", "SDC01005729/10613", 438, "ACCEPTED (8-digit SDC fixed)"),
    ("12/06/2026 10:00", "RAB210C", "AGO", "40", "2927", "SDC010057299/10614", 438, "ACCEPTED (SDC typo fixed)"),
    ("12/06/2026 11:00", "RAB211C", "AGO", "50", "2927", "SDC010057290/10615", 438, "ACCEPTED (oil item ignored)"),
    ("12/06/2026 12:00", "RAB212C", "AGO", "35", "2927", "SDC010057290/19999", 438, "REJECTED not in EBM"),
    ("12/06/2026 13:00", "RAB771Q", "AGO", "33.33", "2927", "-", 438, "REJECTED no slip, no match"),
    ("11/06/2026 00:48", "RAG900A", "AGO", "69", "2927", "SDC007079204/5108", 438, "REVIEW buyer TIN differs from client usual (R10)"),
    ("07/06/2026 01:10", "RAD300B", "AGO", "60.20", "2927", "SDC010057290/10541", 438, "REJECTED invoice already used"),
    (46185.5, "RAB213C", "PMS", "50", "2938", "SDC007079204-5107", 500, "REVIEW rate 500 ≠ 438 (Excel date)"),
    ("30/07/2026 09:00", "RAB214C", "AGO", "25", "2927", "SDC010057290/10616", 438, "REVIEW Closed at outside interval, EBM inside"),
    ("15/07/2026 10:00", "RAB215C", "AGO", "20", "2927", "SDC010057290/19998", 438, "REJECTED Closed at outside interval, no EBM"),
]
wb = Workbook()
ws = wb.active
ws.append(["FUEL SUBSIDY CLAIM — SAMPLE OMC"])
ws.append(["Period: 01/06/2026 - 30/06/2026"])
ws.append([])
ws.append(H)
for n, (dt, veh, prod, qty, pu, slip, rate, _) in enumerate(claim, 1):
    q = float(str(qty).replace(",", ".").strip())
    p = 2927 if pu == "2.927" else float(str(pu).replace(",", ""))
    amount = round(q * p)
    sub = round(q * rate, 2)
    ws.append([n, "RWAMAGANA-FORECOURT", "Stella Express Ltd", dt, veh, "19xxxxxxxxxx3686", prod, qty, pu,
               f"{amount:,}", rate, sub, round(amount - sub, 2), "Eric Harerimana", slip])
ws.append([])
ws.append(["", "TOTAL", "", "", "", "", "", "", "", "", "", "", "", "", ""])
wb.save(HERE / "claim_sample.xlsx")

pd.DataFrame([{"product": "DIESEL", "effective_from": "2026-06-01", "price": 2927},
              {"product": "PETROL", "effective_from": "2026-06-01", "price": 2938}]).to_csv(HERE / "rura_prices.csv", index=False)

pd.DataFrame([(i + 1, c[-1]) for i, c in enumerate(claim)], columns=["row", "expect"]).to_csv(HERE / "expected.csv", index=False)
print("Sample files written to", HERE)
