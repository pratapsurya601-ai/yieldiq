# backend/tests/test_sector_medians_for_ticker.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for backend/services/sector_medians_for_ticker.py.
#
# These tests stub `analysis_cache_service.get_cached_latest` so the
# helper can be exercised without an Aiven connection. Cohort
# definitions are intentionally NOT mocked — we rely on the real
# sector_pages.SECTOR_PAGES so the test also validates that a known
# cohort ticker (TCS in `it-services`) resolves through the slug
# reverse-lookup correctly.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from unittest.mock import patch

from backend.services import sector_medians_for_ticker as svc


def _payload(pe: float | None, pb: float | None, roe: float | None,
             div_yield: float | None, op_margin: float | None) -> dict:
    """Build a minimal cached-payload dict matching the surfaces the
    helper reads (quality.pe_ratio / pb_ratio / roe,
    insights.dividend.current_yield_pct, quality.operating_margin)."""
    return {
        "quality": {
            "pe_ratio": pe,
            "pb_ratio": pb,
            "roe": roe,
            "operating_margin": op_margin,
        },
        "insights": {
            "dividend": {"current_yield_pct": div_yield},
        },
    }


def test_out_of_cohort_returns_all_none():
    """A ticker outside every Day-108c cohort returns the empty shell —
    not a partial dict, not an exception."""
    svc._reset_cache_for_tests()
    out = svc.get_sector_medians_for_ticker("RANDOMSMALLCAP")
    assert set(out.keys()) == {"pe", "pb", "roe", "div_yield", "op_margin"}
    assert all(v is None for v in out.values())


def test_in_cohort_aggregates_medians():
    """A cohort ticker (TCS in `it-services`) returns the median over
    its 5-member cohort. The fixture gives every cohort member a
    different value so the median picks the middle one."""
    svc._reset_cache_for_tests()
    # IT services cohort = TCS, INFY, WIPRO, HCLTECH, TECHM (sorted
    # by value below so the median is the 3rd entry).
    by_symbol = {
        "TCS.NS":     _payload(pe=10.0, pb=2.0, roe=10.0, div_yield=1.0, op_margin=20.0),
        "INFY.NS":    _payload(pe=20.0, pb=4.0, roe=20.0, div_yield=2.0, op_margin=22.0),
        "WIPRO.NS":   _payload(pe=30.0, pb=6.0, roe=30.0, div_yield=3.0, op_margin=24.0),
        "HCLTECH.NS": _payload(pe=40.0, pb=8.0, roe=40.0, div_yield=4.0, op_margin=26.0),
        "TECHM.NS":   _payload(pe=50.0, pb=10.0, roe=50.0, div_yield=5.0, op_margin=28.0),
    }
    from backend.services import analysis_cache_service as _acs
    with patch.object(
        _acs,
        "get_cached_latest",
        side_effect=lambda sym: by_symbol.get(sym),
    ):
        out = svc.get_sector_medians_for_ticker("TCS")
    # Median of 5 ordered values is the middle (3rd) entry.
    assert out["pe"] == 30.0
    assert out["pb"] == 6.0
    assert out["roe"] == 30.0
    assert out["div_yield"] == 3.0
    assert out["op_margin"] == 24.0


def test_skips_none_entries_in_median():
    """Cohort members with a missing metric are dropped from the
    median, not coerced to zero. The remaining 3 values produce the
    middle entry."""
    svc._reset_cache_for_tests()
    by_symbol = {
        "TCS.NS":     _payload(pe=None, pb=None, roe=10.0, div_yield=None, op_margin=None),
        "INFY.NS":    _payload(pe=20.0, pb=None, roe=20.0, div_yield=None, op_margin=None),
        "WIPRO.NS":   _payload(pe=30.0, pb=None, roe=30.0, div_yield=None, op_margin=None),
        "HCLTECH.NS": _payload(pe=40.0, pb=None, roe=None, div_yield=None, op_margin=None),
        "TECHM.NS":   None,  # cache miss for this member
    }
    from backend.services import analysis_cache_service as _acs
    with patch.object(
        _acs,
        "get_cached_latest",
        side_effect=lambda sym: by_symbol.get(sym),
    ):
        out = svc.get_sector_medians_for_ticker("INFY")
    # PE has 3 values 20/30/40 → 30. ROE 10/20/30 → 20. PB / yield /
    # op_margin all-None → None (chip self-hides per metric).
    assert out["pe"] == 30.0
    assert out["roe"] == 20.0
    assert out["pb"] is None
    assert out["div_yield"] is None
    assert out["op_margin"] is None


def test_swallows_exceptions():
    """A blow-up inside the cohort walk must never propagate to the
    response path — the chip is descriptive, not load-bearing."""
    svc._reset_cache_for_tests()
    def _boom(_sym: str):
        raise RuntimeError("aiven down")
    from backend.services import analysis_cache_service as _acs2
    with patch.object(
        _acs2,
        "get_cached_latest",
        side_effect=_boom,
    ):
        out = svc.get_sector_medians_for_ticker("TCS")
    # Every per-ticker fetch fails → no contributions → empty shell.
    assert all(v is None for v in out.values())


def test_strips_exchange_suffix():
    """Bare and .NS forms must resolve to the same cohort."""
    svc._reset_cache_for_tests()
    # Both should find the it-services cohort.
    bare = svc._find_cohort_slug("TCS")
    suffixed = svc._find_cohort_slug(svc._bare("TCS.NS"))
    assert bare == "it-services"
    assert suffixed == "it-services"
