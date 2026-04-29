# backend/services/data_service.py
# Wraps data/ and market data logic for FastAPI.
from __future__ import annotations
import sys, os, logging
from pathlib import Path
from datetime import datetime

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.models.responses import (
    MarketPulseResponse, MarketIndex, SectorOverviewItem,
)

try:
    import yfinance as yf
except ImportError:
    yf = None

logger = logging.getLogger(__name__)


class DataService:
    """Market data and sector overview."""

    _pulse_cache: dict = {}
    _pulse_ts: float = 0

    def get_market_pulse(self) -> MarketPulseResponse:
        """Market indices + fear/greed. Cached 5 minutes."""
        import time
        if time.time() - self._pulse_ts < 300 and self._pulse_cache:
            return self._pulse_cache

        from config.countries import get_active_country
        country = get_active_country()
        is_india = country.get("currency_code") == "INR"

        # India-first launch — always show Indian indices
        indices_config = [
            ("NIFTY 50", "^NSEI"),
            ("SENSEX", "^BSESN"),
            ("NIFTY Bank", "^NSEBANK"),
        ]

        from backend.services import market_data_service as _mds

        indices = []
        for name, symbol in indices_config:
            snap = _mds.get_index_snapshot(symbol)
            if snap and snap.get("price"):
                indices.append(MarketIndex(
                    name=name,
                    price=round(float(snap["price"]), 2),
                    change_pct=round(float(snap.get("change_pct") or 0), 2),
                ))
                continue
            # Fallback: DB row missing — hit yfinance directly.
            logger.warning("market_pulse: DB miss for %s, falling back to yfinance", symbol)
            try:
                tk = yf.Ticker(symbol)
                fi = tk.fast_info
                _price = getattr(fi, "last_price", 0) or 0
                _prev = getattr(fi, "previous_close", _price) or _price
                _chg = ((_price - _prev) / _prev * 100) if _prev > 0 else 0
                indices.append(MarketIndex(name=name, price=round(_price, 2), change_pct=round(_chg, 2)))
            except Exception:
                indices.append(MarketIndex(name=name))

        # Fear & greed from VIX
        fg_idx, fg_label = None, None
        _vix_sym = "^INDIAVIX"
        _vix_snap = _mds.get_index_snapshot(_vix_sym)
        _val = None
        if _vix_snap and _vix_snap.get("price"):
            _val = float(_vix_snap["price"])
        else:
            logger.warning("market_pulse: DB miss for VIX, falling back to yfinance")
            try:
                _vix = yf.Ticker(_vix_sym).fast_info
                _val = getattr(_vix, "last_price", 20) or 20
            except Exception:
                _val = None
        if _val is not None:
            fg_idx = int(_val)
            fg_label = "Greed" if _val < 12 else "Neutral" if _val < 18 else "Fear" if _val < 25 else "Extreme Fear"

        result = MarketPulseResponse(
            indices=indices,
            fear_greed_index=fg_idx,
            fear_greed_label=fg_label,
            timestamp=datetime.now().isoformat(),
        )
        self._pulse_cache = result
        self._pulse_ts = time.time()
        return result

    def get_sector_overview(self) -> list[SectorOverviewItem]:
        """Sector-level stats from screener data or static fallback."""
        try:
            import pandas as pd
            _path = Path(_PROJECT_ROOT) / "data" / "screener_results.csv"
            if _path.exists():
                df = pd.read_csv(_path)
                _sector_col = next((c for c in df.columns if c.lower() in ("sector", "sector_name")), None)
                _score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score")), None)
                _mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct")), None)
                if _sector_col and _score_col:
                    result = []
                    for sector, group in df.groupby(_sector_col):
                        _avg = group[_score_col].mean()
                        _pct = (group[_mos_col] > 0).mean() * 100 if _mos_col else 50
                        result.append(SectorOverviewItem(
                            name=str(sector), avg_score=round(_avg, 1),
                            pct_undervalued=round(_pct, 1),
                            trend="up" if _avg > 60 else "flat" if _avg > 45 else "down",
                        ))
                    return sorted(result, key=lambda x: x.avg_score, reverse=True)
        except Exception:
            pass

        # Static fallback
        return [
            SectorOverviewItem(name="Technology", avg_score=65, pct_undervalued=55, trend="up"),
            SectorOverviewItem(name="Financials", avg_score=62, pct_undervalued=60, trend="up"),
            SectorOverviewItem(name="Healthcare", avg_score=58, pct_undervalued=45, trend="flat"),
            SectorOverviewItem(name="Consumer Staples", avg_score=55, pct_undervalued=40, trend="flat"),
            SectorOverviewItem(name="Energy", avg_score=52, pct_undervalued=48, trend="down"),
        ]


# Money-magnitude keys: an explicit NULL in DB means "we deliberately
# don't have this; do NOT pull from yfinance" — yfinance returns ADR
# values in raw USD for cross-listed Indian tickers (INFY/HCLTECH/WIPRO
# etc.), which would leak through as USD-as-rupees and crash DCF FV.
_MONEY_KEYS = {
    "freeCashflow", "totalRevenue", "totalDebt", "totalCash",
    "operatingCashflow", "capitalExpenditures", "ebitda",
    "marketCap", "enterpriseValue", "totalAssets",
    "netIncomeToCommon",
}


def _prefer_db(key: str, db_v, yf_v):
    """For money-magnitude keys, an explicit NULL in DB means
    'do not fall back to yfinance' (avoids USD-as-rupees leaks).
    For all other keys, fall back to yfinance when DB is None."""
    if key in _MONEY_KEYS:
        return db_v  # NULL DB stays NULL; don't pull from yfinance
    return db_v if db_v is not None else yf_v


def get_stock_data(ticker: str) -> dict:
    """
    Primary data fetch function for YieldIQ.
    1. Try local database first (fast, reliable)
    2. Fall back to yfinance if DB has no data
    3. Validate data quality either way
    """
    try:
        from data_pipeline.db import Session as PipelineSession
        from data_pipeline.pipeline import get_stock_data_from_db
    except Exception:
        # Pipeline not configured (no DATABASE_URL) — skip to yfinance
        logger.info(f"{ticker}: data pipeline not available, using yfinance")
        return _fetch_yfinance_direct(f"{ticker}.NS")

    if PipelineSession is None:
        return _fetch_yfinance_direct(f"{ticker}.NS")

    db = PipelineSession()
    try:
        data = get_stock_data_from_db(ticker, db)

        if data.get("currentPrice") and data.get("_has_financials"):
            logger.info(f"{ticker}: served from local DB")
        else:
            logger.warning(f"{ticker}: DB incomplete, falling back to yfinance")
            yf_data = _fetch_yfinance_direct(f"{ticker}.NS")
            if yf_data:
                merged = {
                    k: _prefer_db(k, data.get(k), yf_data.get(k))
                    for k in set(yf_data) | set(data)
                }
                data = merged
            data["_source"] = "yfinance_fallback"

        from data.validator import validate_stock_data
        validation = validate_stock_data(ticker, data)
        data["_validation"] = validation

        return data

    finally:
        db.close()


def _fetch_yfinance_direct(ticker_ns: str) -> dict:
    """Direct yfinance fetch when pipeline DB is unavailable."""
    try:
        if yf is None:
            return {}
        stock = yf.Ticker(ticker_ns)
        info = stock.info
        return info if info else {}
    except Exception:
        return {}
