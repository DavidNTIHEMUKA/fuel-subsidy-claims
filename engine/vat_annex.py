"""Appeal review: is the EBM sale behind each appealed line declared in the sales annex of the OMC's VAT declaration?

The annex is matched, in this order:
  1. by the EBM receipt (SDC ID + receipt number, or an invoice number carrying both) — exact;
  2. by buyer TIN + invoice date + amount (±1 % or ±100 RWF) — when the annex has no receipt number.
The column names are matched loosely (case, spaces, symbols), like the claim and EBM files.
"""
import pandas as pd

from engine.cleaning import merge_key, normalize_slip, normalize_tin, parse_datetime, parse_number, read_table

ANNEX_COLUMNS = {
    "seller_tin": ["sellertin", "tinofseller", "declaranttin", "suppliertin", "taxpayertin", "tin"],
    "buyer_tin": ["buyertin", "tinofbuyer", "clienttin", "clientstin", "customertin", "purchasertin", "tinofclient",
                  "tinofcustomer"],
    "buyer_name": ["buyername", "nameofbuyer", "clientname", "customername", "purchasername"],
    "sdc_id": ["sdcid", "sdc", "sdcnumber", "ebmsdcid"],
    "receipt": ["receiptnumber", "receiptno", "sdcreceipttypecounter", "sdcreceiptnumber", "ebmreceiptnumber",
                "ebmreceipt", "receipt", "invoicenumber", "invoiceno", "invoice", "ebmnumber", "ebmslipno"],
    "date": ["invoicedate", "receiptdate", "salesdate", "date", "sdcdatetime", "transactiondate"],
    "amount": ["amountinclvat", "totalamountinclvat", "totalinclvat", "invoiceamount", "matchinvoiceamount",
               "totalamount", "amount", "salesamount", "taxableamount", "amountexclvat", "itemtotalprice",
               "totalprice", "value"],
    "item_name": ["itemname", "item", "product", "description"],
    "period": ["period", "taxperiod", "declarationperiod", "month", "returnperiod"],
}
ANNEX_REQUIRED = ["date"]


def read_annex(file):
    raw, problems = read_table(file, ANNEX_COLUMNS, ANNEX_REQUIRED, "VAT annex")
    if raw.empty:
        return pd.DataFrame(), problems
    df = pd.DataFrame(index=raw.index)
    df["seller_tin"] = raw.get("seller_tin", pd.Series("", index=raw.index)).map(lambda v: normalize_tin(v) or "")
    df["buyer_tin"] = raw.get("buyer_tin", pd.Series("", index=raw.index)).map(lambda v: normalize_tin(v) or "")
    df["date"] = raw["date"].map(lambda v: parse_datetime(v)[0])
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df["amount"] = raw.get("amount", pd.Series("", index=raw.index)).map(lambda v: _num(v))
    df["period"] = raw.get("period", pd.Series("", index=raw.index)).astype(str)
    df["key"] = [_key(s, r) for s, r in zip(raw.get("sdc_id", pd.Series("", index=raw.index)),
                                            raw.get("receipt", pd.Series("", index=raw.index)))]
    df["source_row"] = raw.index + 2
    # the annex has the same layout as an EBM extract: one row per item — add the items up per receipt
    keyed = df[df.key != ""]
    if keyed.key.duplicated().any():
        g = keyed.groupby("key", as_index=False).agg(seller_tin=("seller_tin", "first"), buyer_tin=("buyer_tin", "first"),
                                                     date=("date", "first"), amount=("amount", "sum"),
                                                     period=("period", "first"), source_row=("source_row", "first"))
        df = pd.concat([g, df[df.key == ""]], ignore_index=True)
    if (df["key"] == "").all() and df["buyer_tin"].eq("").all():
        problems.append("The annex has neither receipt numbers nor buyer TINs: lines can only be matched by date and "
                        "amount, which is weak evidence.")
    return df, problems


def _num(v):
    return parse_number(v, "amount")[0]


def _key(sdc, receipt) -> str:
    sdc, receipt = str(sdc or "").strip(), str(receipt or "").strip()
    if not receipt and not sdc:
        return ""
    sl = normalize_slip(f"{sdc}/{receipt}" if sdc and receipt else (receipt or sdc))
    return merge_key(sl.key) if sl.key else ""


def check(analysis: pd.DataFrame, annex: pd.DataFrame, omc_tin: str | None = None) -> pd.DataFrame:
    """Add vat_status, vat_match, vat_period, vat_amount to the appeal analysis (one row per appealed line)."""
    out = analysis.copy()
    a = annex.copy()
    if omc_tin and (a.seller_tin != "").any():
        a = a[(a.seller_tin == "") | (a.seller_tin == str(omc_tin))]
    by_key = {k: i for i, k in zip(a.index, a.key) if k}
    status, how, period, amount = [], [], [], []
    for r in out.itertuples():
        key = merge_key(getattr(r, "matched_key", "") or "")
        if not key:
            status.append("No EBM sale to look for"); how.append(""); period.append(""); amount.append(None)
            continue
        i = by_key.get(key)
        if i is None:                       # fallback: buyer TIN + date + amount
            d = pd.to_datetime(getattr(r, "ebm_date", None), errors="coerce")
            amt = pd.to_numeric(getattr(r, "ebm_amount", None), errors="coerce")
            buyer = str(getattr(r, "ebm_buyer_tin", "") or "")
            if pd.notna(d):
                c = a[a.date == d.normalize()]
                if buyer and (c.buyer_tin != "").any():
                    c = c[c.buyer_tin == buyer]
                if pd.notna(amt) and amt:
                    c = c[(c.amount - amt).abs() <= max(100.0, 0.01 * amt)]
                if len(c) == 1:
                    i = c.index[0]
                    how.append("buyer TIN + date + amount" if buyer else "date + amount")
                elif len(c) > 1:
                    status.append("Several possible lines in the annex"); how.append(f"{len(c)} candidates")
                    period.append(""); amount.append(None)
                    continue
            if i is None:
                status.append("Not in the VAT annex"); how.append(""); period.append(""); amount.append(None)
                continue
        else:
            how.append("EBM receipt number")
        status.append("Declared in the VAT annex")
        period.append(a.at[i, "period"] if a.at[i, "period"] not in ("", "nan") else
                      (f"{a.at[i, 'date']:%m/%Y}" if pd.notna(a.at[i, "date"]) else ""))
        amount.append(a.at[i, "amount"])
    out["vat_status"], out["vat_match"], out["vat_period"], out["vat_amount"] = status, how, period, amount
    return out
