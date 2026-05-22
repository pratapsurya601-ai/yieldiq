"""Day-107b (2026-05-23) — FMCG sector cohort overrides.

Mirrors the Day-84 pharma-franchise cohort test layout (source-text
guards + math/membership guards + non-cohort negative cases). The
overrides ship four coordinated levers for the Indian FMCG large-cap
franchise tickers (HUL / NESTLEIND / ITC / BRITANNIA / DABUR /
MARICO / COLPAL / GODREJCP / EMAMILTD / TATACONSUM / VBL):

  1. Terminal-growth tier lift (5.0% / 4.5% / 4.5% / 4.0%) reflecting
     India's nominal household-consumption baseline.
  2. WACC floor of 8.5% — these balance sheets are net-cash with
     beta 0.5-0.7 and CAPM systematically over-charges them.
  3. Moat-pillar floor of 75/100 for the top-4 franchise leaders
     (HUL / NESTLE / ITC / BRITANNIA) — 20%+ category share + 40+
     year distribution moats deserve a higher floor than the broader
     STRONG_BRAND_ALLOWLIST (which floors at 70).
  4. Slightly bullish scenario weights (40/40/20) for the top-4 —
     they compound through downturns and the default symmetric
     30/50/20 weighting is too bearish.

ITC carries a cigarette tail-risk discount (TG 4.5% not 5.0%) but
keeps the 8.5% WACC floor and the moat / scenario lifts — the
audit's `_FMCG_ITC_SPECIAL` block isolates this so future tail-risk
changes (e.g. WHO regulation, India excise duty) can be applied
without touching the other top-3.

These tests pin:
  - Cohort detection for the 11 named tickers (any tier)
  - Tier classification (top / ITC-special / tier-2 / tier-3)
  - Non-FMCG tickers (NTPC / TCS / RELIANCE / MANKIND) NOT in cohort
  - TG lift wired into service.py at the right precedence
  - WACC floor wired into service.py at the right precedence
  - Moat floor wired into screener/moat_engine.py
  - Cache invalidation manifest entry exists with the spec'd
    version_id and applied_at timestamp
  - No CACHE_VERSION bump (the spec is explicit about this)
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
MOAT_ENGINE_PATH = REPO_ROOT / "screener" / "moat_engine.py"
MANIFEST_PATH = (
    REPO_ROOT / "backend" / "services" / "cache_invalidation_manifest.py"
)
CACHE_PATH = REPO_ROOT / "backend" / "services" / "cache_service.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


# ─────────────────────────────────────────────────────────────────
# 1. Module exists and exports the right names
# ─────────────────────────────────────────────────────────────────

def test_sector_overrides_module_exists():
    assert SECTOR_OVERRIDES_PATH.exists(), (
        "backend/services/analysis/sector_overrides.py must exist as "
        "the single source of truth for Day-107b FMCG cohort "
        "membership and override magnitudes."
    )


def test_sector_overrides_exports_public_helpers():
    from backend.services.analysis import sector_overrides as so
    for name in (
        "is_fmcg_cohort_ticker", "is_fmcg_top_franchise",
        "fmcg_terminal_growth", "fmcg_wacc_floor",
        "fmcg_moat_floor", "fmcg_scenario_weights",
        "FMCG_TG_TOP", "FMCG_TG_ITC", "FMCG_TG_TIER2", "FMCG_TG_TIER3",
        "FMCG_WACC_FLOOR", "FMCG_TOP_MOAT_FLOOR",
        "FMCG_TOP_SCENARIO_WEIGHTS",
    ):
        assert hasattr(so, name), f"sector_overrides missing {name!r}"


# ─────────────────────────────────────────────────────────────────
# 2. Cohort detection for the 11 named tickers
# ─────────────────────────────────────────────────────────────────

EXPECTED_COHORT = {
    "HINDUNILVR", "NESTLEIND", "ITC", "BRITANNIA", "DABUR",
    "MARICO", "COLPAL", "GODREJCP", "EMAMILTD", "TATACONSUM", "VBL",
}


def test_all_eleven_named_tickers_classify_into_cohort():
    from backend.services.analysis.sector_overrides import (
        is_fmcg_cohort_ticker,
    )
    for bare in EXPECTED_COHORT:
        assert is_fmcg_cohort_ticker(bare), f"{bare} should be in cohort"
        assert is_fmcg_cohort_ticker(f"{bare}.NS"), (
            f"{bare}.NS (NSE-suffixed) must also classify"
        )
        assert is_fmcg_cohort_ticker(f"{bare}.BO"), (
            f"{bare}.BO (BSE-suffixed) must also classify"
        )


def test_top_franchise_membership_is_top_4():
    """HUL / NESTLE / ITC / BRITANNIA are the top-4 by category share
    + distribution moat. They alone get the moat-pillar floor + the
    bullish scenario weighting."""
    from backend.services.analysis.sector_overrides import (
        is_fmcg_top_franchise,
    )
    for t in ("HINDUNILVR", "NESTLEIND", "ITC", "BRITANNIA"):
        assert is_fmcg_top_franchise(t), f"{t} must be top-4"
    for t in ("DABUR", "MARICO", "COLPAL", "GODREJCP",
              "EMAMILTD", "TATACONSUM", "VBL"):
        assert not is_fmcg_top_franchise(t), (
            f"{t} is tier-2/3, must NOT be top-4"
        )


# ─────────────────────────────────────────────────────────────────
# 3. Non-FMCG tickers do NOT trigger FMCG overrides
# ─────────────────────────────────────────────────────────────────

def test_non_fmcg_tickers_not_in_cohort():
    from backend.services.analysis.sector_overrides import (
        is_fmcg_cohort_ticker, is_fmcg_top_franchise,
        fmcg_terminal_growth, fmcg_wacc_floor, fmcg_moat_floor,
        fmcg_scenario_weights,
    )
    for t in (
        "NTPC", "TCS", "RELIANCE", "HDFCBANK", "INFY",
        "MANKIND", "SUNPHARMA", "MAXHEALTH", "DIVISLAB",
        "POWERGRID", "ASIANPAINT", "PIDILITIND", "GILLETTE",
    ):
        assert not is_fmcg_cohort_ticker(t), (
            f"{t} must NOT classify into the FMCG cohort — that "
            f"would silently apply TG lift + WACC tighten to a "
            f"non-FMCG name."
        )
        assert not is_fmcg_top_franchise(t)
        assert fmcg_terminal_growth(t) is None
        assert fmcg_wacc_floor(t) is None
        assert fmcg_moat_floor(t) is None
        assert fmcg_scenario_weights(t) is None
    # Edge cases: None / empty
    assert not is_fmcg_cohort_ticker(None)
    assert not is_fmcg_cohort_ticker("")


# ─────────────────────────────────────────────────────────────────
# 4. TG lift + WACC tighten applied correctly per tier
# ─────────────────────────────────────────────────────────────────

def test_top_tier_tg_is_50bps_above_default():
    from backend.services.analysis.sector_overrides import (
        fmcg_terminal_growth, FMCG_TG_TOP,
    )
    assert FMCG_TG_TOP == pytest.approx(0.050)
    for t in ("HINDUNILVR", "NESTLEIND", "BRITANNIA"):
        assert fmcg_terminal_growth(t) == pytest.approx(0.050), (
            f"{t} TG target must be 5.0% (top tier)"
        )


def test_itc_tg_is_45bps_cigarette_tail_risk_discount():
    """ITC is top-4 by share but cigarette tail risk justifies a
    TG between top (5.0%) and tier-2 (4.5%) — landing at 4.5%."""
    from backend.services.analysis.sector_overrides import (
        fmcg_terminal_growth, FMCG_TG_ITC, FMCG_TG_TOP,
    )
    assert FMCG_TG_ITC == pytest.approx(0.045)
    assert FMCG_TG_ITC < FMCG_TG_TOP, (
        "ITC TG must be STRICTLY below the top-tier TG — the "
        "cigarette tail risk discount is the whole point of "
        "separating ITC from HUL/NESTLE/BRITANNIA."
    )
    assert fmcg_terminal_growth("ITC") == pytest.approx(0.045)


def test_tier2_tg_is_45bps():
    from backend.services.analysis.sector_overrides import (
        fmcg_terminal_growth,
    )
    for t in ("DABUR", "MARICO", "COLPAL", "GODREJCP"):
        assert fmcg_terminal_growth(t) == pytest.approx(0.045), (
            f"{t} tier-2 TG must be 4.5%"
        )


def test_tier3_tg_at_default():
    from backend.services.analysis.sector_overrides import (
        fmcg_terminal_growth,
    )
    for t in ("EMAMILTD", "TATACONSUM", "VBL"):
        assert fmcg_terminal_growth(t) == pytest.approx(0.040), (
            f"{t} tier-3 TG must be 4.0% (no lift vs country default)"
        )


def test_wacc_floor_applies_to_all_eleven_at_85bps():
    from backend.services.analysis.sector_overrides import (
        fmcg_wacc_floor, FMCG_WACC_FLOOR,
    )
    assert FMCG_WACC_FLOOR == pytest.approx(0.085)
    for t in EXPECTED_COHORT:
        assert fmcg_wacc_floor(t) == pytest.approx(0.085), (
            f"{t} must receive the 8.5% WACC floor"
        )


# ─────────────────────────────────────────────────────────────────
# 5. Moat pillar boost on top-4 names
# ─────────────────────────────────────────────────────────────────

def test_moat_pillar_floor_75_for_top_4_only():
    from backend.services.analysis.sector_overrides import (
        fmcg_moat_floor, FMCG_TOP_MOAT_FLOOR,
    )
    assert FMCG_TOP_MOAT_FLOOR == 75
    for t in ("HINDUNILVR", "NESTLEIND", "ITC", "BRITANNIA"):
        assert fmcg_moat_floor(t) == 75
    for t in ("DABUR", "MARICO", "VBL", "EMAMILTD"):
        assert fmcg_moat_floor(t) is None, (
            f"{t} must NOT receive the top-4 moat floor — the "
            f"75-point floor is reserved for the narrow top-4 set."
        )


def test_moat_floor_above_allowlist_floor():
    """The Day-107b FMCG moat floor (75) must be STRICTLY above the
    existing ALLOWLIST_MOAT_FLOOR_SCORE (70). The allowlist captures
    bellwethers across all sectors; the FMCG floor is reserved for
    the narrower top-4 franchise leaders whose distribution moats
    are structurally stronger."""
    from screener.moat_engine import ALLOWLIST_MOAT_FLOOR_SCORE
    from backend.services.analysis.sector_overrides import (
        FMCG_TOP_MOAT_FLOOR,
    )
    assert FMCG_TOP_MOAT_FLOOR > ALLOWLIST_MOAT_FLOOR_SCORE, (
        f"FMCG top-franchise moat floor ({FMCG_TOP_MOAT_FLOOR}) must "
        f"be > allowlist floor ({ALLOWLIST_MOAT_FLOOR_SCORE})."
    )


def test_moat_engine_wires_fmcg_floor():
    """Source-text guard: screener/moat_engine.py must import and
    apply the Day-107b FMCG floor AFTER the allowlist floor (so the
    higher floor wins) and BEFORE moat-types detection (so the
    grade is final by the time moat-types are computed)."""
    src = _read(MOAT_ENGINE_PATH)
    assert "fmcg_moat_floor" in src
    assert "Day-107b" in src or "day107b" in src.lower()
    allow_pos = src.find("Allowlist floor applied")
    fmcg_pos = src.find("Day-107b FMCG top-franchise moat floor")
    moat_types_pos = src.find("# ── Moat types")
    assert allow_pos > 0 and fmcg_pos > 0 and moat_types_pos > 0
    assert allow_pos < fmcg_pos < moat_types_pos, (
        "moat_engine.py must order: allowlist floor → FMCG floor → "
        "moat-types detection. Otherwise the FMCG floor either "
        "double-applies under the allowlist (wrong band) or runs "
        "after moat-types are detected against a stale grade."
    )


# ─────────────────────────────────────────────────────────────────
# 6. Scenario re-weight applied to top-4 only
# ─────────────────────────────────────────────────────────────────

def test_scenario_weights_for_top_4_are_40_40_20():
    from backend.services.analysis.sector_overrides import (
        fmcg_scenario_weights, FMCG_TOP_SCENARIO_WEIGHTS,
    )
    bull, base, bear = FMCG_TOP_SCENARIO_WEIGHTS
    assert bull == pytest.approx(0.40)
    assert base == pytest.approx(0.40)
    assert bear == pytest.approx(0.20)
    assert bull + base + bear == pytest.approx(1.0)
    for t in ("HINDUNILVR", "NESTLEIND", "ITC", "BRITANNIA"):
        w = fmcg_scenario_weights(t)
        assert w == (0.40, 0.40, 0.20), (
            f"{t} top-4 scenario weights must be 40/40/20 "
            f"(slightly bullish skew for franchise leaders)"
        )


def test_scenario_weights_none_for_non_top_4():
    from backend.services.analysis.sector_overrides import (
        fmcg_scenario_weights,
    )
    for t in ("DABUR", "MARICO", "COLPAL", "GODREJCP",
              "EMAMILTD", "TATACONSUM", "VBL"):
        assert fmcg_scenario_weights(t) is None, (
            f"{t} must use the default scenario weights — the "
            f"bullish 40/40/20 skew is reserved for the narrow "
            f"top-4 franchise leaders."
        )


# ─────────────────────────────────────────────────────────────────
# 7. Service.py wiring — source-text guards
# ─────────────────────────────────────────────────────────────────

def test_service_wires_fmcg_tg_lift_after_pharma_cdmo():
    """The FMCG TG lift must come AFTER the Day-84 pharma-franchise +
    Day-21 pharma-CDMO branches, so the pharma-specific cohorts
    (which use the same kind of TG mechanic) are evaluated first
    and FMCG only fires for genuine FMCG tickers."""
    src = _read(SERVICE_PATH)
    cdmo_pos = src.find("[pharma-cdmo-tg-lifted]")
    fmcg_pos = src.find("[fmcg-cohort-tg-lifted]")
    assert cdmo_pos > 0, "Day-21 pharma-CDMO TG branch must exist"
    assert fmcg_pos > 0, "Day-107b FMCG TG branch must exist"
    assert cdmo_pos < fmcg_pos, (
        "service.py must evaluate pharma-CDMO TG BEFORE FMCG TG so "
        "the pharma-specific cohorts get their dedicated branches "
        "and FMCG is the catch-all for the named FMCG tickers."
    )


def test_service_wires_fmcg_wacc_floor():
    src = _read(SERVICE_PATH)
    assert "Day-107b" in src
    assert "fmcg_cohort_wacc_floor_applied" in src
    assert "fmcg_wacc_floor" in src


def test_fmcg_wacc_floor_runs_before_tg_block():
    """The WACC tighten must run BEFORE the TG lift block, because
    the TG-lift safety guard is ``terminal_g < wacc - 0.02``. If
    WACC is still at 0.105 when TG branches evaluate, the 5.0% lift
    is fine; but if a future change lowers TG further, ordering
    matters. Pin the order so future edits don't quietly re-order."""
    src = _read(SERVICE_PATH)
    wacc_block = src.find("fmcg_cohort_wacc_floor_applied")
    tg_block = src.find("[fmcg-cohort-tg-lifted]")
    assert wacc_block > 0 and tg_block > 0
    assert wacc_block < tg_block, (
        "FMCG WACC floor must run BEFORE the FMCG TG lift so the "
        "``terminal_g < wacc - 0.02`` safety guard uses the "
        "tightened WACC."
    )


