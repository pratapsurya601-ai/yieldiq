#!/usr/bin/env python3
# main.py
# ─────────────────────────────────────────────────────────────
# AI DCF Stock Screener — Main Entry Point
# ─────────────────────────────────────────────────────────────
# Usage:
#   python main.py                      → analyse default tickers
#   python main.py --ticker AAPL        → single stock analysis
#   python main.py --screen             → full batch screener
#   python main.py --tickers path.csv   → load tickers from file
#   streamlit run dashboard/app.py      → launch web dashboard
# ─────────────────────────────────────────────────────────────

from __future__ import annotations

import argparse
import sys

import pandas as pd

from data.collector import StockDataCollector, load_tickers
from data.processor import compute_metrics
from models.forecaster import FCFForecaster
from screener.dcf_engine import DCFEngine, margin_of_safety, assign_signal
from screener.stock_screener import run_screener, analyse_ticker
from utils.config import (
    DISCOUNT_RATE, TERMINAL_GROWTH_RATE, FORECAST_YEARS,
    TICKER_LIST_PATH, RESULTS_PATH,
)
from utils.logger import get_logger

log = get_logger("main")

# ── Default demo tickers ───────────────────────────────────────
DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
                   "META", "NVDA", "JPM", "JNJ", "V"]


# ══════════════════════════════════════════════════════════════
# Single-stock report
# ══════════════════════════════════════════════════════════════

def run_single(ticker: str) -> None:
    sym = "₹" if ticker.endswith(".NS") or ticker.endswith(".BO") else "$"
    print(f"\n{'─'*62}")
    print(f"  AI DCF Analysis: {ticker}")
    print(f"{'─'*62}")

    forecaster = FCFForecaster()
    dcf_engine = DCFEngine()

    result = analyse_ticker(ticker, forecaster, dcf_engine)
    if result is None:
        print(f"  ❌ Could not analyse {ticker}.")
        return

    print(f"  Current Price      : {sym}{result['price']:,.2f}")
    print(f"  Intrinsic Value    : {sym}{result['intrinsic_value']:,.2f}  (Blended)")
    print(f"    ↳ DCF Value      : {sym}{result.get('dcf_iv',0):,.2f}")
    print(f"    ↳ PE Value       : {sym}{result.get('pe_iv',0):,.2f}")
    print(f"  Margin of Safety   : {result['margin_of_safety']:.1f}%")
    print(f"  Signal             : {result['signal']}")
    print(f"  Sector             : {result.get('sector','?')}")
    print(f"  WACC Used          : {result.get('wacc_used',0):.1f}%")
    print(f"  DCF Reliable       : {result.get('dcf_reliable', True)}")
    print(f"  Revenue Growth     : {result['revenue_growth']:.1f}% p.a.")
    print(f"  FCF Growth         : {result['fcf_growth']:.1f}% p.a.")
    print(f"  Operating Margin   : {result['op_margin']:.1f}%")
    print(f"  Fundamental Grade  : {result.get('fundamental_grade','N/A')} ({result.get('fundamental_score',0)}/100)")

    if result.get('dcf_reliable', True) and result.get('buy_price'):
        print(f"\n  {'─'*56}")
        print(f"  📋 INVESTMENT PLAN")
        print(f"  {'─'*56}")
        print(f"  Entry Signal       : {result.get('entry_signal','')}")
        print(f"  Buy Price          : {sym}{result.get('buy_price',0):,.2f}")
        print(f"  Target Price       : {sym}{result.get('target_price',0):,.2f}  ({'+' if result.get('target_upside_pct',0) >= 0 else ''}{result.get('target_upside_pct',0):.1f}%)")
        print(f"  Stop Loss          : {sym}{result.get('stop_loss',0):,.2f}  (-{result.get('sl_pct',0):.1f}%)")
        print(f"  Risk/Reward Ratio  : {result.get('rr_ratio',0):.1f}x")
        print(f"  Holding Period     : {result.get('holding_period','N/A')}")
        print(f"  Summary            : {result.get('plan_summary','')}")
    elif not result.get('dcf_reliable', True):
        print(f"\n  {'─'*56}")
        print(f"  ⚡ RELATIVE VALUATION NOTE (DCF not applicable)")
        print(f"  {'─'*56}")
        print(f"  {result.get('entry_signal', 'Use P/E, PEG ratio, or EV/Sales for valuation')}")
        print(f"  Summary            : {result.get('plan_summary','')}")

    print(f"{'─'*62}\n")


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="AI DCF Stock Screener",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--ticker",
        type=str,
        help="Analyse a single stock (e.g. --ticker AAPL)",
    )
    parser.add_argument(
        "--screen",
        action="store_true",
        help="Run the batch screener on the default or provided ticker list",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help=f"Path to a CSV file with tickers (default: {TICKER_LIST_PATH})",
    )
    parser.add_argument(
        "--discount-rate",
        type=float,
        default=DISCOUNT_RATE,
        help=f"WACC / discount rate (default: {DISCOUNT_RATE})",
    )
    parser.add_argument(
        "--terminal-growth",
        type=float,
        default=TERMINAL_GROWTH_RATE,
        help=f"Terminal growth rate (default: {TERMINAL_GROWTH_RATE})",
    )
    args = parser.parse_args()

    # ── Single stock ────────────────────────────────────────────
    if args.ticker:
        run_single(args.ticker.upper())
        return

    # ── Batch screener ──────────────────────────────────────────
    if args.screen:
        ticker_path = args.tickers or TICKER_LIST_PATH
        tickers = load_tickers(ticker_path)
        if not tickers:
            log.warning("No tickers loaded — using default list.")
            tickers = DEFAULT_TICKERS

        df = run_screener(
            tickers         = tickers,
            discount_rate   = args.discount_rate,
            terminal_growth = args.terminal_growth,
        )

        if not df.empty:
            print("\n" + "="*70)
            print("  TOP 20 UNDERVALUED STOCKS  (by Margin of Safety)")
            print("="*70)
            print(df.head(20).to_string(index=False))
            print(f"\nFull results saved → {RESULTS_PATH}")
        return

    # ── Default: analyse the demo tickers ──────────────────────
    print("\n🚀 AI DCF Screener — Demo Mode")
    print("Analysing default tickers:", ", ".join(DEFAULT_TICKERS))
    print("(Run with --screen for full batch screening)\n")

    forecaster = FCFForecaster()
    dcf_engine = DCFEngine()
    rows = []
    for t in DEFAULT_TICKERS:
        log.info(f"Analysing {t} …")
        res = analyse_ticker(t, forecaster, dcf_engine)
        if res:
            rows.append({k: res[k] for k in [
                "ticker", "price", "intrinsic_value",
                "margin_of_safety", "signal", "revenue_growth", "fcf_growth",
            ]})

    if rows:
        df = pd.DataFrame(rows).sort_values("margin_of_safety", ascending=False)
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
