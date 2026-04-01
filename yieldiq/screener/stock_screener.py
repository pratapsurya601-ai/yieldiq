# screener/stock_screener.py
# ═══════════════════════════════════════════════════════════════
# STOCK SCREENER v6 — Concurrent ThreadPoolExecutor edition
# ═══════════════════════════════════════════════════════════════
# Changes from v5:
#   • ThreadPoolExecutor replaces sequential for-loop
#   • max_workers parameter (default 8, tune to taste)
#   • threading.local() gives each thread its own FCFForecaster
#     instance — eliminates shared-state races
#   • Lock-guarded results list and failure counter
#   • tqdm progress bar updated via as_completed()
#   • time.sleep(0.3) removed (was 225 s for 750 tickers alone)
#   • Throughput logged at finish: x stocks/sec
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import pandas as pd
from tqdm import tqdm

from data.collector import StockDataCollector
from data.processor import compute_metrics
from models.forecaster import FCFForecaster
from models.industry_wacc import get_industry_wacc, detect_sector
from screener.dcf_engine import DCFEngine, margin_of_safety, assign_signal
from screener.valuation_model import generate_valuation_summary as generate_investment_plan
from screener.valuation_crosscheck import compute_pe_based_iv, blend_dcf_pe, get_eps
from screener.relative_valuation import (
    load_dcf_eligibility_map,
    relative_valuation_only,
)
from utils.config import (
    FORECAST_YEARS, DISCOUNT_RATE, TERMINAL_GROWTH_RATE,
    STRONG_BUY_THRESHOLD, RESULTS_PATH,
)
from utils.logger import get_logger

log = get_logger(__name__)

# ── Filters ────────────────────────────────────────────────────
MIN_MARKET_CAP_INR = 2000e7
MIN_MARKET_CAP_USD = 200e6
MIN_PRICE_INR      = 50.0
MIN_PRICE_USD      = 1.0
MIN_REVENUE_INR    = 500e7

HOLDING_CO_KEYWORDS = [
    "hldng", "holding", "invest", "venture", "capital",
    "asset", "wealth", "trust", "fund", "portfolio",
    "bajajhldng", "tatainvest", "pilani",
]

# ── Per-thread FCFForecaster ───────────────────────────────────
# Each worker thread keeps its own FCFForecaster so concurrent
# calls to predict() (which re-fits the model per ticker) never
# share internal sklearn estimator state.
_thread_local = threading.local()


def _get_forecaster() -> FCFForecaster:
    """Return the FCFForecaster bound to the current thread, creating it if needed."""
    if not hasattr(_thread_local, "forecaster"):
        _thread_local.forecaster = FCFForecaster()
    return _thread_local.forecaster


# ══════════════════════════════════════════════════════════════
# PER-TICKER ANALYSIS (unchanged logic, safe to call concurrently)
# ══════════════════════════════════════════════════════════════

