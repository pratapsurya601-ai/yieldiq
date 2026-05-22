"""Task#87 — asset_turnover null at call site due to unit mismatch.

PR #498 added a sanity gate inside ``compute_asset_turnover`` that
returns ``None`` for ratios outside ``[0.001, 100]``. That gate was
correct, but it surfaced a *pre-existing* unit-mismatch bug at the
call site in ``backend/services/analysis/service.py``:

    _total_assets = enriched.get("total_assets") or _ta_db or 0
    ...
    _asset_turnover = _at(
        enriched.get("latest_revenue") or enriched.get("revenue"),
        _total_assets,
    )

``enriched.latest_revenue`` is in Crores (repo convention), but
``enriched.total_assets`` comes from yfinance in *raw INR*
(TCS.NS = 1,823,720,000,000 = ~1.82e12). When yfinance has a value
it wins over ``_ta_db`` (Crores), so the ratio collapses to ~1e-7
and trips the sanity gate. Result on prod: RELIANCE / TATASTEEL /
ULTRACEMCO / TCS / INFY all show ``asset_turnover: null`` and the
UI renders "n/a" despite the raw data being clean.

The fix mirrors ``_ta_for_roce`` at line ~3536 of the same file:
prefer the DB value (``_ta_db``, in Crores) so revenue and
total_assets share the same unit.

These tests exercise ``compute_asset_turnover`` with the exact
shapes that were broken in prod (units intact) and verify the
expected post-fix ratios. The actual call-site fix is asserted by
inspecting the source so a future refactor that re-introduces the
unit mismatch will fail this test.
"""
from __future__ import annotations

import re
from pathlib import Path

from backend.services.ratios_service import compute_asset_turnover


# ─────────────────── Real-shape regression cases ───────────────────


def test_reliance_real_shape_post_fix():
    """RELIANCE FY25: revenue 964,693 Cr / total_assets 1,950,121 Cr."""
    assert compute_asset_turnover(964_693, 1_950_121) == 0.49


def test_tatasteel_real_shape_post_fix():
    """TATASTEEL FY25: revenue 216,840 Cr / total_assets 279,395 Cr."""
    assert compute_asset_turnover(216_840.35, 279_394.80) == 0.78


def test_ultracemco_real_shape_post_fix():
    """ULTRACEMCO FY25: revenue 74,936 Cr / total_assets 133,697 Cr."""
    assert compute_asset_turnover(74_936.45, 133_697.16) == 0.56


def test_tcs_real_shape_post_fix():
    """TCS FY26: revenue 267,021 Cr / total_assets 182,372 Cr."""
    assert compute_asset_turnover(267_021, 182_372) == 1.46


def test_infy_real_shape_post_fix():
    """INFY FY25: revenue 1,927.7 Cr / total_assets 1,741.9 Cr."""
    # NB: INFY rows in financials.parquet are scaled differently
    # (already in thousands of Cr) but the ratio is what matters.
    assert compute_asset_turnover(1_927.70, 1_741.90) == 1.11


# ─────────────────── Pre-fix repro: unit mismatch ──────────────────


def test_tcs_unit_mismatch_repro_trips_gate():
    """Pre-fix behaviour: revenue in Crores, total_assets in raw INR.

    Without the call-site fix, TCS would pass these args:
      revenue       = 267,021      (Crores)
      total_assets  = 1.82372e12   (raw INR, from yfinance)
    Ratio = 1.46e-7 < 0.001 → PR #498 gate returns None.
    """
    assert compute_asset_turnover(267_021, 1_823_720_000_000) is None


# ─────────────────── Call-site source assertion ────────────────────


def test_call_site_prefers_db_total_assets_for_asset_turnover():
    """The fix in service.py must prefer _ta_db (Crores) over the
    mixed-unit _total_assets for the asset_turnover call.

    This guards against a future refactor reverting to passing
    _total_assets directly and silently re-introducing the unit
    mismatch.
    """
    svc = Path(__file__).resolve().parent.parent / "services" / "analysis" / "service.py"
    src = svc.read_text(encoding="utf-8")
    # The fix introduces _ta_for_at = _ta_db if _ta_db is not None else _total_assets
    # immediately before the compute_asset_turnover call.
    pat = re.compile(
        r"_ta_for_at\s*=\s*_ta_db\s+if\s+_ta_db\s+is\s+not\s+None\s+else\s+_total_assets[\s\S]{0,400}?_asset_turnover\s*=\s*_at\(",
    )
    assert pat.search(src), (
        "Expected _ta_for_at fallback (DB → enriched) immediately before "
        "the compute_asset_turnover call in analysis/service.py"
    )
