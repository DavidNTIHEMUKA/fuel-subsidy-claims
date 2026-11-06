"""Cleaning and harmonisation for OMC claim files and EBM extracts.

Principle: a line is never rejected because of how a value was *written*.
Every repair is recorded in a cleaning note so the analyst can see what was
changed, and only values that cannot be repaired become data-quality issues
sent back to the supplier.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from .config import DEFAULT, Settings

# ---------------------------------------------------------------------------
# Generic text helpers
# ---------------------------------------------------------------------------
_EMPTY = {"", "-", "--", "–", "—", "NAN", "NONE", "NULL", "N/A", "NA", "#N/A", "NIL", "0.0"}
_SPACES = re.compile(r"[    ​﻿]")
_DASHES = re.compile(r"[‐-―−]")


def clean_text(value) -> str:
    """String form of any cell value: no exotic spaces, trimmed, '' for empty."""
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():  # 10540.0 -> "10540"
            return str(int(value))
    s = str(value)
    s = _SPACES.sub(" ", s)
    s = _DASHES.sub("-", s)
    s = s.replace("／", "/").replace("\\", "/")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_empty(value) -> bool:
    return clean_text(value).upper() in _EMPTY - {"0.0"}


def header_key(name) -> str:
    """'Net To be Payed ' -> 'nettobepayed'; 'P.U' -> 'pu'."""
    return re.sub(r"[^a-z0-9#]", "", clean_text(name).lower())


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
_PLAIN_THOUSANDS_COMMA = re.compile(r"^-?\d{1,3}(,\d{3})+$")
_PLAIN_THOUSANDS_DOT = re.compile(r"^-?\d{1,3}(\.\d{3}){2,}$")
_PLAIN_THOUSANDS_SPACE = re.compile(r"^-?\d{1,3}( \d{3})+([.,]\d+)?$")
_UNITS = re.compile(r"(RWF|FRW|RFW|FRS|LTRS?|LITRES?|LITERS?|LTR|\bL\b)", re.I)


def parse_number(value, kind: str = "generic", settings: Settings = DEFAULT):
    """Return (float | None, note | None).

    kind: 'qty', 'price', 'amount', 'rate' or 'generic' — used only to settle
    genuinely ambiguous writings such as '2.927' or '78,730'.
    """
    if value is None or isinstance(value, bool):
        return None, None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None, None
        return round(float(value), 6), None

    raw = clean_text(value)
    if raw.upper() in _EMPTY - {"0.0"}:
        return None, None

    s = _UNITS.sub("", raw).strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s.endswith("-"):
        negative, s = True, s[:-1].strip()
    if s.startswith("-"):
        negative, s = True, s[1:].strip()
    s = s.replace("'", "").replace("’", "")

    note = None
    if _PLAIN_THOUSANDS_SPACE.match(s):
        s = s.replace(" ", "")
    s = s.replace(" ", "")
    s = re.sub(r"[^0-9.,]", "", s)
    if not s or not re.search(r"\d", s):
        return None, f"'{raw}' is not a number"

    if "," in s and "." in s:
        # whichever separator comes last is the decimal separator
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if _PLAIN_THOUSANDS_COMMA.match(s):
            as_thousands = float(s.replace(",", ""))
            as_decimal = float(s.replace(",", ".", 1)) if s.count(",") == 1 else None
            if kind == "qty" and as_decimal is not None and as_thousands > 2000 >= as_decimal:
                s = s.replace(",", ".")
                note = f"'{raw}' read as decimal litres"
            else:
                s = s.replace(",", "")
        elif s.count(",") == 1:
            s = s.replace(",", ".")
            note = f"decimal comma in '{raw}'"
        else:
            return None, f"'{raw}' has an unreadable number format"
    elif "." in s:
        if _PLAIN_THOUSANDS_DOT.match(s):
            s = s.replace(".", "")
            note = f"dots read as thousands in '{raw}'"
        elif s.count(".") > 1:
            return None, f"'{raw}' has an unreadable number format"
        else:
            whole, frac = s.split(".")
            if (kind == "price" and len(frac) == 3 and len(whole) <= 2
                    and settings.min_plausible_price <= float(whole + frac) <= settings.max_plausible_price):
                s = whole + frac
                note = f"price '{raw}' read as {int(float(s)):,} RWF"
    try:
        number = float(s)
    except ValueError:
        return None, f"'{raw}' is not a number"
    if negative:
        number = -number
    return round(number, 6), note


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
_DAYFIRST_FORMATS = [
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
    "%d/%m/%y %H:%M", "%d/%m/%y",
]
_ISO_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S.%f",
]


def parse_datetime(value, dayfirst: bool = True):
    """Return (Timestamp | None, swapped_alternative | None, note | None).

    When day and month are both <= 12 the day/month-swapped reading is also
    returned, so matching can fall back to it instead of rejecting.
    """
    if value is None:
        return None, None, None
    if isinstance(value, pd.Timestamp):
        return (None, None, None) if pd.isna(value) else (value, None, None)
    if isinstance(value, datetime):
        return pd.Timestamp(value), None, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and math.isnan(value):
            return None, None, None
        if 20_000 < value < 80_000:  # Excel serial date
            return pd.Timestamp(datetime(1899, 12, 30) + timedelta(days=float(value))).round("s"), None, "Excel serial date converted"
        return None, None, f"'{value}' is not a date"

    raw = clean_text(value)
    if raw.upper() in _EMPTY:
        return None, None, None
    s = re.sub(r"\s*([/.:-])\s*", r"\1", raw)
    s = re.sub(r"(\d)(AM|PM)$", r"\1 \2", s, flags=re.I)

    serial, _ = parse_number(s)
    if serial is not None and re.fullmatch(r"\d{5}(\.\d+)?", s):
        return parse_datetime(serial)

    formats = (_DAYFIRST_FORMATS + _ISO_FORMATS) if dayfirst else (_ISO_FORMATS + _DAYFIRST_FORMATS)
    for fmt in formats:
        try:
            ts = pd.Timestamp(datetime.strptime(s, fmt))
        except ValueError:
            continue
        alt = None
        if fmt in _DAYFIRST_FORMATS and ts.day <= 12 and ts.day != ts.month:
            try:
                alt = ts.replace(day=ts.month, month=ts.day)
            except ValueError:
                alt = None
        return ts, alt, None
    try:
        ts = pd.to_datetime(s, dayfirst=dayfirst)
        return ts, None, f"date '{raw}' read as {ts:%d/%m/%Y %H:%M}"
    except (ValueError, TypeError):
        return None, None, f"'{raw}' is not a date"


# ---------------------------------------------------------------------------
# EBM slip number -> SdcId | invoice_number
# ---------------------------------------------------------------------------
@dataclass
class Slip:
    sdc_id: str | None
    invoice: str | None
    status: str          # OK | FIXED | MISSING | INCOMPLETE | INVALID
    note: str | None = None

    @property
    def key(self) -> str | None:
        if self.sdc_id and self.invoice:
            return f"{self.sdc_id}|{self.invoice}"
        return None


_LOOKALIKE = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1"})
_SDC_RE = re.compile(r"S\s*[DO0]\s*C\s*[-_:#./]*\s*([0-9OQIL|][0-9OQIL| ]{6,14})")


def normalize_sdc_id(value) -> str | None:
    """'sdc 010-057-290', 'SDCO10057290', 10057290 -> 'SDC010057290'."""
    s = clean_text(value).upper()
    if not s:
        return None
    m = _SDC_RE.search(s.replace("-", ""))
    digits = m.group(1) if m else s
    digits = re.sub(r"\s", "", digits).translate(_LOOKALIKE)
    digits = re.sub(r"\D", "", digits)
    if not digits:
        return None
    if len(digits) < 9:
        digits = digits.zfill(9)
    return "SDC" + digits[:9]


def normalize_invoice(value) -> str | None:
    s = clean_text(value)
    if not s:
        return None
    num, _ = parse_number(s)
    if num is not None and float(num).is_integer() and num > 0:
        return str(int(num))
    digits = re.sub(r"\D", "", s).lstrip("0")
    return digits or None


def normalize_slip(value) -> Slip:
    """Harmonise a supplier's 'EBM Slip No' into the EBM key SdcId|invoice."""
    raw = clean_text(value)
    if raw.upper() in _EMPTY:
        return Slip(None, None, "MISSING", "EBM Slip No is empty")
    s = raw.upper()
    notes = []

    m = _SDC_RE.search(s)
    sdc_digits = None
    rest = s
    if m:
        block = re.sub(r"\s", "", m.group(1))
        mapped = block.translate(_LOOKALIKE)
        if mapped != block and re.sub(r"\D", "", block) != re.sub(r"\D", "", mapped):
            notes.append("letters O/I/L in SDC ID read as 0/1")
        digits = re.sub(r"\D", "", mapped)
        rest = s[: m.start()] + " " + s[m.start() + len(m.group(0)):]
        if len(digits) > 9:
            # invoice glued to the SDC ID: SDC01005729010540
            glued = digits[9:]
            digits = digits[:9]
            rest = glued + " " + rest
            notes.append("invoice number was glued to the SDC ID")
        elif len(digits) == 8:
            digits = digits.zfill(9)
            notes.append("SDC ID had 8 digits; leading zero assumed, checked against EBM SDC IDs")
        elif len(digits) < 8:
            return Slip(None, None, "INVALID", f"SDC ID in '{raw}' has only {len(digits)} digits (needs 9)")
        sdc_digits = digits
    groups = re.findall(r"\d+", rest)

    if sdc_digits is None:
        nine = [g for g in groups if len(g) == 9]
        if nine:
            sdc_digits = nine[0]
            groups.remove(nine[0])
            notes.append("'SDC' prefix added")
        elif len(groups) == 1 and len(groups[0]) > 9:
            sdc_digits, groups = groups[0][:9], [groups[0][9:]]
            notes.append("'SDC' prefix added; invoice split from SDC ID")
        elif groups:
            return Slip(None, normalize_invoice(groups[0]), "INCOMPLETE", f"'{raw}' has no SDC ID")
        else:
            return Slip(None, None, "INVALID", f"'{raw}' is not an EBM slip number")

    sdc = "SDC" + sdc_digits
    groups = [g for g in groups if g.lstrip("0")]
    if not groups:
        return Slip(sdc, None, "INCOMPLETE", f"invoice number missing after {sdc}")
    if len(groups) > 1:
        notes.append(f"several numbers after the SDC ID; used {groups[0].lstrip('0')}")
    invoice = groups[0].lstrip("0")
    if groups[0] != invoice:
        notes.append("leading zeros removed from invoice number")

    canonical = f"{sdc}/{invoice}"
    changed = bool(notes) or re.sub(r"\s", "", s) != canonical
    if changed and not notes:
        notes.append(f"reformatted to {canonical}")
    return Slip(sdc, invoice, "FIXED" if changed else "OK", "; ".join(notes) or None)


