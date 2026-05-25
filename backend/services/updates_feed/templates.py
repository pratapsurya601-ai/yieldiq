"""Template engine for the Portfolio Updates Feed (P0 #1).

Pure functions: each builder takes a typed dict describing the source
event and returns ``{"headline": str, "detail": str}``. NO LLM calls,
NO network calls, NO DB calls — the aggregator (scripts/build_updates_feed.py)
passes already-loaded rows in.

SEBI discipline (memory/feedback_yieldiq_discipline.md):
  - Never use "buy", "sell", "hold", "recommend", "target".
  - "Verdict" copy describes the engine's classification, not advice.
  - All numeric formatting in ₹ uses lakhs/crores per Indian convention.

Categories handled here:
  - earnings           — quarterly / annual results
  - valuations         — model fair-value deltas (manifest / analysis_cache)
  - intrinsic_updates  — same as valuations but flagged as engine-driven
  - dividends          — declared / ex-date events from corporate_actions
  - insider_trading    — insider_trading table rows
  - risk_legal         — manifest red_flags_structured or SEBI filings
  - other              — generic fallback

All builders are total: any missing field falls back to a safe default
string so the aggregator never inserts a row with a NULL headline.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Optional

# Categories accepted by the DB CHECK constraint
# (data_pipeline/migrations/064_portfolio_updates_feed.sql).
CATEGORIES = (
    "earnings",
    "valuations",
    "intrinsic_updates",
    "dividends",
    "insider_trading",
    "risk_legal",
    "other",
)


# ─────────────────────────── helpers ────────────────────────────

def _fmt_rs(value: Optional[float]) -> str:
    """Format a rupee amount for display (₹X / ₹X.XL / ₹X.XCr)."""
    if value is None:
        return "₹—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "₹—"
    abs_v = abs(v)
    sign = "-" if v < 0 else ""
    if abs_v >= 1_00_00_000:  # 1 crore
        return f"{sign}₹{abs_v / 1_00_00_000:.2f}Cr"
    if abs_v >= 1_00_000:  # 1 lakh
        return f"{sign}₹{abs_v / 1_00_000:.2f}L"
    if abs_v >= 1_000:
        return f"{sign}₹{abs_v / 1_000:.1f}K"
    if abs_v >= 1:
        return f"{sign}₹{abs_v:.2f}"
    return f"{sign}₹{abs_v:.4f}"


def _fmt_pct(delta: Optional[float]) -> str:
    if delta is None:
        return "—%"
    try:
        d = float(delta)
    except (TypeError, ValueError):
        return "—%"
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.1f}%"


def _fmt_date(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (datetime, date)):
        return value.strftime("%d %b %Y")
    return str(value)


def _verdict_phrase(curr: Optional[float], prior: Optional[float]) -> str:
    """SEBI-safe verb phrase describing direction of an earnings metric.

    Returns one of: "beat", "missed", "matched", "ahead of", "below",
    "in line with". Never includes buy/sell/hold/target.
    """
    if curr is None or prior is None:
        return "in line with"
    try:
        c, p = float(curr), float(prior)
    except (TypeError, ValueError):
        return "in line with"
    if p == 0:
        return "in line with"
    delta = (c - p) / abs(p)
    if delta >= 0.05:
        return "ahead of"
    if delta <= -0.05:
        return "below"
    return "in line with"


# ─────────────────────────── builders ───────────────────────────

def render_earnings(event: Mapping[str, Any]) -> dict[str, str]:
    """Earnings template.

    Expected keys (any may be missing):
        period          — e.g. "Q4 FY25"
        eps             — current period EPS (₹/share)
        eps_prior       — prior-period EPS for the same line
        prior_period    — e.g. "Q4 FY24"
        revenue         — current revenue (₹)
        revenue_prior   — prior-period revenue
        revenue_growth  — pre-computed YoY % (optional; computed if absent)
    """
    period = event.get("period") or "Latest quarter"
    prior_period = event.get("prior_period") or "prior period"
    eps = event.get("eps")
    eps_prior = event.get("eps_prior")
    revenue = event.get("revenue")
    revenue_prior = event.get("revenue_prior")

    verdict = _verdict_phrase(eps, eps_prior)
    headline = f"{period} earnings: EPS {verdict} prior-period print"

    eps_part = f"EPS: {_fmt_rs(eps)}"
    if eps_prior is not None:
        direction = "up from" if (eps or 0) >= (eps_prior or 0) else "down from"
        eps_part += f" ({direction} {_fmt_rs(eps_prior)} in {prior_period})"
    eps_part += "."

    rev_part = ""
    if revenue is not None:
        rev_part = f" Revenue: {_fmt_rs(revenue)}"
        growth = event.get("revenue_growth")
        if growth is None and revenue_prior:
            try:
                growth = (float(revenue) - float(revenue_prior)) / abs(float(revenue_prior)) * 100.0
            except (TypeError, ValueError, ZeroDivisionError):
                growth = None
        if growth is not None:
            direction = "up" if growth >= 0 else "down"
            rev_part += f" ({direction} {abs(growth):.1f}% vs {prior_period})."
        else:
            rev_part += "."

    return {"headline": headline, "detail": (eps_part + rev_part).strip()}


def render_valuations(event: Mapping[str, Any]) -> dict[str, str]:
    """Model fair-value change template.

    Expected keys:
        old_fv, new_fv  — floats
        reason          — short engine-side rationale (optional)
    """
    old_fv = event.get("old_fv")
    new_fv = event.get("new_fv")
    reason = event.get("reason") or "Model inputs refreshed."

    delta_pct: Optional[float] = None
    try:
        if old_fv and new_fv is not None:
            delta_pct = (float(new_fv) - float(old_fv)) / abs(float(old_fv)) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        delta_pct = None

    headline = (
        f"Model fair value changed: {_fmt_rs(old_fv)} → {_fmt_rs(new_fv)} "
        f"({_fmt_pct(delta_pct)})"
    )
    detail = (
        f"Our internal valuation model now estimates fair value at {_fmt_rs(new_fv)} "
        f"(previously {_fmt_rs(old_fv)}). {reason}"
    )
    return {"headline": headline, "detail": detail}


def render_intrinsic_updates(event: Mapping[str, Any]) -> dict[str, str]:
    """Intrinsic-value update — same shape as valuations but flagged as
    engine-driven (cache invalidation manifest entry, not a price-driven
    revision)."""
    out = render_valuations(event)
    out["headline"] = "Intrinsic value updated: " + out["headline"].split(": ", 1)[-1]
    return out


def render_dividends(event: Mapping[str, Any]) -> dict[str, str]:
    """Dividend template.

    Expected keys:
        period        — "FY25 Final" / "Interim 2026" / etc.
        amount        — ₹/share (uses corporate_actions.ratio for dividends)
        ex_date       — date
        record_date   — optional
    """
    period = event.get("period") or "Dividend"
    amount = event.get("amount")
    ex_date = event.get("ex_date")
    record_date = event.get("record_date")

    headline = (
        f"{period} dividend declared: {_fmt_rs(amount)}/share, "
        f"ex-date {_fmt_date(ex_date)}"
    )
    detail = (
        f"The company has declared a dividend of {_fmt_rs(amount)} per share "
        f"with an ex-date of {_fmt_date(ex_date)}."
    )
    if record_date is not None:
        detail += f" Record date: {_fmt_date(record_date)}."
    return {"headline": headline, "detail": detail}


def render_insider_trading(event: Mapping[str, Any]) -> dict[str, str]:
    """Insider-trading template.

    Expected keys (mirrors insider_trading table):
        acquirer_name
        buy_qty / sell_qty  — at most one non-zero
        transaction_value_cr — ₹ crores (optional)
        filing_date
        acquirer_category   — optional ("Promoter" / "Director" / etc.)
    """
    name = event.get("acquirer_name") or "An insider"
    buy_qty = event.get("buy_qty") or 0
    sell_qty = event.get("sell_qty") or 0
    txn_value_cr = event.get("transaction_value_cr")
    filing_date = event.get("filing_date")
    category = event.get("acquirer_category")

    if buy_qty and not sell_qty:
        verb, qty = "acquired", int(buy_qty)
    elif sell_qty and not buy_qty:
        verb, qty = "disposed of", int(sell_qty)
    else:
        # Mixed / unknown direction — neutral phrasing, no advice.
        verb, qty = "transacted", int(buy_qty or sell_qty or 0)

    qty_str = f"{qty:,}" if qty else "shares"
    headline = f"{name} {verb} {qty_str} shares"
    if category:
        headline = f"{name} ({category}) {verb} {qty_str} shares"

    detail = f"Filing date: {_fmt_date(filing_date)}."
    if txn_value_cr is not None:
        try:
            detail = (
                f"Transaction value: ₹{float(txn_value_cr):.2f} Cr. " + detail
            )
        except (TypeError, ValueError):
            pass
    return {"headline": headline, "detail": detail}


def render_risk_legal(event: Mapping[str, Any]) -> dict[str, str]:
    """Risk / Legal template.

    Expected keys:
        flag         — short label (e.g. "Auditor change", "SEBI inquiry")
        description  — longer explanation
        as_of        — when the flag was recorded
    """
    flag = event.get("flag") or "Risk flag"
    description = event.get("description") or (
        "A new risk-or-governance flag was recorded for this company."
    )
    as_of = event.get("as_of")
    headline = f"Risk flag noted: {flag}"
    detail = description
    if as_of is not None:
        detail += f" (recorded {_fmt_date(as_of)})."
    return {"headline": headline, "detail": detail}


def render_other(event: Mapping[str, Any]) -> dict[str, str]:
    headline = event.get("headline") or "Portfolio update"
    detail = event.get("detail") or "A new event was recorded for this holding."
    return {"headline": str(headline), "detail": str(detail)}


_BUILDERS = {
    "earnings": render_earnings,
    "valuations": render_valuations,
    "intrinsic_updates": render_intrinsic_updates,
    "dividends": render_dividends,
    "insider_trading": render_insider_trading,
    "risk_legal": render_risk_legal,
    "other": render_other,
}


def render(category: str, event: Mapping[str, Any]) -> dict[str, str]:
    """Dispatch to the per-category builder. Unknown category → "other"."""
    builder = _BUILDERS.get(category, render_other)
    return builder(event)
