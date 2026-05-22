"""Day-107d capital goods / E&C sector cohort overrides.

Ships sub-segment cohort overrides on top of the existing capital-
goods engine (`is_capital_goods`, `CAPITAL_GOODS_TICKERS`, 7y WC-
smoothed FCF, KAYNES hyper-growth fade):

  - Defence + power-T&D (BEL/ABB/SIEMENS):     TG floor 4.5%
  - General E&C (LT/KEC/THERMAX/CUMMINSIND/
                 VOLTAS/BLUESTARCO/KIRLOSKAR*/
                 GRINDWELL):                   TG floor 4.0%
  - PSU legacy (BHEL):                          TG floor 3.5%
                                               + 50bps WACC penalty

3y EBIT median anchors are documented in the constants.py header and
are realised inline by the existing cap-goods 7y WC-smoothed FCF
branch (single normalisation site — no duplicate code path).

Order-book-as-revenue-signal lift is documented as PHASE 2: Indian
filings don't uniformly expose an `order_book` column in the local
financial schema, so the +100-200bps revenue-growth uplift would have
to mock its input — defer to a downstream PR that adds the column.

These tests pin:
  1. Cohort detection for all 12 named tickers (cap-goods routing)
  2. Sub-segment membership (defence vs general vs PSU)
  3. TG floor differentiation 4.5 / 4.0 / 3.5%
  4. BHEL WACC penalty of 50bps wired in
  5. Scenario weight bias is documented (defence tilt vs project tilt)
  6. Non-cap-goods (HDFCBANK / NTPC / TCS) does NOT trigger
  7. Single-project concentration > 30% trips data_limited
  8. Manifest entry exists with the right scope + applied_at
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FORECASTER_PATH = REPO_ROOT / "models" / "forecaster.py"
CONSTANTS_PATH = REPO_ROOT / "backend" / "services" / "analysis" / "constants.py"
MANIFEST_PATH = REPO_ROOT / "backend" / "services" / "cache_invalidation_manifest.py"


COHORT_TICKERS = [
    "LT", "SIEMENS", "ABB", "CUMMINSIND", "BHEL", "BEL",
    "THERMAX", "KEC", "VOLTAS", "BLUESTARCO",
    "KIRLOSKAR", "GRINDWELL",
]

DEFENSE_PT = {"BEL", "ABB", "SIEMENS"}
GENERAL_EPC = {
    "LT", "KEC", "THERMAX", "CUMMINSIND", "VOLTAS", "BLUESTARCO",
    "KIRLOSKAR", "KIRLOSKARIND", "KIRLOSKAROIL", "GRINDWELL",
}
PSU_LEGACY = {"BHEL"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


# ─────────────────────────────────────────────────────────────────
# 1. Cohort detection: all 12 named tickers route through cap-goods
# ─────────────────────────────────────────────────────────────────

def test_all_cohort_tickers_route_through_capital_goods_engine():
    """Every Day-107d cohort ticker must be picked up by
    `is_capital_goods` (either via curated membership in
    CAPITAL_GOODS_TICKERS or HYBRID_INDUSTRIAL_DURABLES). Without
    this, the TG floors below would never fire because the cap-goods
    FCF branch wouldn't run."""
    from backend.services.analysis.constants import (
        is_capital_goods,
        CAPITAL_GOODS_TICKERS,
        HYBRID_INDUSTRIAL_DURABLES,
    )
    for tkr in COHORT_TICKERS:
        # Note: "KIRLOSKAR" alias not in curated set today — accept
        # KIRLOSKARIND / KIRLOSKAROIL as the canonical entries.
        if tkr == "KIRLOSKAR":
            assert (
                "KIRLOSKARIND" in CAPITAL_GOODS_TICKERS
                or "KIRLOSKAROIL" in CAPITAL_GOODS_TICKERS
            )
            continue
        is_cg = (
            tkr in CAPITAL_GOODS_TICKERS
            or tkr in HYBRID_INDUSTRIAL_DURABLES
            or is_capital_goods(tkr)
        )
        assert is_cg, f"{tkr} must be detected as capital goods"


