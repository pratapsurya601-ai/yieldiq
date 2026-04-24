import os

import psycopg2

# Import defensively — `config` package may not export DATABASE_URL
# in all deployment environments. Fall back to the OS env var, which
# is the canonical source everywhere else in the codebase anyway
# (data_pipeline/db.py, scripts/backfill_from_cache.py, etc. all use
# os.environ["DATABASE_URL"]). This prevents the entire XBRL ingest
# pipeline from failing to import when the legacy `config` shim is
# absent.
try:
    from config import DATABASE_URL as _CFG_DATABASE_URL  # type: ignore
except ImportError:
    _CFG_DATABASE_URL = None


def _resolve_database_url() -> str | None:
    # Prefer the OS env var (set by Railway, .env files, and all other
    # scripts). Fall back to the config shim for backwards compatibility.
    return os.environ.get("DATABASE_URL") or _CFG_DATABASE_URL


def get_conn():
    url = _resolve_database_url()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Set it in .env or the environment."
        )
    return psycopg2.connect(url)


def create_tables():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS company_financials (
        id SERIAL PRIMARY KEY,
        ticker_nse VARCHAR(20) NOT NULL,
        period_type VARCHAR(10) NOT NULL,
        period_end_date DATE,
        statement_type VARCHAR(20) NOT NULL,
        -- Income Statement
        revenue NUMERIC,
        gross_profit NUMERIC,
        ebitda NUMERIC,
        ebit NUMERIC,
        depreciation NUMERIC,
        interest_expense NUMERIC,
        other_income NUMERIC,
        pretax_income NUMERIC,
        tax_provision NUMERIC,
        net_income NUMERIC,
        minority_interest NUMERIC,
        total_expenses NUMERIC,
        operating_expense NUMERIC,
        eps_basic NUMERIC,
        eps_diluted NUMERIC,
        -- Balance Sheet
        total_assets NUMERIC,
        current_assets NUMERIC,
        cash NUMERIC,
        inventory NUMERIC,
        receivables NUMERIC,
        fixed_assets NUMERIC,
        investments NUMERIC,
        total_liabilities NUMERIC,
        current_liabilities NUMERIC,
        total_debt NUMERIC,
        long_term_debt NUMERIC,
        short_term_debt NUMERIC,
        payables NUMERIC,
        total_equity NUMERIC,
        retained_earnings NUMERIC,
        working_capital NUMERIC,
        net_debt NUMERIC,
        -- Cash Flow
        operating_cf NUMERIC,
        investing_cf NUMERIC,
        financing_cf NUMERIC,
        capex NUMERIC,
        free_cash_flow NUMERIC,
        dividends_paid NUMERIC,
        net_cash_change NUMERIC,
        -- NSE supplement
        interest_earned NUMERIC,
        interest_expended NUMERIC,
        total_income NUMERIC,
        interest NUMERIC,
        is_bank BOOLEAN DEFAULT FALSE,
        is_audited BOOLEAN DEFAULT TRUE,
        -- Metadata
        source VARCHAR(20),
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(ticker_nse, period_type, period_end_date, statement_type, source)
    );
    CREATE INDEX IF NOT EXISTS idx_fin_ticker
        ON company_financials(ticker_nse);
    CREATE INDEX IF NOT EXISTS idx_fin_period
        ON company_financials(period_end_date);
    CREATE INDEX IF NOT EXISTS idx_fin_type
        ON company_financials(statement_type);
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("Tables created/verified")


# Full list of numeric/metadata columns we write. Anything not supplied by a
# given record is filled with None (NSE rows have no BS/CF; yfinance rows
# have no NSE flags, etc).
_ALL_FIELDS = [
    'revenue', 'gross_profit', 'ebitda', 'ebit', 'depreciation',
    'interest_expense', 'other_income', 'pretax_income', 'tax_provision',
    'net_income', 'minority_interest', 'total_expenses', 'operating_expense',
    'eps_basic', 'eps_diluted',
    'total_assets', 'current_assets', 'cash', 'inventory', 'receivables',
    'fixed_assets', 'investments', 'total_liabilities', 'current_liabilities',
    'total_debt', 'long_term_debt', 'short_term_debt', 'payables',
    'total_equity', 'retained_earnings', 'working_capital', 'net_debt',
    'operating_cf', 'investing_cf', 'financing_cf', 'capex',
    'free_cash_flow', 'dividends_paid', 'net_cash_change',
    'interest_earned', 'interest_expended', 'total_income', 'interest',
    'notes', 'currency',
]


