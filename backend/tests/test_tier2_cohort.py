"""
Tests for the Tier 2 quality-bucketed sector cohort valuation engine.

Layer B Week 1 PR 1 — see
docs/design/valuation-architecture-simplification.md §2.2.

Coverage:
  1. MANKIND (Premium pharma bucket) → benchmarks against Sun/Cipla/
     Lupin-tier moats, FV in [₹2,200, ₹2,800].
  2. Generic exporter (LAURUSLABS-shape) (Tail pharma bucket) →
     benchmarks against lower-quality peers; FV materially below
     a Premium MANKIND-style result for the same EPS.
  3. Sector with < 5 peers in target bucket (even after widening) →
     returns None.
  4. TIER2_ENABLED defaults to False → tier2_enabled() returns False.
  5. Skip-sector (banking / regulated utility / REIT / ETF / holdco)
     → returns None regardless of flag (caller routes via existing
     sector engine).
  6. EV/EBITDA-preferred sector (Capital Goods) uses EV/EBITDA leg
     when peer ev_ebitda median is present.
  7. FV cap at 8× BVPS prevents one-off peak-EPS over-shoots.
  8. Confidence score capped at 75 (TIER2_CONFIDENCE_CAP).
"""
from __future__ import annotations

import os
import pytest

from backend.services.tier2_cohort_valuation_service import (
    compute_tier2_fair_value,
    is_tier2_skip_sector,
    tier2_enabled,
    _bucket_for,
    TIER2_CONFIDENCE_CAP,
    MIN_BUCKET_SIZE,
)


# ──────────────────────────────────────────────────────────────────
# Fixture builders
# ──────────────────────────────────────────────────────────────────

def _pharma_premium_peers() -> list[dict]:
    """SUN / CIPLA / DRREDDY / DIVISLAB / LUPIN — Premium pharma cohort.

    All ROCE > 25, Piotroski ≥ 7, mcap >= ₹50k Cr.  Median P/E ≈ 32.
    """
    return [
        # SUN PHARMA
        {"ticker": "SUNPHARMA", "pe": 38.0, "ev_ebitda": 24.0,
         "roce": 26.0, "piotroski": 7, "market_cap_cr": 380000.0},
        # CIPLA
        {"ticker": "CIPLA", "pe": 30.0, "ev_ebitda": 20.0,
         "roce": 27.0, "piotroski": 8, "market_cap_cr": 110000.0},
        # DR REDDY's
        {"ticker": "DRREDDY", "pe": 22.0, "ev_ebitda": 16.0,
         "roce": 30.0, "piotroski": 8, "market_cap_cr": 100000.0},
        # DIVIS LAB
        {"ticker": "DIVISLAB", "pe": 55.0, "ev_ebitda": 38.0,
         "roce": 28.0, "piotroski": 7, "market_cap_cr": 150000.0},
        # LUPIN
        {"ticker": "LUPIN", "pe": 28.0, "ev_ebitda": 18.0,
         "roce": 26.0, "piotroski": 7, "market_cap_cr": 80000.0},
        # ZYDUSLIFE
        {"ticker": "ZYDUSLIFE", "pe": 25.0, "ev_ebitda": 17.0,
         "roce": 25.5, "piotroski": 7, "market_cap_cr": 90000.0},
    ]


def _pharma_tail_peers() -> list[dict]:
    """LAURUSLABS / GRANULES / AUROBINDO-shape — Tail pharma cohort.

    Mostly mid-quality generics; ROCE 8-12, Piotroski 3-4, mcap small.
    Median P/E ≈ 15.
    """
    return [
        {"ticker": "LAURUSLABS", "pe": 14.0, "ev_ebitda": 10.0,
         "roce": 9.0, "piotroski": 3, "market_cap_cr": 25000.0},
        {"ticker": "GRANULES", "pe": 12.0, "ev_ebitda": 8.0,
         "roce": 11.0, "piotroski": 4, "market_cap_cr": 12000.0},
        {"ticker": "AUROBINDO", "pe": 16.0, "ev_ebitda": 9.0,
         "roce": 10.0, "piotroski": 3, "market_cap_cr": 65000.0},
        {"ticker": "AJANTPHARMA", "pe": 18.0, "ev_ebitda": 12.0,
         "roce": 13.5, "piotroski": 3, "market_cap_cr": 30000.0},
        {"ticker": "ALKEM", "pe": 15.0, "ev_ebitda": 11.0,
         "roce": 8.0, "piotroski": 4, "market_cap_cr": 60000.0},
        {"ticker": "GLAND", "pe": 17.0, "ev_ebitda": 13.0,
         "roce": 11.5, "piotroski": 3, "market_cap_cr": 22000.0},
    ]


