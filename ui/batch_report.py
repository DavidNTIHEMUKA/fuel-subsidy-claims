"""Reporting › Taskforce batch report: the analyses of the 'Fuel Subsidy Reimbursement Claims' deck, from the data."""
import altair as alt
import pandas as pd
import streamlit as st

from engine import batches as bt
from engine import export as ex
from ui import common as ui

GREY, NAVY = "#AEB8C5", "#0B2B57"
RWF0 = st.column_config.NumberColumn(format="%,.0f")
PCT = st.column_config.NumberColumn(format="%.1f%%")


def _data(con, u, key):
    """Batch lines limited to the user (a fuel supplier sees only its own TIN) and to the chosen batches."""
    df = bt.lines(con, tin=u.get("tin") if u["role"] == "supplier" else None)
    if df.empty:
        st.info("No batch yet: batches appear when submission rounds are created, or after the batch history is "
                "loaded (Admin › Batch history).")
        return None
    b = sorted(df.batch.unique())
    if len(b) > 1:
        with ui.filter_bar() as fb:
            lo, hi = st.select_slider("Batches", options=b, value=(b[0], b[-1]), key=f"bt_range_{key}",
                                      format_func=lambda x: f"B{x}")
            fb.active(int((lo, hi) != (b[0], b[-1])), f"B{lo}–B{hi}" if (lo, hi) != (b[0], b[-1]) else "")
        df = df[df.batch.between(lo, hi)]
    return df


def _kpi(label, value, sub, tone):
    return ui.card(label, value, sub, tone)


def overview(con, u):
    df = _data(con, u, "ov")
    if df is None:
        return
    o = bt.overview(df)
    st.markdown(f"**Verification results, batches {o['first_batch']}–{o['last_batch']} · "
                f"{o['from']:%B} – {o['to']:%B %Y}** · {o['omcs']} oil marketing companies")
    c = st.columns(3)
    c[0].markdown(_kpi("Claimed", f"{o['claimed_l']:,.0f} L", f"RWF {o['claimed_rwf']:,.0f} · 100%", "navy"),
                  unsafe_allow_html=True)
    c[1].markdown(_kpi("Accepted", f"{o['accepted_l']:,.0f} L",
                       f"{o['accepted_pct']:.1f}% of litres · RWF {o['reimburse_rwf']:,.0f} to reimburse "
                       f"({o['reimburse_pct']:.1f}%)", "green"), unsafe_allow_html=True)
    c[2].markdown(_kpi("Pending / rejected", f"{o['pending_l']:,.0f} L",
                       f"{o['pending_pct']:.1f}% of litres · RWF {o['withheld_rwf']:,.0f} withheld "
                       f"({o['withheld_pct']:.1f}%)", "orange"), unsafe_allow_html=True)
    st.caption("The amount percentage can differ slightly from the litre percentage because the subsidy rate per "
               "litre varies between batches.")
    t = pd.DataFrame([["Claimed", o["claimed_l"], 100.0, o["claimed_rwf"], 100.0],
                      ["Accepted · to reimburse", o["accepted_l"], o["accepted_pct"], o["reimburse_rwf"], o["reimburse_pct"]],
                      ["Pending / rejected · withheld", o["pending_l"], o["pending_pct"], o["withheld_rwf"], o["withheld_pct"]]],
                     columns=["", "Litres", "% of litres", "RWF", "% of amount"])
    _downloads("scheme_overview", {"Overview": t}, u)


