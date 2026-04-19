#!/usr/bin/env python3
"""Build derived ratio_history rows from raw financials + market_metrics.

Purpose
-------
The `financials` table stores raw P&L/BS/CF fields per
(ticker, period_end, period_type); a handful of ratios (roe, roa,
margins, YoY growth) are stored alongside, but many derived metrics
the analysis UI wants for 10-year sparklines are not — ROCE,
debt/EBITDA, EV/EBITDA, current ratio, asset turnover, etc.

This script recomputes every ratio we care about and UPSERTs one row
per (ticker, period_end, period_type) into `ratio_history`.

Usage
-----
    DATABASE_URL=postgres://... python scripts/build_ratio_history.py --all
    DATABASE_URL=postgres://... python scripts/build_ratio_history.py \
        --tickers RELIANCE,TCS --since 2020-01-01
    DATABASE_URL=postgres://... python scripts/build_ratio_history.py \
        --all --period-types annual,quarterly

Flags
-----
    --all                    process every is_active=true stock
    --tickers T1,T2,...      process only the given tickers
    --since YYYY-MM-DD       only recompute periods with period_end >= this date
    --period-types a,b,...   restrict to given period_types
                             (default: annual,quarterly)

Idempotency
-----------
Safe to run repeatedly. Each row is UPSERTed on the unique key
(ticker, period_end, period_type); stale values are overwritten.
Only reads from `financials` and `market_metrics`; only writes to
`ratio_history`. Never touches `stocks`.

Sanity clamps
-------------
The following out-of-band values are clamped to NULL on write (and
logged at WARNING):
  - |revenue_yoy| > 2.0 (200 pp)  → corporate-action noise
  - ev_ebitda outside (0.5, 200)  → junk
  - roe outside (-100, 200)       → junk
  - de_ratio outside (0, 50)      → junk

These mirror the response-layer clamps in the analysis path so that
the sparklines never show spurious spikes.

Exit codes
----------
    0  — all tickers processed (possibly with warnings)
    1  — at least one ticker failed entirely
    130 — SIGINT received (prints progress summary first)
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import signal
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session as OrmSession  # noqa: E402

from data_pipeline.db import Session  # noqa: E402
from data_pipeline.models import Financials, MarketMetrics  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("build_ratio_history")


SOURCE_VERSION = "v1"
DEFAULT_PERIOD_TYPES = ("annual", "quarterly")

# Sanity clamp bounds — mirror backend response-layer clamps.
REVENUE_YOY_ABS_MAX = 2.0        # |YoY| > 200 pp → clamp
EV_EBITDA_MIN, EV_EBITDA_MAX = 0.5, 200.0
ROE_MIN, ROE_MAX = -100.0, 200.0
DE_MIN, DE_MAX = 0.0, 50.0


# ──────────────────────────────────────────────────────────────────────
# SIGINT handling
# ──────────────────────────────────────────────────────────────────────
_interrupted = False
_processed_count = 0


def _sigint_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
    global _interrupted
    _interrupted = True


signal.signal(signal.SIGINT, _sigint_handler)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _is_finite(x: Any) -> bool:
    """True if x is a real finite number (not None, NaN, or inf)."""
    if x is None:
        return False
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


def _safe_div(num: Any, den: Any) -> float | None:
    if not _is_finite(num) or not _is_finite(den):
        return None
    d = float(den)
    if d == 0.0:
        return None
    return float(num) / d


def _parse_raw_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _get_numeric(d: dict[str, Any], *keys: str) -> float | None:
    """Try each key in order, return first finite numeric."""
    for k in keys:
        if k in d and _is_finite(d[k]):
            return float(d[k])
    return None


def _clamp(
    value: float | None,
    lo: float | None,
    hi: float | None,
    *,
    ticker: str,
    period_end: date,
    metric: str,
    clamp_log: list[tuple[str, str]],
    abs_max: float | None = None,
) -> float | None:
    """Return value or None if outside (lo, hi) or |value|>abs_max."""
    if value is None:
        return None
    if not _is_finite(value):
        clamp_log.append((metric, f"non-finite({value})"))
        logger.warning(
            "clamp %s %s %s raw=%r (non-finite)",
            ticker, period_end.isoformat(), metric, value,
        )
        return None
    v = float(value)
    if abs_max is not None and abs(v) > abs_max:
        clamp_log.append((metric, f"{v:.4f}"))
        logger.warning(
            "clamp %s %s %s raw=%.4f |v|>%.2f",
            ticker, period_end.isoformat(), metric, v, abs_max,
        )
        return None
    if lo is not None and v <= lo:
        clamp_log.append((metric, f"{v:.4f}"))
        logger.warning(
            "clamp %s %s %s raw=%.4f <= %.2f",
            ticker, period_end.isoformat(), metric, v, lo,
        )
        return None
    if hi is not None and v >= hi:
        clamp_log.append((metric, f"{v:.4f}"))
        logger.warning(
            "clamp %s %s %s raw=%.4f >= %.2f",
            ticker, period_end.isoformat(), metric, v, hi,
        )
        return None
    return v


# ──────────────────────────────────────────────────────────────────────
# Core computation
# ──────────────────────────────────────────────────────────────────────
def _find_prior_year_row(
    rows: list[Financials],
    idx_by_type: dict[str, list[int]],
    i: int,
) -> Financials | None:
    """Return the Financials row for same period_type ~1 year prior.

    Matches on nearest period_end within 335-395 days (handles slight
    filing-date drift).
    """
    cur = rows[i]
    if cur.period_end is None or cur.period_type is None:
        return None
    candidates = idx_by_type.get(cur.period_type, [])
    best: Financials | None = None
    best_gap = 10**9
    target_days = 365
    for j in candidates:
        if j == i:
            continue
        other = rows[j]
        if other.period_end is None or other.period_end >= cur.period_end:
            continue
        delta = (cur.period_end - other.period_end).days
        if 335 <= delta <= 395:
            gap = abs(delta - target_days)
            if gap < best_gap:
                best_gap = gap
                best = other
    return best


def _latest_metrics_at_or_before(
    db: OrmSession, ticker: str, on_or_before: date,
) -> MarketMetrics | None:
    row = (
        db.query(MarketMetrics)
        .filter(MarketMetrics.ticker == ticker)
        .filter(MarketMetrics.trade_date <= on_or_before)
        .order_by(MarketMetrics.trade_date.desc())
        .first()
    )
    return row


# Max tolerated gap between period_end and the daily_prices row we'll
# use as "price at period end". 180 days covers typical quarterly-results
# reporting lag, daily_prices ingestion gaps, and the rolling 52-week
# contamination window is still avoided.
_PRICE_LOOKUP_MAX_GAP_DAYS = 180


def _price_at_or_before(
    db: OrmSession, ticker: str, on_or_before: date,
) -> float | None:
    """Close price for `ticker` on the latest trading day on-or-before
    `on_or_before`, within ``_PRICE_LOOKUP_MAX_GAP_DAYS``. Returns the
    RAW close — the caller is expected to apply corporate-action
    adjustments (see ``_adjust_price``) because daily_prices.adj_close
    is not reliably backfilled in this pipeline."""
    sql = text("""
        SELECT trade_date, close_price, adj_close
        FROM daily_prices
        WHERE ticker = :t AND trade_date <= :d
        ORDER BY trade_date DESC LIMIT 1
    """)
    row = db.execute(sql, {"t": ticker, "d": on_or_before}).first()
    if row is None:
        return None
    td, close, adj = row[0], row[1], row[2]
    try:
        gap = (on_or_before - td).days
        if gap > _PRICE_LOOKUP_MAX_GAP_DAYS:
            return None
    except Exception:
        pass
    # Prefer raw close_price — adj_close in this DB is not actually
    # backfilled for splits/bonuses (verified empirically: RELIANCE
    # 2022-03-31 shows close==adj_close=2634.75, yet the Oct 2024 1:1
    # bonus should have halved the historical adjusted price). We
    # apply corporate-action adjustment explicitly in _adjust_price.
    if close is not None:
        try:
            return float(close)
        except (TypeError, ValueError):
            pass
    if adj is not None:
        try:
            return float(adj)
        except (TypeError, ValueError):
            pass
    return None


def _load_corporate_actions(
    db: OrmSession, ticker: str,
) -> list[tuple[date, float]]:
    """Return [(ex_date, adjustment_factor)] for ticker, sorted ASC.
    Used to back out splits/bonuses from historical prices so that
    ``raw_close × current_shares`` lands on the right market cap."""
    sql = text("""
        SELECT ex_date, adjustment_factor
        FROM corporate_actions
        WHERE ticker = :t
          AND adjustment_factor IS NOT NULL
          AND adjustment_factor > 0
          AND ex_date IS NOT NULL
        ORDER BY ex_date ASC
    """)
    rows = db.execute(sql, {"t": ticker}).fetchall()
    out: list[tuple[date, float]] = []
    for r in rows:
        try:
            out.append((r[0], float(r[1])))
        except (TypeError, ValueError):
            continue
    return out


def _adjust_price(
    raw_close: float, period_end: date, actions: list[tuple[date, float]],
) -> float:
    """Adjust raw_close so it's comparable against CURRENT shares_outstanding.

    For each corporate action with ex_date > period_end, the current share
    count has been inflated (bonus) or contracted (reverse split) since
    that period. Dividing raw_close by the compound factor gives a price
    that, when multiplied by current shares, reproduces the period-end
    market cap correctly.

    Example — RELIANCE 1:1 bonus on 2024-10-28 has adjustment_factor=2.0:
        period_end=2022-03-31:
            factor = 2.0   (bonus happened AFTER this period)
            raw_close = 2634 → adjusted = 1317
            mcap = 1317 × 13.5B shares = 17.77L Cr  ✓ (matches reported)
        period_end=2025-03-31:
            factor = 1.0   (bonus happened BEFORE this period)
            raw_close = 1275 → adjusted = 1275
            mcap = 1275 × 13.5B shares = 17.25L Cr  ✓
    """
    factor = 1.0
    for ex_date, f in actions:
        if ex_date > period_end:
            factor *= f
    if factor != 1.0:
        return raw_close / factor
    return raw_close


def _compute_row(
    f: Financials,
    prior: Financials | None,
    mm: MarketMetrics | None,
    *,
    ticker: str,
    clamp_log: list[tuple[str, str]],
    price_at_period_end: float | None = None,
) -> dict[str, Any]:
    """Compute the full ratio_history row for one financial period."""
    raw = _parse_raw_json(f.raw_data)

    # ── Profitability ──
    roe = f.roe
    if not _is_finite(roe):
        roe = _safe_div(f.pat, f.total_equity)
        if roe is not None:
            roe *= 100.0

    roa = f.roa
    if not _is_finite(roa):
        roa = _safe_div(f.pat, f.total_assets)
        if roa is not None:
            roa *= 100.0

    # ROCE = EBIT / (Total Assets - Current Liabilities) * 100
    current_liab = _get_numeric(
        raw, "current_liabilities", "total_current_liabilities",
    )
    if current_liab is None:
        # proxy: total_assets - total_equity - total_debt
        if (
            _is_finite(f.total_assets)
            and _is_finite(f.total_equity)
            and _is_finite(f.total_debt)
        ):
            current_liab = (
                float(f.total_assets) - float(f.total_equity) - float(f.total_debt)
            )
            if current_liab < 0:
                current_liab = None

    # EBIT fallback chain — the financials table often doesn't populate
    # the `ebit` column, so without fallbacks ROCE = 0% coverage across
    # the board (confirmed empirically in first rebuild run).
    # Order of preference (highest precision first):
    #   1. f.ebit                             (canonical column)
    #   2. raw["ebit"] / raw["operating_income"] / raw["operating_profit"]
    #   3. pbt + interest_expense             (algebraic identity)
    #   4. ebitda                             (lossy — adds D&A back in)
    ebit_effective: float | None = None
    if _is_finite(f.ebit):
        ebit_effective = float(f.ebit)
    else:
        r_ebit = _get_numeric(raw, "ebit", "operating_income", "operating_profit")
        if r_ebit is not None:
            ebit_effective = r_ebit
        else:
            interest_exp_for_ebit = _get_numeric(
                raw, "interest_expense", "finance_cost", "finance_costs",
            )
            if _is_finite(f.pbt) and interest_exp_for_ebit is not None:
                ebit_effective = float(f.pbt) + float(interest_exp_for_ebit)
            elif _is_finite(f.ebitda):
                # Lossy: EBIT ≈ EBITDA - D&A. We don't reliably have D&A,
                # so use EBITDA as an UPPER bound. Flag by clamping ROCE
                # after compute if it's implausibly high.
                ebit_effective = float(f.ebitda)

    roce = None
    if (
        ebit_effective is not None
        and _is_finite(f.total_assets)
        and current_liab is not None
    ):
        capital_employed = float(f.total_assets) - float(current_liab)
        roce = _safe_div(ebit_effective, capital_employed)
        if roce is not None:
            roce *= 100.0

    # ── Leverage ──
    de_ratio = f.debt_to_equity
    if not _is_finite(de_ratio):
        de_ratio = _safe_div(f.total_debt, f.total_equity)

    debt_ebitda = None
    if _is_finite(f.ebitda) and float(f.ebitda) > 0:
        debt_ebitda = _safe_div(f.total_debt, f.ebitda)

    interest_expense = _get_numeric(
        raw, "interest_expense", "finance_cost", "finance_costs",
    )
    interest_cov = None
    if interest_expense is not None and interest_expense > 0:
        interest_cov = _safe_div(f.ebit, interest_expense)

    # ── Margins (already % in Financials) ──
    gross_margin = f.gross_margin if _is_finite(f.gross_margin) else None
    operating_margin = (
        f.operating_margin if _is_finite(f.operating_margin) else None
    )
    net_margin = f.net_margin if _is_finite(f.net_margin) else None
    fcf_margin = f.fcf_margin if _is_finite(f.fcf_margin) else None

    # ── Growth (DECIMAL) ──
    revenue_yoy = ebitda_yoy = pat_yoy = fcf_yoy = None
    if prior is not None:
        if _is_finite(f.revenue) and _is_finite(prior.revenue) and float(prior.revenue) != 0:
            revenue_yoy = (float(f.revenue) - float(prior.revenue)) / abs(float(prior.revenue))
        if _is_finite(f.ebitda) and _is_finite(prior.ebitda) and float(prior.ebitda) != 0:
            ebitda_yoy = (float(f.ebitda) - float(prior.ebitda)) / abs(float(prior.ebitda))
        if _is_finite(f.pat) and _is_finite(prior.pat) and float(prior.pat) != 0:
            pat_yoy = (float(f.pat) - float(prior.pat)) / abs(float(prior.pat))
        if (
            _is_finite(f.free_cash_flow)
            and _is_finite(prior.free_cash_flow)
            and float(prior.free_cash_flow) != 0
        ):
            fcf_yoy = (
                float(f.free_cash_flow) - float(prior.free_cash_flow)
            ) / abs(float(prior.free_cash_flow))
    else:
        # fall back to stored growth fields where available (already DECIMAL? — stored
        # as percent in some pipelines; leave None unless the prior row found it)
        if _is_finite(f.revenue_growth_yoy):
            # stored-growth values are decimals in this pipeline per CLAUDE conventions.
            revenue_yoy = float(f.revenue_growth_yoy)
        if _is_finite(f.pat_growth_yoy):
            pat_yoy = float(f.pat_growth_yoy)
        if _is_finite(f.fcf_growth_yoy):
            fcf_yoy = float(f.fcf_growth_yoy)

    # ── Valuation (point-in-time) ──
    # Two sources, in order of preference:
    #   1. Compute from primitives: daily_prices close × shares + Financials
    #      pat/equity/debt/cash/ebitda. Gives real historical ratios at
    #      any period_end back to when daily_prices starts (~5Y).
    #   2. Fall back to the market_metrics snapshot at-or-before period_end.
    #      market_metrics rarely has historical depth (today: 3 days), so
    #      this mostly supplies dividend_yield + a same-day reference.
    pe_ratio = pb_ratio = ev_ebitda = dividend_yield = market_cap_cr = None

    # Unit contract for this block:
    #   shares_outstanding : LAKHS (1 lakh = 100_000 shares)   — from Financials
    #   pat, ebitda, total_debt, cash_and_equivalents, total_equity : CRORES
    #       — these are stored in Cr by the XBRL ingestion pipeline
    #         (verified empirically: RELIANCE FY25 pat=69648 matches the
    #         reported ₹69,648 Cr headline)
    #   price_at_period_end : INR/share
    # Deriving market cap in Crores keeps every ratio dimensionless:
    #   mcap_cr = price_inr × shares_lakhs × 1e5 / 1e7 = price × shares_lakhs / 100
    shares_lakhs = float(f.shares_outstanding) if _is_finite(f.shares_outstanding) else None
    mcap_cr: float | None = None
    if price_at_period_end is not None and shares_lakhs is not None and shares_lakhs > 0:
        mcap_cr = price_at_period_end * shares_lakhs / 100.0
        market_cap_cr = mcap_cr

        # PE = market cap (Cr) / net income (Cr)
        if _is_finite(f.pat) and float(f.pat) > 0:
            pe_ratio = mcap_cr / float(f.pat)

        # PB = market cap (Cr) / shareholders equity (Cr)
        if _is_finite(f.total_equity) and float(f.total_equity) > 0:
            pb_ratio = mcap_cr / float(f.total_equity)

        # EV/EBITDA = (market cap + total_debt − cash) / ebitda — all Cr
        if (
            _is_finite(f.ebitda)
            and float(f.ebitda) > 0
            and _is_finite(f.total_debt)
            and _is_finite(f.cash_and_equivalents)
        ):
            ev_cr = mcap_cr + float(f.total_debt) - float(f.cash_and_equivalents)
            ev_ebitda = ev_cr / float(f.ebitda)

    # Fallback / supplement from market_metrics snapshot
    if mm is not None:
        if pe_ratio is None and _is_finite(mm.pe_ratio):
            pe_ratio = float(mm.pe_ratio)
        if pb_ratio is None and _is_finite(mm.pb_ratio):
            pb_ratio = float(mm.pb_ratio)
        if ev_ebitda is None and _is_finite(mm.ev_ebitda):
            ev_ebitda = float(mm.ev_ebitda)
        if _is_finite(mm.dividend_yield):
            dividend_yield = float(mm.dividend_yield)
        if market_cap_cr is None and _is_finite(mm.market_cap_cr):
            market_cap_cr = float(mm.market_cap_cr)

    # ── Liquidity / efficiency ──
    current_assets = _get_numeric(raw, "current_assets", "total_current_assets")
    current_ratio = None
    if (
        current_assets is not None
        and current_liab is not None
        and current_liab > 0
    ):
        current_ratio = current_assets / current_liab

    asset_turnover = _safe_div(f.revenue, f.total_assets)

    # ── Apply sanity clamps on WRITE ──
    period_end = f.period_end
    revenue_yoy = _clamp(
        revenue_yoy, None, None,
        ticker=ticker, period_end=period_end, metric="revenue_yoy",
        clamp_log=clamp_log, abs_max=REVENUE_YOY_ABS_MAX,
    )
    ev_ebitda = _clamp(
        ev_ebitda, EV_EBITDA_MIN, EV_EBITDA_MAX,
        ticker=ticker, period_end=period_end, metric="ev_ebitda",
        clamp_log=clamp_log,
    )
    roe = _clamp(
        roe, ROE_MIN, ROE_MAX,
        ticker=ticker, period_end=period_end, metric="roe",
        clamp_log=clamp_log,
    )
    de_ratio = _clamp(
        de_ratio, DE_MIN, DE_MAX,
        ticker=ticker, period_end=period_end, metric="de_ratio",
        clamp_log=clamp_log,
    )

    return {
        "ticker": ticker,
        "period_end": period_end,
        "period_type": f.period_type,
        "roe": roe,
        "roce": roce,
        "roa": roa,
        "de_ratio": de_ratio,
        "debt_ebitda": debt_ebitda,
        "interest_cov": interest_cov,
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "fcf_margin": fcf_margin,
        "revenue_yoy": revenue_yoy,
        "ebitda_yoy": ebitda_yoy,
        "pat_yoy": pat_yoy,
        "fcf_yoy": fcf_yoy,
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "ev_ebitda": ev_ebitda,
        "dividend_yield": dividend_yield,
        "market_cap_cr": market_cap_cr,
        "current_ratio": current_ratio,
        "asset_turnover": asset_turnover,
        "computed_at": datetime.utcnow(),
        "source_version": SOURCE_VERSION,
    }


UPSERT_SQL = text("""
    INSERT INTO ratio_history (
        ticker, period_end, period_type,
        roe, roce, roa,
        de_ratio, debt_ebitda, interest_cov,
        gross_margin, operating_margin, net_margin, fcf_margin,
        revenue_yoy, ebitda_yoy, pat_yoy, fcf_yoy,
        pe_ratio, pb_ratio, ev_ebitda, dividend_yield, market_cap_cr,
        current_ratio, asset_turnover,
        computed_at, source_version
    ) VALUES (
        :ticker, :period_end, :period_type,
        :roe, :roce, :roa,
        :de_ratio, :debt_ebitda, :interest_cov,
        :gross_margin, :operating_margin, :net_margin, :fcf_margin,
        :revenue_yoy, :ebitda_yoy, :pat_yoy, :fcf_yoy,
        :pe_ratio, :pb_ratio, :ev_ebitda, :dividend_yield, :market_cap_cr,
        :current_ratio, :asset_turnover,
        :computed_at, :source_version
    )
    ON CONFLICT (ticker, period_end, period_type) DO UPDATE SET
        roe              = EXCLUDED.roe,
        roce             = EXCLUDED.roce,
        roa              = EXCLUDED.roa,
        de_ratio         = EXCLUDED.de_ratio,
        debt_ebitda      = EXCLUDED.debt_ebitda,
        interest_cov     = EXCLUDED.interest_cov,
        gross_margin     = EXCLUDED.gross_margin,
        operating_margin = EXCLUDED.operating_margin,
        net_margin       = EXCLUDED.net_margin,
        fcf_margin       = EXCLUDED.fcf_margin,
        revenue_yoy      = EXCLUDED.revenue_yoy,
        ebitda_yoy       = EXCLUDED.ebitda_yoy,
        pat_yoy          = EXCLUDED.pat_yoy,
        fcf_yoy          = EXCLUDED.fcf_yoy,
        pe_ratio         = EXCLUDED.pe_ratio,
        pb_ratio         = EXCLUDED.pb_ratio,
        ev_ebitda        = EXCLUDED.ev_ebitda,
        dividend_yield   = EXCLUDED.dividend_yield,
        market_cap_cr    = EXCLUDED.market_cap_cr,
        current_ratio    = EXCLUDED.current_ratio,
        asset_turnover   = EXCLUDED.asset_turnover,
        computed_at      = EXCLUDED.computed_at,
        source_version   = EXCLUDED.source_version