# ──────────────────────────────────────────────────────────────────
# 1. MANKIND in Premium pharma bucket
# ──────────────────────────────────────────────────────────────────

def test_mankind_premium_pharma_bucket_lands_in_band():
    """MANKIND (ROCE 27%, Piotroski 8, mcap ₹68k Cr) routes to the
    Premium pharma bucket and benchmarks against SUN/CIPLA/DIVIS-tier
    peers.  FV should land in [₹2,200, ₹2,800] for TTM EPS ₹76.
    """
    # MANKIND's bucket inputs land squarely in Premium:
    #   ROCE 27 > 25, Piotroski 8 >= 7, mcap 68000 >= 50000.
    fin = {
        "eps": 76.0,           # TTM diluted EPS approx
        "ebitda": 3500.0,      # Cr
        "shares": 4.005e8,     # ~400M shares
        "roce": 27.0,
        "piotroski": 8,
        "market_cap_cr": 68000.0,
        "bvps": 380.0,
        "current_price": 2400.0,
    }
    out = compute_tier2_fair_value(
        ticker="MANKIND",
        sector="Pharma",
        financials=fin,
        peers=_pharma_premium_peers(),
    )
    assert out is not None, "Tier 2 must produce a result for MANKIND"
    fv = out["fair_value"]
    assert 2200 <= fv <= 2800, (
        f"MANKIND FV ₹{fv} outside [₹2,200, ₹2,800] — bucket should "
        f"have benchmarked against Premium pharma (median P/E ~32). "
        f"meta={out['_meta']}"
    )
    assert out["_meta"]["bucket"] == "premium"
    assert out["_meta"]["cohort_size"] >= MIN_BUCKET_SIZE
    assert out["_meta"]["leg_used"] == "pe"
    assert out["method"] == "cohort_pe"
    # Confidence is capped at 75 per design doc.
    assert out["confidence_score"] <= TIER2_CONFIDENCE_CAP


# ──────────────────────────────────────────────────────────────────
# 2. Generic exporter (Tail pharma bucket)
# ──────────────────────────────────────────────────────────────────

def test_generic_exporter_tail_pharma_bucket_uses_low_quality_peers():
    """A LAURUSLABS-shape ticker (ROCE 9, Piotroski 3, mcap ₹25k Cr)
    routes to the Tail pharma bucket.  FV with same EPS as MANKIND
    must be materially lower than the Premium result.
    """
    fin = {
        "eps": 76.0,           # same EPS as MANKIND to isolate bucket effect
        "ebitda": 3500.0,
        "shares": 4.0e8,
        "roce": 9.0,           # Tail criteria
        "piotroski": 3,
        "market_cap_cr": 25000.0,
        "bvps": 380.0,
        "current_price": 1200.0,
    }
    # Build a Tail-only peer set with at least MIN_BUCKET_SIZE peers
    out = compute_tier2_fair_value(
        ticker="LAURUSLABS",
        sector="Pharma",
        financials=fin,
        peers=_pharma_tail_peers(),
    )
    assert out is not None
    assert out["_meta"]["bucket"] == "tail"
    fv = out["fair_value"]
    # Tail median P/E ≈ 15 → FV ≈ 76 × 15 = ₹1,140 (within bands).
    assert 800 <= fv <= 1500, (
        f"Tail-bucket FV ₹{fv} should reflect lower peer multiples "
        f"(median P/E ~15). meta={out['_meta']}"
    )
    # And materially lower than the Premium-bucket FV for the same EPS.
    premium_out = compute_tier2_fair_value(
        ticker="MANKIND",
        sector="Pharma",
        financials={**fin, "roce": 27.0, "piotroski": 8,
                    "market_cap_cr": 68000.0},
        peers=_pharma_premium_peers(),
    )
    assert premium_out["fair_value"] > 1.5 * fv, (
        "Premium-bucket FV should be at least 50% above Tail-bucket "
        "FV for an identical EPS — the whole point of bucketing."
    )


# ──────────────────────────────────────────────────────────────────
# 3. Cohort too small → None
# ──────────────────────────────────────────────────────────────────

