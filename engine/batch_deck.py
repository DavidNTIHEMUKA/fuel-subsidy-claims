"""The Taskforce batch report as a PowerPoint, built from the data (python-pptx, native chart and tables)."""
import io
import re

import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from engine import batches as bt

NAVY, BLUE, GREEN, ORANGE = RGBColor(0x0B, 0x2B, 0x57), RGBColor(0x1F, 0x5F, 0xA8), RGBColor(0x1B, 0x7A, 0x3E), RGBColor(0xE8, 0x82, 0x0E)
INK, MUTED, LIGHT, WHITE = RGBColor(0x14, 0x21, 0x3D), RGBColor(0x52, 0x60, 0x7A), RGBColor(0xEE, 0xF3, 0xF8), RGBColor(0xFF, 0xFF, 0xFF)
GREY, ROW, LOW = RGBColor(0xAE, 0xB8, 0xC5), RGBColor(0xF5, 0xF8, 0xFB), RGBColor(0xA8, 0x55, 0x0A)
FONT = "Calibri"


def _text(slide, x, y, w, h, text, size=14, bold=False, color=INK, align=PP_ALIGN.LEFT):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    lines = text if isinstance(text, list) else [text]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), bold, color, FONT
    return tb


def _box(slide, x, y, w, h, fill, line=None):
    from pptx.enum.shapes import MSO_SHAPE
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.adjustments[0] = 0.06
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
    s.shadow.inherit = False
    return s


def _bg(slide, color):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = color


def _title(slide, title, kicker=None):
    if kicker:
        _text(slide, 0.6, 0.35, 12, 0.3, kicker, 11, True, ORANGE)
    _text(slide, 0.6, 0.55 if kicker else 0.45, 12.2, 0.7, title, 28, True, NAVY)


def _table(slide, df, x, y, w, col_w=None, size=10, highlight=None, total_last=False, row_h=0.3):
    rows, cols = len(df) + 1, len(df.columns)
    shp = slide.shapes.add_table(rows, cols, Inches(x), Inches(y), Inches(w), Inches(row_h * rows))
    t = shp.table
    widths = col_w or [w / cols] * cols
    for j, cw in enumerate(widths):
        t.columns[j].width = Inches(cw)
    for i in range(rows):
        t.rows[i].height = Inches(row_h)
        for j in range(cols):
            c = t.cell(i, j)
            c.margin_left = c.margin_right = Inches(0.05)
            c.margin_top = c.margin_bottom = Inches(0.02)
            v = df.columns[j] if i == 0 else df.iat[i - 1, j]
            c.text = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
            p = c.text_frame.paragraphs[0]
            numeric = bool(re.fullmatch(r"(RWF )?[-\d,.]+%?( M| low)?|none|–|-", c.text.strip())) and j > 0
            p.alignment = PP_ALIGN.RIGHT if numeric and i > 0 or (i == 0 and _num_col(df.iloc[:, j])) else PP_ALIGN.LEFT
            for r in p.runs:
                r.font.size, r.font.name = Pt(size), FONT
                r.font.bold = i == 0 or (total_last and i == rows - 1)
                r.font.color.rgb = WHITE if i == 0 else INK
                if highlight and i > 0 and highlight(i - 1, j):
                    r.font.color.rgb, r.font.bold = LOW, True
            c.fill.solid()
            c.fill.fore_color.rgb = NAVY if i == 0 else (LIGHT if total_last and i == rows - 1 else
                                                         (WHITE if i % 2 else ROW))
    return t


def _num_col(col) -> bool:
    vals = [str(v).strip() for v in col if str(v).strip() not in ("", "–", "-", "none", "nan")]
    return bool(vals) and all(re.fullmatch(r"(RWF )?[-\d,.]+%?( M| low)?", v) for v in vals[1:] or vals)


def _n(v, d=0):
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:,.{d}f}"


