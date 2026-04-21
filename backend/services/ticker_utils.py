"""Ticker normalisation helpers.

The YieldIQ DB carries ticker strings in several inconsistent formats
across tables (bare "TCS", ".NS"-suffixed "TCS.NS", ".BO"-suffixed
"TCS.BO", and Zerodha-style hyphen variants "PREMCO-X"). This module
gives callers a single, documented way to move between the two forms
used by the rest of the system:

  * "canonical":  <BARE>.NS for NSE tickers and <BARE>.BO for BSE-only
                  tickers. Matches what ``live_quotes`` already stores.
  * "bare":       Just the NSE stem (no exchange suffix). Used by
                  ``stocks``, ``financials``, ``market_metrics``,
                  ``ratio_history``, and ``daily_prices``.

NOTE: This module is groundwork for an incremental migration - writers
and readers are NOT yet switched over to call these helpers. Step 1 of
the plan (new writes -> canonical) lives in follow-up PRs. See
``docs/ticker_format_audit.md`` for the full migration ladder.

Edge cases handled:
  * ".BO" pass-through                 (BSE-only tickers stay on BSE)
  * Hyphen suffix stripping            (PREMCO-X, XYZ-EQ, ABC-BE, ...)
    Mirrors the precedent in
    ``backend/services/portfolio_service.py::_fetch_yfinance_price``.
  * Case normalisation                 (always upper-case)
  * Whitespace / empty / None safety   (returns "" for empty input)
"""
from __future__ import annotations

# Zerodha / exchange-series suffixes that appear in broker-statement
# tickers and need to be stripped before hitting yfinance or DB lookups.
# Keep this list in sync with portfolio_service._fetch_yfinance_price.
_HYPHEN_SUFFIXES: tuple[str, ...] = ("-X", "-EQ", "-BE", "-BL", "-BT", "-BZ")


def _strip_exchange(ticker: str) -> tuple[str, str]:
    """Split ticker into (bare, suffix) where suffix is ``.NS``, ``.BO`` or ``""``."""
    t = (ticker or "").strip().upper()
    if not t:
        return "", ""
    if t.endswith(".NS"):
        return t[:-3], ".NS"
    if t.endswith(".BO"):
        return t[:-3], ".BO"
    return t, ""


def _strip_hyphen_suffix(bare: str) -> str:
    """Strip Zerodha-style hyphen suffix (e.g. PREMCO-X -> PREMCO)."""
    b = bare.upper()
    for suffix in _HYPHEN_SUFFIXES:
        if b.endswith(suffix):
            return b[: -len(suffix)]
    return b


def to_canonical(ticker: str) -> str:
    """Return the canonical form of ``ticker``.

    Rules:
      * ``""`` or None -> ``""``
      * already ``.BO`` -> returned unchanged (case-folded to upper,
        hyphen suffix stripped)
      * otherwise -> append ``.NS``

    Examples:
        >>> to_canonical("tcs")
        'TCS.NS'
        >>> to_canonical("TCS.NS")
        'TCS.NS'
        >>> to_canonical("premco-x.bo")   # BSE-only, keep BSE
        'PREMCO.BO'
        >>> to_canonical("  reliance-eq  ")
        'RELIANCE.NS'
        >>> to_canonical("")
        ''
    """
    bare, suffix = _strip_exchange(ticker)
    if not bare:
        return ""
    bare = _strip_hyphen_suffix(bare)
    if not bare:
        return ""
    # BSE-only listings stay on BSE - do not force NSE.
    if suffix == ".BO":
        return f"{bare}.BO"
    return f"{bare}.NS"


def from_canonical(ticker: str) -> str:
    """Return the bare form (no exchange suffix, no hyphen series).

    Examples:
        >>> from_canonical("TCS.NS")
        'TCS'
        >>> from_canonical("PREMCO.BO")
        'PREMCO'
        >>> from_canonical("reliance")
        'RELIANCE'
        >>> from_canonical("RELIANCE-EQ")
        'RELIANCE'
        >>> from_canonical("")
        ''
    """
    bare, _suffix = _strip_exchange(ticker)
    if not bare:
        return ""
    return _strip_hyphen_suffix(bare)


__all__ = ["to_canonical", "from_canonical"]
