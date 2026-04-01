# dashboard/pdf_report.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ — Institutional PDF Report Generator  (ReportLab)
# 4-page PDF: Overview · DCF · Quality · Recommendation
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import io
from datetime import datetime
from typing import Any, Dict, List, Optional

# ── ReportLab imports ────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame,
    Paragraph, Table, TableStyle, Spacer,
    HRFlowable, KeepTogether, PageBreak,
)
from reportlab.lib.colors import HexColor

# ── Brand colours ────────────────────────────────────────────────
C_NAVY      = HexColor("#0F2942")
C_BLUE      = HexColor("#1D4ED8")
C_CYAN      = HexColor("#06B6D4")
C_GREEN     = HexColor("#059669")
C_RED       = HexColor("#DC2626")
C_AMBER     = HexColor("#D97706")
C_SLATE     = HexColor("#475569")
C_LIGHT_BG  = HexColor("#F1F5F9")
C_BORDER    = HexColor("#CBD5E1")
C_WHITE     = colors.white
C_BLACK     = HexColor("#1E293B")

# ── Page dimensions ──────────────────────────────────────────────
PAGE_W, PAGE_H = A4          # 595 × 842 pt
MARGIN_L = MARGIN_R = 18 * mm
MARGIN_T = 28 * mm          # room for header band
MARGIN_B = 22 * mm          # room for footer

CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R


# ═══════════════════════════════════════════════════════════════
#  Helper: paragraph styles
# ═══════════════════════════════════════════════════════════════
def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    S = {}

    def s(name, parent="Normal", **kw):
        S[name] = ParagraphStyle(name, parent=base[parent], **kw)

    s("h1",      fontSize=20, textColor=C_WHITE,  fontName="Helvetica-Bold",
                 leading=24,  spaceAfter=4)
    s("h2",      fontSize=13, textColor=C_NAVY,   fontName="Helvetica-Bold",
                 leading=16,  spaceBefore=10, spaceAfter=4)
    s("h3",      fontSize=10, textColor=C_BLUE,   fontName="Helvetica-Bold",
                 leading=13,  spaceBefore=6,  spaceAfter=2)
    s("body",    fontSize=9,  textColor=C_BLACK,  fontName="Helvetica",
                 leading=13,  spaceAfter=3)
    s("small",   fontSize=8,  textColor=C_SLATE,  fontName="Helvetica",
                 leading=11,  spaceAfter=2)
    s("mono",    fontSize=8,  textColor=C_BLACK,  fontName="Courier",
                 leading=11)
    s("label",   fontSize=7.5,textColor=C_SLATE,  fontName="Helvetica",
                 leading=10,  spaceAfter=1, alignment=TA_LEFT)
    s("val_lg",  fontSize=18, textColor=C_NAVY,   fontName="Helvetica-Bold",
                 leading=22,  alignment=TA_CENTER)
    s("val_cap", fontSize=7.5,textColor=C_SLATE,  fontName="Helvetica",
                 leading=10,  alignment=TA_CENTER)
    s("cap_c",   fontSize=8,  textColor=C_SLATE,  fontName="Helvetica",
                 leading=11,  alignment=TA_CENTER)
    s("footer",  fontSize=7,  textColor=C_SLATE,  fontName="Helvetica",
                 leading=9,   alignment=TA_CENTER)
    s("risk",    fontSize=8.5,textColor=C_BLACK,  fontName="Helvetica",
                 leading=12,  leftIndent=8, spaceAfter=3)
    s("section_title", fontSize=11, textColor=C_WHITE, fontName="Helvetica-Bold",
                 leading=14, alignment=TA_LEFT)
    return S


# ═══════════════════════════════════════════════════════════════
#  Header / footer callbacks
# ═══════════════════════════════════════════════════════════════
def _make_page_decorator(ticker: str, company: str, page_titles: List[str]):
    """Return (on_first_page, on_later_pages) that draw header + footer."""

    def _draw_header_footer(canvas, doc):
        page_num = doc.page
        title = page_titles[min(page_num - 1, len(page_titles) - 1)]
        canvas.saveState()

        # ── Navy header band ────────────────────────────────────
        canvas.setFillColor(C_NAVY)
        canvas.rect(0, PAGE_H - 22 * mm, PAGE_W, 22 * mm, fill=1, stroke=0)

        # Logo mark (cyan square)
        canvas.setFillColor(C_CYAN)
        canvas.roundRect(MARGIN_L, PAGE_H - 16 * mm, 8 * mm, 8 * mm, 1 * mm,
                         fill=1, stroke=0)
        canvas.setFillColor(C_WHITE)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawCentredString(MARGIN_L + 4 * mm, PAGE_H - 11.5 * mm, "Y")

        # Brand name
        canvas.setFillColor(C_WHITE)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(MARGIN_L + 10 * mm, PAGE_H - 10.5 * mm, "YieldIQ")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(C_CYAN)
        canvas.drawString(MARGIN_L + 10 * mm, PAGE_H - 15 * mm,
                          "Institutional DCF Analysis")

        # Right: ticker + page title
        canvas.setFillColor(C_WHITE)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 10 * mm, ticker)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(HexColor("#94A3B8"))
        canvas.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 15 * mm, title)

        # ── Thin cyan rule under header ─────────────────────────
        canvas.setStrokeColor(C_CYAN)
        canvas.setLineWidth(1)
        canvas.line(0, PAGE_H - 22 * mm, PAGE_W, PAGE_H - 22 * mm)

        # ── Footer ──────────────────────────────────────────────
        canvas.setFillColor(C_LIGHT_BG)
        canvas.rect(0, 0, PAGE_W, MARGIN_B - 2 * mm, fill=1, stroke=0)
        canvas.setStrokeColor(C_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_L, MARGIN_B - 2 * mm,
                    PAGE_W - MARGIN_R, MARGIN_B - 2 * mm)

        canvas.setFillColor(C_SLATE)
        canvas.setFont("Helvetica", 6.5)
        date_str = datetime.now().strftime("%d %b %Y")
        canvas.drawString(MARGIN_L, 7 * mm,
                          f"YieldIQ — {company} ({ticker})   |   Generated {date_str}   |   "
                          "For informational purposes only. Not investment advice.")
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawRightString(PAGE_W - MARGIN_R, 7 * mm,
                               f"Page {page_num}")

        canvas.restoreState()

    return _draw_header_footer, _draw_header_footer


