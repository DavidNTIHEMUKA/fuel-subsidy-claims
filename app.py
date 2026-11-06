"""Fuel Subsidy Claims Platform — RURA · RRA · MINECOFIN · MININFRA (trial build).

Run:  streamlit run app.py

Heads: Home · Submission of request · Processing (claim analysis) · Approval (rounds,
e-signatures) · Payment · Analysis · Reporting · Insights · Appeal · Admin · My account.
Each role sees its own heads (ACCESS below); the administrator sees everything.
"""
import inspect

import streamlit as st

from ui import common as ui
from ui import appeal, home, insights, login, payment, processing, reporting, reports, submission

st.set_page_config(page_title="Fuel Subsidy Claims", page_icon="⛽", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(ui.CSS, unsafe_allow_html=True)

_v = tuple(int(x) for x in st.__version__.split(".")[:2])
if _v < (1, 46):
    st.error(f"This app needs Streamlit 1.46 or newer — you have {st.__version__}. In Terminal run:  "
             "pip install -U streamlit   then start the app again.")
    st.stop()
_PAGE_LINK_WIDTH = "width" in inspect.signature(st.page_link).parameters

user = ui.user()
if not user:
    nav = st.navigation([st.Page(login.page, title="Sign in", icon=":material/login:", url_path="sign-in")],
                        position="hidden")
    nav.run()
    st.stop()

from ui import account, admin, approval

if user.get("must_change"):
    # First sign-in with a default or reset password: change it before anything else
    nav = st.navigation([st.Page(account.first_change, title="Change your password", icon=":material/key:",
                                 url_path="change-password")], position="hidden")
    nav.run()
    st.stop()

pages = {
    "home": st.Page(home.page, title="Home", icon=":material/home:", url_path="home", default=True),
    "submission": st.Page(submission.page, title="Submission of request", icon=":material/upload_file:",
                          url_path="submission"),
    "processing": st.Page(processing.page, title="Processing · Claim analysis", icon=":material/fact_check:",
                          url_path="processing"),
    "approval": st.Page(approval.page, title="Approval · Rounds", icon=":material/verified:", url_path="approval"),
    "payment": st.Page(payment.page, title="Payment", icon=":material/payments:", url_path="payment"),
    "reports": st.Page(reports.page, title="Analysis", icon=":material/analytics:", url_path="analysis"),
    "reporting": st.Page(reporting.page, title="Reporting", icon=":material/description:", url_path="reporting"),
    "insights": st.Page(insights.page, title="Insights", icon=":material/insights:", url_path="insights"),
    "appeal": st.Page(appeal.page, title="Appeal", icon=":material/gavel:", url_path="appeal"),
    "admin": st.Page(admin.page, title="Admin", icon=":material/admin_panel_settings:", url_path="admin"),
    "account": st.Page(account.page, title="My account", icon=":material/person:", url_path="account"),
}
ACCESS = {
    "supplier":  ["home", "submission", "appeal", "reporting", "account"],
    "officer":   ["home", "submission", "processing", "approval", "reports", "reporting", "insights", "appeal", "account"],
    "finance":   ["home", "payment", "reports", "reporting", "insights", "account"],
    "taskforce": ["home", "approval", "reports", "reporting", "insights", "account"],
    "approver":  ["home", "approval", "appeal", "reports", "reporting", "insights", "account"],
    # view everything from submission to taskforce approval, payment and appeal — approve or delete nothing
    "manager":   ["home", "submission", "processing", "approval", "payment", "reports", "reporting", "insights", "appeal",
                  "account"],
    "senior_manager": ["home", "submission", "processing", "approval", "payment", "reports", "reporting", "insights", "appeal",
                       "admin", "account"],                                  # + can add users (Admin)
    "admin":     list(pages),
}
allowed = ACCESS.get(user["role"], ["home", "account"])
if user.get("heads"):                       # a function (e.g. Data Scientist): only its own heads
    allowed = [k for k in pages if k in user["heads"]]
st.session_state["pages"] = {k: pages[k] for k in allowed}
ROLE_LABEL = {"supplier": "Fuel supplier", "officer": "RRA officer", "finance": "Finance officer",
              "taskforce": "Taskforce member", "approver": "Final approver", "manager": "Manager (view only)",
              "senior_manager": "Senior manager (view only)", "admin": "Administrator"}

with st.sidebar:
    st.markdown(f"**{user['name']}**  \n{user.get('function_label') or ROLE_LABEL.get(user['role'], user['role'])}"
                + (f" · TIN {user['tin']}" if user.get("tin") else ""))
    if st.button("Sign out", width="stretch"):
        st.session_state.clear()
        st.rerun()

try:
    nav = st.navigation([pages[k] for k in allowed], position="top")      # Streamlit 1.46+
except Exception:
    nav = st.navigation([pages[k] for k in allowed])                      # older: menu in the sidebar

# The same heads as buttons at the top of every page (works on every Streamlit version)
SHORT = {"home": "Home", "submission": "Submission", "processing": "Processing", "approval": "Approval",
         "payment": "Payment", "reports": "Analysis", "reporting": "Reporting", "insights": "Insights", "appeal": "Appeal", "admin": "Admin",
         "account": "Account"}
# (hidden when there are many heads: the labels would be cut; the top menu shows them all)
menu = st.columns(len(allowed)) if len(allowed) <= 9 else []
for col, k in zip(menu, allowed):
    with col:
        if _PAGE_LINK_WIDTH:
            st.page_link(pages[k], label=SHORT[k], icon=pages[k].icon, width="stretch")
        else:
            st.page_link(pages[k], label=SHORT[k], icon=pages[k].icon)
nav.run()