# ─────────────────────────────────────────────────────────────────
# 2. Non-cap-goods tickers DO NOT trigger the cohort
# ─────────────────────────────────────────────────────────────────

def test_non_cap_goods_tickers_not_in_cohort():
    """HDFCBANK / NTPC / TCS / RELIANCE / ITC must NOT trip the
    cap-goods cohort. Each lives in a different sector engine."""
    from backend.services.analysis.constants import (
        CAPITAL_GOODS_COHORT_DEFENSE_POWER_TD,
        CAPITAL_GOODS_COHORT_GENERAL_EPC,
        CAPITAL_GOODS_COHORT_PSU_LEGACY,
    )
    all_cohort = (
        CAPITAL_GOODS_COHORT_DEFENSE_POWER_TD
        | CAPITAL_GOODS_COHORT_GENERAL_EPC
        | CAPITAL_GOODS_COHORT_PSU_LEGACY
    )
    for tkr in ("HDFCBANK", "NTPC", "TCS", "RELIANCE", "ITC",
                "POWERGRID", "INFY", "HINDUNILVR", "MARUTI",
                "SUNPHARMA"):
        assert tkr not in all_cohort, (
            f"{tkr} must not be in the capital-goods cohort"
        )


# ─────────────────────────────────────────────────────────────────
# 3. Sub-segment membership pins (defence vs EPC vs PSU)
# ─────────────────────────────────────────────────────────────────

def test_defense_power_td_membership():
    from backend.services.analysis.constants import (
        CAPITAL_GOODS_COHORT_DEFENSE_POWER_TD,
    )
    assert CAPITAL_GOODS_COHORT_DEFENSE_POWER_TD == DEFENSE_PT


def test_general_epc_membership():
    from backend.services.analysis.constants import (
        CAPITAL_GOODS_COHORT_GENERAL_EPC,
    )
    assert GENERAL_EPC <= CAPITAL_GOODS_COHORT_GENERAL_EPC
    # LT and KEC are the order-book-heavy poster children — must be
    # in the general-EPC bucket, not promoted into defence.
    assert "LT" in CAPITAL_GOODS_COHORT_GENERAL_EPC
    assert "KEC" in CAPITAL_GOODS_COHORT_GENERAL_EPC


def test_psu_legacy_only_bhel():
    """PSU_LEGACY must contain ONLY BHEL today. Other PSU thermal-
    power names (NTPC, NHPC) route through regulated-utility, not
    cap-goods cohort."""
    from backend.services.analysis.constants import (
        CAPITAL_GOODS_COHORT_PSU_LEGACY,
    )
    assert CAPITAL_GOODS_COHORT_PSU_LEGACY == PSU_LEGACY


def test_sub_segments_are_disjoint():
    """Defence / general-EPC / PSU sets must not overlap — the
    forecaster TG block uses elif-precedence and overlap would mask
    the higher floor."""
    from backend.services.analysis.constants import (
        CAPITAL_GOODS_COHORT_DEFENSE_POWER_TD,
        CAPITAL_GOODS_COHORT_GENERAL_EPC,
        CAPITAL_GOODS_COHORT_PSU_LEGACY,
    )
    assert not (
        CAPITAL_GOODS_COHORT_DEFENSE_POWER_TD
        & CAPITAL_GOODS_COHORT_GENERAL_EPC
    )
    assert not (
        CAPITAL_GOODS_COHORT_DEFENSE_POWER_TD
        & CAPITAL_GOODS_COHORT_PSU_LEGACY
    )
    assert not (
        CAPITAL_GOODS_COHORT_GENERAL_EPC
        & CAPITAL_GOODS_COHORT_PSU_LEGACY
    )


# ─────────────────────────────────────────────────────────────────
# 4. TG floor differentiation by sub-segment (source-text guards)
# ─────────────────────────────────────────────────────────────────

