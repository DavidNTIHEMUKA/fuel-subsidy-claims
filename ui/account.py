import streamlit as st

from engine import register as reg
from ui import common as ui


def _form(u, first=False):
    with st.form("pw", clear_on_submit=True):
        old = st.text_input("Current password" if not first else "Password you received", type="password")
        new = st.text_input("New password (at least 8 characters, letters and numbers)", type="password")
        again = st.text_input("Repeat the new password", type="password")
        ok = st.form_submit_button("Change password", type="primary")
    if ok:
        try:
            if new != again:
                raise ValueError("the two new passwords are different")
            reg.change_password(ui.db(), u["username"], old, new)
            st.session_state["user"] = dict(u, must_change=False)
            st.success("Password changed.")
            if first:
                st.rerun()
        except ValueError as e:
            st.error(f"Not changed: {e}")


def first_change():
    u = ui.user()
    ui.band("Change your password", "You signed in with a default or reset password. Choose your own to continue.")
    c1, c2 = st.columns([1, 1], gap="large")
    with c1:
        _form(u, first=True)
    with c2:
        st.markdown(ui.card("Signed in as", u["username"], u["name"], "orange"), unsafe_allow_html=True)
        st.write("")
        if st.button("Sign out"):
            st.session_state.clear()
            st.rerun()


def page():
    u = ui.user()
    info = reg.user_info(ui.db(), u["username"]) or {}
    ui.band("My account", "Your details and password.")
    c1, c2 = st.columns([1, 1], gap="large")
    with c1:
        st.subheader("Change password")
        _form(u)
    with c2:
        st.subheader("Details")
        st.markdown(ui.card("Username", u["username"], u["name"], "navy"), unsafe_allow_html=True)
        st.write("")
        st.markdown(ui.card("Role", u.get("function_label") or reg.ROLES.get(u["role"], u["role"]),
                            " · ".join(x for x in [info.get("institution"), info.get("title"),
                                                   u.get("tin") and f"TIN {u['tin']}"] if x), "blue"),
                    unsafe_allow_html=True)
        st.caption("To change your name, role or TIN, contact the system administrator.")
    ui.footer()
