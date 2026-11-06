import io

import pandas as pd
import streamlit as st

from engine import register as reg
from engine import workflow as wf
from ui import common as ui

STEPS = [
    ("1", ui.NAVY, "Submission", "The supplier fills the official claim form, checks the warnings and submits."),
    ("2", ui.BLUE, "Verification", "The RRA officer uploads the EBM file; every line is matched and checked."),
    ("3", ui.ORANGE, "Approval", "The round is approved by each taskforce member, then by the final approver."),
    ("4", ui.GREEN, "Payment", "Finance pays first submissions and appeal awards, each with its reference."),
]
TASKS = {
    "to_analyse": ("Claims to analyse", "Processing", "processing", "blue"),
    "to_consolidate": ("Verified claims to put in a round", "Approval", "approval", "orange"),
    "appeals_to_verify": ("Appeals to analyse and verify", "Appeal", "appeal", "navy"),
    "appeals_assigned": ("Appeal cases assigned to you", "Appeal", "appeal", "orange"),
    "to_sign": ("Rounds awaiting your approval", "Approval", "approval", "orange"),
    "to_approve": ("Rounds ready for final approval", "Approval", "approval", "green"),
    "appeals_to_approve": ("Appeals awaiting approval", "Appeal", "appeal", "blue"),
    "to_pay": ("Amounts to pay", "Payment", "payment", "green"),
}


def _prices(con):
    from engine.pipeline import DEFAULT_PRICE_FILE, load_rura_prices
    blob, name, _ = reg.get_setting(con, "rura_prices")
    if blob:
        f = io.BytesIO(blob); f.name = name
        return load_rura_prices(f)
    return load_rura_prices(DEFAULT_PRICE_FILE)


def _reference(con):
    p = _prices(con)
    rates = wf.subsidy_rates(con)
    cols = st.columns(len(rates))
    for c, (prod, rate) in zip(cols, rates.items()):
        sub = p[p["product"] == prod]
        dated = sub.dropna(subset=["effective_from"])
        row = dated.sort_values("effective_from").iloc[-1] if not dated.empty else (sub.iloc[0] if not sub.empty else None)
        price = f"{row.price:,.0f}" if row is not None else "—"
        when = f"{row.effective_from:%d/%m/%Y}" if row is not None and pd.notna(row.effective_from) else ""
        c.markdown(f"""<div class="fs-card navy"><div class="lbl">{prod.title()} — RURA pump price</div>
            <div class="num">{price} <span style="font-size:15px;font-weight:600">RWF/L</span></div>
            <div class="sub">{when}</div>
            <div style="border-top:1px solid #D8E0EB;margin:10px 0 6px"></div>
            <div class="lbl">Official subsidy</div>
            <div class="num" style="color:{ui.GREEN}">{rate:,.0f} <span style="font-size:15px;font-weight:600">RWF/L</span></div>
            </div>""", unsafe_allow_html=True)