# ═══════════════════════════════════════════════════════════════
#  Table style helpers
# ═══════════════════════════════════════════════════════════════
def _kv_style(alt: bool = True):
    cmds = [
        ("BACKGROUND",   (0, 0), (-1, 0), C_NAVY),
        ("TEXTCOLOR",    (0, 0), (-1, 0), C_WHITE),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 8),
        ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 1), (-1, -1), 8),
        ("TEXTCOLOR",    (0, 1), (-1, -1), C_BLACK),
        ("BACKGROUND",   (0, 1), (-1, -1), C_WHITE),
        ("GRID",         (0, 0), (-1, -1), 0.4, C_BORDER),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("ALIGN",        (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ]
    return TableStyle(cmds)


def _section_header(text: str, S: Dict) -> Table:
    """Navy band with white title text."""
    t = Table([[Paragraph(text, S["section_title"])]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_NAVY),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("ROWHEIGHT",    (0, 0), (-1, -1), 18),
    ]))
    return t


def _metric_box(label: str, value: str, color=None, S=None) -> Table:
    """Small KPI tile."""
    col = color or C_NAVY
    val_style = ParagraphStyle(
        "vb", fontName="Helvetica-Bold", fontSize=14,
        textColor=col, leading=18, alignment=TA_CENTER,
    )
    lbl_style = ParagraphStyle(
        "lb", fontName="Helvetica", fontSize=7,
        textColor=C_SLATE, leading=10, alignment=TA_CENTER,
    )
    t = Table(
        [[Paragraph(value, val_style)], [Paragraph(label, lbl_style)]],
        colWidths=[CONTENT_W / 4 - 3 * mm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), C_LIGHT_BG),
        ("BOX",          (0, 0), (-1, -1), 1, col),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


# ═══════════════════════════════════════════════════════════════
#  Formatting helpers
# ═══════════════════════════════════════════════════════════════
def _fmt(val: float, sym: str = "$", decimals: int = 2) -> str:
    if val is None:
        return "N/A"
    sign = "-" if val < 0 else ""
    val = abs(val)
    if val >= 1e9:
        return f"{sign}{sym}{val/1e9:.{decimals}f}B"
    if val >= 1e6:
        return f"{sign}{sym}{val/1e6:.{decimals}f}M"
    if val >= 1e3:
        return f"{sign}{sym}{val/1e3:.{decimals}f}K"
    return f"{sign}{sym}{val:.{decimals}f}"


def _pct(val: float, signed: bool = False) -> str:
    if val is None:
        return "N/A"
    return f"{'+' if signed and val > 0 else ''}{val:.1f}%"


def _sig_color(sig: str):
    s = sig.upper()
    if "STRONG BUY" in s:  return C_GREEN
    if "BUY" in s:         return HexColor("#16A34A")
    if "HOLD" in s:        return C_AMBER
    if "STRONG SELL" in s: return C_RED
    if "SELL" in s:        return HexColor("#EF4444")
    return C_SLATE


def _grade_color(grade: str):
    g = (grade or "").upper()
    if g.startswith("A"):  return C_GREEN
    if g.startswith("B"):  return HexColor("#16A34A")
    if g.startswith("C"):  return C_AMBER
    return C_RED


