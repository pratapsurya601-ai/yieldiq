"""Day-64 (2026-05-21): audit-driven low-hanging polish batch.

Closes 3 audit findings from the 2026-05-20 walkthrough in one PR:

  1. PARADEEP rendered as sector "GENERAL/DIVERSIFIED" (audit screen
     2.5). 10 Indian fertilizer tickers pinned to "Chemicals" so the
     chemicals cohort engine + sector facet route them correctly.
  2. Footer summary line leaked dev-name strings like
     "local_db_parquet" (audit screen 1.3 "Sources: local_db_parquet").
     humaniseSource() in AnalysisBody.tsx maps them to "YieldIQ database".
  3. Page title for HDFCBANK showed "Undervalued | YieldIQ" while the
     body's verdict pill was "Under Review" (audit screen 2.2 title
     vs verdict). UNDER_REVIEW_VERDICTS set in layout.tsx expanded to
     catch under_review / low_confidence and the top-level `status`
     field.

Source-text regression guards because all 3 fixes are isolated string
/ mapping changes with no Python-runtime surface.
"""
from __future__ import annotations
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_CONSTS = _ROOT / "backend" / "services" / "analysis" / "constants.py"
_BODY = (
    _ROOT / "frontend" / "src" / "app" / "(app)" / "analysis" / "[ticker]"
    / "AnalysisBody.tsx"
)
_LAYOUT = (
    _ROOT / "frontend" / "src" / "app" / "(app)" / "analysis" / "[ticker]"
    / "layout.tsx"
)
_CACHE = _ROOT / "backend" / "services" / "cache_service.py"


# ── Fertilizer sector pins ─────────────────────────────────


def test_paradeep_pinned_to_chemicals():
    src = _CONSTS.read_text(encoding="utf-8")
    assert '"PARADEEP":    "Chemicals"' in src


def test_all_ten_fertilizers_pinned():
    src = _CONSTS.read_text(encoding="utf-8")
    fertilizers = (
        "PARADEEP", "RCF", "GNFC", "GSFC", "NFL",
        "CHAMBLFERT", "FACT", "ZUARI", "DEEPAKFERT", "MADRASFERT",
    )
    for t in fertilizers:
        assert f'"{t}":' in src, f"{t} not in sector overrides"


# ── Frontend humanise expansion ────────────────────────────


def test_local_db_parquet_humanised():
    src = _BODY.read_text(encoding="utf-8")
    assert 'lower === "local_db_parquet"' in src
    assert '"YieldIQ database"' in src


def test_supabase_cache_humanised():
    src = _BODY.read_text(encoding="utf-8")
    assert 'lower === "supabase_cache"' in src


def test_tier2_cohort_humanised_as_model():
    src = _BODY.read_text(encoding="utf-8")
    assert 'lower === "tier2_cohort"' in src
    assert '"YieldIQ model"' in src


# ── Page title gate expansion ──────────────────────────────


def test_under_review_set_includes_new_states():
    src = _LAYOUT.read_text(encoding="utf-8")
    assert '"data_limited"' in src
    assert '"unavailable"' in src
    assert '"under_review"' in src
    assert '"low_confidence"' in src


def test_forbidden_substrings_include_low_confidence():
    src = _LAYOUT.read_text(encoding="utf-8")
    assert '"Low Confidence"' in src
    assert '"Under Review"' in src


def test_layout_checks_top_level_status_field():
    src = _LAYOUT.read_text(encoding="utf-8")
    # The new status read
    assert "ogData?.status" in src
    # And it must feed into isUnderReview
    assert "UNDER_REVIEW_VERDICTS.has(backendStatus)" in src


# ── CACHE_VERSION bumped ────────────────────────────────────


def test_cache_version_bumped_for_engine_change():
    src = _CACHE.read_text(encoding="utf-8")
    # Day-73 (Bug D, 2026-05-21): CACHE_VERSION moved past 129 with
    # multiple subsequent bumps. Pin the changelog entry, not the
    # integer, so future bumps don't keep editing this Day-64 guard.
    assert "fix/day64-audit-polish-batch" in src or "day64" in src.lower()