def by_batch(con, u):
    df = _data(con, u, "bb")
    if df is None:
        return
    g = bt.by_batch(df)
    long = pd.concat([
        g.assign(Series="Claimed", RWF=g.claimed_rwf / 1e6),
        g.assign(Series="Submitted for reimbursement", RWF=g.reimburse_rwf / 1e6)])
    order = g.Batch.tolist()
    bars = alt.Chart(long).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=alt.X("Batch:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("Series:N", sort=["Claimed", "Submitted for reimbursement"]),
        y=alt.Y("RWF:Q", title="RWF million", axis=alt.Axis(grid=True, gridColor="#E5EAF1")),
        color=alt.Color("Series:N", scale=alt.Scale(domain=["Claimed", "Submitted for reimbursement"],
                                                    range=[GREY, NAVY]), legend=alt.Legend(orient="top", title=None, labelLimit=0)),
        tooltip=[alt.Tooltip("Batch:N"), alt.Tooltip("Series:N"), alt.Tooltip("RWF:Q", format=",.1f", title="RWF M"),
                 alt.Tooltip("payout_pct:Q", format=".0f", title="Payout %")])
    g = g.assign(payout_label=[f"{v:.0f}%" for v in g.payout_pct])
    pct = alt.Chart(g).mark_text(fontSize=13, fontWeight="bold").encode(
        x=alt.X("Batch:N", sort=order, axis=None), text=alt.Text("payout_label:N"),
        color=alt.condition(alt.datum.payout_pct < 75, alt.value("#A8550A"), alt.value("#52607A")),
        tooltip=[alt.Tooltip("Batch:N"), alt.Tooltip("payout_pct:Q", format=".1f", title="Payout %")]
    ).properties(height=24, title=alt.TitleParams("Payout % (orange: under 75%)", fontSize=12, anchor="start",
                                                    color="#52607A", fontWeight="normal"))
    st.altair_chart(alt.vconcat(bars.properties(height=320), pct, spacing=4).resolve_scale(x="shared")
                    .configure_view(stroke=None), use_container_width=True)
    t = g.rename(columns={"omcs": "OMCs", "claimed_l": "Claimed L", "accepted_l": "Accepted L", "pending_l": "Pending L",
                          "claimed_rwf": "Claimed RWF", "reimburse_rwf": "Reimburse RWF", "payout_pct": "Payout %",
                          "accepted_pct": "Accepted %"}).drop(columns=["batch"])
    st.dataframe(t, hide_index=True, width="stretch",
                 column_config={c: RWF0 for c in ("Claimed L", "Accepted L", "Pending L", "Claimed RWF", "Reimburse RWF")}
                 | {"Payout %": PCT, "Accepted %": PCT})
    _downloads("claimed_vs_reimbursable_by_batch", {"By batch": t}, u)


def by_omc(con, u):
    df = _data(con, u, "bo")
    if df is None:
        return
    g = bt.by_omc(df)
    o = bt.overview(df)
    t = pd.DataFrame({"OMC": g.omc, "TIN": g.tin, "Batches": g.batches, "Litres claimed": g.claimed_l,
                      "Litres accepted": g.accepted_l,
                      "Accepted": [f"{a:.1f}%" + (" · low" if lo else "") for a, lo in zip(g.accepted_pct, g.low)],
                      "Claimed RWF M": (g.claimed_rwf / 1e6).round(1), "Reimb. RWF M": (g.reimburse_rwf / 1e6).round(1),
                      "Share": g.share_pct})
    total = {"OMC": "Total", "TIN": "", "Batches": o["batches"], "Litres claimed": o["claimed_l"],
             "Litres accepted": o["accepted_l"], "Accepted": f"{o['accepted_pct']:.1f}%",
             "Claimed RWF M": round(o["claimed_rwf"] / 1e6, 1), "Reimb. RWF M": round(o["reimburse_rwf"] / 1e6, 1),
             "Share": 100.0}
    t = pd.concat([t, pd.DataFrame([total])], ignore_index=True)
    st.dataframe(t, hide_index=True, width="stretch",
                 column_config={"Litres claimed": RWF0, "Litres accepted": RWF0, "Share": PCT})
    top = g.head(4)
    st.caption(f"The {len(top)} largest — {', '.join(top.omc)} — account for {top.share_pct.sum():.0f}% of the money "
               f"submitted for reimbursement. \"low\" = under {bt.LOW_ACCEPTANCE:.0f}% of litres accepted.")
    _downloads("results_by_omc", {"By OMC": t}, u)


def coverage(con, u):
    df = _data(con, u, "cv")
    if df is None:
        return
    m, overl = bt.coverage(df)
    st.dataframe(m, hide_index=True, width="stretch")
    st.caption("Period each OMC was reimbursed for in each batch. * = the period overlaps another claim of the same "
               "OMC — confirm the same fuel is not reimbursed twice.")
    _downloads("coverage_by_batch", {"Coverage": m}, u)


