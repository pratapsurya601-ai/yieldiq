"""Regression test for /analysis/{ticker}/og-data alias rewrite.

Before 2026-05-03, the og-data router did NOT apply TICKER_ALIASES, so a
request to /og-data/LTIM.NS would compute against the stale yfinance
LTIM.NS row (Mindtree merger leftover) instead of the canonical
LTIMINDTREE.NS, producing fv=0/px=0 and tripping VALIDATION CRITICAL on
every single page-view (Sentry: 13,964 events/24h).

This test pins the contract: the og-data endpoint applies the alias map
BEFORE the cache key is built. We grep the source rather than importing
the FastAPI router so the unit-test layer doesn't need fastapi installed.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_PY = ROOT / "backend" / "routers" / "analysis.py"


def _og_data_function_source() -> str:
    """Return the raw text of get_og_data() including its signature."""
    src = ANALYSIS_PY.read_text(encoding="utf-8")
    # Find the get_og_data function definition.
    m = re.search(
        r"^async def get_og_data\([^)]*\):\n(?:[ \t]+.*\n|\n)+",
        src,
        re.MULTILINE,
    )
    assert m, "get_og_data() not found in backend/routers/analysis.py"
    return m.group(0)


def test_ltim_alias_is_present():
    """LTIM.NS and bare LTIM both alias to LTIMINDTREE.NS in the dict."""
    src = ANALYSIS_PY.read_text(encoding="utf-8")
    assert '"LTIM.NS":         "LTIMINDTREE.NS"' in src
    assert '"LTIM":            "LTIMINDTREE.NS"' in src


def test_og_data_endpoint_resolves_alias_before_cache_lookup():
    """The og-data handler MUST apply TICKER_ALIASES BEFORE the
    `og:{ticker}` cache key is computed. Without this, the LTIM.NS and
    LTIMINDTREE.NS share-link previews diverge — and worse, LTIM.NS
    cold-computes through validators on every request.
    """
    fn_src = _og_data_function_source()

    assert "TICKER_ALIASES.get(" in fn_src, (
        "get_og_data must rewrite via TICKER_ALIASES before cache lookup; "
        "otherwise renamed/rebranded tickers (LTIM.NS → LTIMINDTREE.NS) "
        "bypass the alias and flood Sentry with VALIDATION CRITICAL."
    )

    # Order check: alias rewrite must precede the og:{ticker} cache key.
    alias_pos = fn_src.find("TICKER_ALIASES.get(")
    cache_key_pos = fn_src.find('f"og:{')
    assert alias_pos != -1 and cache_key_pos != -1
    assert alias_pos < cache_key_pos, (
        "TICKER_ALIASES rewrite must run BEFORE the og: cache key is built"
    )
