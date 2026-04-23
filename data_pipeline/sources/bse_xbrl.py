# data_pipeline/sources/bse_xbrl.py
# Downloads structured financial data from BSE official API.
# No scraping — official BSE API endpoints.
from __future__ import annotations

import json
import logging
import time
from datetime import date

import requests
from sqlalchemy.orm import Session

from data_pipeline.models import Financials

logger = logging.getLogger(__name__)


# ── Currency detection ────────────────────────────────────────────
# A small set of NSE tickers that file their consolidated XBRL in USD.
# Kept in sync with backend/services/local_data_service.USD_REPORTERS.
# The BSE XBRL payload does expose a currency/unit tag, but it is not
# reliably populated, so we fall back to this explicit allow-list.
USD_REPORTER_TICKERS: set[str] = {
    "INFY", "WIPRO", "HCLTECH", "TECHM", "MPHASIS",
    "HEXAWARE", "LTIM", "LTIMINDTR", "PERSISTENT",
    "COFORGE", "KPITTECH", "TATAELXSI", "CYIENT",
    "ZENSAR", "MASTEK", "NIIT", "OFSS",
    "DIVISLAB", "LAURUSLABS",
}


def _detect_currency(ticker: str, financial_data: dict | None = None) -> str:
    """
    Pick the reporting currency for a BSE XBRL filing.

    1. If the filing payload carries a `currency` / `unit_currency` tag,
       respect it (upper-cased, first 3 chars).
    2. Otherwise fall back to the explicit USD-reporter allow-list.
    3. Otherwise default to INR.
    """
    if financial_data:
        raw = (
            financial_data.get("currency")
            or financial_data.get("unit_currency")
            or financial_data.get("reporting_currency")
        )
        if raw:
            code = str(raw).strip().upper()[:3]
            if code in {"INR", "USD", "EUR", "GBP"}:
                return code
    clean = (ticker or "").replace(".NS", "").replace(".BO", "").upper()
    return "USD" if clean in USD_REPORTER_TICKERS else "INR"

BSE_FINANCIAL_DATA_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/Stockquote/w?scripcode={scrip_code}"
)

BSE_CORP_RESULT_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/CorporateAnnouncement/w"
    "?pageno=1&category=Result&scrip_cd={scrip_code}"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
}


def get_bse_scrip_code(isin: str) -> str | None:
    """Get BSE scrip code from ISIN using BSE API."""
    try:
        url = (
            f"https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w"
            f"?Isin={isin}&flag=0"
        )
        r = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
        code = data.get("Scripcode", "")
        return str(code) if code else None
    except Exception:
        return None


def download_financials_bse(scrip_code: str, ticker: str) -> dict | None:
    """Download financial data for a company from BSE stock quote API."""
    try:
        url = BSE_FINANCIAL_DATA_URL.format(scrip_code=scrip_code)
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None

        data = r.json()

        result = {
            "ticker": ticker,
            "source": "BSE_API",
            "revenue": _parse_cr(data.get("Sales52WH")),
            "pat": _parse_cr(data.get("PAT")),
            "eps_diluted": _parse_float(data.get("CPS")),
            "market_cap_cr": _parse_cr(data.get("MKTCAP")),
            "pe_ratio": _parse_float(data.get("PE")),
            "pb_ratio": _parse_float(data.get("PB")),
            "dividend_yield": _parse_float(data.get("DivYld")),
            "book_value": _parse_float(data.get("BVPS")),
            "raw": json.dumps(data),
        }
        return result

    except Exception as e:
        logger.warning(f"BSE financials failed for {scrip_code}/{ticker}: {e}")
        return None


def download_quarterly_results_bse(scrip_code: str) -> list[dict]:
    """Download quarterly result announcements from BSE."""
    results = []
    try:
        url = BSE_CORP_RESULT_URL.format(scrip_code=scrip_code)
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []

        data = r.json()
        announcements = data.get("Table", [])

        for ann in announcements[:8]:
            result = {
                "filing_date": ann.get("NewsDate"),
                "period": ann.get("SubCatName"),
                "headline": ann.get("HEADLINE"),
                "pdf_url": ann.get("ATTACHMENTNAME"),
            }
            results.append(result)

    except Exception as e:
        logger.warning(f"BSE quarterly results failed: {e}")

    return results


def _parse_cr(value) -> float | None:
    try:
        if value is None or value == "" or value == "-":
            return None
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def _parse_float(value) -> float | None:
    try:
        if value is None or value == "" or value == "-":
            return None
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def _safe_div(a, b):
    try:
        return a / b if b and b != 0 else None
    except Exception:
        return None


