# yieldiq/seo/generator.py
# ═══════════════════════════════════════════════════════════════════
# SEO Static Page Generator
# ═══════════════════════════════════════════════════════════════════
#
# Produces one JSON file per stock (+ a manifest.json index) for
# consumption by a Next.js / Astro / any static site that serves
# pages like:
#   /stocks/aapl-dcf-analysis
#   /stocks/msft-intrinsic-value-2026
#
# The pages are pure data — the front-end renders them with its own
# design.  Each JSON is self-contained and SEO-ready: it includes
# OpenGraph metadata, schema.org markup data, and the full valuation
# payload needed to hydrate the page without an API call.
#
# Usage (from yieldiq/ package root):
#   python -m seo.generator                        # top 500, 8 workers
#   python -m seo.generator --n 100                # first 100 tickers
#   python -m seo.generator --workers 16           # more parallelism
#   python -m seo.generator --output /tmp/seo_out  # custom output dir
#   python -m seo.generator --app-url https://app.yieldiq.io
#   python -m seo.generator --refresh              # ignore existing files
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import pathlib
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

from utils.logger import get_logger

log = get_logger(__name__)

# ── Default configuration ─────────────────────────────────────────────────────
_DEFAULT_APP_URL   = "https://app.yieldiq.io"
_DEFAULT_OUTPUT    = pathlib.Path(__file__).parent.parent.parent / "seo_output"
_DEFAULT_WORKERS   = 8
_DEFAULT_N         = 500
_YEAR              = datetime.now(tz=timezone.utc).year

# ── Signal helpers ────────────────────────────────────────────────────────────

_SIGNAL_RE = re.compile(r"[^\w\s\-\+%./]")   # strip emoji & special chars

def _clean_signal(signal: str) -> str:
    """'Undervalued 🟢'  →  'Undervalued'"""
    return _SIGNAL_RE.sub("", str(signal)).strip()


def _signal_color(signal: str) -> str:
    s = signal.lower()
    if any(k in s for k in ("undervalued", "discount", "strong buy")):
        return "green"
    if any(k in s for k in ("overvalued", "premium", "sell")):
        return "red"
    if any(k in s for k in ("fair", "neutral", "hold", "average", "watch")):
        return "yellow"
    return "gray"


def _signal_cta(signal_clean: str) -> str:
    """Short CTA verb for the signal badge."""
    s = signal_clean.lower()
    if "undervalued" in s or "discount" in s:
        return "Potential buy"
    if "overvalued" in s or "premium" in s:
        return "Monitor carefully"
    return "Hold / watch"


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_large(n: float | None) -> str:
    """Format large numbers: 2_750_000_000_000 → '$2.75T'"""
    if n is None or n == 0:
        return "N/A"
    abs_n = abs(n)
    if abs_n >= 1e12:
        return f"${abs_n / 1e12:.2f}T"
    if abs_n >= 1e9:
        return f"${abs_n / 1e9:.2f}B"
    if abs_n >= 1e6:
        return f"${abs_n / 1e6:.2f}M"
    return f"${abs_n:,.0f}"


def _pct(v: float | None) -> float | None:
    """Round a 0-1 ratio to a 1-decimal percentage, or None."""
    return round(v * 100, 1) if v is not None else None


def _r2(v: float | None) -> float | None:
    return round(v, 2) if v is not None else None


def _r1(v: float | None) -> float | None:
    return round(v, 1) if v is not None else None


def _safe(raw: dict, key: str, fallback=None):
    v = raw.get(key)
    if v is None or (isinstance(v, float) and (v != v)):   # NaN guard
        return fallback
    return v


# ── SEO metadata builder ──────────────────────────────────────────────────────

