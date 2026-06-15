# backend/tests/test_og_data_extended.py
# ═══════════════════════════════════════════════════════════════
# Regression lock-in for feat/ogdata-add-scenarios-ratios.
#
# Context: PR #243 switched the canary-diff harness from the
# admin-gated /api/v1/analysis/{ticker} endpoint to the unauth
# /api/v1/analysis/{ticker}/og-data endpoint, removing the JWT
# expiry headaches that periodically broke the merge gate.
#
# But og-data was leaner than full /analysis — it returned only
# {title, description, ticker, score, verdict, fair_value, price,
# mos, coverage_tier}. Without scenarios (bear/base/bull) or
# ratios (roe/roce/wacc/ev_ebitda), canary Gates 3
# (scenario_dispersion) and 4 (canary_bounds) silently became
# no-ops: extract_fields() returned all-None for those keys, and
# every gate skipped every stock for "field not present".
#
# This PR plumbs those already-computed values from the cached
# AnalysisResponse into the og-data response dict. No new compute,
# no CACHE_VERSION bump, no auth added. The tests below assert:
#
#   1. All 7 new fields appear in the response when the cached
#      AnalysisResponse populates them.
#   2. Missing-data shapes (banks with no ev_ebitda, etc.) return
#      None rather than raising.
#   3. The zero-poison "_suspicious" path nulls scenario IVs (we
#      already null fv/mos there) — ratios stay valid because they
#      come from non-DCF code paths.
#   4. Existing og-data fields are unchanged (additive contract).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.routers.analysis import get_og_data


def _fake_analysis_response(
    *,
    fv: float = 1500.0,
    px: float = 1200.0,
    mos: float = 25.0,
    verdict: str = "undervalued",
    bear: float = 1100.0,
    base: float = 1500.0,
    bull: float = 1900.0,
    wacc: float = 0.115,
    roe: float | None = 0.235,
    roce: float | None = 0.295,
    ev_ebitda: float | None = 14.8,
    company_name: str = "Reliance Industries Ltd",
    score: int = 78,
    moat: str = "Wide",
) -> SimpleNamespace:
    """Build a SimpleNamespace shaped like AnalysisResponse for the
    fields the og-data handler reads. Avoids needing the real
    Pydantic model + every nested required field."""
    return SimpleNamespace(
        ticker="RELIANCE.NS",
        company=SimpleNamespace(company_name=company_name),
        valuation=SimpleNamespace(
            fair_value=fv,
            current_price=px,
            margin_of_safety=mos,
            verdict=verdict,
            bear_case=bear,
            base_case=base,
            bull_case=bull,
            wacc=wacc,
        ),
        quality=SimpleNamespace(
            yieldiq_score=score,
            moat=moat,
            roe=roe,
            roce=roce,
        ),
        insights=SimpleNamespace(ev_ebitda=ev_ebitda),
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not hasattr(
        asyncio, "run"
    ) else asyncio.run(coro)


def _call_og(fake) -> dict:
    """Invoke get_og_data with the og: cache empty and the
    analysis: cache pre-populated with `fake`. Bypasses coverage-tier
    service (returns None) so the assertions stay focused on the
    new fields."""
    # cache.get signature picked up an optional `version_keyed` kwarg
    # post-PR #243; accept and ignore so this mock keeps matching.
    def _cache_get(key, version_keyed=False):
        if key.startswith("og:"):
            return None
        if key.startswith("analysis:"):
            return fake
        return None

    # PR #236 added `request` and `background_tasks` params for
    # signed-in page-view telemetry. Pass stand-ins; user defaults to
    # None so the telemetry branch short-circuits and these mocks are
    # never actually exercised.
    fake_request = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/analysis/RELIANCE.NS/og-data"),
        headers={},
    )
    fake_bg = SimpleNamespace(add_task=lambda *a, **kw: None)

    # score-SSOT (2026-06-15): og-data now surfaces the CANONICAL
    # composite "YieldIQ Score" (= hex.overall × 10, what /prism shows)
    # instead of the quality pillar, falling back to the pillar only when
    # hex is unavailable. `_canonical_yieldiq_score` calls
    # hex_service.compute_hex_safe, which would otherwise hit the real DB
    # and make this unit test non-hermetic. Patch it to a fixed overall so
    # the composite is deterministic. overall=7.8 → composite score 78,
    # matching the fake's pillar value so every existing scenario/ratio
    # assertion in this module is unaffected.
    def _fake_hex(_ticker):
        return {"overall": 7.8}

    with patch("backend.routers.analysis.cache.get", side_effect=_cache_get), \
         patch("backend.routers.analysis.cache.set", return_value=None), \
         patch(
             "backend.services.hex_service.compute_hex_safe",
             side_effect=_fake_hex,
         ), \
         patch(
             "backend.services.coverage_tier_service.summary_for_og",
             return_value=None,
         ):
        return _run(get_og_data("RELIANCE.NS", fake_request, fake_bg))


