"""Batch report (Inter-ministerial Taskforce): the analyses of the 'Fuel Subsidy Reimbursement Claims' deck,
produced from the data — batches reimbursed before the platform (batch history) plus every submission round
of the platform.

A *batch* is a submission round. Litres "pending / rejected" = litres not accepted (pending review + rejected).
"Claimed RWF" = subsidy requested by the OMC; "Reimburse RWF" = amount submitted for reimbursement.
"""
from datetime import datetime
from pathlib import Path

import pandas as pd

HISTORY_FILE = Path(__file__).resolve().parent.parent / "reference" / "batch_history_1_15.csv"
COLS = ["batch", "omc", "tin", "period_start", "period_end", "vehicles", "claimed_l", "accepted_l", "pending_l",
        "claimed_rwf", "reimburse_rwf", "note"]
LOW_ACCEPTANCE = 80.0          # % of litres: flagged "low"
WEAK_BATCH = 60.0              # % of litres: weak batch in a profile
RATE_TOLERANCE = 0.02          # RWF per litre more than 2 % from the scheme median is flagged
CATCH_UP_DAYS = 31             # a claim covering more than a month is a catch-up claim
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ------------------------------------------------------------------------------------------------ history
def seed_history(con):
    """Load batches 1–15 (from the Taskforce report) once, on a new database."""
    from engine import register as reg
    if reg.get_setting(con, "batch_history_seeded")[0] is not None:
        return
    if con.execute("SELECT COUNT(*) FROM batch_history").fetchone()[0] == 0 and HISTORY_FILE.exists():
        load_history(con, pd.read_csv(HISTORY_FILE, dtype={"tin": str}), "system", replace=True)
    reg.put_setting(con, "batch_history_seeded", b"1", "system")