def merge_key(value) -> str:
    """Invoice key for merging, without any symbol: 'SDC010057290|10540' or
    'SDC010057290/10540' -> 'SDC01005729010540'. The SDC ID is always normalised to
    9 digits first, so joining SDC ID and invoice number stays unambiguous."""
    s = clean_text(value).upper()
    return re.sub(r"[^A-Z0-9]", "", s)


def slip_merge_key(raw) -> str:
    """Cleaned EBM Slip No without symbols, comparable with the EBM merge key."""
    sl = normalize_slip(raw)
    return merge_key(sl.key) if sl.key else merge_key(raw)


# ---------------------------------------------------------------------------
# Other identifiers
# ---------------------------------------------------------------------------
_PLATE_OK = re.compile(r"^(R[A-Z]{2}\d{3}[A-Z]|GR\d{3}[A-Z]|[A-Z]{2,3}\d{3,4}[A-Z]?)$")


def normalize_plate(value):
    raw = clean_text(value).upper()
    plate = re.sub(r"[^A-Z0-9]", "", raw)
    if not plate:
        return None, "Vehicle ID is empty"
    note = None
    if not _PLATE_OK.match(plate):
        note = f"unusual plate format '{raw}'"
    return plate, note


def normalize_tin(value):
    s = clean_text(value)
    if not s:
        return None
    num, _ = parse_number(s)
    if num is not None and float(num).is_integer():
        s = str(int(num))
    digits = re.sub(r"\D", "", s)
    return digits or None


