"""yfinance full dump for 4 Indian tickers."""
import yfinance as yf

tickers = {
    'RELIANCE': 'RELIANCE.NS',
    'TCS': 'TCS.NS',
    'HDFCBANK': 'HDFCBANK.NS',
    'ITC': 'ITC.NS',
}

for name, symbol in tickers.items():
    print(f"\n{'='*60}")
    print(f"YFINANCE FULL DUMP: {name} ({symbol})")
    print('='*60)
    try:
        ticker = yf.Ticker(symbol)

        print("\n--- QUARTERLY INCOME STATEMENT ---")
        qi = ticker.quarterly_income_stmt
        if qi is not None and not qi.empty:
            print(f"Periods: {[str(c)[:10] for c in qi.columns]}")
            print(f"Fields ({len(qi.index)}):")
            for field in qi.index:
                vals = [str(qi[c][field])[:15] for c in qi.columns[:3]]
                print(f"  {field}: {vals}")
        else:
            print("EMPTY")

        print("\n--- ANNUAL INCOME STATEMENT ---")
        ai = ticker.income_stmt
        if ai is not None and not ai.empty:
            print(f"Periods: {[str(c)[:10] for c in ai.columns]}")
            print(f"Fields ({len(ai.index)}): {list(ai.index)[:15]}")
        else:
            print("EMPTY")

        print("\n--- QUARTERLY BALANCE SHEET ---")
        qb = ticker.quarterly_balance_sheet
        if qb is not None and not qb.empty:
            print(f"Periods: {[str(c)[:10] for c in qb.columns]}")
            print(f"Fields ({len(qb.index)}):")
            for field in qb.index:
                vals = [str(qb[c][field])[:15] for c in qb.columns[:3]]
                print(f"  {field}: {vals}")
        else:
            print("EMPTY")

        print("\n--- ANNUAL BALANCE SHEET ---")
        ab = ticker.balance_sheet
        if ab is not None and not ab.empty:
            print(f"Periods: {[str(c)[:10] for c in ab.columns]}")
            print(f"Fields ({len(ab.index)}): {list(ab.index)}")
        else:
            print("EMPTY")

        print("\n--- QUARTERLY CASH FLOW ---")
        qc = ticker.quarterly_cashflow
        if qc is not None and not qc.empty:
            print(f"Periods: {[str(c)[:10] for c in qc.columns]}")
            print(f"Fields ({len(qc.index)}):")
            for field in qc.index:
                vals = [str(qc[c][field])[:15] for c in qc.columns[:3]]
                print(f"  {field}: {vals}")
        else:
            print("EMPTY")

        print("\n--- ANNUAL CASH FLOW ---")
        ac = ticker.cashflow
        if ac is not None and not ac.empty:
            print(f"Periods: {[str(c)[:10] for c in ac.columns]}")
            print(f"Fields ({len(ac.index)}): {list(ac.index)}")
        else:
            print("EMPTY")

        print(f"\n--- SUMMARY FOR {name} ---")
        print(f"Quarterly IS periods: {len(qi.columns) if qi is not None and not qi.empty else 0}")
        print(f"Annual IS periods:    {len(ai.columns) if ai is not None and not ai.empty else 0}")
        print(f"Quarterly BS periods: {len(qb.columns) if qb is not None and not qb.empty else 0}")
        print(f"Annual BS periods:    {len(ab.columns) if ab is not None and not ab.empty else 0}")
        print(f"Quarterly CF periods: {len(qc.columns) if qc is not None and not qc.empty else 0}")
        print(f"Annual CF periods:    {len(ac.columns) if ac is not None and not ac.empty else 0}")
    except Exception as e:
        print(f"ERROR: {e}")
