"""Data extraction for the administrator: ready-made extracts, read-only SQL, Excel export and a database backup.

Queries run on an in-memory copy of the database, so nothing a query does can change the real data.
In that copy:
  * the claim lines (stored inside each claim) are expanded into a normal table `claim_lines`;
  * password hashes are removed and file contents (claim files, letters, reports) are left out.
"""
import io
import os
import re
import sqlite3
import tempfile

import pandas as pd

from engine import register as reg

BLOB_COLUMNS = {"claims": ["claim_file", "report", "letter", "lines_csv"], "appeals": ["evidence"],
                "deleted_claims": ["claim_file", "letter"], "users": ["salt", "pw"], "settings": ["value"]}

TABLES = {
    "claims": "One row per claim: supplier, interval, amounts requested / calculated / to reimburse, status, payment",
    "claim_lines": "One row per claim line after analysis: vehicle, slip, litres accepted / pending / rejected, reason",
    "payables": "Amounts to pay: first submission, appeal awards, pending lines accepted later; paid or not",
    "rounds": "Submission rounds (15th submission …) and their status",
    "signatures": "Electronic signatures of taskforce members and final approver per round",
    "appeals": "Appeals: rows contested, reason, status, award",
    "events": "Audit log: every action with date, user and note",
    "users": "Accounts (without passwords)",
    "deleted_claims": "Archive of deleted submissions",
    "deleted_users": "Archive of deleted accounts",
    "claim_keys": "EBM invoices already claimed (duplicate control)",
}

READY = {
    "All claims with amounts": """
SELECT id AS claim_no, tin, name AS supplier, submission AS round, interval_start, interval_end, status,
       submitted_at, vehicles, claimed_l, accepted_l, pending_l, rejected_l,
       requested_rwf, calculated_rwf, to_reimburse, appeal_award, paid_amount, paid_at, payment_ref, account
FROM claims ORDER BY id""",
    "All claim lines (accepted, pending, rejected)": """
SELECT claim_id, supplier, tin, submission AS round, source_row AS row_no, client, vehicle, closed_at,
       product_raw AS product, slip_clean AS ebm_slip, invoice_clean AS ebm_invoice, qty AS claimed_l,
       accepted_qty AS accepted_l, pending_qty AS pending_l, rejected_qty AS rejected_l,
       accepted_subsidy AS subsidy_paid_rwf, rejected_subsidy AS subsidy_rejected_rwf, status, reason, decision
FROM claim_lines ORDER BY claim_id, row_no""",
    "Rejected lines with reasons": """
SELECT claim_id, supplier, round, row_no, vehicle, closed_at, ebm_slip, rejected_l, subsidy_rejected_rwf, reason
FROM (SELECT claim_id, supplier, submission AS round, source_row AS row_no, vehicle, closed_at,
             slip_clean AS ebm_slip, rejected_qty AS rejected_l, rejected_subsidy AS subsidy_rejected_rwf, reason
      FROM claim_lines WHERE rejected_qty > 0)
ORDER BY claim_id, row_no""",
    "Totals per supplier": """
SELECT tin, name AS supplier, COUNT(*) AS claims, SUM(claimed_l) AS claimed_l, SUM(accepted_l) AS accepted_l,
       SUM(rejected_l) AS rejected_l, SUM(requested_rwf) AS requested_rwf, SUM(to_reimburse) AS to_reimburse,
       SUM(paid_amount) AS paid, SUM(to_reimburse) - SUM(COALESCE(paid_amount, 0)) AS outstanding
FROM claims WHERE status NOT IN ('SUBMITTED', 'RETURNED')
GROUP BY tin, name ORDER BY to_reimburse DESC""",
    "Totals per round": """
SELECT r.name AS round, r.status, COUNT(c.id) AS claims, SUM(c.accepted_l) AS accepted_l,
       SUM(c.to_reimburse) AS to_reimburse, SUM(c.paid_amount) AS paid
FROM rounds r LEFT JOIN claims c ON c.round_id = r.id
GROUP BY r.id ORDER BY r.id""",
    "Payments (first submission, appeals, pending review)": """
SELECT p.id AS payable_no, p.claim_id, c.name AS supplier, c.tin, p.kind, p.amount, p.status,
       p.paid_amount, p.paid_at, p.payment_ref, p.paid_by
FROM payables p JOIN claims c ON c.id = p.claim_id ORDER BY p.id""",
    "Litres per vehicle per day": """
SELECT supplier, client, vehicle, substr(closed_at, 1, 10) AS day, COUNT(*) AS refuels,
       SUM(qty) AS claimed_l, SUM(accepted_qty) AS accepted_l
FROM claim_lines GROUP BY supplier, client, vehicle, day ORDER BY claimed_l DESC""",
    "Rejections by rule": """
SELECT substr(reason, 1, 2) AS rule, COUNT(*) AS lines, SUM(rejected_qty) AS rejected_l,
       SUM(rejected_subsidy) AS rejected_rwf
FROM claim_lines WHERE rejected_qty > 0 GROUP BY rule ORDER BY rejected_rwf DESC""",
    "Taskforce signatures": """
SELECT r.name AS round, s.name AS signatory, s.title AS role, s.decision, s.signed_at, s.comment
FROM signatures s JOIN rounds r ON r.id = s.round_id ORDER BY r.id, s.signed_at""",
    "Appeals": """
SELECT a.id AS appeal_no, a.claim_id, c.name AS supplier, a.submitted_at, a.status, a.reason,
       a.award_l, a.award_rwf, a.decided_by, a.decided_at, a.decision_note
FROM appeals a LEFT JOIN claims c ON c.id = a.claim_id ORDER BY a.id""",
    "Audit log": "SELECT claim_id, at, who, action, note FROM events ORDER BY at",
    "Accounts": "SELECT username, name, role, tin, institution, title, active, expires_at FROM users ORDER BY role, username",
}