def load_history(con, df: pd.DataFrame, who: str, replace: bool = False) -> int:
    """Import batch history (one row per OMC per batch). Columns as in COLS; 'note' optional."""
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    missing = [c for c in COLS if c not in df.columns and c != "note"]
    if missing:
        raise ValueError("Missing column(s): " + ", ".join(missing))
    if "note" not in df:
        df["note"] = ""
    df["tin"] = df["tin"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    for c in ("period_start", "period_end"):
        df[c] = df[c].map(_date)
    if df[["period_start", "period_end"]].isna().any().any():
        raise ValueError("Some period dates could not be read (use dd/mm/yyyy or yyyy-mm-dd)")
    if replace:
        con.execute("DELETE FROM batch_history")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = [tuple(None if pd.isna(r[c]) else r[c] for c in COLS) + (now, who) for _, r in df.iterrows()]
    con.executemany(f"INSERT INTO batch_history ({', '.join(COLS)}, loaded_at, loaded_by) VALUES "
                    f"({', '.join('?' * (len(COLS) + 2))})", rows)
    con.commit()
    return len(rows)


def _date(v):
    """yyyy-mm-dd, Excel dates, or dd/mm/yyyy → 'yyyy-mm-dd' (None if unreadable)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    t = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(t, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


# ------------------------------------------------------------------------------------------------ data
def lines(con, tin: str | None = None) -> pd.DataFrame:
    """One row per OMC per batch: history + platform rounds."""
    h = pd.read_sql_query(f"SELECT {', '.join(COLS)} FROM batch_history", con, dtype={"tin": str})
    h["source"] = "Batch history"
    s = pd.read_sql_query("""
        SELECT r.number AS batch, c.name AS omc, c.tin, c.interval_start AS period_start,
               c.interval_end AS period_end, c.vehicles, c.claimed_l, c.accepted_l,
               COALESCE(c.pending_l, 0) + COALESCE(c.rejected_l, 0) AS pending_l,
               COALESCE(NULLIF(c.requested_rwf, 0), c.claimed_rwf) AS claimed_rwf, c.to_reimburse AS reimburse_rwf,
               'claim #' || c.id || ' · ' || r.status AS note
        FROM claims c JOIN rounds r ON r.id = c.round_id
        WHERE c.status NOT IN ('SUBMITTED', 'RETURNED')""", con, dtype={"tin": str})
    s["source"] = "Platform"
    frames = [f for f in (h, s) if not f.empty]
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLS + ["source"])
    if df.empty:
        return df
    for c in ("period_start", "period_end"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ("claimed_l", "accepted_l", "pending_l", "claimed_rwf", "reimburse_rwf"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["batch"] = df["batch"].astype(int)
    # one name per TIN (the latest one used)
    names = df.sort_values("batch").groupby("tin")["omc"].last()
    df["omc"] = df["tin"].map(names).fillna(df["omc"])
    if tin:
        df = df[df.tin == str(tin)]
    return df.sort_values(["batch", "omc"]).reset_index(drop=True)


def pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def period_text(start, end) -> str:
    if pd.isna(start) or pd.isna(end):
        return "—"
    if start.month == end.month:
        return f"{start.day}–{end.day} {MONTHS[end.month - 1]}"
    return f"{start.day} {MONTHS[start.month - 1]}–{end.day} {MONTHS[end.month - 1]}"


# ------------------------------------------------------------------------------------------------ analyses
def overview(df) -> dict:
    c, a, p = df.claimed_l.sum(), df.accepted_l.sum(), df.pending_l.sum()
    cr, rr = df.claimed_rwf.sum(), df.reimburse_rwf.sum()
    first, last = df.period_start.min(), df.period_end.max()
    return {"batches": int(df.batch.nunique()), "first_batch": int(df.batch.min()) if len(df) else 0,
            "last_batch": int(df.batch.max()) if len(df) else 0, "omcs": int(df.tin.nunique()),
            "claimed_l": c, "accepted_l": a, "pending_l": p, "accepted_pct": pct(a, c), "pending_pct": pct(p, c),
            "claimed_rwf": cr, "reimburse_rwf": rr, "withheld_rwf": cr - rr,
            "reimburse_pct": pct(rr, cr), "withheld_pct": pct(cr - rr, cr),
            "from": first, "to": last}


def by_batch(df) -> pd.DataFrame:
    g = df.groupby("batch").agg(omcs=("tin", "nunique"), claimed_l=("claimed_l", "sum"), accepted_l=("accepted_l", "sum"),
                                pending_l=("pending_l", "sum"), claimed_rwf=("claimed_rwf", "sum"),
                                reimburse_rwf=("reimburse_rwf", "sum")).reset_index()
    g["payout_pct"] = [pct(r, c) for r, c in zip(g.reimburse_rwf, g.claimed_rwf)]
    g["accepted_pct"] = [pct(a, c) for a, c in zip(g.accepted_l, g.claimed_l)]
    g.insert(0, "Batch", "B" + g.batch.astype(str))
    return g


def by_omc(df) -> pd.DataFrame:
    total_r = df.reimburse_rwf.sum()
    g = df.groupby(["tin", "omc"]).agg(batches=("batch", "nunique"), claimed_l=("claimed_l", "sum"),
                                       accepted_l=("accepted_l", "sum"), pending_l=("pending_l", "sum"),
                                       claimed_rwf=("claimed_rwf", "sum"), reimburse_rwf=("reimburse_rwf", "sum")
                                       ).reset_index()
    g["accepted_pct"] = [pct(a, c) for a, c in zip(g.accepted_l, g.claimed_l)]
    g["low"] = g.accepted_pct < LOW_ACCEPTANCE
    g["share_pct"] = [pct(r, total_r) for r in g.reimburse_rwf]
    return g.sort_values("reimburse_rwf", ascending=False).reset_index(drop=True)


def coverage(df):
    """(matrix batch × OMC with periods, set of (batch, tin) whose period overlaps another claim of the same OMC)."""
    overl = {(o["batch_a"], o["tin"]) for o in overlaps(df)} | {(o["batch_b"], o["tin"]) for o in overlaps(df)}
    omcs = by_omc(df)[["tin", "omc"]]
    m = pd.DataFrame({"Batch": [f"B{b}" for b in sorted(df.batch.unique())]})
    for tin, name in zip(omcs.tin, omcs.omc):
        col = []
        for b in sorted(df.batch.unique()):
            x = df[(df.batch == b) & (df.tin == tin)]
            if x.empty:
                col.append("–")
            else:
                texts = [period_text(r.period_start, r.period_end) for r in x.itertuples()]
                col.append(" + ".join(texts) + (" *" if (b, tin) in overl else ""))
        m[name] = col
    total = {"Batch": "Total"}
    total.update({name: str(int(df[df.tin == tin].batch.nunique())) for tin, name in zip(omcs.tin, omcs.omc)})
    return pd.concat([m, pd.DataFrame([total])], ignore_index=True), overl


def overlaps(df) -> list:
    out = []
    for tin, g in df.groupby("tin"):
        g = g.sort_values("period_start").reset_index(drop=True)
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                a, b = g.iloc[i], g.iloc[j]
                s, e = max(a.period_start, b.period_start), min(a.period_end, b.period_end)
                if s <= e:
                    out.append({"tin": tin, "omc": a.omc, "batch_a": int(a.batch), "batch_b": int(b.batch),
                                "from": s, "to": e, "days": (e - s).days + 1})
    return out


def gaps(df) -> list:
    """Periods between two claims of the same OMC with no claim (from its first claim to its last one)."""
    out = []
    for tin, g in df.groupby("tin"):
        g = g.sort_values("period_start")
        reach = None
        for r in g.itertuples():
            if reach is not None and r.period_start > reach + pd.Timedelta(days=1):
                out.append({"tin": tin, "omc": r.omc, "from": reach + pd.Timedelta(days=1),
                            "to": r.period_start - pd.Timedelta(days=1),
                            "days": (r.period_start - reach).days - 1, "before_batch": int(r.batch)})
            reach = r.period_end if reach is None else max(reach, r.period_end)
    return out


def checks(df) -> pd.DataFrame:
    """Points to raise with the OMCs — the same kind of observations as in the Taskforce report."""
    rows = []
    for o in overlaps(df):
        rows.append((o["omc"], o["tin"], "Overlapping periods",
                     f"B{o['batch_a']} and B{o['batch_b']} both cover {period_text(o['from'], o['to'])} "
                     f"({o['days']} day{'s' if o['days'] != 1 else ''}) — confirm the same fuel is not reimbursed twice."))
    for g in gaps(df):
        rows.append((g["omc"], g["tin"], "Gap with no claim",
                     f"No claim for {period_text(g['from'], g['to'])} ({g['days']} days) before B{g['before_batch']}."))
    rate = df[df.claimed_l > 0].assign(rpl=lambda d: d.claimed_rwf / d.claimed_l)
    med = rate.rpl.median() if not rate.empty else 0
    for r in rate.itertuples():
        if med and abs(r.rpl - med) / med > RATE_TOLERANCE:
            rows.append((r.omc, r.tin, "Rate per litre",
                         f"B{r.batch} claimed at about RWF {r.rpl:,.0f} per litre against RWF {med:,.0f} in most claims "
                         "— confirm the rate applied."))
    for r in df.itertuples():
        if pd.isna(r.vehicles) or not r.vehicles:
            rows.append((r.omc, r.tin, "No vehicles recorded",
                         f"B{r.batch}: {r.claimed_l:,.0f} L with no number of vehicles — confirm the fleet and "
                         "consumption records."))
        if r.claimed_l >= 10_000 and r.claimed_l % 1000 == 0:
            rows.append((r.omc, r.tin, "Round figure",
                         f"B{r.batch}: exactly {r.claimed_l:,.0f} L claimed — metered figures are rarely round."))
        days = (r.period_end - r.period_start).days + 1 if pd.notna(r.period_end) else 0
        if days > CATCH_UP_DAYS:
            rows.append((r.omc, r.tin, "Catch-up claim",
                         f"B{r.batch} covers {days} days ({period_text(r.period_start, r.period_end)}) in one claim — "
                         "regular claims are easier to verify."))
        a = pct(r.accepted_l, r.claimed_l)
        if r.claimed_l and a < WEAK_BATCH:
            rows.append((r.omc, r.tin, "Low acceptance",
                         f"B{r.batch}: only {a:.1f}% of litres accepted ({r.pending_l:,.0f} L pending / rejected)."))
    out = pd.DataFrame(rows, columns=["OMC", "TIN", "Check", "Detail"])
    order = {"Overlapping periods": 0, "Rate per litre": 1, "Low acceptance": 2, "No vehicles recorded": 3,
             "Round figure": 4, "Gap with no claim": 5, "Catch-up claim": 6}
    return out.sort_values(["Check", "OMC"], key=lambda s: s.map(order) if s.name == "Check" else s).reset_index(drop=True)


def profile(df, tin) -> dict:
    """Everything for one OMC page: figures, batch table and a one-line headline."""
    d = df[df.tin == str(tin)].sort_values("batch")
    if d.empty:
        return {}
    total_r = df.reimburse_rwf.sum()
    t = d.assign(**{"Accepted %": [pct(a, c) for a, c in zip(d.accepted_l, d.claimed_l)]})
    table = pd.DataFrame({
        "Batch": "B" + t.batch.astype(str), "Period": [period_text(a, b) for a, b in zip(t.period_start, t.period_end)],
        "Vehicles": t.vehicles, "Claimed L": t.claimed_l, "Accepted L": t.accepted_l, "Pending L": t.pending_l,
        "Accepted %": t["Accepted %"], "Claimed RWF": t.claimed_rwf, "Reimburse RWF": t.reimburse_rwf,
        "Source": t.source})
    tot = {"Batch": "Total", "Period": f"{len(d)} batch{'es' if len(d) != 1 else ''}",
           "Vehicles": pd.to_numeric(d.vehicles, errors="coerce").sum(min_count=1),
           "Claimed L": d.claimed_l.sum(), "Accepted L": d.accepted_l.sum(), "Pending L": d.pending_l.sum(),
           "Accepted %": pct(d.accepted_l.sum(), d.claimed_l.sum()), "Claimed RWF": d.claimed_rwf.sum(),
           "Reimburse RWF": d.reimburse_rwf.sum(), "Source": ""}
    acc = t["Accepted %"].tolist()
    weak = t[t["Accepted %"] < 90]
    if len(d) == 1:
        head = f"One batch (B{int(d.batch.iloc[0])}), {acc[0]:.0f}% of litres accepted."
    elif len(d) <= 3 and not weak.empty:
        head = ("Batches: " + ", ".join(f"B{int(b)} {a:.0f}%" for b, a in zip(t.batch, acc)) +
                f" of litres accepted; {d.pending_l.sum():,.0f} L pending / rejected.")
    elif weak.empty:
        head = f"Consistent: {min(acc):.0f}–{max(acc):.0f}% of litres accepted in every one of its {len(d)} batches."
    else:
        worst = weak.sort_values("Accepted %").iloc[0]
        recent = t.tail(3)
        head = (f"Weakest batch B{int(worst.batch)} ({worst['Accepted %']:.1f}%, {worst.pending_l:,.0f} L pending); "
                f"last {len(recent)} batch{'es' if len(recent) != 1 else ''} at "
                f"{recent['Accepted %'].min():.0f}–{recent['Accepted %'].max():.0f}% accepted.")
    return {"omc": d.omc.iloc[-1], "tin": str(tin), "batches": len(d), "claimed_l": d.claimed_l.sum(),
            "accepted_pct": tot["Accepted %"], "reimburse_rwf": d.reimburse_rwf.sum(),
            "share_pct": pct(d.reimburse_rwf.sum(), total_r), "pending_l": d.pending_l.sum(),
            "headline": head, "table": pd.concat([table, pd.DataFrame([tot])], ignore_index=True),
            "checks": checks(df)[lambda c: c.TIN == str(tin)]}