# ─────────────────────────────────────────────────────────────────
# 8. Cache invalidation manifest entry
# ─────────────────────────────────────────────────────────────────

def test_manifest_entry_for_day107b_exists():
    """Engine-output change for 11 tickers — scoped manifest entry
    is mandatory per Day-94 invalidation discipline. No global
    CACHE_VERSION bump (per Day-107b spec)."""
    from backend.services.cache_invalidation_manifest import MANIFEST
    matches = [
        e for e in MANIFEST
        if e.get("version_id") == "v_day107b_fmcg_cohort_2026_05_23"
    ]
    assert len(matches) == 1, (
        f"Expected exactly one Day-107b manifest entry; got "
        f"{len(matches)}."
    )
    entry = matches[0]
    # Timestamp must match the spec exactly so parallel Day-107
    # agents don't collide.
    assert entry["applied_at"] == datetime(
        2026, 5, 23, 10, 5, 0, tzinfo=timezone.utc,
    )
    # Scope must list the 11 named tickers.
    scoped = set(entry["scope"]["tickers"])
    expected_scope = {
        "HUL", "NESTLEIND", "ITC", "BRITANNIA", "DABUR",
        "MARICO", "COLPAL", "GODREJCP", "EMAMI",
        "TATACONSUM", "VBL",
    }
    assert scoped == expected_scope, (
        f"Manifest scope drifted: got {scoped}, expected "
        f"{expected_scope}."
    )
    assert entry["scope"]["fields"] == "*"


def test_cache_version_NOT_bumped_by_day107b():
    """Day-107b explicitly does NOT bump CACHE_VERSION (per spec).
    The scoped manifest entry is the invalidation mechanism. Guard
    against a future regression that bumps the integer anyway."""
    src = _read(CACHE_PATH)
    m = re.search(r"^CACHE_VERSION\s*=\s*(\d+)\s*#\s*(\d+):", src, re.M)
    assert m is not None, "CACHE_VERSION header must exist"
    cv = int(m.group(1))
    # Day-92 landed CACHE_VERSION=135. Day-107b must NOT bump.
    assert cv == 135, (
        f"CACHE_VERSION drifted to {cv}; Day-107b spec is explicit "
        f"that no global bump is permitted (scoped manifest only)."
    )