def normalize_card(value):
    s = clean_text(value).upper().replace(" ", "")
    return s or None


_DIESEL = ("AGO", "DIESEL", "GASOIL", "GAS OIL", "MAZOUT", "GASOLE")
_PETROL = ("PMS", "PETROL", "GASOLINE", "ESSENCE", "SUPER", "PREMIUM", "MOGAS")
_KEROSENE = ("KEROSENE", "DPK", "JET", "PETROLE")


def normalize_product(value):
    s = clean_text(value).upper()
    if not s:
        return None
    hits = set()
    if any(k in s for k in _DIESEL):
        hits.add("DIESEL")
    if any(k in s for k in _PETROL):
        hits.add("PETROL")
    if any(k in s for k in _KEROSENE) and not hits:
        hits.add("KEROSENE")
    if len(hits) == 1:
        return hits.pop()
    return "UNKNOWN"


def normalize_bool(value):
    s = clean_text(value).upper()
    if s in {"TRUE", "1", "YES", "Y", "T", "VRAI"}:
        return True
    if s in {"FALSE", "0", "NO", "N", "F", "FAUX"}:
        return False
    return None


# ---------------------------------------------------------------------------
# Reading files: header detection and column mapping
# ---------------------------------------------------------------------------
CLAIM_COLUMNS = {
    "row_no": ["#", "no", "n", "sn", "sno", "rowno"],
    "site": ["sitename", "site", "station", "forecourt", "stationname"],
    "client": ["clientname", "client", "customer", "transporter", "agency", "company"],
    "omc_tin": ["omctin", "omctinno", "suppliertin", "sellertin", "tinomc", "tinofomc", "tinofsupplier",
                "fuelsuppliertin", "stationtin", "omc"],
    "closed_at": ["closedat", "closedtime", "date", "datetime", "transactiondate", "transactiontime", "dateclosed"],
    "vehicle": ["vehicleid", "vehicle", "plate", "plateno", "platenumber", "vehicleplate", "vehicleno", "immatriculation"],
    "card": ["cardnumber", "card", "cardno", "fuelcard"],
    "product": ["product", "fueltype", "fuel", "item", "productname"],
    "qty": ["quantity", "qty", "litres", "liters", "volume", "quantityl", "quantityltr", "qtyl"],
    "unit_price": ["pu", "unitprice", "price", "priceperlitre", "priceperliter", "prixunitaire"],
    "amount": ["amount", "totalamount", "value", "total", "amountrwf"],
    "subsidy_rate": ["subsidyrate", "rate", "subsidyperlitre", "subsidyperliter"],
    "subsidy_amount": ["subsidyamount", "subsidy", "subsidyrwf"],
    "net_payable": ["nettobepayed", "nettobepaid", "netpayable", "net", "netamount"],
    "served_by": ["servedby", "attendant", "cashier", "pumpattendant"],
    "slip": ["ebmslipno", "ebmslip", "ebmslipnumber", "ebmreceipt", "ebmreceiptno", "ebminvoice",
             "ebminvoiceno", "slipno", "receiptno", "ebmno", "invoiceno"],
}
CLAIM_REQUIRED = ["closed_at", "vehicle", "product", "qty", "unit_price", "slip"]