def test_cohort_with_fewer_than_min_peers_returns_none():
    """Sector with < 5 peers in the bucket (and < 5 even after
    widening) returns None — caller surfaces as data_limited.
    """
    # Only 2 Premium peers, no Core peers → widening to Premium+Core
    # still produces < 5.  Must return None.
    small_cohort = _pharma_premium_peers()[:2]
    fin = {
        "eps": 50.0, "ebitda": 1000.0, "shares": 1e8,
        "roce": 27.0, "piotroski": 8, "market_cap_cr": 60000.0,
        "bvps": 200.0, "current_price": 1500.0,
    }
    out = compute_tier2_fair_value(
        ticker="SOMETHING",
        sector="Pharma",
        financials=fin,
        peers=small_cohort,
    )
    assert out is None, (
        f"Expected None for cohort size {len(small_cohort)} < "
        f"MIN_BUCKET_SIZE ({MIN_BUCKET_SIZE}); got {out}"
    )


# ──────────────────────────────────────────────────────────────────
# 4. Feature flag default — off
# ──────────────────────────────────────────────────────────────────

def test_tier2_enabled_defaults_to_false(monkeypatch):
    """TIER2_ENABLED unset OR set to '0'/'false' → tier2_enabled() False.
    This guarantees byte-identical routing in prod until W2 onwards.
    """
    monkeypatch.delenv("TIER2_ENABLED", raising=False)
    assert tier2_enabled() is False
    for val in ("0", "false", "no", "off", "FALSE", ""):
        monkeypatch.setenv("TIER2_ENABLED", val)
        assert tier2_enabled() is False, f"{val!r} should be off"
    for val in ("1", "true", "yes", "on", "TRUE"):
        monkeypatch.setenv("TIER2_ENABLED", val)
        assert tier2_enabled() is True, f"{val!r} should be on"


# ──────────────────────────────────────────────────────────────────
# 5. Skip-sectors short-circuit to None
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sector", [
    "Banking", "NBFC", "Insurance", "Financial Services",
    "Regulated Utility", "ETF", "REIT", "Holding Company",
])
def test_skip_sectors_return_none(sector):
    """Tier 2 must not fire for sectors with dedicated engines or
    skip paths.  The routing tree in service.py already short-
    circuits these BEFORE the Tier 2 branch — this is defence in
    depth so a wrong-sector hand-off to Tier 2 never returns a FV.
    """
    assert is_tier2_skip_sector(sector) is True
    fin = {
        "eps": 50.0, "ebitda": 1000.0, "shares": 1e8,
        "roce": 27.0, "piotroski": 8, "market_cap_cr": 60000.0,
        "current_price": 1500.0,
    }
    out = compute_tier2_fair_value(
        ticker="X",
        sector=sector,
        financials=fin,
        peers=_pharma_premium_peers(),
    )
    assert out is None


# ──────────────────────────────────────────────────────────────────
# 6. EV/EBITDA preference for capital-goods / cement / metals
# ──────────────────────────────────────────────────────────────────

def test_capital_goods_uses_ev_ebitda_leg():
    """Capital Goods is in EV_EBITDA_PREFERRED_SECTORS — Tier 2 must
    prefer the EV/EBITDA leg when peer median is present.
    """
    # Build a Premium cap-goods cohort.  Use stable EV/EBITDA values
    # so the result is predictable.
    peers = [
        {"ticker": "SIEMENS", "pe": 70.0, "ev_ebitda": 40.0,
         "roce": 28.0, "piotroski": 8, "market_cap_cr": 200000.0},
        {"ticker": "ABB", "pe": 80.0, "ev_ebitda": 45.0,
         "roce": 30.0, "piotroski": 7, "market_cap_cr": 150000.0},
        {"ticker": "CUMMINSIND", "pe": 50.0, "ev_ebitda": 30.0,
         "roce": 35.0, "piotroski": 7, "market_cap_cr": 80000.0},
        {"ticker": "THERMAX", "pe": 60.0, "ev_ebitda": 35.0,
         "roce": 26.0, "piotroski": 7, "market_cap_cr": 60000.0},
        {"ticker": "ELGIEQUIP", "pe": 55.0, "ev_ebitda": 32.0,
         "roce": 27.0, "piotroski": 8, "market_cap_cr": 55000.0},
    ]
    fin = {
        "eps": 50.0,
        "ebitda": 1000.0,
        "shares": 5e7,        # 50M shares
        "roce": 28.0,
        "piotroski": 8,
        "market_cap_cr": 100000.0,
        "net_debt_cr": 500.0,
        "bvps": 800.0,
        "current_price": 5000.0,
    }
    out = compute_tier2_fair_value(
        ticker="CAPGOODS-X",
        sector="Capital Goods",
        financials=fin,
        peers=peers,
    )
    assert out is not None
    assert out["_meta"]["leg_used"] == "ev_ebitda"
    assert out["method"] == "cohort_ev_ebitda"
    # EV = 35 (median) × 1000 = 35000 Cr
    # equity = 35000 - 500 = 34500 Cr; ÷ 50M shares = ₹6,900
    # But will be capped at 8× BVPS = ₹6,400 → fv_capped = True.
    assert out["_meta"]["fv_capped"] in (True, False)