_ALLOWED = re.compile(r"^\s*(select|with)\b", re.I)


def snapshot(con) -> sqlite3.Connection:
    """In-memory copy of the database, safe to query, with the claim lines as a table."""
    mem = sqlite3.connect(":memory:", check_same_thread=False)
    con.backup(mem)
    for table, cols in BLOB_COLUMNS.items():
        have = {r[1] for r in mem.execute(f"PRAGMA table_info({table})")}
        for c in cols:
            if c in have:
                mem.execute(f"UPDATE {table} SET {c} = NULL")
    lines = reg.all_lines(con, statuses=("PROCESSED", "APPROVED", "PARTLY PAID", "PAID"))
    if lines.empty:
        lines = pd.DataFrame(columns=["claim_id", "supplier", "tin", "submission", "source_row", "client", "vehicle",
                                      "closed_at", "product_raw", "slip_clean", "invoice_clean", "qty",
                                      "accepted_qty", "pending_qty", "rejected_qty", "accepted_subsidy",
                                      "pending_subsidy", "rejected_subsidy", "status", "reason", "decision"])
    lines = lines.copy()
    for c in lines.columns:
        if lines[c].dtype == "datetime64[ns]" or "datetime" in str(lines[c].dtype):
            lines[c] = lines[c].astype(str)
    lines.to_sql("claim_lines", mem, index=False)
    mem.commit()
    return mem


def run_query(con, sql: str, limit: int | None = None) -> pd.DataFrame:
    """Run one SELECT (or WITH … SELECT) on a safe copy of the data."""
    sql = sql.strip().rstrip(";").strip()
    if not _ALLOWED.match(sql):
        raise ValueError("Only queries that read data are allowed: start with SELECT (or WITH).")
    if ";" in sql:
        raise ValueError("One query at a time (remove the ';' in the middle).")
    mem = snapshot(con)
    try:
        df = pd.read_sql_query(sql, mem)
    except Exception as e:                     # show SQLite's message (column or table name wrong, …)
        raise ValueError(f"Query error: {e}") from None
    finally:
        mem.close()
    return df.head(limit) if limit else df


def to_excel(frames: dict) -> bytes:
    b = io.BytesIO()
    with pd.ExcelWriter(b, engine="openpyxl") as w:
        for name, df in frames.items():
            df.to_excel(w, sheet_name=re.sub(r"[\[\]:*?/\\]", "", name)[:31], index=False)
    return b.getvalue()


def all_tables_excel(con) -> bytes:
    """Every table (without passwords and file contents) in one workbook, one sheet per table."""
    mem = snapshot(con)
    try:
        frames = {}
        for t in TABLES:
            if t in ("claim_keys",):
                continue
            df = pd.read_sql_query(f"SELECT * FROM {t}", mem)
            frames[t] = df.drop(columns=[c for c in BLOB_COLUMNS.get(t, []) if c in df], errors="ignore")
        return to_excel(frames)
    finally:
        mem.close()


def database_backup(con) -> bytes:
    """Complete copy of the database file (all data and files) — to keep safely or restore."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        out = sqlite3.connect(path)
        con.backup(out)
        out.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.remove(path)


def columns(con) -> dict:
    """{table: [columns]} as seen by queries (for the help panel)."""
    mem = snapshot(con)
    try:
        return {t: [r[1] for r in mem.execute(f"PRAGMA table_info({t})") if r[1] not in BLOB_COLUMNS.get(t, [])]
                for t in TABLES}
    finally:
        mem.close()
