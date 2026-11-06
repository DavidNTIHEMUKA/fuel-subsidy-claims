"""Shared look and helpers: dark blue, green, orange and white."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from engine import register as reg

NAVY = "#0B2B57"
BLUE = "#1460AA"
GREEN = "#1B7A3E"
ORANGE = "#E8820E"
ORANGE_TEXT = "#A8550A"
WHITE = "#FFFFFF"
GROUND = "#EEF3F9"

STATUS_STYLE = {
    "SUBMITTED": (GROUND, NAVY), "PROCESSED": ("#E3ECF8", BLUE), "APPROVED": (NAVY, WHITE),
    "PARTLY PAID": ("#FDEBD3", ORANGE_TEXT), "PAID": ("#E1F2E7", GREEN), "RETURNED": ("#FDEBD3", ORANGE_TEXT),
    "OPEN": ("#FDEBD3", ORANGE_TEXT), "UPHELD": ("#E1F2E7", GREEN), "PARTLY UPHELD": ("#E1F2E7", GREEN),
    "DISMISSED": (GROUND, NAVY), "ACCEPTED": ("#E1F2E7", GREEN), "PARTIAL": ("#FDEBD3", ORANGE_TEXT),
    "REJECTED": ("#FDEBD3", ORANGE_TEXT), "REVIEW": ("#E3ECF8", BLUE),
}

CSS = f"""
<style>
  .block-container, [data-testid="stMainBlockContainer"] {{padding-top: 5rem; max-width: 1320px;}}
  header[data-testid="stHeader"] {{background: {NAVY};}}
  header[data-testid="stHeader"] a, header[data-testid="stHeader"] span,
  header[data-testid="stHeader"] p {{color: #DCE6F3 !important;}}
  header[data-testid="stHeader"] [aria-current="page"] p,
  header[data-testid="stHeader"] [aria-current="page"] span {{color: {WHITE} !important; font-weight: 700;}}
  h1, h2, h3 {{color: {NAVY}; letter-spacing: -0.01em;}}

  .fs-hero {{background: {NAVY}; color: {WHITE}; border-radius: 16px; padding: 40px 44px; position: relative;
            overflow: hidden; margin-bottom: 22px;}}
  .fs-hero h1 {{color: {WHITE}; font-size: 40px; margin: 6px 0 10px; line-height: 1.1;}}
  .fs-hero p {{color: #DCE6F3; font-size: 18px; max-width: 720px; margin: 0;}}
  .fs-hero .kicker {{color: {ORANGE}; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; font-size: 13px;}}
  .fs-hero .bars {{display: flex; gap: 8px; margin-top: 26px;}}
  .fs-hero .bars span {{height: 6px; width: 64px; border-radius: 3px;}}

  .fs-band {{background: {NAVY}; color: {WHITE}; border-radius: 12px; padding: 18px 24px; margin-bottom: 18px;
            border-left: 0; border-bottom: 4px solid {GREEN};}}
  .fs-band h2 {{color: {WHITE}; margin: 0; font-size: 24px;}}
  .fs-band p {{color: #DCE6F3; margin: 4px 0 0;}}

  .fs-card {{background: {WHITE}; border: 1px solid #D8E0EB; border-radius: 12px; padding: 18px 20px; height: 100%;}}
  .fs-card .num {{font-size: 28px; font-weight: 800; color: {NAVY}; line-height: 1.15;}}
  .fs-card .lbl {{color: #52607A; font-size: 14px;}}
  .fs-card .sub {{color: #52607A; font-size: 13px; margin-top: 2px;}}
  .fs-card.green {{border-top: 5px solid {GREEN};}} .fs-card.green .num {{color: {GREEN};}}
  .fs-card.orange {{border-top: 5px solid {ORANGE};}} .fs-card.orange .num {{color: {ORANGE_TEXT};}}
  .fs-card.navy {{border-top: 5px solid {NAVY};}}
  .fs-card.blue {{border-top: 5px solid {BLUE};}} .fs-card.blue .num {{color: {BLUE};}}

  .fs-step {{background: {WHITE}; border: 1px solid #D8E0EB; border-radius: 12px; padding: 18px; height: 100%;}}
  .fs-step .dot {{width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center;
                 justify-content: center; font-weight: 800; color: {WHITE}; margin-bottom: 10px;}}
  .fs-step b {{color: {NAVY}; font-size: 17px;}}
  .fs-step p {{color: #52607A; margin: 4px 0 0; font-size: 14px;}}

  /* ---------- softer page background with green / orange touches ---------- */
  [data-testid="stAppViewContainer"] {{background:
      radial-gradient(360px 230px at 100% 0%, rgba(232,130,14,.95), rgba(232,130,14,.35) 45%, transparent 72%),
      radial-gradient(380px 230px at 0% 100%, rgba(27,122,62,.95), rgba(27,122,62,.35) 45%, transparent 72%),
      linear-gradient(180deg, #0B2B57 0px, #174A86 120px, #5FA9E0 210px, #9ACFF2 290px, #B3DBF6 620px, #C6E5F9 100%);}}
  .fs-sec {{display:flex;align-items:center;gap:10px;font-size:22px;font-weight:800;color:{NAVY};margin:4px 0 12px}}
  .fs-sec .bar {{display:inline-block;width:8px;height:26px;border-radius:4px}}
  .st-key-tint_green {{background:linear-gradient(135deg,#CFE8D7 0%,#E2F2E7 100%);border:1px solid #9FD0AF;
                       border-radius:16px;padding:18px 20px 22px}}
  .st-key-tint_orange {{background:linear-gradient(135deg,#FCE2C2 0%,#FFF0DD 100%);border:1px solid #F0BE82;
                        border-radius:16px;padding:18px 20px 22px}}
  .fs-card, .fs-step {{box-shadow:0 3px 10px rgba(11,43,87,.14);}}

  .chip {{display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 13px; font-weight: 700;}}

  /* ---------- buttons: primary = green, secondary = white with navy, download = navy ---------- */
  .stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {{
      border-radius: 10px; min-height: 44px; font-weight: 600; padding: 0 18px;
      transition: background .15s, border-color .15s, box-shadow .15s;}}
  .stButton > button[kind="secondary"], .stFormSubmitButton > button[kind="secondary"] {{
      background: {WHITE}; border: 1.5px solid {NAVY}; color: {NAVY};}}
  .stButton > button[kind="secondary"]:hover, .stFormSubmitButton > button[kind="secondary"]:hover {{
      background: {GROUND}; border-color: {BLUE}; color: {NAVY};}}
  .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
      background: {GREEN}; border: 1.5px solid {GREEN}; color: {WHITE};}}
  .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {{
      background: #156532; border-color: #156532; color: {WHITE}; box-shadow: 0 2px 8px rgba(27,122,62,.25);}}
  .stButton > button[kind="primary"] p, .stFormSubmitButton > button[kind="primary"] p,
  .stDownloadButton > button p {{color: inherit !important;}}
  .stDownloadButton > button {{background: {NAVY}; border: 1.5px solid {NAVY}; color: {WHITE} !important;}}
  .stDownloadButton > button:hover {{background: {BLUE}; border-color: {BLUE}; color: {WHITE} !important;}}
  .stButton > button:disabled, .stFormSubmitButton > button:disabled, .stDownloadButton > button:disabled {{
      background: #C9D3E0 !important; border-color: #C9D3E0 !important; color: #52607A !important;
      cursor: not-allowed; box-shadow: none;}}
  .fs-danger .stButton > button {{background: {WHITE}; border: 1.5px solid {ORANGE}; color: {ORANGE_TEXT};}}

  /* ---------- filter bar ---------- */
  .fs-filter-title {{display: flex; align-items: center; gap: 8px; color: {NAVY}; font-weight: 700;
      font-size: 15px; margin-bottom: 2px;}}
  .fs-filter-title .count {{background: {ORANGE}; color: {WHITE}; border-radius: 999px; padding: 1px 9px;
      font-size: 12px;}}
  .fs-filter-on {{color: #52607A; font-size: 13px;}}
  div[data-testid="stVerticalBlockBorderWrapper"]:has(.fs-filter-title) {{background: {GROUND};
      border-color: #C9D6EA !important; border-left: 5px solid {ORANGE} !important;}}
  .fs-steps {{display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0 12px;}}
  .fs-steps span {{padding: 6px 12px; border-radius: 999px; font-size: 13px; font-weight: 700;
      background: {GROUND}; color: #52607A; border: 1px solid #D8E0EB;}}
  .fs-steps span.done {{background: #E1F2E7; color: {GREEN}; border-color: #B9DEC6;}}
  .fs-steps span.now {{background: {NAVY}; color: {WHITE}; border-color: {NAVY};}}
  div[data-testid="stTabs"] button[aria-selected="true"] p {{color: {NAVY}; font-weight: 700;}}
  div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{background: {ORANGE};}}
  div[data-testid="stExpander"] details {{border-color: #D8E0EB; border-radius: 12px;}}
  [data-testid="stPageLink"] a {{background: {GROUND}; border: 1px solid #D8E0EB; border-radius: 10px;
      padding: 8px 10px; justify-content: center;}}
  [data-testid="stPageLink"] a:hover {{background: #DDE7F4; border-color: {BLUE};}}
  [data-testid="stPageLink"] a[aria-current="page"] {{background: {NAVY}; border-color: {NAVY};}}
  [data-testid="stPageLink"] a[aria-current="page"] p, [data-testid="stPageLink"] a[aria-current="page"] span
      {{color: {WHITE} !important; font-weight: 700;}}
  .fs-footer {{color: #52607A; font-size: 13px; text-align: center; margin-top: 40px;}}
</style>
"""


@st.cache_resource
@st.cache_resource(show_spinner=False)
def _shared_connection():
    """One database connection for the whole app (not one per page refresh, which left locks behind)."""
    return reg.connect()


def db():
    con = _shared_connection()
    if con.in_transaction:            # an earlier action stopped half-way: undo it so it cannot lock the database
        con.rollback()
    from engine import workflow as wf
    if reg.get_setting(con, "signatories_seeded")[0] is None:
        wf.seed_signatories(con)          # taskforce + approver accounts, default password to change at first use
        reg.put_setting(con, "signatories_seeded", b"1", "system")
    from engine import batches as bt
    bt.seed_history(con)                  # batches 1–15 of the Taskforce report, loaded once
    return con


def user():
    return st.session_state.get("user")


def is_officer():
    """Staff (any non-supplier role)."""
    u = user()
    return bool(u and u["role"] != "supplier")


def band(title, subtitle=""):
    st.markdown(f'<div class="fs-band"><h2>{html.escape(title)}</h2>'
                f'{"<p>" + html.escape(subtitle) + "</p>" if subtitle else ""}</div>', unsafe_allow_html=True)


def card(label, value, sub="", tone="navy"):
    return (f'<div class="fs-card {tone}"><div class="lbl">{html.escape(label)}</div>'
            f'<div class="num">{html.escape(str(value))}</div>'
            f'{"<div class=sub>" + html.escape(sub) + "</div>" if sub else ""}</div>')


def cards(items):
    cols = st.columns(len(items))
    for c, it in zip(cols, items):
        c.markdown(card(*it), unsafe_allow_html=True)


def chip(status):
    bg, fg = STATUS_STYLE.get(status, (GROUND, NAVY))
    return f'<span class="chip" style="background:{bg};color:{fg}">{html.escape(status.title())}</span>'


def money(x, unit=""):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x:,.0f}{(' ' + unit) if unit else ''}"


def interval_text(df):
    return (pd.to_datetime(df.interval_start).dt.strftime("%d/%m/%Y") + " – " +
            pd.to_datetime(df.interval_end).dt.strftime("%d/%m/%Y"))


RWF = st.column_config.NumberColumn(format="%,.0f")
LITRES = st.column_config.NumberColumn(format="%,.2f")


def claims_grid(df, supplier=False, key=None):
    if df.empty:
        st.info("No claims yet.")
        return
    t = df.copy()
    t["Interval"] = interval_text(t)
    for c in ["claimed_rwf", "to_reimburse", "pending_rwf", "rejected_rwf", "appeal_award", "paid_amount", "outstanding"]:
        t[c] = pd.to_numeric(t[c], errors="coerce")
    t["status"] = t["status"].str.title()
    for c in ["submission", "paid_at", "payment_ref", "note"]:
        t[c] = t[c].fillna("")
    cols = {"id": "Claim #", "submission": "Submission", "name": "Supplier", "Interval": "Consumption interval",
            "status": "Status", "claimed_rwf": "Claimed (RWF)", "to_reimburse": "To reimburse (RWF)",
            "pending_rwf": "Pending (RWF)", "rejected_rwf": "Rejected (RWF)", "appeal_award": "Added on appeal (RWF)",
            "paid_amount": "Paid (RWF)", "outstanding": "Outstanding (RWF)", "paid_at": "Paid on",
            "payment_ref": "Payment ref", "note": "Note"}
    if supplier:
        cols.pop("name")
    money_cols = ["Claimed (RWF)", "To reimburse (RWF)", "Pending (RWF)", "Rejected (RWF)",
                  "Added on appeal (RWF)", "Paid (RWF)", "Outstanding (RWF)"]
    st.dataframe(t[list(cols)].rename(columns=cols), hide_index=True, width="stretch", key=key,
                 column_config={c: RWF for c in money_cols})


def footer():
    st.markdown('<div class="fs-footer">RURA · RRA · MINECOFIN · MININFRA — '
                'Fuel Subsidy Claims Platform</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Roles, filter bar and step tracker
# ---------------------------------------------------------------------------
def role():
    u = user()
    return u["role"] if u else None


def read_only():
    """Manager / senior manager: see everything, approve or delete nothing."""
    return role() in reg.READ_ONLY_ROLES


def view_only_note():
    st.caption("👁 View only — your role can see this stage but not act on it.")


def has(*roles):
    """True when the signed-in user has one of these roles (the administrator has every role)."""
    r = role()
    return r == "admin" or r in roles


def filter_bar(title="Filters"):
    """A clearly marked filter area. Use as:  with ui.filter_bar() as fb: ... ; fb.active(n)"""
    box = st.container(border=True)
    holder = box.empty()

    class _FB:
        def __enter__(self):
            self._ctx = box.__enter__()
            return self

        def __exit__(self, *a):
            return box.__exit__(*a)

        def active(self, n, summary=""):
            badge = f'<span class="count">{n} active</span>' if n else '<span class="fs-filter-on">none active — showing all</span>'
            holder.markdown(f'<div class="fs-filter-title">⚲ {html.escape(title)} {badge}</div>'
                            + (f'<div class="fs-filter-on">{html.escape(summary)}</div>' if summary else ""),
                            unsafe_allow_html=True)
    return _FB()


def steps(labels, done_upto: int, current: int | None = None):
    """Step tracker: labels[0..done_upto] done, labels[current] highlighted."""
    parts = []
    for i, l in enumerate(labels):
        cls = "done" if i <= done_upto else ("now" if i == current else "")
        mark = "✓ " if i <= done_upto else ""
        parts.append(f'<span class="{cls}">{mark}{html.escape(l)}</span>')
    st.markdown('<div class="fs-steps">' + "".join(parts) + "</div>", unsafe_allow_html=True)