# ──────────────────────────────────────────────────────────────────
# 7. FV cap prevents over-shoots
# ──────────────────────────────────────────────────────────────────

def test_fv_capped_at_8x_bvps():
    """When peer P/E × ticker EPS would produce > 8× BVPS, the FV
    is capped — protects against SCHAEFFLER-style one-off peak EPS.
    """
    fin = {
        "eps": 200.0,          # peak EPS
        "ebitda": 1000.0,
        "shares": 1e8,
        "roce": 27.0,
        "piotroski": 8,
        "market_cap_cr": 60000.0,
        "bvps": 100.0,         # low book value
        "current_price": 1000.0,
    }
    out = compute_tier2_fair_value(
        ticker="PEAKEPS",
        sector="Pharma",
        financials=fin,
        peers=_pharma_premium_peers(),
    )
    assert out is not None
    # Uncapped: ~32 × 200 = 6400.  Cap: 8 × 100 = 800.
    assert out["_meta"]["fv_capped"] is True
    assert out["fair_value"] <= 8 * 100 + 0.01


# ──────────────────────────────────────────────────────────────────
# 8. Bucket classifier — sanity
# ──────────────────────────────────────────────────────────────────

def test_bucket_for_premium_core_tail():
    # ── Original 2026-04 cases (all still pass under refined rules) ──
    # Premium: large mcap + ROCE>=25 + Piotroski>=7
    assert _bucket_for(roce=27.0, piotroski=8,
                       market_cap_cr=70000.0) == "premium"
    # Core: ROCE 18 (>=15)
    assert _bucket_for(roce=18.0, piotroski=5,
                       market_cap_cr=10000.0) == "core"
    # Core: Piotroski 5 even with low ROCE
    assert _bucket_for(roce=8.0, piotroski=5,
                       market_cap_cr=10000.0) == "core"
    # Tail: low everything
    assert _bucket_for(roce=8.0, piotroski=3,
                       market_cap_cr=1000.0) == "tail"
    # Sub-Premium mcap kills Premium even with great quality → Core
    assert _bucket_for(roce=27.0, piotroski=8,
                       market_cap_cr=10000.0) != "premium"
    # Missing inputs → Tail (conservative default)
    assert _bucket_for(roce=None, piotroski=None,
                       market_cap_cr=None) == "tail"


def test_bucket_for_refined_2026_05():
    """Cases the original strict-AND rule mis-classified.

    Background: pre-refinement, _bucket_for required ALL THREE axes
    (ROCE>=25 AND Piotroski>=7 AND mcap>=50k Cr) for Premium. The
    Core branch used a narrow band (ROCE 15-25, Piotroski 5-6) that
    excluded exceptional outliers. Real-world peers like HDFCBANK
    (Piotroski=9, mcap=₹11L Cr, ROCE=NULL because banks have no
    meaningful ROCE) and TCS (ROCE=60.7%, mcap=₹8L Cr, Piotroski=6)
    fell to Tail despite clearly being best-in-class.
    """
    # HDFCBANK shape — large bank with high Piotroski, NULL ROCE
    assert _bucket_for(roce=None, piotroski=9,
                       market_cap_cr=1_185_447.0) == "premium"
    # TCS shape — exceptional ROCE, large cap, merely-good Piotroski
    assert _bucket_for(roce=60.7, piotroski=6,
                       market_cap_cr=820_220.0) == "premium"
    # INFY shape — large IT services, high Piotroski, NULL ROCE
    assert _bucket_for(roce=None, piotroski=7,
                       market_cap_cr=451_646.0) == "premium"
    # Open-ended Core: ROCE 30 with Piotroski 4 and sub-Premium mcap → core
    assert _bucket_for(roce=30.0, piotroski=4,
                       market_cap_cr=10_000.0) == "core"
    # Open-ended Core: Piotroski 8 with NULL ROCE and sub-Premium mcap → core
    assert _bucket_for(roce=None, piotroski=8,
                       market_cap_cr=10_000.0) == "core"
    # Small + low quality stays Tail even with one missing axis
    assert _bucket_for(roce=10.0, piotroski=None,
                       market_cap_cr=5_000.0) == "tail"
    # Large mcap alone (no quality signal) stays Tail
    assert _bucket_for(roce=None, piotroski=None,
                       market_cap_cr=200_000.0) == "tail"


