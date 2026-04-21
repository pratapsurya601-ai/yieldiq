# backend/services/newsletter_render_service.py
# ═══════════════════════════════════════════════════════════════
# Founder-authored weekly newsletter renderer.
#
# Reads a Markdown file (with YAML-ish frontmatter), fetches live
# stock-summary data from the YieldIQ public API, and merges the
# two into the responsive HTML template at
# `backend/templates/newsletter/weekly_pick.html`.
#
# The Markdown body becomes the "Founder Note" section; everything
# else (verdict banner, Prism hex, metrics table, AI summary) is
# pulled live from the canonical AnalysisResponse so the numbers in
# the email always match what's on the site at send time.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("yieldiq.newsletter_render")

# ── Paths ────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "templates" / "newsletter" / "weekly_pick.html"
)

# ── Public API base ──────────────────────────────────────────────
# Local dev defaults to localhost; CI / GH Actions overrides via
# NEWSLETTER_API_BASE so the renderer can pull production payloads.
_DEFAULT_API_BASE = os.environ.get(
    "NEWSLETTER_API_BASE",
    "http://localhost:8000",
)
_OG_IMAGE_BASE = os.environ.get(
    "NEWSLETTER_OG_BASE",
    "https://api.yieldiq.in",
)
_SITE_URL = os.environ.get("NEWSLETTER_SITE_URL", "https://yieldiq.in")

# Reuse the SEBI block from the email service so we have one canonical
# disclaimer string in the codebase.
try:
    from backend.services.email_service import (
        SEBI_DISCLAIMER as _SEBI_DISCLAIMER,
        _get_unsubscribe_url as _build_unsub_url,
    )
except Exception:  # pragma: no cover — fallback if circular at import
    _SEBI_DISCLAIMER = (
        "SEBI Disclaimer: YieldIQ is not a SEBI-registered investment "
        "advisor. All data, analysis, and scores are for informational "
        "purposes only and do not constitute investment advice."
    )

    def _build_unsub_url(email: str) -> str:
        return f"{_SITE_URL}/unsubscribe?email={email}"