# ── Test 1: happy path — all 7 new fields present ───────────────

def test_og_data_includes_all_new_fields():
    fake = _fake_analysis_response()
    og = _call_og(fake)

    # New scenario fields
    assert og["bear_case"] == 1100.0
    assert og["base_case"] == 1500.0
    assert og["bull_case"] == 1900.0

    # New ratio fields
    assert og["roe"] == 0.235
    assert og["roce"] == 0.295
    assert og["wacc"] == 0.115
    assert og["ev_ebitda"] == 14.8


# ── Test 2: existing fields still present (additive contract) ───

def test_og_data_existing_fields_unchanged():
    fake = _fake_analysis_response()
    og = _call_og(fake)
    for f in (
        "title", "description", "ticker", "score", "verdict",
        "fair_value", "price", "mos",
    ):
        assert f in og, f"existing field {f} missing — additive contract broken"
    assert og["fair_value"] == 1500.0
    assert og["price"] == 1200.0
    assert og["score"] == 78


# ── Test 3: bank-shaped payload (no ev_ebitda) returns None ─────

def test_og_data_missing_ev_ebitda_returns_none():
    fake = _fake_analysis_response(ev_ebitda=None)
    og = _call_og(fake)
    assert "ev_ebitda" in og
    assert og["ev_ebitda"] is None


def test_og_data_missing_roe_returns_none():
    fake = _fake_analysis_response(roe=None, roce=None)
    og = _call_og(fake)
    assert og["roe"] is None
    assert og["roce"] is None
    # wacc + scenarios still present and populated
    assert og["wacc"] == 0.115
    assert og["base_case"] == 1500.0


# ── Test 4: suspicious / zero-poison path nulls scenarios ───────
#
# The og-data handler already clamps fair_value, mos, and verdict to
# {0, 0, "data_limited"} when fv/px ratio > 3x or |mos| > 95.
# Scenarios are derived from the same DCF that produced the
# now-suspect FV, so they should also be suppressed. Ratios live on
# the non-DCF (ratios_service) code path and remain valid.

def test_og_data_suspicious_payload_nulls_scenarios_keeps_ratios():
    fake = _fake_analysis_response(
        fv=10000.0,   # 10k vs 1.2k price → ratio 8.3 → suspicious
        px=1200.0,
        mos=720.0,
    )
    og = _call_og(fake)
    assert og["verdict"] == "data_limited"
    assert og["fair_value"] == 0.0
    assert og["mos"] == 0.0
    # Scenarios nulled
    assert og["bear_case"] is None
    assert og["base_case"] is None
    assert og["bull_case"] is None
    # Ratios survive — different compute path
    assert og["roe"] == 0.235
    assert og["roce"] == 0.295
    assert og["wacc"] == 0.115
    assert og["ev_ebitda"] == 14.8


# ── Test 4b: exact-boundary clamp artifacts are suppressed ──────
#
# Regression lock for fix/prod-forbidden-values (2026-06-13). The
# +200% MoS display clamp + composite headline-FV cap back-project a
# headline fair_value of EXACTLY 3× cmp with mos == EXACTLY 200.0 for
# clamped names (observed on prod for ITC / LICI / MFSL — all at
# fv/cmp == 3.0000, mos == 200.0, with headline_fv > bull_case, an
# impossible ordering for a real DCF). The og-data sanity gate must
# treat these boundary values as suspicious — previously the strict
# `> 3.0` / `> 200` let them through and they reached the canary as
# forbidden_values violations on every PR.


def test_og_data_ratio_exactly_3x_is_suppressed():
    # fv/px == 3.0 exactly (MFSL on prod: 4737.0/1579.0 == 3.0). Strict
    # `> 3.0` served this verbatim; inclusive `>= 3.0` suppresses it.
    # Keep mos below the 200 ceiling so this isolates the ratio bound.
    fake = _fake_analysis_response(fv=4737.0, px=1579.0, mos=185.0)
    og = _call_og(fake)
    assert og["verdict"] == "data_limited"
    assert og["fair_value"] == 0.0
    assert og["mos"] == 0.0


def test_og_data_mos_exactly_200_is_suppressed():
    # |mos| == 200.0 exactly — the display-clamp ceiling that the
    # ITC/LICI/MFSL clamp class all land on. This is the bound that
    # catches the whole class: their ratios round to 3.000 for display
    # but are actually 2.9999996 (< 3.0) in float, so the ratio gate
    # alone would miss ITC/LICI — the mos boundary is the real catch.
    # Ratio kept inside (0.1, 3.0) to isolate the mos bound.
    fake = _fake_analysis_response(fv=2400.0, px=1200.0, mos=200.0)
    og = _call_og(fake)
    assert og["verdict"] == "data_limited"
    assert og["fair_value"] == 0.0
    assert og["mos"] == 0.0


