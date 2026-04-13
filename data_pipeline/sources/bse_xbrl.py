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


def store_financials(financial_data: dict, db: Session,
                     period_end: date, period_type: str = "annual") -> bool:
    """Store financial data into financials table."""
    try:
        ticker = financial_data["ticker"]

        revenue = financial_data.get("revenue")
        pat = financial_data.get("pat")
        cfo = financial_data.get("cfo")
        capex = financial_data.get("capex")
        fcf = (cfo - abs(capex)) if cfo and capex else None
        equity = financial_data.get("total_equity")

        record = Financials(
            ticker=ticker,
            period_end=period_end,
            period_type=period_type,
            revenue=revenue,
            pat=pat,
            cfo=cfo,
            capex=capex,
            free_cash_flow=fcf,
            eps_diluted=financial_data.get("eps_diluted"),
            total_debt=financial_data.get("total_debt"),
            cash_and_equivalents=financial_data.get("cash"),
            total_equity=equity,
            roe=(_safe_div(pat, equity) * 100) if pat and equity else None,
            data_source=financial_data.get("source", "BSE_API"),
            raw_data=financial_data.get("raw"),
        )

        db.merge(record)
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