EBM_COLUMNS = {
    "seller_tin": ["tin", "sellertin", "suppliertin"],
    "buyer_tin": ["clientstin", "clienttin", "buyertin", "customertin"],
    "sdc_id": ["sdcid", "sdc"],
    # EBM 2.1 extracts have no invoice_number: the receipt counter is the number on the slip
    "invoice": ["invoicenumber", "invoiceno", "invoice", "sdcreceipttypecounter", "receipttypecounter",
                "sdcreceiptcounter", "receiptcounter", "rcptcounter", "receiptnumber", "rcptno"],
    "sdc_datetime": ["sdcdatetime", "datetime", "invoicedate", "date"],
    "invoice_type": ["invoicetype", "receipttype"],
    "item_name": ["itemname", "item", "product"],
    "item_unit_price": ["itemunitprice", "unitprice", "price"],
    "item_qty": ["itemquantity", "quantity", "qty"],
    "item_total": ["itemtotalprice", "itemtotal"],
    "tax_type": ["taxtype", "tax"],
    "signature": ["sdcreceiptsignature", "receiptsignature", "signature"],
    "total_amount": ["totalamount", "total"],
    "match_amount": ["matchinvoiceamount"],
    "item_code": ["itemcode"],
    "unit_code": ["quantityunitcode"],
}
EBM_REQUIRED = ["sdc_id", "invoice", "item_name", "item_qty", "item_unit_price"]


def _map_headers(headers, spec):
    keys = [header_key(h) for h in headers]
    mapping = {}
    for field_name, aliases in spec.items():
        for i, k in enumerate(keys):
            if i in mapping.values():
                continue
            if k in aliases:
                mapping[field_name] = i
                break
    return mapping


