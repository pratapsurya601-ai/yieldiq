# backend/tests/test_consumer_durables_wc_service.py
#
# Tests for the standalone consumer-durables WC valuation service
# shipped in T3.13 Phase A. Phase B will wire the engine into the
# analysis route; this test surface covers ONLY the pure math + the
# applicability gate so the Phase A PR can ship without touching any
# caller.
#
# Coverage:
#   1. HAVELLS-shape: revenue ~18,000 Cr, normalized WC 15%, current 18%
#      → "stretched" label, FV computed, drag is non-zero
#   2. VOLTAS-shape: AC seasonal build. Higher current WC than median,
#      operating cycle median derived from history
#   3. CROMPTON-shape: fans, normal WC intensity, premium multiple
#   4. classify_wc_intensity: efficient / normal / stretched / stressed
#      bucket boundaries
#   5. compute_normalized_wc: 5y median + fallback on empty
#   6. compute_wc_drag: excess × cost-of-equity; zero when tighter than
#      normalized
#   7. Operating cycle median computation
#   8. Defensive: zero revenue, zero shares, missing history
#   9. Applicability gate: universe in, RAJESHEXPO out, sector-tagged
#      mismatch out, empty in out
#  10. to_dict shape: JSON-safe round-trip
#  11. Universe + frozenset constants
#
# Run: pytest backend/tests/test_consumer_durables_wc_service.py -v
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── HAVELLS-shape: stretched WC ─────────────────────────────────
def test_havells_shaped_stretched_wc_intensity():
    """HAVELLS-shape: revenue ₹18,000 Cr, 5y normalized WC 15%, but
    current period inventory + receivables − payables runs at 18% of
    revenue. Bucket should be "stretched" (current/median = 1.20 →
    inside the (1.10, 1.25] band)."""
    from backend.services.consumer_durables_wc_service import (
        ConsumerDurablesInputs, compute_consumer_durables_fv,
    )
    # Build a current-period WC that lands at 18% of revenue:
    # inventory + receivables − payables = 3240 Cr (18% of 18000).
    inp = ConsumerDurablesInputs(
        revenue_inr_cr=18000.0,
        inventory_inr_cr=2400.0,       # ~13% of revenue
        receivables_inr_cr=1800.0,     # ~10% of revenue
        payables_inr_cr=960.0,         # ~5% of revenue → WC=3240, 18%
        operating_cycle_days_history=[95.0, 92.0, 98.0, 100.0, 96.0],
        wc_intensity_pct_history=[14.0, 15.0, 16.0, 15.0, 13.0],   # median 15
        margin_pct=11.0,               # HAVELLS-typical
        ev_ebitda_multiple=32.0,       # brand premium
        net_debt_inr_cr=-500.0,        # net cash
        shares_outstanding=63.0,       # ~63 Cr shares
    )
    out = compute_consumer_durables_fv(inp)
    assert out.normalized_wc_intensity_pct == pytest.approx(15.0, abs=0.01)
    assert out.current_wc_intensity_pct == pytest.approx(18.0, abs=0.05)
    assert out.intensity_label == "stretched"
    # Drag is non-zero (excess WC × cost-of-equity).
    # excess = 3% of 18000 = 540 Cr; at 12% ke → ~64.8 Cr drag.
    assert out.wc_swing_drag_inr_cr == pytest.approx(64.8, abs=0.5)
    # FV per share computed.
    assert out.fair_value_per_share is not None
    assert out.fair_value_per_share > 0
    # Operating cycle median pulled from history (5-num median 96).
    assert out.operating_cycle_days_median == pytest.approx(96.0, abs=0.1)


