# backend/services/local_data_service.py
"""
Local data assembler — builds the same dict shape as ``collector.get_all()``
entirely from Aiven DB + Parquet files. Zero yfinance dependency on the
hot path for tickers with DB coverage.

Latency: ~100-200ms (DB queries + DuckDB Parquet read) vs 20-30s for
yfinance ``.info``.

Falls back to None if the ticker doesn't have sufficient local data
(no price in Parquet, no financials in DB). Caller then uses the
original collector as fallback.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

log = logging.getLogger("yieldiq.local_data")


def _safe(v: Any, default: float = 0.0) -> float:
    """Convert to float safely. None/NaN → default."""
    if v is None:
        return default
    try:
        f = float(v)
        if f != f:  # NaN check
            return default
        return f
    except (TypeError, ValueError):
        return default


def assemble_local(ticker: str, db_session) -> dict | None:
    """
    Build a collector-compatible dict from local sources.

    Returns None if insufficient data — caller should fall back to
    ``collector.get_all()``.

    Args:
        ticker: full symbol e.g. ``"ITC.NS"``
        db_session: a live SQLAlchemy session against Aiven
    """
    if db_session is None:
        return None

    clean = ticker.replace(".NS", "").replace(".BO", "")
    is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")

    # ── 1. Price from Parquet ────────────────────────────────────
    price = 0.0
    high_52w = 0.0
    low_52w = 0.0
    try:
        from data_pipeline.nse_prices.db_integration import (
            get_latest_price,
            get_52w_high_low,
        )
        price = get_latest_price(clean) or 0.0
        h, l = get_52w_high_low(clean)
        high_52w = h or 0.0
        low_52w = l or 0.0
    except Exception as exc:
        log.debug("Parquet read failed for %s: %s", clean, exc)

    if price <= 0:
        log.debug("LOCAL_DATA: no price for %s — falling back", ticker)
        return None  # Can't do analysis without price

    # ── 2. Company info from stocks table ────────────────────────
    company_name = clean
    sector_name = ""
    try:
        from sqlalchemy import text
        row = db_session.execute(text(
            "SELECT company_name, sector, industry FROM stocks "
            "WHERE ticker = :t OR ticker_ns = :tns LIMIT 1"
        ), {"t": clean, "tns": ticker}).mappings().first()
        if row:
            company_name = row.get("company_name") or clean
            sector_name = row.get("sector") or row.get("industry") or ""
    except Exception:
        pass

    # ── 3. Market metrics (PE, PB, EV, beta, div yield) ──────────
    pe = 0.0
    pb = 0.0
    ev_ebitda_mm = 0.0
    market_cap_cr = 0.0
    dividend_yield = 0.0
    beta = 0.0
    try:
        from sqlalchemy import text
        mm = db_session.execute(text(
            "SELECT market_cap_cr, pe_ratio, pb_ratio, ev_ebitda, "
            "dividend_yield, beta_1yr FROM market_metrics "
            "WHERE ticker = :t ORDER BY trade_date DESC LIMIT 1"
        ), {"t": clean}).mappings().first()
        if mm:
            market_cap_cr = _safe(mm.get("market_cap_cr"))
            pe = _safe(mm.get("pe_ratio"))
            pb = _safe(mm.get("pb_ratio"))
            ev_ebitda_mm = _safe(mm.get("ev_ebitda"))
            dividend_yield = _safe(mm.get("dividend_yield")) / 100  # stored as pct → ratio
            beta = _safe(mm.get("beta_1yr"))
    except Exception:
        pass

    # ── 4. Financials (multiple years → DataFrames) ──────────────
    revenue_list: list[float] = []
    ni_list: list[float] = []
    oi_list: list[float] = []
    fcf_list: list[float] = []
    ocf_list: list[float] = []
    capex_list: list[float] = []

    shares = 0.0
    total_debt = 0.0
    total_cash = 0.0
    total_assets = 0.0
    total_assets_prev = 0.0
    total_equity = 0.0
    roe = 0.0
    de_ratio = 0.0
    ebitda = 0.0
    latest_fcf = 0.0
    eps_diluted = 0.0
    net_margin = 0.0

    try:
        from sqlalchemy import text
        fins = db_session.execute(text(
            "SELECT revenue, pat, ebitda, eps_diluted, cfo, capex, "
            "free_cash_flow, total_assets, total_equity, total_debt, "
            "cash_and_equivalents, shares_outstanding, roe, "
            "debt_to_equity, net_margin, period_end "
            "FROM financials WHERE ticker = :t AND period_type = 'annual' "
            "ORDER BY period_end DESC LIMIT 5"
        ), {"t": clean}).mappings().all()

        if fins:
            latest = fins[0]
            shares = _safe(latest.get("shares_outstanding"))
            total_debt = _safe(latest.get("total_debt"))
            total_cash = _safe(latest.get("cash_and_equivalents"))
            total_assets = _safe(latest.get("total_assets"))
            total_equity = _safe(latest.get("total_equity"))
            roe = _safe(latest.get("roe"))
            de_ratio = _safe(latest.get("debt_to_equity"))
            ebitda = _safe(latest.get("ebitda"))
            latest_fcf = _safe(latest.get("free_cash_flow"))
            eps_diluted = _safe(latest.get("eps_diluted"))
            net_margin = _safe(latest.get("net_margin"))

            if len(fins) >= 2:
                total_assets_prev = _safe(fins[1].get("total_assets"))

            # Build DataFrames (oldest → newest for compute_metrics)
            for f in reversed(fins):
                revenue_list.append(_safe(f.get("revenue")))
                ni_list.append(_safe(f.get("pat")))
                oi_list.append(0.0)  # operating_income not in this table
                fcf_list.append(_safe(f.get("free_cash_flow")))
                ocf_list.append(_safe(f.get("cfo")))
                capex_list.append(_safe(f.get("capex")))
    except Exception as exc:
        log.debug("Financials query failed for %s: %s", clean, exc)

    if not revenue_list:
        log.debug("LOCAL_DATA: no financials for %s — falling back", ticker)
        return None  # Can't do DCF without financials

    # Aiven stores monetary values in Crores. The analysis pipeline
    # (compute_metrics, DCF engine, Piotroski) expects RAW INR.
    # 1 Crore = 1e7 INR. Multiply all monetary values.
    CR = 1e7

    income_df = pd.DataFrame({
        "revenue":          [v * CR for v in revenue_list],
        "net_income":       [v * CR for v in ni_list],
        "operating_income": [v * CR for v in oi_list],
    })
    cf_df = pd.DataFrame({
        "fcf":   [v * CR for v in fcf_list],
        "ocf":   [v * CR for v in ocf_list],
        "capex": [v * CR for v in capex_list],
    })

    # Convert balance sheet fields too
    total_debt *= CR
    total_cash *= CR
    total_assets *= CR
    total_assets_prev *= CR
    total_equity *= CR

    # Convert shares: Aiven stores in Lakhs, pipeline expects raw count
    shares_raw = shares * 1e5 if shares else 0

    # ── 5. Derived fields ────────────────────────────────────────
    # total_debt/cash are now in raw INR (after CR multiplication above)
    enterprise_value = (market_cap_cr * CR) + total_debt - total_cash \
        if market_cap_cr > 0 else 0.0
    ev_to_ebitda_calc = (enterprise_value / (ebitda * CR)) if ebitda > 0 else ev_ebitda_mm
    latest_rev_raw = income_df["revenue"].iloc[-1] if not income_df.empty else 0
    ev_to_revenue = (enterprise_value / latest_rev_raw) if latest_rev_raw > 0 else 0.0

    # ── 6. Assemble output ───────────────────────────────────────
    log.info("LOCAL_DATA: assembled %s from DB+Parquet (price=%.2f, %d fin rows)",
             ticker, price, len(revenue_list))

    return {
        # Core — all monetary values in RAW INR (not Crores)
        "ticker":           ticker,
        "price":            price,
        "shares":           shares_raw,
        "total_debt":       total_debt,
        "total_cash":       total_cash,
        "income_df":        income_df,
        "cf_df":            cf_df,
        "native_ccy":       "INR" if is_indian else "USD",
        "fin_multiplier":   1.0,
        # Market data
        "forward_eps":      0.0,
        "trailing_eps":     eps_diluted,
        "forward_pe":       0.0,
        "pe_ratio":         pe,
        "peg_ratio":        0.0,
        "roe":              roe,
        "roce_proxy":       0.0,
        "de_ratio":         de_ratio,
        "interest_cov":     0.0,
        "gross_margin":     0.0,
        "sector_name":      sector_name,
        "norm_capex_pct":   None,
        "ebitda":           ebitda * CR if ebitda else 0,  # Cr → raw for compute_metrics
        "enterprise_value": enterprise_value,
        "ev_to_ebitda":     ev_to_ebitda_calc,
        "ev_to_revenue":    ev_to_revenue,
        "yahoo_fcf_ttm":    latest_fcf * CR if latest_fcf else 0,
        "dividend_yield":   dividend_yield,
        "dividend_rate":    0.0,
        "payout_ratio":     0.0,
        "five_yr_avg_div_yield": 0.0,
        # Company
        "company_name":     company_name,
        "shortName":        company_name,
        "currentPrice":     price,
        "regularMarketPrice": price,
        "priceToBook":      pb,
        "trailingPE":       pe,
        "beta":             beta,
        "marketCap":        market_cap_cr * CR if market_cap_cr else 0,
        "fiftyTwoWeekHigh": high_52w,
        "fiftyTwoWeekLow":  low_52w,
        "sharesOutstanding": shares_raw,
        "total_equity":     total_equity,
        "total_assets":     total_assets,
        "total_assets_prev": total_assets_prev,
        "price_change_pct": 0.0,
        "day_high":         0.0,
        "day_low":          0.0,
        # Balance sheet extras for Piotroski
        "current_ratio":    0.0,
        "current_ratio_prev": 0.0,
        "lt_debt":          total_debt,  # already in raw INR after CR multiplication
        "lt_debt_prev":     0.0,
        "shares_prev_year": 0.0,
        # Finnhub placeholders (not available from local, filled by Finnhub if online)
        "finnhub_price_target": {},
        "finnhub_rec_trend":    [],
        "finnhub_earnings":     [],
        "earnings_track_record": {},
        "finnhub_next_earnings": {},
        "news":                 [],
        "finnhub_financials":   {},
        "finnhub_insider":      {},
        "finnhub_institutional": {},
        "fh_beta":              beta,
        "fh_52w_high":          high_52w,
        "fh_52w_low":           low_52w,
        "fh_roic_ttm":          0.0,
        "fh_rev_growth_3y":     0.0,
        "fh_div_yield":         dividend_yield * 100 if dividend_yield else 0.0,
        "day_change_pct":       0.0,
        # Validation placeholder
        "_fetched_at":          0,
        "_validation":          None,
        "_source":              "local_db_parquet",
    }