# ── BSE Peercomp Historical API endpoints (up to 10 years) ────────
BSE_PEERCOMP_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/Peercomp/w"
    "?scripcode={scrip_code}&type={stmt_type}&annuallyquarterly={freq}"
)

# (type, freq, label) tuples for the 4 historical endpoints
_HIST_ENDPOINTS = [
    ("P", "A", "pl_annual"),
    ("P", "Q", "pl_quarterly"),
    ("B", "A", "bs_annual"),
    ("C", "A", "cf_annual"),
]

# Month abbreviation → month number
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Last day of each month (non-leap, leap is handled inline)
_MONTH_LAST_DAY = {
    1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}


def parse_bse_period(period_str: str) -> date | None:
    """
    Parse BSE Peercomp period strings into a date.
    Examples:
      "FY2024"  → date(2024, 3, 31)   (Indian FY ends March 31)
      "Mar-24"  → date(2024, 3, 31)
      "Sep-23"  → date(2023, 9, 30)
      "Jun-2022"→ date(2022, 6, 30)
    """
    if not period_str or not isinstance(period_str, str):
        return None

    s = period_str.strip()

    # Pattern 1: "FY2024" or "FY 2024"
    if s.upper().startswith("FY"):
        try:
            year = int(s.upper().replace("FY", "").strip())
            if year < 100:
                year += 2000
            return date(year, 3, 31)
        except (ValueError, TypeError):
            return None

    # Pattern 2: "Mar-24", "Sep-23", "Jun-2022"
    parts = s.replace("/", "-").split("-")
    if len(parts) == 2:
        try:
            month_str = parts[0].strip().lower()[:3]
            year_str = parts[1].strip()
            month = _MONTH_MAP.get(month_str)
            if month is None:
                return None
            year = int(year_str)
            if year < 100:
                year += 2000
            # Last day of the month
            last_day = _MONTH_LAST_DAY[month]
            if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
                last_day = 29
            return date(year, month, last_day)
        except (ValueError, TypeError, KeyError):
            return None

    return None