# ── VOLTAS-shape: seasonal AC build ─────────────────────────────
def test_voltas_shaped_seasonal_ac_wc():
    """VOLTAS-shape: pre-summer AC inventory + dealer credit build.
    Median WC intensity ~12% but current snapshot at 17% (peak build).
    Operating cycle is longer (~110 days) reflecting AC seasonality."""
    from backend.services.consumer_durables_wc_service import (
        ConsumerDurablesInputs, compute_consumer_durables_fv,
    )
    inp = ConsumerDurablesInputs(
        revenue_inr_cr=12000.0,
        inventory_inr_cr=2200.0,
        receivables_inr_cr=1600.0,
        payables_inr_cr=1760.0,                  # WC = 2040, 17% of revenue
        operating_cycle_days_history=[105.0, 110.0, 115.0, 108.0, 112.0],
        wc_intensity_pct_history=[11.0, 12.0, 13.0, 12.0, 11.5],   # median 12
        margin_pct=9.0,
        ev_ebitda_multiple=30.0,
        net_debt_inr_cr=200.0,
        shares_outstanding=33.0,
    )
    out = compute_consumer_durables_fv(inp)
    assert out.normalized_wc_intensity_pct == pytest.approx(12.0, abs=0.01)
    # current_wc_pct ~ 17%; ratio to median ~ 1.42 → "stressed" via
    # ratio threshold (>1.25), though absolute 17% is under 30% ceiling.
    assert out.intensity_label in {"stressed", "stretched"}
    # Operating cycle median = middle of sorted [105,108,110,112,115] = 110.
    assert out.operating_cycle_days_median == pytest.approx(110.0, abs=0.1)
    # FV computed.
    assert out.fair_value_per_share is not None
    # Drag exists because current > normalized.
    assert out.wc_swing_drag_inr_cr > 0


# ── CROMPTON-shape: efficient WC ────────────────────────────────
def test_crompton_shaped_normal_wc():
    """CROMPTON-shape: fans + premium kitchen. WC intensity in line
    with its own 5y median, brand multiple intact, no excess drag."""
    from backend.services.consumer_durables_wc_service import (
        ConsumerDurablesInputs, compute_consumer_durables_fv,
    )
    inp = ConsumerDurablesInputs(
        revenue_inr_cr=7500.0,
        inventory_inr_cr=900.0,
        receivables_inr_cr=600.0,
        payables_inr_cr=450.0,                # WC = 1050, 14% of revenue
        operating_cycle_days_history=[80.0, 82.0, 78.0, 85.0, 79.0],
        wc_intensity_pct_history=[13.0, 14.0, 14.5, 13.5, 14.0],   # median 14
        margin_pct=10.5,
        ev_ebitda_multiple=28.0,
        net_debt_inr_cr=100.0,
        shares_outstanding=63.0,
    )
    out = compute_consumer_durables_fv(inp)
    assert out.normalized_wc_intensity_pct == pytest.approx(14.0, abs=0.01)
    assert out.current_wc_intensity_pct == pytest.approx(14.0, abs=0.05)
    # Right at median → normal bucket.
    assert out.intensity_label == "normal"
    # No excess → no drag.
    assert out.wc_swing_drag_inr_cr == pytest.approx(0.0, abs=0.01)
    # FV computed.
    assert out.fair_value_per_share is not None
    assert out.fair_value_per_share > 0


# ── classify_wc_intensity boundaries ────────────────────────────
def test_classify_wc_intensity_efficient():
    from backend.services.consumer_durables_wc_service import classify_wc_intensity
    # 8 / 10 = 0.80 → efficient
    assert classify_wc_intensity(8.0, 10.0) == "efficient"


def test_classify_wc_intensity_normal():
    from backend.services.consumer_durables_wc_service import classify_wc_intensity
    # 10.5 / 10 = 1.05 → normal (inside (0.90, 1.10])
    assert classify_wc_intensity(10.5, 10.0) == "normal"


def test_classify_wc_intensity_stretched():
    from backend.services.consumer_durables_wc_service import classify_wc_intensity
    # 12 / 10 = 1.20 → stretched
    assert classify_wc_intensity(12.0, 10.0) == "stretched"


def test_classify_wc_intensity_stressed_by_ratio():
    from backend.services.consumer_durables_wc_service import classify_wc_intensity
    # 14 / 10 = 1.40 → stressed
    assert classify_wc_intensity(14.0, 10.0) == "stressed"


def test_classify_wc_intensity_absolute_ceiling():
    """current_pct >= 30% backstops to stressed regardless of ratio."""
    from backend.services.consumer_durables_wc_service import classify_wc_intensity
    # 32% over 30% median = 1.07 ratio (would be "normal"); absolute
    # backstop overrides.
    assert classify_wc_intensity(32.0, 30.0) == "stressed"


