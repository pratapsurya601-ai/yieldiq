"""
Entry point for the NSE price pipeline.

Usage:
    # Test with 5 tickers:
    python data_pipeline/nse_prices/run.py --test

    # Specific tickers:
    python data_pipeline/nse_prices/run.py --tickers RELIANCE,TCS,INFY

    # Full Nifty 50:
    python data_pipeline/nse_prices/run.py --full

    # Convert only (CSVs already downloaded):
    python data_pipeline/nse_prices/run.py --convert-only

    # Query test (after download + convert):
    python data_pipeline/nse_prices/run.py --query-test
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure project root is on path
_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from data_pipeline.nse_prices.downloader import NIFTY50, download_all
from data_pipeline.nse_prices.converter import convert_all, PARQUET_DIR

TEST_TICKERS = ["RELIANCE", "TCS", "INFY", "ITC", "HDFCBANK"]


def _query_test() -> None:
    """Run sample DuckDB queries against existing Parquet files."""
    from data_pipeline.nse_prices.db_integration import (
        get_price_history,
        get_52w_high_low,
        get_returns,
        get_latest_price,
    )

    files = list(PARQUET_DIR.glob("*.parquet"))
    if not files:
        print("No Parquet files found. Run --test or --full first.")
        return

    print(f"\n{'='*60}")
    print(f"Query test on {len(files)} Parquet files")
    print(f"{'='*60}")

    for pf in sorted(files)[:5]:
        ticker = pf.stem
        print(f"\n--- {ticker} ---")

        # Timing: price history
        t0 = time.time()
        df = get_price_history(ticker, 365)
        elapsed = time.time() - t0
        if df is not None:
            print(f"  1Y history: {len(df)} rows in {elapsed*1000:.1f}ms")
            print(f"  Latest: {df.iloc[-1]['date'].date()} close={df.iloc[-1]['close']:.2f}")
        else:
            print(f"  1Y history: no data")

        # 52W high/low
        high, low = get_52w_high_low(ticker)
        print(f"  52W High: {high}  Low: {low}")

        # Returns
        ret = get_returns(ticker, 252)
        if ret:
            print(f"  1Y Return: {ret['return_pct']}% ({ret['start']:.2f} -> {ret['end']:.2f})")

        # Latest price
        ltp = get_latest_price(ticker)
        print(f"  Latest close: {ltp}")

    # Summary stats
    total_size = sum(f.stat().st_size for f in files)
    print(f"\n{'='*60}")
    print(f"Total Parquet storage: {total_size / 1024:.0f} KB across {len(files)} files")
    print(f"{'='*60}")


def main() -> int:
    parser = argparse.ArgumentParser(description="NSE Price Pipeline")
    parser.add_argument("--test", action="store_true",
                        help="Download + convert 5 test tickers only")
    parser.add_argument("--full", action="store_true",
                        help="Download + convert all Nifty 50")
    parser.add_argument("--tickers", type=str, default="",
                        help="Comma-separated tickers to download")
    parser.add_argument("--convert-only", action="store_true",
                        help="Skip download, just convert existing CSVs")
    parser.add_argument("--query-test", action="store_true",
                        help="Run DuckDB query tests on existing Parquet")
    args = parser.parse_args()

    if args.query_test:
        _query_test()
        return 0

    # Determine ticker list
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    elif args.test:
        tickers = TEST_TICKERS
    elif args.full:
        tickers = NIFTY50
    else:
        parser.print_help()
        return 0

    # Download
    if not args.convert_only:
        print(f"\n=== DOWNLOADING {len(tickers)} tickers from NSE ===\n")
        download_all(tickers)

    # Convert
    print(f"\n=== CONVERTING to Parquet ===\n")
    convert_all(tickers)

    # Query test
    _query_test()

    return 0


if __name__ == "__main__":
    sys.exit(main())