def _normalize_ticker_nse(raw):
    """Defense-in-depth: force bare-form ticker (no .NS/.BO suffix).

    Companion to the one-shot migration at scripts/migrate_dual_ticker.sql
    (data-hygiene pass 2026-04-25). Service-layer readers
    (backend/services/analysis/db.py etc.) strip the suffix before
    querying, so any '.NS'/'.BO' row written here becomes a shadow row
    nobody reads. Normalizing on write makes it impossible for a future
    script — or a regressed caller — to recreate the 22k-row bug.
    """
    if raw is None:
        return None
    return str(raw).strip().upper().replace(".NS", "").replace(".BO", "")


def _prepare(rec):
    params = {
        'ticker_nse': _normalize_ticker_nse(rec.get('ticker_nse')),
        'period_type': rec.get('period_type'),
        'period_end_date': rec.get('period_end_date'),
        'statement_type': rec.get('statement_type'),
        'source': rec.get('source'),
        'is_bank': bool(rec.get('is_bank', False)),
        'is_audited': bool(rec.get('is_audited', True)),
    }
    for f in _ALL_FIELDS:
        params[f] = rec.get(f)
    params['currency'] = rec.get('currency', 'INR')
    return params


def upsert_records(records):
    """Bulk upsert records into company_financials."""
    if not records:
        return 0, 0

    conn = get_conn()
    cur = conn.cursor()
    inserted = 0
    errors = 0

    sql = """
    INSERT INTO company_financials (
        ticker_nse, period_type, period_end_date, statement_type,
        revenue, gross_profit, ebitda, ebit, depreciation,
        interest_expense, other_income, pretax_income, tax_provision,
        net_income, minority_interest, total_expenses, operating_expense,
        eps_basic, eps_diluted,
        total_assets, current_assets, cash, inventory, receivables,
        fixed_assets, investments, total_liabilities, current_liabilities,
        total_debt, long_term_debt, short_term_debt, payables,
        total_equity, retained_earnings, working_capital, net_debt,
        operating_cf, investing_cf, financing_cf, capex,
        free_cash_flow, dividends_paid, net_cash_change,
        interest_earned, interest_expended, total_income, interest,
        is_bank, is_audited, source, notes, currency
    ) VALUES (
        %(ticker_nse)s, %(period_type)s, %(period_end_date)s, %(statement_type)s,
        %(revenue)s, %(gross_profit)s, %(ebitda)s, %(ebit)s, %(depreciation)s,
        %(interest_expense)s, %(other_income)s, %(pretax_income)s, %(tax_provision)s,
        %(net_income)s, %(minority_interest)s, %(total_expenses)s, %(operating_expense)s,
        %(eps_basic)s, %(eps_diluted)s,
        %(total_assets)s, %(current_assets)s, %(cash)s, %(inventory)s, %(receivables)s,
        %(fixed_assets)s, %(investments)s, %(total_liabilities)s, %(current_liabilities)s,
        %(total_debt)s, %(long_term_debt)s, %(short_term_debt)s, %(payables)s,
        %(total_equity)s, %(retained_earnings)s, %(working_capital)s, %(net_debt)s,
        %(operating_cf)s, %(investing_cf)s, %(financing_cf)s, %(capex)s,
        %(free_cash_flow)s, %(dividends_paid)s, %(net_cash_change)s,
        %(interest_earned)s, %(interest_expended)s, %(total_income)s, %(interest)s,
        %(is_bank)s, %(is_audited)s, %(source)s, %(notes)s, %(currency)s
    )
    ON CONFLICT (ticker_nse, period_type, period_end_date, statement_type, source)
    DO UPDATE SET
        revenue = EXCLUDED.revenue,
        gross_profit = EXCLUDED.gross_profit,
        ebitda = EXCLUDED.ebitda,
        ebit = EXCLUDED.ebit,
        net_income = EXCLUDED.net_income,
        total_assets = EXCLUDED.total_assets,
        total_equity = EXCLUDED.total_equity,
        total_debt = EXCLUDED.total_debt,
        cash = EXCLUDED.cash,
        operating_cf = EXCLUDED.operating_cf,
        free_cash_flow = EXCLUDED.free_cash_flow,
        capex = EXCLUDED.capex,
        currency = EXCLUDED.currency,
        eps_diluted = EXCLUDED.eps_diluted,
        updated_at = NOW()
    """

    for rec in records:
        try:
            if not rec.get('period_end_date') or not rec.get('ticker_nse'):
                continue
            cur.execute(sql, _prepare(rec))
            inserted += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  DB error {rec.get('ticker_nse')} "
                      f"{rec.get('period_end_date')} "
                      f"{rec.get('statement_type')}/{rec.get('source')}: {e}")
            conn.rollback()

    conn.commit()
    cur.close()
    conn.close()
    return inserted, errors
