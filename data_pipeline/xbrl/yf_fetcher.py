import time

import yfinance as yf
import pandas as pd

from config import RUPEES_TO_CRORES
from tickers import get_yf_symbol


def safe_val(val):
    """Convert raw rupee value to Crores. Returns None for NaN/None."""
    try:
        if val is None or pd.isna(val):
            return None
        return round(float(val) / RUPEES_TO_CRORES, 2)
    except Exception:
        return None


def safe_ratio(val):
    """For ratios/percentages/EPS — no unit conversion."""
    try:
        if val is None or pd.isna(val):
            return None
        return round(float(val), 4)
    except Exception:
        return None


def _nonempty(df):
    return df is not None and not df.empty


def _fetch_once(symbol):
    """Single fetch attempt. Returns a dict of DataFrames (may contain empties)."""
    yf_ticker = yf.Ticker(symbol)
    return {
        'quarterly_income': yf_ticker.quarterly_income_stmt,
        'annual_income': yf_ticker.income_stmt,
        'quarterly_balance': yf_ticker.quarterly_balance_sheet,
        'annual_balance': yf_ticker.balance_sheet,
        'annual_cashflow': yf_ticker.cashflow,
    }


def fetch_yfinance_data(ticker):
    """Fetch all financial statements for a ticker.

    Retry once (after 5s) if any of the three annual statements (IS / BS / CF)
    comes back empty. Quarterly statements are NOT required for retry trigger
    because yfinance frequently omits them by design for some tickers.
    """
    symbol = get_yf_symbol(ticker)
    max_attempts = 2
    last = None

    for attempt in range(1, max_attempts + 1):
        try:
            last = _fetch_once(symbol)
        except Exception as e:
            print(f"  {ticker}: yfinance error (attempt {attempt}): {e}")
            last = None

        if last is not None:
            annual_ok = (
                _nonempty(last.get('annual_income'))
                and _nonempty(last.get('annual_balance'))
                and _nonempty(last.get('annual_cashflow'))
            )
            if annual_ok:
                break  # full annual triad present — stop retrying

        if attempt < max_attempts:
            print(f"  retrying {ticker}...")
            time.sleep(5)

    if last is None:
        print(f"  {ticker}: yfinance failed after {max_attempts} attempts")
        return None

    # Require at least one non-empty income statement (annual OR quarterly) to proceed.
    if not (_nonempty(last.get('annual_income')) or _nonempty(last.get('quarterly_income'))):
        print(f"  {ticker}: No income statement data from yfinance")
        return None

    return {
        'ticker': ticker,
        'symbol': symbol,
        **last,
    }


def _col_date(col):
    if hasattr(col, 'strftime'):
        return col.strftime('%Y-%m-%d')
    return str(col)[:10]


def extract_income_records(data, period_type='annual'):
    ticker = data['ticker']
    stmt = data.get('annual_income' if period_type == 'annual' else 'quarterly_income')
    if stmt is None or stmt.empty:
        return []

    records = []
    for col in stmt.columns:
        non_null = stmt[col].notna().sum()
        if non_null < 3:
            continue

        def g(field):
            try:
                return safe_val(stmt.loc[field, col])
            except Exception:
                return None

        def gr(field):
            try:
                return safe_ratio(stmt.loc[field, col])
            except Exception:
                return None

        record = {
            'ticker_nse': ticker,
            'period_type': period_type,
            'period_end_date': _col_date(col),
            'revenue': g('Total Revenue') or g('Operating Revenue'),
            'gross_profit': g('Gross Profit'),
            'ebitda': g('EBITDA') or g('Normalized EBITDA'),
            'ebit': g('EBIT') or g('Operating Income'),
            'depreciation': g('Depreciation') or g('Reconciled Depreciation'),
            'interest_expense': g('Interest Expense') or g('Interest Expense Non Operating'),
            'other_income': g('Other Income Expense'),
            'pretax_income': g('Pretax Income') or g('Normalized Pre Tax Income'),
            'tax_provision': g('Tax Provision'),
            'net_income': g('Net Income') or g('Net Income Common Stockholders'),
            'minority_interest': g('Minority Interests'),
            'eps_basic': gr('Basic EPS'),
            'eps_diluted': gr('Diluted EPS'),
            'total_expenses': g('Total Expenses'),
            'operating_expense': g('Operating Expense'),
            'source': 'yfinance',
            'statement_type': 'income',
        }
        if record['revenue'] or record['net_income']:
            records.append(record)
    return records


def extract_balance_records(data, period_type='annual'):
    ticker = data['ticker']
    stmt = data.get('annual_balance' if period_type == 'annual' else 'quarterly_balance')
    if stmt is None or stmt.empty:
        return []

    records = []
    for col in stmt.columns:
        non_null = stmt[col].notna().sum()
        if non_null < 3:
            continue

        def g(field):
            try:
                return safe_val(stmt.loc[field, col])
            except Exception:
                return None

        record = {
            'ticker_nse': ticker,
            'period_type': period_type,
            'period_end_date': _col_date(col),
            'total_assets': g('Total Assets'),
            'current_assets': g('Current Assets'),
            'cash': g('Cash And Cash Equivalents') or g('Cash Cash Equivalents And Short Term Investments'),
            'inventory': g('Inventory'),
            'receivables': g('Receivables') or g('Accounts Receivable'),
            'fixed_assets': g('Net PPE') or g('Net Property Plant Equipment'),
            'investments': g('Investments And Advances') or g('Long Term Equity Investment'),
            'total_liabilities': g('Total Liabilities Net Minority Interest'),
            'current_liabilities': g('Current Liabilities'),
            'total_debt': g('Total Debt') or g('Long Term Debt And Capital Lease Obligation'),
            'long_term_debt': g('Long Term Debt'),
            'short_term_debt': g('Short Term Debt'),
            'payables': g('Payables') or g('Accounts Payable'),
            'total_equity': g('Stockholders Equity') or g('Common Stock Equity'),
            'retained_earnings': g('Retained Earnings'),
            'working_capital': g('Working Capital'),
            'net_debt': g('Net Debt'),
            'source': 'yfinance',
            'statement_type': 'balance_sheet',
        }
        if record['total_assets'] or record['total_equity']:
            records.append(record)
    return records


def extract_cashflow_records(data):
    ticker = data['ticker']
    stmt = data.get('annual_cashflow')
    if stmt is None or stmt.empty:
        return []

    records = []
    for col in stmt.columns:
        non_null = stmt[col].notna().sum()
        if non_null < 2:
            continue

        def g(field):
            try:
                return safe_val(stmt.loc[field, col])
            except Exception:
                return None

        record = {
            'ticker_nse': ticker,
            'period_type': 'annual',
            'period_end_date': _col_date(col),
            'operating_cf': g('Operating Cash Flow') or g('Cash Flow From Continuing Operating Activities'),
            'investing_cf': g('Investing Cash Flow') or g('Cash Flow From Continuing Investing Activities'),
            'financing_cf': g('Financing Cash Flow') or g('Cash Flow From Continuing Financing Activities'),
            'capex': g('Capital Expenditure') or g('Purchase Of PPE'),
            'free_cash_flow': g('Free Cash Flow'),
            'dividends_paid': g('Payment Of Dividends') or g('Cash Dividends Paid'),
            'net_cash_change': g('Changes In Cash'),
            'source': 'yfinance',
            'statement_type': 'cashflow',
        }
        if record['operating_cf'] or record['free_cash_flow']:
            records.append(record)
    return records