# ═══════════════════════════════════════════════════════════════
#  PAGE 1 — Company Overview
# ═══════════════════════════════════════════════════════════════
def _page1(
    story: list, S: Dict, ticker: str, enriched: dict,
    price_d: float, iv_d: float, mos_pct: float, sig: str,
    sym: str, wacc: float, terminal_g: float,
) -> None:

    company   = enriched.get("company_name", ticker)
    sector    = enriched.get("sector", "")
    exchange  = enriched.get("exchange", "")
    currency  = enriched.get("currency_display", sym)

    # ── Company name banner ─────────────────────────────────────
    banner_data = [[Paragraph(
        f'<font color="white"><b>{company}</b></font>  '
        f'<font color="#94A3B8" size="9">{sector}  ·  {exchange}</font>',
        ParagraphStyle("bn", fontName="Helvetica-Bold", fontSize=14,
                       textColor=C_WHITE, leading=18),
    )]]
    banner = Table(banner_data, colWidths=[CONTENT_W])
    banner.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), C_BLUE),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
    ]))
    story.append(banner)
    story.append(Spacer(1, 4 * mm))

    # ── 4 KPI tiles ─────────────────────────────────────────────
    sig_col   = _sig_color(sig)
    mos_col   = C_GREEN if mos_pct > 0 else C_RED
    mos_str   = f"{mos_pct:+.1f}%"
    iv_str    = f"{sym}{iv_d:,.2f}"
    price_str = f"{sym}{price_d:,.2f}"
    sig_short = sig.replace("STRONG ", "STR. ") if len(sig) > 10 else sig

    kpi_row = Table(
        [[
            _metric_box("Current Price",     price_str,  C_NAVY, S),
            _metric_box("Intrinsic Value",   iv_str,     C_BLUE, S),
            _metric_box("Margin of Safety",  mos_str,    mos_col, S),
            _metric_box("Signal",            sig_short,  sig_col, S),
        ]],
        colWidths=[CONTENT_W / 4 - 1.5 * mm] * 4,
        hAlign="LEFT",
    )
    kpi_row.setStyle(TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(kpi_row)
    story.append(Spacer(1, 5 * mm))

    # ── Key Metrics table ────────────────────────────────────────
    story.append(_section_header("Key Financial Metrics", S))
    story.append(Spacer(1, 2 * mm))

    rev_gr  = enriched.get("revenue_growth",  0) or 0
    fcf_gr  = enriched.get("fcf_growth",      0) or 0
    op_mg   = enriched.get("op_margin",       0) or 0
    gm      = enriched.get("gross_margin",    0) or 0
    roe     = enriched.get("roe",             0) or 0
    de      = enriched.get("de_ratio",        0) or 0
    fpe     = enriched.get("forward_pe",      0) or 0
    fv      = enriched.get("market_cap",      0) or 0
    td      = enriched.get("total_debt",      0) or 0
    cash    = enriched.get("total_cash",      0) or 0
    shares  = enriched.get("shares",          0) or 0

    left_rows = [
        ["Metric", "Value"],
        ["Revenue Growth (YoY)",    _pct(rev_gr * 100)],
        ["FCF Growth (YoY)",        _pct(fcf_gr * 100)],
        ["Operating Margin",        _pct(op_mg * 100)],
        ["Gross Margin",            _pct(gm * 100)],
        ["Return on Equity",        _pct(roe * 100)],
        ["Debt / Equity",           f"{de:.2f}x"],
        ["Forward P/E",             f"{fpe:.1f}x" if fpe else "N/A"],
    ]

    right_rows = [
        ["Metric", "Value"],
        ["WACC (Discount Rate)",    f"{wacc:.2%}"],
        ["Terminal Growth Rate",    f"{terminal_g:.2%}"],
        ["Market Cap",              _fmt(fv, sym, 1)],
        ["Total Debt",              _fmt(td, sym, 1)],
        ["Cash & Equivalents",      _fmt(cash, sym, 1)],
        ["Shares Outstanding",      f"{shares/1e9:.3f}B"],
        ["Currency",                currency],
    ]

    half = (CONTENT_W - 4 * mm) / 2
    lt = Table(left_rows,  colWidths=[half * 0.62, half * 0.38])
    rt = Table(right_rows, colWidths=[half * 0.62, half * 0.38])
    lt.setStyle(_kv_style())
    rt.setStyle(_kv_style())

    pair = Table([[lt, Spacer(4 * mm, 1), rt]], colWidths=[half, 4 * mm, half])
    pair.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",(0, 0), (-1, -1), 0),
    ]))
    story.append(pair)
    story.append(Spacer(1, 5 * mm))

    # ── Business description ─────────────────────────────────────
    story.append(_section_header("Business Overview", S))
    story.append(Spacer(1, 2 * mm))
    desc = enriched.get("description", "") or enriched.get("long_business_summary", "")
    if desc:
        # Trim to ~400 chars
        if len(desc) > 450:
            desc = desc[:450].rsplit(" ", 1)[0] + "…"
        story.append(Paragraph(desc, S["body"]))
    else:
        story.append(Paragraph(
            f"{company} operates in the {sector} sector. "
            "Detailed business description not available.",
            S["body"],
        ))

    story.append(PageBreak())


