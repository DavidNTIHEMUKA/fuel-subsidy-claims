import streamlit as st

from engine import register as reg
from ui import common as ui


def page():
    st.markdown(f"""
    <div class="fs-hero">
      <div class="kicker">Rwanda Revenue Authority · RURA</div>
      <h1>Fuel Subsidy Claims Platform</h1>
      <p>Fuel suppliers submit reimbursement requests. Officers verify every transaction against EBM,
         approve, pay and report — with appeals handled in the same place.</p>
      <div class="bars"><span style="background:{ui.WHITE}"></span><span style="background:{ui.GREEN}"></span>
      <span style="background:{ui.ORANGE}"></span></div>
    </div>""", unsafe_allow_html=True)

    left, right = st.columns([1, 1], gap="large")
    with left:
        st.subheader("Sign in")
        with st.form("login"):
            username = st.text_input("Username (suppliers: your TIN)")
            password = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", type="primary", width="stretch")
        if ok:
            u = reg.login(ui.db(), username, password)
            if u and u.get("expired"):
                st.error(f"This temporary account expired on {u['expires_at']}. Ask an officer for a new one.")
                st.stop()
            if u:
                st.session_state["user"] = u
                st.rerun()
            st.error("Wrong username or password.")
    with right:
        st.subheader("Who uses it")
        st.markdown(ui.card("Fuel supplier (OMC)", "Submit · Appeal",
                            "Upload claims, follow status and payments, appeal rejected lines", "orange"),
                    unsafe_allow_html=True)
        st.write("")
        st.markdown(ui.card("RRA · RURA officers", "All stages",
                            "Process against EBM, approve, pay, report, insights, decide appeals", "navy"),
                    unsafe_allow_html=True)
        st.caption("Test accounts are given by an officer (Home › Accounts) or created with create_test_accounts.py")
    ui.footer()