def _build_seo_meta(
    ticker: str,
    name: str,
    sector: str,
    signal_clean: str,
    price: float | None,
    iv: float | None,
    mos: float | None,   # already a percentage (e.g. 39.5)
    dcf_eligible: bool,
    market_cap_fmt: str,
) -> dict:
    """Produce the seo sub-object: title, description, keywords, slug, schema_org."""

    price_str = f"${price:,.2f}" if price else "N/A"
    iv_str    = f"${iv:,.2f}"   if iv    else "N/A"
    mos_str   = f"{mos:.0f}%"   if mos is not None else ""

    method    = "DCF" if dcf_eligible else "relative valuation"

    # ── Title ─────────────────────────────────────────────────
    if iv and mos is not None and abs(mos) >= 5:
        direction = "undervalued" if mos > 0 else "overvalued"
        title = (
            f"{ticker} Intrinsic Value & DCF Analysis {_YEAR} | "
            f"{name} {direction} by {abs(mos):.0f}%"
        )
    else:
        title = (
            f"{ticker} Stock DCF Analysis {_YEAR} | "
            f"{name} Fair Value & Intrinsic Value"
        )

    # ── Meta description ───────────────────────────────────────
    if iv and mos is not None:
        direction_txt = "upside" if mos > 0 else "downside"
        desc = (
            f"{name} ({ticker}) {method} valuation: intrinsic value {iv_str}, "
            f"current price {price_str} suggests {abs(mos):.0f}% {direction_txt}. "
            f"Signal: {signal_clean}. Market cap: {market_cap_fmt}. "
            f"Free YieldIQ analysis with 10-year FCF projections."
        )
    else:
        desc = (
            f"{name} ({ticker}) stock analysis: {signal_clean} signal at {price_str}. "
            f"Free {method} valuation, key metrics, and analyst estimates on YieldIQ."
        )

    # Truncate to ~160 chars for Google snippet
    if len(desc) > 160:
        desc = desc[:157] + "…"

    # ── Keywords ───────────────────────────────────────────────
    keywords = [
        f"{ticker} DCF analysis",
        f"{ticker} intrinsic value",
        f"{ticker} intrinsic value {_YEAR}",
        f"{ticker} stock valuation",
        f"{ticker} fair value",
        f"{name} stock analysis",
        f"{name} DCF {_YEAR}",
        f"{name} intrinsic value",
        f"{ticker} buy or sell {_YEAR}",
        f"{ticker} stock forecast {_YEAR}",
        f"is {ticker} undervalued",
        f"{ticker} {sector.lower()} stock",
    ]

    # ── URL slug ───────────────────────────────────────────────
    slug = re.sub(r"[^a-z0-9]+", "-", ticker.lower()).strip("-")
    slug = f"{slug}-stock-dcf-analysis"

    # ── schema.org FinancialProduct markup (structured data) ──
    schema_org: dict = {
        "@context":    "https://schema.org",
        "@type":       "FinancialProduct",
        "name":        f"{name} ({ticker}) Stock Analysis",
        "description": desc,
        "url":         f"{_DEFAULT_APP_URL}/stocks/{slug}",
        "provider": {
            "@type": "Organization",
            "name":  "YieldIQ",
            "url":   _DEFAULT_APP_URL,
        },
    }
    if price:
        schema_org["offers"] = {
            "@type":         "Offer",
            "price":         str(round(price, 2)),
            "priceCurrency": "USD",
        }

    return {
        "title":       title,
        "description": desc,
        "keywords":    keywords,
        "slug":        slug,
        "schema_org":  schema_org,
    }


# ── Core per-ticker analysis ──────────────────────────────────────────────────

