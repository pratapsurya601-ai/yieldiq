# data_pipeline/sources/nse_bhavcopy_legacy.py
# Pre-2020-07-08 NSE bhavcopy downloader.
#
# NSE switched their daily EOD format on 2020-07-08. The new format
# (sec_bhavdata_full_DDMMYYYY.csv) is handled by nse_bhavcopy.py.
#
# The OLD format that covers 2016-01-01 → 2020-07-07 lives at:
#   https://archives.nseindia.com/content/historical/EQUITIES/
#       <YYYY>/<MMM>/cm<DD><MMM><YYYY>bhav.csv.zip
#
# Example: https://archives.nseindia.com/content/historical/EQUITIES/
#          2018/JAN/cm02JAN2018bhav.csv.zip
#
# The CSV inside the zip has columns:
#   SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY,
#   TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN
#
# We normalise to the same column names emitted by the modern downloader
# (ticker / open_price / high_price / low_price / close_price /
#  prev_close / volume / turnover_cr / vwap / trade_date) so callers can
# treat both eras uniformly.
#
# Reference packages that wrap this same archive:
#   - jugaad-data (jugaad_data.nse.bhavcopy_save)
#   - nselib (nselib.capital_market.bhav_copy_with_delivery)
# We don't depend on either — direct download keeps the dep tree small.
from __future__ import annotations

import io
import logging
import zipfile
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"

# Old archive lives on archives.nseindia.com (NOT nsearchives — different host).
LEGACY_BHAVCOPY_URL = (
    "https://archives.nseindia.com/content/historical/EQUITIES/"
    "{year}/{mon}/cm{day:02d}{mon}{year}bhav.csv.zip"
)

# 2020-07-08 is the first date the NEW (sec_bhavdata_full) format works.
# Anything strictly before that needs the legacy downloader.
LEGACY_CUTOFF: date = date(2020, 7, 8)


def _get_nse_session():
    """curl_cffi session impersonating Chrome — NSE blocks requests/urllib."""
    from curl_cffi import requests as cffi_requests
    session = cffi_requests.Session(impersonate="chrome")
    # Warm the cookie jar from the homepage.
    try:
        session.get(NSE_BASE, timeout=15)
    except Exception:
        # Archive endpoint sometimes works without the homepage cookies.
        pass
    return session


def _build_url(trade_date: date) -> str:
    mon = trade_date.strftime("%b").upper()  # JAN, FEB, ...
    return LEGACY_BHAVCOPY_URL.format(
        year=trade_date.year,
        mon=mon,
        day=trade_date.day,
    )


def download_bhavcopy_legacy(
    trade_date: date,
    session=None,
) -> pd.DataFrame | None:
    """Download + parse the pre-2020-07 NSE bhavcopy for `trade_date`.

    Returns a DataFrame with columns matching the modern downloader's
    output schema, or None if the archive returned 404 / empty / the
    request failed.

    The DataFrame is filtered to SERIES == 'EQ' (regular equity) so it
    can be inserted straight into daily_prices.
    """
    if trade_date >= LEGACY_CUTOFF:
        logger.warning(
            "%s is on/after legacy cutoff %s — use nse_bhavcopy.download_bhavcopy",
            trade_date, LEGACY_CUTOFF,
        )

    url = _build_url(trade_date)

    if session is None:
        session = _get_nse_session()

    try:
        response = session.get(url, timeout=30)
    except Exception as exc:
        logger.error("legacy bhavcopy %s download error: %s", trade_date, exc)
        return None

    if response.status_code == 404:
        logger.info("legacy bhavcopy %s: 404 (holiday/weekend)", trade_date)
        return None
    if response.status_code != 200:
        logger.warning(
            "legacy bhavcopy %s: HTTP %s", trade_date, response.status_code
        )
        return None
    if not response.content or len(response.content) < 200:
        logger.info("legacy bhavcopy %s: empty payload", trade_date)
        return None

    # ZIP → CSV
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            names = zf.namelist()
            if not names:
                return None
            # Always exactly one .csv inside the archive.
            with zf.open(names[0]) as fp:
                df = pd.read_csv(fp)
    except (zipfile.BadZipFile, Exception) as exc:
        logger.error("legacy bhavcopy %s parse failed: %s", trade_date, exc)
        return None

    return _clean_legacy(df, trade_date)


def _clean_legacy(df: pd.DataFrame, trade_date: date) -> pd.DataFrame:
    """Normalise old-format columns to the modern downloader's schema."""
    df.columns = df.columns.str.strip().str.upper()

    # Filter to equity series only.
    if "SERIES" in df.columns:
        df["SERIES"] = df["SERIES"].astype(str).str.strip()
        df = df[df["SERIES"] == "EQ"].copy()

    col_map = {
        "SYMBOL": "ticker",
        "OPEN": "open_price",
        "HIGH": "high_price",
        "LOW": "low_price",
        "CLOSE": "close_price",
        "PREVCLOSE": "prev_close",
        "TOTTRDQTY": "volume",
        "TOTTRDVAL": "turnover_raw",   # this is in rupees, convert below
        "TOTALTRADES": "trades",
        "ISIN": "isin",
    }
    df = df.rename(
        columns={k: v for k, v in col_map.items() if k in df.columns}
    )
    df["trade_date"] = trade_date

    # Old format reports turnover in plain rupees (TOTTRDVAL). Convert
    # to crore so it matches the modern downloader's `turnover_cr`.
    if "turnover_raw" in df.columns:
        df["turnover_cr"] = (
            pd.to_numeric(df["turnover_raw"], errors="coerce") / 1e7
        )
        df = df.drop(columns=["turnover_raw"])
    else:
        df["turnover_cr"] = None

    # Old format has no per-row VWAP; derive from turnover/volume so the
    # downstream code path doesn't need a special case.
    if "volume" in df.columns and "turnover_cr" in df.columns:
        with pd.option_context("mode.use_inf_as_na", True):
            vol = pd.to_numeric(df["volume"], errors="coerce")
            tov_rs = df["turnover_cr"] * 1e7
            df["vwap"] = (tov_rs / vol).where(vol > 0)
    else:
        df["vwap"] = None

    # Old format has no delivery columns. Emit them as None for schema parity.
    df["delivery_qty"] = None
    df["delivery_pct"] = None

    # Trim ticker whitespace (CSVs occasionally pad).
    if "ticker" in df.columns:
        df["ticker"] = df["ticker"].astype(str).str.strip()

    return df.reset_index(drop=True)