def test_classify_wc_intensity_zero_median_fallback():
    """Empty / zero median → fall back to absolute thresholds."""
    from backend.services.consumer_durables_wc_service import classify_wc_intensity
    assert classify_wc_intensity(8.0, 0.0) == "efficient"
    assert classify_wc_intensity(15.0, 0.0) == "normal"
    assert classify_wc_intensity(22.0, 0.0) == "stretched"
    # 28% is past the absolute-bucket "stretched" ceiling of 25% in the
    # zero-median fallback path → stressed.
    assert classify_wc_intensity(28.0, 0.0) == "stressed"
    assert classify_wc_intensity(35.0, 0.0) == "stressed"


# ── compute_normalized_wc ───────────────────────────────────────
def test_compute_normalized_wc_5y_median():
    from backend.services.consumer_durables_wc_service import compute_normalized_wc
    # 5y series — odd number, median is middle.
    assert compute_normalized_wc([12.0, 14.0, 15.0, 16.0, 18.0]) == pytest.approx(15.0)


def test_compute_normalized_wc_empty_fallback():
    """Empty history → fall back to 15% cohort default."""
    from backend.services.consumer_durables_wc_service import compute_normalized_wc
    assert compute_normalized_wc([]) == pytest.approx(15.0)


def test_compute_normalized_wc_handles_nones():
    """None / NaN entries are filtered before median."""
    from backend.services.consumer_durables_wc_service import compute_normalized_wc
    assert compute_normalized_wc([10.0, None, 20.0]) == pytest.approx(15.0)


# ── compute_wc_drag ─────────────────────────────────────────────
def test_compute_wc_drag_excess():
    """current=18%, normalized=15%, revenue=18000, ke=12%.
       excess = 3% × 18000 = 540 Cr; drag = 540 × 0.12 = 64.8 Cr."""
    from backend.services.consumer_durables_wc_service import compute_wc_drag
    drag = compute_wc_drag(
        current_wc=18.0, normalized_wc=15.0, revenue=18000.0,
        cost_of_equity=0.12,
    )
    assert drag == pytest.approx(64.8, abs=0.5)


def test_compute_wc_drag_zero_when_tighter_than_normalized():
    """Running tighter than median → no drag (the upside accrues to
    EBITDA via lower funding cost, not modeled here)."""
    from backend.services.consumer_durables_wc_service import compute_wc_drag
    drag = compute_wc_drag(
        current_wc=10.0, normalized_wc=15.0, revenue=18000.0,
        cost_of_equity=0.12,
    )
    assert drag == pytest.approx(0.0)


# ── operating cycle median ──────────────────────────────────────
def test_operating_cycle_median_from_history():
    """Median of sorted [80, 82, 85, 88, 95] = 85."""
    from backend.services.consumer_durables_wc_service import (
        ConsumerDurablesInputs, compute_consumer_durables_fv,
    )
    inp = ConsumerDurablesInputs(
        revenue_inr_cr=5000.0,
        inventory_inr_cr=400.0,
        receivables_inr_cr=300.0,
        payables_inr_cr=200.0,
        operating_cycle_days_history=[80.0, 82.0, 85.0, 88.0, 95.0],
        wc_intensity_pct_history=[10.0, 11.0, 10.5, 10.0, 11.0],
        shares_outstanding=20.0,
    )
    out = compute_consumer_durables_fv(inp)
    assert out.operating_cycle_days_median == pytest.approx(85.0, abs=0.1)


def test_operating_cycle_falls_back_to_current_when_history_empty():
    """Empty history → current operating cycle is used as proxy
    median. Warning surfaced."""
    from backend.services.consumer_durables_wc_service import (
        ConsumerDurablesInputs, compute_consumer_durables_fv,
    )
    inp = ConsumerDurablesInputs(
        revenue_inr_cr=10000.0,
        inventory_inr_cr=1000.0,            # DIO = 36.5
        receivables_inr_cr=800.0,           # DSO = 29.2
        payables_inr_cr=500.0,              # DPO = 18.25
        operating_cycle_days_history=[],    # empty
        wc_intensity_pct_history=[12.0, 13.0, 14.0, 13.0, 13.5],
        shares_outstanding=25.0,
    )
    out = compute_consumer_durables_fv(inp)
    # Current cycle ≈ 36.5 + 29.2 - 18.25 = 47.45
    assert out.operating_cycle_days_median == pytest.approx(47.5, abs=0.5)
    assert any("operating_cycle" in w for w in out.sanity_warnings)


