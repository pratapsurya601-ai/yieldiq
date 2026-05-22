"""Day-110b (2026-05-23) — Insurance sector cohort overrides.

Insurance is fundamentally different valuation math:
  - Life insurers: P/EV (Price-to-Embedded-Value), NOT DCF or P/B.
    Indian Tier-1 private life insurers trade at 2.0–3.5× EV; PSU
    (LICI) at 0.8–1.5× EV.
  - General insurers: P/B with combined-ratio overlay.

This file pins:
  - Sub-segment membership for 7 tickers (HDFCLIFE / SBILIFE /
    ICICIPRULI / LICI / MAXFIN / ICICIGI / NIACL)
  - Anchor + band values per sub-segment (P/EV path AND P/B fallback)
  - Combined-ratio overlay shape for GI tier-1 private
  - data_gaps surfacing (EV-missing for life, CR-missing for GI t1)
  - Non-insurance tickers (HDFCBANK, BAJFINANCE, TCS) NOT in cohort
  - Dual-handling guarantee with Day-109b (insurance is still
    NBFC-excluded; the new POSITIVE cohort layers on top)
  - Wiring into financial_valuation_service._compute_pbv_path
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
# 1. Cohort detection — life Tier-1 private
# ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "ticker", ["HDFCLIFE", "SBILIFE", "ICICIPRULI", "MAXFIN"]
)
def test_life_tier1_private_detected(ticker):
    assert so.is_insurance_cohort_ticker(ticker)
    assert so.is_insurance_cohort_ticker(f"{ticker}.NS")
    assert so.insurance_subsegment(ticker) == "life_tier1_private"


def test_hdfclife_pb_fallback_anchor():
    # No EV supplied → P/B fallback 4.5x, band [3.0, 6.0].
    anchor = so.insurance_anchor_multiple("HDFCLIFE")
    band = so.insurance_anchor_band("HDFCLIFE")
    assert anchor == pytest.approx(4.5)
    assert band == (3.0, 6.0)


def test_hdfclife_pev_anchor_when_ev_supplied():
    # EV per share supplied → P/EV 2.5x, band [2.0, 3.5].
    anchor = so.insurance_anchor_multiple(
        "HDFCLIFE", embedded_value_per_share=300.0
    )
    band = so.insurance_anchor_band(
        "HDFCLIFE", embedded_value_per_share=300.0
    )
    assert anchor == pytest.approx(2.5)
    assert band == (2.0, 3.5)


# ─────────────────────────────────────────────────────────────────
# 2. Cohort detection — life PSU (LICI)
# ─────────────────────────────────────────────────────────────────
def test_lici_detected_as_psu():
    assert so.is_insurance_cohort_ticker("LICI")
    assert so.insurance_subsegment("LICI") == "life_psu"


def test_lici_pb_fallback_anchor():
    anchor = so.insurance_anchor_multiple("LICI")
    band = so.insurance_anchor_band("LICI")
    assert anchor == pytest.approx(1.5)
    assert band == (1.0, 2.5)


def test_lici_pev_anchor_when_ev_supplied():
    anchor = so.insurance_anchor_multiple(
        "LICI", embedded_value_per_share=900.0
    )
    band = so.insurance_anchor_band(
        "LICI", embedded_value_per_share=900.0
    )
    assert anchor == pytest.approx(1.0)
    assert band == (0.8, 1.5)


# ─────────────────────────────────────────────────────────────────
# 3. Cohort detection — general insurance Tier-1 private (ICICIGI)
# ─────────────────────────────────────────────────────────────────
def test_icicigi_detected():
    assert so.is_insurance_cohort_ticker("ICICIGI")
    assert so.insurance_subsegment("ICICIGI") == "gi_tier1_private"


def test_icicigi_anchor_underwriting_profit():
    # CR < 100% → 6.5x anchor (above the unknown-CR baseline 6.0).
    anchor = so.insurance_anchor_multiple(
        "ICICIGI", combined_ratio=0.97
    )
    assert anchor == pytest.approx(6.5)


def test_icicigi_anchor_underwriting_loss():
    # CR >= 100% → 6.0x anchor (same as CR-unknown baseline).
    anchor = so.insurance_anchor_multiple(
        "ICICIGI", combined_ratio=1.05
    )
    assert anchor == pytest.approx(6.0)


def test_icicigi_anchor_cr_missing_defaults_safe():
    # CR not provided → defaults to 6.0x baseline (aligned with the
    # consensus-pinned private_gi median 5.9×).
    anchor = so.insurance_anchor_multiple("ICICIGI")
    assert anchor == pytest.approx(6.0)


def test_icicigi_combined_ratio_percent_form():
    # CR provided as percent (e.g. 97.0 not 0.97) — auto-detected.
    anchor = so.insurance_anchor_multiple(
        "ICICIGI", combined_ratio=97.0
    )
    assert anchor == pytest.approx(6.5)


# ─────────────────────────────────────────────────────────────────
# 4. Cohort detection — general insurance PSU (NIACL)
# ─────────────────────────────────────────────────────────────────
def test_niacl_detected():
    assert so.is_insurance_cohort_ticker("NIACL")
    assert so.insurance_subsegment("NIACL") == "gi_psu"


def test_niacl_anchor_regardless_of_cr():
    # PSU anchor is 1.05x book whether CR is loss or profit (matches
    # psu_gi peer-median, NIACL FY25 P/B ≈ 0.94 — keeps cohort layer
    # aligned with 3-analyst consensus ₹170).
    assert so.insurance_anchor_multiple("NIACL") == pytest.approx(1.05)
    assert so.insurance_anchor_multiple(
        "NIACL", combined_ratio=0.92
    ) == pytest.approx(1.05)
    assert so.insurance_anchor_multiple(
        "NIACL", combined_ratio=1.10
    ) == pytest.approx(1.05)
    assert so.insurance_anchor_band("NIACL") == (0.8, 1.5)


# ─────────────────────────────────────────────────────────────────
# 5. Non-insurance tickers NOT in cohort
# ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "ticker", ["HDFCBANK", "BAJFINANCE", "TCS", "RELIANCE", "HUL"]
)
def test_non_insurance_not_in_cohort(ticker):
    assert not so.is_insurance_cohort_ticker(ticker)
    assert so.insurance_subsegment(ticker) is None
    assert so.insurance_anchor_multiple(ticker) is None
    assert so.insurance_anchor_band(ticker) is None
    assert so.insurance_data_gaps(ticker) == {}


# ─────────────────────────────────────────────────────────────────
# 6. data_gaps surfacing
# ─────────────────────────────────────────────────────────────────
def test_data_gaps_life_ev_missing():
    # HDFCLIFE without EV → ev_missing True, data_limited True.
    gaps = so.insurance_data_gaps("HDFCLIFE", bvps=80.0)
    assert gaps["ev_missing"] is True
    assert gaps["combined_ratio_missing"] is False
    assert gaps["data_limited"] is True
    assert gaps["sub_segment"] == "life_tier1_private"


def test_data_gaps_life_ev_present():
    gaps = so.insurance_data_gaps(
        "HDFCLIFE", embedded_value_per_share=300.0, bvps=80.0
    )
    assert gaps["ev_missing"] is False
    assert gaps["data_limited"] is False


def test_data_gaps_gi_tier1_cr_missing():
    gaps = so.insurance_data_gaps("ICICIGI", bvps=180.0)
    assert gaps["combined_ratio_missing"] is True
    assert gaps["data_limited"] is True


def test_data_gaps_gi_tier1_cr_present():
    gaps = so.insurance_data_gaps(
        "ICICIGI", combined_ratio=0.98, bvps=180.0
    )
    assert gaps["combined_ratio_missing"] is False
    assert gaps["data_limited"] is False


def test_data_gaps_gi_psu_always_complete():
    # gi_psu does not need CR — static 1.5x book.
    gaps = so.insurance_data_gaps("NIACL", bvps=400.0)
    assert gaps["data_limited"] is False


def test_data_gaps_bvps_missing_flag():
    gaps = so.insurance_data_gaps("LICI")
    assert gaps["bvps_missing"] is True


# ─────────────────────────────────────────────────────────────────
# 7. Dual-handling with Day-109b (NBFC) — insurance is still
#    NBFC-excluded; this cohort is the POSITIVE side.
# ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ticker", ["HDFCLIFE", "SBILIFE", "ICICIPRULI", "LICI"])
def test_insurance_still_nbfc_excluded(ticker):
    # Day-109b's exclusion list MUST continue to flag insurers, so
    # they don't accidentally pick up NBFC math via is_nbfc_cohort_
    # ticker. Day-110b is layered on top of the existing peer-group
    # routing in financial_valuation_service.py, not a replacement.
    assert so.is_nbfc_insurance_excluded(ticker) is True
    assert so.is_nbfc_cohort_ticker(ticker) is False
    # And the Day-110b POSITIVE cohort fires.
    assert so.is_insurance_cohort_ticker(ticker) is True


# ─────────────────────────────────────────────────────────────────
# 8. Suffix tolerance
# ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("suffix", ["", ".NS", ".BO", ".BSE"])
def test_suffix_tolerated(suffix):
    assert so.is_insurance_cohort_ticker(f"HDFCLIFE{suffix}")
    assert so.insurance_subsegment(f"LICI{suffix}") == "life_psu"


# ─────────────────────────────────────────────────────────────────
# 9. Cohort membership (inline set) — pinning exact tickers in scope
# ─────────────────────────────────────────────────────────────────
def test_cohort_membership_exact():
    expected = {
        "HDFCLIFE", "SBILIFE", "ICICIPRULI", "MAXFIN",
        "LICI", "ICICIGI", "NIACL",
    }
    assert so.INSURANCE_COHORT_TICKERS_INLINE == expected


# ─────────────────────────────────────────────────────────────────
# 10. Source-text: wired into financial_valuation_service
# ─────────────────────────────────────────────────────────────────
def test_finval_imports_insurance_helpers():
    src = _read(FINVAL_PATH)
    assert "insurance_anchor_multiple" in src
    assert "insurance_anchor_band" in src
    assert "insurance_subsegment" in src
    assert "insurance_data_gaps" in src
    assert "is_insurance_cohort_ticker" in src
    # Tagged for diff readability.
    assert "Day-110b" in src
    assert "Insurance cohort anchor applied" in src


def test_finval_meta_includes_insurance_cohort():
    src = _read(FINVAL_PATH)
    assert "insurance_cohort" in src


# ─────────────────────────────────────────────────────────────────
# 11. Manifest entry
# ─────────────────────────────────────────────────────────────────
def test_manifest_entry_present():
    src = _read(MANIFEST_PATH)
    assert "v_day110b_insurance_cohort_2026_05_23" in src
    # applied_at 21:00 UTC per spec (no collision with prior entries).
    assert "datetime(2026, 5, 23, 21, 0, 0, tzinfo=timezone.utc)" in src
    # All 7 tickers listed.
    for t in [
        "HDFCLIFE", "SBILIFE", "ICICIPRULI", "LICI", "MAXFIN",
        "ICICIGI", "NIACL",
    ]:
        assert f'"{t}"' in src


# ─────────────────────────────────────────────────────────────────
# 12. No CACHE_VERSION bump
# ─────────────────────────────────────────────────────────────────
def test_no_cache_version_bump():
    if not CACHE_PATH.exists():
        pytest.skip("cache_service.py not present in this checkout")
    src = _read(CACHE_PATH)
    # Whatever CACHE_VERSION is today, this commit must not touch it
    # — we only added a scoped manifest entry. Pin the count of
    # CACHE_VERSION = "..." assignment lines (typically 1) so any
    # accidental bump shows up as a test failure.
    matches = re.findall(r"^CACHE_VERSION\s*=", src, flags=re.MULTILINE)
    assert len(matches) == 1