def analyse_ticker(
    ticker:      str,
    forecaster:  FCFForecaster,
    dcf:         DCFEngine,
    dcf_eligible: bool = True,
    sector_key:  str = "",
) -> Optional[dict]:
    try:
        collector = StockDataCollector(ticker)
        raw = collector.get_all()
        if raw is None:
            return None

        is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")

        # ── Filter: Holding companies ──────────────────────────
        if any(kw in ticker.lower() for kw in HOLDING_CO_KEYWORDS):
            return None

        # ── Filter: Price ──────────────────────────────────────
        price     = raw.get("price", 0)
        min_price = MIN_PRICE_INR if is_indian else MIN_PRICE_USD
        if price < min_price:
            return None

        # ── Filter: Market cap ────────────────────────────────
        try:
            info    = collector._ticker_obj.info
            mkt_cap = float(info.get("marketCap", 0) or 0)
            min_cap = MIN_MARKET_CAP_INR if is_indian else MIN_MARKET_CAP_USD
            if mkt_cap > 0 and mkt_cap < min_cap:
                return None
        except Exception:
            info = {}

        # ── Get Yahoo Finance sector ───────────────────────────
        yf_sector = ""
        try:
            yf_sector = info.get("sector", "") or info.get("industry", "") or ""
        except Exception:
            pass

        # ── Non-DCF path (banks, REITs, insurance) ────────────
        if not dcf_eligible:
            rv = relative_valuation_only(
                ticker=ticker,
                sector_key=sector_key or yf_sector,
                raw=raw,
                gics_sector=yf_sector,
            )
            if not rv:
                return None
            # Map relative-val result to the standard screener row schema.
            # Fields that don't apply to relative valuation are set to None.
            return {
                "ticker":            ticker,
                "price":             round(rv.get("price", price), 2),
                "intrinsic_value":   None,
                "dcf_iv":            None,
                "pe_iv":             None,
                "margin_of_safety":  None,
                "signal":            rv.get("signal", "N/A ⬜"),
                "sector":            rv.get("gics_sector") or rv.get("sector_key", ""),
                "wacc_used":         None,
                "revenue_growth":    None,
                "fcf_growth":        None,
                "op_margin":         None,
                "dcf_reliable":      False,
                "dcf_eligible":      False,
                "latest_fcf_bn":     None,
                "fundamental_grade": "N/A",
                "fundamental_score": 0,
                "buy_price":         None,
                "target_price":      None,
                "stop_loss":         None,
                "rr_ratio":          None,
                "target_upside_pct": None,
                "sl_pct":            None,
                "holding_period":    "N/A",
                "entry_signal":      "",
                "plan_summary":      f"Relative valuation vs sector median. Signal: {rv.get('signal','')}.",
                "rel_val_signal":    rv.get("signal", ""),
                "rel_val_avg_pct":   round(rv.get("signal_avg_pct", 0), 1),
                "rel_val_metrics":   rv.get("metrics", []),
            }

        enriched = compute_metrics(raw)
        if not enriched:
            return None

        # ── Filter: Minimum revenue ────────────────────────────
        latest_rev = enriched.get("latest_revenue", 0)
        if is_indian and latest_rev < MIN_REVENUE_INR:
            return None

        # ── Filter: Operating margin ───────────────────────────
        # Only apply the 8% floor to Indian stocks — US companies can have
        # temporarily low op_margin but still generate strong FCF (e.g. airlines,
        # turnaround stories). For US, use FCF > 0 as the primary quality gate.
        op_margin  = enriched.get("op_margin", 0)
        latest_fcf = enriched.get("latest_fcf", 0)
        if enriched.get("dcf_reliable", True) and op_margin < 0.08:
            if is_indian:
                # India: strict op_margin gate
                enriched["dcf_reliable"]      = False
                enriched["unreliable_reason"] = f"Op margin {op_margin:.1%} < 8%"
            elif latest_fcf <= 0:
                # US: only flag if BOTH op_margin AND FCF are bad
                enriched["dcf_reliable"]      = False
                enriched["unreliable_reason"] = f"Op margin {op_margin:.1%} < 8% and FCF negative"

        # ── Industry WACC ──────────────────────────────────────
        capm_wacc = None
        try:
            from models.forecaster import compute_wacc as _compute_wacc
            wacc_data  = _compute_wacc(collector._ticker_obj, is_indian)
            capm_wacc  = wacc_data.get("capm_wacc") or wacc_data.get("wacc")
        except Exception:
            pass

        industry_info = get_industry_wacc(
            ticker=ticker,
            yf_sector=yf_sector,
            capm_wacc=capm_wacc,
        )
        sector       = industry_info["sector"]
        final_wacc   = industry_info["wacc"]
        industry_tg  = industry_info["terminal_growth"]

        dcf_industry = DCFEngine(
            discount_rate=final_wacc,
            terminal_growth=industry_tg,
        )

        # ── Forecast ───────────────────────────────────────────
        forecast_result = forecaster.predict(enriched, years=FORECAST_YEARS)
        projected       = forecast_result["projections"]
        terminal_norm   = forecast_result["terminal_fcf_norm"]
        reliable        = forecast_result.get("reliable", True)

        # ── DCF Valuation ──────────────────────────────────────
        dcf_result = dcf_industry.intrinsic_value_per_share(
            projected_fcfs=projected,
            terminal_fcf_norm=terminal_norm,
            total_debt=enriched["total_debt"],
            total_cash=enriched["total_cash"],
            shares_outstanding=enriched["shares"],
            current_price=price,
            ticker=ticker,
        )

        dcf_iv = dcf_result.get("intrinsic_value_per_share", 0)

        # ── PE Cross-check ─────────────────────────────────────
        eps    = get_eps(enriched)
        pe_iv  = compute_pe_based_iv(eps, sector, scenario="base",
                                      growth=enriched.get("revenue_growth", None))

        # Blend DCF + PE based on sector
        if reliable and dcf_iv > 0 and pe_iv > 0:
            blended_iv = blend_dcf_pe(dcf_iv, pe_iv, sector)
        elif pe_iv > 0 and not reliable:
            blended_iv = pe_iv
        else:
            blended_iv = dcf_iv

        # Hard cap: blended IV cannot exceed 3× current price
        if price > 0 and blended_iv > 3.0 * price:
            log.warning(f"[{ticker}] Blended IV {blended_iv:.0f} > 3× price — capping")
            blended_iv = 3.0 * price

        iv  = blended_iv
        mos = margin_of_safety(iv, price)

        if mos > 2.0:
            mos      = 2.0
            reliable = False

        sig = assign_signal(mos, dcf_result.get("suspicious", False), reliable)

        # ── Investment Plan ────────────────────────────────────
        inv_plan = generate_investment_plan(
            enriched=enriched,
            current_price=price,
            intrinsic_value=iv,
            mos=mos,
        )
        pt = inv_plan["price_targets"]
        hp = inv_plan["holding_period"]
        fs = inv_plan["fundamental"]

        return {
            "ticker":            ticker,
            "price":             round(price, 2),
            "intrinsic_value":   round(iv, 2),
            "dcf_iv":            round(dcf_iv, 2),
            "pe_iv":             round(pe_iv, 2),
            "margin_of_safety":  round(mos * 100, 2),
            "signal":            sig,
            "sector":            industry_info["sector_name"],
            "wacc_used":         round(final_wacc * 100, 1),
            "revenue_growth":    round(enriched.get("revenue_growth", 0) * 100, 2),
            "fcf_growth":        round(enriched.get("fcf_growth",     0) * 100, 2),
            "op_margin":         round(enriched.get("op_margin",      0) * 100, 2),
            "dcf_reliable":      reliable,
            "dcf_eligible":      True,
            "latest_fcf_bn":     round(enriched.get("latest_fcf", 0) / 1e9, 3),
            "fundamental_grade": fs.get("grade", "N/A"),
            "fundamental_score": fs.get("score", 0),
            "buy_price":         pt.get("buy_price"),
            "target_price":      pt.get("target_price"),
            "stop_loss":         pt.get("stop_loss"),
            "rr_ratio":          pt.get("rr_ratio"),
            "target_upside_pct": pt.get("target_upside_pct"),
            "sl_pct":            pt.get("sl_pct"),
            "holding_period":    hp.get("label", "N/A"),
            "entry_signal":      pt.get("entry_signal", ""),
            "plan_summary":      inv_plan.get("summary", ""),
            "rel_val_signal":    None,
            "rel_val_avg_pct":   None,
            "rel_val_metrics":   None,
        }

    except Exception as exc:
        log.error(f"[{ticker}] Error: {exc}")
        return None