# ── Defensive: zero revenue ─────────────────────────────────────
def test_zero_revenue_returns_unavailable_result():
    """Non-positive revenue → engine suppresses output but returns a
    sane ConsumerDurablesResult with a warning surfaced."""
    from backend.services.consumer_durables_wc_service import (
        ConsumerDurablesInputs, compute_consumer_durables_fv,
    )
    inp = ConsumerDurablesInputs(
        revenue_inr_cr=0.0,
        inventory_inr_cr=1000.0,
        receivables_inr_cr=500.0,
        payables_inr_cr=300.0,
        shares_outstanding=20.0,
    )
    out = compute_consumer_durables_fv(inp)
    assert out.fair_value_per_share is None
    assert any("revenue" in w.lower() for w in out.sanity_warnings)


# ── Defensive: zero shares ──────────────────────────────────────
def test_zero_shares_suppresses_per_share():
    from backend.services.consumer_durables_wc_service import (
        ConsumerDurablesInputs, compute_consumer_durables_fv,
    )
    inp = ConsumerDurablesInputs(
        revenue_inr_cr=10000.0,
        inventory_inr_cr=1000.0,
        receivables_inr_cr=800.0,
        payables_inr_cr=600.0,
        operating_cycle_days_history=[80.0, 90.0, 85.0],
        wc_intensity_pct_history=[12.0, 13.0, 12.5],
        shares_outstanding=0.0,            # missing
    )
    out = compute_consumer_durables_fv(inp)
    assert out.fair_value_per_share is None
    assert any("shares" in w.lower() for w in out.sanity_warnings)
    # Operating cycle median and intensity still computed.
    assert out.operating_cycle_days_median > 0
    assert out.intensity_label in {"efficient", "normal", "stretched", "stressed"}


# ── Defensive: missing WC history ───────────────────────────────
def test_missing_wc_history_uses_cohort_default():
    """Empty wc_intensity_pct_history → engine falls back to 15%
    cohort default and surfaces a warning."""
    from backend.services.consumer_durables_wc_service import (
        ConsumerDurablesInputs, compute_consumer_durables_fv,
    )
    inp = ConsumerDurablesInputs(
        revenue_inr_cr=10000.0,
        inventory_inr_cr=1200.0,
        receivables_inr_cr=800.0,
        payables_inr_cr=500.0,
        operating_cycle_days_history=[],
        wc_intensity_pct_history=[],        # empty!
        shares_outstanding=30.0,
    )
    out = compute_consumer_durables_fv(inp)
    assert out.normalized_wc_intensity_pct == pytest.approx(15.0, abs=0.01)
    assert any("wc_intensity_pct_history" in w for w in out.sanity_warnings)


# ── Applicability gate ──────────────────────────────────────────
def test_is_applicable_havells_true():
    from backend.services.consumer_durables_wc_service import is_consumer_durables_applicable
    ok, reason = is_consumer_durables_applicable("HAVELLS", "Consumer Durables")
    assert ok is True
    assert "HAVELLS" in reason


def test_is_applicable_all_universe():
    from backend.services.consumer_durables_wc_service import (
        is_consumer_durables_applicable, CONSUMER_DURABLES_TICKERS,
    )
    for t in CONSUMER_DURABLES_TICKERS:
        ok, reason = is_consumer_durables_applicable(t, None)
        assert ok is True, f"{t} should be applicable; reason={reason}"


def test_is_applicable_rajeshexpo_false_jewellery_excluded():
    """RAJESHEXPO is jewellery — explicit exclusion with reason."""
    from backend.services.consumer_durables_wc_service import is_consumer_durables_applicable
    ok, reason = is_consumer_durables_applicable("RAJESHEXPO", "Consumer Durables")
    assert ok is False
    assert "jewellery" in reason.lower() or "gold" in reason.lower()