def fetch_historical_financials(scrip_code: str, ticker: str) -> list[dict]:
    """
    Fetch up to 10 years of historical financials from BSE Peercomp API.
    Calls P&L Annual, P&L Quarterly, Balance Sheet Annual, Cash Flow Annual.
    Returns a list of dicts ready for store_financials().
    """
    raw_data: dict[str, list[dict]] = {}

    for stmt_type, freq, label in _HIST_ENDPOINTS:
        url = BSE_PEERCOMP_URL.format(
            scrip_code=scrip_code, stmt_type=stmt_type, freq=freq
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                payload = r.json()
                rows = payload.get("Table", []) if isinstance(payload, dict) else []
                raw_data[label] = rows
                logger.debug(f"BSE Peercomp {label} for {ticker}: {len(rows)} rows")
            else:
                logger.debug(f"BSE Peercomp {label} HTTP {r.status_code} for {ticker}")
                raw_data[label] = []
        except Exception as e:
            logger.warning(f"BSE Peercomp {label} failed for {ticker}: {e}")
            raw_data[label] = []
        time.sleep(0.3)

    # Index balance sheet and cash flow by period_end for merging
    bs_by_period: dict[date, dict] = {}
    for row in raw_data.get("bs_annual", []):
        period_str = row.get("Year") or row.get("Period") or row.get("year")
        pd_date = parse_bse_period(period_str)
        if pd_date:
            bs_by_period[pd_date] = row

    cf_by_period: dict[date, dict] = {}
    for row in raw_data.get("cf_annual", []):
        period_str = row.get("Year") or row.get("Period") or row.get("year")
        pd_date = parse_bse_period(period_str)
        if pd_date:
            cf_by_period[pd_date] = row

    results: list[dict] = []

    # Process P&L Annual
    for row in raw_data.get("pl_annual", []):
        period_str = row.get("Year") or row.get("Period") or row.get("year")
        period_end = parse_bse_period(period_str)
        if not period_end:
            continue

        revenue = (
            _parse_cr(row.get("NetSales"))
            or _parse_cr(row.get("TotalRevenue"))
            or _parse_cr(row.get("GrossSales"))
            or _parse_cr(row.get("Net Sales"))
            or _parse_cr(row.get("Total Revenue"))
        )
        pat = (
            _parse_cr(row.get("PAT"))
            or _parse_cr(row.get("NetProfit"))
            or _parse_cr(row.get("Net Profit"))
            or _parse_cr(row.get("ProfitAfterTax"))
        )
        ebitda = (
            _parse_cr(row.get("EBITDA"))
            or _parse_cr(row.get("OperatingProfit"))
            or _parse_cr(row.get("Operating Profit"))
        )
        eps = (
            _parse_float(row.get("EPS"))
            or _parse_float(row.get("DilutedEPS"))
            or _parse_float(row.get("Diluted EPS"))
            or _parse_float(row.get("BasicEPS"))
        )

        # Merge balance sheet data for same period
        bs = bs_by_period.get(period_end, {})
        total_debt = (
            _parse_cr(bs.get("TotalDebt"))
            or _parse_cr(bs.get("Borrowings"))
            or _parse_cr(bs.get("Total Debt"))
            or _parse_cr(bs.get("TotalBorrowings"))
        )
        total_equity = (
            _parse_cr(bs.get("ShareholdersFunds"))
            or _parse_cr(bs.get("TotalEquity"))
            or _parse_cr(bs.get("Shareholders Funds"))
            or _parse_cr(bs.get("NetWorth"))
        )
        cash = (
            _parse_cr(bs.get("CashAndBankBalances"))
            or _parse_cr(bs.get("CashEquivalents"))
            or _parse_cr(bs.get("Cash And Bank Balances"))
            or _parse_cr(bs.get("Cash"))
        )

        # Merge cash flow data for same period
        cf = cf_by_period.get(period_end, {})
        cfo = (
            _parse_cr(cf.get("CashFromOperations"))
            or _parse_cr(cf.get("OperatingActivities"))
            or _parse_cr(cf.get("Cash From Operations"))
            or _parse_cr(cf.get("CFO"))
        )
        capex = (
            _parse_cr(cf.get("CapitalExpenditure"))
            or _parse_cr(cf.get("Capex"))
            or _parse_cr(cf.get("Capital Expenditure"))
            or _parse_cr(cf.get("PurchaseOfFixedAssets"))
        )

        # TODO(xbrl-roce): BSE Peercomp's "bs_annual" rows don't expose
        # a reliable TotalAssets / CurrentLiabilities field across the
        # full universe. Leave ebit/total_assets/current_liabilities
        # unset here and let the NSE XBRL pipeline (which does parse
        # those tags) populate them — the ON CONFLICT upsert in
        # store_financials won't clobber already-populated values
        # unless EXCLUDED carries non-null data. If we later audit a
        # reliable BSE field name we can wire them in here.
        results.append({
            "ticker": ticker,
            "period_end": period_end,
            "period_type": "annual",
            "revenue": revenue,
            "pat": pat,
            "ebitda": ebitda,
            "cfo": cfo,
            "capex": capex,
            "total_debt": total_debt,
            "total_equity": total_equity,
            "cash": cash,
            "eps_diluted": eps,
            "source": "BSE_PEERCOMP",
        })

    # Process P&L Quarterly
    for row in raw_data.get("pl_quarterly", []):
        period_str = row.get("Year") or row.get("Period") or row.get("year")
        period_end = parse_bse_period(period_str)
        if not period_end:
            continue

        revenue = (
            _parse_cr(row.get("NetSales"))
            or _parse_cr(row.get("TotalRevenue"))
            or _parse_cr(row.get("GrossSales"))
            or _parse_cr(row.get("Net Sales"))
            or _parse_cr(row.get("Total Revenue"))
        )
        pat = (
            _parse_cr(row.get("PAT"))
            or _parse_cr(row.get("NetProfit"))
            or _parse_cr(row.get("Net Profit"))
            or _parse_cr(row.get("ProfitAfterTax"))
        )
        ebitda = (
            _parse_cr(row.get("EBITDA"))
            or _parse_cr(row.get("OperatingProfit"))
            or _parse_cr(row.get("Operating Profit"))
        )
        eps = (
            _parse_float(row.get("EPS"))
            or _parse_float(row.get("DilutedEPS"))
            or _parse_float(row.get("Diluted EPS"))
            or _parse_float(row.get("BasicEPS"))
        )

        results.append({
            "ticker": ticker,
            "period_end": period_end,
            "period_type": "quarterly",
            "revenue": revenue,
            "pat": pat,
            "ebitda": ebitda,
            "cfo": None,
            "capex": None,
            "total_debt": None,
            "total_equity": None,
            "cash": None,
            "eps_diluted": eps,
            "source": "BSE_PEERCOMP",
        })

    logger.info(
        f"BSE Peercomp historical for {ticker}: {len(results)} periods fetched"
    )
    return results


def store_financials(financial_data: dict, db: Session,
                     period_end: date, period_type: str = "annual") -> bool:
    """Upsert one period of financials.

    On conflict on uq_financials_period (ticker, period_end, period_type)
    we UPDATE the existing row — prior callers used db.merge() which
    keys on primary key, not the unique constraint, so re-runs collided
    with UniqueViolation and rolled back.

    Also applies a ROE sanity guard: if computed ROE is outside
    ±200% it's almost certainly a unit-scale mismatch between pat and
    equity (historically happened with mixed raw-rupees + crores from
    NSE XBRL). Better to store NULL than garbage — downstream services
    can refetch from .info/yfinance if NULL.
    """
    try:
        ticker = financial_data["ticker"]

        revenue = financial_data.get("revenue")
        pat = financial_data.get("pat")
        cfo = financial_data.get("cfo")
        capex = financial_data.get("capex")
        fcf = (cfo - abs(capex)) if cfo and capex else None
        equity = financial_data.get("total_equity")
        # New fields (optional — NSE XBRL populates these; BSE
        # Peercomp / BSE API paths currently leave them None).
        ebit = financial_data.get("ebit")
        total_assets = financial_data.get("total_assets")
        current_liabilities = financial_data.get("current_liabilities")

        # Sanity guard on ROE — cap extremes instead of writing garbage.
        roe = None
        if pat and equity:
            raw_roe = _safe_div(pat, equity) * 100
            if raw_roe is not None and -200 <= raw_roe <= 200:
                roe = raw_roe
            else:
                logger.warning(
                    "store_financials: dropping implausible roe=%.1f for "
                    "%s %s (pat=%s equity=%s — likely unit mismatch)",
                    raw_roe, ticker, period_end, pat, equity,
                )

        # Neon `financials` schema check (2026-04-24): `current_liabilities`
        # was declared on the SQLAlchemy ORM model but never applied as a
        # migration against the prod DB — every INSERT that referenced it
        # failed with `column "current_liabilities" of relation
        # "financials" does not exist`, silently swallowed, dropping the
        # entire NSE XBRL backfill. Omitted here until a proper migration
        # adds the column; the extracted value is dropped on the floor
        # (no downstream consumer uses it today).
        from sqlalchemy import text as _text
        stmt = _text("""
            INSERT INTO financials (
                ticker, period_end, period_type,
                revenue, pat, ebit, cfo, capex, free_cash_flow,
                eps_diluted, total_debt, cash_and_equivalents,
                total_equity, total_assets,
                roe, data_source, raw_data, currency
            ) VALUES (
                :ticker, :period_end, :period_type,
                :revenue, :pat, :ebit, :cfo, :capex, :fcf,
                :eps, :debt, :cash,
                :equity, :total_assets,
                :roe, :source, :raw, :currency
            )
            ON CONFLICT ON CONSTRAINT uq_financials_period
            DO UPDATE SET
                revenue = EXCLUDED.revenue,
                pat = EXCLUDED.pat,
                -- COALESCE for balance-sheet fields so a later
                -- BSE_PEERCOMP upsert (leaves these NULL) does NOT
                -- clobber values populated by NSE_XBRL ingest.
                -- Income-statement fields are recomputed per ingest.
                ebit = COALESCE(EXCLUDED.ebit, financials.ebit),
                cfo = EXCLUDED.cfo,
                capex = EXCLUDED.capex,
                free_cash_flow = EXCLUDED.free_cash_flow,
                eps_diluted = EXCLUDED.eps_diluted,
                total_debt = EXCLUDED.total_debt,
                cash_and_equivalents = EXCLUDED.cash_and_equivalents,
                total_equity = EXCLUDED.total_equity,
                total_assets = COALESCE(EXCLUDED.total_assets, financials.total_assets),
                roe = EXCLUDED.roe,
                data_source = EXCLUDED.data_source,
                raw_data = EXCLUDED.raw_data,
                currency = EXCLUDED.currency
        """)
        db.execute(stmt, {
            "ticker": ticker,
            "period_end": period_end,
            "period_type": period_type,
            "revenue": revenue,
            "pat": pat,
            "ebit": ebit,
            "cfo": cfo,
            "capex": capex,
            "fcf": fcf,
            "eps": financial_data.get("eps_diluted"),
            "debt": financial_data.get("total_debt"),
            "cash": financial_data.get("cash"),
            "equity": equity,
            "total_assets": total_assets,
            "roe": roe,
            "source": financial_data.get("source", "BSE_API"),
            "raw": financial_data.get("raw"),
            "currency": _detect_currency(ticker, financial_data),
        })
        db.commit()
        return True

    except Exception as e:
        logger.error(f"Failed to store financials for {financial_data.get('ticker')}: {e}")
        db.rollback()
        return False


def batch_update_financials(db: Session, tickers: list[str],
                            isin_map: dict[str, str]):
    """Update financial data for a batch of tickers via BSE API."""
    success = 0
    failed = 0

    for ticker in tickers:
        isin = isin_map.get(ticker)
        if not isin:
            logger.warning(f"No ISIN for {ticker} — skipping")
            failed += 1
            continue

        scrip_code = get_bse_scrip_code(isin)
        if not scrip_code:
            logger.warning(f"No BSE scrip code for {ticker}/{isin}")
            failed += 1
            continue

        data = download_financials_bse(scrip_code, ticker)
        if data:
            period_end = date(date.today().year - 1, 3, 31)
            stored = store_financials(data, db, period_end)
            if stored:
                success += 1
            else:
                failed += 1
        else:
            failed += 1

        # Rate limit — be respectful to BSE servers
        time.sleep(0.5)

    logger.info(f"Financials batch: {success} success, {failed} failed")
    return success, failed


# ── TTM (Trailing Twelve Months) calculation ──────────────────────

def calculate_ttm(ticker: str, db: Session) -> dict | None:
    """
    Calculate trailing-twelve-month financials from the last 4 quarters.
    Income statement items are summed; balance sheet items use latest quarter.
    Returns a dict compatible with store_financials(), or None if insufficient data.
    """
    from sqlalchemy import desc as sa_desc

    quarters = (
        db.query(Financials)
        .filter_by(ticker=ticker, period_type="quarterly")
        .order_by(sa_desc(Financials.period_end))
        .limit(4)
        .all()
    )

    if len(quarters) < 4:
        logger.debug(f"TTM: only {len(quarters)} quarters for {ticker}, need 4")
        return None

    latest = quarters[0]

    # Sum income-statement / flow items across 4 quarters
    def _sum_field(field_name: str) -> float | None:
        vals = [getattr(q, field_name) for q in quarters if getattr(q, field_name) is not None]
        return sum(vals) if vals else None

    revenue = _sum_field("revenue")
    pat = _sum_field("pat")
    ebitda = _sum_field("ebitda")
    cfo = _sum_field("cfo")
    capex = _sum_field("capex")
    eps = _sum_field("eps_diluted")
    fcf = (cfo - abs(capex)) if cfo is not None and capex is not None else None

    return {
        "ticker": ticker,
        "period_end": latest.period_end,
        "period_type": "ttm",
        "revenue": revenue,
        "pat": pat,
        "ebitda": ebitda,
        "cfo": cfo,
        "capex": capex,
        "total_debt": latest.total_debt,
        "total_equity": latest.total_equity,
        "cash": latest.cash_and_equivalents,
        "eps_diluted": eps,
        "free_cash_flow": fcf,
        "source": "BSE_TTM",
    }


def store_ttm(ticker: str, db: Session) -> bool:
    """
    Calculate TTM for a ticker and store/update the result in the financials table.
    Returns True on success, False otherwise.
    """
    ttm = calculate_ttm(ticker, db)
    if ttm is None:
        logger.debug(f"TTM: no result for {ticker}")
        return False

    try:
        period_end = ttm["period_end"]
        equity = ttm.get("total_equity")
        pat = ttm.get("pat")
        cfo = ttm.get("cfo")
        capex = ttm.get("capex")
        fcf = ttm.get("free_cash_flow")

        record = Financials(
            ticker=ticker,
            period_end=period_end,
            period_type="ttm",
            revenue=ttm.get("revenue"),
            pat=pat,
            ebitda=ttm.get("ebitda"),
            cfo=cfo,
            capex=capex,
            free_cash_flow=fcf,
            eps_diluted=ttm.get("eps_diluted"),
            total_debt=ttm.get("total_debt"),
            cash_and_equivalents=ttm.get("cash"),
            total_equity=equity,
            roe=(_safe_div(pat, equity) * 100) if pat and equity else None,
            data_source="BSE_TTM",
            currency=_detect_currency(ticker),
        )

        db.merge(record)
        db.commit()
        logger.info(f"TTM stored for {ticker} (period_end={period_end})")
        return True

    except Exception as e:
        logger.error(f"Failed to store TTM for {ticker}: {e}")
        db.rollback()
        return False
