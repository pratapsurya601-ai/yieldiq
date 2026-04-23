"""Lock-in tests for Prism pillar completeness on bellwether tickers.

Regression guard for fix/prism-pillars-completeness (2026-04-23).

History: on prod 2026-04-23 the TCS.NS analysis page rendered
"n/a" for the MOAT and GROWTH axes of the Spectrum Prism plus
"Revenue CAGR (3y): n/a" in the AI summary, even though TCS
has 10+ years of public revenue history and a moat_score of 80.
Root cause: ``hex_service._fetch_core_data`` queried the
``financials`` table with wrong column names (``op_margin``,
``fcf``, ``eps``, ``interest_coverage``) — every query raised
UndefinedColumn and the exception was swallowed. With no
financials rows, ``_axis_moat`` lost its op-margin-stability
signal and ``_axis_growth`` lost its revenue-CAGR fallback, so
every ticker whose cached ``quality.moat`` / ``quality.revenue_cagr_*y``
was null collapsed to ``data_limited=True``.

These tests lock in:
  1. The financials-table query uses column names that exist on
     ``data_pipeline.models.Financials`` (operating_margin,
     free_cash_flow, eps_diluted, debt_to_equity).
  2. ``_axis_moat`` lights up when only ``quality.moat_score`` is
     present (the numeric fallback for stale cached payloads).
  3. ``_axis_moat`` recognises the "Moderate" band introduced by
     PR #36's STRONG_BRAND_ALLOWLIST floor.
  4. ``_axis_growth`` reads ``quality.revenue_cagr_3y`` as a
     decimal and normalises to percent (existing behaviour, guarded).
  5. The prism_service market_metrics fetch tries both canonical
     (``HDFCBANK.NS``) and bare (``HDFCBANK``) ticker forms.
"""
from __future__ import annotations

import re

from backend.services import hex_service, prism_service
from data_pipeline.models import Financials


# ── (1) Column-name sanity ─────────────────────────────────────────
def test_fetch_core_data_sql_references_real_columns():
    """The SELECT in _fetch_core_data must reference columns that
    actually exist on the Financials ORM model. A typo here silently
    starves the moat + growth axes (the TCS canary bug).
    """
    import inspect
    src = inspect.getsource(hex_service._fetch_core_data)
    # Collapse adjacent string literals and whitespace so the SELECT
    # is a single flat string even when Python source splits it across
    # "..." "..." pairs.
    flat = re.sub(r'"\s*"', "", src)
    flat = re.sub(r"\s+", " ", flat)
    m = re.search(r"SELECT\s+([\w\s,]+?)\s+FROM financials", flat)
    assert m, "financials SELECT not found in _fetch_core_data"
    selected = [s.strip() for s in m.group(1).split(",") if s.strip()]

    real_columns = {c.name for c in Financials.__table__.columns}
    # period_end is selected but not in the output dict by name — still
    # a real column so it must resolve.
    for col in selected:
        assert col in real_columns, (
            f"_fetch_core_data selects non-existent column `{col}` "
            f"from financials. Known columns: {sorted(real_columns)[:10]}…"
        )


# ── (2) moat_score numeric fallback ───────────────────────────────
def test_axis_moat_lights_when_only_moat_score_present():
    """Cached payloads from before PR #36 may have
    ``quality.moat = null`` but a valid ``quality.moat_score``. The
    axis must light from the numeric field so the Spectrum doesn't
    render "n/a" on stale rows.
    """
    data = {
        "analysis": {"quality": {"moat": None, "moat_score": 80.0}},
        "financials": [],  # no op-margin fallback available
        "metrics": {},
    }
    ax = hex_service._axis_moat(data, sector="it")
    assert ax["data_limited"] is False, (
        f"moat axis must not be data_limited when moat_score is present "
        f"(got why={ax['why']!r})"
    )
    assert ax["score"] > 5.0, (
        f"moat_score=80 should push axis above neutral (got {ax['score']})"
    )


