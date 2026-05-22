"""Day-103c (2026-05-22): compounded-growth (CAGR) panel tests.

Locks in:
  1. Standard CAGR math is correct for clean revenue/profit inputs
  2. Insufficient data (< 70% coverage) returns None for that window
  3. Sanity gate nulls |CAGR| > 100% (likely unit error or base effect)
  4. All four metric keys (revenue/profit/roe_avg/stock) are present
     in the panel regardless of data state
  5. ROE uses simple average over the window, NOT CAGR
  6. Empty financials still returns a well-formed all-null shape
  7. Public stock-summary route surfaces the panel under
     `compounded_growth` (source-text guard)
  8. Manifest carries the Day-103c entry
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.cagr_service import (
    _AnnualPoint,
    _cagr,
    compute_cagr_panel,
)


# ── helpers ──────────────────────────────────────────────────────


def _make_points(
    n: int,
    *,
    base_revenue: float = 100.0,
    revenue_cagr_pct: float = 12.0,
    base_pat: float = 10.0,
    pat_cagr_pct: float = 9.0,
    base_equity: float = 50.0,
    equity_cagr_pct: float = 8.0,
    newest_fy: int = 2025,
) -> list[_AnnualPoint]:
    """Synthesise newest→oldest annual points with known CAGRs."""
    rg = 1 + revenue_cagr_pct / 100.0
    pg = 1 + pat_cagr_pct / 100.0
    eg = 1 + equity_cagr_pct / 100.0
    pts: list[_AnnualPoint] = []
    for i in range(n):
        # i = 0 is newest. Older points have smaller values.
        years_back = i
        rev = base_revenue * (rg ** (n - 1 - years_back))
        pat = base_pat * (pg ** (n - 1 - years_back))
        eq = base_equity * (eg ** (n - 1 - years_back))
        fy = newest_fy - years_back
        pts.append(_AnnualPoint(
            fy=fy,
            period_end=date(fy, 3, 31),
            revenue=rev,
            pat=pat,
            equity=eq,
        ))
    return pts


# ── 1. Standard CAGR math ────────────────────────────────────────


def test_cagr_math_on_clean_inputs():
    # Doubled in 3 years → ~25.99% CAGR
    assert _cagr(100, 200, 3) == 26.0
    # 1.10^5 = 1.61051 → CAGR = 10%
    assert _cagr(100, 161.051, 5) == 10.0
    # Flat → 0%
    assert _cagr(100, 100, 7) == 0.0


def test_revenue_and_profit_cagr_on_synthetic_points():
    pts = _make_points(11, revenue_cagr_pct=12.0, pat_cagr_pct=9.0)
    panel = compute_cagr_panel(
        "TEST.NS",
        today=date(2025, 5, 1),
        points=pts,
        stock_panel={"3y": None, "5y": None, "10y": None},
    )
    # Synthetic series has exact CAGR by construction
    assert panel["revenue"]["3y"] == 12.0
    assert panel["revenue"]["5y"] == 12.0
    assert panel["revenue"]["10y"] == 12.0
    assert panel["profit"]["3y"] == 9.0
    assert panel["profit"]["5y"] == 9.0
    assert panel["profit"]["10y"] == 9.0


# ── 2. Insufficient data → None ──────────────────────────────────


def test_insufficient_data_returns_none_for_window():
    # Only 4 points present → 10y window can't make the 70% coverage
    # threshold (needs at least ceil(11*0.7) = 8) but 3y still can.
    pts = _make_points(4)
    panel = compute_cagr_panel(
        "TEST.NS",
        today=date(2025, 5, 1),
        points=pts,
        stock_panel={"3y": None, "5y": None, "10y": None},
    )
    assert panel["revenue"]["3y"] is not None
    assert panel["revenue"]["10y"] is None  # coverage gate trips


# ── 3. Sanity gate on absurd values ──────────────────────────────


def test_sanity_gate_nulls_over_100pct_cagr():
    # 100 → 100000 over 3y is ~9.6× per year ≈ 1000% — must null.
    pts = [
        _AnnualPoint(fy=2025, period_end=date(2025, 3, 31),
                     revenue=100_000.0, pat=10.0, equity=50.0),
        _AnnualPoint(fy=2024, period_end=date(2024, 3, 31),
                     revenue=80_000.0, pat=8.0, equity=48.0),
        _AnnualPoint(fy=2023, period_end=date(2023, 3, 31),
                     revenue=60_000.0, pat=7.0, equity=46.0),
        _AnnualPoint(fy=2022, period_end=date(2022, 3, 31),
                     revenue=100.0, pat=5.0, equity=42.0),
    ]
    panel = compute_cagr_panel(
        "TEST.NS",
        today=date(2025, 5, 1),
        points=pts,
        stock_panel={"3y": None, "5y": None, "10y": None},
    )
    # 3y endpoints are 100 → 100000 → ~1000% — nulled.
    assert panel["revenue"]["3y"] is None
    # Also confirm the underlying primitive nulls absurd values directly
    assert _cagr(100, 100_000, 3) is None


# ── 4. All four metric keys present ──────────────────────────────


def test_all_four_metrics_present_in_payload():
    pts = _make_points(6)
    panel = compute_cagr_panel(
        "TEST.NS",
        today=date(2025, 5, 1),
        points=pts,
        stock_panel={"3y": 10.0, "5y": 12.0, "10y": 14.0},
    )
    for k in ("revenue", "profit", "roe_avg", "stock"):
        assert k in panel
        for w in ("3y", "5y", "10y"):
            assert w in panel[k]
        assert "as_of_fy" in panel[k]


# ── 5. ROE uses average, not CAGR ────────────────────────────────


def test_roe_uses_average_not_cagr():
    # Construct flat ROE = 20% across the window.
    # If we accidentally compute CAGR, equity & pat both grow at the
    # same rate so the answer would be 0%. The average must be 20%.
    pts = _make_points(
        6,
        base_pat=10.0, pat_cagr_pct=10.0,
        base_equity=50.0, equity_cagr_pct=10.0,  # pat/equity ratio = 20% flat
    )
    panel = compute_cagr_panel(
        "TEST.NS",
        today=date(2025, 5, 1),
        points=pts,
        stock_panel={"3y": None, "5y": None, "10y": None},
    )
    assert panel["roe_avg"]["3y"] == 20.0
    assert panel["roe_avg"]["5y"] == 20.0


def test_roe_avg_differs_from_profit_cagr():
    """Cross-check: a series with rising profit but stable equity has
    profit CAGR > 0 AND rising ROE — averaged ROE must NOT equal the
    profit CAGR number, proving the two formulas aren't aliased."""
    pts = _make_points(
        6,
        base_pat=5.0, pat_cagr_pct=15.0,
        base_equity=50.0, equity_cagr_pct=0.0,
    )
    panel = compute_cagr_panel(
        "TEST.NS",
        today=date(2025, 5, 1),
        points=pts,
        stock_panel={"3y": None, "5y": None, "10y": None},
    )
    assert panel["profit"]["3y"] == 15.0
    # Average ROE across the window is not 15 — it's the mean of
    # pat/equity * 100 over rising pat. Just assert they differ.
    assert panel["roe_avg"]["3y"] != panel["profit"]["3y"]
    assert panel["roe_avg"]["3y"] is not None