# ═══════════════════════════════════════════════════════════════
#  PAGE 2 — DCF Model
# ═══════════════════════════════════════════════════════════════
def _page2(
    story: list, S: Dict, ticker: str, enriched: dict,
    dcf_res: dict, forecast_result: dict,
    scenarios: dict, wacc_data: dict,
    wacc: float, terminal_g: float, forecast_yrs: int,
    sym: str, fx: float, price_d: float, iv_d: float,
) -> None:

    story.append(_section_header("Discounted Cash Flow Model", S))
    story.append(Spacer(1, 3 * mm))

    projected = forecast_result.get("projected_fcfs", [])
    cur_yr    = datetime.now().year

    # ── Projected FCFs table ─────────────────────────────────────
    story.append(Paragraph("Projected Free Cash Flows", S["h3"]))

    fcf_hdr = ["Year"] + [str(cur_yr + i) for i in range(1, len(projected) + 1)] + ["Terminal"]
    fcf_vals = [sym] + [_fmt(v * fx, sym, 1) for v in projected]

    # PV column
    pv_list = dcf_res.get("pv_fcfs", [])
    pv_row  = ["PV @ WACC"] + [_fmt(v * fx, sym, 1) for v in pv_list] + ["—"]

    # Growth row
    prev    = (forecast_result.get("fcf_base", 0) or 1)
    grw_row = ["Growth %"]
    for v in projected:
        g = ((v - prev) / abs(prev) * 100) if prev != 0 else 0
        grw_row.append(f"{g:+.1f}%")
        prev = v
    grw_row.append(f"{terminal_g:.1%}")

    # Pad if needed
    while len(fcf_vals) < len(fcf_hdr):
        fcf_vals.append("—")
    while len(pv_row) < len(fcf_hdr):
        pv_row.append("—")
    while len(grw_row) < len(fcf_hdr):
        grw_row.append("—")

    n_cols = len(fcf_hdr)
    col_w  = CONTENT_W / n_cols
    fcf_tbl = Table(
        [fcf_hdr, fcf_vals, grw_row, pv_row],
        colWidths=[col_w] * n_cols,
    )
    fcf_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  C_NAVY),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  C_WHITE),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 0), (-1, -1), 7.5),
        ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
        ("GRID",         (0, 0), (-1, -1), 0.4, C_BORDER),
        ("BACKGROUND",   (0, 1), (-1, -1), C_WHITE),
        ("BACKGROUND",   (0, 2), (-1, 2),  C_LIGHT_BG),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("FONTNAME",     (0, 3), (-1, 3),  "Helvetica-Bold"),
    ]))
    story.append(fcf_tbl)
    story.append(Spacer(1, 4 * mm))

    # ── Valuation bridge ─────────────────────────────────────────
    sum_pv   = dcf_res.get("sum_pv_fcfs",      0) * fx
    pv_tv    = dcf_res.get("pv_terminal_value", 0) * fx
    ev       = dcf_res.get("enterprise_value",  0) * fx
    debt     = enriched.get("total_debt",       0) * fx
    cash     = enriched.get("total_cash",       0) * fx
    equity   = dcf_res.get("equity_value",      0) * fx
    shares   = enriched.get("shares",           0)
    tv_pct   = dcf_res.get("tv_pct_of_ev",      0)

    half = (CONTENT_W - 4 * mm) / 2

    bridge_rows = [
        ["DCF Valuation Bridge", ""],
        ["PV of FCFs (explicit period)", _fmt(sum_pv, sym, 1)],
        ["PV of Terminal Value",         _fmt(pv_tv, sym, 1)],
        ["Terminal Value % of EV",       f"{tv_pct:.0%}"],
        ["Enterprise Value",             _fmt(ev, sym, 1)],
        ["Less: Total Debt",             f"({_fmt(debt, sym, 1)})"],
        ["Plus: Cash",                   _fmt(cash, sym, 1)],
        ["Equity Value",                 _fmt(equity, sym, 1)],
        ["Shares Outstanding",           f"{shares/1e9:.3f}B"],
        ["Intrinsic Value / Share",      f"{sym}{iv_d:,.2f}"],
    ]
    bt = Table(bridge_rows, colWidths=[half * 0.65, half * 0.35])
    bt.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  C_NAVY),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  C_WHITE),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("SPAN",         (0, 0), (-1, 0)),
        ("ALIGN",        (0, 0), (-1, 0),  "LEFT"),
        ("FONTNAME",     (0, 1), (-1, -2), "Helvetica"),
        ("FONTSIZE",     (0, 0), (-1, -1), 8),
        ("ALIGN",        (1, 1), (1, -1),  "RIGHT"),
        ("GRID",         (0, 0), (-1, -1), 0.4, C_BORDER),
        ("BACKGROUND",   (0, 1), (-1, -2), C_WHITE),
        ("BACKGROUND",   (0, -1),(-1, -1), HexColor("#DBEAFE")),
        ("FONTNAME",     (0, -1),(-1, -1), "Helvetica-Bold"),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))

    # ── WACC build-up ────────────────────────────────────────────
    wd = wacc_data or {}
    wacc_rows = [
        ["WACC Build-Up", ""],
        ["Risk-Free Rate",              f"{wd.get('rf', 0):.2%}"],
        ["Equity Risk Premium × Beta",  f"{wd.get('beta', 1):.2f}×"],
        ["Cost of Equity",              f"{wd.get('equity_cost', 0):.2%}"],
        ["Pre-tax Cost of Debt",        f"{wd.get('rd', 0):.2%}"],
        ["Tax Rate",                    f"{wd.get('tax_rate', 0):.1%}"],
        ["Weight Equity / Debt",        f"{wd.get('weight_e', 0.7):.0%} / {wd.get('weight_d', 0.3):.0%}"],
        ["WACC",                        f"{wacc:.2%}"],
        ["Terminal Growth Rate",        f"{terminal_g:.2%}"],
    ]
    wt = Table(wacc_rows, colWidths=[half * 0.65, half * 0.35])
    wt.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  C_NAVY),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  C_WHITE),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("SPAN",         (0, 0), (-1, 0)),
        ("ALIGN",        (0, 0), (-1, 0),  "LEFT"),
        ("FONTNAME",     (0, 1), (-1, -2), "Helvetica"),
        ("FONTNAME",     (0, -2),(-1, -1), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 8),
        ("ALIGN",        (1, 1), (1, -1),  "RIGHT"),
        ("GRID",         (0, 0), (-1, -1), 0.4, C_BORDER),
        ("BACKGROUND",   (0, 1), (-1, -1), C_WHITE),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))

    pair = Table([[bt, Spacer(4 * mm, 1), wt]], colWidths=[half, 4 * mm, half])
    pair.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",(0, 0), (-1, -1), 0),
    ]))
    story.append(pair)
    story.append(Spacer(1, 4 * mm))

    # ── Sensitivity table ────────────────────────────────────────
    story.append(_section_header("Sensitivity Analysis — Intrinsic Value per Share", S))
    story.append(Spacer(1, 2 * mm))

    wacc_steps = [-0.02, -0.01, 0.0, 0.01, 0.02]
    g_steps    = [-0.02, -0.01, 0.0, 0.01, 0.02]

    # Build sensitivity grid from dcf_res if available, else approximate
    sa_grid = dcf_res.get("sa_grid", {})

    # Header row: growth offsets
    g_labels = [f"g{'+' if d > 0 else ''}{d*100:.0f}%" for d in g_steps]
    sa_hdr = ["WACC \\ Growth"] + g_labels

    sa_body = []
    for wd_off in wacc_steps:
        w_eff = wacc + wd_off
        row_label = f"WACC {'+' if wd_off >= 0 else ''}{wd_off*100:.0f}% = {w_eff:.1%}"
        row_vals = [row_label]
        for gd_off in g_steps:
            key = (round(wd_off, 3), round(gd_off, 3))
            val = sa_grid.get(str(key), None)
            if val is None:
                # Rough approximation using Gordon-like scaling
                g_eff   = terminal_g + gd_off
                spread  = w_eff - g_eff
                spread0 = wacc - terminal_g
                if spread > 0 and spread0 > 0 and iv_d > 0:
                    val = iv_d * (spread0 / spread)
                else:
                    val = 0.0
            val = float(val) * fx if isinstance(val, (int, float)) else 0.0
            row_vals.append(f"{sym}{val:,.2f}")
        sa_body.append(row_vals)

    sa_data = [sa_hdr] + sa_body
    n_sa    = len(sa_hdr)
    sa_col  = [CONTENT_W * 0.28] + [(CONTENT_W * 0.72 / (n_sa - 1))] * (n_sa - 1)
    sa_tbl  = Table(sa_data, colWidths=sa_col)

    # Color center cell (base case = row 3, col 3 in 0-indexed body)
    base_row = 3   # 0=hdr, 1,2,3=base is middle = row 3 (index of 0 offset in wacc_steps)
    base_col = 3   # index of 0 offset in g_steps (1-indexed col = 3+1=4)

    sa_style = [
        ("BACKGROUND",   (0, 0),  (-1, 0),  C_NAVY),
        ("TEXTCOLOR",    (0, 0),  (-1, 0),  C_WHITE),
        ("FONTNAME",     (0, 0),  (-1, 0),  "Helvetica-Bold"),
        ("FONTNAME",     (0, 1),  (0, -1),  "Helvetica-Bold"),
        ("FONTNAME",     (1, 1),  (-1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 0),  (-1, -1), 7.5),
        ("ALIGN",        (1, 0),  (-1, -1), "CENTER"),
        ("ALIGN",        (0, 1),  (0, -1),  "LEFT"),
        ("GRID",         (0, 0),  (-1, -1), 0.4, C_BORDER),
        ("BACKGROUND",   (0, 1),  (-1, -1), C_WHITE),
        ("TOPPADDING",   (0, 0),  (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0),  (-1, -1), 3),
        ("LEFTPADDING",  (0, 0),  (-1, -1), 4),
        ("RIGHTPADDING", (0, 0),  (-1, -1), 4),
        # Base case highlight
        ("BACKGROUND",   (base_col + 1, base_row), (base_col + 1, base_row),
         HexColor("#DBEAFE")),
        ("FONTNAME",     (base_col + 1, base_row), (base_col + 1, base_row),
         "Helvetica-Bold"),
        ("TEXTCOLOR",    (base_col + 1, base_row), (base_col + 1, base_row),
         C_BLUE),
    ]
    sa_tbl.setStyle(TableStyle(sa_style))
    story.append(sa_tbl)
    story.append(Paragraph(
        "Blue cell = base case (current WACC & terminal growth). "
        "±1% WACC rows, ±2% growth columns.",
        S["small"],
    ))

    # ── Scenario summary ─────────────────────────────────────────
    if scenarios:
        story.append(Spacer(1, 4 * mm))
        story.append(_section_header("Scenario Analysis", S))
        story.append(Spacer(1, 2 * mm))
        sc_rows = [["Scenario", "Intrinsic Value", "vs Current", "MoS"]]
        for label, sc in scenarios.items():
            sc_iv  = (sc.get("iv", 0) or 0) * fx
            sc_mos = ((sc_iv - price_d) / price_d * 100) if price_d else 0
            diff   = sc_iv - iv_d
            sc_rows.append([
                label,
                f"{sym}{sc_iv:,.2f}",
                f"{'+' if diff >= 0 else ''}{sym}{diff:,.2f}",
                _pct(sc_mos, signed=True),
            ])
        sc_col = [CONTENT_W * 0.40, CONTENT_W * 0.20, CONTENT_W * 0.20, CONTENT_W * 0.20]
        sc_tbl = Table(sc_rows, colWidths=sc_col)
        sc_tbl.setStyle(_kv_style())
        story.append(sc_tbl)

    story.append(PageBreak())


