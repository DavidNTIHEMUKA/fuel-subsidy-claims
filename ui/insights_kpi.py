"""Insights tabs: one supplier, comparison with similar suppliers, agencies, KPI scorecard."""
import altair as alt
import pandas as pd
import streamlit as st

from engine.kpis import KPI, KPI_DEFS, entity_kpis, flag_against_peers, fmt
from ui import common as ui

LIGHT = {"red": "🔴", "amber": "🟠", "green": "🟢", "": "⚪"}
TONE = {"red": "orange", "amber": "orange", "green": "green", "": "navy"}


def _chart(c, height=280):
    return (c.properties(height=height)
            .configure_axis(labelColor="#52607A", titleColor="#52607A", gridColor="#E8EDF4", labelLimit=220)
            .configure_legend(labelColor="#14213D", orient="bottom")
            .configure_view(strokeWidth=0))


def _supplier_kpis(lines):
    if lines.empty:
        return pd.DataFrame()
    return flag_against_peers(entity_kpis(lines, "supplier"), "fleet_band")


def _kpi_cards(row, names):
    items = []
    for n in names:
        flag = row.get(f"{n}_flag", "")
        med = row.get(f"{n}_peer_median")
        items.append((f"{LIGHT[flag]} {KPI[n]['label']}", fmt(n, row[n]),
                      f"peers: {fmt(n, med)}" if med is not None and not pd.isna(med) else "", TONE[flag]))
    for i in range(0, len(items), 4):
        ui.cards(items[i:i + 4])
        st.write("")


def _kpi_table(k, names, label_col="entity"):
    t = pd.DataFrame({"Name": k[label_col]})
    for c in ["vehicles", "transactions", "claimed_l"]:
        t[{"vehicles": "Vehicles", "transactions": "Transactions", "claimed_l": "Claimed L"}[c]] = k[c].round(0)
    for n in names:
        t[KPI[n]["label"]] = [f"{LIGHT[f]} {fmt(n, v)}" for v, f in zip(k[n], k.get(f"{n}_flag", [""] * len(k)))]
    if "red_flags" in k:
        t["🔴 flags"] = k["red_flags"]
    return t


