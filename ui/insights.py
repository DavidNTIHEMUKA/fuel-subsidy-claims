import altair as alt
import pandas as pd
import streamlit as st

from engine import register as reg
from ui import common as ui

PALETTE = alt.Scale(domain=["Claimed", "Accepted", "Rejected / pending", "Paid"],
                    range=[ui.NAVY, ui.GREEN, ui.ORANGE, ui.BLUE])


def _chart(c, height=300):
    return (c.properties(height=height)
            .configure_axis(labelColor="#52607A", titleColor="#52607A", gridColor="#E8EDF4")
            .configure_legend(labelColor="#14213D", orient="bottom")
            .configure_view(strokeWidth=0))


def page():
    con = ui.db()
    ui.band("Insights", "Overall picture, one fuel supplier, comparison with similar suppliers, transport agencies, "
                        "and KPIs that flag low compliance or abnormal consumption.")
    claims = reg.claims(con)
    analysed = claims[claims.status.isin(["PROCESSED", "APPROVED", "PARTLY PAID", "PAID"])]
    if analysed.empty:
        st.info("Insights appear once claims have been analysed.")
        return
    lines = reg.all_lines(con)
    t = st.tabs(["Overall", "Fuel supplier", "Compare similar suppliers", "Transport agencies", "KPI scorecard"])
    with t[0]:
        _overall(con, claims, analysed, lines)
    from ui import insights_kpi as kp
    with t[1]:
        kp.supplier_view(con, analysed, lines)
    with t[2]:
        kp.peer_view(con, analysed, lines)
    with t[3]:
        kp.agency_view(con, analysed, lines)
    with t[4]:
        kp.scorecard(con, analysed, lines)
    ui.footer()