def read_table(path_or_buffer, spec, required, name="file", max_scan=30):
    """Read Excel/CSV as text, find the header row, rename to standard names.

    Returns (DataFrame, list_of_problems). Everything is read as text so
    TINs, SDC IDs and invoice numbers keep their leading zeros.
    """
    fname = str(getattr(path_or_buffer, "name", path_or_buffer)).lower()
    if fname.endswith((".csv", ".txt")):
        raw = None
        for enc in ("utf-8-sig", "latin-1"):
            for sep in (",", ";", "\t", "|"):
                try:
                    if hasattr(path_or_buffer, "seek"):
                        path_or_buffer.seek(0)
                    trial = pd.read_csv(path_or_buffer, header=None, dtype=str, sep=sep,
                                        keep_default_na=False, encoding=enc, engine="python")
                except Exception:
                    continue
                if trial.shape[1] > 3:
                    raw = trial
                    break
            if raw is not None:
                break
        if raw is None:
            return pd.DataFrame(), [f"{name}: could not read the CSV file"]
    else:
        raw = pd.read_excel(path_or_buffer, header=None, dtype=object)

    best_row, best_hits, best_map = None, 0, {}
    for r in range(min(max_scan, len(raw))):
        mapping = _map_headers(raw.iloc[r].tolist(), spec)
        if len(mapping) > best_hits:
            best_row, best_hits, best_map = r, len(mapping), mapping
    if best_row is None or best_hits < 3:
        return pd.DataFrame(), [f"{name}: no header row found (expected columns like {', '.join(required)})"]

    body = raw.iloc[best_row + 1:].reset_index(drop=True)
    out = pd.DataFrame({f: body.iloc[:, i] for f, i in best_map.items()})
    out["source_row"] = body.index + best_row + 2  # 1-based Excel row number
    problems = [f"{name}: required column '{c}' not found" for c in required if c not in best_map]

    # Drop blank rows and total/signature rows below the table
    def _is_data(row):
        vals = [clean_text(row[f]) for f in best_map]
        filled = sum(1 for v in vals if v)
        joined = " ".join(vals).upper()
        if filled <= 2:
            return False
        if re.search(r"\bTOTAL\b|VERIFIED BY|APPROVED BY", joined):
            return False
        return True

    out = out[out.apply(_is_data, axis=1)].reset_index(drop=True)
    preamble = [" ".join(clean_text(v) for v in raw.iloc[r].tolist() if clean_text(v)) for r in range(best_row)]
    out.attrs["preamble"] = " | ".join(p for p in preamble if p)
    return out, problems


# ---------------------------------------------------------------------------
# Consumption interval declared by the supplier
# ---------------------------------------------------------------------------
_MONTHS = {
    "jan": 1, "january": 1, "janvier": 1, "feb": 2, "february": 2, "fevrier": 2, "février": 2,
    "mar": 3, "march": 3, "mars": 3, "apr": 4, "april": 4, "avril": 4, "may": 5, "mai": 5,
    "jun": 6, "june": 6, "juin": 6, "jul": 7, "july": 7, "juillet": 7, "aug": 8, "august": 8,
    "aout": 8, "août": 8, "sep": 9, "sept": 9, "september": 9, "septembre": 9, "oct": 10,
    "october": 10, "octobre": 10, "nov": 11, "november": 11, "novembre": 11, "dec": 12,
    "december": 12, "decembre": 12, "décembre": 12,
}
_NUM_DATE = r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}"
_SEP = r"\s*(?:-|–|—|to|au|until|jusqu'au|→)\s*"
_WORD_RANGE = re.compile(
    r"(\d{1,2})\s*([A-Za-zéû]+)?\.?\s*(\d{4})?" + _SEP + r"(\d{1,2})\s*([A-Za-zéû]+)\.?\s*(\d{4})?", re.I)


def parse_interval(text, default_year: int | None = None):
    """Read a consumption interval such as '01/06/2026 - 30/06/2026',
    '21 - 30 Sept 2026', '28 Sept - 04 Oct 2026' or '29 June - 30 Sept'.

    Returns (start, end) as Timestamps (end = the whole last day) or (None, None).
    """
    s = clean_text(text)
    if not s:
        return None, None
    nums = re.findall(_NUM_DATE, s)
    if len(nums) >= 2:
        dates, _, _ = harmonize_dates(nums[:2])
        a, b = dates[0][0], dates[1][0]
        if a is not None and b is not None:
            a, b = min(a, b), max(a, b)
            return a.normalize(), b.normalize()
    for m in _WORD_RANGE.finditer(s):
        d1, mon1, y1, d2, mon2, y2 = m.groups()
        m2 = _MONTHS.get((mon2 or "").lower().rstrip("."))
        m1 = _MONTHS.get((mon1 or "").lower().rstrip(".")) if mon1 else m2
        if not (m1 and m2):
            continue
        year2 = int(y2) if y2 else (int(y1) if y1 else default_year)
        if year2 is None:
            continue
        year1 = int(y1) if y1 else (year2 - 1 if m1 > m2 else year2)
        try:
            return pd.Timestamp(year1, m1, int(d1)), pd.Timestamp(year2, m2, int(d2))
        except ValueError:
            continue
    return None, None