def _analyse_for_seo(
    ticker: str,
    sector: str,
    dcf_eligible: bool,
    forecaster,
) -> Optional[dict]:
    """
    Run the full valuation pipeline for one ticker and return a flat dict
    containing everything needed to build the SEO JSON page.

    Returns None if the ticker should be skipped (no data / too thin).
    """
    # Lazy imports — keeps module load time fast and avoids circular imports
    # when this module is imported outside the yieldiq package context.
    from data.collector    import StockDataCollector
    from data.processor    import compute_metrics
    from models.industry_wacc import get_industry_wacc
    from screener.dcf_engine  import DCFEngine, margin_of_safety, assign_signal
    from screener.valuation_crosscheck import (
        compute_pe_based_iv, blend_dcf_pe, get_eps,
    )
    from screener.relative_valuation  import relative_valuation_only
    from screener.valuation_model     import generate_valuation_summary as _gen_plan
    from utils.config                 import FORECAST_YEARS

    try:
        collector = StockDataCollector(ticker)
        raw = collector.get_all()
        if raw is None:
            return None

        price = float(_safe(raw, "price", 0) or 0)
        if price < 0.5:
            return None

        # ── yfinance info for sector/market cap ───────────────
        try:
            info    = collector._ticker_obj.info
            mkt_cap = float(info.get("marketCap", 0) or 0)
            yf_sector = (
                info.get("sector", "")
                or info.get("industry", "")
                or sector
                or ""
            )
        except Exception:
            info      = {}
            mkt_cap   = 0.0
            yf_sector = sector or ""

        # Skip shells / SPACs with no real market cap
        if mkt_cap > 0 and mkt_cap < 50_000_000:
            return None

        # ── Collect raw metrics for the JSON payload ──────────
        pe_ratio      = _safe(raw, "forward_pe") or _safe(raw, "pe_ratio")
        ev_ebitda     = _safe(raw, "ev_to_ebitda")
        roe           = _safe(raw, "roe")
        gross_margin  = _safe(raw, "gross_margin")
        de_ratio      = _safe(raw, "de_ratio")
        div_yield     = _safe(raw, "dividend_yield") or _safe(raw, "fh_div_yield")
        beta          = _safe(raw, "fh_beta")
        high_52w      = _safe(raw, "fh_52w_high")
        low_52w       = _safe(raw, "fh_52w_low")
        ebitda        = _safe(raw, "ebitda")
        ev            = _safe(raw, "enterprise_value")
        yahoo_fcf     = _safe(raw, "yahoo_fcf_ttm")
        forward_pe    = _safe(raw, "forward_pe")
        peg           = _safe(raw, "peg_ratio")

        # FCF yield = FCF / market cap
        fcf_yield_pct: float | None = None
        if yahoo_fcf and mkt_cap and mkt_cap > 0:
            fcf_yield_pct = round(yahoo_fcf / mkt_cap * 100, 2)

        # Analyst targets from Finnhub
        pt_data  = _safe(raw, "finnhub_price_target", {}) or {}
        pt_mean  = _safe(pt_data, "mean")
        pt_high  = _safe(pt_data, "high")
        pt_low   = _safe(pt_data, "low")
        pt_count = _safe(pt_data, "count")

        company_name = _safe(raw, "company_name", "")

        # ── Non-DCF path (Financials, Real Estate) ────────────
        if not dcf_eligible:
            rv = relative_valuation_only(
                ticker=ticker,
                sector_key=yf_sector,
                raw=raw,
                gics_sector=yf_sector,
            )
            if not rv:
                return None

            sig_raw   = rv.get("signal", "N/A")
            sig_clean = _clean_signal(sig_raw)
            avg_pct   = rv.get("signal_avg_pct", 0.0)

            # Build per-metric table for the page
            rv_metrics = []
            for m in rv.get("metrics", []):
                if not m.get("available"):
                    continue
                rv_metrics.append({
                    "key":           m.get("key"),
                    "label":         m.get("label"),
                    "value":         _r2(m.get("value")),
                    "sector_median": _r2(m.get("sector_median")),
                    "vs_sector_pct": _r1(m.get("vs_sector_pct")),
                    "vs_label":      m.get("vs_label"),
                })

            return {
                "_ok":          True,
                "company_name": company_name,
                "yf_sector":    yf_sector,
                "price":        round(price, 2),
                "mkt_cap":      mkt_cap,
                # valuation
                "method":           "Relative Valuation",
                "dcf_eligible":     False,
                "dcf_reliable":     False,
                "signal":           sig_raw,
                "signal_clean":     sig_clean,
                "signal_color":     _signal_color(sig_raw),
                "intrinsic_value":  None,
                "dcf_iv":           None,
                "pe_iv":            None,
                "margin_of_safety": None,
                "wacc_used":        None,
                "revenue_growth":   None,
                "fcf_growth":       None,
                "op_margin":        None,
                "fundamental_grade": "N/A",
                "buy_price":        None,
                "target_price":     None,
                "stop_loss":        None,
                "holding_period":   "N/A",
                "rel_val_avg_pct":  round(avg_pct, 1),
                "rel_val_metrics":  rv_metrics,
                # raw metrics
                "pe_ratio":     _r2(pe_ratio),
                "forward_pe":   _r2(forward_pe),
                "ev_ebitda":    _r2(ev_ebitda),
                "fcf_yield_pct": fcf_yield_pct,
                "roe":          _pct(roe),
                "gross_margin": _pct(gross_margin),
                "de_ratio":     _r2(de_ratio),
                "div_yield_pct": _pct(div_yield),
                "beta":         _r2(beta),
                "high_52w":     _r2(high_52w),
                "low_52w":      _r2(low_52w),
                "peg":          _r2(peg),
                # analyst
                "pt_mean":  _r2(pt_mean),
                "pt_high":  _r2(pt_high),
                "pt_low":   _r2(pt_low),
                "pt_count": pt_count,
            }

        # ── DCF path ──────────────────────────────────────────
        enriched = compute_metrics(raw)
        if not enriched:
            return None

        op_margin_v  = enriched.get("op_margin", 0) or 0
        latest_fcf_v = enriched.get("latest_fcf", 0) or 0
        dcf_reliable = enriched.get("dcf_reliable", True)
        if op_margin_v < 0.08 and latest_fcf_v <= 0:
            dcf_reliable = False

        # Industry WACC
        try:
            from models.forecaster import compute_wacc as _cwacc
            wacc_data = _cwacc(collector._ticker_obj, False)
            capm_wacc = wacc_data.get("capm_wacc") or wacc_data.get("wacc")
        except Exception:
            capm_wacc = None

        industry_info = get_industry_wacc(
            ticker=ticker, yf_sector=yf_sector, capm_wacc=capm_wacc,
        )
        final_wacc  = industry_info["wacc"]
        industry_tg = industry_info["terminal_growth"]

        dcf_inst = DCFEngine(discount_rate=final_wacc, terminal_growth=industry_tg)

        # Forecast
        forecast_result = forecaster.predict(enriched, years=FORECAST_YEARS)
        projected       = forecast_result["projections"]
        terminal_norm   = forecast_result["terminal_fcf_norm"]
        forecast_reliable = forecast_result.get("reliable", True)
        if not forecast_reliable:
            dcf_reliable = False

        # DCF
        dcf_result = dcf_inst.intrinsic_value_per_share(
            projected_fcfs=projected,
            terminal_fcf_norm=terminal_norm,
            total_debt=enriched["total_debt"],
            total_cash=enriched["total_cash"],
            shares_outstanding=enriched["shares"],
            current_price=price,
            ticker=ticker,
        )
        dcf_iv = dcf_result.get("intrinsic_value_per_share", 0) or 0

        # PE cross-check + blend
        eps   = get_eps(enriched)
        pe_iv = compute_pe_based_iv(
            eps, industry_info["sector"],
            scenario="base",
            growth=enriched.get("revenue_growth"),
        )
        if dcf_reliable and dcf_iv > 0 and pe_iv > 0:
            blended_iv = blend_dcf_pe(dcf_iv, pe_iv, industry_info["sector"])
        elif pe_iv > 0 and not dcf_reliable:
            blended_iv = pe_iv
        else:
            blended_iv = dcf_iv

        # Hard cap: IV ≤ 3× price
        if price > 0 and blended_iv > 3.0 * price:
            blended_iv  = 3.0 * price
            dcf_reliable = False

        iv  = blended_iv
        mos = margin_of_safety(iv, price)
        if mos > 2.0:
            mos          = 2.0
            dcf_reliable = False

        sig = assign_signal(mos, dcf_result.get("suspicious", False), dcf_reliable)

        # Investment plan (price targets, fundamental score)
        plan = _gen_plan(
            enriched=enriched,
            current_price=price,
            intrinsic_value=iv,
            mos=mos,
        )
        pt_plan = plan.get("price_targets", {})
        fs_plan = plan.get("fundamental", {})
        hp_plan = plan.get("holding_period", {})

        sig_clean = _clean_signal(sig)

        rev_growth = enriched.get("revenue_growth")
        fcf_growth = enriched.get("fcf_growth")
        op_marg    = enriched.get("op_margin")

        return {
            "_ok":          True,
            "company_name": company_name,
            "yf_sector":    yf_sector,
            "price":        round(price, 2),
            "mkt_cap":      mkt_cap,
            # valuation
            "method":           "DCF + P/E Blend" if (dcf_iv > 0 and pe_iv > 0) else "DCF",
            "dcf_eligible":     True,
            "dcf_reliable":     dcf_reliable,
            "signal":           sig,
            "signal_clean":     sig_clean,
            "signal_color":     _signal_color(sig),
            "intrinsic_value":  _r2(iv),
            "dcf_iv":           _r2(dcf_iv),
            "pe_iv":            _r2(pe_iv),
            "margin_of_safety": round(mos * 100, 1),
            "wacc_used":        round(final_wacc * 100, 1),
            "revenue_growth":   _pct(rev_growth),
            "fcf_growth":       _pct(fcf_growth),
            "op_margin":        _pct(op_marg),
            "fundamental_grade": fs_plan.get("grade", "N/A"),
            "buy_price":        _r2(pt_plan.get("buy_price")),
            "target_price":     _r2(pt_plan.get("target_price")),
            "stop_loss":        _r2(pt_plan.get("stop_loss")),
            "holding_period":   hp_plan.get("label", "N/A"),
            "rel_val_avg_pct":  None,
            "rel_val_metrics":  None,
            # raw metrics
            "pe_ratio":      _r2(pe_ratio),
            "forward_pe":    _r2(forward_pe),
            "ev_ebitda":     _r2(ev_ebitda),
            "fcf_yield_pct": fcf_yield_pct,
            "roe":           _pct(roe),
            "gross_margin":  _pct(gross_margin),
            "de_ratio":      _r2(de_ratio),
            "div_yield_pct": _pct(div_yield),
            "beta":          _r2(beta),
            "high_52w":      _r2(high_52w),
            "low_52w":       _r2(low_52w),
            "peg":           _r2(peg),
            # analyst
            "pt_mean":  _r2(pt_mean),
            "pt_high":  _r2(pt_high),
            "pt_low":   _r2(pt_low),
            "pt_count": pt_count,
        }

    except Exception as exc:
        log.warning(f"[{ticker}] SEO analysis failed: {exc}")
        return None


