"""DB-free test of the test-mode tickers. Exercises yfinance + NSE +
the 3 record extractors, prints per-ticker/per-source summary and a
coverage map for RELIANCE across the 13 required fields. No DB writes."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yf_fetcher import (
    fetch_yfinance_data,
    extract_income_records,
    extract_balance_records,
    extract_cashflow_records,
)
from nse_fetcher import get_nse_session, fetch_nse_quarterly

TICKERS = ['RELIANCE', 'TCS', 'HDFCBANK', 'ITC', 'INFY']

REQUIRED_13 = [
    'revenue', 'gross_profit', 'ebitda', 'ebit', 'net_income',
    'eps_diluted', 'total_assets', 'total_debt', 'cash',
    'total_equity', 'operating_cf', 'capex', 'free_cash_flow',
]

all_records_by_ticker = {t: [] for t in TICKERS}

print("Warming NSE session...")
nse = get_nse_session()
print("OK\n")

for t in TICKERS:
    print("=" * 60)
    print(f"TICKER: {t}")
    print("=" * 60)
    yfd = fetch_yfinance_data(t)
    if not yfd:
        print("  yfinance: NO DATA")
    else:
        for (kind, fn) in [
            ('annual IS',     lambda d: extract_income_records(d, 'annual')),
            ('quarterly IS',  lambda d: extract_income_records(d, 'quarterly')),
            ('annual BS',     lambda d: extract_balance_records(d, 'annual')),
            ('quarterly BS',  lambda d: extract_balance_records(d, 'quarterly')),
            ('annual CF',     lambda d: extract_cashflow_records(d)),
        ]:
            recs = fn(yfd)
            print(f"  yf {kind:<14s}: {len(recs)} records")
            all_records_by_ticker[t].extend(recs)

    print("  Fetching NSE...")
    nse_recs = fetch_nse_quarterly(t, nse)
    # Fill period_end_date like the pipeline does
    from datetime import datetime
    for r in nse_recs:
        to_dt = r.get('period_to', '')
        if to_dt:
            try:
                r['period_end_date'] = datetime.strptime(to_dt, '%d-%b-%Y').strftime('%Y-%m-%d')
            except Exception:
                r['period_end_date'] = None
    nse_recs = [r for r in nse_recs if r.get('period_end_date')]
    print(f"  nse quarterly  : {len(nse_recs)} records")
    all_records_by_ticker[t].extend(nse_recs)

    time.sleep(1)

print("\n\n" + "=" * 60)
print("RELIANCE — sample annual yfinance rows (Crores)")
print("=" * 60)
rel = all_records_by_ticker['RELIANCE']
sample_fields = ['period_end_date', 'statement_type', 'source',
                 'revenue', 'net_income', 'total_assets', 'total_debt',
                 'cash', 'total_equity', 'operating_cf', 'capex',
                 'free_cash_flow', 'gross_profit', 'ebitda', 'ebit',
                 'eps_diluted']
annual = [r for r in rel if r.get('period_type') == 'annual' and r.get('source') == 'yfinance']
annual.sort(key=lambda r: r['period_end_date'], reverse=True)
for r in annual[:12]:
    pieces = []
    for f in sample_fields:
        v = r.get(f)
        pieces.append(f"{f}={v}")
    print("  " + " | ".join(pieces[:5]))
    print("      " + " | ".join(pieces[5:10]))
    print("      " + " | ".join(pieces[10:]))

print("\n" + "=" * 60)
print("RELIANCE — 13-field coverage (non-NULL counts across all sources)")
print("=" * 60)
for f in REQUIRED_13:
    hits = sum(1 for r in rel if r.get(f) is not None)
    print(f"  [{'OK ' if hits else 'MISS'}] {f:<16s}: {hits} records")

print("\n" + "=" * 60)
print("Per-ticker total record counts")
print("=" * 60)
for t, recs in all_records_by_ticker.items():
    by_src = {}
    for r in recs:
        k = (r.get('source'), r.get('statement_type'), r.get('period_type'))
        by_src[k] = by_src.get(k, 0) + 1
    print(f"\n  {t}: {len(recs)} total records")
    for (src, stype, ptype), n in sorted(by_src.items()):
        print(f"    {src:<8s} {stype:<14s} {ptype:<10s}: {n}")