# ---------------------------------------------------------------------------
# Dates written day/month or month/day: decide per file, not per line
# ---------------------------------------------------------------------------
_NUMERIC_DATE = re.compile(r"^\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})(.*)$")
_TIME = re.compile(r"(\d{1,2})\s*:\s*(\d{2})(?:\s*:\s*(\d{2}))?\s*(AM|PM)?", re.I)


def _build(day, month, year, rest):
    year = year + 2000 if year < 100 else year
    h = mi = sec = 0
    t = _TIME.search(rest or "")
    if t:
        h, mi, sec = int(t.group(1)), int(t.group(2)), int(t.group(3) or 0)
        ampm = (t.group(4) or "").upper()
        if ampm == "PM" and h < 12:
            h += 12
        if ampm == "AM" and h == 12:
            h = 0
    try:
        return pd.Timestamp(year, month, day, h, mi, sec)
    except ValueError:
        return None


def harmonize_dates(values, start=None, end=None):
    """Read a whole column of dates consistently.

    The file's format (day/month/year or month/day/year) is decided from the
    dates that can only be read one way (13/06/2026 is day-first, 06/13/2026
    is month-first). Dates that could be read both ways (07/06/2026) follow the
    file's format; if the whole file is ambiguous, the reading that puts more
    dates inside the declared interval wins (then the narrower date range).
    A single date that would fall outside the interval while its other reading
    is inside is switched, and noted.

    Returns (list of (timestamp, alternative, note), order, summary note).
    order is 'DMY', 'MDY' or None.
    """
    parsed = []          # (kind, a, b, year, rest) or ('other', value)
    dmy = mdy = 0
    for v in values:
        if isinstance(v, (datetime, pd.Timestamp)) or (isinstance(v, float) and not math.isnan(v)) or isinstance(v, int):
            parsed.append(("other", v))
            continue
        m = _NUMERIC_DATE.match(clean_text(v))
        if not m:
            parsed.append(("other", v))
            continue
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        parsed.append(("num", a, b, y, m.group(4)))
        if a > 12 >= b:
            dmy += 1
        elif b > 12 >= a:
            mdy += 1

    end_full = end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1) if end is not None else None
    inside = (lambda t: t is not None and start is not None and start <= t <= end_full)

    def read(order):
        out = []
        for p in parsed:
            if p[0] != "num":
                out.append(None)
                continue
            _, a, b, y, rest = p
            if a > 12 >= b:
                out.append(_build(a, b, y, rest))
            elif b > 12 >= a:
                out.append(_build(b, a, y, rest))
            else:
                out.append(_build(a, b, y, rest) if order == "DMY" else _build(b, a, y, rest))
        return out

    if mdy > dmy:
        order, why = "MDY", f"{mdy} date(s) can only be month/day/year"
    elif dmy > mdy:
        order, why = "DMY", f"{dmy} date(s) can only be day/month/year"
    else:
        order, why = None, ""
        n_num = sum(1 for p in parsed if p[0] == "num")
        if n_num:
            d_read, m_read = read("DMY"), read("MDY")
            d_in = sum(inside(t) for t in d_read)
            m_in = sum(inside(t) for t in m_read)
            if m_in > d_in:
                order, why = "MDY", "month/day/year puts more dates inside the declared interval"
            elif d_in > m_in:
                order, why = "DMY", "day/month/year puts more dates inside the declared interval"
            else:
                span = lambda ts: (max(t for t in ts if t) - min(t for t in ts if t)) if any(ts) else pd.Timedelta(0)
                if span(m_read) < span(d_read):
                    order, why = "MDY", "month/day/year gives a consistent (narrower) date range"
                else:
                    order, why = "DMY", "day/month/year (default)"
    if dmy and mdy:
        why += f"; note: the file mixes formats ({dmy} day-first, {mdy} month-first)"

    main = read(order or "DMY")
    results = []
    for p, ts in zip(parsed, main):
        if p[0] == "other":
            t, alt, note = parse_datetime(p[1], dayfirst=True)
            if t is not None and isinstance(p[1], (datetime, pd.Timestamp)) and t.day <= 12 and t.day != t.month:
                sw = t.replace(day=t.month, month=t.day)
                if start is not None and not inside(t) and inside(sw):
                    results.append((sw, t, f"date {t:%d/%m/%Y} stored with day and month swapped; read as {sw:%d/%m/%Y}"))
                    continue
                alt = sw
            results.append((t, alt, note))
            continue
        _, a, b, y, rest = p
        if ts is None:
            results.append((None, None, f"'{a}/{b}/{y}' is not a valid date"))
            continue
        alt = None
        if a <= 12 and b <= 12 and a != b:
            alt = _build(b, a, y, rest) if order != "MDY" else _build(a, b, y, rest)
            if start is not None and not inside(ts) and inside(alt):
                results.append((alt, ts, f"date read as {alt:%d/%m/%Y} (other reading {ts:%d/%m/%Y} is outside the interval)"))
                continue
        results.append((ts, alt, None))
    label = {"DMY": "day/month/year", "MDY": "month/day/year"}.get(order, "")
    summary = f"Dates in the file read as {label} ({why}); shown everywhere as dd/mm/yyyy" if label else ""
    return results, order, summary