# ── Page builder ──────────────────────────────────────────────────────────────

def build_seo_page(
    ticker: str,
    name: str,
    sector: str,
    result: dict,
    app_url: str = _DEFAULT_APP_URL,
) -> dict:
    """
    Assemble the final SEO JSON document from a completed analysis result.
    """
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    price  = result.get("price")
    iv     = result.get("intrinsic_value")
    mos    = result.get("margin_of_safety")
    sc     = result.get("signal_clean", "N/A")
    mktcap = result.get("mkt_cap") or 0
    mktcap_fmt = _fmt_large(mktcap)

    display_name = result.get("company_name") or name
    display_sector = result.get("yf_sector") or sector

    seo_meta = _build_seo_meta(
        ticker=ticker,
        name=display_name,
        sector=display_sector,
        signal_clean=sc,
        price=price,
        iv=iv,
        mos=mos,
        dcf_eligible=result.get("dcf_eligible", True),
        market_cap_fmt=mktcap_fmt,
    )

    ticker_url = f"{app_url.rstrip('/')}/?ticker={ticker}"

    # ── Valuation block ───────────────────────────────────────
    valuation: dict = {
        "signal":            result.get("signal", "N/A"),
        "signal_clean":      sc,
        "signal_color":      result.get("signal_color", "gray"),
        "signal_cta":        _signal_cta(sc),
        "method":            result.get("method", "N/A"),
        "price":             price,
        "intrinsic_value":   iv,
        "margin_of_safety":  mos,
        "dcf_eligible":      result.get("dcf_eligible"),
        "dcf_reliable":      result.get("dcf_reliable"),
        "dcf_iv":            result.get("dcf_iv"),
        "pe_iv":             result.get("pe_iv"),
        "wacc_used":         result.get("wacc_used"),
        "revenue_growth":    result.get("revenue_growth"),
        "fcf_growth":        result.get("fcf_growth"),
        "op_margin":         result.get("op_margin"),
        "fundamental_grade": result.get("fundamental_grade"),
        "buy_price":         result.get("buy_price"),
        "target_price":      result.get("target_price"),
        "stop_loss":         result.get("stop_loss"),
        "holding_period":    result.get("holding_period"),
    }

    # Relative valuation extras (non-DCF only)
    if not result.get("dcf_eligible"):
        valuation["rel_val_avg_pct"] = result.get("rel_val_avg_pct")
        valuation["rel_val_metrics"] = result.get("rel_val_metrics", [])

    # ── Metrics block ─────────────────────────────────────────
    metrics: dict = {
        "pe_ratio":      result.get("pe_ratio"),
        "forward_pe":    result.get("forward_pe"),
        "peg":           result.get("peg"),
        "ev_ebitda":     result.get("ev_ebitda"),
        "fcf_yield_pct": result.get("fcf_yield_pct"),
        "roe":           result.get("roe"),
        "gross_margin":  result.get("gross_margin"),
        "op_margin":     result.get("op_margin"),
        "de_ratio":      result.get("de_ratio"),
        "div_yield_pct": result.get("div_yield_pct"),
        "beta":          result.get("beta"),
        "52w_high":      result.get("high_52w"),
        "52w_low":       result.get("low_52w"),
        "market_cap":    mktcap if mktcap else None,
        "market_cap_fmt": mktcap_fmt,
    }

    # ── Analyst block ─────────────────────────────────────────
    analyst: dict | None = None
    if result.get("pt_mean") or result.get("pt_count"):
        analyst = {
            "price_target_mean":  result.get("pt_mean"),
            "price_target_high":  result.get("pt_high"),
            "price_target_low":   result.get("pt_low"),
            "analyst_count":      result.get("pt_count"),
        }

    # ── CTA block ─────────────────────────────────────────────
    cta: dict = {
        "headline":    f"Full {result.get('method', 'DCF')} Model for {ticker}",
        "subtext": (
            "10-year FCF projections · Sensitivity analysis · "
            "Monte Carlo simulation · Analyst targets · AI summary"
        ),
        "button_text": f"Analyze {ticker} Free →",
        "app_url":     ticker_url,
    }

    # ── Assemble ──────────────────────────────────────────────
    page: dict = {
        "ticker":       ticker,
        "name":         display_name,
        "sector":       display_sector,
        "generated_at": generated_at,
        "seo":          seo_meta,
        "valuation":    valuation,
        "metrics":      metrics,
        "cta":          cta,
    }
    if analyst:
        page["analyst"] = analyst

    return page