def test_axis_moat_recognises_moderate_band():
    """PR #36's STRONG_BRAND_ALLOWLIST floor surfaces
    ``quality.moat = 'Moderate'`` for TITAN/RELIANCE/HDFCBANK. The
    axis must map that to a positive contribution — not treat it as
    unknown (which would collapse to neutral).
    """
    data = {
        "analysis": {"quality": {"moat": "Moderate", "moat_score": 65.0}},
        "financials": [],
        "metrics": {},
    }
    ax = hex_service._axis_moat(data, sector="general")
    assert ax["data_limited"] is False
    assert ax["score"] > 5.0, (
        f"Moderate moat must contribute positively (got {ax['score']})"
    )
    # Reason string should mention the band.
    assert "moderate" in ax["why"].lower() or "moat score" in ax["why"].lower()


# ── (3) Moat axis stays data_limited when BOTH inputs absent ──────
def test_axis_moat_still_neutral_when_genuinely_thin():
    """Complementary test: if quality.moat AND quality.moat_score
    are both null AND financials has no op-margin history, the axis
    should stay data_limited=True. We want the hardening to catch
    stale payloads, not to fabricate moats for tickers that really
    have no signal.
    """
    data = {
        "analysis": {"quality": {"moat": None, "moat_score": None}},
        "financials": [],
        "metrics": {},
    }
    ax = hex_service._axis_moat(data, sector="general")
    assert ax["data_limited"] is True


# ── (4) Growth axis revenue-CAGR plumbing ─────────────────────────
def test_axis_growth_reads_decimal_revenue_cagr_3y():
    """quality.revenue_cagr_3y is persisted as DECIMAL (0.08 = 8%).
    The axis must normalise to percent internally. Regression guard
    for the bellwether case: 7% real CAGR must NOT be misread as
    ~700% and then clamped to neutral.
    """
    data = {
        "analysis": {"quality": {"revenue_cagr_3y": 0.08}},
        "financials": [],
    }
    ax = hex_service._axis_growth(data, sector="it")
    assert ax["data_limited"] is False
    assert "Rev CAGR" in ax["why"]
    # 8% → anchor-adjusted score ≈ 5.0 + 0.8 = 5.8 (within ±0.5 band).
    assert 5.3 < ax["score"] < 6.3


def test_axis_growth_falls_back_to_financials_when_cagr_absent():
    """Stale cached payloads may lack revenue_cagr_3y/_5y. The
    axis must still light when the financials table has enough
    revenue history to derive the CAGR on the fly.
    """
    # 5 annual rows — same shape as _fetch_core_data's output.
    # oldest last in the financials slice? actually hex_service uses
    # `fins[-1]` as oldest and `fins[0]` as newest (see _axis_growth).
    fins = [
        {"revenue": 2_000_000.0},  # newest
        {"revenue": 1_850_000.0},
        {"revenue": 1_700_000.0},
        {"revenue": 1_600_000.0},
        {"revenue": 1_500_000.0},  # oldest
    ]
    data = {
        "analysis": {"quality": {"revenue_cagr_3y": None, "revenue_cagr_5y": None}},
        "financials": fins,
    }
    ax = hex_service._axis_growth(data, sector="general")
    assert ax["data_limited"] is False, (
        f"Growth axis must fall back to financials-derived CAGR "
        f"(got why={ax['why']!r})"
    )


# ── (5) prism market-cap ticker-form expansion ────────────────────
def test_fetch_market_cap_cr_tries_both_ticker_forms():
    """HDFCBANK had market_metrics rows under the BARE form only —
    the canonical-only query returned None, which starved the bank
    branch of _axis_moat of its scale signal. Regression guard.
    """
    import inspect
    src = inspect.getsource(prism_service._fetch_market_cap_cr)
    assert 'replace(".NS"' in src and 'replace(".BO"' in src, (
        "_fetch_market_cap_cr must strip ticker suffixes as part of "
        "its candidate expansion"
    )
    assert "candidates" in src, (
        "_fetch_market_cap_cr must iterate over multiple ticker forms"
    )
