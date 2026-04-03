# test_backtest.py
# Run with: python test_backtest.py
import sqlite3, pathlib

db = str(pathlib.Path("dashboard/portfolio.db"))
conn = sqlite3.connect(db)

# Insert a fake entry saved 1 year ago
conn.execute("""
    INSERT OR REPLACE INTO portfolio
        (ticker, company_name, entry_price, iv, mos_pct, signal,
         wacc, sym, to_code, notes, saved_at, sector)
    VALUES ('MSFT', 'Microsoft Corp', 415.0, 320.0, -23.0,
            'Overvalued', 0.09, '$', 'USD', 'Test backtest entry',
            '2024-03-22', 'Technology')
""")
conn.commit()
conn.close()
print("✓ MSFT backdated entry saved to portfolio.db")
print("  Now go to the Backtesting tab and click Run Backtest")