def test_og_data_just_inside_boundary_still_served():
    # Guard against over-suppression: fv/cmp just under 3.0, |mos| just
    # under 200, and a well-ordered fv <= bull must remain a real,
    # served valuation.
    fake = _fake_analysis_response(
        fv=2390.0, px=1200.0, mos=99.0, bull=2500.0, base=2000.0,
    )
    og = _call_og(fake)
    assert og["verdict"] == "undervalued"
    assert og["fair_value"] == 2390.0
    assert og["mos"] == 99.0


def test_og_data_headline_above_bull_is_suppressed():
    # Headline fair_value > bull_case is impossible for a real DCF —
    # the clamp/cap class (ITC fv=855.3 > bull=780.23) lands here. This
    # is the float-robust discriminator that catches the < 3.0-ratio
    # members of the clamp class (ITC/LICI) regardless of ratio rounding.
    # Ratio (855.3/285.1 ≈ 2.9999996) and mos (185) both kept inside the
    # other two bounds so this isolates the bull-case guard.
    fake = _fake_analysis_response(
        fv=855.3, px=285.1, mos=185.0,
        bear=367.3, base=655.65, bull=780.23,
    )
    og = _call_og(fake)
    assert og["verdict"] == "data_limited"
    assert og["fair_value"] == 0.0
    assert og["mos"] == 0.0


# ── Test 5: canary field-name compatibility ─────────────────────
#
# scripts/canary_diff.py:extract_fields reads bear_case / base_case /
# bull_case / roe / roce / wacc / ev_ebitda directly off the top-level
# payload. Lock those exact key names so a future rename here
# silently re-breaks Gates 3+4.

def test_og_data_uses_canary_expected_field_names():
    fake = _fake_analysis_response()
    og = _call_og(fake)
    expected = {
        "bear_case", "base_case", "bull_case",
        "roe", "roce", "wacc", "ev_ebitda",
    }
    assert expected.issubset(og.keys()), (
        f"missing canary fields: {expected - set(og.keys())}"
    )


# ── Test 6: pipeline-failure fallback emits a structured log ────
#
# Pre-fix-247 the outer except in get_og_data was a bare
# `except: pass` that returned the SEO stub on ANY error with no
# log line. PR #673's LTIMINDTREE silent crash sat in that hole
# for hours before discovery because Railway/Sentry saw nothing.
# Lock the structured-log contract so a future regression that
# re-introduces the swallow fails this test instead of paging
# on-call on a Saturday.

def test_og_data_fallback_logs_exception(caplog):
    """When the analysis pipeline raises, the og-data handler must:
    1. Still return the SEO-stub shape (clients keep working).
    2. Emit a logger.exception call with structured ticker +
       exception_type fields so Railway log-search + Sentry can
       find it.
    """
    import logging

    fake_request = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/analysis/RELIANCE.NS/og-data"),
        headers={},
    )
    fake_bg = SimpleNamespace(add_task=lambda *a, **kw: None)

    def _boom(*_a, **_kw):
        raise RuntimeError("simulated upstream failure")

    # cache.get returns None for og: + analysis: so we fall through
    # to the live-compute path, which we patch to raise. That puts
    # us in the outer except handler.
    def _cache_get(key, version_keyed=False):
        return None

    with caplog.at_level(logging.ERROR, logger="yieldiq.analysis"), \
         patch("backend.routers.analysis.cache.get", side_effect=_cache_get), \
         patch("backend.routers.analysis.cache.set", return_value=None), \
         patch(
             "backend.routers.analysis.service.get_full_analysis",
             side_effect=_boom,
         ), \
         patch(
             "backend.services.analysis_cache_service.get_cached",
             return_value=None,
         ):
        og = _run(get_og_data("RELIANCE.NS", fake_request, fake_bg))

    # 1. Stub shape preserved — clients keep working.
    assert og["title"] == "RELIANCE.NS Stock Analysis | YieldIQ"
    assert "Free DCF valuation" in og["description"]

    # 2. logger.exception fired with the expected structured fields.
    matching = [
        r for r in caplog.records
        if r.name == "yieldiq.analysis"
        and r.getMessage() == "og_data_analysis_failed"
    ]
    assert matching, (
        "expected a 'og_data_analysis_failed' log record on the "
        "yieldiq.analysis logger — bare-except regression?"
    )
    rec = matching[-1]
    assert getattr(rec, "ticker", None) == "RELIANCE.NS"
    assert getattr(rec, "exception_type", None) == "RuntimeError"
    # logger.exception (not .error) attaches the active exception
    # so Sentry + Railway get the full stack trace.
    assert rec.exc_info is not None, (
        "logger.exception must be used (not .error) so the stack "
        "trace reaches Sentry"
    )