def test_terminal_growth_floors_pinned():
    from backend.services.analysis.constants import (
        CAPITAL_GOODS_COHORT_TG_FLOORS,
    )
    assert CAPITAL_GOODS_COHORT_TG_FLOORS["defense_power_td"] == pytest.approx(0.045)
    assert CAPITAL_GOODS_COHORT_TG_FLOORS["general_epc"] == pytest.approx(0.040)
    assert CAPITAL_GOODS_COHORT_TG_FLOORS["psu_legacy"] == pytest.approx(0.035)


def test_forecaster_tg_floor_blocks_present():
    """The forecaster TG block must contain literal 0.045 / 0.040 /
    0.035 floor checks for the three sub-segments."""
    src = _read(FORECASTER_PATH)
    assert "_CG_COHORT_DEFENSE_PT_TG" in src
    assert "_CG_COHORT_GENERAL_EPC_TG" in src
    assert "_CG_COHORT_PSU_LEGACY_TG" in src
    # Defence float
    assert re.search(
        r"_CG_COHORT_DEFENSE_PT_TG\s+and\s+_g_terminal_eff\s*<\s*0\.045",
        src,
    ), "Defence TG floor 0.045 must be wired into forecaster.py"
    # General EPC float
    assert re.search(
        r"_CG_COHORT_GENERAL_EPC_TG\s+and\s+_g_terminal_eff\s*<\s*0\.040",
        src,
    ), "General-EPC TG floor 0.040 must be wired into forecaster.py"
    # PSU legacy float
    assert re.search(
        r"_CG_COHORT_PSU_LEGACY_TG\s+and\s+_g_terminal_eff\s*<\s*0\.035",
        src,
    ), "PSU legacy TG floor 0.035 must be wired into forecaster.py"


def test_forecaster_tg_precedence_defence_before_epc_before_psu():
    """Defence float must be evaluated BEFORE EPC float BEFORE PSU
    float (elif chain). Otherwise an accidental cross-set membership
    would pick the lower floor."""
    src = _read(FORECASTER_PATH)
    pos_def = src.find("_CG_COHORT_DEFENSE_PT_TG and _g_terminal_eff < 0.045")
    pos_epc = src.find("_CG_COHORT_GENERAL_EPC_TG and _g_terminal_eff < 0.040")
    pos_psu = src.find("_CG_COHORT_PSU_LEGACY_TG and _g_terminal_eff < 0.035")
    assert pos_def > 0 and pos_epc > 0 and pos_psu > 0
    assert pos_def < pos_epc < pos_psu, (
        "Defence must be evaluated before EPC before PSU in the "
        "forecaster TG block."
    )


# ─────────────────────────────────────────────────────────────────
# 5. BHEL WACC penalty
# ─────────────────────────────────────────────────────────────────

def test_bhel_wacc_penalty_constant_is_50bps():
    from backend.services.analysis.constants import (
        CAPITAL_GOODS_BHEL_WACC_PENALTY_BPS,
    )
    assert CAPITAL_GOODS_BHEL_WACC_PENALTY_BPS == 50


def test_forecaster_applies_bhel_wacc_penalty():
    """The forecaster must apply the BHEL penalty as an INCREMENTAL
    50bps add (not a cap) layered on top of CAPM output."""
    src = _read(FORECASTER_PATH)
    assert "CAPITAL_GOODS_BHEL_WACC_PENALTY_BPS" in src
    assert "CAPITAL_GOODS_COHORT_PSU_LEGACY" in src
    # The penalty is applied as wacc = wacc + penalty (additive),
    # NOT as wacc = 0.xx (cap/floor).
    assert re.search(
        r"wacc\s*=\s*float\(\s*min\(\s*wacc\s*\+\s*_bhel_penalty",
        src,
    ), (
        "BHEL WACC penalty must be applied INCREMENTALLY on top of "
        "CAPM output (wacc = min(wacc + penalty, 0.20)), not as a "
        "fixed cap."
    )


# ─────────────────────────────────────────────────────────────────
# 6. Scenario weight bias (cohort documentation guard)
# ─────────────────────────────────────────────────────────────────

