"""Administrator (super user): users and access, signatories, official rates, prices, rounds, policies."""
import io
import re

import pandas as pd
import streamlit as st

from engine import register as reg
from engine import workflow as wf
from ui import common as ui


def page():
    con, u = ui.db(), ui.user()
    if u["role"] == "senior_manager":
        ui.band("Admin · Users", "As senior manager you can see all accounts and add new ones. "
                                 "Changing, resetting or deleting accounts is done by the administrator.")
        _users(con, u, add_only=True)
        return ui.footer()
    if u["role"] != "admin":
        st.error("Only the administrator can open this page.")
        return
    ui.band("Admin", "Users and access, signatories, official subsidy rates, pump prices, rounds, policies and "
                     "deleted records.")
    t = st.tabs(["Users and access", "Signatories", "Rates and prices", "Rounds and policies", "Deleted records",
                 "Home pictures", "Batch history", "Functions", "Backup", "Audit log"])
    with t[0]:
        _users(con, u)
    with t[1]:
        _signatories(con)
    with t[2]:
        _rates(con, u)
    with t[3]:
        _policies(con, u)
    with t[4]:
        _deleted(con, u)
    with t[5]:
        _home_pictures(con, u)
    with t[6]:
        _batch_history(con, u)
    with t[7]:
        _functions(con, u)
    with t[8]:
        _backup(con)
    with t[9]:
        ev = reg.events(con)
        st.dataframe(ev, hide_index=True, width="stretch")
        st.download_button("Download audit log (CSV)", ev.to_csv(index=False).encode(), file_name="audit_log.csv")
    ui.footer()