def test_is_applicable_hdfcbank_false():
    from backend.services.consumer_durables_wc_service import is_consumer_durables_applicable
    ok, reason = is_consumer_durables_applicable("HDFCBANK", "Financial Services")
    assert ok is False
    assert "not" in reason.lower() or "consumer" in reason.lower()


def test_is_applicable_empty_ticker():
    from backend.services.consumer_durables_wc_service import is_consumer_durables_applicable
    ok, _ = is_consumer_durables_applicable("", None)
    assert ok is False


def test_is_applicable_handles_ns_suffix():
    from backend.services.consumer_durables_wc_service import is_consumer_durables_applicable
    ok, _ = is_consumer_durables_applicable("HAVELLS.NS", None)
    assert ok is True
    ok2, _ = is_consumer_durables_applicable("VOLTAS.BO", None)
    assert ok2 is True


# ── to_dict shape ───────────────────────────────────────────────
def test_to_dict_shape_is_json_safe():
    """to_dict() must return a plain dict whose values are JSON-
    serialisable primitives. No dataclass instances or datetimes."""
    import json
    from backend.services.consumer_durables_wc_service import (
        ConsumerDurablesInputs, compute_consumer_durables_fv, to_dict,
    )
    inp = ConsumerDurablesInputs(
        revenue_inr_cr=18000.0,
        inventory_inr_cr=2400.0,
        receivables_inr_cr=1800.0,
        payables_inr_cr=960.0,
        operating_cycle_days_history=[95.0, 92.0, 98.0, 100.0, 96.0],
        wc_intensity_pct_history=[14.0, 15.0, 16.0, 15.0, 13.0],
        shares_outstanding=63.0,
    )
    out = compute_consumer_durables_fv(inp)
    d = to_dict(out)
    expected_keys = {
        "fair_value_per_share", "normalized_wc_intensity_pct",
        "current_wc_intensity_pct", "wc_swing_drag_inr_cr",
        "intensity_label", "operating_cycle_days_median",
        "components", "sanity_warnings",
    }
    assert expected_keys.issubset(set(d.keys()))
    blob = json.dumps(d)
    assert isinstance(blob, str)
    parsed = json.loads(blob)
    assert parsed["intensity_label"] in {
        "efficient", "normal", "stretched", "stressed", "unknown",
    }
    assert isinstance(parsed["components"], dict)
    assert isinstance(parsed["sanity_warnings"], list)


# ── Constants ──────────────────────────────────────────────────
def test_consumer_durables_tickers_constants():
    """Phase A frozenset: 12 tickers exactly, RAJESHEXPO excluded."""
    from backend.services.consumer_durables_wc_service import CONSUMER_DURABLES_TICKERS
    assert CONSUMER_DURABLES_TICKERS == frozenset({
        "HAVELLS", "VOLTAS", "CROMPTON", "WHIRLPOOL", "BLUESTARCO",
        "ORIENTELEC", "BAJAJELEC", "V-GUARD", "KEI", "AMBER",
        "DIXON", "POLYCAB",
    })
    assert "RAJESHEXPO" not in CONSUMER_DURABLES_TICKERS
    assert len(CONSUMER_DURABLES_TICKERS) == 12


# ── Stressed label surfaces warning ─────────────────────────────
def test_stressed_label_surfaces_channel_stuffing_warning():
    """Stressed WC intensity should surface a channel-stuffing risk
    warning in sanity_warnings."""
    from backend.services.consumer_durables_wc_service import (
        ConsumerDurablesInputs, compute_consumer_durables_fv,
    )
    inp = ConsumerDurablesInputs(
        revenue_inr_cr=5000.0,
        inventory_inr_cr=1200.0,
        receivables_inr_cr=600.0,
        payables_inr_cr=200.0,              # WC = 1600, 32% of revenue → stressed
        operating_cycle_days_history=[100.0, 105.0, 110.0],
        wc_intensity_pct_history=[14.0, 15.0, 16.0, 15.0, 14.5],
        shares_outstanding=20.0,
    )
    out = compute_consumer_durables_fv(inp)
    assert out.intensity_label == "stressed"
    assert any(
        "channel-stuffing" in w.lower() or "stressed" in w.lower()
        for w in out.sanity_warnings
    )