def page():
    con, u = ui.db(), ui.user()
    officer = ui.is_officer()
    _slider(con, officer)

    pages = st.session_state.get("pages", {})
    if officer:
        todo = wf.awaiting(con, u)
        st.markdown('<div class="fs-sec"><span class="bar" style="background:#0B2B57"></span>Waiting for you</div>',
                    unsafe_allow_html=True)
        shown = [(k, v) for k, v in todo.items() if k in TASKS and TASKS[k][2] in pages
                 and not (k == "appeals_assigned" and not v and not u.get("function"))]
        if not shown:
            st.info("Nothing waiting.")
        else:
            cols = st.columns(len(shown))
            for c, (k, n) in zip(cols, shown):
                label, page_name, key, tone = TASKS[k]
                c.markdown(ui.card(label, n, f"open {page_name}", tone if n else "navy"), unsafe_allow_html=True)
                if key in pages:
                    c.page_link(pages[key], label=f"Go to {page_name}", icon=":material/arrow_forward:")
    else:
        df = reg.claims(con, u["tin"])
        live = df[df.status != "RETURNED"]
        ui.cards([
            ("My claims", f"{len(df)}", f"{(df.status == 'SUBMITTED').sum()} waiting for verification", "navy"),
            ("To be reimbursed", ui.money(live["to_reimburse"].fillna(0).sum()), "RWF verified or approved", "blue"),
            ("Paid", ui.money(df["paid_amount"].fillna(0).sum()), "RWF", "green"),
            ("Outstanding", ui.money(df["outstanding"].sum()), "RWF approved, not yet paid", "orange"),
        ])
        if not df.empty:
            st.write("")
            st.markdown('<div class="fs-sec"><span class="bar" style="background:#0B2B57"></span>Where are my files?</div>',
                        unsafe_allow_html=True)
            from ui import tracking
            tracking.overview(con, df)
            if "submission" in pages:
                st.page_link(pages["submission"], label="Open a file for details (Submission › My requests and status)",
                             icon=":material/arrow_forward:")
        st.write("")
        lc = st.columns(2)
        for c, (k, label, icon) in zip(lc, [("submission", "Submit a request", ":material/upload_file:"),
                                            ("appeal", "Appeal a decision", ":material/gavel:")]):
            if k in pages:
                c.page_link(pages[k], label=label, icon=icon)

    st.write("")
    with st.container(key="tint_green"):
        st.markdown('<div class="fs-sec"><span class="bar" style="background:#1B7A3E"></span>'
                    'Reference: RURA pump price and official subsidy</div>', unsafe_allow_html=True)
        _reference(con)

    st.write("")
    with st.container(key="tint_orange"):
        st.markdown('<div class="fs-sec"><span class="bar" style="background:#E8820E"></span>How it works</div>',
                    unsafe_allow_html=True)
        cols = st.columns(4)
        for c, (n, color, title, text) in zip(cols, STEPS):
            c.markdown(f'<div class="fs-step"><div class="dot" style="background:{color}">{n}</div>'
                       f'<b>{title}</b><p>{text}</p></div>', unsafe_allow_html=True)

    if officer:
        r = wf.rounds(con)
        if not r.empty:
            st.write("")
            x = r.iloc[0]
            st.subheader(f"Latest round — {x['name']}")
            done = {"VERIFIED": 0, "SIGNING": 0, "SIGNED": 1, "APPROVED": 2}.get(x.status, -1)
            ui.steps(["RRA Staff verification", f"Taskforce approvals ({x.signed}/{x.signatories})",
                      "Final approval", "Payment"], done, done + 1 if done >= 0 else None)
        st.write("")
        st.subheader("Latest claims")
        df = reg.claims(con)
        if df.empty:
            st.info("No claims yet.")
        for _, r in df.head(6).iterrows():
            interval = f"{pd.Timestamp(r.interval_start):%d/%m/%Y} – {pd.Timestamp(r.interval_end):%d/%m/%Y}"
            amount = ui.money(r.to_reimburse, "RWF") if pd.notna(r.to_reimburse) else "awaiting verification"
            st.markdown(f"{ui.chip(r.status)} &nbsp; **Claim #{r.id}** · {r['name']} · {interval} · {amount}",
                        unsafe_allow_html=True)
    ui.footer()


def slides(con):
    """[(title, caption, image data URI)] — an uploaded photo replaces the built-in illustration."""
    import base64
    import json
    from ui import art
    out = []
    for key, title, caption, draw in art.SLIDES:
        blob, name, _ = reg.get_setting(con, f"home_slide_{key}")
        txt, _, _ = reg.get_setting(con, f"home_slide_{key}_text")
        if txt:
            t = json.loads(txt.decode())
            title, caption = t.get("title") or title, t.get("caption") or caption
        if blob:
            ext = (name or "x.jpg").rsplit(".", 1)[-1].lower()
            mime = {"png": "image/png", "webp": "image/webp", "svg": "image/svg+xml"}.get(ext, "image/jpeg")
            uri = f"data:{mime};base64," + base64.b64encode(blob).decode()
        else:
            uri = art.data_uri(draw())
        out.append((title, caption, uri))
    return out


