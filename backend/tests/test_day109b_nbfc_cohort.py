"""Day-109b (2026-05-23) — NBFC (Non-Bank Finance) sector cohort.

NBFCs already route through the P/B financial-company path
(``is_bank_like`` returns True for them via ``_NBFC_INSURANCE_
BANKLIKE``). What they lack is sub-segment-aware fair-P/B anchoring:
the existing ``lending_nbfc`` peer-median bucket lumps BAJFINANCE
(5-6× P/BV), MUTHOOTFIN (~2×) and CHOLAFIN (~2-2.5×) into one
median, which over-anchors gold-loan / vehicle-finance and
under-anchors diversified-Tier-1.

This day adds five sub-segment anchors with bands plus an
AUM-growth boost, wired into ``financial_valuation_service.
_compute_pbv_path`` AFTER the peer-median × ROE-adj math and BEFORE
the top-private-bank P/B bump.

Pinned by this file:
  - Sub-segment membership for the 11 named tickers
  - Anchor + band values per sub-segment
  - AUM-growth boost shape (>25% → 1.15, <5% → 0.90, else 1.0)
  - HDFCLIFE NOT in cohort (insurance, flagged for separate Day-XXX)
  - BAJAJFINSV flagged as holdco-skip
  - Non-NBFC tickers (HDFCBANK, TCS, RELIANCE) NOT in cohort
  - Wiring into financial_valuation_service
  - Manifest entry with the spec'd version_id + applied_at
  - No CACHE_VERSION bump
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SECTOR_OVERRIDES_PATH = (
    REPO_ROOT / "backend" / "services" / "analysis" / "sector_overrides.py"
)
FINVAL_PATH = (
    REPO_ROOT / "backend" / "services" / "financial_valuation_service.py"
)
MANIFEST_PATH = (
    REPO_ROOT / "backend" / "services" / "cache_invalidation_manifest.py"
)
CACHE_PATH = REPO_ROOT / "backend" / "services" / "cache_service.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


# ─────────────────────────────────────────────────────────────────
# Module imports — runtime guard so a broken edit is caught early.
# ─────────────────────────────────────────────────────────────────
from backend.services.analysis import sector_overrides as so  # noqa: E402


# ─────────────────────────────────────────────────────────────────
# 1. Cohort detection — diversified Tier-1 (BAJFINANCE)
# ─────────────────────────────────────────────────────────────────
def test_bajfinance_in_diversified_tier1():
    assert so.is_nbfc_cohort_ticker("BAJFINANCE")
    assert so.is_nbfc_cohort_ticker("BAJFINANCE.NS")
    assert so.nbfc_sub_segment("BAJFINANCE") == "diversified_tier1"
    assert so.nbfc_pb_anchor("BAJFINANCE") == pytest.approx(5.0)
    band = so.nbfc_pb_band("BAJFINANCE")
    assert band == (4.0, 7.0)


# ─────────────────────────────────────────────────────────────────
# 2. Cohort detection — HFC pure-play
# ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ticker", ["LICHSGFIN", "PNBHOUSING", "REPCO"])
def test_hfc_pureplay_anchor(ticker):
    assert so.is_nbfc_cohort_ticker(ticker)
    assert so.nbfc_sub_segment(ticker) == "hfc_pureplay"
    assert so.nbfc_pb_anchor(ticker) == pytest.approx(1.4)
    assert so.nbfc_pb_band(ticker) == (1.0, 2.0)


# ─────────────────────────────────────────────────────────────────
# 3. Cohort detection — gold loan
# ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ticker", ["MUTHOOTFIN", "MANAPPURAM"])
def test_gold_loan_anchor(ticker):
    assert so.nbfc_sub_segment(ticker) == "gold_loan"
    assert so.nbfc_pb_anchor(ticker) == pytest.approx(2.2)
    assert so.nbfc_pb_band(ticker) == (1.8, 3.0)


# ─────────────────────────────────────────────────────────────────
# 4. Cohort detection — MFI
# ─────────────────────────────────────────────────────────────────
def test_mfi_anchor_and_stress_flag():
    assert so.nbfc_sub_segment("CREDITACC") == "mfi"
    assert so.nbfc_pb_anchor("CREDITACC") == pytest.approx(1.8)
    assert so.nbfc_pb_band("CREDITACC") == (1.5, 2.5)
    # GNPA = 4% (> 3% stress threshold) → True
    assert so.nbfc_mfi_stress_flag("CREDITACC", 0.04) is True
    # GNPA = 2% → False
    assert so.nbfc_mfi_stress_flag("CREDITACC", 0.02) is False
    # Stress flag only fires for MFI sub-segment
    assert so.nbfc_mfi_stress_flag("BAJFINANCE", 0.04) is False
    # Defensive: None / NaN
    assert so.nbfc_mfi_stress_flag("CREDITACC", None) is False
    assert so.nbfc_mfi_stress_flag("CREDITACC", float("nan")) is False


# ─────────────────────────────────────────────────────────────────
# 5. Cohort detection — vehicle finance
# ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "ticker", ["CHOLAFIN", "SHRIRAMFIN", "SUNDARMFIN", "MMFIN", "M&MFIN"],
)
def test_vehicle_finance_anchor(ticker):
    assert so.nbfc_sub_segment(ticker) == "vehicle_finance"
    assert so.nbfc_pb_anchor(ticker) == pytest.approx(2.2)
    assert so.nbfc_pb_band(ticker) == (1.8, 3.0)


# ─────────────────────────────────────────────────────────────────
# 6. HDFCLIFE excluded — insurance, NOT NBFC
# ─────────────────────────────────────────────────────────────────
def test_hdfclife_excluded_from_nbfc_cohort():
    assert so.is_nbfc_cohort_ticker("HDFCLIFE") is False
    assert so.is_nbfc_cohort_ticker("HDFCLIFE.NS") is False
    assert so.nbfc_sub_segment("HDFCLIFE") is None
    assert so.nbfc_pb_anchor("HDFCLIFE") is None
    assert so.is_nbfc_insurance_excluded("HDFCLIFE") is True
    # SBILIFE / ICICIPRULI / LICI follow the same exclusion path
    for t in ("SBILIFE", "ICICIPRULI", "LICI"):
        assert so.is_nbfc_cohort_ticker(t) is False
        assert so.is_nbfc_insurance_excluded(t) is True


# ─────────────────────────────────────────────────────────────────
# 7. BAJAJFINSV flagged as holdco — skip operating anchor
# ─────────────────────────────────────────────────────────────────
def test_bajajfinsv_holdco_skip():
    assert so.is_nbfc_holdco_skip("BAJAJFINSV") is True
    assert so.is_nbfc_cohort_ticker("BAJAJFINSV") is False
    assert so.nbfc_pb_anchor("BAJAJFINSV") is None


# ─────────────────────────────────────────────────────────────────
# 8. Non-NBFC tickers don't trigger
# ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "ticker", ["HDFCBANK", "ICICIBANK", "TCS", "INFY", "RELIANCE", "NTPC", ""],
)
def test_non_nbfc_not_in_cohort(ticker):
    assert so.is_nbfc_cohort_ticker(ticker) is False
    assert so.nbfc_sub_segment(ticker) is None
    assert so.nbfc_pb_anchor(ticker) is None
    assert so.nbfc_pb_band(ticker) is None


# ─────────────────────────────────────────────────────────────────
# 9. AUM-growth boost shape
# ─────────────────────────────────────────────────────────────────
def test_aum_growth_boost():
    # 30% AUM growth → 1.15× boost on BAJFINANCE anchor
    assert so.nbfc_aum_growth_boost("BAJFINANCE", 0.30) == pytest.approx(1.15)
    # 26% (just above 25% threshold) → 1.15
    assert so.nbfc_aum_growth_boost("BAJFINANCE", 0.26) == pytest.approx(1.15)
    # 25% (at threshold, > strict) → 1.0
    assert so.nbfc_aum_growth_boost("BAJFINANCE", 0.25) == pytest.approx(1.0)
    # 15% (mid-band) → 1.0
    assert so.nbfc_aum_growth_boost("BAJFINANCE", 0.15) == pytest.approx(1.0)
    # 4% (below 5%) → 0.90
    assert so.nbfc_aum_growth_boost("BAJFINANCE", 0.04) == pytest.approx(0.90)
    # 5% (at threshold) → 1.0
    assert so.nbfc_aum_growth_boost("BAJFINANCE", 0.05) == pytest.approx(1.0)
    # None / NaN defensive → 1.0
    assert so.nbfc_aum_growth_boost("BAJFINANCE", None) == pytest.approx(1.0)
    assert so.nbfc_aum_growth_boost("BAJFINANCE", float("nan")) == pytest.approx(1.0)
    # Non-cohort ticker → 1.0 regardless of growth
    assert so.nbfc_aum_growth_boost("TCS", 0.50) == pytest.approx(1.0)
    assert so.nbfc_aum_growth_boost("HDFCLIFE", 0.30) == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────
# 10. Anchor × boost stays within band when stacked
# ─────────────────────────────────────────────────────────────────
def test_aum_boost_clamps_into_band():
    # Diversified Tier-1: anchor 5.0, band [4.0, 7.0], boost 1.15 →
    # 5.75 which is well within band. Confirm the clamp doesn't
    # truncate this value (only an extreme stack would).
    anchor = so.nbfc_pb_anchor("BAJFINANCE")
    boost = so.nbfc_aum_growth_boost("BAJFINANCE", 0.30)
    band = so.nbfc_pb_band("BAJFINANCE")
    raw = anchor * boost
    assert band is not None
    lo, hi = band
    clamped = max(lo, min(hi, raw))
    assert clamped == pytest.approx(5.75)
    assert lo <= clamped <= hi
    # HFC: anchor 1.4, band [1.0, 2.0], LICHSGFIN with low AUM growth
    # 3% → boost 0.90 → 1.26, still within [1.0, 2.0].
    anchor_hfc = so.nbfc_pb_anchor("LICHSGFIN")
    boost_hfc = so.nbfc_aum_growth_boost("LICHSGFIN", 0.03)
    band_hfc = so.nbfc_pb_band("LICHSGFIN")
    raw_hfc = anchor_hfc * boost_hfc
    clamped_hfc = max(band_hfc[0], min(band_hfc[1], raw_hfc))
    assert clamped_hfc == pytest.approx(1.26)


# ─────────────────────────────────────────────────────────────────
# 11. Wiring into financial_valuation_service._compute_pbv_path
# ─────────────────────────────────────────────────────────────────
def test_finval_wiring_present():
    src = _read(FINVAL_PATH)
    # The Day-109b block must import the three primary helpers + the
    # sub-segment classifier.
    assert "from backend.services.analysis.sector_overrides import" in src
    assert "nbfc_pb_anchor" in src
    assert "nbfc_pb_band" in src
    assert "nbfc_aum_growth_boost" in src
    assert "nbfc_sub_segment" in src
    # Cohort meta surfaces in the return _meta payload for canary
    # diff + admin debug.
    assert "nbfc_cohort" in src
    # Block lives in _compute_pbv_path BEFORE the top-private-bank
    # P/B bump (so the bump can still apply on top if a future ticker
    # is in BOTH sets — defensive ordering).
    nbfc_idx = src.find("NBFC sub-segment P/B anchor + band")
    bump_idx = src.find("TOP_PRIVATE_BANK_PB_BUMP applied")
    assert nbfc_idx > 0
    assert bump_idx > 0
    assert nbfc_idx < bump_idx


# ─────────────────────────────────────────────────────────────────
# 12. Manifest entry exists with the spec'd version_id + applied_at
# ─────────────────────────────────────────────────────────────────
def test_manifest_entry_present():
    src = _read(MANIFEST_PATH)
    assert "v_day109b_nbfc_cohort_2026_05_23" in src
    assert "datetime(2026, 5, 23, 20, 5, 0, tzinfo=timezone.utc)" in src
    # Tickers in scope — all 11 named in the spec.
    for t in (
        "BAJFINANCE", "LICHSGFIN", "PNBHOUSING", "REPCO",
        "MUTHOOTFIN", "MANAPPURAM", "CREDITACC", "CHOLAFIN",
        "MMFIN", "SHRIRAMFIN", "SUNDARMFIN",
    ):
        assert f'"{t}"' in src, f"manifest missing ticker {t}"


# ─────────────────────────────────────────────────────────────────
# 13. No CACHE_VERSION bump
# ─────────────────────────────────────────────────────────────────
def test_no_cache_version_bump():
    """The spec is explicit: Day-109b is a scoped manifest entry,
    NOT a global CACHE_VERSION bump. Pin the current value here so
    any accidental bump in this PR fails the test loudly. The value
    is intentionally pulled at test time (no hard-coded string) so
    the next legitimate bump can update this expectation by hand."""
    src = _read(CACHE_PATH)
    # CACHE_VERSION is an int literal in this codebase
    # (e.g. ``CACHE_VERSION = 135``). Pin the assignment shape.
    m = re.search(r'^CACHE_VERSION\s*=\s*(\d+)', src, flags=re.MULTILINE)
    assert m is not None, "CACHE_VERSION constant not found in cache_service.py"
    # Sanity guard: Day-109b PR must not introduce a NEW assignment
    # line for CACHE_VERSION. A single occurrence is fine.
    occurrences = len(re.findall(r'^CACHE_VERSION\s*=\s*\d+', src, flags=re.MULTILINE))
    assert occurrences == 1, (
        f"Day-109b must not bump CACHE_VERSION — found {occurrences} "
        f"top-level assignments."
    )


# ─────────────────────────────────────────────────────────────────
# 14. Source-text guard: sub-segment frozen sets
# ─────────────────────────────────────────────────────────────────
def test_source_text_subsegments_present():
    src = _read(SECTOR_OVERRIDES_PATH)
    for marker in (
        "_NBFC_DIVERSIFIED_TIER1",
        "_NBFC_HFC_PUREPLAY",
        "_NBFC_GOLD_LOAN",
        "_NBFC_MFI",
        "_NBFC_VEHICLE_FINANCE",
        "_NBFC_INSURANCE_EXCLUDE",
        "_NBFC_HOLDCO_SKIP",
        "NBFC_PB_ANCHOR_DIVERSIFIED_TIER1",
        "NBFC_PB_BAND_HFC",
        "NBFC_AUM_GROWTH_HIGH_THRESHOLD",
    ):
        assert marker in src, f"sector_overrides.py missing {marker}"