# ---------------------------------------------------------------------------
# Row-level cleaning
# ---------------------------------------------------------------------------
def clean_claim(df: pd.DataFrame, settings: Settings = DEFAULT, interval=(None, None)) -> pd.DataFrame:
    """Add standardised columns + 'cleaning_notes' + 'format_issues' to a claim.

    interval: (start, end) declared by the supplier, used only to settle dates
    that could be read either way.
    """
    start, end = interval
    start = pd.Timestamp(start).normalize() if start is not None else None
    end = pd.Timestamp(end).normalize() if end is not None else None
    dates, order, date_summary = harmonize_dates(
        df["closed_at"].tolist() if "closed_at" in df else [None] * len(df), start, end)
    rows = []
    for k, (_, r) in enumerate(df.iterrows()):
        notes, issues = [], []

        def num(col, kind):
            if col not in r:
                return None
            v, n = parse_number(r[col], kind, settings)
            if n:
                (issues if v is None else notes).append(f"{col}: {n}")
            return v

        qty = num("qty", "qty")
        pu = num("unit_price", "price")
        amount = num("amount", "amount")
        rate = num("subsidy_rate", "rate")
        subsidy = num("subsidy_amount", "amount")
        net = num("net_payable", "amount")

        # Repair amounts typed with dots as thousands separators, e.g. 230.443
        if qty and pu and amount:
            expected = qty * pu
            if abs(amount * 1000 - expected) <= max(2, expected * 0.005) and abs(amount - expected) > expected * 0.5:
                notes.append(f"amount {amount} read as {amount * 1000:,.0f}")
                amount = amount * 1000

        ts, ts_alt, n = dates[k]
        if n:
            (issues if ts is None else notes).append(f"Closed at: {n}")
        elif ts is not None and order == "MDY" and isinstance(r.get("closed_at"), str):
            notes.append(f"Closed at '{clean_text(r.get('closed_at'))}' (mm/dd/yyyy) read as {ts:%d/%m/%Y %H:%M}")
        plate, n = normalize_plate(r.get("vehicle"))
        if n:
            (issues if plate is None else notes).append(n)
        slip = normalize_slip(r.get("slip"))
        if slip.status in ("FIXED",) and slip.note:
            notes.append(f"EBM slip: {slip.note}")
        product = normalize_product(r.get("product"))

        if qty is None:
            issues.append("Quantity missing or unreadable")
        elif qty <= 0:
            issues.append("Quantity must be positive")
        if pu is None:
            issues.append("P.U missing or unreadable")
        if ts is None and "closed_at: " not in " ".join(issues):
            issues.append("Closed at missing")
        otin = normalize_tin(r.get("omc_tin")) if "omc_tin" in r else None
        if otin and len(otin) != 9:
            issues.append(f"OMC TIN '{clean_text(r.get('omc_tin'))}' must have 9 digits")
        if product in (None, "UNKNOWN"):
            issues.append(f"Product '{clean_text(r.get('product'))}' not recognised")
        if slip.status in ("MISSING", "INCOMPLETE", "INVALID"):
            issues.append(f"EBM slip {slip.status.lower()}: {slip.note}")

        # Arithmetic consistency (warnings for the supplier, never rejection)
        warnings = []
        if qty and pu and amount is not None:
            exp = qty * pu
            if abs(amount - exp) > max(settings.amount_tolerance_rwf, exp * settings.amount_rel_tolerance):
                warnings.append(f"Amount {amount:,.0f} ≠ Quantity × P.U = {exp:,.0f}")
        if qty and rate and subsidy is not None:
            exp = qty * rate
            if abs(subsidy - exp) > max(settings.amount_tolerance_rwf, exp * settings.amount_rel_tolerance):
                warnings.append(f"Subsidy {subsidy:,.2f} ≠ Quantity × rate = {exp:,.2f}")

        rows.append({
            "source_row": r.get("source_row"),
            "site": clean_text(r.get("site")),
            "client": clean_text(r.get("client")),
            "omc_tin": normalize_tin(r.get("omc_tin")) or "",
            "closed_at": ts,
            "closed_at_alt": ts_alt,
            "vehicle": plate,
            "card": normalize_card(r.get("card")),
            "product": product,
            "product_raw": clean_text(r.get("product")),
            "qty": qty,
            "unit_price": pu,
            "amount": amount,
            "subsidy_rate": rate,
            "subsidy_amount": subsidy,
            "net_payable": net,
            "served_by": clean_text(r.get("served_by")),
            "slip_raw": clean_text(r.get("slip")),
            "slip_clean": merge_key(slip.key) if slip.key else merge_key(r.get("slip")),
            "sdc_id": slip.sdc_id,
            "invoice": slip.invoice,
            "ebm_key": slip.key,
            "slip_status": slip.status,
            "cleaning_notes": "; ".join(notes),
            "format_issues": "; ".join(issues),
            "warnings": "; ".join(warnings),
        })
    out = pd.DataFrame(rows)
    out.attrs["date_order"] = order
    out.attrs["date_summary"] = date_summary
    return out