# ════════════════════════════════════════════════════════════════
# Frontmatter parser — minimal YAML subset (key: value strings)
# ════════════════════════════════════════════════════════════════

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z",
    re.DOTALL,
)


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter_dict, body_markdown).

    Accepts only `key: value` lines, optionally quoted. Anything fancy
    (lists, nested maps) is out of scope — newsletter posts have a
    fixed flat schema. Comments (#...) at end of line are stripped.
    """
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    block, body = m.group(1), m.group(2)
    fm: dict[str, str] = {}
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        k, v = stripped.split(":", 1)
        v = v.strip()
        # Strip inline comment
        if "#" in v:
            # only treat unquoted # as comment
            quote_open = v.startswith(("'", '"'))
            if not quote_open:
                v = v.split("#", 1)[0].rstrip()
        # Unquote
        if (v.startswith('"') and v.endswith('"')) or (
            v.startswith("'") and v.endswith("'")
        ):
            v = v[1:-1]
        fm[k.strip()] = v
    return fm, body


# ════════════════════════════════════════════════════════════════
# Markdown → HTML — minimal renderer (no new dep required)
#
# We support exactly what the founder-note template needs:
#   - ## headings
#   - paragraphs (blank-line separated)
#   - **bold** and *italic*
#   - bullet lists ("- ")
#   - inline links [text](url)
#
# If `mistune` is installed, we use it. Otherwise we fall back to
# this in-house renderer so the script works on a clean machine
# without `pip install`.
# ════════════════════════════════════════════════════════════════


def _md_to_html(md: str) -> str:
    """Render a small Markdown subset to inline-styled HTML."""
    try:
        import mistune  # type: ignore
        html = mistune.html(md.strip())
        return _restyle_mistune_html(html)
    except Exception:
        return _fallback_md_to_html(md)


def _restyle_mistune_html(html: str) -> str:
    """Inject inline styles into mistune output so email clients
    that strip <style> blocks still render the typography correctly.
    """
    replacements = {
        "<h2>": (
            '<h2 style="margin:24px 0 10px;font-family:Georgia,'
            "'Times New Roman',serif;font-size:19px;font-weight:700;"
            'color:#0F172A;letter-spacing:-0.2px;">'
        ),
        "<h3>": (
            '<h3 style="margin:18px 0 8px;font-family:Georgia,'
            "'Times New Roman',serif;font-size:16px;font-weight:700;"
            'color:#0F172A;">'
        ),
        "<p>": (
            '<p style="margin:0 0 14px;font-size:16px;line-height:1.7;'
            'color:#1E293B;">'
        ),
        "<ul>": (
            '<ul style="margin:0 0 16px;padding:0 0 0 20px;'
            'font-size:16px;line-height:1.7;color:#1E293B;">'
        ),
        "<li>": '<li style="margin:0 0 6px;">',
        "<strong>": '<strong style="color:#0F172A;font-weight:700;">',
        "<em>": '<em style="color:#475569;">',
        "<a href=": '<a style="color:#0F172A;text-decoration:underline;" href=',
    }
    for k, v in replacements.items():
        html = html.replace(k, v)
    return html


def _fallback_md_to_html(md: str) -> str:
    """Tiny in-house Markdown renderer for the founder-note subset.

    Not feature-complete — intentionally so. Anything weirder than the
    listed primitives should be authored as raw HTML in the .md file.
    """
    out: list[str] = []
    lines = md.strip().splitlines()
    i = 0
    n = len(lines)

    def _inline(s: str) -> str:
        # bold
        s = re.sub(r"\*\*(.+?)\*\*",
                   r'<strong style="color:#0F172A;font-weight:700;">\1</strong>',
                   s)
        # italic
        s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
                   r'<em style="color:#475569;">\1</em>', s)
        # links
        s = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            r'<a style="color:#0F172A;text-decoration:underline;" href="\2">\1</a>',
            s,
        )
        return s

    while i < n:
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue
        if line.startswith("## "):
            out.append(
                '<h2 style="margin:24px 0 10px;font-family:Georgia,'
                "'Times New Roman',serif;font-size:19px;font-weight:700;"
                'color:#0F172A;letter-spacing:-0.2px;">'
                + _inline(line[3:].strip()) + "</h2>"
            )
            i += 1
            continue
        if line.startswith("### "):
            out.append(
                '<h3 style="margin:18px 0 8px;font-family:Georgia,'
                "'Times New Roman',serif;font-size:16px;font-weight:700;"
                'color:#0F172A;">'
                + _inline(line[4:].strip()) + "</h3>"
            )
            i += 1
            continue
        if line.startswith("- "):
            items = []
            while i < n and lines[i].rstrip().startswith("- "):
                items.append(
                    '<li style="margin:0 0 6px;">'
                    + _inline(lines[i].rstrip()[2:].strip())
                    + "</li>"
                )
                i += 1
            out.append(
                '<ul style="margin:0 0 16px;padding:0 0 0 20px;'
                'font-size:16px;line-height:1.7;color:#1E293B;">'
                + "".join(items) + "</ul>"
            )
            continue
        # Paragraph: collect until blank line
        para = [line]
        i += 1
        while i < n and lines[i].rstrip():
            para.append(lines[i].rstrip())
            i += 1
        out.append(
            '<p style="margin:0 0 14px;font-size:16px;line-height:1.7;'
            'color:#1E293B;">'
            + _inline(" ".join(para)) + "</p>"
        )
    return "\n".join(out)


# ════════════════════════════════════════════════════════════════
# Live data fetch
# ════════════════════════════════════════════════════════════════


def fetch_stock_summary(ticker: str, api_base: str | None = None) -> dict[str, Any]:
    """GET /api/v1/public/stock-summary/{ticker}.

    Returns the JSON dict on 200; raises RuntimeError otherwise so
    callers can decide whether to bail or fall back to a stub payload.
    """
    base = (api_base or _DEFAULT_API_BASE).rstrip("/")
    url = f"{base}/api/v1/public/stock-summary/{ticker}"
    logger.info("fetching stock summary: %s", url)
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, headers={"User-Agent": "yieldiq-newsletter/1.0"})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        raise RuntimeError(f"stock-summary fetch failed for {ticker}: {e}") from e


# ════════════════════════════════════════════════════════════════
# Verdict + metric formatting
# ════════════════════════════════════════════════════════════════


_VERDICT_PALETTE = {
    "undervalued": {
        "label_template": "UNDERVALUED by {mos:.1f}%",
        "fg": "#047857",
        "fg_muted": "#065F46",
        "bg": "#ECFDF5",
        "border": "#A7F3D0",
    },
    "fairly_valued": {
        "label_template": "FAIRLY VALUED",
        "fg": "#92400E",
        "fg_muted": "#78350F",
        "bg": "#FFFBEB",
        "border": "#FDE68A",
    },
    "overvalued": {
        "label_template": "OVERVALUED by {mos_abs:.1f}%",
        "fg": "#B91C1C",
        "fg_muted": "#991B1B",
        "bg": "#FEF2F2",
        "border": "#FECACA",
    },
    "avoid": {
        "label_template": "AVOID",
        "fg": "#7F1D1D",
        "fg_muted": "#7F1D1D",
        "bg": "#FEE2E2",
        "border": "#FCA5A5",
    },
}


def _verdict_block(verdict: str, mos: float | None) -> dict[str, str]:
    key = (verdict or "").lower().replace("-", "_").replace(" ", "_")
    palette = _VERDICT_PALETTE.get(key, _VERDICT_PALETTE["fairly_valued"])
    mos_val = mos or 0.0
    label = palette["label_template"].format(mos=mos_val, mos_abs=abs(mos_val))
    return {
        "verdict_label": label,
        "verdict_fg": palette["fg"],
        "verdict_fg_muted": palette["fg_muted"],
        "verdict_bg": palette["bg"],
        "verdict_border": palette["border"],
    }


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "&mdash;"
    try:
        return f"{float(v):.1f}%"
    except Exception:
        return "&mdash;"


def _fmt_num(v: Any, dp: int = 1) -> str:
    if v is None:
        return "&mdash;"
    try:
        return f"{float(v):.{dp}f}"
    except Exception:
        return "&mdash;"


def _fmt_inr(v: Any) -> str:
    if v is None:
        return "&mdash;"
    try:
        return f"&#8377;{float(v):,.0f}"
    except Exception:
        return "&mdash;"


def _color_for_roce(roce: Any) -> str:
    try:
        r = float(roce)
        if r >= 20:
            return "#047857"
        if r >= 12:
            return "#0F172A"
        return "#B91C1C"
    except Exception:
        return "#64748B"


def _color_for_mos(mos: Any) -> str:
    try:
        m = float(mos)
        if m >= 15:
            return "#047857"
        if m >= 0:
            return "#0F172A"
        return "#B91C1C"
    except Exception:
        return "#64748B"


def _color_for_piotroski(p: Any) -> str:
    try:
        s = float(p)
        if s >= 7:
            return "#047857"
        if s >= 4:
            return "#0F172A"
        return "#B91C1C"
    except Exception:
        return "#64748B"


def _color_for_pe(pe: Any) -> str:
    try:
        v = float(pe)
        if v <= 0:
            return "#64748B"
        if v <= 25:
            return "#047857"
        if v <= 45:
            return "#0F172A"
        return "#B91C1C"
    except Exception:
        return "#64748B"


def _build_metrics_rows(summary: dict[str, Any]) -> str:
    """Six-row metrics table — ROCE, P/E, MoS, Moat, Piotroski, FV."""
    pe = summary.get("pe_ratio")
    if pe is None:
        # stock-summary doesn't always carry PE; derive from price/eps
        # if available. Otherwise leave blank.
        pe = None

    rows: list[tuple[str, str, str]] = [
        (
            "ROCE",
            _fmt_pct(summary.get("roce")),
            _color_for_roce(summary.get("roce")),
        ),
        (
            "P/E",
            _fmt_num(pe, 1) if pe is not None else "&mdash;",
            _color_for_pe(pe),
        ),
        (
            "Margin of Safety",
            _fmt_pct(summary.get("mos")),
            _color_for_mos(summary.get("mos")),
        ),
        (
            "Moat",
            str(summary.get("moat") or "&mdash;").title(),
            "#0F172A",
        ),
        (
            "Piotroski",
            f"{summary.get('piotroski', '—')}/9" if summary.get("piotroski") is not None else "&mdash;",
            _color_for_piotroski(summary.get("piotroski")),
        ),
        (
            "Fair Value",
            _fmt_inr(summary.get("fair_value")),
            "#0F172A",
        ),
    ]

    out = []
    for i, (label, value, color) in enumerate(rows):
        border = "" if i == len(rows) - 1 else "border-bottom:1px solid #F1F5F9;"
        out.append(
            f"""
            <tr>
              <td style="padding:12px 16px;{border}color:#64748B;font-size:13px;">{label}</td>
              <td align="right" style="padding:12px 16px;{border}color:{color};font-weight:700;font-family:'SF Mono',Menlo,Consolas,monospace;font-size:14px;">{value}</td>
            </tr>"""
        )
    return "".join(out)


def _ai_summary_block(summary: dict[str, Any], override: str = "") -> str:
    """Optional 1-line narrative banner above the founder note."""
    text = (override or summary.get("ai_summary_snippet") or "").strip()
    if not text:
        return ""
    return f"""
          <tr>
            <td style="padding:18px 32px 0;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="background:#F8FAFC;border-left:3px solid #0F172A;padding:14px 18px;">
                    <p style="margin:0;font-size:14px;line-height:1.55;color:#334155;font-style:italic;">
                      {text}
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>"""


# ════════════════════════════════════════════════════════════════
# Main entrypoint
# ════════════════════════════════════════════════════════════════


def render_weekly_pick(
    markdown_path: str | Path,
    *,
    api_base: str | None = None,
    recipient_email: str = "subscriber@yieldiq.in",
    summary_override: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Render a founder-authored weekly pick to email-ready HTML.

    Parameters
    ----------
    markdown_path : path to a .md file with frontmatter (see schema in
        the project README and `content/newsletter/2026-04-22-...md`).
    api_base : override the public-API base URL. Falls back to env
        NEWSLETTER_API_BASE, then localhost:8000.
    recipient_email : used to build the unsubscribe URL. The `--send`
        path passes the real address; preview/test paths pass a stub.
    summary_override : dict with the same shape as the
        `/public/stock-summary/{ticker}` response. Used by tests and
        for offline `--dry-run` against a snapshotted payload.

    Returns
    -------
    (subject, html) tuple ready for SendGrid.
    """
    md_path = Path(markdown_path)
    if not md_path.exists():
        raise FileNotFoundError(f"newsletter markdown not found: {md_path}")

    raw = md_path.read_text(encoding="utf-8")
    fm, body_md = _parse_frontmatter(raw)

    ticker = fm.get("ticker", "").strip()
    if not ticker:
        raise ValueError(f"frontmatter `ticker` missing in {md_path}")
    if not (ticker.endswith(".NS") or ticker.endswith(".BO")):
        ticker = f"{ticker}.NS"
    display_ticker = ticker.replace(".NS", "").replace(".BO", "")

    title = fm.get("title", f"This Week's Pick: {display_ticker}")
    week = fm.get("week", "??")
    issue_date_raw = fm.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        issue_date_human = datetime.strptime(issue_date_raw, "%Y-%m-%d").strftime("%b %d, %Y")
    except Exception:
        issue_date_human = issue_date_raw
    preheader = fm.get("preheader", f"YieldIQ Weekly — {display_ticker}, {issue_date_human}").strip()

    # Live data — or offline override
    if summary_override is not None:
        summary = summary_override
    else:
        try:
            summary = fetch_stock_summary(ticker, api_base=api_base)
        except RuntimeError as e:
            logger.warning("falling back to stub summary: %s", e)
            summary = _stub_summary(ticker, display_ticker)

    # Mosaic the template
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    metrics_rows = _build_metrics_rows(summary)
    verdict = _verdict_block(summary.get("verdict") or "fairly_valued", summary.get("mos"))
    ai_block = _ai_summary_block(summary, override=fm.get("summary_override", ""))
    founder_html = _md_to_html(body_md)

    prism_image_url = f"{_OG_IMAGE_BASE.rstrip('/')}/api/og/analysis/{display_ticker}"
    analysis_url = f"{_SITE_URL.rstrip('/')}/analysis/{display_ticker}"
    unsub_url = _build_unsub_url(recipient_email)

    subject = (
        f"YieldIQ Weekly #{week}: {fm.get('title', display_ticker)}"
        if fm.get("title") else
        f"YieldIQ Weekly #{week}: {display_ticker}"
    )

    fillers = {
        "{{ subject }}": subject,
        "{{ preheader }}": preheader,
        "{{ week }}": str(week),
        "{{ issue_date_human }}": issue_date_human,
        "{{ title }}": title,
        "{{ company_name }}": str(summary.get("company_name") or display_ticker),
        "{{ display_ticker }}": display_ticker,
        "{{ sector }}": str(summary.get("sector") or "—"),
        "{{ verdict_label }}": verdict["verdict_label"],
        "{{ verdict_fg }}": verdict["verdict_fg"],
        "{{ verdict_fg_muted }}": verdict["verdict_fg_muted"],
        "{{ verdict_bg }}": verdict["verdict_bg"],
        "{{ verdict_border }}": verdict["verdict_border"],
        "{{ prism_image_url }}": prism_image_url,
        "{{ analysis_url }}": analysis_url,
        "{{ ai_summary_block }}": ai_block,
        "{{ founder_note_html }}": founder_html,
        "{{ metrics_rows }}": metrics_rows,
        "{{ unsubscribe_url }}": unsub_url,
        "{{ sebi_disclaimer }}": _SEBI_DISCLAIMER,
        "{{ year }}": str(datetime.now(timezone.utc).year),
    }
    html = template
    for k, v in fillers.items():
        html = html.replace(k, v)

    return subject, html


def _stub_summary(ticker: str, display_ticker: str) -> dict[str, Any]:
    """Last-ditch fallback so --dry-run never hard-fails on a missing API.

    Renders the template with placeholder dashes; the founder note
    still ships intact so the user can preview the prose.
    """
    return {
        "ticker": ticker,
        "company_name": display_ticker,
        "sector": "—",
        "fair_value": None,
        "current_price": None,
        "mos": 0.0,
        "verdict": "fairly_valued",
        "score": None,
        "moat": None,
        "piotroski": None,
        "roce": None,
        "ai_summary_snippet": "",
    }