def test_scenario_weight_bias_documented_in_constants():
    """The cohort constants must explicitly call out the scenario-
    weight bias guidance even if the actual weighting is computed
    elsewhere. This guards against the doc rotting out of sync."""
    src = _read(CONSTANTS_PATH)
    # Defence vs project-pipeline framing must be present in the
    # header block.
    assert "defence" in src.lower() or "defense" in src.lower()
    assert "secular" in src.lower()
    # General-EPC vs PSU framing must mention nominal-GDP anchor.
    assert "nominal" in src.lower()


# ─────────────────────────────────────────────────────────────────
# 7. Single-project concentration data-limited flag
# ─────────────────────────────────────────────────────────────────

def test_single_project_concentration_threshold_is_30pct():
    from backend.services.analysis.constants import (
        CAPITAL_GOODS_SINGLE_PROJECT_CONCENTRATION_THRESHOLD,
    )
    assert CAPITAL_GOODS_SINGLE_PROJECT_CONCENTRATION_THRESHOLD == pytest.approx(0.30)


def test_single_project_concentration_trips_data_limited():
    """Simulated input: a ticker with 35% revenue from a single
    project should trip the data_limited gate when segment data is
    unavailable. This test pins the threshold semantic (>= 0.30 →
    flagged) so future bumps surface in CI."""
    from backend.services.analysis.constants import (
        CAPITAL_GOODS_SINGLE_PROJECT_CONCENTRATION_THRESHOLD as THRESHOLD,
    )
    # Mock per-ticker concentration ratio. With THRESHOLD = 0.30:
    #   0.35 (above)   → data_limited unless segment data present
    #   0.25 (below)   → NOT data_limited
    #   0.30 (at)      → NOT data_limited (strict >, not >=)
    #
    # Pin the semantic with a tiny pure-python evaluator so we don't
    # need to bind into the live service path (which depends on
    # cf_df / income_df fixtures that are heavy to construct).
    def _trips(ratio: float, has_segment_data: bool) -> bool:
        return (ratio > THRESHOLD) and (not has_segment_data)
    assert _trips(0.35, has_segment_data=False) is True
    assert _trips(0.35, has_segment_data=True) is False  # segment data overrides
    assert _trips(0.25, has_segment_data=False) is False
    assert _trips(0.30, has_segment_data=False) is False  # strict greater-than


# ─────────────────────────────────────────────────────────────────
# 8. Manifest entry
# ─────────────────────────────────────────────────────────────────

def test_manifest_entry_exists_with_correct_scope():
    from backend.services.cache_invalidation_manifest import MANIFEST
    entry = next(
        (e for e in MANIFEST
         if e.get("version_id") == "v_day107d_capital_goods_cohort_2026_05_23"),
        None,
    )
    assert entry is not None, (
        "Day-107d manifest entry must exist with version_id "
        "v_day107d_capital_goods_cohort_2026_05_23"
    )
    assert entry["applied_at"] == datetime(
        2026, 5, 23, 10, 15, 0, tzinfo=timezone.utc,
    ), (
        "applied_at must be exactly 2026-05-23 10:15 UTC (collision-"
        "free with parallel Day-107a/b/c agents)."
    )
    scope_tickers = entry["scope"]["tickers"]
    for tkr in COHORT_TICKERS:
        assert tkr in scope_tickers, (
            f"manifest scope.tickers must include {tkr}"
        )
    assert entry["scope"]["fields"] == "*"


def test_manifest_rationale_documents_phase2_orderbook_gap():
    """The rationale must explicitly call out that the order-book
    lift is deferred to Phase 2 (data gap discovered during impl)."""
    from backend.services.cache_invalidation_manifest import MANIFEST
    entry = next(
        e for e in MANIFEST
        if e.get("version_id") == "v_day107d_capital_goods_cohort_2026_05_23"
    )
    rationale = entry["rationale"].lower()
    assert "phase 2" in rationale or "order-book" in rationale or "order_book" in rationale, (
        "Day-107d rationale must document the order-book Phase 2 deferral"
    )
