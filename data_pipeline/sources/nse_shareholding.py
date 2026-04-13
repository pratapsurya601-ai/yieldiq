# data_pipeline/sources/nse_shareholding.py
# Downloads promoter, FII, DII shareholding from NSE official data.
from __future__ import annotations

import io
import logging
from datetime import date

import pandas as pd
import requests
from sqlalchemy.orm import Session

from data_pipeline.models import ShareholdingPattern

logger = logging.getLogger(__name__)

NSE_BULK_SHAREHOLDING_URL = (
    "https://nsearchives.nseindia.com/corporate/datafiles/"
    "shareholding-pattern/{year}_{quarter_num}.csv"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.nseindia.com",
}


def download_bulk_shareholding(year: int, quarter: int,
                               db: Session) -> int:
    """
    Download shareholding pattern for all NSE companies for a quarter.
    quarter: 1=Apr-Jun, 2=Jul-Sep, 3=Oct-Dec, 4=Jan-Mar
    """
    url = NSE_BULK_SHAREHOLDING_URL.format(
        year=year, quarter_num=quarter,
    )

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            logger.warning(f"Shareholding not available: Q{quarter} {year}")
            return 0

        df = pd.read_csv(io.StringIO(r.text))
        stored = 0

        quarter_end_map = {
            1: date(year, 6, 30),
            2: date(year, 9, 30),
            3: date(year, 12, 31),
            4: date(year + 1, 3, 31),
        }
        quarter_end = quarter_end_map[quarter]

        for _, row in df.iterrows():
            try:
                sh = ShareholdingPattern(
                    ticker=str(row.get("Symbol", "")).strip(),
                    quarter_end=quarter_end,
                    promoter_pct=_pct(row.get("Promoter and Promoter Group")),
                    fii_pct=_pct(row.get("Foreign Institutional Investors")),
                    dii_pct=_pct(row.get("Domestic Institutional Investors")),
                    public_pct=_pct(row.get("Public")),
                )
                db.merge(sh)
                stored += 1
            except Exception:
                continue

        db.commit()
        logger.info(f"Shareholding Q{quarter} {year}: {stored} records")
        return stored

    except Exception as e:
        logger.error(f"Shareholding download failed: {e}")
        return 0


def _pct(value) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).replace(",", "").replace("%", ""))
    except Exception:
        return None