def clean_ebm(df: pd.DataFrame, settings: Settings = DEFAULT, interval=(None, None)) -> pd.DataFrame:
    """Standardise an EBM extract (one row per invoice item).

    Values are parsed once per distinct value, so large extracts stay fast.
    """
    def col(name, fn):
        if name not in df:
            return pd.Series([None] * len(df), index=df.index, dtype=object)
        s = df[name].astype(object)
        s = s.where(s.notna(), "")
        uniq = {}
        for v in s.unique():
            k = clean_text(v)
            uniq[v] = fn(v) if k else None
        return s.map(uniq).astype(object)

    out = pd.DataFrame(index=df.index)
    out["ebm_row"] = df["source_row"]
    out["seller_tin"] = col("seller_tin", normalize_tin)
    out["buyer_tin"] = col("buyer_tin", normalize_tin)
    out["sdc_id"] = col("sdc_id", normalize_sdc_id)
    out["invoice"] = col("invoice", normalize_invoice)
    out["ebm_key"] = [f"{s}|{i}" if s and i else None for s, i in zip(out["sdc_id"], out["invoice"])]
    out.attrs["date_summary"] = ""
    if "sdc_datetime" in df:
        fast = pd.to_datetime(df["sdc_datetime"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
        slow = fast.isna() & df["sdc_datetime"].map(lambda v: bool(clean_text(v)))
        if slow.any():
            # Non-ISO dates (06/07/2026 17:20): decide day/month for the whole file, like the request file
            start, end = interval
            start = pd.Timestamp(start).normalize() if start is not None else None
            end = pd.Timestamp(end).normalize() if end is not None else None
            vals = df.loc[slow, "sdc_datetime"].astype(object)
            uniq = list(dict.fromkeys(vals.tolist()))
            res, order, summary = harmonize_dates(uniq, start, end)
            lookup = {v: r[0] for v, r in zip(uniq, res)}
            fast = fast.astype(object)
            fast[slow] = vals.map(lookup)
            if summary:
                out.attrs["date_summary"] = summary.replace("Dates in the file", "Dates in the EBM file")
        out["sdc_datetime"] = pd.to_datetime(fast)
    else:
        out["sdc_datetime"] = pd.NaT
    out["invoice_type"] = col("invoice_type", lambda v: clean_text(v).upper()).fillna("")
    out["item_name"] = col("item_name", clean_text).fillna("")
    out["product"] = col("item_name", normalize_product)
    out["item_unit_price"] = col("item_unit_price", lambda v: parse_number(v, "price", settings)[0]).astype(float)
    out["item_qty"] = col("item_qty", lambda v: parse_number(v, "qty", settings)[0]).astype(float)
    out["item_total"] = col("item_total", lambda v: parse_number(v, "amount", settings)[0]).astype(float)
    out["tax_type"] = col("tax_type", lambda v: clean_text(v).upper()[:1] or None)
    out["total_amount"] = col("total_amount", lambda v: parse_number(v, "amount", settings)[0]).astype(float)
    out["match_amount"] = col("match_amount", normalize_bool)
    return out.reset_index(drop=True)
