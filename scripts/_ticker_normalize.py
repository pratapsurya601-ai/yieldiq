"""Shared bare-ticker → exchange-suffix normalizer for offline scripts.

Why this exists
---------------
The 2026-05-17 MPHASIS/COFORGE/PERSISTENT `data_limited` outage was
caused by a golden-snapshot refresh script that passed BARE tickers
(e.g. ``"MPHASIS"`` instead of ``"MPHASIS.NS"``) into the compute
path. yfinance, given a bare Indian ticker, returns the US-routed
empty result with ``market_cap=0``. That poisoned payload then
UPSERTed over the previously-healthy ``MPHASIS.NS`` cache row via
``analysis_cache_service.save_cached`` and surfaced as ``data_limited``
on the live site.

Root-cause fix: every offline script that writes to ``analysis_cache``
(directly or indirectly, e.g. via ``compute_for_date`` or
``AnalysisService.get_full_analysis``) MUST funnel each ticker through
``normalize_for_compute()`` BEFORE handing it to compute.

Implementation
--------------
We delegate to the existing
``backend.services.analysis.utils._canonicalize_ticker`` which
already encodes the "bare Indian → .NS" rule (and leaves US/global
symbols alone). For numeric BSE scrip codes (``"500188"``) we layer
an extra rule: 6-digit all-numeric strings get ``.BO`` appended
because no NSE symbol is purely numeric.

If the backend import fails (rare; e.g. running the script with a
broken PYTHONPATH), we fall back to a minimal in-place rule that
appends ``.NS`` to any bare alphanumeric symbol that contains at
least one letter. That is the same default the rest of the codebase
applies for unknown bare symbols.
"""
from __future__ import annotations

import re

_NUMERIC_BSE = re.compile(r"^\d{6}$")


def normalize_for_compute(ticker: str) -> str:
    """Return an exchange-suffixed ticker safe to pass into the compute path.

    Examples:
        ``"MPHASIS"``     -> ``"MPHASIS.NS"``
        ``"MPHASIS.NS"``  -> ``"MPHASIS.NS"`` (unchanged)
        ``"mphasis"``     -> ``"MPHASIS.NS"``
        ``"500188"``      -> ``"500188.BO"`` (numeric BSE scrip code)
        ``"AAPL"``        -> ``"AAPL"``      (genuinely US, unchanged)
        ``""``            -> ``""``          (empty passthrough)
        ``None``          -> ``""``
    """
    if not ticker:
        return ""
    raw = str(ticker).strip()
    if not raw:
        return ""
    upper = raw.upper()

    # 1. Numeric-only BSE scrip code — no NSE symbol is all-digits.
    if _NUMERIC_BSE.match(upper):
        return f"{upper}.BO"

    # 2. Already suffixed — preserve as-is (canonicalize will pass through).
    if upper.endswith(".NS") or upper.endswith(".BO"):
        return upper

    # 3. Delegate to the backend canonicalizer, which knows the live
    #    universe of Indian bare tickers via the `stocks` table cache.
    try:
        from backend.services.analysis.utils import _canonicalize_ticker
        canon = _canonicalize_ticker(upper)
        if canon and (canon.endswith(".NS") or canon.endswith(".BO")):
            return canon
        # Backend says "unknown" — for an offline script that *only*
        # operates on Indian tickers (snapshot/refresh universes are
        # all Indian by construction) default to .NS rather than let a
        # bare symbol hit yfinance and silently route to the US path.
        if canon and any(ch.isalpha() for ch in canon):
            return f"{canon}.NS"
        return canon or upper
    except Exception:
        # 4. Fallback if backend import is broken.
        if any(ch.isalpha() for ch in upper):
            return f"{upper}.NS"
        return upper


__all__ = ["normalize_for_compute"]