def build_deck(df: pd.DataFrame) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    o = bt.overview(df)
    bb, bo = bt.by_batch(df), bt.by_omc(df)
    span = f"batches {o['first_batch']}–{o['last_batch']}"

    # 1 · overview
    s = prs.slides.add_slide(blank)
    _bg(s, NAVY)
    _text(s, 0.7, 0.8, 12, 0.35, "RURA · RRA · MINECOFIN · MININFRA — PUBLIC TRANSPORT FUEL SUBSIDY SCHEME", 12, True, ORANGE)
    _text(s, 0.7, 1.2, 12, 1.0, "Fuel Subsidy Reimbursement Claims", 40, True, WHITE)
    _text(s, 0.7, 2.15, 12, 0.5, f"Verification results, {span} · {o['from']:%B} – {o['to']:%B %Y}", 18, False,
          RGBColor(0xDC, 0xE6, 0xF3))
    cards = [("CLAIMED", o["claimed_l"], "100% of litres", o["claimed_rwf"], "100% of amount", WHITE),
             ("ACCEPTED", o["accepted_l"], f"{o['accepted_pct']:.1f}% of litres claimed", o["reimburse_rwf"],
              f"{o['reimburse_pct']:.1f}% of amount claimed · to reimburse", RGBColor(0x4A, 0xDE, 0x80)),
             ("PENDING / REJECTED", o["pending_l"], f"{o['pending_pct']:.1f}% of litres claimed", o["withheld_rwf"],
              f"{o['withheld_pct']:.1f}% of amount claimed · withheld", RGBColor(0xF7, 0xB7, 0x33))]
    for k, (lab, l, lp, r, rp, col) in enumerate(cards):
        x = 0.7 + k * 4.05
        _box(s, x, 3.3, 3.8, 3.3, RGBColor(0x16, 0x3B, 0x6E))
        _text(s, x + 0.25, 3.45, 3.4, 0.35, lab, 12, True, col)
        _text(s, x + 0.25, 3.85, 3.4, 0.6, f"{l:,.0f} L", 28, True, col)
        _text(s, x + 0.25, 4.5, 3.4, 0.35, lp, 12, False, RGBColor(0xDC, 0xE6, 0xF3))
        _text(s, x + 0.25, 5.15, 3.4, 0.5, f"RWF {r:,.0f}", 20, True, WHITE)
        _text(s, x + 0.25, 5.7, 3.4, 0.6, rp, 12, False, RGBColor(0xDC, 0xE6, 0xF3))
    s.notes_slide.notes_text_frame.text = (
        f"Overview of {o['batches']} reimbursement batches. OMCs claimed {o['claimed_l']:,.0f} litres worth RWF "
        f"{o['claimed_rwf']:,.0f}. After verification, {o['accepted_l']:,.0f} litres ({o['accepted_pct']:.1f}%) were "
        f"accepted and RWF {o['reimburse_rwf']:,.0f} ({o['reimburse_pct']:.1f}%) submitted for reimbursement. "
        f"{o['pending_l']:,.0f} litres ({o['pending_pct']:.1f}%), worth RWF {o['withheld_rwf']:,.0f}, are pending or rejected.")

    # 2 · by batch (native clustered column chart + payout row)
    s = prs.slides.add_slide(blank)
    _bg(s, LIGHT)
    _title(s, "Claimed vs. reimbursable amount, by batch")
    cd = CategoryChartData()
    cd.categories = bb.Batch.tolist()
    cd.add_series("Claimed (RWF M)", [round(v / 1e6, 1) for v in bb.claimed_rwf])
    cd.add_series("Submitted for reimbursement (RWF M)", [round(v / 1e6, 1) for v in bb.reimburse_rwf])
    ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.3), Inches(12.1), Inches(4.9), cd).chart
    ch.has_legend, ch.legend.position, ch.legend.include_in_layout = True, XL_LEGEND_POSITION.TOP, False
    ch.legend.font.size, ch.legend.font.name = Pt(11), FONT
    for ser, col in zip(ch.plots[0].series, (GREY, BLUE)):
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = col
    ch.plots[0].gap_width, ch.plots[0].overlap = 60, -10
    ch.value_axis.has_major_gridlines = True
    ch.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xDD, 0xE3, 0xEA)
    ch.value_axis.format.line.fill.background()
    for ax in (ch.value_axis, ch.category_axis):
        ax.tick_labels.font.size, ax.tick_labels.font.name = Pt(10), FONT
        ax.tick_labels.font.color.rgb = MUTED
    n = len(bb)
    plot_x, plot_w = 1.25, 11.3
    for k, (b, p) in enumerate(zip(bb.Batch, bb.payout_pct)):
        _text(s, plot_x + plot_w * (k + 0.5) / n - 0.35, 6.25, 0.7, 0.3, f"{p:.0f}%", 11, True,
              LOW if p < 75 else MUTED, PP_ALIGN.CENTER)
    _text(s, 0.6, 6.6, 12, 0.3, "Payout per batch = submitted for reimbursement ÷ claimed (orange: under 75%)", 10,
          False, MUTED)
    worst = bb.sort_values("payout_pct").head(3)
    s.notes_slide.notes_text_frame.text = (
        "Each pair of bars is one batch: grey is what the OMCs claimed, blue is what was verified and submitted for "
        "reimbursement. Lowest payout: " + ", ".join(f"{r.Batch} ({r.payout_pct:.0f}%)" for r in worst.itertuples()) + ".")

    # 3 · by OMC
    s = prs.slides.add_slide(blank)
    _bg(s, LIGHT)
    _title(s, "Results by Oil Marketing Company")
    t = pd.DataFrame({"OMC": bo.omc, "Batches": bo.batches, "Litres claimed": bo.claimed_l.map(_n),
                      "Litres accepted": bo.accepted_l.map(_n),
                      "Accepted": [f"{a:.1f}%" + (" low" if lo else "") for a, lo in zip(bo.accepted_pct, bo.low)],
                      "Claimed RWF M": (bo.claimed_rwf / 1e6).map(lambda v: _n(v, 1)),
                      "Reimb. RWF M": (bo.reimburse_rwf / 1e6).map(lambda v: _n(v, 1)),
                      "Share": bo.share_pct.map(lambda v: f"{v:.1f}%")})
    t.loc[len(t)] = ["Total", o["batches"], _n(o["claimed_l"]), _n(o["accepted_l"]), f"{o['accepted_pct']:.1f}%",
                     _n(o["claimed_rwf"] / 1e6, 1), _n(o["reimburse_rwf"] / 1e6, 1), "100%"]
    low = set(i for i, lo in enumerate(bo.low) if lo)
    _table(s, t, 0.6, 1.4, 12.1, [3.2, 1.0, 1.5, 1.5, 1.3, 1.3, 1.3, 1.0], 12,
           highlight=lambda i, j: j == 4 and i in low, total_last=True, row_h=0.42)
    top = bo.head(4)
    s.notes_slide.notes_text_frame.text = (
        f"{', '.join(top.omc)} account for about {top.share_pct.sum():.0f}% of the money submitted for reimbursement. "
        f"Low = under {bt.LOW_ACCEPTANCE:.0f}% of litres accepted.")

    # 4 · coverage matrix
    s = prs.slides.add_slide(blank)
    _bg(s, LIGHT)
    _title(s, "Batches processed per OMC, with coverage dates")
    m, _ = bt.coverage(df)
    m.columns = ["Batch"] + [c.replace(" Ltd", "").replace(" (Rwanda)", "") for c in m.columns[1:]]
    ncol = len(m.columns)
    rh = min(0.32, 5.6 / (len(m) + 1))
    _table(s, m, 0.4, 1.3, 12.5, [0.7] + [(12.5 - 0.7) / (ncol - 1)] * (ncol - 1), 9,
           highlight=lambda i, j: "*" in str(m.iat[i, j]), total_last=True, row_h=rh)
    _text(s, 0.4, 7.0, 12, 0.3, "* the period overlaps another claim of the same OMC — confirm the same fuel is not "
                                "reimbursed twice", 10, False, MUTED)

    # 5 · points to check (split over slides)
    c = bt.checks(df)
    for start in range(0, max(len(c), 1), 13):
        s = prs.slides.add_slide(blank)
        _bg(s, LIGHT)
        _title(s, "Points to check" + (f" ({start // 13 + 1})" if len(c) > 13 else ""))
        part = c.iloc[start:start + 13][["OMC", "Check", "Detail"]] if not c.empty else \
            pd.DataFrame([["—", "—", "Nothing to raise"]], columns=["OMC", "Check", "Detail"])
        _table(s, part, 0.6, 1.3, 12.1, [2.8, 1.9, 7.4], 10, row_h=0.4)

    # 6 · one profile per OMC
    for rank, tin in enumerate(bo.tin, 1):
        p = bt.profile(df, tin)
        s = prs.slides.add_slide(blank)
        _bg(s, LIGHT)
        _title(s, p["omc"], f"OMC PROFILE {rank} OF {len(bo)} · TIN {tin}")
        kp = [(f"{p['batches']}", "batches" if p["batches"] != 1 else "batch", NAVY),
              (f"{p['claimed_l']:,.0f}", "litres claimed", NAVY),
              (f"{p['accepted_pct']:.1f}%", "litres accepted", LOW if p["accepted_pct"] < bt.LOW_ACCEPTANCE else GREEN),
              (f"RWF {p['reimburse_rwf'] / 1e6:,.1f} M", f"to reimburse · {p['share_pct']:.1f}% of total", GREEN)]
        for k, (v, lab, col) in enumerate(kp):
            x = 0.6 + [0, 1.3, 3.4, 5.4][k]
            _text(s, x, 1.3, 2.2, 0.5, v, 24, True, col)
            _text(s, x, 1.85, 2.4, 0.3, lab, 11, False, MUTED)
        _box(s, 8.4, 1.3, 4.3, 0.85, WHITE, RGBColor(0xDC, 0xE4, 0xEF))
        _text(s, 8.55, 1.33, 4.0, 0.8, p["headline"], 11, False, INK)
        tb = p["table"].drop(columns=["Source"]).copy()
        for col in ("Vehicles", "Claimed L", "Accepted L", "Pending L", "Claimed RWF", "Reimburse RWF"):
            tb[col] = tb[col].map(lambda v: "none" if v is None or (isinstance(v, float) and pd.isna(v)) else _n(v))
        accs = tb["Accepted %"].tolist()
        tb["Accepted %"] = [f"{v:.1f}%" for v in accs]
        rh = min(0.34, 4.6 / (len(tb) + 1))
        _table(s, tb, 0.6, 2.45, 12.1, [0.8, 1.7, 0.8, 1.35, 1.35, 1.2, 1.1, 1.9, 1.9], 10,
               highlight=lambda i, j: j == 6 and i < len(accs) - 1 and accs[i] < bt.WEAK_BATCH + 20,
               total_last=True, row_h=rh)
        if not p["checks"].empty:
            s.notes_slide.notes_text_frame.text = p["headline"] + " Points to check: " + \
                " ".join(f"{r.Check}: {r.Detail}" for r in p["checks"].itertuples())
        else:
            s.notes_slide.notes_text_frame.text = p["headline"]
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
