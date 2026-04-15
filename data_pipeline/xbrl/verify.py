import psycopg2

from config import DATABASE_URL


def verify():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    print("\n=== DATABASE VERIFICATION ===\n")

    cur.execute("SELECT COUNT(*) FROM company_financials")
    print(f"Total records: {cur.fetchone()[0]}")

    cur.execute("""
        SELECT ticker_nse,
               COUNT(*) as total,
               COUNT(CASE WHEN statement_type='income' THEN 1 END) as income,
               COUNT(CASE WHEN statement_type='balance_sheet' THEN 1 END) as bs,
               COUNT(CASE WHEN statement_type='cashflow' THEN 1 END) as cf
        FROM company_financials
        GROUP BY ticker_nse
        ORDER BY ticker_nse
    """)
    rows = cur.fetchall()
    print(f"\n{'Ticker':<15} {'Total':>6} {'IS':>6} {'BS':>6} {'CF':>6}")
    print("-" * 40)
    for row in rows:
        print(f"{row[0]:<15} {row[1]:>6} {row[2]:>6} {row[3]:>6} {row[4]:>6}")

    cur.execute("""
        SELECT period_end_date, revenue, net_income,
               total_assets, total_debt, free_cash_flow
        FROM company_financials
        WHERE ticker_nse = 'RELIANCE'
          AND period_type = 'annual'
          AND source = 'yfinance'
        ORDER BY period_end_date DESC, statement_type
        LIMIT 15
    """)
    rows = cur.fetchall()
    print(f"\nRELIANCE annual rows (all statements, Crores):")
    print(f"{'Date':<12} {'Revenue':>12} {'NetIncome':>12} "
          f"{'Assets':>14} {'Debt':>12} {'FCF':>12}")
    print("-" * 78)
    for row in rows:
        print(f"{str(row[0]):<12} "
              f"{str(row[1] if row[1] is not None else '-'):>12} "
              f"{str(row[2] if row[2] is not None else '-'):>12} "
              f"{str(row[3] if row[3] is not None else '-'):>14} "
              f"{str(row[4] if row[4] is not None else '-'):>12} "
              f"{str(row[5] if row[5] is not None else '-'):>12}")

    cur.execute("""
        SELECT
            SUM(CASE WHEN revenue IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN gross_profit IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN ebitda IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN ebit IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN net_income IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN eps_diluted IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN total_assets IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN total_debt IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN cash IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN total_equity IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN operating_cf IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN capex IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN free_cash_flow IS NOT NULL THEN 1 ELSE 0 END)
        FROM company_financials
        WHERE ticker_nse = 'RELIANCE'
    """)
    row = cur.fetchone()
    fields = ['Revenue', 'GrossProfit', 'EBITDA',
              'EBIT', 'NetIncome', 'EPS',
              'TotalAssets', 'TotalDebt', 'Cash',
              'Equity', 'OperatingCF', 'Capex', 'FCF']
    print(f"\nRELIANCE field coverage (13 required):")
    for field, count in zip(fields, row):
        status = 'OK ' if (count or 0) > 0 else 'MISS'
        print(f"  [{status}] {field}: {count or 0} records")

    cur.close()
    conn.close()


if __name__ == '__main__':
    verify()