def _users(con, me, add_only=False):
    msg = st.session_state.pop("admin_flash", None)
    if msg:
        st.success(msg)
    df = reg.users(con)
    with ui.filter_bar() as fb:
        c1, c2, c3 = st.columns([1, 1, 2])
        allr = list(reg.ROLES) + list(reg.functions(con))
        roles = c1.multiselect("Role", allr, format_func=lambda r: reg.role_label(con, r), key="adm_role",
                               placeholder="All roles")
        state = c2.selectbox("Status", ["All", "Active", "Inactive", "Must change password"], key="adm_state")
        q = c3.text_input("Search name, username or TIN", key="adm_q")
        n = bool(roles) + (state != "All") + bool(q)
        fb.active(n)
    v = df
    if roles:
        v = v[v.role.isin(roles)]
    if state == "Active":
        v = v[v.active == 1]
    elif state == "Inactive":
        v = v[v.active != 1]
    elif state == "Must change password":
        v = v[v.must_change_password == "yes"]
    if q:
        m = v.apply(lambda r: q.lower() in " ".join(str(x) for x in r.values).lower(), axis=1)
        v = v[m]
    show = v.assign(role=v.role.map(lambda r: reg.role_label(con, r)), active=v.active.map({1: "yes", 0: "no"}).fillna("no"))
    st.dataframe(show.rename(columns={"username": "Username", "name": "Name", "role": "Role", "tin": "TIN",
                                      "institution": "Institution", "title": "Title", "active": "Active",
                                      "must_change_password": "Must change password", "valid_until": "Valid until"}),
                 hide_index=True, width="stretch")
    st.caption(f"{len(v)} of {len(df)} accounts")

    c1, c2 = st.columns(2, gap="large")
    with c1:
        with st.container(border=True):
            st.markdown("**Create an account** — staff or fuel supplier")
            with st.form("new_user", clear_on_submit=True):
                choices = [r for r in list(reg.ROLES) + list(reg.functions(con)) if not (add_only and r == "admin")]
                role = st.selectbox("Role or function", choices, format_func=lambda r: reg.role_label(con, r))
                a, b = st.columns(2)
                name = a.text_input("Full name or company")
                tin = b.text_input("TIN (fuel suppliers)")
                a, b = st.columns(2)
                inst = a.text_input("Institution (RRA, RURA, MINECOFIN…)")
                title = b.text_input("Title (e.g. Chair)")
                a, b = st.columns(2)
                username = a.text_input("Username (blank = automatic)")
                days = b.number_input("Valid for days (0 = no expiry)", min_value=0, value=0)
                pw = st.text_input("Initial password (blank = generate)", type="password")
                go = st.form_submit_button("Create account", type="primary")
            if go:
                try:
                    if role == "supplier" and not tin.strip():
                        raise ValueError("a fuel supplier account needs a TIN")
                    un = username.strip() or (tin.strip() if role == "supplier" else reg.uniform_username(name))
                    if con.execute("SELECT 1 FROM users WHERE username=?", (un,)).fetchone():
                        raise ValueError(f"username '{un}' already exists")
                    pw = pw or reg.make_password()
                    exp = pd.Timestamp.now() + pd.Timedelta(days=int(days)) if days else None
                    reg.create_user(con, un, name, role, pw, tin if role == "supplier" else None, exp, inst, title,
                                    must_change=True)
                    st.success(f"Account created — username **{un}**, password **{pw}** (must be changed at first "
                               "sign-in). Copy it now; it is not shown again.")
                except ValueError as e:
                    st.error(str(e))
    if add_only:
        return
    with c2:
        with st.container(border=True):
            st.markdown("**Change an account** — role, access, password")
            if df.empty:
                return
            un = st.selectbox("Account", df.username.tolist(),
                              format_func=lambda x: f"{x} — {df.loc[df.username == x, 'name'].iloc[0]}")
            r = df[df.username == un].iloc[0]
            a, b = st.columns(2)
            allr = list(reg.ROLES) + list(reg.functions(con))
            new_role = a.selectbox("Role or function", allr, index=allr.index(r.role) if r.role in allr else 0,
                                   format_func=lambda x: reg.role_label(con, x), key=f"r_{un}")
            active = b.toggle("Active (can sign in)", value=bool(r.active == 1), key=f"a_{un}")
            a, b = st.columns(2)
            inst = a.text_input("Institution", value=r.institution or "", key=f"i_{un}")
            title = b.text_input("Title", value=r.title or "", key=f"t_{un}")
            if st.button("Save changes", type="primary", key=f"s_{un}"):
                try:
                    if un == me["username"] and (new_role != "admin" or not active):
                        raise ValueError("you cannot remove your own administrator access")
                    reg.update_user(con, un, role=new_role, active=int(active), institution=inst or None,
                                    title=title or None)
                    st.success("Saved.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
            st.divider()
            a, b = st.columns([2, 1])
            npw = a.text_input("New password (blank = generate)", type="password", key=f"p_{un}")
            if b.button("Reset password", key=f"rp_{un}"):
                try:
                    pw = npw or reg.make_password()
                    reg.reset_password(con, un, pw, must_change=True)
                    st.success(f"Password for **{un}** reset to **{pw}** — to be changed at the next sign-in.")
                except ValueError as e:
                    st.error(str(e))
        st.write("")
        _delete_user_box(con, me, df)


def _signatories(con):
    st.markdown("Taskforce members approve each submission round in the system — their approval is their "
                "electronic signature. The final approver then approves the round.")
    s = wf.signatories(con)
    a = wf.approvers(con)
    c1, c2 = st.columns([3, 2])
    c1.markdown(f"**Taskforce members ({len(s)})**")
    c1.dataframe(s, hide_index=True, width="stretch")
    c2.markdown(f"**Final approver ({len(a)})**")
    c2.dataframe(a, hide_index=True, width="stretch")
    with st.container(border=True):
        st.markdown("**Create signatory accounts from names** — one line per person, as on the report: "
                    "`FAMILY Given (Institution) Title`. Usernames are made the same way for everyone: "
                    "`given.family` (e.g. *beatha.mukangabo*).")
        lines = st.text_area("Names", "\n".join(wf.DEFAULT_SIGNATORIES), height=200)
        a, b, c = st.columns(3)
        as_role = a.selectbox("Role", ["taskforce", "approver"], format_func=lambda r: reg.ROLES[r])
        pw = b.text_input("Default password", value=wf.setting(con, "default_signatory_password"))
        preview = []
        for l in [x for x in lines.splitlines() if x.strip()]:
            info = reg.parse_signatory(l)
            un = reg.uniform_username(info["name"])
            exists = bool(con.execute("SELECT 1 FROM users WHERE username=?", (un,)).fetchone())
            preview.append({**info, "username": un, "status": "exists" if exists else "will be created"})
        st.dataframe(pd.DataFrame(preview), hide_index=True, width="stretch")
        if c.button("Create the accounts", type="primary"):
            try:
                if len(pw) < 6:
                    raise ValueError("the default password needs at least 6 characters")
                made = reg.create_signatories(con, lines.splitlines(), pw, role=as_role)
                wf.set_setting(con, "default_signatory_password", pw)
                st.success(f"{len(made)} account(s) created with the default password **{pw}**; each person must "
                           "change it at first sign-in. Existing accounts were not changed.")
            except ValueError as e:
                st.error(str(e))


def _rates(con, u):
    from engine.pipeline import DEFAULT_PRICE_FILE, load_rura_prices
    rates = wf.subsidy_rates(con)
    st.markdown("**Official subsidy rate (RWF per litre)** — used to pay every accepted litre, and to warn "
                "suppliers whose claimed rate is different.")
    with st.form("rates"):
        cols = st.columns(len(rates))
        new = {p: c.number_input(p.title(), min_value=0.0, value=float(v), step=1.0) for c, (p, v) in
               zip(cols, rates.items())}
        if st.form_submit_button("Save rates", type="primary"):
            wf.set_setting(con, "subsidy_rates", new, u["username"])
            st.success("Official subsidy rates saved.")
    st.divider()
    blob, name, at = reg.get_setting(con, "rura_prices")
    try:
        if blob:
            f = io.BytesIO(blob); f.name = name
            prices, label = load_rura_prices(f), f"{name} (uploaded {at})"
        else:
            prices, label = load_rura_prices(DEFAULT_PRICE_FILE), "built-in list (ASSIMPER, Nov 2026)"
        st.markdown(f"**RURA / pump prices in use:** {label}")
        show = prices.copy()
        show["effective_from"] = pd.to_datetime(show["effective_from"]).dt.strftime("%d/%m/%Y").fillna("any date")
        st.dataframe(show, hide_index=True, width="stretch",
                     column_config={"source_url": st.column_config.LinkColumn("Source URL")})
    except Exception as e:
        st.error(f"Price list could not be read: {e}")
    up = st.file_uploader("Upload a new price list (Excel/CSV)", type=["xlsx", "csv"], key="adm_prices")
    a, b = st.columns(2)
    if up is not None and a.button("Save price list", type="primary"):
        try:
            f = io.BytesIO(up.getvalue()); f.name = up.name
            if load_rura_prices(f).empty:
                raise ValueError("no product with a price found")
            reg.put_setting(con, "rura_prices", up.getvalue(), up.name)
            st.success("Price list saved.")
        except Exception as e:
            st.error(f"Not saved: {e}")
    if blob and b.button("Go back to the built-in price list"):
        con.execute("DELETE FROM settings WHERE key='rura_prices'"); con.commit()
        st.rerun()


def _policies(con, u):
    with st.form("pol"):
        n = st.number_input("Number of the next submission round", min_value=1,
                            value=int(wf.setting(con, "next_round_number")), step=1)
        strict = st.toggle("Fuel suppliers must use the official claim form (other files are rejected)",
                           value=bool(wf.setting(con, "strict_form")))
        if st.form_submit_button("Save", type="primary"):
            wf.set_setting(con, "next_round_number", int(n), u["username"])
            wf.set_setting(con, "strict_form", bool(strict), u["username"])
            st.success("Saved.")
    st.caption("Rule thresholds (litres per vehicle-day, refuel interval, tolerances, exempt tax types) are under "
               "Processing › Rules.")


def _delete_user_box(con, me, df):
    with st.container(border=True):
        st.markdown("**Delete an account**")
        st.caption("Before deletion the account's details are archived (Deleted records). Its claims, signatures, "
                   "appeals and audit entries are kept unchanged. To stop access only, untick *Active* instead.")
        others = [x for x in df.username.tolist() if x != me["username"]]
        if not others:
            return
        un = st.selectbox("Account to delete", others, key="del_user",
                          format_func=lambda x: f"{x} — {df.loc[df.username == x, 'name'].iloc[0]} "
                                                f"({reg.role_label(con, df.loc[df.username == x, 'role'].iloc[0])})")
        reason = st.text_input("Reason (required)", key="del_user_reason")
        sure = st.checkbox(f"I confirm the deletion of {un}", key=f"del_user_ok_{un}")
        if st.button("Delete the account", disabled=not sure, key="del_user_go"):
            try:
                kept = reg.delete_user(con, un, me["username"], reason)
                st.session_state["admin_flash"] = f"Account {un} deleted — {kept}. Details archived in Deleted records."
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def _deleted(con, me):
    st.markdown("**Delete a submitted file at any stage** (administrator)")
    c = reg.claims(con)
    if c.empty:
        st.caption("No claims.")
    else:
        a, b = st.columns([2, 2])
        cid = a.selectbox("Claim", c.id.tolist(), key="adm_del_claim",
                          format_func=lambda i: (lambda r: f"#{i} · {r['name']} · {r.status.title()}"
                                                           f"{' · ' + r.submission if isinstance(r.submission, str) and r.submission else ''}")(
                              c[c.id == i].iloc[0]))
        reason = b.text_input("Reason (required)", key="adm_del_reason")
        r = c[c.id == cid].iloc[0]
        if r.status not in reg.DELETABLE_BY_OFFICER:
            st.warning(f"Claim #{cid} is **{r.status}**: deleting it also removes it from its round, payments and appeals.")
        sure = st.checkbox(f"I confirm the deletion of claim #{cid}", key=f"adm_del_ok_{cid}")
        if st.button("Delete the submission", disabled=not sure, key="adm_del_go"):
            try:
                reg.delete_claim(con, int(cid), me["username"], "admin", reason)
                st.success(f"Claim #{cid} deleted — a full copy is archived below.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    st.divider()
    st.markdown("**Deleted submissions** (archived copy: files, letter, lines, payments, appeals)")
    dc = reg.deleted_claims(con)
    if dc.empty:
        st.caption("None.")
    else:
        st.dataframe(dc, hide_index=True, width="stretch",
                     column_config={k: ui.RWF for k in ("requested_rwf", "to_reimburse", "paid_amount")})
        pick = st.selectbox("Download an archived file", dc.claim_id.tolist(), key="arch_pick")
        f, fn, l, ln = con.execute("SELECT claim_file, claim_filename, letter, letter_name FROM deleted_claims "
                                   "WHERE claim_id=? ORDER BY deleted_at DESC", (pick,)).fetchone()
        a, b = st.columns(2)
        if f:
            a.download_button(f"Claim file ({fn})", f, file_name=fn or "claim.xlsx", key="arch_f")
        if l:
            b.download_button(f"Letter ({ln})", l, file_name=ln, key="arch_l")
    st.markdown("**Deleted accounts**")
    du = reg.deleted_users(con)
    if du.empty:
        st.caption("None.")
    else:
        st.dataframe(du.rename(columns={"created_note": "Records kept"}), hide_index=True, width="stretch")


def _backup(con):
    from datetime import datetime
    from engine import export as ex
    st.caption("Complete copy of the database (all data, uploaded files and password hashes) — administrator only. "
               "Data extraction for officers and analysts is under **Reporting › Data extraction**. "
               "On Streamlit Community Cloud the database can be reset when the app restarts: download a backup "
               "regularly and before every update.")
    if st.button("Prepare a full database backup (.db)", key="exp_db"):
        st.session_state["exp_db_bytes"] = ex.database_backup(con)
    if st.session_state.get("exp_db_bytes"):
        st.download_button("Download database backup", st.session_state["exp_db_bytes"],
                           file_name=f"claims_backup_{datetime.now():%Y%m%d_%H%M}.db", type="primary", key="exp_db_dl")
        st.caption("Open it with DB Browser for SQLite, or in Python: sqlite3.connect('claims_backup_….db').")


def _home_pictures(con, me):
    """Replace the illustrations of the Home slider with real photos (e.g. RRA and RURA buildings)."""
    import json
    from PIL import Image
    from ui import art
    from ui.home import slides
    st.caption("The Home page shows four slides. Each uses a built-in illustration until you upload a photo. "
               "Use photos RRA owns or has permission to use. Photos are resized automatically (max 1600 px wide).")
    current = slides(con)
    for (key, title, caption, _), (t_now, c_now, uri) in zip(art.SLIDES, current):
        with st.container(border=True):
            a, b = st.columns([1, 2], gap="large")
            a.markdown(f'<img src="{uri}" style="width:100%;border-radius:10px;aspect-ratio:3/1;object-fit:cover">',
                       unsafe_allow_html=True)
            with b:
                blob, name, when = reg.get_setting(con, f"home_slide_{key}")
                st.markdown(f"**Slide: {title}** — " + (f"photo *{name}* (uploaded {when})" if blob
                                                         else "built-in illustration"))
                nt = st.text_input("Title", value=t_now, key=f"hs_t_{key}")
                nc = st.text_input("Caption", value=c_now, key=f"hs_c_{key}")
                up = st.file_uploader("Photo (JPG or PNG)", type=["jpg", "jpeg", "png", "webp"], key=f"hs_u_{key}")
                c1, c2 = st.columns(2)
                if c1.button("Save", type="primary", key=f"hs_s_{key}", width="stretch"):
                    if up is not None:
                        img = Image.open(up).convert("RGB")
                        if img.width > 1600:
                            img = img.resize((1600, int(img.height * 1600 / img.width)))
                        out = io.BytesIO()
                        img.save(out, "JPEG", quality=82, optimize=True)
                        reg.put_setting(con, f"home_slide_{key}", out.getvalue(), up.name.rsplit(".", 1)[0] + ".jpg")
                    reg.put_setting(con, f"home_slide_{key}_text", json.dumps({"title": nt, "caption": nc}).encode(),
                                    "slide text")
                    reg.log(con, None, me["username"], "HOME PICTURE", f"{key}: {nt}" + (f" — {up.name}" if up else ""))
                    con.commit()
                    st.rerun()
                if c2.button("Back to the illustration", key=f"hs_r_{key}", width="stretch", disabled=not blob):
                    con.execute("DELETE FROM settings WHERE key IN (?, ?)", (f"home_slide_{key}", f"home_slide_{key}_text"))
                    con.commit()
                    st.rerun()


def _batch_history(con, me):
    """Batches reimbursed before the platform (Taskforce report): view, download, replace or add."""
    from engine import batches as bt
    h = pd.read_sql_query(f"SELECT {', '.join(bt.COLS)}, loaded_at, loaded_by FROM batch_history ORDER BY batch, omc",
                          con, dtype={"tin": str})
    st.caption("One row per oil marketing company per batch, for batches reimbursed before the platform. They are "
               "reported with the platform's own rounds under Reporting › Taskforce batch report. New rounds are "
               f"numbered after the last batch here (next: B{(h.batch.max() if not h.empty else 0) + 1}).")
    if h.empty:
        st.info("No batch history.")
    else:
        st.markdown(f"**{len(h)} rows · batches B{h.batch.min()}–B{h.batch.max()} · {h.tin.nunique()} OMCs** · "
                    f"{h.claimed_l.sum():,.0f} L claimed · RWF {h.reimburse_rwf.sum():,.0f} to reimburse")
        st.dataframe(h, hide_index=True, width="stretch")
    st.download_button("Download the history / template (Excel)", ex_excel(h if not h.empty else
                       pd.DataFrame(columns=bt.COLS)), file_name="batch_history.xlsx", key="bh_dl")
    with st.container(border=True):
        st.markdown("**Load batch history** — columns: " + ", ".join(f"`{c}`" for c in bt.COLS) +
                    " (dates dd/mm/yyyy; `note` optional)")
        up = st.file_uploader("Excel or CSV", type=["xlsx", "csv"], key="bh_up")
        mode = st.radio("How", ["Add these rows", "Replace all the history"], horizontal=True, key="bh_mode")
        if up is not None and st.button("Load", type="primary", key="bh_go"):
            try:
                df = pd.read_csv(up, dtype={"tin": str}) if up.name.endswith(".csv") else pd.read_excel(up, dtype={"tin": str})
                n = bt.load_history(con, df, me["username"], replace=mode.startswith("Replace"))
                reg.log(con, None, me["username"], "BATCH HISTORY", f"{n} rows loaded ({mode.lower()}) from {up.name}")
                con.commit()
                st.success(f"{n} rows loaded.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def ex_excel(df):
    from engine import export as ex
    return ex.to_excel({"Batch history": df})


def _functions(con, me):
    """Functions: roles defined here (e.g. Data Scientist) — the heads they open and whose permissions they use."""
    fns = reg.functions(con)
    st.caption("A function is a role you define: its name, the heads it can open, and the built-in role whose "
               "permissions it uses inside those heads. Example: a Data Scientist works like an RRA officer but only "
               "in Appeal, Analysis, Reporting and Insights. Give it to an account under Users and access.")
    used = pd.read_sql_query("SELECT role, COUNT(*) AS n FROM users GROUP BY role", con).set_index("role").n.to_dict()
    if fns:
        st.dataframe(pd.DataFrame([{"Function": f["label"], "Acts as": reg.ROLES.get(f["acts_as"], f["acts_as"]),
                                    "Heads": ", ".join(reg.HEADS[h] for h in f["heads"] if h in reg.HEADS),
                                    "Accounts": used.get(k, 0), "Description": f.get("description", "")}
                                   for k, f in fns.items()]), hide_index=True, width="stretch")
    keys = list(fns) + ["__new__"]
    pick = st.selectbox("Create or change a function", keys, key="fn_pick",
                        format_func=lambda k: "➕ New function" if k == "__new__" else fns[k]["label"])
    f = fns.get(pick, {"label": "", "acts_as": "officer", "heads": ["home", "account"], "description": ""})
    with st.container(border=True):
        a, b = st.columns(2)
        label = a.text_input("Name", value=f["label"], key=f"fn_l_{pick}", placeholder="e.g. Data Scientist")
        acts = b.selectbox("Acts as (permissions inside its heads)", [r for r in reg.ROLES if r != "admin"],
                           index=[r for r in reg.ROLES if r != "admin"].index(f["acts_as"]),
                           format_func=lambda r: reg.ROLES[r], key=f"fn_a_{pick}")
        heads = st.multiselect("Heads it can open", [h for h in reg.HEADS if h != "admin"], default=
                               [h for h in f["heads"] if h != "admin"], format_func=lambda h: reg.HEADS[h],
                               key=f"fn_h_{pick}")
        desc = st.text_input("Description", value=f.get("description", ""), key=f"fn_d_{pick}")
        c1, c2 = st.columns(2)
        if c1.button("Save the function", type="primary", key=f"fn_s_{pick}", width="stretch"):
            try:
                if not label.strip():
                    raise ValueError("Give the function a name")
                key = pick if pick != "__new__" else reg.function_key(label)
                if pick == "__new__" and (key in fns or key in reg.ROLES):
                    raise ValueError(f"A role or function '{label}' already exists")
                fns[key] = {"label": label.strip(), "acts_as": acts, "heads": heads, "description": desc}
                reg.save_functions(con, fns, me["username"])
                reg.log(con, None, me["username"], "FUNCTION SAVED", f"{label}: acts as {acts}; heads {', '.join(heads)}")
                con.commit()
                st.success(f"Function '{label}' saved. Accounts with it see the change at their next sign-in.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        if pick != "__new__" and c2.button("Delete the function", key=f"fn_x_{pick}", width="stretch",
                                           disabled=used.get(pick, 0) > 0,
                                           help="Only a function no account uses can be deleted"):
            label0 = fns.pop(pick)["label"]
            reg.save_functions(con, fns, me["username"])
            reg.log(con, None, me["username"], "FUNCTION DELETED", label0)
            con.commit()
            st.rerun()