def _overall(con, claims, analysed, lines):
    with ui.filter_bar() as fb:
        f1, f2, f3 = st.columns(3)
        sup = f1.multiselect("Fuel supplier (OMC)", sorted(analysed["name"].unique()), placeholder="All suppliers")
        agencies = sorted([a for a in lines.get("client", pd.Series(dtype=str)).unique() if a]) if not lines.empty else []
        agency = f2.multiselect("Transport agency", agencies, placeholder="All agencies")
        rounds = analysed.sort_values("interval_start")["submission"].replace("", None).dropna().unique().tolist()
        rnd = f3.multiselect("Submission round", rounds, placeholder="All rounds")
        fb.active(bool(sup) + bool(agency) + bool(rnd),
                  "; ".join(x for x in [", ".join(sup), ", ".join(agency), ", ".join(rnd)] if x))
    a = analysed[analysed.name.isin(sup)] if sup else analysed
    a = a[a.submission.isin(rnd)] if rnd else a
    ln = lines[lines.claim_id.isin(a.id)] if not lines.empty else lines
    if agency and not ln.empty:
        ln = ln[ln.client.isin(agency)]

    claimed, accepted = a.claimed_rwf.sum(), a.to_reimburse.sum()
    ui.cards([
        ("Subsidy claimed", ui.money(claimed), f"RWF · {a.claimed_l.sum():,.0f} L", "navy"),
        ("Accepted to reimburse", ui.money(accepted), f"RWF · {accepted / claimed:.1%} of claimed" if claimed else "RWF", "green"),
        ("Rejected / pending", ui.money(a.rejected_rwf.sum() + a.pending_rwf.sum()), "RWF", "orange"),
        ("Paid", ui.money(a.paid_amount.fillna(0).sum()), f"RWF · {ui.money(a.outstanding.sum())} outstanding", "blue"),
    ])
    st.write("")

    # --- Trend by submission round ------------------------------------------------
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.subheader("Trend of requests")
        g = a.assign(round=a.submission.replace("", None).fillna("Claim #" + a.id.astype(str)))
        order = g.sort_values("interval_start")["round"].unique().tolist()
        t = g.groupby("round").agg(Claimed=("claimed_rwf", "sum"), Accepted=("to_reimburse", "sum"),
                                   rej=("rejected_rwf", "sum"), pen=("pending_rwf", "sum"),
                                   Paid=("paid_amount", "sum")).reset_index()
        t["Rejected / pending"] = t.rej + t.pen
        long = t.melt("round", ["Claimed", "Accepted", "Rejected / pending", "Paid"], var_name="Measure", value_name="RWF")
        st.altair_chart(_chart(alt.Chart(long).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("round:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, labelLimit=160)),
            xOffset=alt.XOffset("Measure:N", sort=["Claimed", "Accepted", "Rejected / pending", "Paid"]),
            y=alt.Y("RWF:Q", title="RWF", axis=alt.Axis(format=",.0f")),
            color=alt.Color("Measure:N", scale=PALETTE, title=None,
                            sort=["Claimed", "Accepted", "Rejected / pending", "Paid"]),
            tooltip=["round", "Measure", alt.Tooltip("RWF:Q", format=",.0f")])), width="stretch")
    with c2:
        st.subheader("Reimbursement status")
        s = claims[claims.id.isin(a.id) | claims.status.isin(["SUBMITTED"])]
        st_df = (s.assign(amount=s.to_reimburse.fillna(0)).groupby("status")
                 .agg(claims=("id", "size"), amount=("amount", "sum")).reset_index())
        colors = alt.Scale(domain=["SUBMITTED", "PROCESSED", "APPROVED", "PARTLY PAID", "PAID", "RETURNED"],
                           range=["#8FA6C4", ui.BLUE, ui.NAVY, ui.ORANGE, ui.GREEN, "#C9862F"])
        st.altair_chart(_chart(alt.Chart(st_df).mark_bar(cornerRadiusEnd=4, size=26).encode(
            y=alt.Y("status:N", sort=["SUBMITTED", "PROCESSED", "APPROVED", "PARTLY PAID", "PAID", "RETURNED"], title=None),
            x=alt.X("claims:Q", title="Claims", axis=alt.Axis(tickMinStep=1, format="d")),
            color=alt.Color("status:N", scale=colors, legend=None),
            tooltip=["status", "claims", alt.Tooltip("amount:Q", format=",.0f", title="RWF")])), width="stretch")

    # --- By supplier ------------------------------------------------------------------
    st.subheader("Claimed vs accepted by fuel supplier")
    b = a.groupby("name").agg(Claimed=("claimed_rwf", "sum"), Accepted=("to_reimburse", "sum"),
                              rej=("rejected_rwf", "sum"), pen=("pending_rwf", "sum"),
                              Paid=("paid_amount", "sum")).reset_index()
    b["Rejected / pending"] = b.rej + b.pen
    measures = ["Claimed", "Accepted", "Rejected / pending", "Paid"]
    long = b.melt("name", measures, var_name="Measure", value_name="RWF")
    st.altair_chart(_chart(alt.Chart(long).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("name:N", title=None, axis=alt.Axis(labelAngle=0, labelLimit=180)),
        xOffset=alt.XOffset("Measure:N", sort=measures),
        y=alt.Y("RWF:Q", title="RWF", axis=alt.Axis(format=",.0f")),
        color=alt.Color("Measure:N", scale=PALETTE, title=None, sort=measures),
        tooltip=["name", "Measure", alt.Tooltip("RWF:Q", format=",.0f")])), width="stretch")
    b["Rejection rate"] = (1 - b.Accepted / b.Claimed).where(b.Claimed > 0, 0)
    b = b.drop(columns=["rej", "pen"])
    st.dataframe(b.rename(columns={"name": "Supplier"}), hide_index=True, width="stretch",
                 column_config={"Claimed": ui.RWF, "Accepted": ui.RWF, "Rejected / pending": ui.RWF, "Paid": ui.RWF,
                                "Rejection rate": st.column_config.NumberColumn(format="percent")})

    # --- Fuel consumption per vehicle per day ---------------------------------------------
    st.subheader("Fuel consumption per vehicle per day")
    if ln.empty:
        st.info("No line details for this selection.")
        return
    paid = ln[ln.accepted_qty > 0].copy()
    paid["day"] = pd.to_datetime(paid.closed_at, format="%d/%m/%Y %H:%M", errors="coerce").dt.normalize()
    vd = paid.dropna(subset=["day"]).groupby(["supplier", "client", "vehicle", "day"]).accepted_qty.sum().reset_index()
    if vd.empty:
        st.info("No dated accepted lines for this selection.")
        return
    k1, k2, k3 = st.columns(3)
    k1.markdown(ui.card("Average per vehicle-day", f"{vd.accepted_qty.mean():,.1f} L", f"{len(vd):,} vehicle-days", "blue"),
                unsafe_allow_html=True)
    k2.markdown(ui.card("Median", f"{vd.accepted_qty.median():,.1f} L", "half of vehicle-days below", "navy"),
                unsafe_allow_html=True)
    k3.markdown(ui.card("Highest", f"{vd.accepted_qty.max():,.1f} L",
                        vd.loc[vd.accepted_qty.idxmax(), "vehicle"], "orange"), unsafe_allow_html=True)
    st.write("")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        by = st.radio("Average by", ["Fuel supplier", "Transport agency"], horizontal=True)
        col = "supplier" if by == "Fuel supplier" else "client"
        avg = vd.groupby(col).agg(litres=("accepted_qty", "mean"), vehicles=("vehicle", "nunique")).reset_index()
        st.altair_chart(_chart(alt.Chart(avg).mark_bar(color=ui.BLUE, cornerRadiusEnd=4).encode(
            y=alt.Y(f"{col}:N", sort="-x", title=None), x=alt.X("litres:Q", title="Average litres per vehicle per day"),
            tooltip=[col, alt.Tooltip("litres:Q", format=",.1f"), "vehicles"]), height=max(160, 40 * len(avg))),
            width="stretch")
    with c2:
        trend = vd.groupby(pd.Grouper(key="day", freq="W-MON")).accepted_qty.mean().reset_index()
        st.markdown("Weekly trend — average litres per vehicle per day")
        st.altair_chart(_chart(alt.Chart(trend).mark_area(color=ui.GREEN, opacity=0.25, line={"color": ui.GREEN}).encode(
            x=alt.X("day:T", title=None), y=alt.Y("accepted_qty:Q", title="L / vehicle / day"),
            tooltip=[alt.Tooltip("day:T", title="week of"), alt.Tooltip("accepted_qty:Q", format=",.1f")])), width="stretch")
    st.markdown("**Vehicles with the highest daily consumption**")
    st.dataframe(vd.sort_values("accepted_qty", ascending=False).head(20).rename(
        columns={"supplier": "Supplier", "client": "Agency", "vehicle": "Vehicle", "day": "Day",
                 "accepted_qty": "Litres"}), hide_index=True, width="stretch",
        column_config={"Day": st.column_config.DateColumn(format="DD/MM/YYYY"), "Litres": ui.LITRES})
