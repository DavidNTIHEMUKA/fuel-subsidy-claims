"""IKWIM-shaped run: 875 lines, July 06-12, mm/dd/yyyy dates, real EBM 2.1 layout (synthetic data)."""
import io

import numpy as np
import pandas as pd

from engine.indicators import indicators, match_summary
from engine.pipeline import process


def _ikwim_like():
    rng = np.random.default_rng(7)
    SELLER = "101968859"
    sites = {"NYAMATA-FORECOURT": "SDC010192402", "FREEZONE-FORECOURT": "SDC010193766", "KICUKIRO-FORECOURT": "SDC010161033"}
    ops = {"Metro Tours Ltd": "102929604", "Star Express Ltd": "100428731", "Stella Express Ltd": "106880641",
           "Volcano Express": "101234567", "Ritco Ltd": "103456789"}
    plates = [f"RA{c}{n:03d}{s}" for c, n, s in zip(rng.choice(list("BCDJ"), 135), rng.integers(100, 999, 135), rng.choice(list("ABCDHKLMNQR"), 135))]
    plate_op = {p: list(ops)[i % 5] for i, p in enumerate(plates)}
    t0 = pd.Timestamp("2026-07-06")
    claim, ebm = [], []
    counter = {s: 2000 for s in sites.values()}
    for i in range(875):
        site = rng.choice(list(sites)); sdc = sites[site]; counter[sdc] += 1
        p = rng.choice(plates); q = round(float(np.clip(rng.normal(58.4, 16), 3, 98.4)), 2)
        when = t0 + pd.Timedelta(minutes=int(rng.integers(0, 7 * 24 * 60 - 1)))
        claim.append({"#": i + 1, "Site-name": site, "Client-name": plate_op[p], "Closed at": when.strftime("%m/%d/%Y %H:%M"),
                      "Vehicle ID": p, "Card Number": "19xxxxxxxxxx3705", "Product": "AGO - 1x", " Quantity ": q,
                      "P.U": "2,927.00", "Amount": f"{round(q*2927):,}", "subsidy rate": 438,
                      "subsidy Amount": f"{q*438:,.2f}", "Net To be Payed": f"{q*2927-q*438:,.2f}",
                      "Served-by": "Agnès Uwase", "EBM Slip No": f"{sdc}/{counter[sdc]}"})
        if i >= 30:   # first 30 slips are not in EBM
            ebm.append({"TIN": SELLER, "ClientsTIN": ops[plate_op[p]], "SdcId": sdc, "SdcReceiptTypeCounter": counter[sdc],
                        "SdcDateTime": (when + pd.Timedelta(seconds=40)).to_pydatetime(), "WasReported": None, "HasSignature": None,
                        "HasItemsBlock": None, "InvoiceType": "ebm2.1", "ItemName": "Mazout", "ItemUnitPrice": 2927,
                        "ItemQuantity": q + 0.000147, "ItemTotalPrice": q * 2927, "TaxType": "B",
                        "SdcReceiptSignature": f"SIG{i}", "MatchInvoiceAmount": True, "ItemCode": "RW3CYXLTR0000001",
                        "QuantityUnitCode": "LTR", "PackageUnitCode": "CY"})
    claim.append(dict(claim[500], **{"#": 876}))          # one slip claimed twice
    ebm.append(dict(ebm[100]))                              # one duplicated EBM row
    for k in range(1050):                                   # other EBM traffic: wholesale + other customers
        sdc = "SDC010002825"; counter.setdefault(sdc, 1000); counter[sdc] += 1
        big = k % 7 == 0
        ebm.append({"TIN": SELLER, "ClientsTIN": "999999999" if not big else "994325096", "SdcId": sdc,
                    "SdcReceiptTypeCounter": counter[sdc], "SdcDateTime": (t0 + pd.Timedelta(hours=k % 160)).to_pydatetime(),
                    "InvoiceType": "ebm2.1", "ItemName": "Mazout" if big else "Essence", "ItemUnitPrice": 2050 if big else 2938,
                    "ItemQuantity": 50000 if big else 1556.3077, "ItemTotalPrice": 1.0, "TaxType": "A" if big else "B",
                    "SdcReceiptSignature": f"W{k}", "MatchInvoiceAmount": True})
    cdf = pd.DataFrame(claim); edf = pd.DataFrame(ebm)
    return cdf, edf


def test_ikwim_shaped_claim():
    cdf, edf = _ikwim_like()
    cb = io.BytesIO(cdf.to_csv(index=False).encode("latin-1")); cb.name = "IKWIM-SUBSIDY REPORT.csv"
    eb = io.BytesIO(); edf.to_excel(eb, index=False); eb.seek(0); eb.name = "extracted-ebm-items IKWIM.xlsx"
    lines, problems, xlsx = process(cb, eb, {"tin": "101968859", "period_start": "2026-07-06",
                                             "period_end": "2026-07-12"})
    assert any("month/day/year" in p for p in problems)
    assert pd.to_datetime(lines.closed_at).dt.month.eq(7).all()          # 07/09/2026 = 9 July
    reasons = lines.reason.str.extract(r"(R\d+)")[0].value_counts().to_dict()
    assert reasons == {"R1": 30, "R2": 1}                               # 30 missing slips, 1 slip claimed twice
    m = dict(match_summary(lines).values)
    assert m["Matched to EBM by slip number"] == 846 and m["Not found in EBM"] == 30
    ind = indicators(lines).set_index("Group")
    assert ind.loc["All claimed", "Operators (buyer TINs)"] == 5
    assert xlsx[:2] == b"PK"
