"""Approval · Rounds: officer verification -> taskforce e-signatures -> final approval."""
import pandas as pd
import streamlit as st

from engine import register as reg
from engine import workflow as wf
from engine.report import round_excel, round_table
from ui import common as ui

STEPS = ["RRA Staff verification", "Taskforce approvals", "Final approval", "Payment"]


def page():
    con, u = ui.db(), ui.user()
    ui.band("Approval · Submission rounds",
            "Verified claims are consolidated into a numbered round, approved by each taskforce member "
            "(electronic signature) and finally approved for payment.")
    todo = wf.awaiting(con, u)
    items = []
    if ui.has("officer"):
        items.append(("Verified claims to consolidate", todo.get("to_consolidate", 0), "not yet in a round", "blue"))
    if ui.has("taskforce"):
        items.append(("Rounds awaiting your approval", todo.get("to_sign", 0), "your electronic signature", "orange"))
    if ui.has("approver"):
        items.append(("Rounds ready for final approval", todo.get("to_approve", 0), "all taskforce members signed",
                      "green"))
    r = wf.rounds(con)
    items.append(("Rounds approved", int((r.status == "APPROVED").sum()) if not r.empty else 0, "", "navy"))
    ui.cards(items[:4])
    st.write("")

    if ui.has("officer"):
        _consolidate(con, u)
    _rounds(con, u)
    ui.footer()


