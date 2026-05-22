"""Day-93 (2026-05-22): audit #4 low-hanging polish batch.

Closes 4 findings from the 2026-05-22 audit walkthrough:

  1. HINDZINC (pure-play zinc miner) rendered with non-metals sector.
     17 metals/mining tickers pinned to "Metals & Mining" in
     _DAY3_SECTOR_FIXES so the cyclical-normalisation cohort + sector
     facet route them correctly. CACHE_VERSION bumped 134 -> 136 (Day-92 took 135).
  2. AdrCohortBanner banner showed "Fix ETA Q2 2026" — we are now IN
     Q2 2026 and the date became a credibility tax. Copy rewritten to
     active language ("Repair is in progress …").
  3. DataFreshnessWidget showed INFY as "Sources: yfinance" while 16
     sibling stocks rendered "YieldIQ database". Underlying data IS
     legitimately yfinance for INFY (ADR cohort, no warm DB record yet)
     so the honest disclosure stays — but the PHRASING is normalised
     to "Live (yfinance)" to match the existing "Live (NSE)" /
     "Live (BSE)" convention.
  4. MANKIND analysis "timed out" was probed live: backend stock-summary
     endpoint returns 200 in ~0.6s. The 7s wait the audit recorded was
     a cold-cache full /analyze recompute, not a backend bug. Tracked
     as known UX; warm-cache job already covers MANKIND via Day-25 job
     and Day-89 YIQ50 universe.

Source-text regression guards because all real changes are isolated
string / mapping / dict edits with no Python-runtime surface beyond
import.
"""
from __future__ import annotations
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_CONSTS = _ROOT / "backend" / "services" / "analysis" / "constants.py"
_BODY = (
    _ROOT / "frontend" / "src" / "app" / "(app)" / "analysis" / "[ticker]"
    / "AnalysisBody.tsx"
)
_BANNER = (
    _ROOT / "frontend" / "src" / "components" / "analysis" / "AdrCohortBanner.tsx"
)
_CACHE = _ROOT / "backend" / "services" / "cache_service.py"


# ── Item 1: HINDZINC + metals/mining sector pins ───────────────


def test_hindzinc_pinned_to_metals_mining():
    src = _CONSTS.read_text(encoding="utf-8")
    assert '"HINDZINC":    "Metals & Mining"' in src


def test_all_metals_tickers_pinned():
    src = _CONSTS.read_text(encoding="utf-8")
    metals = (
        "HINDZINC", "HINDCOPPER", "HINDALCO", "VEDL", "NATIONALUM",
        "TATASTEEL", "JSWSTEEL", "JINDALSTEL", "SAIL", "NMDC",
        "MOIL", "GMDCLTD", "COALINDIA",
        "WELCORP", "RATNAMANI", "APLAPOLLO", "JINDALSAW",
    )
    import re
    for t in metals:
        # Tolerate variable spacing between the colon and the value (dict
        # alignment varies with key length, e.g. HINDCOPPER vs SAIL).
        pat = re.compile(rf'"{t}":\s+"Metals & Mining"')
        assert pat.search(src), f"{t} not pinned to Metals & Mining"


def test_metals_pins_resolved_via_overrides_dict():
    """Import-time check the dict actually picks up the new entries."""
    from backend.services.analysis.constants import TICKER_SECTOR_OVERRIDES

    for t in ("HINDZINC", "TATASTEEL", "VEDL", "COALINDIA"):
        assert TICKER_SECTOR_OVERRIDES.get(t) == "Metals & Mining"
        assert TICKER_SECTOR_OVERRIDES.get(f"{t}.NS") == "Metals & Mining"


# ── Item 2: TCS / ADR banner ETA date removed ──────────────────


def test_adr_banner_eta_q2_2026_removed():
    src = _BANNER.read_text(encoding="utf-8")
    # The user-visible banner copy must no longer contain the expired date.
    # We allow the string in the design-rationale comment block (history).
    user_copy_region = src.split("export default function", 1)[1]
    assert "Fix ETA Q2 2026" not in user_copy_region
    assert "fix ETA Q2 2026" not in user_copy_region


def test_adr_banner_uses_active_repair_copy():
    src = _BANNER.read_text(encoding="utf-8")
    assert "Repair is in progress" in src


def test_adr_banner_no_strong_tag():
    """Theme rule from Day-72: <strong> -> <span className=\"font-bold\">."""
    src = _BANNER.read_text(encoding="utf-8")
    assert "<strong>" not in src
    assert '<span className="font-bold">Data Limited:</span>' in src


# ── Item 3: yfinance humanise phrasing parity ──────────────────


def test_yfinance_humanise_phrased_as_live():
    src = _BODY.read_text(encoding="utf-8")
    assert 'lower === "yfinance"' in src
    assert 'return "Live (yfinance)"' in src


def test_yfinance_humanise_no_longer_literal_passthrough():
    """Negative assertion: the old `return "yfinance"` literal is gone."""
    src = _BODY.read_text(encoding="utf-8")
    # The bare return-literal pattern must no longer appear adjacent to
    # the yfinance branch. We test by ensuring the line that used to read
    # `if (lower === "yfinance") return "yfinance"` is not present.
    assert 'if (lower === "yfinance") return "yfinance"' not in src


# ── Item 4: CACHE_VERSION bump (136 — metals pin routes cohorts; Day-92 took 135) ──


def test_cache_version_bumped_to_136():
    src = _CACHE.read_text(encoding="utf-8")
    assert "CACHE_VERSION = 136" in src
    assert "CACHE_VERSION = 134" not in src.split("\n")[33]


def test_cache_version_bump_documents_day93():
    src = _CACHE.read_text(encoding="utf-8")
    assert "day93-audit4-polish" in src
    assert "HINDZINC" in src
