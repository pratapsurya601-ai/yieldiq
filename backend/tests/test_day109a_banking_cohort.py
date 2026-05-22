"""Day-109a (2026-05-23) — Banking sector cohort overrides.

Layered on top of the existing Day-76 PB-ratio skip path (banks already
bypass generic DCF in favour of P/BV peer-median valuation). The cohort
adds:

  1. Tier-anchored fair P/BV: tier-1 private 3.0x, PSU 1.2x, tier-2
     1.8x — with cohort bands (2.5-4.0 / 0.9-1.6 / 1.2-2.5).
  2. ROE-quality boost: ROE >= 16% AND GNPA <= 2.0% lifts the anchor
     by +20% (HDFCBANK shape → 3.6x book).
  3. Stress flag: GNPA > 5% OR PCR < 60% sets data_limited and
     surfaces "stressed book" in data_issues.
  4. NIM is informational only (not a knob), surfaced via data_issues.

Data gap (2026-05-23): GNPA + provision_coverage are not in the local
parquet (no `data/parquet/` checked in). The cohort degrades gracefully
when these are None — anchor still applies, boost reverts to 1.0, no
stress flag. Phase 2 will populate from NSE-XBRL-Sch-XVIII.

These tests pin:
  - Module exports + cohort membership
  - Tier classification (tier-1 private / PSU / tier-2)
  - PB band + anchor per tier
  - ROE-quality boost math (fires only on HDFCBANK shape)
  - Stress flag thresholds (GNPA > 5% / PCR < 60%)
  - Non-bank tickers don't trigger
  - Pre-existing PB-ratio skip path preserved for cohort tickers
  - Manifest entry exists with the spec'd version_id + applied_at
  - No CACHE_VERSION bump
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = REPO_ROOT / "backend" / "services" / "analysis" / "service.py"
SECTOR_OVERRIDES_PATH = (
    REPO_ROOT / "backend" / "services" / "analysis" / "sector_overrides.py"
)
MANIFEST_PATH = (
    REPO_ROOT / "backend" / "services" / "cache_invalidation_manifest.py"
)
CACHE_PATH = REPO_ROOT / "backend" / "services" / "cache_service.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


# ─────────────────────────────────────────────────────────────────
# 1. Module + exports
# ─────────────────────────────────────────────────────────────────

def test_sector_overrides_exports_banking_helpers():
    from backend.services.analysis import sector_overrides as so
    for name in (
        "is_banking_cohort_ticker",
        "banking_tier",
        "banking_pb_band",
        "banking_pb_anchor",
        "banking_roe_quality_boost",
        "banking_stress_flag",
        "BANKING_TIER1_TICKERS_INLINE",
        "BANKING_TIER1_PRIVATE_TICKERS",
        "BANKING_PSU_TICKERS",
        "BANKING_TIER2_TICKERS",
    ):
        assert hasattr(so, name), (
            f"sector_overrides must export {name} for Day-109a banking cohort"
        )


# ─────────────────────────────────────────────────────────────────
# 2. Cohort membership & tier classification
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ticker", [
    "HDFCBANK", "HDFCBANK.NS",
    "ICICIBANK", "ICICIBANK.NS",
    "KOTAKBANK", "AXISBANK", "INDUSINDBK",
    "SBIN", "SBIN.NS",
    "FEDERALBNK", "IDFCFIRSTB", "AUBANK", "BANDHANBNK", "RBLBANK",
])
def test_banking_cohort_membership_positive(ticker):
    from backend.services.analysis import sector_overrides as so
    assert so.is_banking_cohort_ticker(ticker), (
        f"{ticker} must be in Day-109a banking cohort"
    )


@pytest.mark.parametrize("ticker", [
    "NTPC", "TCS", "RELIANCE", "INFY", "HUL", "HINDUNILVR",
    "MANKIND", "TATAMOTORS", None, "",
])
def test_banking_cohort_membership_negative(ticker):
    from backend.services.analysis import sector_overrides as so
    assert not so.is_banking_cohort_ticker(ticker), (
        f"{ticker} must NOT be in Day-109a banking cohort"
    )


def test_banking_tier_classification():
    from backend.services.analysis import sector_overrides as so
    # Tier-1 private
    for t in ("HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK"):
        assert so.banking_tier(t) == "tier1_private", t
    # PSU
    assert so.banking_tier("SBIN") == "psu"
    assert so.banking_tier("SBIN.NS") == "psu"
    # Tier-2
    for t in ("FEDERALBNK", "IDFCFIRSTB", "AUBANK", "BANDHANBNK", "RBLBANK"):
        assert so.banking_tier(t) == "tier2", t
    # Non-cohort
    assert so.banking_tier("NTPC") is None
    assert so.banking_tier("TCS") is None


# ─────────────────────────────────────────────────────────────────
# 3. PB band + anchor per tier
# ─────────────────────────────────────────────────────────────────

def test_hdfcbank_tier1_band_and_anchor():
    from backend.services.analysis import sector_overrides as so
    assert so.banking_pb_band("HDFCBANK") == (2.5, 4.0)
    assert so.banking_pb_anchor("HDFCBANK") == 3.0
    assert so.banking_pb_band("HDFCBANK.NS") == (2.5, 4.0)


def test_sbin_psu_band_and_anchor():
    from backend.services.analysis import sector_overrides as so
    assert so.banking_pb_band("SBIN") == (0.9, 1.6)
    assert so.banking_pb_anchor("SBIN") == 1.2


def test_tier2_band_and_anchor():
    from backend.services.analysis import sector_overrides as so
    assert so.banking_pb_band("FEDERALBNK") == (1.2, 2.5)
    assert so.banking_pb_anchor("FEDERALBNK") == 1.8
    assert so.banking_pb_anchor("AUBANK") == 1.8


def test_non_bank_returns_none_for_band_anchor():
    from backend.services.analysis import sector_overrides as so
    assert so.banking_pb_band("NTPC") is None
    assert so.banking_pb_anchor("TCS") is None


# ─────────────────────────────────────────────────────────────────
# 4. ROE-quality boost
# ─────────────────────────────────────────────────────────────────

def test_roe_quality_boost_fires_for_hdfcbank_shape():
    """HDFCBANK at ROE 17.5%, GNPA 1.4% → +20% boost (anchor × 1.2 = 3.6)."""
    from backend.services.analysis import sector_overrides as so
    boost = so.banking_roe_quality_boost("HDFCBANK", 0.175, 0.014)
    assert boost == 1.20
    # Accepts percent format too
    boost_pct = so.banking_roe_quality_boost("HDFCBANK", 17.5, 1.4)
    assert boost_pct == 1.20
    # End-to-end fair PB
    anchor = so.banking_pb_anchor("HDFCBANK")
    assert round(anchor * boost, 2) == 3.6


def test_roe_quality_boost_does_not_fire_when_roe_too_low():
    from backend.services.analysis import sector_overrides as so
    # ROE 12% < 16% threshold
    assert so.banking_roe_quality_boost("ICICIBANK", 0.12, 0.014) == 1.0


def test_roe_quality_boost_does_not_fire_when_gnpa_too_high():
    from backend.services.analysis import sector_overrides as so
    # GNPA 3.5% > 2.0% threshold
    assert so.banking_roe_quality_boost("ICICIBANK", 0.17, 0.035) == 1.0


def test_roe_quality_boost_degrades_on_missing_data():
    """Data gap (no GNPA in parquet today) must not penalise the bank."""
    from backend.services.analysis import sector_overrides as so
    assert so.banking_roe_quality_boost("HDFCBANK", 0.18, None) == 1.0
    assert so.banking_roe_quality_boost("HDFCBANK", None, 0.014) == 1.0
    assert so.banking_roe_quality_boost("HDFCBANK", None, None) == 1.0


def test_roe_quality_boost_negative_for_non_bank():
    from backend.services.analysis import sector_overrides as so
    assert so.banking_roe_quality_boost("NTPC", 0.20, 0.01) == 1.0
    assert so.banking_roe_quality_boost("TCS", 0.40, 0.0) == 1.0


# ─────────────────────────────────────────────────────────────────
# 5. Stress flag
# ─────────────────────────────────────────────────────────────────

def test_stress_flag_fires_on_high_gnpa():
    from backend.services.analysis import sector_overrides as so
    assert so.banking_stress_flag("SBIN", 0.06, 0.70) is True
    assert so.banking_stress_flag("SBIN", 6.0, 70.0) is True   # percent


def test_stress_flag_fires_on_low_provision_coverage():
    from backend.services.analysis import sector_overrides as so
    assert so.banking_stress_flag("FEDERALBNK", 0.018, 0.55) is True


def test_stress_flag_does_not_fire_on_healthy_book():
    from backend.services.analysis import sector_overrides as so
    assert so.banking_stress_flag("HDFCBANK", 0.014, 0.75) is False


def test_stress_flag_degrades_to_false_on_missing_data():
    from backend.services.analysis import sector_overrides as so
    assert so.banking_stress_flag("HDFCBANK", None, None) is False


def test_stress_flag_negative_for_non_bank():
    from backend.services.analysis import sector_overrides as so
    assert so.banking_stress_flag("NTPC", 0.10, 0.30) is False


# ─────────────────────────────────────────────────────────────────
# 6. Service.py wiring (source-text guard)
# ─────────────────────────────────────────────────────────────────

def test_service_imports_banking_cohort_helpers():
    src = _read(SERVICE_PATH)
    for name in (
        "is_banking_cohort_ticker",
        "banking_pb_anchor",
        "banking_pb_band",
        "banking_roe_quality_boost",
        "banking_stress_flag",
    ):
        assert name in src, (
            f"service.py must reference {name} (Day-109a banking overlay)"
        )


def test_service_banking_cohort_layered_on_existing_pb_path():
    """The Day-109a overlay must layer on top of the existing PB-ratio
    skip path — NOT replace it. The overlay block must appear AFTER
    the financial_valuation_service call (Day-76 path) so the existing
    TOP_PRIVATE_BANK_PB_BUMP and peer-median runs first."""
    src = _read(SERVICE_PATH)
    fv_call = src.find("compute_financial_fair_value(")
    cohort_overlay = src.find("Day-109a")
    assert fv_call > 0, "compute_financial_fair_value call must exist"
    assert cohort_overlay > 0, "Day-109a banking overlay must be wired"
    assert cohort_overlay > fv_call, (
        "Day-109a banking cohort overlay must run AFTER the existing "
        "Day-76 PB-ratio path (additive nuance, not replacement)."
    )


def test_pre_existing_top_private_bank_path_preserved():
    src = _read(SERVICE_PATH)
    # Day-76 / PR-BANKSC top-private-bank COE compression must still
    # be live — it's the PB-ratio engine fallback for banks not in
    # the Day-109a cohort (or with no BVPS).
    assert "is_top_private_bank" in src
    assert "TOP_PRIVATE_BANK_COE" in src


# ─────────────────────────────────────────────────────────────────
# 7. Cache invalidation manifest entry
# ─────────────────────────────────────────────────────────────────

def test_manifest_has_day109a_entry():
    src = _read(MANIFEST_PATH)
    assert "v_day109a_banking_cohort_2026_05_23" in src
    # Spec'd applied_at: 2026-05-23 20:00 UTC (no collision with Day-107).
    assert "datetime(2026, 5, 23, 20, 0, 0, tzinfo=timezone.utc)" in src


def test_manifest_entry_scope_lists_all_11_tickers():
    from backend.services.cache_invalidation_manifest import MANIFEST
    entry = next(
        (m for m in MANIFEST
         if m["version_id"] == "v_day109a_banking_cohort_2026_05_23"),
        None,
    )
    assert entry is not None, (
        "Day-109a manifest entry must be appended to MANIFEST"
    )
    scope_tickers = set(entry["scope"]["tickers"])
    expected = {
        "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN",
        "INDUSINDBK", "FEDERALBNK", "IDFCFIRSTB", "AUBANK",
        "BANDHANBNK", "RBLBANK",
    }
    assert scope_tickers == expected, (
        f"Scope mismatch: missing={expected - scope_tickers}, "
        f"extra={scope_tickers - expected}"
    )


def test_manifest_applied_at_no_collision_with_day107_family():
    from backend.services.cache_invalidation_manifest import MANIFEST
    target = datetime(2026, 5, 23, 20, 0, 0, tzinfo=timezone.utc)
    entry = next(
        (m for m in MANIFEST if m["applied_at"] == target),
        None,
    )
    assert entry is not None
    assert entry["version_id"] == "v_day109a_banking_cohort_2026_05_23"


# ─────────────────────────────────────────────────────────────────
# 8. No CACHE_VERSION bump
# ─────────────────────────────────────────────────────────────────

def test_no_cache_version_bump():
    src = _read(CACHE_PATH)
    # Pre-Day-109a CACHE_VERSION (Day-92 utility-bear-floor) was 135.
    # The spec is explicit: Day-109a ships WITHOUT bumping CACHE_VERSION.
    m = re.search(r"CACHE_VERSION\s*=\s*(\d+)", src)
    assert m is not None, "CACHE_VERSION must exist in cache_service.py"
    assert int(m.group(1)) == 135, (
        f"CACHE_VERSION must NOT be bumped for Day-109a (still 135), "
        f"found {m.group(1)}"
    )