def _consolidate(con, u):
    free = wf.unassigned_verified(con)
    with st.expander(f"Consolidate verified claims into the next round ({len(free)} ready)", expanded=len(free) > 0):
        if free.empty:
            st.caption("No verified claim is waiting. Claims become verified when the analysis is saved in Processing.")
            return
        n = max(int(wf.setting(con, "next_round_number")),
                (con.execute("SELECT MAX(number) FROM rounds").fetchone()[0] or 0) + 1)
        st.markdown(f"The system will create the **{wf.ordinal(n)} submission ({pd.Timestamp.now():%B %Y})**.")
        ed = pd.DataFrame({"Include ✓": True, "Claim #": free.id, "Supplier": free.name, "TIN": free.tin,
                           "Interval": ui.interval_text(free), "Requested (RWF)": free.requested_rwf,
                           "Calculated (RWF)": free.calculated_rwf.fillna(free.to_reimburse),
                           "To reimburse (RWF)": free.to_reimburse, "Pending (RWF)": free.pending_rwf,
                           "Rejected (RWF)": free.rejected_rwf, "Verified by": free.processor})
        out = st.data_editor(ed, hide_index=True, width="stretch", key="cons_ed",
                             disabled=[c for c in ed.columns if c != "Include ✓"],
                             column_config={c: ui.RWF for c in ["Requested (RWF)", "Calculated (RWF)", "To reimburse (RWF)",
                                                               "Pending (RWF)", "Rejected (RWF)"]})
        pick = out[out["Include ✓"]]
        st.caption(f"{len(pick)} claim(s) · {pick['To reimburse (RWF)'].sum():,.0f} RWF to reimburse")
        note = st.text_input("Note for the taskforce (optional)", key="cons_note")
        if st.button("Create the submission round", type="primary", disabled=pick.empty):
            try:
                rid = wf.create_round(con, [int(x) for x in pick["Claim #"]], u["name"], note)
                st.success(f"Round created — it is now waiting for the taskforce approvals.")
                st.session_state["round_sel"] = rid
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def _rounds(con, u):
    r = wf.rounds(con)
    if r.empty:
        st.info("No submission round yet.")
        return
    with ui.filter_bar() as fb:
        c1, c2 = st.columns([1, 2])
        st_f = c1.multiselect("Round status", ["VERIFIED", "SIGNING", "SIGNED", "APPROVED", "RETURNED"],
                              key="rnd_status", placeholder="All statuses")
        fb.active(len(st_f))
    v = r[r.status.isin(st_f)] if st_f else r
    if v.empty:
        st.info("No round matches the filter.")
        return
    ids = v.id.tolist()
    default = st.session_state.get("round_sel")
    rid = st.selectbox("Submission round", ids, index=ids.index(default) if default in ids else 0,
                       format_func=lambda i: (lambda x: f"{x['name']} · {x.status.title()} · {int(x.claims or 0)} claim(s) · "
                                                        f"{ui.money(x.to_reimburse, 'RWF')}")(v[v.id == i].iloc[0]))
    x = v[v.id == rid].iloc[0]
    done = {"VERIFIED": 0, "SIGNING": 0, "SIGNED": 1, "APPROVED": 2, "RETURNED": -1}.get(x.status, 0)
    claims = wf.round_claims(con, rid)
    if x.status == "APPROVED" and not claims.empty and (claims.status == "PAID").all():
        done = 3
    ui.steps(STEPS, done, None if x.status == "RETURNED" else done + 1)
    if x.status == "RETURNED":
        st.warning(x.note or "Returned")
    ui.cards([
        ("Claims", int(x.claims or 0), f"created {x.created_at} by {x.created_by}", "navy"),
        ("To reimburse", ui.money(x.to_reimburse), "RWF", "green"),
        ("Not paid (rejected / pending)", ui.money(x.not_paid_rwf), "RWF", "orange"),
        ("Taskforce approvals", f"{x.signed} of {x.signatories}", x.status.title(), "blue"),
    ])
    st.write("")
    if not claims.empty:
        table = round_table(claims.sort_values("name"))
        money = ["Subsidies claimed (RWF)", "Subsidies calculated (RWF)", "Amount to reimburse (RWF)", "Amount to reimburse rejected (RWF)"]
        st.dataframe(table, hide_index=True, width="stretch", column_config={c: ui.RWF for c in money})

    sig = wf.round_signatures(con, rid)
    members = wf.signatories(con)
    c1, c2 = st.columns([3, 2], gap="large")
    with c1:
        st.markdown("**Verified by Interministerial Taskforce**")
        rows = []
        for m in members.itertuples():
            s = sig[(sig.username == m.username) & (sig.title != "Final approver")]
            if s.empty:
                state = "⏳ waiting"
            else:
                s = s.iloc[-1]
                state = (f"✍ I approve and sign — {s['name']} · {s.signed_at}" if s.decision == "APPROVED"
                         else f"✍ I reject and sign — {s['name']} · {s.signed_at}: {s.comment}")
            label = f"{m.name}" + (f" ({m.institution})" if m.institution else "") + (f", {m.title}" if m.title else "")
            rows.append({"Member": label, "Signature": state})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Member": st.column_config.TextColumn(width="medium"),
                                    "Signature": st.column_config.TextColumn(width="large")})
    with c2:
        st.markdown("**Approved by**")
        fa = sig[sig.title == "Final approver"]
        if fa.empty:
            st.markdown("⏳ " + ", ".join(wf.approvers(con)["name"]) + " — after all taskforce approvals")
        else:
            f = fa.iloc[-1]
            st.markdown(f"✍ **{'I approve and sign' if f.decision == 'APPROVED' else 'I reject and sign'}** — "
                        f"*{f['name']}* · {f.signed_at}" + (f": {f.comment}" if f.comment else ""))
    _act(con, u, rid, x, sig)
    if not claims.empty:
        st.download_button("Download the round report (Excel, with electronic signatures)",
                           round_report(con, rid), file_name=f"round_{x.number}_report.xlsx")


def round_report(con, rid) -> bytes:
    """Report of a round in the taskforce format, with the electronic signatures."""
    x = wf.rounds(con).set_index("id").loc[rid]
    claims = wf.round_claims(con, rid)
    sig = wf.round_signatures(con, rid)
    sigrows = []
    for m in wf.signatories(con).itertuples():
        s = sig[(sig.username == m.username) & (sig.decision == "APPROVED") & (sig.title != "Final approver")]
        label = f"{m.name}" + (f" ({m.institution})" if m.institution else "") + (f", {m.title}" if m.title else "")
        sigrows.append((label, f"Approved and signed electronically by {s.iloc[-1]['name']} on {s.iloc[-1].signed_at}"
                       if not s.empty else None))
    fa = sig[(sig.title == "Final approver") & (sig.decision == "APPROVED")]
    appr = (fa.iloc[-1]["name"], f"Approved and signed electronically by {fa.iloc[-1]['name']} on {fa.iloc[-1].signed_at}") if not fa.empty else \
        (", ".join(wf.approvers(con)["name"]) or "", None)
    lines = reg.all_lines(con, statuses=("PROCESSED", "APPROVED", "PARTLY PAID", "PAID"))
    lines = lines[lines.claim_id.isin(claims.id)] if not lines.empty else lines
    from ui.reports import _detail
    title = (f"SUBMISSION OF THE {x['name'].split(' (')[0].upper()} REIMBURSEMENT REQUESTS OF FUEL SUBSIDIES "
             f"({x['name'].split('(')[-1].rstrip(')').upper()})")
    return round_excel(round_table(claims.sort_values("name")), title, sigrows, appr,
                       _detail(lines[lines.accepted_qty > 0]) if not lines.empty else None,
                       _detail(lines[lines.rejected_qty > 0]) if not lines.empty else None)


