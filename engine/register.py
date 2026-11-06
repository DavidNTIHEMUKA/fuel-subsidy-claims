"""Data layer: accounts, claims through every stage, reviewer decisions, appeals.

Claim stages (one claim = one OMC submission):

  SUBMITTED   supplier uploaded the claim file and declared the interval
  PROCESSED   officer validated it against EBM (report available)
  APPROVED    signed off for payment
  PARTLY PAID finance recorded a payment below the amount due
  PAID        finance ticked it fully paid
  RETURNED    sent back to the supplier (with a reason)

Every switch goes through `move()`, which checks TRANSITIONS, so a claim can
never jump a stage. Every action is written to the audit log.
"""
from __future__ import annotations

import hashlib
import io
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .rules import summarise

# Values coming from pandas tables are numpy types; let SQLite store them as plain numbers
for _t in (np.int64, np.int32):
    sqlite3.register_adapter(_t, int)
for _t in (np.float64, np.float32):
    sqlite3.register_adapter(_t, float)

DB_PATH = Path(__file__).resolve().parent.parent / "claims.db"

TRANSITIONS = {
    "SUBMITTED":   {"PROCESSED", "RETURNED"},
    "PROCESSED":   {"PROCESSED", "APPROVED", "RETURNED"},    # re-processing allowed
    "APPROVED":    {"PAID", "PARTLY PAID", "RETURNED"},
    "PARTLY PAID": {"PAID", "PARTLY PAID", "APPROVED"},      # APPROVED = payment undone
    "PAID":        {"PARTLY PAID", "APPROVED"},              # PARTLY PAID = appeal award added
    "RETURNED":    set(),                                    # supplier submits again
}
STAGES = ["SUBMITTED", "PROCESSED", "APPROVED", "PARTLY PAID", "PAID", "RETURNED"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, name TEXT, role TEXT, tin TEXT, salt BLOB, pw BLOB, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission TEXT, tin TEXT, name TEXT, interval_start TEXT, interval_end TEXT, account TEXT,
  submitted_at TEXT, submitted_by TEXT, claim_file BLOB, claim_filename TEXT, supplier_note TEXT,
  processed_at TEXT, processor TEXT,
  vehicles INTEGER, claimed_l REAL, claimed_rwf REAL, accepted_l REAL, pending_l REAL,
  rejected_l REAL, to_reimburse REAL, rejected_rwf REAL, pending_rwf REAL, appeal_award REAL DEFAULT 0,
  status TEXT, approved_by TEXT, approved_at TEXT,
  paid_amount REAL, paid_at TEXT, payment_ref TEXT, paid_by TEXT, note TEXT,
  report BLOB, lines_csv TEXT
);
CREATE TABLE IF NOT EXISTS claim_keys (claim_id INTEGER, ebm_key TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS events (claim_id INTEGER, at TEXT, who TEXT, action TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS appeals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id INTEGER, tin TEXT, submitted_at TEXT, submitted_by TEXT,
  rows TEXT, reason TEXT, evidence BLOB, evidence_name TEXT,
  status TEXT, decided_by TEXT, decided_at TEXT, decision_note TEXT, award_l REAL, award_rwf REAL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value BLOB, name TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS payables (
  id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id INTEGER, kind TEXT, appeal_id INTEGER, amount REAL,
  created_at TEXT, status TEXT, paid_amount REAL DEFAULT 0, paid_at TEXT, payment_ref TEXT, paid_by TEXT
);
CREATE TABLE IF NOT EXISTS rounds (
  id INTEGER PRIMARY KEY AUTOINCREMENT, number INTEGER, name TEXT, created_at TEXT, created_by TEXT,
  status TEXT, approved_at TEXT, approved_by TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS signatures (
  round_id INTEGER, username TEXT, name TEXT, title TEXT, decision TEXT, comment TEXT, signed_at TEXT
);
CREATE TABLE IF NOT EXISTS deleted_users (
  username TEXT, name TEXT, role TEXT, tin TEXT, institution TEXT, title TEXT, created_note TEXT,
  deleted_at TEXT, deleted_by TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS deleted_claims (
  claim_id INTEGER, status TEXT, tin TEXT, name TEXT, submission TEXT, interval_start TEXT, interval_end TEXT,
  requested_rwf REAL, to_reimburse REAL, paid_amount REAL, claim_filename TEXT, claim_file BLOB,
  letter_name TEXT, letter BLOB, record TEXT, deleted_at TEXT, deleted_by TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS batch_history (
  batch INTEGER, omc TEXT, tin TEXT, period_start TEXT, period_end TEXT, vehicles INTEGER,
  claimed_l REAL, accepted_l REAL, pending_l REAL, claimed_rwf REAL, reimburse_rwf REAL, note TEXT,
  loaded_at TEXT, loaded_by TEXT
);
CREATE INDEX IF NOT EXISTS ix_keys ON claim_keys(ebm_key);
"""

LINE_COLUMNS = ["source_row", "status", "client", "vehicle", "closed_at", "product_raw", "slip_raw", "matched_key",
                "qty", "ebm_qty", "pay_rate", "accepted_qty", "pending_qty", "rejected_qty", "claimed_subsidy",
                "accepted_subsidy", "pending_subsidy", "rejected_subsidy", "reason", "review_reason",
                "format_issues", "warnings", "decision", "unit_price", "ebm_unit_price", "rura_price",
                "ebm_buyer_tin", "match_method", "ebm_key", "product", "slip_clean", "invoice_clean", "omc_tin"]
NUMERIC = ["qty", "ebm_qty", "pay_rate", "accepted_qty", "pending_qty", "rejected_qty", "claimed_subsidy",
           "accepted_subsidy", "pending_subsidy", "rejected_subsidy"]


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Connection and accounts
# ---------------------------------------------------------------------------
def connect(path=DB_PATH):
    # timeout: wait up to 30 s for another user's write instead of failing with "database is locked"
    con = sqlite3.connect(path, check_same_thread=False, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(_SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(users)")}
    if "expires_at" not in cols:                       # older databases: add the expiry column
        con.execute("ALTER TABLE users ADD COLUMN expires_at TEXT")
        con.commit()
    acols = {r[1] for r in con.execute("PRAGMA table_info(appeals)")}
    for c in ("corrections", "analysis_csv", "recommendation", "recommended_by", "recommended_at",
              "approved_by", "approved_at"):           # older databases: appeal steps
        if c not in acols:
            con.execute(f"ALTER TABLE appeals ADD COLUMN {c} TEXT")
    for c in ("institution", "title", "must_change"):
        if c not in {r[1] for r in con.execute("PRAGMA table_info(users)")}:
            con.execute(f"ALTER TABLE users ADD COLUMN {c} TEXT")
    acols = {r[1] for r in con.execute("PRAGMA table_info(appeals)")}
    for c in ("assigned_to", "assigned_by", "assigned_at"):
        if c not in acols:
            con.execute(f"ALTER TABLE appeals ADD COLUMN {c} TEXT")
    ccols = {r[1] for r in con.execute("PRAGMA table_info(claims)")}
    for c, kind in (("round_id", "INTEGER"), ("requested_rwf", "REAL"), ("calculated_rwf", "REAL"),
                    ("letter", "BLOB"), ("letter_name", "TEXT")):
        if c not in ccols:                              # older databases
            con.execute(f"ALTER TABLE claims ADD COLUMN {c} {kind}")
    con.commit()
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        # Demo accounts for the trial — change the passwords on first use
        create_user(con, "officer", "RRA Officer", "officer", "rra2026", institution="RRA")
        create_user(con, "100007664", "SAMPLE OMC", "supplier", "omc2026", tin="100007664")
    if con.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] == 0:
        create_user(con, "admin", "System administrator", "admin", "admin2026", institution="RRA")
    _migrate_payables(con)
    return con


def _migrate_payables(con):
    """Claims approved before payables existed get one 'First submission' payable."""
    rows = con.execute("""SELECT id, to_reimburse, paid_amount, paid_at, payment_ref, paid_by FROM claims
                          WHERE status IN ('APPROVED','PARTLY PAID','PAID')
                          AND id NOT IN (SELECT claim_id FROM payables)""").fetchall()
    for cid, due, paid, at, ref, by in rows:
        paid = paid or 0.0
        st = "PAID" if paid >= (due or 0) - 1 else ("PARTLY PAID" if paid else "DUE")
        con.execute("""INSERT INTO payables (claim_id, kind, amount, created_at, status, paid_amount, paid_at,
                       payment_ref, paid_by) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (cid, "First submission", due or 0, _now(), st, paid, at, ref, by))
    con.commit()


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)


ROLES = {
    "supplier": "Fuel supplier (OMC)",
    "officer": "RRA officer (analyst)",
    "finance": "Finance officer",
    "taskforce": "Taskforce member (signatory)",
    "approver": "Final approver",
    "manager": "Manager (view only)",
    "senior_manager": "Senior manager (view only, adds users)",
    "admin": "Administrator (super user)",
}
READ_ONLY_ROLES = ("manager", "senior_manager")

# Functions: roles the administrator defines (e.g. Data Scientist): the heads they open and the built-in role
# whose permissions they use inside those heads ("acts as").
HEADS = {"home": "Home", "submission": "Submission of request", "processing": "Processing · Claim analysis",
         "approval": "Approval · Rounds", "payment": "Payment", "reports": "Analysis", "reporting": "Reporting",
         "insights": "Insights", "appeal": "Appeal", "admin": "Admin", "account": "My account"}
DEFAULT_FUNCTIONS = {
    "data_scientist": {"label": "Data Scientist", "acts_as": "officer",
                       "heads": ["home", "appeal", "reports", "reporting", "insights", "account"],
                       "description": "Analyses appeal cases (re-matching with EBM, recommendation), data extraction "
                                      "and analysis; no processing, approval or payment."},
}


def functions(con) -> dict:
    import json
    row = con.execute("SELECT value FROM settings WHERE key='cfg:functions'").fetchone()
    return json.loads(row[0]) if row and row[0] else dict(DEFAULT_FUNCTIONS)


def save_functions(con, fns: dict, who: str):
    import json
    for k, f in fns.items():
        if f.get("acts_as") not in ROLES or f.get("acts_as") == "admin":
            raise ValueError(f"{f.get('label', k)}: 'acts as' must be one of the built-in roles (not administrator)")
        if not f.get("heads"):
            raise ValueError(f"{f.get('label', k)}: choose at least one head")
        f["heads"] = [h for h in HEADS if h in f["heads"] or h in ("home", "account")]
    put_setting(con, "cfg:functions", json.dumps(fns).encode(), who)


def function_key(label: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")


def role_label(con, role: str) -> str:
    return ROLES.get(role) or functions(con).get(role, {}).get("label", role)


def _known_role(con, role):
    return role in ROLES or role in functions(con)


def _with_function(con, info: dict) -> dict:
    """A user whose role is a function gets the permissions of its 'acts as' role and only its heads."""
    fn = functions(con).get(info.get("role"))
    if fn:
        info = dict(info, function=info["role"], function_label=fn["label"], role=fn["acts_as"], heads=fn["heads"])
    return info


def create_user(con, username, name, role, password, tin=None, expires_at=None, institution=None, title=None,
                must_change=False):
    """expires_at: date/datetime after which the account can no longer sign in (None = never)."""
    if not _known_role(con, role):
        raise ValueError(f"role must be one of: {', '.join(list(ROLES) + list(functions(con)))}")
    if not str(username).strip() or not str(name).strip():
        raise ValueError("username and name are required")
    if len(password) < 6:
        raise ValueError("password must have at least 6 characters")
    salt = os.urandom(16)
    exp = f"{pd.Timestamp(expires_at):%Y-%m-%d %H:%M}" if expires_at is not None else None
    con.execute("""INSERT OR REPLACE INTO users (username, name, role, tin, salt, pw, active, expires_at,
                   institution, title, must_change) VALUES (?,?,?,?,?,?,1,?,?,?,?)""",
                (username.strip(), name.strip(), role, (tin or "").strip() or None, salt, _hash(password, salt), exp,
                 (institution or "").strip() or None, (title or "").strip() or None, "1" if must_change else None))
    con.commit()


def update_user(con, username, **fields):
    allowed = {"name", "role", "tin", "active", "expires_at", "institution", "title"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot change {', '.join(bad)}")
    if "role" in fields and not _known_role(con, fields["role"]):
        raise ValueError("unknown role")
    if fields.get("active") == 0 and con.execute(
            "SELECT role FROM users WHERE username=?", (username,)).fetchone()[0] == "admin" and \
            con.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
        raise ValueError("the last active administrator cannot be deactivated")
    if fields:
        con.execute(f"UPDATE users SET {', '.join(k + '=?' for k in fields)} WHERE username=?",
                    (*fields.values(), username))
        con.commit()


def _strong(password):
    if len(password) < 8 or not any(c.isdigit() for c in password) or not any(c.isalpha() for c in password):
        raise ValueError("the new password needs at least 8 characters, with letters and numbers")


def reset_password(con, username, password, must_change=True):
    """Administrator sets a password; by default the user must change it at the next sign-in."""
    if len(password) < 6:
        raise ValueError("password must have at least 6 characters")
    salt = os.urandom(16)
    con.execute("UPDATE users SET salt=?, pw=?, must_change=? WHERE username=?",
                (salt, _hash(password, salt), "1" if must_change else None, username))
    con.commit()


def change_password(con, username, old, new):
    """The user changes their own password (also used for the forced change at first sign-in)."""
    row = con.execute("SELECT salt, pw FROM users WHERE username=?", (username,)).fetchone()
    if not row or _hash(old, row[0]) != row[1]:
        raise ValueError("the current password is not correct")
    if new == old:
        raise ValueError("the new password must be different from the current one")
    _strong(new)
    salt = os.urandom(16)
    con.execute("UPDATE users SET salt=?, pw=?, must_change=NULL WHERE username=?", (salt, _hash(new, salt), username))
    con.commit()


def uniform_username(name: str) -> str:
    """'MUKANGABO Beatha (RURA) Chair' -> 'beatha.mukangabo' (given name . family name, ASCII, lower case)."""
    import re
    import unicodedata
    base = re.split(r"[(,]", name)[0]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    parts = [p for p in re.split(r"[^A-Za-z'-]+", base) if p]
    if not parts:
        raise ValueError(f"cannot make a username from '{name}'")
    family, given = parts[0], (parts[1] if len(parts) > 1 else "")
    u = f"{given}.{family}" if given else family
    return re.sub(r"[^a-z.]", "", u.lower())


def parse_signatory(line: str) -> dict:
    """'MUKANGABO Beatha (RURA) Chair' -> name, institution, title."""
    import re
    inst = re.search(r"\(([^)]+)\)", line)
    title = re.sub(r"^[,\s-]+", "", line[inst.end():]).strip() if inst else ""
    name = re.split(r"[(,]", line)[0].strip()
    return {"name": name, "institution": inst.group(1).strip() if inst else "", "title": title}


def create_signatories(con, lines: list[str], default_password: str, role="taskforce", expires_at=None):
    """Create one account per signatory, uniform usernames, default password to change at first sign-in.
    Existing usernames are left untouched. Returns the accounts created."""
    made = []
    for line in [l for l in lines if l.strip()]:
        info = parse_signatory(line)
        username = uniform_username(info["name"])
        if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            continue
        create_user(con, username, info["name"], role, default_password, institution=info["institution"],
                    title=info["title"], must_change=True, expires_at=expires_at)
        made.append({**info, "username": username, "role": role})
    return made


def make_password(n=10):
    """Readable random password (no 0/O, 1/l/I)."""
    import secrets
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def login(con, username, password):
    row = con.execute("SELECT username, name, role, tin, salt, pw, active, expires_at FROM users WHERE username=?",
                      (username.strip(),)).fetchone()
    if not row or not row[6] or _hash(password, row[4]) != row[5]:
        return None
    if row[7] and pd.Timestamp(row[7]) < pd.Timestamp.now():
        return {"expired": True, "expires_at": row[7]}
    must = con.execute("SELECT must_change FROM users WHERE username=?", (row[0],)).fetchone()[0]
    return _with_function(con, {"username": row[0], "name": row[1], "role": row[2], "tin": row[3],
                                "must_change": bool(must)})


def user_info(con, username):
    row = con.execute("SELECT username, name, role, tin, institution, title FROM users WHERE username=?",
                      (username,)).fetchone()
    return _with_function(con, dict(zip(["username", "name", "role", "tin", "institution", "title"], row))) if row else None


def users(con):
    return pd.read_sql_query("SELECT username, name, role, tin, institution, title, active, "
                             "CASE WHEN must_change='1' THEN 'yes' ELSE '' END AS must_change_password, "
                             "expires_at AS valid_until FROM users ORDER BY role, name", con).fillna("")


# ---------------------------------------------------------------------------
# Audit log and the one place where a stage changes
# ---------------------------------------------------------------------------
def log(con, claim_id, who, action, note=""):
    con.execute("INSERT INTO events VALUES (?,?,?,?,?)", (claim_id, _now(), who, action, note))


def move(con, claim_id, new_status, who, remark="", **fields):
    """Change the stage of a claim (the only place where it happens). remark goes to the audit log;
    fields are claim columns to update (they may include the claim's own `note`)."""
    note = remark
    current = status_of(con, claim_id)
    if new_status not in TRANSITIONS[current]:
        raise ValueError(f"Claim #{claim_id} is {current}; it cannot move to {new_status}")
    cols = ["status", *fields]
    con.execute(f"UPDATE claims SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                (new_status, *fields.values(), claim_id))
    log(con, claim_id, who, new_status, note)
    con.commit()


def status_of(con, claim_id):
    row = con.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()
    if not row:
        raise ValueError(f"Claim #{claim_id} not found")
    return row[0]


# ---------------------------------------------------------------------------
# Stage 1 — submission by the supplier
# ---------------------------------------------------------------------------
def submit_claim(con, user, name, start, end, account, file_bytes, filename, note="", requested_rwf=None,
                 letter=None, letter_name=None):
    """requested_rwf: amount of subsidies the supplier requests (from its request letter).
    letter / letter_name: the signed request letter (PDF or image)."""
    if not (start and end):
        raise ValueError("The consumption interval (from–to) is required")
    if pd.Timestamp(end) < pd.Timestamp(start):
        raise ValueError("The interval ends before it starts")
    if requested_rwf is not None and float(requested_rwf) < 0:
        raise ValueError("The amount of subsidies requested cannot be negative")
    cur = con.execute(
        """INSERT INTO claims (tin, name, interval_start, interval_end, account, submitted_at, submitted_by,
           claim_file, claim_filename, supplier_note, status, requested_rwf, letter, letter_name)
           VALUES (?,?,?,?,?,?,?,?,?,?, 'SUBMITTED',?,?,?)""",
        (user.get("tin") or "", name, f"{pd.Timestamp(start):%Y-%m-%d}", f"{pd.Timestamp(end):%Y-%m-%d}",
         account, _now(), user["username"], file_bytes, filename, note,
         round(float(requested_rwf), 2) if requested_rwf else None, letter, letter_name))
    cid = cur.lastrowid
    log(con, cid, user["username"], "SUBMITTED",
        filename + (f"; requested {float(requested_rwf):,.0f} RWF" if requested_rwf else "")
        + (f"; letter {letter_name}" if letter_name else ""))
    con.commit()
    return cid


def claim_letter(con, claim_id):
    """(bytes, file name) of the request letter, or (None, None)."""
    row = con.execute("SELECT letter, letter_name FROM claims WHERE id=?", (claim_id,)).fetchone()
    return (row[0], row[1]) if row and row[0] else (None, None)


def set_requested(con, claim_id, who, requested_rwf, letter=None, letter_name=None):
    """Officer records the amount requested / letter for a claim that came without them."""
    con.execute("UPDATE claims SET requested_rwf=? WHERE id=?", (round(float(requested_rwf), 2), claim_id))
    if letter:
        con.execute("UPDATE claims SET letter=?, letter_name=? WHERE id=?", (letter, letter_name, claim_id))
    log(con, claim_id, who, "REQUEST AMOUNT", f"{float(requested_rwf):,.0f} RWF" + (f"; letter {letter_name}" if letter else ""))
    con.commit()


def lower_of(requested, calculated):
    """Amount to reimburse: the lower of the subsidies requested and the subsidies calculated (potential)."""
    calculated = float(calculated or 0)
    if requested is None or pd.isna(requested) or float(requested) <= 0:
        return calculated, "calculated (no amount requested)"
    requested = float(requested)
    return (requested, "requested (lower)") if requested < calculated else (calculated, "calculated (lower)")


def claim_file(con, claim_id):
    blob, name = con.execute("SELECT claim_file, claim_filename FROM claims WHERE id=?", (claim_id,)).fetchone()
    b = io.BytesIO(blob)
    b.name = name or "claim.xlsx"
    return b


# ---------------------------------------------------------------------------
# Stage 2 — processing / claim analysis
# ---------------------------------------------------------------------------
def _totals(lines: pd.DataFrame) -> dict:
    n = lambda c: float(pd.to_numeric(lines[c], errors="coerce").fillna(0).sum())
    return {"accepted_l": round(n("accepted_qty"), 2), "pending_l": round(n("pending_qty"), 2),
            "rejected_l": round(n("rejected_qty"), 2), "to_reimburse": round(n("accepted_subsidy")),
            "pending_rwf": round(n("pending_subsidy")), "rejected_rwf": round(n("rejected_subsidy"))}


def _line_frame(lines: pd.DataFrame) -> pd.DataFrame:
    keep = lines.copy()
    for c in LINE_COLUMNS:
        if c not in keep:
            keep[c] = ""
    keep = keep[LINE_COLUMNS].copy()
    keep["closed_at"] = pd.to_datetime(keep["closed_at"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M")
    keep["matched_key"] = keep["matched_key"].fillna("").astype(str).str.replace("|", "/", regex=False)
    return keep


def save_processing(con, claim_id, lines: pd.DataFrame, report: bytes, who: str, submission: str):
    s = summarise(lines)
    lf = _line_frame(lines)
    t = _totals(lf)
    req = con.execute("SELECT requested_rwf FROM claims WHERE id=?", (claim_id,)).fetchone()[0]
    t["calculated_rwf"] = t["to_reimburse"]
    amount, basis = lower_of(req, t["calculated_rwf"])
    t["to_reimburse"] = round(amount)
    move(con, claim_id, "PROCESSED", who, f"{t['accepted_l']:,.2f} L accepted, calculated {t['calculated_rwf']:,} RWF, "
         f"requested {req or 0:,.0f} RWF → to reimburse {t['to_reimburse']:,} RWF ({basis})",
         submission=submission, processed_at=_now(), processor=who, vehicles=s["vehicles"],
         claimed_l=s["claimed_qty"], claimed_rwf=round(s["claimed_subsidy"]), report=report,
         lines_csv=lf.to_csv(index=False), **t)
    con.execute("DELETE FROM claim_keys WHERE claim_id=?", (claim_id,))
    # every invoice decided here is blocked in later claims (rejected ones can only return via Appeal)
    used = lines[lines["matched_key"].notna() & (lines["matched_key"].astype(str) != "")]
    con.executemany("INSERT INTO claim_keys VALUES (?,?,?)",
                    [(claim_id, k, s_) for k, s_ in zip(used["matched_key"], used["status"])])
    con.commit()


def history_keys(con, exclude_claim=None) -> dict:
    """EBM invoices already used by other claims still in force."""
    q = """SELECT k.ebm_key, k.status, c.id, c.submission, c.name FROM claim_keys k JOIN claims c ON c.id = k.claim_id
           WHERE c.status != 'RETURNED' AND c.id != ?"""
    out = {}
    for k, st, i, sub, name in con.execute(q, (exclude_claim or -1,)).fetchall():
        tail = " — it was rejected there; use Appeal" if st == "REJECTED" else ""
        out[k] = f"claim #{i} {sub or ''} ({name}){tail}".replace("  ", " ")
    return out


def approve(con, claim_id, who):
    pending, due = con.execute("SELECT pending_l, to_reimburse FROM claims WHERE id=?", (claim_id,)).fetchone()
    note = f"{(pending or 0):,.2f} L still pending review (not paid)" if pending else ""
    move(con, claim_id, "APPROVED", who, note, approved_by=who, approved_at=_now())
    add_payable(con, claim_id, "First submission", due or 0)


def add_payable(con, claim_id, kind, amount, appeal_id=None):
    if amount <= 0:
        return
    con.execute("""INSERT INTO payables (claim_id, kind, appeal_id, amount, created_at, status, paid_amount)
                   VALUES (?,?,?,?,?, 'DUE', 0)""", (claim_id, kind, appeal_id, round(float(amount), 2), _now()))
    con.commit()


def payables(con, status=None) -> pd.DataFrame:
    q = """SELECT p.id, p.claim_id, c.name, c.tin, c.submission, c.account, p.kind, p.appeal_id, p.amount,
                  p.paid_amount, p.amount - p.paid_amount AS outstanding, p.status, p.created_at, p.paid_at,
                  p.payment_ref, p.paid_by, c.claimed_rwf, c.rejected_rwf, c.pending_rwf
           FROM payables p JOIN claims c ON c.id = p.claim_id WHERE 1=1"""
    p = []
    if status:
        q += f" AND p.status IN ({','.join('?' * len(status))})"
        p += list(status)
    return pd.read_sql_query(q + " ORDER BY p.id", con, params=p)


def _sync_claim_payment(con, claim_id, who, note):
    paid, due = con.execute("SELECT COALESCE(SUM(paid_amount),0), COALESCE(SUM(amount),0) FROM payables "
                            "WHERE claim_id=?", (claim_id,)).fetchone()
    refs = "; ".join(r for (r,) in con.execute("SELECT payment_ref FROM payables WHERE claim_id=? AND payment_ref "
                                               "IS NOT NULL ORDER BY id", (claim_id,)) if r)
    last = con.execute("SELECT MAX(paid_at), MAX(paid_by) FROM payables WHERE claim_id=?", (claim_id,)).fetchone()
    new = "PAID" if paid >= due - 1 and paid > 0 else ("PARTLY PAID" if paid > 0 else "APPROVED")
    cur = status_of(con, claim_id)
    fields = dict(paid_amount=paid or None, paid_at=last[0], paid_by=last[1], payment_ref=refs or None)
    if new != cur and new in TRANSITIONS[cur]:
        move(con, claim_id, new, who, note, **fields)
    else:
        con.execute(f"UPDATE claims SET {', '.join(k + '=?' for k in fields)} WHERE id=?", (*fields.values(), claim_id))
        log(con, claim_id, who, "PAYMENT", note)
        con.commit()


def pay_payable(con, payable_id, who, amount: float, paid_on, reference: str):
    row = con.execute("SELECT claim_id, amount, paid_amount, payment_ref, kind FROM payables WHERE id=?",
                      (payable_id,)).fetchone()
    if not row:
        raise ValueError(f"Payable #{payable_id} not found")
    claim_id, due, already, old_ref, kind = row
    if not reference:
        raise ValueError("Payment reference is required")
    if amount <= 0:
        raise ValueError("Amount paid must be positive")
    total = (already or 0) + float(amount)
    if total > due + 1:
        raise ValueError(f"Total paid {total:,.0f} would exceed the amount due {due:,.0f} RWF ({kind})")
    st = "PAID" if total >= due - 1 else "PARTLY PAID"
    con.execute("UPDATE payables SET paid_amount=?, status=?, paid_at=?, payment_ref=?, paid_by=? WHERE id=?",
                (total, st, f"{pd.Timestamp(paid_on):%Y-%m-%d}", f"{old_ref}; {reference}" if old_ref else reference,
                 who, payable_id))
    con.commit()
    _sync_claim_payment(con, claim_id, who, f"{kind}: {amount:,.0f} RWF, ref {reference}")


def return_claim(con, claim_id, who, reason):
    if not reason:
        raise ValueError("A reason is required to return a claim")
    move(con, claim_id, "RETURNED", who, reason, note=reason)


# ---------------------------------------------------------------------------
# Stage 3 — payment
# ---------------------------------------------------------------------------
def mark_paid(con, claim_id, who, amount: float, paid_on, reference: str):
    """Pay a claim: the amount is applied to its payables in order (first submission, then appeals)."""
    status = status_of(con, claim_id)
    if status not in ("APPROVED", "PARTLY PAID"):
        raise ValueError(f"Claim #{claim_id} is {status}; it must be APPROVED before payment")
    if not reference:
        raise ValueError("Payment reference is required")
    if amount <= 0:
        raise ValueError("Amount paid must be positive")
    due = con.execute("SELECT id, amount - paid_amount FROM payables WHERE claim_id=? AND status != 'PAID' "
                      "ORDER BY id", (claim_id,)).fetchall()
    outstanding = sum(d for _, d in due)
    if amount > outstanding + 1:
        raise ValueError(f"Total paid would exceed the amount due ({outstanding:,.0f} RWF outstanding)")
    left = float(amount)
    for pid, d in due:
        if left <= 0:
            break
        part = min(left, d)
        pay_payable(con, pid, who, part, paid_on, reference)
        left -= part


def unmark_paid(con, claim_id, who, reason):
    if not reason:
        raise ValueError("A reason is required to undo a payment")
    con.execute("UPDATE payables SET paid_amount=0, status='DUE', paid_at=NULL, payment_ref=NULL, paid_by=NULL "
                "WHERE claim_id=?", (claim_id,))
    move(con, claim_id, "APPROVED", who, f"payment undone: {reason}", paid_amount=None, paid_at=None,
         payment_ref=None, paid_by=None)


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------
def file_appeal(con, user, claim_id, rows: list, reason: str, evidence=None, evidence_name=None,
                corrections: pd.DataFrame | None = None):
    """corrections: optional rows from the appeal form (row, slip, qty, explanation)."""
    tin = con.execute("SELECT tin FROM claims WHERE id=?", (claim_id,)).fetchone()[0]
    if user["role"] == "supplier" and tin != user.get("tin"):
        raise ValueError("You can only appeal your own claims")
    if not rows:
        raise ValueError("Select at least one rejected line to appeal")
    if not reason.strip():
        raise ValueError("Explain why the lines should be accepted")
    open_rows = set()
    for (r,) in con.execute("SELECT rows FROM appeals WHERE claim_id=? AND status='OPEN'", (claim_id,)):
        open_rows |= set(r.split(","))
    clash = sorted(set(map(str, rows)) & open_rows, key=int)
    if clash:
        raise ValueError(f"Claim #{claim_id}: row(s) {', '.join(clash)} already have an open appeal")
    corr_csv = None
    if corrections is not None and not corrections.empty:
        c = corrections[corrections["row"].astype(str).isin(set(map(str, rows)))]
        corr_csv = c[["row", "slip", "qty", "explanation"]].to_csv(index=False) if not c.empty else None
    cur = con.execute(
        """INSERT INTO appeals (claim_id, tin, submitted_at, submitted_by, rows, reason, evidence, evidence_name,
           status, corrections) VALUES (?,?,?,?,?,?,?,?, 'OPEN', ?)""",
        (claim_id, tin, _now(), user["username"], ",".join(map(str, rows)), reason, evidence, evidence_name,
         corr_csv))
    log(con, claim_id, user["username"], f"APPEAL #{cur.lastrowid} FILED", f"rows {','.join(map(str, rows))}")
    con.commit()
    return cur.lastrowid


def appeals(con, tin=None, status=None):
    q = """SELECT a.id, a.claim_id, c.name, c.submission, a.tin, a.submitted_at, c.submitted_at AS claim_submitted_at,
                  a.rows, a.reason, a.evidence_name, a.status, a.decided_by, a.decided_at, a.decision_note,
                  a.award_l, a.award_rwf, (a.corrections IS NOT NULL) AS has_corrections,
                  (a.analysis_csv IS NOT NULL) AS analysed, a.assigned_to, a.assigned_at
           FROM appeals a JOIN claims c ON c.id = a.claim_id WHERE 1=1"""
    p = []
    if tin:
        q, p = q + " AND a.tin=?", p + [tin]
    if status:
        q, p = q + " AND a.status=?", p + [status]
    return pd.read_sql_query(q + " ORDER BY a.id DESC", con, params=p)


def appeal_corrections(con, appeal_id) -> pd.DataFrame:
    row = con.execute("SELECT corrections FROM appeals WHERE id=?", (appeal_id,)).fetchone()
    if not row or not row[0]:
        return pd.DataFrame(columns=["row", "slip", "qty", "explanation"])
    df = pd.read_csv(io.StringIO(row[0]), dtype=str, keep_default_na=False)
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce")
    return df


def save_appeal_analysis(con, appeal_id, analysis: pd.DataFrame, who: str):
    con.execute("UPDATE appeals SET analysis_csv=? WHERE id=?", (analysis.to_csv(index=False), appeal_id))
    claim_id = con.execute("SELECT claim_id FROM appeals WHERE id=?", (appeal_id,)).fetchone()[0]
    n_ok = int((analysis["award_l"] > 0).sum()) if "award_l" in analysis else 0
    log(con, claim_id, who, f"APPEAL #{appeal_id} ANALYSED", f"{n_ok} of {len(analysis)} line(s) supported by EBM")
    con.commit()


def save_appeal_vat_check(con, appeal_id, analysis: pd.DataFrame, who: str, annex_name: str):
    con.execute("UPDATE appeals SET analysis_csv=? WHERE id=?", (analysis.to_csv(index=False), appeal_id))
    claim_id = con.execute("SELECT claim_id FROM appeals WHERE id=?", (appeal_id,)).fetchone()[0]
    n = int((analysis["vat_status"] == "Declared in the VAT annex").sum())
    log(con, claim_id, who, f"APPEAL #{appeal_id} VAT ANNEX CHECKED",
        f"{n} of {len(analysis)} line(s) declared in the VAT annex ({annex_name})")
    con.commit()


def appeal_analysis(con, appeal_id) -> pd.DataFrame | None:
    row = con.execute("SELECT analysis_csv FROM appeals WHERE id=?", (appeal_id,)).fetchone()
    if not row or not row[0]:
        return None
    df = pd.read_csv(io.StringIO(row[0]), dtype=str, keep_default_na=False)
    for c in ("award_l", "award_rwf", "ebm_qty", "claimed_qty", "vat_amount", "ebm_amount"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def evidence(con, appeal_id):
    return con.execute("SELECT evidence, evidence_name FROM appeals WHERE id=?", (appeal_id,)).fetchone()


def decide_appeal(con, appeal_id, who, upheld_rows: list, note: str, awards: dict | None = None,
                  new_keys: dict | None = None):
    """Uphold some/all appealed lines.

    awards: {row: litres} to accept per line (from the re-analysis); capped at the litres
            rejected. Without it an upheld line gets all its rejected litres back.
    new_keys: {row: EBM key} when the analysis matched a corrected slip number.
    """
    claim_id, rows, status = con.execute("SELECT claim_id, rows, status FROM appeals WHERE id=?",
                                         (appeal_id,)).fetchone()
    if status not in ("OPEN", "VERIFIED"):
        raise ValueError(f"Appeal #{appeal_id} is already {status}")
    if not note.strip():
        raise ValueError("A decision note is required")
    appealed = set(rows.split(","))
    upheld = {str(r) for r in upheld_rows} & appealed
    lines = lines_for(con, claim_id)
    award_l = award_rwf = 0.0
    full = True
    for i in lines.index[lines["source_row"].astype(str).isin(upheld)]:
        row = str(lines.at[i, "source_row"])
        rej = float(lines.at[i, "rejected_qty"])
        rate = float(lines.at[i, "pay_rate"]) or (float(lines.at[i, "rejected_subsidy"]) / rej if rej else 0.0)
        litres = rej if awards is None else max(0.0, min(float(awards.get(row, 0.0)), rej))
        if litres <= 0:
            full = False
            continue
        rwf = round(litres * rate, 2)
        award_l += litres
        award_rwf += rwf
        lines.at[i, "accepted_qty"] = round(float(lines.at[i, "accepted_qty"]) + litres, 2)
        lines.at[i, "accepted_subsidy"] = round(float(lines.at[i, "accepted_subsidy"]) + rwf, 2)
        lines.at[i, "rejected_qty"] = round(rej - litres, 2)
        lines.at[i, "rejected_subsidy"] = max(0.0, round(float(lines.at[i, "rejected_subsidy"]) - rwf, 2))
        partial = lines.at[i, "rejected_qty"] > 0.005
        full = full and not partial
        lines.at[i, "status"] = "PARTLY ACCEPTED ON APPEAL" if partial else "ACCEPTED ON APPEAL"
        key = (new_keys or {}).get(row)
        if key:
            lines.at[i, "matched_key"] = key.replace("|", "/")
            from .cleaning import merge_key
            lines.at[i, "invoice_clean"] = merge_key(key)
        lines.at[i, "decision"] = (f"Appeal #{appeal_id}: {litres:,.2f} L accepted by {who}"
                                   + (f" (EBM invoice {key.replace('|', '')})" if key else "") + f": {note}")
    t = _totals(lines)
    req, before, prior = con.execute("SELECT requested_rwf, to_reimburse, COALESCE(appeal_award,0) FROM claims WHERE id=?",
                                     (claim_id,)).fetchone()
    t["calculated_rwf"] = t["to_reimburse"]
    t.pop("to_reimburse")
    if req and float(req) > 0:                   # never pay more than the supplier requested
        room = max(0.0, float(req) - float(before or 0))
        if award_rwf > room:
            note = f"{note} [award limited to {room:,.0f} RWF: amount requested {float(req):,.0f} RWF]"
            award_rwf = room
    t["to_reimburse"] = round(float(before or 0) + award_rwf)
    if award_l <= 0:
        new_status = "DISMISSED"
    else:
        new_status = "UPHELD" if (upheld == appealed and full) else "PARTLY UPHELD"
    con.execute("""UPDATE appeals SET status=?, decided_by=?, decided_at=?, decision_note=?, award_l=?, award_rwf=?
                   WHERE id=?""", (new_status, who, _now(), note, round(award_l, 2), round(award_rwf), appeal_id))
    con.execute(f"""UPDATE claims SET lines_csv=?, appeal_award=COALESCE(appeal_award,0)+?,
                    {', '.join(k + '=?' for k in t)} WHERE id=?""",
                (lines.to_csv(index=False), round(award_rwf), *t.values(), claim_id))
    won = lines[lines["source_row"].astype(str).isin(upheld) & (lines["matched_key"] != "")]
    keys = won["matched_key"].str.replace("/", "|", regex=False)
    con.executemany("INSERT INTO claim_keys VALUES (?,?,?)", [(claim_id, k, "APPEAL") for k in keys])
    log(con, claim_id, who, f"APPEAL #{appeal_id} {new_status}", f"{award_l:,.2f} L, {award_rwf:,.0f} RWF")
    con.commit()
    if award_rwf > 0 and status_of(con, claim_id) in ("APPROVED", "PARTLY PAID", "PAID"):
        add_payable(con, claim_id, f"Appeal #{appeal_id}", award_rwf, appeal_id)
        _sync_claim_payment(con, claim_id, who, f"appeal #{appeal_id} added {award_rwf:,.0f} RWF to pay")
    return new_status, award_l, award_rwf


# ---------------------------------------------------------------------------
# Appeal steps: Submitted -> Analysed -> Verified (officer) -> Approved (approver) -> Paid
# ---------------------------------------------------------------------------
def recommend_appeal(con, appeal_id, who, awards: dict, note: str, new_keys: dict | None = None):
    """Officer verification: records the proposed award per line; nothing is paid until approved."""
    import json
    st = con.execute("SELECT status, claim_id FROM appeals WHERE id=?", (appeal_id,)).fetchone()
    if not st or st[0] not in ("OPEN", "VERIFIED"):
        raise ValueError(f"Appeal #{appeal_id} cannot be verified now ({st[0] if st else 'not found'})")
    if not note.strip():
        raise ValueError("A verification note is required")
    rec = {"awards": {str(k): float(v) for k, v in awards.items()}, "new_keys": new_keys or {}, "note": note}
    con.execute("UPDATE appeals SET status='VERIFIED', recommendation=?, recommended_by=?, recommended_at=? WHERE id=?",
                (json.dumps(rec), who, _now(), appeal_id))
    total = sum(v for v in rec["awards"].values() if v > 0)
    log(con, st[1], who, f"APPEAL #{appeal_id} VERIFIED", f"{total:,.2f} L proposed")
    con.commit()


def appeal_recommendation(con, appeal_id):
    import json
    row = con.execute("SELECT recommendation, recommended_by, recommended_at FROM appeals WHERE id=?",
                      (appeal_id,)).fetchone()
    if not row or not row[0]:
        return None
    rec = json.loads(row[0])
    rec.update(by=row[1], at=row[2])
    return rec


def approve_appeal(con, appeal_id, who, approve: bool, note: str = ""):
    """Final approval of a verified appeal: applies the proposed awards (or dismisses)."""
    rec = appeal_recommendation(con, appeal_id)
    st = con.execute("SELECT status, claim_id FROM appeals WHERE id=?", (appeal_id,)).fetchone()
    if st[0] != "VERIFIED" or rec is None:
        raise ValueError(f"Appeal #{appeal_id} must be verified by an officer before approval")
    con.execute("UPDATE appeals SET approved_by=?, approved_at=? WHERE id=?", (who, _now(), appeal_id))
    if not approve:
        con.execute("UPDATE appeals SET status='DISMISSED', decided_by=?, decided_at=?, decision_note=?, award_l=0, "
                    "award_rwf=0 WHERE id=?", (who, _now(), note or "not approved", appeal_id))
        log(con, st[1], who, f"APPEAL #{appeal_id} NOT APPROVED", note)
        con.commit()
        return "DISMISSED", 0.0, 0.0
    awards = {k: v for k, v in rec["awards"].items() if v > 0}
    con.execute("UPDATE appeals SET status='OPEN' WHERE id=?", (appeal_id,))   # decide_appeal applies from OPEN
    text = rec["note"] + (f" — approved by {who}" + (f": {note}" if note else ""))
    return decide_appeal(con, appeal_id, who, list(awards), text, awards, rec.get("new_keys"))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def claims(con, tin=None, status=None) -> pd.DataFrame:
    q = """SELECT id, submission, tin, name, interval_start, interval_end, account, submitted_at, submitted_by,
                  claim_filename, processed_at, processor, vehicles, claimed_l, claimed_rwf, accepted_l, pending_l,
                  rejected_l, to_reimburse, rejected_rwf, pending_rwf, appeal_award, status, approved_by,
                  approved_at, paid_amount, paid_at, payment_ref, paid_by, note, round_id, requested_rwf,
                  calculated_rwf, letter_name FROM claims WHERE 1=1"""
    p = []
    if tin:
        q, p = q + " AND tin=?", p + [str(tin).strip()]
    if status:
        q, p = q + f" AND status IN ({','.join('?' * len(status))})", p + list(status)
    df = pd.read_sql_query(q + " ORDER BY id DESC", con, params=p)
    df["outstanding"] = (df["to_reimburse"].fillna(0) - df["paid_amount"].fillna(0)).where(
        df["status"].isin(["APPROVED", "PARTLY PAID", "PAID"]), 0)
    return df


def lines_for(con, claim_id) -> pd.DataFrame:
    csv = con.execute("SELECT lines_csv FROM claims WHERE id=?", (claim_id,)).fetchone()[0]
    if not csv:
        return pd.DataFrame(columns=LINE_COLUMNS)
    df = pd.read_csv(io.StringIO(csv), dtype=str, keep_default_na=False)
    # claims saved before symbol-free keys existed
    from .cleaning import merge_key, slip_merge_key
    if "slip_clean" not in df or (df["slip_clean"] == "").all():
        df["slip_clean"] = df["slip_raw"].map(slip_merge_key)
    if "invoice_clean" not in df or (df["invoice_clean"] == "").all():
        df["invoice_clean"] = df["matched_key"].map(merge_key)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def all_lines(con, statuses=("PROCESSED", "APPROVED", "PARTLY PAID", "PAID")) -> pd.DataFrame:
    frames = []
    q = f"SELECT id, name, tin, submission, interval_start FROM claims WHERE status IN ({','.join('?' * len(statuses))})"
    for cid, name, tin, sub, start in con.execute(q, statuses).fetchall():
        df = lines_for(con, cid)
        if not df.empty:
            frames.append(df.assign(claim_id=cid, supplier=name, tin=tin, submission=sub, interval_start=start))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def report(con, claim_id) -> bytes:
    return con.execute("SELECT report FROM claims WHERE id=?", (claim_id,)).fetchone()[0]


def events(con, claim_id=None) -> pd.DataFrame:
    q, p = "SELECT * FROM events", ()
    if claim_id:
        q, p = q + " WHERE claim_id=?", (claim_id,)
    return pd.read_sql_query(q + " ORDER BY at DESC", con, params=p)


def put_setting(con, key, value: bytes, name: str):
    con.execute("INSERT OR REPLACE INTO settings VALUES (?,?,?,?)", (key, value, name, _now()))
    con.commit()


def get_setting(con, key):
    row = con.execute("SELECT value, name, updated_at FROM settings WHERE key=?", (key,)).fetchone()
    return row if row else (None, None, None)


# ---------------------------------------------------------------------------
# Deleting users and submitted files — a copy is archived first, nothing in the history is lost
# ---------------------------------------------------------------------------
def delete_user(con, username, who, reason):
    """Remove an account. Its details are archived first; its claims, signatures, appeals and audit
    entries stay as they are (they hold the name, not a link that would break)."""
    if not reason.strip():
        raise ValueError("A reason is required to delete an account")
    if username == who:
        raise ValueError("You cannot delete your own account")
    row = con.execute("SELECT username, name, role, tin, institution, title FROM users WHERE username=?",
                      (username,)).fetchone()
    if not row:
        raise ValueError(f"Account '{username}' not found")
    if row[2] == "admin" and con.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] <= 1:
        raise ValueError("The last administrator cannot be deleted")
    n = {k: con.execute(q, (username, row[3] or "~")).fetchone()[0] for k, q in {
        "claims": "SELECT COUNT(*) FROM claims WHERE submitted_by=? OR tin=?",
        "signatures": "SELECT COUNT(*) FROM signatures WHERE username=? OR username=?",
        "events": "SELECT COUNT(*) FROM events WHERE who=? OR who=?"}.items()}
    kept = f"kept: {n['claims']} claims, {n['signatures']} signatures, {n['events']} audit entries"
    con.execute("INSERT INTO deleted_users VALUES (?,?,?,?,?,?,?,?,?,?)", (*row, kept, _now(), who, reason))
    con.execute("DELETE FROM users WHERE username=?", (username,))
    log(con, None, who, "USER DELETED", f"{username} ({row[1]}, {ROLES.get(row[2], row[2])}): {reason}; {kept}")
    con.commit()
    return kept


def deleted_users(con) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM deleted_users ORDER BY deleted_at DESC", con).fillna("")


DELETABLE_BY_OFFICER = ("SUBMITTED", "RETURNED")


def delete_claim(con, claim_id, who, role, reason):
    """Delete a submitted file. An RRA officer can delete it before analysis (Submitted / Returned);
    the administrator at any stage. The whole record (files, lines, payables, appeals) is archived first."""
    import json
    if not reason.strip():
        raise ValueError("A reason is required to delete a submission")
    st_ = status_of(con, claim_id)
    if role != "admin" and not (role == "officer" and st_ in DELETABLE_BY_OFFICER):
        raise ValueError(f"Claim #{claim_id} is {st_}: only the administrator can delete it at this stage")
    c = pd.read_sql_query("SELECT * FROM claims WHERE id=?", con, params=(claim_id,)).iloc[0]
    extra = {
        "payables": pd.read_sql_query("SELECT * FROM payables WHERE claim_id=?", con, params=(claim_id,)).to_dict("records"),
        "appeals": pd.read_sql_query("SELECT id, status, rows, reason, award_rwf FROM appeals WHERE claim_id=?", con,
                                     params=(claim_id,)).to_dict("records"),
        "claim": {k: (None if pd.isna(v) else v) for k, v in c.items()
                  if k not in ("claim_file", "letter", "report") and not isinstance(v, bytes)},
    }
    con.execute("INSERT INTO deleted_claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (claim_id, st_, c.tin, c["name"], c.submission, c.interval_start, c.interval_end, c.requested_rwf,
                 c.to_reimburse, c.paid_amount, c.claim_filename, c.claim_file, c.letter_name, c.letter,
                 json.dumps(extra, default=str), _now(), who, reason))
    for t in ("claim_keys", "payables", "appeals"):
        con.execute(f"DELETE FROM {t} WHERE claim_id=?", (claim_id,))
    con.execute("DELETE FROM claims WHERE id=?", (claim_id,))
    log(con, claim_id, who, "DELETED", f"was {st_} — {reason} (archived copy kept)")
    con.commit()


def deleted_claims(con) -> pd.DataFrame:
    return pd.read_sql_query("""SELECT claim_id, status, tin, name, submission, requested_rwf, to_reimburse,
                                paid_amount, claim_filename, letter_name, deleted_at, deleted_by, reason
                                FROM deleted_claims ORDER BY deleted_at DESC""", con)


# ---------------------------------------------------------------------------
# Pending lines: the analyst re-routes them to accepted or rejected, case by case
# ---------------------------------------------------------------------------
def pending_lines(con, claim_id) -> pd.DataFrame:
    lines = lines_for(con, claim_id)
    return lines[lines["pending_qty"] > 0.005] if not lines.empty else lines


def resolve_pending(con, claim_id, who, decisions: dict):
    """decisions: {source_row: ("Accept" | "Reject", note)}; other rows stay pending.

    Accept: the pending litres and subsidy become accepted. Reject: they become rejected, with the note as reason.
    The claim totals are recalculated (amount to reimburse = lower of requested and calculated). On an approved
    claim the extra amount becomes a payable "Pending review" for Finance. Not allowed while the claim's round
    is being signed (the signed figures must not change)."""
    status = status_of(con, claim_id)
    if status in ("SUBMITTED", "RETURNED"):
        raise ValueError(f"Claim #{claim_id} is {status}: analyse it first")
    rid = con.execute("SELECT round_id FROM claims WHERE id=?", (claim_id,)).fetchone()[0]
    if rid is not None:
        rst = con.execute("SELECT status FROM rounds WHERE id=?", (rid,)).fetchone()
        if rst and rst[0] in ("VERIFIED", "SIGNING", "SIGNED"):
            raise ValueError(f"Claim #{claim_id} is in a round being signed by the taskforce ({rst[0].title()}). "
                             "Decide its pending lines after the round is approved, or return the round first.")
    picked = {str(k): (d, (n or "").strip()) for k, (d, n) in decisions.items() if d in ("Accept", "Reject")}
    if not picked:
        raise ValueError("Choose Accept or Reject for at least one pending line")
    missing = [r for r, (d, n) in picked.items() if d == "Reject" and not n]
    if missing:
        raise ValueError(f"Give the reason for rejecting row(s) {', '.join(missing[:10])}")
    lines = lines_for(con, claim_id)
    acc_l = acc_rwf = rej_l = 0.0
    for i in lines.index:
        row = str(lines.at[i, "source_row"])
        if row not in picked or lines.at[i, "pending_qty"] <= 0.005:
            continue
        choice, note = picked[row]
        pq, ps = float(lines.at[i, "pending_qty"]), float(lines.at[i, "pending_subsidy"])
        text = f"{'Accepted' if choice == 'Accept' else 'Rejected'} after review by {who} ({_now()})" + \
               (f": {note}" if note else "")
        if choice == "Accept":
            lines.at[i, "accepted_qty"] = round(float(lines.at[i, "accepted_qty"]) + pq, 2)
            lines.at[i, "accepted_subsidy"] = round(float(lines.at[i, "accepted_subsidy"]) + ps, 2)
            acc_l, acc_rwf = acc_l + pq, acc_rwf + ps
        else:
            lines.at[i, "rejected_qty"] = round(float(lines.at[i, "rejected_qty"]) + pq, 2)
            lines.at[i, "rejected_subsidy"] = round(float(lines.at[i, "rejected_subsidy"]) + ps, 2)
            code = (str(lines.at[i, "review_reason"]) or "R8").split(" · ")[0].split(":")[0] or "R8"
            lines.at[i, "reason"] = "; ".join(filter(None, [str(lines.at[i, "reason"] or ""), f"{code} · {text}"]))
            rej_l += pq
        lines.at[i, "pending_qty"] = 0.0
        lines.at[i, "pending_subsidy"] = 0.0
        a, r_ = float(lines.at[i, "accepted_qty"]), float(lines.at[i, "rejected_qty"])
        lines.at[i, "status"] = "ACCEPTED" if r_ <= 0.005 else ("REJECTED" if a <= 0.005 else "PARTIAL")
        lines.at[i, "decision"] = "; ".join(filter(None, [str(lines.at[i, "decision"] or ""), text]))
    t = _totals(lines)
    req, before = con.execute("SELECT requested_rwf, to_reimburse FROM claims WHERE id=?", (claim_id,)).fetchone()
    t["calculated_rwf"] = t["to_reimburse"]
    t["to_reimburse"] = round(lower_of(req, t["calculated_rwf"] + 0)[0])
    con.execute(f"UPDATE claims SET lines_csv=?, {', '.join(k + '=?' for k in t)} WHERE id=?",
                (lines.to_csv(index=False), *t.values(), claim_id))
    # the EBM invoices of these lines are now accepted / rejected in the register
    for i in lines.index:
        if str(lines.at[i, "source_row"]) in picked and lines.at[i, "matched_key"]:
            con.execute("UPDATE claim_keys SET status=? WHERE claim_id=? AND ebm_key=?",
                        (lines.at[i, "status"], claim_id, str(lines.at[i, "matched_key"]).replace("/", "|")))
    log(con, claim_id, who, "PENDING DECIDED",
        f"{len(picked)} line(s): {acc_l:,.2f} L accepted ({acc_rwf:,.0f} RWF), {rej_l:,.2f} L rejected; "
        f"to reimburse {before or 0:,.0f} → {t['to_reimburse']:,.0f} RWF")
    con.commit()
    extra = round(t["to_reimburse"] - float(before or 0), 2)
    sent = 0.0
    if status in ("APPROVED", "PARTLY PAID", "PAID") and extra > 0:
        add_payable(con, claim_id, "Pending review", extra)
        _sync_claim_payment(con, claim_id, who, f"pending lines accepted: {extra:,.0f} RWF added to pay")
        sent = extra
    return {"accepted_l": round(acc_l, 2), "accepted_rwf": round(acc_rwf), "rejected_l": round(rej_l, 2),
            "to_reimburse": t["to_reimburse"], "extra_payable": sent}



def assign_appeal(con, appeal_id, username, who):
    """Give an appeal case to a person (e.g. a data scientist); '' removes the assignment."""
    if username and not con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise ValueError(f"Unknown account '{username}'")
    con.execute("UPDATE appeals SET assigned_to=?, assigned_by=?, assigned_at=? WHERE id=?",
                (username or None, who, _now() if username else None, appeal_id))
    cid = con.execute("SELECT claim_id FROM appeals WHERE id=?", (appeal_id,)).fetchone()[0]
    log(con, cid, who, f"APPEAL #{appeal_id} ASSIGNED", username or "unassigned")
    con.commit()