# ══════════════════════════════════════════════════════════════
# BATCH SCREENER — concurrent execution
# ══════════════════════════════════════════════════════════════

def run_screener(
    tickers,
    forecaster=None,           # kept for backward-compat; threads use _get_forecaster()
    discount_rate=DISCOUNT_RATE,
    terminal_growth=TERMINAL_GROWTH_RATE,
    save_csv=True,
    max_workers: int = 8,
) -> pd.DataFrame:
    """
    Screen a list of tickers concurrently.

    Parameters
    ----------
    tickers      : iterable of ticker strings
    forecaster   : ignored — each thread owns its FCFForecaster via threading.local()
    discount_rate: fallback WACC (industry override applied inside analyse_ticker)
    terminal_growth: fallback terminal growth rate
    save_csv     : write results to RESULTS_PATH when True
    max_workers  : thread-pool size.
                   8  → good default for most machines / API quotas
                   16 → faster on high-core machines; watch for 429s from Yahoo
                   32 → aggressive; pair with a VPN or proxy rotation if needed

    Returns
    -------
    pd.DataFrame sorted by signal quality (reliable BUYs first, then by MoS%)
    """
    # Shared DCFEngine is stateless after construction — safe across threads.
    # Per-ticker DCFEngine instances are created inside analyse_ticker anyway.
    dcf = DCFEngine(discount_rate=discount_rate, terminal_growth=terminal_growth)

    # Load DCF eligibility map once — {ticker: bool}.
    # Falls back gracefully if csv is missing (all tickers treated as DCF-eligible).
    eligibility_map: dict[str, bool] = {}
    try:
        eligibility_map = load_dcf_eligibility_map()
        non_dcf_count = sum(1 for v in eligibility_map.values() if not v)
        log.info(f"Eligibility map loaded — {non_dcf_count} non-DCF tickers")
    except Exception as _e:
        log.warning(f"Could not load DCF eligibility map: {_e} — all tickers treated as DCF-eligible")

    results: list[dict] = []
    failures = 0
    _lock = threading.Lock()           # guards results list and failures counter

    log.info(
        f"Starting screener — {len(tickers)} tickers, "
        f"{max_workers} workers …"
    )

    def _worker(ticker: str) -> None:
        """Single-ticker unit of work executed in a thread-pool thread."""
        nonlocal failures
        # One FCFForecaster per thread (re-used across tickers assigned to the
        # same thread, but never shared between threads).
        _fc = _get_forecaster()
        is_eligible = eligibility_map.get(ticker, True)  # default: DCF-eligible
        result = analyse_ticker(ticker, _fc, dcf, dcf_eligible=is_eligible)
        with _lock:
            if result:
                results.append(result)
                _alert(result)
            else:
                failures += 1

    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tickers up-front; futures dict lets us map back to ticker
        # names for error reporting.
        futures = {executor.submit(_worker, t): t for t in tickers}

        with tqdm(
            total=len(futures),
            desc="Screening",
            unit="stock",
            ncols=88,
            dynamic_ncols=False,
        ) as pbar:
            for fut in as_completed(futures):
                ticker = futures[fut]
                try:
                    # _worker already catches all analyse_ticker exceptions;
                    # this catches unexpected errors in the worker scaffolding.
                    fut.result()
                except Exception as exc:
                    log.error(f"[{ticker}] Unhandled thread error: {exc}")
                    with _lock:
                        failures += 1
                pbar.set_postfix(ok=len(results), fail=failures, refresh=False)
                pbar.update(1)

    elapsed = time.perf_counter() - t0
    rate    = len(results) / elapsed if elapsed > 0 else 0
    log.info(
        f"Done in {elapsed:.1f}s — {len(results)} passed, {failures} skipped/failed "
        f"({rate:.1f} stocks/sec)"
    )

    if not results:
        return pd.DataFrame()

    summary_cols = [
        "ticker", "price", "intrinsic_value", "dcf_iv", "pe_iv",
        "margin_of_safety", "signal", "sector", "wacc_used",
        "revenue_growth", "fcf_growth", "op_margin",
        "dcf_reliable", "dcf_eligible", "latest_fcf_bn",
        "fundamental_grade", "fundamental_score",
        "buy_price", "target_price", "stop_loss",
        "rr_ratio", "target_upside_pct", "sl_pct",
        "holding_period", "entry_signal", "plan_summary",
        "rel_val_signal", "rel_val_avg_pct", "rel_val_metrics",
    ]
    df = pd.DataFrame([{k: r.get(k) for k in summary_cols} for r in results])

    # Sort: DCF-eligible reliable stocks first (by MoS%), then non-DCF (by rel_val_avg_pct desc).
    # Encode into a single numeric score so a plain sort_values() works:
    #   DCF reliable Undervalued → 3000 + MoS%
    #   DCF reliable others      → 2000 + MoS%
    #   DCF unreliable           → 1000
    #   Non-DCF Discount         → 500 - rel_val_avg_pct  (more negative = better discount)
    #   Non-DCF others           → 0
    def _numeric_sort(row) -> float:
        if row.get("dcf_eligible", True):
            mos = row.get("margin_of_safety") or 0
            if row.get("dcf_reliable", False):
                base = 3000 if "Undervalued" in (row.get("signal") or "") else 2000
                return base + mos
            return 1000 + mos
        # Non-DCF
        avg_pct = row.get("rel_val_avg_pct") or 0
        if "Discount" in (row.get("signal") or ""):
            return 500 - avg_pct   # avg_pct is negative for discounts → adds to score
        return -avg_pct            # "At Sector Average" / "Premium" rank below

    df["_sort"] = [_numeric_sort(r) for r in results]
    df = df.sort_values("_sort", ascending=False).drop("_sort", axis=1).reset_index(drop=True)

    if save_csv:
        Path(RESULTS_PATH).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(RESULTS_PATH, index=False)
        log.info(f"Results saved → {RESULTS_PATH}")

    # Signal breakdown log
    dcf_df      = df[df["dcf_eligible"] == True]
    non_dcf_df  = df[df["dcf_eligible"] == False]
    reliable_df = dcf_df[dcf_df["dcf_reliable"] == True]
    log.info(
        f"DCF — Undervalued={len(reliable_df[reliable_df['signal'].str.contains('Undervalued',   na=False)])} "
        f"NearFV={len(reliable_df[reliable_df['signal'].str.contains('Near Fair Value', na=False)])} "
        f"Overvalued={len(reliable_df[reliable_df['signal'].str.contains('Overvalued',  na=False)])} "
        f"DataLimited={len(dcf_df[dcf_df['dcf_reliable'] == False])} | "
        f"RelVal — Discount={len(non_dcf_df[non_dcf_df['signal'].str.contains('Discount', na=False)])} "
        f"AtAvg={len(non_dcf_df[non_dcf_df['signal'].str.contains('At Sector', na=False)])} "
        f"Premium={len(non_dcf_df[non_dcf_df['signal'].str.contains('Premium', na=False)])}"
    )
    return df


# ══════════════════════════════════════════════════════════════
# ALERT
# ══════════════════════════════════════════════════════════════

def _alert(result: dict) -> None:
    """Print a console alert for strong-buy signals. Called inside the lock."""
    if not result.get("dcf_reliable", True):
        return
    mos_pct = result.get("margin_of_safety", 0)
    if mos_pct / 100 >= STRONG_BUY_THRESHOLD:
        print(
            f"\n{'='*58}\n"
            f"  🚨  STRONG BUY DETECTED\n"
            f"  Ticker  : {result['ticker']}\n"
            f"  Sector  : {result.get('sector','?')}\n"
            f"  Price   : {result['price']:.2f}   "
            f"IV (Blended): {result['intrinsic_value']:.2f}\n"
            f"  DCF IV  : {result.get('dcf_iv',0):.2f}   "
            f"PE IV: {result.get('pe_iv',0):.2f}\n"
            f"  MoS     : {mos_pct:.1f}%  |  WACC: {result.get('wacc_used',0):.1f}%\n"
            f"  Buy at  : {result.get('buy_price',0):.2f}   "
            f"Target: {result.get('target_price',0):.2f}\n"
            f"{'='*58}\n"
        )
