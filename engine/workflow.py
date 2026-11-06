"""System settings (admin), submission rounds and electronic signatures.

Round flow (replaces the signed paper report):

  1. RRA officer verifies each claim (Processing) -> claim status PROCESSED.
  2. The officer consolidates the verified claims into a submission round; the
     system gives it the next number ("15th submission (November 2026)").   VERIFIED
  3. Every taskforce member approves (or returns) it in the system; each approval
     is their electronic signature.                                         SIGNING -> SIGNED
  4. The final approver approves; all claims become APPROVED and payable.  APPROVED
  A taskforce member or the approver can return the round with a comment:   RETURNED
  its claims go back to the officer.
"""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from . import register as reg

DEFAULTS = {
    "subsidy_rates": {"DIESEL": 438.0, "PETROL": 438.0},   # official subsidy, RWF per litre
    "next_round_number": 15,
    "strict_form": True,             # suppliers must use the official claim form
    "default_signatory_password": "Change@2026",
}
DEFAULT_SIGNATORIES = [
    "MUKANGABO Beatha (RURA) Chair",
    "Mutabazi Eric (MINECOFIN), Co-chair",
    "Mukamurera Venerande (RURA)",
    "Tuyizere Aimable (RURA)",
    "Rubayiza Noel (RURA)",
    "Ntihemuka David (RRA)",
    "Ndahayo Capiton (MININFRA)",
    "Mugabe Emmanuel (RURA)",
]
DEFAULT_APPROVER = "RUGIGANA Evariste"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def setting(con, key):
    blob, _, _ = reg.get_setting(con, f"cfg:{key}")
    if blob is None:
        return DEFAULTS.get(key)
    return json.loads(blob)


def set_setting(con, key, value, who=""):
    reg.put_setting(con, f"cfg:{key}", json.dumps(value).encode(), who)


def subsidy_rates(con) -> dict:
    return {k: float(v) for k, v in setting(con, "subsidy_rates").items()}


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ---------------------------------------------------------------------------
# Signatories
# ---------------------------------------------------------------------------
def signatories(con) -> pd.DataFrame:
    return pd.read_sql_query("""SELECT username, name, institution, title FROM users
                                WHERE role='taskforce' AND active=1 ORDER BY
                                CASE WHEN lower(title) LIKE 'chair%' THEN 0 WHEN lower(title) LIKE 'co-chair%' THEN 1
                                ELSE 2 END, name""", con).fillna("")


def approvers(con) -> pd.DataFrame:
    return pd.read_sql_query("SELECT username, name, institution, title FROM users WHERE role='approver' AND active=1",
                             con).fillna("")


def seed_signatories(con):
    """Create the taskforce and approver accounts once (uniform usernames, password to change at first use)."""
    pw = setting(con, "default_signatory_password")
    made = reg.create_signatories(con, DEFAULT_SIGNATORIES, pw, role="taskforce")
    made += reg.create_signatories(con, [DEFAULT_APPROVER], pw, role="approver")
    return made


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------
def unassigned_verified(con) -> pd.DataFrame:
    df = reg.claims(con, status=["PROCESSED"])
    rid = pd.read_sql_query("SELECT id, round_id FROM claims", con).set_index("id")["round_id"]
    return df[df["id"].map(rid).isna()]


def create_round(con, claim_ids: list, who: str, note: str = "") -> int:
    if not claim_ids:
        raise ValueError("Select at least one verified claim")
    free = set(unassigned_verified(con)["id"])
    bad = [c for c in claim_ids if c not in free]
    if bad:
        raise ValueError(f"Claim(s) {', '.join(map(str, bad))} are not verified or already in a round")
    used = con.execute("SELECT MAX(number) FROM rounds").fetchone()[0]
    try:                                    # batches already reimbursed before the system (batch history)
        hist = con.execute("SELECT MAX(batch) FROM batch_history").fetchone()[0]
    except Exception:
        hist = None
    number = max(int(setting(con, "next_round_number")), (used or 0) + 1, (hist or 0) + 1)
    name = f"{ordinal(number)} submission ({datetime.now():%B %Y})"
    cur = con.execute("INSERT INTO rounds (number, name, created_at, created_by, status, note) VALUES (?,?,?,?,?,?)",
                      (number, name, _now(), who, "VERIFIED", note))
    rid = cur.lastrowid
    for c in claim_ids:
        con.execute("UPDATE claims SET round_id=?, submission=? WHERE id=?", (rid, name, int(c)))
        reg.log(con, int(c), who, "IN ROUND", name)
    con.commit()
    set_setting(con, "next_round_number", number + 1, who)
    return rid


def rounds(con) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM rounds ORDER BY id DESC", con)
    if df.empty:
        return df
    tot = pd.read_sql_query("""SELECT round_id, COUNT(*) AS claims, SUM(claimed_rwf) AS claimed_rwf,
                               SUM(to_reimburse) AS to_reimburse, SUM(rejected_rwf + pending_rwf) AS not_paid_rwf
                               FROM claims WHERE round_id IS NOT NULL GROUP BY round_id""", con)
    df = df.merge(tot, left_on="id", right_on="round_id", how="left").drop(columns=["round_id"])
    n_sig = len(signatories(con))
    signed = pd.read_sql_query("SELECT round_id, COUNT(DISTINCT username) AS signed FROM signatures "
                               "WHERE decision='APPROVED' AND title != 'Final approver' GROUP BY round_id", con)
    df = df.merge(signed, left_on="id", right_on="round_id", how="left").drop(columns=["round_id"])
    df["signed"] = df["signed"].fillna(0).astype(int)
    df["signatories"] = n_sig
    return df