# ── 6. Empty financials handled gracefully ───────────────────────


def test_empty_financials_returns_null_shape():
    panel = compute_cagr_panel(
        "TEST.NS",
        today=date(2025, 5, 1),
        points=[],
        stock_panel={"3y": None, "5y": None, "10y": None},
    )
    # Shape must still be present so the frontend can render "—" cells
    for k in ("revenue", "profit", "roe_avg", "stock"):
        assert panel[k]["3y"] is None
        assert panel[k]["5y"] is None
        assert panel[k]["10y"] is None
        assert panel[k]["as_of_fy"] is None


# ── 7. Public route wires the field through ──────────────────────


def test_public_route_includes_compounded_growth_field():
    """Source-text guard: _extract_analysis_summary must emit
    `compounded_growth` so the frontend panel can read it."""
    import backend.routers.public as pub_mod
    src = Path(pub_mod.__file__).read_text(encoding="utf-8")
    assert '"compounded_growth"' in src, (
        "stock-summary must surface compounded_growth — see Day-103c"
    )
    assert "_safe_compute_cagr_panel" in src
    assert "compute_cagr_panel" in src


# ── 8. Manifest entry present ────────────────────────────────────


def test_manifest_has_day103c_entry():
    from backend.services.cache_invalidation_manifest import MANIFEST
    ids = [e.get("version_id") for e in MANIFEST]
    assert "v_day103c_cagr_panel_2026_05_22" in ids
    entry = next(e for e in MANIFEST if e["version_id"] == "v_day103c_cagr_panel_2026_05_22")
    assert "compounded_growth" in entry["scope"]["fields"]