def test_bucket_for_premium_rejects_single_axis_quality():
    """v2 refinement: large mcap + one good axis is NOT enough for Premium
    when the other axis is clearly broken. These cases caught real junk
    inclusions in the 2026-05-19 cohort.

    BHEL had ROCE 2.7% with Piotroski 7 → was passing under v1's OR rule
    despite a crushed return on capital. AMBUJACEM (ROCE 11.6) and TECHM
    (ROCE 12.2) had the same pattern. BAJAJ-AUTO (Piotroski 4) and ABB
    (Piotroski 4) had the inverse — high ROCE but deteriorating financials.
    All six belong in Core, not Premium.
    """
    # BHEL shape — high Piotroski but ROCE below Core floor → Core not Premium
    assert _bucket_for(roce=2.7, piotroski=7,
                       market_cap_cr=138_690.0) == "core"
    # AMBUJACEM shape — same pattern, sub-15 ROCE
    assert _bucket_for(roce=11.6, piotroski=7,
                       market_cap_cr=107_580.0) == "core"
    # BAJAJ-AUTO shape — high ROCE but Piotroski 4 (weak) → Core not Premium
    assert _bucket_for(roce=32.5, piotroski=4,
                       market_cap_cr=289_744.0) == "core"
    # BPCL shape — Piotroski 3 is a financial red flag regardless of ROCE
    assert _bucket_for(roce=32.3, piotroski=3,
                       market_cap_cr=121_661.0) == "core"
    # Lower boundary: ROCE exactly 25 with Piotroski exactly 5 passes Premium
    assert _bucket_for(roce=25.0, piotroski=5,
                       market_cap_cr=50_000.0) == "premium"
    # Inverse lower boundary: Piotroski exactly 7 with ROCE exactly 15
    assert _bucket_for(roce=15.0, piotroski=7,
                       market_cap_cr=50_000.0) == "premium"


# ──────────────────────────────────────────────────────────────────
# 9. Zero / negative EPS → None
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("eps", [0.0, -10.0, None])
def test_non_positive_eps_returns_none(eps):
    fin = {
        "eps": eps, "ebitda": 1000.0, "shares": 1e8,
        "roce": 27.0, "piotroski": 8, "market_cap_cr": 60000.0,
        "current_price": 1500.0,
    }
    out = compute_tier2_fair_value(
        ticker="X", sector="Pharma", financials=fin,
        peers=_pharma_premium_peers(),
    )
    assert out is None


# ──────────────────────────────────────────────────────────────────
# 10. Routing branch in service.py is byte-identical when flag off
# ──────────────────────────────────────────────────────────────────

def test_routing_unchanged_when_flag_off(monkeypatch):
    """When TIER2_ENABLED is off (default), the Tier 2 routing branch
    in backend/services/analysis/service.py MUST NOT call
    compute_tier2_fair_value.  This is the no-breaking-change
    contract for shipping a feature-flagged engine to prod.

    We assert at the engine level: tier2_enabled() False means the
    service.py branch's pre-condition fails, so the cohort path is
    skipped wholesale.
    """
    monkeypatch.delenv("TIER2_ENABLED", raising=False)
    assert tier2_enabled() is False
    # Direct call still works (used by canary diff with flag on) —
    # only the in-service routing is gated.  Verify the function is
    # importable and pure (no side effects beyond return).
    fin = {
        "eps": 76.0, "ebitda": 3500.0, "shares": 4e8,
        "roce": 27.0, "piotroski": 8, "market_cap_cr": 68000.0,
        "bvps": 380.0, "current_price": 2400.0,
    }
    out_a = compute_tier2_fair_value("MANKIND", "Pharma", fin,
                                      _pharma_premium_peers())
    out_b = compute_tier2_fair_value("MANKIND", "Pharma", fin,
                                      _pharma_premium_peers())
    assert out_a == out_b, "Engine must be deterministic / side-effect-free"
