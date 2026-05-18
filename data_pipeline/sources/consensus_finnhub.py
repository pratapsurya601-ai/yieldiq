"""Finnhub consensus-target client.

Wraps Finnhub's `/stock/price-target` endpoint (and optionally
`/stock/recommendation` for analyst count). Used by the nightly
consensus-refresh job — Finnhub gives better small/mid-cap NSE coverage
than yfinance.

Free tier is 60 req/min. The refresh script sleeps ≥1.1s between calls.

Auth: requires the `FINNHUB_API_KEY` environment variable. If unset,
`fetch_one` returns None and logs a warning.

Design: docs/design/benchmark-reconciliation-framework.md §2
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .consensus_yfinance import ConsensusRow, _coerce_float, _coerce_int

logger = logging.getLogger(__name__)

_BASE_URL = "https://finnhub.io/api/v1"
# Finnhub symbol convention for NSE: 'RELIANCE.NS' (same as yfinance).
_FINNHUB_SUFFIX = ".NS"


def _to_finnhub_symbol(ticker: str) -> str:
    t = ticker.strip().upper()
    return t if "." in t else f"{t}{_FINNHUB_SUFFIX}"


def fetch_one(
    ticker: str,
    *,
    api_key: Optional[str] = None,
    requests_module=None,
) -> Optional[ConsensusRow]:
    """Fetch consensus price target + analyst count for a single ticker.

    Returns None when:
      * `FINNHUB_API_KEY` is not configured;
      * Finnhub returns no price-target row;
      * the HTTP call fails.

    Otherwise returns a ConsensusRow with source='finnhub'.
    """
    key = api_key or os.environ.get("FINNHUB_API_KEY")
    if not key:
        logger.warning("FINNHUB_API_KEY not set; skipping Finnhub fetch for %s", ticker)
        return None

    if requests_module is None:
        import requests as requests_module  # type: ignore

    sym = _to_finnhub_symbol(ticker)

    # ── /stock/price-target ─────────────────────────────────────────
    try:
        r = requests_module.get(
            f"{_BASE_URL}/stock/price-target",
            params={"symbol": sym, "token": key},
            timeout=10,
        )
        r.raise_for_status()
        pt = r.json() or {}
    except Exception as e:  # noqa: BLE001
        logger.debug("Finnhub price-target fetch failed for %s: %s", sym, e)
        return None

    target_mean = _coerce_float(pt.get("targetMean"))
    target_median = _coerce_float(pt.get("targetMedian"))
    if target_mean is None and target_median is None:
        return None

    analyst_count = _coerce_int(pt.get("numberOfAnalysts"))

    # ── /stock/recommendation (optional, for analyst_count backfill) ─
    if analyst_count is None:
        try:
            r2 = requests_module.get(
                f"{_BASE_URL}/stock/recommendation",
                params={"symbol": sym, "token": key},
                timeout=10,
            )
            r2.raise_for_status()
            rec = (r2.json() or [])
            if rec:
                latest = rec[0]
                analyst_count = sum(
                    _coerce_int(latest.get(k)) or 0
                    for k in ("strongBuy", "buy", "hold", "sell", "strongSell")
                ) or None
        except Exception as e:  # noqa: BLE001
            logger.debug("Finnhub recommendation fetch failed for %s: %s", sym, e)

    return ConsensusRow(
        ticker=ticker.strip().upper().replace(".NS", ""),
        source="finnhub",
        target_mean=target_mean,
        target_median=target_median,
        target_high=_coerce_float(pt.get("targetHigh")),
        target_low=_coerce_float(pt.get("targetLow")),
        analyst_count=analyst_count,
        currency="INR",  # Finnhub returns INR for .NS symbols
    )
