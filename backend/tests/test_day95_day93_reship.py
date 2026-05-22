"""Day-95 re-ship tests for Day-93 deferred items.

Three items re-shipped via a scoped manifest entry (not a CACHE_VERSION bump):
  1. 17 metals/mining sector pins in TICKER_SECTOR_OVERRIDES
  2. AdrCohortBanner — expired "Q2 2026" ETA copy removed
  3. AnalysisBody humaniseSource — yfinance -> "Live (yfinance)"

Source-text guards only; no engine invocation. CACHE_VERSION must NOT change;
the scoped manifest entry is the sole invalidation gate.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

METALS_TICKERS = [
    "HINDZINC", "HINDCOPPER", "HINDALCO", "VEDL", "NATIONALUM",
    "TATASTEEL", "JSWSTEEL", "JINDALSTEL", "SAIL", "NMDC",
    "MOIL", "GMDCLTD", "COALINDIA", "WELCORP", "RATNAMANI",
    "APLAPOLLO", "JINDALSAW",
]


@pytest.mark.parametrize("ticker", METALS_TICKERS)
def test_metals_ticker_pinned_in_overrides(ticker):
    """Every Day-95 metals ticker resolves to 'Metals' via TICKER_SECTOR_OVERRIDES."""
    from backend.services.analysis.constants import TICKER_SECTOR_OVERRIDES

    assert TICKER_SECTOR_OVERRIDES.get(ticker) == "Metals", (
        f"{ticker} should be pinned to 'Metals' (was {TICKER_SECTOR_OVERRIDES.get(ticker)!r})"
    )
    assert TICKER_SECTOR_OVERRIDES.get(f"{ticker}.NS") == "Metals", (
        f"{ticker}.NS should be pinned to 'Metals'"
    )


def test_all_17_metals_tickers_pinned_count():
    """Sanity: all 17 expected tickers are present (no accidental drops)."""
    from backend.services.analysis.constants import TICKER_SECTOR_OVERRIDES

    missing = [t for t in METALS_TICKERS if TICKER_SECTOR_OVERRIDES.get(t) != "Metals"]
    assert not missing, f"Missing metals pins: {missing}"
    assert len(METALS_TICKERS) == 17


def test_adr_banner_q2_2026_eta_copy_removed():
    """The expired 'fix ETA Q2 2026' copy must be gone from AdrCohortBanner."""
    path = REPO_ROOT / "frontend" / "src" / "components" / "analysis" / "AdrCohortBanner.tsx"
    text = path.read_text(encoding="utf-8")
    assert "Q2 2026" not in text, "Expired 'Q2 2026' ETA copy still present"
    assert "fix ETA" not in text, "Stale 'fix ETA' fragment still present"


def test_adr_banner_uses_span_not_strong():
    """SEBI/theme rule: <strong> must be replaced with <span className=font-bold>."""
    path = REPO_ROOT / "frontend" / "src" / "components" / "analysis" / "AdrCohortBanner.tsx"
    text = path.read_text(encoding="utf-8")
    assert "<strong>" not in text, "<strong> tags must be replaced with span font-bold"
    assert 'className="font-bold"' in text, "Expected span className=font-bold replacement"


def test_humanise_source_maps_yfinance_to_live_label():
    """AnalysisBody humaniseSource should map yfinance to 'Live (yfinance)'."""
    path = REPO_ROOT / "frontend" / "src" / "app" / "(app)" / "analysis" / "[ticker]" / "AnalysisBody.tsx"
    text = path.read_text(encoding="utf-8")
    assert 'lower === "yfinance"' in text, "yfinance source check missing"
    assert '"Live (yfinance)"' in text, "yfinance should map to 'Live (yfinance)'"


def test_manifest_has_day95_metals_entry():
    """Manifest must include the v_day95_metals_sector_pins scoped entry."""
    from backend.services.cache_invalidation_manifest import MANIFEST

    ids = [e.get("version_id") for e in MANIFEST]
    assert "v_day95_metals_sector_pins" in ids, (
        f"Day-95 manifest entry missing. Found: {ids}"
    )


def test_day95_manifest_entry_scope_correct():
    """The Day-95 entry covers all 17 tickers with fields='*'."""
    from backend.services.cache_invalidation_manifest import MANIFEST

    entry = next(
        (e for e in MANIFEST if e.get("version_id") == "v_day95_metals_sector_pins"),
        None,
    )
    assert entry is not None
    scope = entry.get("scope", {})
    tickers = scope.get("tickers")
    assert isinstance(tickers, list)
    for t in METALS_TICKERS:
        assert t in tickers, f"{t} missing from manifest scope.tickers"
    assert scope.get("fields") == "*", "sector pin should invalidate all fields"


def test_cache_version_not_bumped_for_day95():
    """Day-95 must NOT bump CACHE_VERSION — the manifest is the gate."""
    # Day-94 settled CACHE_VERSION at 136; Day-95 must leave it alone.
    from backend.services.cache_service import CACHE_VERSION

    # Pinned at the value present on main at Day-95 start. Bumping this
    # value as part of Day-95 would defeat the purpose of Day-94's manifest.
    assert CACHE_VERSION == 135, (
        f"CACHE_VERSION moved to {CACHE_VERSION}; Day-95 must use manifest, not bump."
    )