# ---------------------------------------------------------------------------
def supplier_view(con, analysed, lines):
    k = _supplier_kpis(lines)
    if k.empty:
        st.info("No analysed lines yet.")
        return
    with ui.filter_bar() as fb:
        name = st.selectbox("Fuel supplier", k.entity.tolist(), key="ins_sup")
        fb.active(1, f"Compared with suppliers of the same fleet size ({k.loc[k.entity == name, 'fleet_band'].iloc[0]})")
    row = k[k.entity == name].iloc[0]
    st.markdown(f"**{name}** · {int(row.vehicles)} vehicles · {int(row.transactions):,} transactions · "
                f"{row.claimed_l:,.0f} L claimed · {ui.money(row.claimed_rwf, 'RWF')} subsidy claimed")
    st.markdown("**Compliance**")
    _kpi_cards(row, ["acceptance_rate", "ebm_match_rate", "duplicate_rate", "overclaim_rate",
                     "invalid_invoice_rate", "price_issue_rate", "buyer_tin_issue_rate", "review_rate"])
    st.markdown("**Consumption and abnormality**")
    _kpi_cards(row, ["litres_per_vehicle_day", "max_litres_vehicle_day", "high_day_share", "quick_refuel_rate",
                     "avg_fill", "subsidy_per_vehicle"])
    L = lines[lines.supplier == name].copy()
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("**Trend by submission round**")
        a = analysed[analysed.name == name].copy()
        a["round"] = a.submission.replace("", None).fillna("Claim #" + a.id.astype(str))
        t = a.groupby("round").agg(Claimed=("claimed_rwf", "sum"), Accepted=("to_reimburse", "sum")).reset_index()
        long = t.melt("round", ["Claimed", "Accepted"], var_name="Measure", value_name="RWF")
        st.altair_chart(_chart(alt.Chart(long).mark_bar().encode(
            x=alt.X("round:N", title=None, axis=alt.Axis(labelAngle=0)), xOffset="Measure:N",
            y=alt.Y("RWF:Q", axis=alt.Axis(format=",.0f")),
            color=alt.Color("Measure:N", scale=alt.Scale(domain=["Claimed", "Accepted"], range=[ui.NAVY, ui.GREEN]),
                            title=None))), width="stretch")
    with c2:
        st.markdown("**Why lines were not accepted**")
        r = L[pd.to_numeric(L.rejected_qty, errors="coerce") > 0]
        if r.empty:
            st.success("No rejected line.")
        else:
            by = (r.assign(rule=r.reason.str.extract(r"(R\d+)")[0].fillna("—"))
                  .groupby("rule")["rejected_qty"].sum().reset_index())
            st.altair_chart(_chart(alt.Chart(by).mark_bar(color=ui.ORANGE, cornerRadiusEnd=3).encode(
                y=alt.Y("rule:N", sort="-x", title=None), x=alt.X("rejected_qty:Q", title="Litres rejected"),
                tooltip=["rule", alt.Tooltip("rejected_qty:Q", format=",.1f")])), width="stretch")
    st.markdown("**Vehicles with the highest daily consumption**")
    L["day"] = pd.to_datetime(L.closed_at, format="%d/%m/%Y %H:%M", errors="coerce").dt.date
    vd = L.groupby(["client", "vehicle", "day"])["qty"].sum().reset_index().sort_values("qty", ascending=False).head(15)
    st.dataframe(vd.rename(columns={"client": "Agency", "vehicle": "Vehicle", "day": "Day", "qty": "Litres"}),
                 hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
def peer_view(con, analysed, lines):
    k = _supplier_kpis(lines)
    if k.empty:
        st.info("No analysed lines yet.")
        return
    with ui.filter_bar("Choose the peer group") as fb:
        c1, c2 = st.columns(2)
        vmin, vmax = int(k.vehicles.min()), int(k.vehicles.max())
        vr = c1.slider("Number of vehicles", vmin, max(vmax, vmin + 1), (vmin, max(vmax, vmin + 1)), key="peer_v")
        lmin, lmax = float(k.claimed_l.min()), float(k.claimed_l.max())
        lr = c2.slider("Litres claimed", lmin, max(lmax, lmin + 1), (lmin, max(lmax, lmin + 1)), key="peer_l",
                       format="%.0f")
        g = k[k.vehicles.between(*vr) & k.claimed_l.between(*lr)]
        pick = st.multiselect("Suppliers to compare", g.entity.tolist(), default=g.entity.tolist()[:6], key="peer_pick")
        fb.active(int(vr != (vmin, max(vmax, vmin + 1))) + int(lr != (lmin, max(lmax, lmin + 1))) + 1,
                  f"{len(g)} supplier(s) with {vr[0]}–{vr[1]} vehicles and {lr[0]:,.0f}–{lr[1]:,.0f} L")
    v = g[g.entity.isin(pick)]
    if v.empty:
        st.info("Select at least one supplier.")
        return
    v = flag_against_peers(v.reset_index(drop=True), None) if len(v) >= 3 else v
    names = [n for n, *_ in KPI_DEFS]
    st.dataframe(_kpi_table(v, names), hide_index=True, width="stretch")
    kpi = st.selectbox("Compare on", names, format_func=lambda n: f"{KPI[n]['label']} — {KPI[n]['group']}",
                       key="peer_kpi")
    st.caption(KPI[kpi]["definition"])
    med = v[kpi].median()
    chart = alt.Chart(v).mark_bar(cornerRadiusEnd=3).encode(
        y=alt.Y("entity:N", sort="-x", title=None),
        x=alt.X(f"{kpi}:Q", title=KPI[kpi]["label"], axis=alt.Axis(format=".0%" if KPI[kpi]["fmt"] == "pct" else ",.0f")),
        color=alt.condition(alt.datum[kpi] > med if KPI[kpi]["direction"] == "high" else alt.datum[kpi] < med,
                            alt.value(ui.ORANGE), alt.value(ui.BLUE)),
        tooltip=["entity", alt.Tooltip(f"{kpi}:Q", format=".1%" if KPI[kpi]["fmt"] == "pct" else ",.1f")])
    rule = alt.Chart(pd.DataFrame({"m": [med]})).mark_rule(color=ui.NAVY, strokeDash=[4, 4]).encode(x="m:Q")
    st.altair_chart(_chart(chart + rule, max(140, 42 * len(v))), width="stretch")
    st.caption("Orange = worse than the group median (dashed line).")


# ---------------------------------------------------------------------------
def agency_view(con, analysed, lines):
    if lines.empty or "client" not in lines:
        st.info("No analysed lines yet.")
        return
    with ui.filter_bar() as fb:
        c1, c2 = st.columns(2)
        sup = c1.multiselect("Fuel supplier", sorted(lines.supplier.unique()), key="ag_sup", placeholder="All suppliers")
        L = lines[lines.supplier.isin(sup)] if sup else lines
        k = flag_against_peers(entity_kpis(L, "client"), "consumption_band")
        name = c2.selectbox("Transport agency", k.entity.tolist(), key="ag_sel")
        fb.active(bool(sup) + 1, f"{name} compared with {len(k) - 1} other agencies")
    row = k[k.entity == name].iloc[0]
    st.markdown(f"**{name}** · {int(row.vehicles)} vehicles · {int(row.transactions):,} fills · "
                f"{row.claimed_l:,.0f} L")
    _kpi_cards(row, ["litres_per_vehicle_day", "max_litres_vehicle_day", "high_day_share", "quick_refuel_rate",
                     "acceptance_rate", "duplicate_rate", "not_in_ebm_rate", "avg_fill"])
    kpi = st.selectbox("Compare all agencies on", ["litres_per_vehicle_day", "max_litres_vehicle_day", "high_day_share",
                                                   "quick_refuel_rate", "acceptance_rate", "avg_fill"],
                       format_func=lambda n: KPI[n]["label"], key="ag_kpi")
    chart = alt.Chart(k).mark_bar(cornerRadiusEnd=3).encode(
        y=alt.Y("entity:N", sort="-x", title=None),
        x=alt.X(f"{kpi}:Q", title=KPI[kpi]["label"], axis=alt.Axis(format=".0%" if KPI[kpi]["fmt"] == "pct" else ",.0f")),
        color=alt.condition(alt.datum.entity == name, alt.value(ui.ORANGE), alt.value(ui.BLUE)),
        tooltip=["entity", alt.Tooltip(f"{kpi}:Q", format=".1%" if KPI[kpi]["fmt"] == "pct" else ",.1f")])
    st.altair_chart(_chart(chart, max(160, 34 * len(k))), width="stretch")
    st.caption(f"Orange = {name}. {KPI[kpi]['definition']}")


# ---------------------------------------------------------------------------
def scorecard(con, analysed, lines):
    if lines.empty:
        st.info("No analysed lines yet.")
        return
    with ui.filter_bar() as fb:
        c1, c2, c3 = st.columns(3)
        level = c1.radio("Score", ["Fuel suppliers", "Transport agencies"], horizontal=True, key="sc_level")
        groups = c2.multiselect("KPI groups", ["Compliance", "Consumption", "Abnormality", "Efficiency"],
                                default=["Compliance", "Abnormality"], key="sc_groups")
        only = c3.toggle("Only entities with a red flag", key="sc_red")
        fb.active(1 + bool(only) + (len(groups) < 4), "Compared with peers of similar fleet size (suppliers) or "
                                                       "consumption (agencies)")
    if level == "Fuel suppliers":
        k = _supplier_kpis(lines)
    else:
        k = flag_against_peers(entity_kpis(lines, "client"), "consumption_band")
    names = [n for n, _, g, *_ in KPI_DEFS if g in groups]
    if only:
        k = k[k[[f"{n}_flag" for n in names]].eq("red").any(axis=1)]
    if k.empty:
        st.success("No entity with a red flag.")
    else:
        st.dataframe(_kpi_table(k.sort_values("red_flags", ascending=False), names), hide_index=True, width="stretch")
        st.caption("🔴 clearly worse than peers (more than twice the usual spread) · 🟠 worse than peers · 🟢 in line "
                   "or better · ⚪ not enough data")
    with st.expander("KPI list — what each indicator shows"):
        st.dataframe(pd.DataFrame([{"Indicator": d[1], "Shows": d[2], "Worse when": "higher" if d[3] == "high" else "lower",
                                    "Definition": d[5]} for d in KPI_DEFS]), hide_index=True, width="stretch")
