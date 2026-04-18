import os
import sys
import time
from datetime import datetime
from pathlib import Path

from config import YFINANCE_DELAY
from tickers import TOP_200
from yf_fetcher import (
    fetch_yfinance_data,
    extract_income_records,
    extract_balance_records,
    extract_cashflow_records,
)
from nse_fetcher import get_nse_session, fetch_nse_quarterly
from db_writer import create_tables, upsert_records


def _get_full_nse_universe():
    """Pull the full active NSE ticker list from the `stocks` DB table
    (populated by populate_stocks.yml). Falls back to TOP_200 if the
    DB tier isn't reachable."""
    # Repo root is two levels up from this file
    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from data_pipeline.pipeline import get_full_universe
        tickers = get_full_universe()
        if tickers:
            print(f"Loaded {len(tickers)} tickers from stocks DB table")
            return tickers
    except Exception as exc:
        print(f"[WARN] couldn't load full universe ({exc}), using TOP_200")
    return list(TOP_200)


def _get_gap_universe():
    """Tickers in `stocks` (active) but missing from `company_financials`.
    Targets the ~580 coverage gap so we don't replay the full 2,970 run
    just to fill holes. Ordered by market_cap_cr DESC so the biggest
    names land first."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        sess = Session()
        try:
            rows = sess.execute(_t(
                "SELECT s.ticker "
                "FROM stocks s "
                "LEFT JOIN company_financials cf ON cf.ticker_nse = s.ticker "
                "LEFT JOIN market_metrics mm ON mm.ticker = s.ticker "
                "WHERE s.is_active = TRUE AND cf.ticker_nse IS NULL "
                "ORDER BY COALESCE(mm.market_cap_cr, 0) DESC"
            )).fetchall()
            tickers = [r[0] for r in rows if r and r[0]]
            print(f"Gap mode: {len(tickers)} tickers missing from company_financials")
            return tickers
        finally:
            sess.close()
    except Exception as exc:
        print(f"[WARN] gap query failed ({exc}), falling back to full_nse")
        return _get_full_nse_universe()


def run(tickers=None, mode='test', skip_nse=False):
    """
    mode='test'     : 5 tickers, verbose
    mode='top50'    : first 50 tickers
    mode='full'     : TOP_200 curated list (~205 tickers)
    mode='full_nse' : every active NSE ticker in the stocks DB
                      (~2,258 after populate_stocks runs)
    mode='gap'      : only tickers missing from company_financials
                      (targeted backfill of the coverage gap)

    Honors SHARD_INDEX / SHARD_COUNT env vars for parallel runs —
    each shard processes tickers[SHARD_INDEX::SHARD_COUNT] so 4 shards
    split the universe evenly with no overlap.
    """
    if tickers is None:
        if mode == 'test':
            tickers = ['RELIANCE', 'TCS', 'HDFCBANK', 'ITC', 'INFY']
        elif mode == 'top50':
            tickers = TOP_200[:50]
        elif mode == 'full_nse':
            tickers = _get_full_nse_universe()
        elif mode == 'gap':
            tickers = _get_gap_universe()
        else:
            tickers = TOP_200

    # Sharding — allows the new full_nse mode to run 4× in parallel
    # on independent GH Actions runners for ~25 min wall-clock instead
    # of ~100 min.
    shard_idx = int(os.environ.get('SHARD_INDEX', '0'))
    shard_count = max(1, int(os.environ.get('SHARD_COUNT', '1')))
    if shard_count > 1:
        total = len(tickers)
        tickers = tickers[shard_idx::shard_count]
        print(f"Sharding: {shard_idx}/{shard_count} — {len(tickers)} of {total} tickers")

    print(f"\nYieldIQ Financial Data Pipeline")
    print(f"Mode: {mode} | Tickers: {len(tickers)}")
    print("=" * 50)

    create_tables()

    nse_session = None
    if not skip_nse:
        print("\nWarming up NSE session...")
        nse_session = get_nse_session()
        print("NSE session ready")

    total_inserted = 0
    total_errors = 0
    failed_tickers = []

    for i, ticker in enumerate(tickers):
        print(f"\n[{i+1}/{len(tickers)}] {ticker}")
        all_records = []

        # SOURCE 1: yfinance
        print(f"  Fetching yfinance...")
        yf_data = fetch_yfinance_data(ticker)
        if yf_data:
            recs = extract_income_records(yf_data, 'annual')
            print(f"  Annual IS: {len(recs)} periods")
            all_records.extend(recs)

            recs = extract_income_records(yf_data, 'quarterly')
            print(f"  Quarterly IS: {len(recs)} periods")
            all_records.extend(recs)

            recs = extract_balance_records(yf_data, 'annual')
            print(f"  Annual BS: {len(recs)} periods")
            all_records.extend(recs)

            recs = extract_balance_records(yf_data, 'quarterly')
            print(f"  Quarterly BS: {len(recs)} periods")
            all_records.extend(recs)

            recs = extract_cashflow_records(yf_data)
            print(f"  Annual CF: {len(recs)} periods")
            all_records.extend(recs)
        else:
            failed_tickers.append(ticker)
            print(f"  [FAIL] yfinance returned nothing")

        # SOURCE 2: NSE supplement
        if not skip_nse and nse_session is not None:
            print(f"  Fetching NSE quarterly...")
            nse_recs = fetch_nse_quarterly(ticker, nse_session)
            if nse_recs:
                for rec in nse_recs:
                    to_dt = rec.get('period_to', '')
                    if to_dt:
                        try:
                            dt = datetime.strptime(to_dt, '%d-%b-%Y')
                            rec['period_end_date'] = dt.strftime('%Y-%m-%d')
                        except Exception:
                            rec['period_end_date'] = None
                nse_recs = [r for r in nse_recs if r.get('period_end_date')]
                print(f"  NSE quarterly: {len(nse_recs)} periods")
                all_records.extend(nse_recs)
            else:
                print(f"  NSE: no data")

        if all_records:
            ins, err = upsert_records(all_records)
            total_inserted += ins
            total_errors += err
            print(f"  Saved {ins} records ({err} errors)")

        time.sleep(YFINANCE_DELAY)

    print(f"\n{'='*50}")
    print(f"PIPELINE COMPLETE")
    print(f"Total inserted: {total_inserted}")
    print(f"Total errors:   {total_errors}")
    print(f"Failed tickers: {failed_tickers}")
    print(f"{'='*50}")

    return {
        'inserted': total_inserted,
        'errors': total_errors,
        'failed': failed_tickers,
    }