def round_claims(con, round_id) -> pd.DataFrame:
    ids = [r for (r,) in con.execute("SELECT id FROM claims WHERE round_id=?", (round_id,))]
    df = reg.claims(con)
    return df[df["id"].isin(ids)]


def round_signatures(con, round_id) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM signatures WHERE round_id=? ORDER BY signed_at", con, params=(round_id,))


def _round_status(con, round_id):
    row = con.execute("SELECT status FROM rounds WHERE id=?", (round_id,)).fetchone()
    if not row:
        raise ValueError(f"Round #{round_id} not found")
    return row[0]


def sign_round(con, round_id, user: dict, approve: bool, comment: str = ""):
    """Taskforce member's electronic signature (approve) or return with a comment."""
    if user["role"] not in ("taskforce", "admin"):
        raise ValueError("Only taskforce members sign a submission round")
    st = _round_status(con, round_id)
    if st not in ("VERIFIED", "SIGNING"):
        raise ValueError(f"This round is {st}; it cannot be signed now")
    if con.execute("SELECT 1 FROM signatures WHERE round_id=? AND username=? AND title != 'Final approver'",
                   (round_id, user["username"])).fetchone():
        raise ValueError("You have already signed this round")
    if not approve and not comment.strip():
        raise ValueError("Explain why the round is returned")
    info = reg.user_info(con, user["username"]) or {}
    title = " ".join(x for x in [info.get("institution") and f"({info['institution']})", info.get("title")] if x)
    con.execute("INSERT INTO signatures VALUES (?,?,?,?,?,?,?)",
                (round_id, user["username"], user["name"], title or "member",
                 "APPROVED" if approve else "RETURNED", comment, _now()))
    if not approve:
        _return_round(con, round_id, user["name"], comment)
        return "RETURNED"
    n_sig = len(signatories(con))
    done = con.execute("SELECT COUNT(DISTINCT username) FROM signatures WHERE round_id=? AND decision='APPROVED' "
                       "AND title != 'Final approver'", (round_id,)).fetchone()[0]
    new = "SIGNED" if done >= n_sig else "SIGNING"
    con.execute("UPDATE rounds SET status=? WHERE id=?", (new, round_id))
    con.commit()
    return new


def approve_round(con, round_id, user: dict, approve: bool = True, comment: str = ""):
    """Final approval: every claim of the round becomes APPROVED and payable."""
    if user["role"] not in ("approver", "admin"):
        raise ValueError("Only the final approver approves a submission round")
    st = _round_status(con, round_id)
    if st != "SIGNED" and not (st in ("VERIFIED", "SIGNING") and len(signatories(con)) == 0):
        raise ValueError(f"The round is {st}: all taskforce members must approve it first")
    con.execute("INSERT INTO signatures VALUES (?,?,?,?,?,?,?)",
                (round_id, user["username"], user["name"], "Final approver",
                 "APPROVED" if approve else "RETURNED", comment, _now()))
    if not approve:
        if not comment.strip():
            raise ValueError("Explain why the round is returned")
        _return_round(con, round_id, user["name"], comment)
        return "RETURNED"
    for cid in round_claims(con, round_id)["id"]:
        reg.approve(con, int(cid), user["name"])
    con.execute("UPDATE rounds SET status='APPROVED', approved_at=?, approved_by=? WHERE id=?",
                (_now(), user["name"], round_id))
    con.commit()
    return "APPROVED"


def _return_round(con, round_id, who, comment):
    con.execute("UPDATE rounds SET status='RETURNED', note=? WHERE id=?", (f"Returned by {who}: {comment}", round_id))
    for (cid,) in con.execute("SELECT id FROM claims WHERE round_id=?", (round_id,)).fetchall():
        reg.log(con, cid, who, "ROUND RETURNED", comment)
    con.execute("UPDATE claims SET round_id=NULL WHERE round_id=?", (round_id,))
    con.commit()


def awaiting(con, user: dict) -> dict:
    """What is waiting for this user (shown on Home)."""
    r = rounds(con)
    out = {}
    if user["role"] in ("officer", "admin"):
        out["to_analyse"] = int((reg.claims(con)["status"] == "SUBMITTED").sum())
        out["to_consolidate"] = len(unassigned_verified(con))
        out["appeals_to_verify"] = int(con.execute("SELECT COUNT(*) FROM appeals WHERE status='OPEN'").fetchone()[0])
        out["appeals_assigned"] = int(con.execute("SELECT COUNT(*) FROM appeals WHERE status='OPEN' AND assigned_to=?",
                                                  (user["username"],)).fetchone()[0])
    if user["role"] in ("taskforce", "admin") and not r.empty:
        mine = {x for (x,) in con.execute("SELECT round_id FROM signatures WHERE username=?", (user["username"],))}
        out["to_sign"] = int((r["status"].isin(["VERIFIED", "SIGNING"]) & ~r["id"].isin(mine)).sum())
    if user["role"] in ("approver", "admin"):
        out["to_approve"] = int((r["status"] == "SIGNED").sum()) if not r.empty else 0
        out["appeals_to_approve"] = int(con.execute("SELECT COUNT(*) FROM appeals WHERE status='VERIFIED'").fetchone()[0])
    if user["role"] in ("finance", "admin"):
        out["to_pay"] = int(con.execute("SELECT COUNT(*) FROM payables WHERE status != 'PAID'").fetchone()[0])
    return out