def checks(con, u):
    df = _data(con, u, "ck")
    if df is None:
        return
    c = bt.checks(df)
    if c.empty:
        st.success("Nothing to raise.")
        return
    counts = c.Check.value_counts()
    st.markdown(" · ".join(f"**{k}**: {v}" for k, v in counts.items()))
    st.dataframe(c, hide_index=True, width="stretch", column_config={"Detail": st.column_config.TextColumn(width="large")})
    _downloads("points_to_check", {"Points to check": c}, u)


def omc_profile(con, u):
    df = _data(con, u, "pf")
    if df is None:
        return
    omcs = bt.by_omc(df)
    if u["role"] == "supplier":
        tin = u.get("tin")
    else:
        tin = st.selectbox("Oil marketing company", omcs.tin.tolist(), key="bt_pf_omc",
                           format_func=lambda t: f"{omcs.loc[omcs.tin == t, 'omc'].iloc[0]} · TIN {t}")
    p = bt.profile(df, tin)
    if not p:
        st.info("No batch for this company in the selected range.")
        return
    rank = omcs.index[omcs.tin == tin][0] + 1
    st.markdown(f'<div style="color:#A8550A;font-weight:800;letter-spacing:.08em;font-size:12px">OMC PROFILE '
                f'{rank} OF {len(omcs)} · TIN {p["tin"]}</div><div class="fs-sec" style="margin-top:2px">{p["omc"]}</div>'
                f'<div style="color:#14213D;margin:-6px 0 12px">{p["headline"]}</div>', unsafe_allow_html=True)
    ui.cards([("Batches", f"{p['batches']}", "", "navy"),
              ("Litres claimed", f"{p['claimed_l']:,.0f}", "", "blue"),
              ("Litres accepted", f"{p['accepted_pct']:.1f}%", f"{p['pending_l']:,.0f} L pending / rejected",
               "orange" if p["accepted_pct"] < bt.LOW_ACCEPTANCE else "green"),
              ("To reimburse", f"RWF {p['reimburse_rwf'] / 1e6:,.1f} M", f"{p['share_pct']:.1f}% of total", "green")])
    st.write("")
    t = p["table"]
    st.dataframe(t, hide_index=True, width="stretch",
                 column_config={c: RWF0 for c in ("Vehicles", "Claimed L", "Accepted L", "Pending L", "Claimed RWF",
                                                  "Reimburse RWF")} | {"Accepted %": PCT})
    if not p["checks"].empty:
        st.markdown("**Points to check**")
        for r in p["checks"].itertuples():
            st.markdown(f"- **{r.Check}** — {r.Detail}")
    name = "".join(ch if ch.isalnum() else "_" for ch in p["omc"].lower()).strip("_")
    _downloads(f"omc_profile_{name}", {"Profile": t, "Points to check": p["checks"]}, u)


def powerpoint(con, u):
    df = _data(con, u, "pp")
    if df is None:
        return
    from engine.batch_deck import build_deck
    st.markdown("The whole Taskforce report as a PowerPoint: overview, claimed vs reimbursable by batch, results by "
                "OMC, coverage, points to check and one profile per OMC — built from the data of the selected batches.")
    if st.button("Prepare the PowerPoint", type="primary", key="bt_pp"):
        with st.spinner("Building the slides…"):
            st.session_state["bt_pp_bytes"] = build_deck(df)
    if st.session_state.get("bt_pp_bytes"):
        b = sorted(df.batch.unique())
        st.download_button("Download the batch report (PowerPoint)", st.session_state["bt_pp_bytes"],
                           file_name=f"Fuel_Subsidy_Reimbursement_Batches_{b[0]}-{b[-1]}.pptx",
                           mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                           key="bt_pp_dl")


def _downloads(name, frames, u):
    from datetime import datetime
    stamp = f"{datetime.now():%Y%m%d_%H%M}"
    st.download_button("Download (Excel)", ex.to_excel(frames), file_name=f"{name}_{stamp}.xlsx",
                       key=f"bt_dl_{name}")


VIEWS = {"batch_overview": overview, "batch_by_batch": by_batch, "batch_by_omc": by_omc,
         "batch_coverage": coverage, "batch_checks": checks, "batch_profile": omc_profile,
         "batch_powerpoint": powerpoint}