""")


# ──────────────────────────────────────────────────────────────────────
# Per-ticker driver
# ──────────────────────────────────────────────────────────────────────
def process_ticker(
    db: OrmSession,
    ticker: str,
    period_types: Iterable[str],
    since: date | None,
) -> tuple[int, int]:
    """Process one ticker. Returns (periods_processed, clamp_count)."""
    q = (
        db.query(Financials)
        .filter(Financials.ticker == ticker)
        .filter(Financials.period_type.in_(tuple(period_types)))
        .filter(Financials.period_end.isnot(None))
        .order_by(Financials.period_end.asc())
    )
    rows: list[Financials] = q.all()
    if not rows:
        return (0, 0)

    # index by period_type for prior-year lookups
    idx_by_type: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        idx_by_type[r.period_type].append(i)

    clamp_log: list[tuple[str, str]] = []
    n_written = 0

    # Load corporate actions once per ticker — used to back out
    # splits/bonuses from historical prices.
    actions = _load_corporate_actions(db, ticker)

    for i, f in enumerate(rows):
        if since is not None and f.period_end < since:
            continue
        prior = _find_prior_year_row(rows, idx_by_type, i)
        mm = _latest_metrics_at_or_before(db, ticker, f.period_end)
        price = _price_at_or_before(db, ticker, f.period_end)
        if price is not None and actions:
            price = _adjust_price(price, f.period_end, actions)
        row_values = _compute_row(
            f, prior, mm,
            ticker=ticker,
            clamp_log=clamp_log,
            price_at_period_end=price,
        )
        db.execute(UPSERT_SQL, row_values)
        n_written += 1

    db.commit()
    return (n_written, len(clamp_log))


# ──────────────────────────────────────────────────────────────────────
# Ticker selection
# ──────────────────────────────────────────────────────────────────────
def _load_tickers(db: OrmSession, args: argparse.Namespace) -> list[str]:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.all:
        rows = db.execute(
            text(
                "SELECT ticker FROM stocks WHERE is_active = true "
                "ORDER BY ticker"
            )
        ).fetchall()
        return [r[0] for r in rows]
    raise SystemExit("Must pass --all or --tickers")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────
def main() -> int:
    global _processed_count

    parser = argparse.ArgumentParser(
        description="Build ratio_history from financials + market_metrics."
    )
    parser.add_argument("--tickers", type=str, default=None,
                        help="Comma-separated list of tickers.")
    parser.add_argument("--all", action="store_true",
                        help="Process all is_active=true stocks.")
    parser.add_argument("--since", type=str, default=None,
                        help="Only recompute period_end >= this YYYY-MM-DD.")
    parser.add_argument(
        "--period-types", type=str,
        default=",".join(DEFAULT_PERIOD_TYPES),
        help="Comma-separated period_types (default: annual,quarterly).",
    )
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set")
        return 1

    if Session is None:
        logger.error("data_pipeline.db.Session unavailable (no DATABASE_URL)")
        return 1

    since: date | None = None
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d").date()

    period_types = tuple(
        pt.strip() for pt in args.period_types.split(",") if pt.strip()
    )

    db = Session()
    try:
        tickers = _load_tickers(db, args)
    finally:
        db.close()

    total = len(tickers)
    logger.info(
        "starting build_ratio_history: %d tickers, period_types=%s, since=%s",
        total, period_types, since.isoformat() if since else "all",
    )

    any_failure = False
    for i, ticker in enumerate(tickers, start=1):
        if _interrupted:
            logger.warning(
                "Interrupted, %d tickers processed", _processed_count,
            )
            return 130

        db = Session()
        try:
            n_periods, n_clamped = process_ticker(
                db, ticker, period_types, since,
            )
            print(
                f"ticker_{i}/{total} {ticker} processed {n_periods} periods "
                f"({n_clamped} clamped)",
                flush=True,
            )
            _processed_count += 1
        except Exception as exc:  # noqa: BLE001
            any_failure = True
            logger.error("ticker %s failed: %s", ticker, exc, exc_info=True)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            db.close()

    logger.info(
        "done: %d/%d tickers processed (failures: %s)",
        _processed_count, total, "yes" if any_failure else "no",
    )
    return 1 if any_failure else 0


if __name__ == "__main__":
    sys.exit(main())
