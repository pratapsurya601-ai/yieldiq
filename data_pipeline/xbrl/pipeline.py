import time
from datetime import datetime

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


def run(tickers=None, mode='test', skip_nse=False):
    """
    mode='test'  : 5 tickers, verbose
    mode='top50' : first 50 tickers
    mode='full'  : all 200 tickers
    """
    if tickers is None:
        if mode == 'test':
            tickers = ['RELIANCE', 'TCS', 'HDFCBANK', 'ITC', 'INFY']
        elif mode == 'top50':
            tickers = TOP_200[:50]
        else:
            tickers = TOP_200

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
