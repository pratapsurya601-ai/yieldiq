# backend/services/data_service.py
# Wraps data/ and market data logic for FastAPI.
from __future__ import annotations
import sys, os
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

        indices = []
        for name, symbol in indices_config:
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
        try:
            _vix_sym = "^INDIAVIX"  # India-first launch
            _vix = yf.Ticker(_vix_sym).fast_info
            _val = getattr(_vix, "last_price", 20) or 20
            fg_idx = int(_val)
            # India VIX thresholds
            fg_label = "Greed" if _val < 12 else "Neutral" if _val < 18 else "Fear" if _val < 25 else "Extreme Fear"
        except Exception:
            pass

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
