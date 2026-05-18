"""yfinance consensus-target client.

Thin wrapper around `yfinance.Ticker(t).info` that extracts the consensus
price-target fields we care about for the Benchmark Reconciliation Framework.

The mapping from yfinance's `.info` dict is:

    targetMeanPrice          -> target_mean
    targetMedianPrice        -> target_median
    targetHighPrice          -> target_high
    targetLowPrice           -> target_low
    numberOfAnalystOpinions  -> analyst_count

Missing keys are returned as None — yfinance silently omits these for
tickers without analyst coverage. Callers should skip rows where
target_mean and target_median are both None.

This module deliberately holds **no** writer state — it is a pure read
adapter. The refresh script (`scripts/refresh_consensus.py`) owns DB I/O.

Design: docs/design/benchmark-reconciliation-framework.md §2
"""
from __future__ import annotations

import logging
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)


class ConsensusRow(TypedDict, total=False):
    ticker: str
    source: str
    target_mean: Optional[float]
    target_median: Optional[float]
    target_high: Optional[float]
    target_low: Optional[float]
    analyst_count: Optional[int]
    currency: Optional[str]


def _to_yf_symbol(ticker: str) -> str:
    """NSE tickers in our DB are bare (e.g. 'RELIANCE'); yfinance wants '.NS'."""
    t = ticker.strip().upper()
    if "." in t:
        return t
    return f"{t}.NS"


def _coerce_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # yfinance occasionally returns 0.0 for "unknown" — treat as missing.
    if f == 0.0:
        return None
    return f


def _coerce_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def fetch_one(ticker: str, *, yf_module=None) -> Optional[ConsensusRow]:
    """Fetch consensus targets for a single ticker.

    Returns None if yfinance has no analyst coverage for the ticker
    (both target_mean and target_median missing). Otherwise returns a
    ConsensusRow with source='yfinance'.

    Parameters
    ----------
    ticker : str
        Bare NSE symbol (e.g. 'RELIANCE'). The '.NS' suffix is added
        automatically if missing.
    yf_module : optional
        Inject a mock yfinance module for tests. Defaults to importing
        the real `yfinance` package.
    """
    if yf_module is None:
        import yfinance as yf_module  # type: ignore

    sym = _to_yf_symbol(ticker)
    try:
        info = yf_module.Ticker(sym).info or {}
    except Exception as e:  # noqa: BLE001 — yfinance raises a zoo of exceptions
        logger.debug("yfinance fetch failed for %s: %s", sym, e)
        return None

    target_mean = _coerce_float(info.get("targetMeanPrice"))
    target_median = _coerce_float(info.get("targetMedianPrice"))
    if target_mean is None and target_median is None:
        return None

    return ConsensusRow(
        ticker=ticker.strip().upper().replace(".NS", ""),
        source="yfinance",
        target_mean=target_mean,
        target_median=target_median,
        target_high=_coerce_float(info.get("targetHighPrice")),
        target_low=_coerce_float(info.get("targetLowPrice")),
        analyst_count=_coerce_int(info.get("numberOfAnalystOpinions")),
        currency=(info.get("currency") or "INR").upper(),
    )