def _slider(con, officer):
    import html
    items = slides(con)
    n, each = len(items), 6                                   # seconds per slide
    total = n * each
    show = 100 / n                                            # share of the cycle each slide is visible
    fade = min(4.0, show / 4)
    frames = (f"@keyframes fsfade {{0% {{opacity:0}} {fade:.2f}% {{opacity:1}} {show:.2f}% {{opacity:1}} "
              f"{show + fade:.2f}% {{opacity:0}} 100% {{opacity:0}}}}"
              f"@keyframes fscap {{0% {{opacity:0}} {fade:.2f}% {{opacity:0}} {fade * 2:.2f}% {{opacity:1}} "
              f"{show - fade / 2:.2f}% {{opacity:1}} {show:.2f}% {{opacity:0}} 100% {{opacity:0}}}}"
              f"@keyframes fsdot {{0% {{background:#FFFFFF;width:28px}} {show:.2f}% {{background:#FFFFFF;width:28px}} "
              f"{show + 0.01:.2f}% {{background:rgba(255,255,255,.45);width:10px}} 100% {{background:rgba(255,255,255,.45);width:10px}}}}")
    kicker = "Fuel Subsidies Command Post" if officer else "Supplier portal"
    partners = "".join(f'<span>{x}</span>' for x in ("RURA", "RRA", "MINECOFIN", "MININFRA"))
    lead = ("Everything waiting for you is below — upload files, verify, sign and pay." if officer else
            "Submit your fuel subsidy requests with the official claim form, follow their status and payment, "
            "and appeal rejected lines.")
    slides_html = "".join(
        f'<div class="fs-slide" style="background-image:url({uri});animation-delay:{i * each}s"></div>'
        for i, (t, c, uri) in enumerate(items))
    caps_html = "".join(
        f'<div class="fs-cap" style="animation-delay:{i * each}s"><b>{html.escape(t)}</b>'
        f'<span>{html.escape(c)}</span></div>' for i, (t, c, uri) in enumerate(items))
    dots = "".join(f'<i style="animation-delay:{i * each}s"></i>' for i in range(n))
    block = f"""<style>{frames}
      .fs-slider {{position:relative;height:400px;border-radius:18px;overflow:hidden;margin-bottom:22px;
                  box-shadow:0 10px 30px rgba(11,43,87,.25);background:#0B2B57}}
      .fs-slide {{position:absolute;inset:0;background-size:cover;background-position:center;opacity:0;
                 animation:fsfade {total}s infinite}}
      .fs-slide:first-child {{opacity:1}}
      .fs-shade {{position:absolute;inset:0;background:linear-gradient(90deg,rgba(11,43,87,.94) 0%,
                 rgba(11,43,87,.80) 38%,rgba(11,43,87,.15) 70%,rgba(11,43,87,0) 100%);pointer-events:none}}
      .fs-copy {{position:absolute;left:44px;top:46px;max-width:560px;color:#fff}}
      .fs-copy .kicker {{color:#F7B733;font-weight:800;letter-spacing:.1em;text-transform:uppercase;font-size:13px}}
      .fs-copy .partners {{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}}
      .fs-copy .partners span {{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.35);color:#fff;
                               font-size:12px;font-weight:700;letter-spacing:.06em;padding:3px 10px;border-radius:999px}}
      .fs-copy h1 {{color:#fff;font-size:40px;line-height:1.1;margin:8px 0 12px;padding:0}}
      .fs-copy p {{color:#DCE6F3;font-size:17px;margin:0}}
      .fs-copy .bars {{display:flex;gap:8px;margin-top:22px}} .fs-copy .bars span {{height:6px;width:60px;border-radius:3px}}
      .fs-cap {{position:absolute;left:44px;bottom:30px;max-width:560px;color:#fff;border-left:4px solid #E8820E;
               padding:6px 0 6px 14px;opacity:0;animation:fscap {total}s infinite}}
      .fs-cap:nth-of-type(1) {{opacity:1}}
      .fs-cap b {{display:block;font-size:19px}} .fs-cap span {{color:#DCE6F3;font-size:15px}}
      .fs-dots {{position:absolute;right:26px;bottom:24px;display:flex;gap:7px}}
      .fs-dots i {{display:block;height:10px;width:10px;border-radius:5px;background:rgba(255,255,255,.45);
                  animation:fsdot {total}s infinite}}
      @media (max-width: 760px) {{ .fs-slider {{height:460px}} .fs-copy {{left:20px;right:20px;top:26px}}
        .fs-copy h1 {{font-size:28px}} .fs-cap {{left:20px;right:20px}}
        .fs-shade {{background:linear-gradient(180deg,rgba(11,43,87,.92) 0%,rgba(11,43,87,.55) 60%,rgba(11,43,87,.85) 100%)}} }}
      @media (prefers-reduced-motion: reduce) {{ .fs-slide, .fs-cap, .fs-dots i {{animation:none}} }}
    </style>
    <div class="fs-slider">{slides_html}<div class="fs-shade"></div>{caps_html}
      <div class="fs-copy"><div class="kicker">{kicker}</div><div class="partners">{partners}</div>
        <h1>Welcome to the Fuel Subsidy Portal</h1>
        <p>{lead}</p><div class="bars"><span style="background:#fff"></span><span style="background:#1B7A3E"></span>
        <span style="background:#E8820E"></span></div></div>
      <div class="fs-dots">{dots}</div></div>"""
    # one line, no indentation: indented lines would be shown as a code block by Markdown
    st.markdown(" ".join(line.strip() for line in block.splitlines()), unsafe_allow_html=True)