# ═══════════════════════════════════════════════════════════════
#  PAGE 3 — Quality Assessment
# ═══════════════════════════════════════════════════════════════
def _page3(
    story: list, S: Dict, ticker: str, enriched: dict, raw: dict,
) -> None:

    story.append(_section_header("Business Quality Assessment", S))
    story.append(Spacer(1, 3 * mm))

    half = (CONTENT_W - 4 * mm) / 2

    # ── Moat Score ───────────────────────────────────────────────
    moat_score  = enriched.get("moat_score",  0) or 0
    moat_grade  = enriched.get("moat_grade",  "N/A")
    moat_types  = enriched.get("moat_types",  []) or []
    moat_summ   = enriched.get("moat_summary","") or ""

    story.append(Paragraph("Economic Moat Analysis", S["h3"]))

    moat_rows = [
        ["Moat Metric", "Value"],
        ["Moat Score",  f"{moat_score:.0f} / 100"],
        ["Moat Grade",  moat_grade],
        ["Moat Types",  ", ".join(moat_types) if moat_types else "None identified"],
    ]
    mt = Table(moat_rows, colWidths=[half * 0.60, half * 0.40])
    mt.setStyle(_kv_style())
    # Grade colour
    gc = _grade_color(moat_grade)
    mt.setStyle(TableStyle([
        *_kv_style().getCommands(),
        ("TEXTCOLOR", (1, 2), (1, 2), gc),
        ("FONTNAME",  (1, 2), (1, 2), "Helvetica-Bold"),
    ]))
    story.append(mt)
    if moat_summ:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(moat_summ[:300], S["small"]))
    story.append(Spacer(1, 4 * mm))

    # ── Piotroski F-Score ────────────────────────────────────────
    story.append(Paragraph("Piotroski F-Score (Financial Health)", S["h3"]))

    fs_score = enriched.get("piotroski_score", None)
    fs_grade = enriched.get("piotroski_grade", "")
    fs_items = enriched.get("piotroski_items", {}) or {}

    if fs_score is not None:
        fs_label = (
            "Strong (8-9)" if fs_score >= 8
            else "Moderate (5-7)" if fs_score >= 5
            else "Weak (0-4)"
        )
        fs_rows = [["F-Score Metric", "Value"]]
        fs_rows.append(["Total F-Score",  f"{fs_score} / 9 — {fs_label}"])
        if fs_grade:
            fs_rows.append(["Grade", fs_grade])
        # Known sub-criteria
        for key, label in [
            ("roa",         "ROA Positive"),
            ("delta_roa",   "ROA Improving"),
            ("cfo",         "Operating Cash Flow +"),
            ("accrual",     "Low Accruals"),
            ("delta_lever", "Leverage Reduced"),
            ("delta_liq",   "Liquidity Improved"),
            ("no_dilution", "No Dilution"),
            ("delta_margin","Margin Improving"),
            ("delta_turn",  "Asset Turnover Up"),
        ]:
            if key in fs_items:
                val = fs_items[key]
                fs_rows.append([label, "✓" if val else "✗"])
    else:
        fs_rows = [["F-Score Metric", "Value"], ["Data", "Not available"]]

    fst = Table(fs_rows, colWidths=[half * 0.65, half * 0.35])
    fst.setStyle(_kv_style())
    story.append(fst)
    story.append(Spacer(1, 4 * mm))

    # ── Earnings Quality ─────────────────────────────────────────
    story.append(Paragraph("Earnings Quality Score (9-Factor)", S["h3"]))

    eq_score = enriched.get("earnings_quality_score", None)
    eq_grade = enriched.get("earnings_quality_grade", "")
    eq_breakdown = enriched.get("eq_breakdown", {}) or {}

    eq_label = "—"
    if eq_score is not None:
        if eq_score >= 80:   eq_label = "Excellent"
        elif eq_score >= 65: eq_label = "Good"
        elif eq_score >= 50: eq_label = "Average"
        elif eq_score >= 35: eq_label = "Poor"
        else:                eq_label = "Very Poor"

    eq_rows = [["Earnings Quality Metric", "Value"]]
    if eq_score is not None:
        eq_rows.append(["Overall EQ Score", f"{eq_score:.1f} / 100 — {eq_label}"])
    if eq_grade:
        eq_rows.append(["Grade", eq_grade])

    # Factor breakdown
    factor_map = {
        "q1": "FCF Conversion",
        "q2": "Revenue Quality",
        "q3": "Accruals Ratio",
        "q4": "Earnings Persistence",
        "q5": "Operating Leverage",
        "q6": "Working Capital",
        "q7": "SGA Trend",
        "q8": "D&A / Revenue",
        "q9": "Analyst Beat Rate",
    }
    for fkey, flabel in factor_map.items():
        if fkey in eq_breakdown:
            eq_rows.append([flabel, f"{eq_breakdown[fkey]:.1f}"])

    eqt = Table(eq_rows, colWidths=[half * 0.65, half * 0.35])
    eqt.setStyle(_kv_style())
    story.append(eqt)
    story.append(Spacer(1, 4 * mm))

    # ── Earnings Track Record ────────────────────────────────────
    etr = enriched.get("earnings_track_record", {}) or raw.get("earnings_track_record", {})
    if etr:
        story.append(Paragraph("Earnings Track Record (Last 8 Quarters)", S["h3"]))
        beat_rate   = etr.get("beat_rate",       0) * 100
        avg_surp    = etr.get("avg_surprise_pct", 0)
        trend_lbl   = etr.get("trend",           "N/A")

        etr_rows = [
            ["Analyst Beat Rate",    f"{beat_rate:.1f}%"],
            ["Avg Surprise Magnitude", f"{avg_surp:+.2f}%"],
            ["Trend",                trend_lbl],
        ]
        etr_tbl = Table(etr_rows, colWidths=[half * 0.65, half * 0.35])
        etr_tbl.setStyle(TableStyle([
            ("FONTNAME",     (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE",     (0, 0), (-1, -1), 8),
            ("ALIGN",        (1, 0), (1, -1),  "RIGHT"),
            ("GRID",         (0, 0), (-1, -1), 0.4, C_BORDER),
            ("BACKGROUND",   (0, 0), (-1, -1), C_WHITE),
            ("TOPPADDING",   (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(etr_tbl)

    story.append(PageBreak())


# ═══════════════════════════════════════════════════════════════
#  PAGE 4 — Valuation Analysis (For Research Only)
# ═══════════════════════════════════════════════════════════════
def _page4(
    story: list, S: Dict, ticker: str, enriched: dict, raw: dict,
    inv_plan: dict, sig: str, price_d: float, sym: str, fx: float,
    mos_pct: float,
) -> None:

    story.append(_section_header("Valuation Analysis (For Research Only)", S))
    story.append(Spacer(1, 3 * mm))

    pt = (inv_plan or {}).get("price_targets", {}) or {}
    hp = (inv_plan or {}).get("holding_period", {}) or {}
    fs = (inv_plan or {}).get("fundamental", {}) or {}

    buy_price  = (pt.get("buy_price")    or 0) * fx
    tgt_price  = (pt.get("target_price") or 0) * fx
    stop_loss  = (pt.get("stop_loss")    or 0) * fx
    rr_ratio   = pt.get("rr_ratio",   0) or 0
    sl_pct     = pt.get("sl_pct",    15) or 15
    entry_sig  = pt.get("entry_signal","") or ""
    hp_label   = hp.get("label",    "N/A")
    hp_rationale = hp.get("rationale","") or ""
    fund_grade = fs.get("grade",    "")
    fund_score = fs.get("score",    0) or 0

    sig_col = _sig_color(sig)

    # ── Signal banner ─────────────────────────────────────────────
    sig_banner_data = [[
        Paragraph(
            f'<font color="white"><b>Model Signal: {sig}</b>   |   '
            f'Margin of Safety: {mos_pct:+.1f}%   |   '
            f'Model Output: {entry_sig}</font>',
            ParagraphStyle("sb", fontName="Helvetica-Bold", fontSize=11,
                           textColor=C_WHITE, leading=14),
        )
    ]]
    sig_banner = Table(sig_banner_data, colWidths=[CONTENT_W])
    sig_banner.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), sig_col),
        ("LEFTPADDING",  (0, 0), (-1, -1), 12),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
    ]))
    story.append(sig_banner)
    story.append(Spacer(1, 4 * mm))

    # ── Price targets table ───────────────────────────────────────
    half = (CONTENT_W - 4 * mm) / 2

    pt_rows = [
        ["Model Level",               "Value"],
        ["Current Price",             f"{sym}{price_d:,.2f}"],
        ["DCF Discount Threshold",    f"{sym}{buy_price:,.2f}" if buy_price else "N/A"],
        ["DCF Model Estimate",        f"{sym}{tgt_price:,.2f}" if tgt_price else "N/A"],
        ["Model Risk Range",          f"{sym}{stop_loss:,.2f} (−{sl_pct:.1f}%)" if stop_loss else "N/A"],
        ["Model Upside/Downside Ratio", f"{rr_ratio:.1f}x" if rr_ratio else "N/A"],
        ["DCF Projection Horizon",    hp_label],
        ["Fundamental Grade",         f"{fund_grade}  ({fund_score:.0f}/100)" if fund_grade else "N/A"],
    ]
    ptt = Table(pt_rows, colWidths=[half * 0.60, half * 0.40])
    ptt.setStyle(TableStyle([
        *_kv_style().getCommands(),
        # Buy zone green
        ("TEXTCOLOR",  (1, 2), (1, 2), C_GREEN),
        ("FONTNAME",   (1, 2), (1, 2), "Helvetica-Bold"),
        # Target blue
        ("TEXTCOLOR",  (1, 3), (1, 3), C_BLUE),
        ("FONTNAME",   (1, 3), (1, 3), "Helvetica-Bold"),
        # Stop-loss red
        ("TEXTCOLOR",  (1, 4), (1, 4), C_RED),
        ("FONTNAME",   (1, 4), (1, 4), "Helvetica-Bold"),
    ]))
    story.append(ptt)
    story.append(Spacer(1, 4 * mm))

    # ── Holding period rationale ──────────────────────────────────
    if hp_rationale:
        story.append(Paragraph("DCF Horizon Context", S["h3"]))
        story.append(Paragraph(hp_rationale[:300], S["body"]))
        story.append(Spacer(1, 3 * mm))

    # ── Key risks ─────────────────────────────────────────────────
    story.append(_section_header("Key Risks & Considerations", S))
    story.append(Spacer(1, 2 * mm))

    # Collect risk signals from enriched/inv_plan
    risks: List[str] = []

    # DCF risk: high terminal value dependency
    tv_pct = enriched.get("tv_pct_of_ev", 0) or 0
    if tv_pct > 0.65:
        risks.append(
            f"High terminal value dependency ({tv_pct:.0%} of enterprise value). "
            "Small changes in discount rate or long-run growth significantly impact fair value."
        )

    # Debt risk
    de = enriched.get("de_ratio", 0) or 0
    if de > 2.0:
        risks.append(
            f"Elevated leverage (D/E: {de:.1f}x). Rising interest rates or revenue shortfall "
            "could strain debt service and reduce equity value."
        )

    # Margin risk
    op_mg = enriched.get("op_margin", 0) or 0
    if op_mg < 0.05:
        risks.append(
            f"Thin operating margins ({op_mg*100:.1f}%). Limited buffer against cost inflation "
            "or demand weakness."
        )

    # FCF growth risk
    fcf_gr = enriched.get("fcf_growth", 0) or 0
    if fcf_gr < -0.05:
        risks.append(
            f"Negative FCF growth ({fcf_gr*100:.1f}%). May indicate increasing capex requirements "
            "or deteriorating cash conversion."
        )

    # Earnings miss risk
    etr = enriched.get("earnings_track_record", raw.get("earnings_track_record", {})) or {}
    beat_rate = etr.get("beat_rate", 1.0) or 1.0
    if beat_rate < 0.5:
        risks.append(
            f"Below-consensus earnings track record ({beat_rate*100:.0f}% beat rate). "
            "Guidance reliability and analyst forecast accuracy may be limited."
        )

    # Insider risk
    insider = raw.get("finnhub_insider", {}) or {}
    ins_sent = insider.get("sentiment", "NEUTRAL")
    if ins_sent in ("SELL", "STRONG SELL"):
        net90 = insider.get("net_shares_90d", 0) or 0
        risks.append(
            f"Insider selling pressure (net {net90:,} shares over 90 days, sentiment: {ins_sent}). "
            "Insiders may have informational advantage about near-term headwinds."
        )

    # Institutional risk
    inst = raw.get("finnhub_institutional", {}) or {}
    inst_trend = inst.get("trend", "STABLE")
    if inst_trend == "DISTRIBUTING":
        qoq = inst.get("qoq_change_pct", 0) or 0
        risks.append(
            f"Institutional distribution ({qoq:+.1f}% QoQ change in ownership). "
            "Smart money may be reducing exposure."
        )

    # Valuation risk: expensive
    if mos_pct < -20:
        risks.append(
            f"Stock appears overvalued relative to DCF fair value (MoS: {mos_pct:+.1f}%). "
            "Entry at current price implies limited margin of safety."
        )

    # Generic risks
    risks.append(
        "Macro risk: Changes in interest rates, currency fluctuations, or economic slowdown "
        "could materially affect both business performance and valuation."
    )
    risks.append(
        "Execution risk: Achieving projected FCF growth requires management to execute on "
        "strategic initiatives. Failure to meet targets will reduce intrinsic value."
    )

    for i, risk in enumerate(risks[:8], 1):
        story.append(Paragraph(f"<b>{i}.</b>  {risk}", S["risk"]))

    story.append(Spacer(1, 5 * mm))

    # ── Insider & Institutional summary ──────────────────────────
    story.append(Paragraph("Market Positioning", S["h3"]))

    inst_pct   = inst.get("total_pct", 0) or 0
    inst_acc   = inst.get("accumulation", False)
    inst_qoq   = inst.get("qoq_change_pct", 0) or 0

    mkt_rows = [
        ["Factor",                 "Reading"],
        ["Insider Sentiment",      ins_sent],
        ["Institutional Ownership", f"{inst_pct:.1f}%"],
        ["Institutional QoQ Δ",   f"{inst_qoq:+.1f}%"],
        ["Smart Money Trend",      inst_trend],
        ["Accumulating?",          "Yes — Institutional Buying" if inst_acc
                                   else "No — Neutral / Distributing"],
    ]
    mkt_tbl = Table(mkt_rows, colWidths=[half * 0.55, half * 0.45])
    mkt_tbl.setStyle(_kv_style())
    story.append(mkt_tbl)

    story.append(Spacer(1, 5 * mm))

    # ── Disclaimer ────────────────────────────────────────────────
    disc = (
        "DISCLAIMER: This report is generated by YieldIQ's quantitative DCF model and is "
        "provided for informational and educational purposes only. It does not constitute "
        "investment advice, a recommendation, or a solicitation to buy or sell any security. "
        "Past performance is not indicative of future results. Always consult a qualified "
        "financial adviser before making investment decisions. YieldIQ is not a registered "
        "investment adviser."
    )
    disc_tbl = Table([[Paragraph(disc, S["small"])]], colWidths=[CONTENT_W])
    disc_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), C_LIGHT_BG),
        ("BOX",          (0, 0), (-1, -1), 0.5, C_BORDER),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
    ]))
    story.append(disc_tbl)