def _act(con, u, rid, x, sig):
    mine = sig[(sig.username == u["username"]) & (sig.title != "Final approver")]
    can_sign = u["role"] in ("taskforce", "admin") and x.status in ("VERIFIED", "SIGNING") and mine.empty \
        and (u["role"] == "taskforce" or u["username"] in set(wf.signatories(con).username))
    can_approve = ui.has("approver") and x.status == "SIGNED"
    if not (can_sign or can_approve):
        if u["role"] == "taskforce" and not mine.empty:
            m = mine.iloc[-1]
            word = "I approve and sign" if m.decision == "APPROVED" else "I reject and sign"
            st.success(f"Your signature is recorded: **{word}** — *{m['name']}* · {m.signed_at}")
        return
    from datetime import datetime
    role_txt = "Taskforce member" if can_sign else "Final approver"
    with st.container(border=True):
        st.markdown(f"**{'Your electronic signature' if can_sign else 'Final approval and signature'} — {x['name']}**  \n"
                    "Check the table above and the claim reports, then choose and sign.")
        c1, c2 = st.columns([1, 1], gap="large")
        choice = c1.radio("Decision", ["I approve and sign", "I reject and sign"], key=f"dec_{rid}",
                          label_visibility="collapsed")
        me = pd.concat([wf.signatories(con), wf.approvers(con)])
        me = me[me.username == u["username"]]
        inst = (me.institution.iloc[0] if not me.empty else "") or u.get("institution") or ""
        ttl = (me.title.iloc[0] if not me.empty else "") or u.get("title") or ""
        info = " · ".join(v for v in (inst, ttl, role_txt) if v)
        tone = "#1E7B45" if choice.startswith("I approve") else "#C0392B"
        c2.markdown(
            f'<div style="border:2px solid {tone};border-radius:10px;padding:10px 14px;background:#fff">'
            f'<div style="font-size:12px;color:#5A6B85">Signature</div>'
            f'<div style="font-family:\'Brush Script MT\',\'Segoe Script\',cursive;font-size:30px;color:#0B2A5B;'
            f'line-height:1.2">{u["name"]}</div>'
            f'<div style="font-size:13px;color:#0B2A5B"><b>{u["name"]}</b>{" · " + info if info else ""}</div>'
            f'<div style="font-size:12px;color:{tone};font-weight:700">{choice} · '
            f'{datetime.now():%d/%m/%Y %H:%M}</div></div>', unsafe_allow_html=True)
        reject = choice.startswith("I reject")
        comment = st.text_input("Reason for rejecting (required)" if reject else "Comment (optional)",
                                key=f"cmt_{rid}")
        if st.button(f"Sign — {choice}", type="primary", key=f"sign_{rid}"):
            if reject and not comment.strip():
                st.error("Write the reason for rejecting before signing.")
                return
            try:
                if can_sign:
                    st_ = wf.sign_round(con, rid, u, not reject, comment)
                    if reject:
                        st.warning("Signed: rejected. The round goes back to the RRA officer with your reason.")
                    else:
                        st.success("Signed: approved." + (" All members have signed." if st_ == "SIGNED" else ""))
                else:
                    wf.approve_round(con, rid, u, not reject, comment)
                    (st.warning if reject else st.success)(
                        "Signed: rejected — round returned to the RRA officer." if reject else
                        "Signed: approved — the claims are now with Finance for payment.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