# ── Batch runner ──────────────────────────────────────────────────────────────

def generate_seo_pages(
    output_dir: str | pathlib.Path = _DEFAULT_OUTPUT,
    n: int = _DEFAULT_N,
    workers: int = _DEFAULT_WORKERS,
    app_url: str = _DEFAULT_APP_URL,
    csv_path: str | pathlib.Path | None = None,
    refresh: bool = False,
    discount_rate: float | None = None,
    terminal_growth: float | None = None,
) -> dict:
    """
    Generate SEO JSON pages for the top *n* US stocks.

    Parameters
    ----------
    output_dir      : root output directory. Produces:
                        <output_dir>/stocks/<TICKER>.json
                        <output_dir>/manifest.json
    n               : number of tickers to process (default 500)
    workers         : thread pool size (default 8)
    app_url         : base URL for CTA links
    csv_path        : override path to usa_tickers.csv
    refresh         : if False (default), skip tickers whose JSON already exists
    discount_rate   : override WACC for DCF (default from config.py)
    terminal_growth : override terminal growth (default from config.py)

    Returns
    -------
    Summary dict: {total, succeeded, failed, skipped, duration_s, output_dir}
    """
    from seo.top500 import get_top500
    from models.forecaster import FCFForecaster
    from utils.config import DISCOUNT_RATE, TERMINAL_GROWTH_RATE

    output_dir = pathlib.Path(output_dir)
    stocks_dir = output_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)

    tickers = get_top500(csv_path=csv_path, n=n)
    log.info(f"SEO generator: {len(tickers)} tickers · workers={workers} · output={output_dir}")

    dr = discount_rate   or DISCOUNT_RATE
    tg = terminal_growth or TERMINAL_GROWTH_RATE

    # FCFForecaster is stateless and thread-safe — one shared instance
    forecaster = FCFForecaster()

    start_ts = time.perf_counter()
    succeeded: list[dict] = []
    failed:    list[str]  = []
    skipped:   list[str]  = []

    def _process(info) -> tuple[str, str, Optional[dict]]:
        """Worker: analyse one ticker and write its JSON. Returns (ticker, status, page)."""
        ticker = info.ticker
        out_file = stocks_dir / f"{ticker}.json"

        if not refresh and out_file.exists():
            return ticker, "skipped", None

        result = _analyse_for_seo(
            ticker=ticker,
            sector=info.sector,
            dcf_eligible=info.dcf_eligible,
            forecaster=forecaster,
        )
        if result is None:
            return ticker, "failed", None

        page = build_seo_page(
            ticker=ticker,
            name=info.name,
            sector=info.sector,
            result=result,
            app_url=app_url,
        )
        out_file.write_text(json.dumps(page, ensure_ascii=False, indent=2), encoding="utf-8")
        return ticker, "ok", page

    # ── Threaded execution ────────────────────────────────────
    try:
        from tqdm import tqdm
        progress = tqdm(total=len(tickers), desc="SEO pages", unit="ticker")
        use_tqdm = True
    except ImportError:
        use_tqdm = False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_process, info): info for info in tickers}
        for fut in as_completed(futures):
            ticker_str, status, page = fut.result()
            if status == "ok" and page:
                succeeded.append({
                    "ticker": ticker_str,
                    "name":   page["name"],
                    "sector": page["sector"],
                    "signal": page["valuation"]["signal_clean"],
                    "slug":   page["seo"]["slug"],
                })
            elif status == "failed":
                failed.append(ticker_str)
            else:
                skipped.append(ticker_str)

            if use_tqdm:
                label = {"ok": "", "failed": " ✗", "skipped": " –"}.get(status, "")
                progress.set_postfix_str(f"{ticker_str}{label}", refresh=False)
                progress.update(1)
            else:
                total_done = len(succeeded) + len(failed) + len(skipped)
                if total_done % 25 == 0:
                    print(f"  … {total_done}/{len(tickers)} tickers processed", flush=True)

    if use_tqdm:
        progress.close()

    duration_s = round(time.perf_counter() - start_ts, 1)

    # ── Write manifest ────────────────────────────────────────
    # Sort manifest by ticker for deterministic diffs
    succeeded.sort(key=lambda x: x["ticker"])

    manifest = {
        "generated_at":   datetime.now(tz=timezone.utc).isoformat(),
        "app_url":        app_url,
        "total":          len(tickers),
        "succeeded":      len(succeeded),
        "failed":         len(failed),
        "skipped":        len(skipped),
        "duration_s":     duration_s,
        "stocks":         succeeded,
    }
    if failed:
        manifest["failed_tickers"] = sorted(failed)

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Summary ───────────────────────────────────────────────
    print("\n" + "═" * 56)
    print("  YieldIQ SEO Generator — Complete")
    print("═" * 56)
    print(f"  Processed  : {len(tickers):>4}")
    print(f"  Succeeded  : {len(succeeded):>4}")
    print(f"  Skipped    : {len(skipped):>4}  (already exist, --refresh to force)")
    print(f"  Failed     : {len(failed):>4}")
    print(f"  Duration   : {duration_s:>5.1f}s  ({duration_s/max(len(tickers),1):.1f}s/ticker avg)")
    print(f"  Output     : {output_dir}")
    print("═" * 56 + "\n")

    return {
        "total":      len(tickers),
        "succeeded":  len(succeeded),
        "failed":     len(failed),
        "skipped":    len(skipped),
        "duration_s": duration_s,
        "output_dir": str(output_dir),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from utils.config import DISCOUNT_RATE, TERMINAL_GROWTH_RATE

    parser = argparse.ArgumentParser(
        prog="python -m seo.generator",
        description=(
            "Generate pre-computed SEO JSON pages for the top N US stocks.\n"
            "Output: seo_output/stocks/<TICKER>.json + seo_output/manifest.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--n", type=int, default=_DEFAULT_N, metavar="COUNT",
        help=f"Number of tickers to generate pages for (default: {_DEFAULT_N}).",
    )
    parser.add_argument(
        "--workers", type=int, default=_DEFAULT_WORKERS, metavar="N",
        help=f"Thread pool size (default: {_DEFAULT_WORKERS}).",
    )
    parser.add_argument(
        "--output", default=str(_DEFAULT_OUTPUT), metavar="DIR",
        help=f"Output directory (default: {_DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--app-url", default=_DEFAULT_APP_URL, metavar="URL",
        help=f"App base URL used in CTA links (default: {_DEFAULT_APP_URL}).",
    )
    parser.add_argument(
        "--csv", default=None, metavar="PATH",
        help="Override path to usa_tickers.csv (auto-detected by default).",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-generate pages even if the JSON file already exists.",
    )
    parser.add_argument(
        "--discount-rate", type=float, default=DISCOUNT_RATE, metavar="RATE",
        help=f"DCF discount rate override, e.g. 0.10 for 10%% (default: {DISCOUNT_RATE}).",
    )
    parser.add_argument(
        "--terminal-growth", type=float, default=TERMINAL_GROWTH_RATE, metavar="RATE",
        help=(
            f"DCF terminal growth rate override, e.g. 0.025 for 2.5%% "
            f"(default: {TERMINAL_GROWTH_RATE})."
        ),
    )

    args = parser.parse_args()

    result = generate_seo_pages(
        output_dir=args.output,
        n=args.n,
        workers=args.workers,
        app_url=args.app_url,
        csv_path=args.csv,
        refresh=args.refresh,
        discount_rate=args.discount_rate,
        terminal_growth=args.terminal_growth,
    )

    sys.exit(0 if result["failed"] == 0 else 1)
