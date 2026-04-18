"""Quick sanity probe for the ADR/USD detection fix.

Run:  python test_adr_fix.py

Prints the financialCurrency + currency fields yfinance returns for a
handful of tickers. Expectation after the fix:
  - INFY, WIPRO, HCLTECH  -> may show USD (ADR leak) => pipeline will skip
  - TCS, RELIANCE         -> INR (healthy)
"""
import sys

import yfinance as yf

from tickers import get_yf_symbol

PROBES = ["INFY", "WIPRO", "HCLTECH", "TCS", "RELIANCE"]


def main():
    for ticker in PROBES:
        sym = get_yf_symbol(ticker)
        try:
            info = yf.Ticker(sym).info or {}
        except Exception as e:
            print(f"{ticker:10s} ({sym:12s}) -> ERROR: {e}")
            continue
        fin_cur = info.get("financialCurrency")
        cur = info.get("currency")
        quote_type = info.get("quoteType")
        exchange = info.get("exchange")
        print(
            f"{ticker:10s} ({sym:12s}) "
            f"financialCurrency={fin_cur!s:6s} currency={cur!s:6s} "
            f"quoteType={quote_type!s:10s} exchange={exchange!s}"
        )


if __name__ == "__main__":
    sys.exit(main())