# ═══════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════
def generate_pdf_report(
    ticker:          str,
    enriched:        dict,
    raw:             dict,
    dcf_res:         dict,
    forecast_result: dict,
    scenarios:       dict,
    inv_plan:        dict,
    wacc_data:       dict,
    wacc:            float,
    terminal_g:      float,
    forecast_yrs:    int,
    sym:             str,
    to_code:         str,
    fx:              float,
    price_d:         float,
    iv_d:            float,
    mos_pct:         float,
    sig:             str,
) -> bytes:
    """
    Generate a 4-page institutional PDF report and return as bytes.
    All monetary values passed in display currency (already ×fx).
    """
    buf  = io.BytesIO()
    S    = _styles()

    company = enriched.get("company_name", ticker)

    page_titles = [
        "Page 1 of 4 — Company Overview",
        "Page 2 of 4 — DCF Valuation Model",
        "Page 3 of 4 — Quality Assessment",
        "Page 4 of 4 — Valuation Analysis (For Research Only)",
    ]

    on_page, on_later = _make_page_decorator(ticker, company, page_titles)

    # ── Document setup ───────────────────────────────────────────
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=MARGIN_T,
        bottomMargin=MARGIN_B,
        title=f"YieldIQ — {ticker} DCF Report",
        author="YieldIQ Institutional Analytics",
        subject=f"DCF valuation report for {company}",
    )
    frame = Frame(
        MARGIN_L, MARGIN_B,
        CONTENT_W, PAGE_H - MARGIN_T - MARGIN_B,
        id="main",
    )
    doc.addPageTemplates([
        PageTemplate(id="All", frames=[frame], onPage=on_page),
    ])

    # ── Build story ──────────────────────────────────────────────
    story: List = []

    _page1(
        story, S, ticker, enriched,
        price_d, iv_d, mos_pct, sig, sym, wacc, terminal_g,
    )
    _page2(
        story, S, ticker, enriched,
        dcf_res, forecast_result, scenarios, wacc_data,
        wacc, terminal_g, forecast_yrs, sym, fx, price_d, iv_d,
    )
    _page3(story, S, ticker, enriched, raw)
    _page4(
        story, S, ticker, enriched, raw,
        inv_plan, sig, price_d, sym, fx, mos_pct,
    )

    # PageTemplate already registers onPage=on_page for every page.
    # BaseDocTemplate.build() does not accept onFirstPage/onLaterPages
    # (those are SimpleDocTemplate-only kwargs) — pass story only.
    doc.build(story)
    return buf.getvalue()
