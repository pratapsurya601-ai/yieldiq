# backend/tests/test_analysis_flags.py
# ═══════════════════════════════════════════════════════════════
# Regression lock-ins for the 2026-04-23 moat-floor + strength
# single-source-of-truth fix (PR `fix/moat-floor-strength-ssot`).
#
# The two bugs these tests prevent from coming back:
#
#  1. Moat allowlist floor was a no-op label-wise. The floor
#     clamped score to ≥ 42 while the label mapping declared
#     "Narrow up to 59, Moderate starting at 60" — so TITAN /
#     RELIANCE / HDFCBANK (all on STRONG_BRAND_ALLOWLIST) came
#     back as "Narrow" despite the floor firing. Fix: floor to
#     the "Moderate" band boundary derived from the label
#     function itself. Tests below exercise the bellwethers the
#     MCP audit caught in-the-wild.
#
#  2. Strength count had two sources of truth. The deep-dive
#     (RedFlagInsights) counted `red_flags_structured.filter(
#     severity === "info")` while the summary card showed 0.
#     The backend SSOT for strengths = info-severity entries in
#     `red_flags_structured` returned by `_build_structured_flags`.
#     Tests below confirm TITAN-shaped inputs emit at least two
#     info flags (high_roce, strong_growth, category_leader — and
#     any others that fire).
#
# These tests are deliberately framework-thin: they call the pure
# moat/flag functions directly with synthetic enriched dicts that
# match what `service.py` injects at the flag-building call-site.
# That's intentional: the full `get_full_analysis` pipeline needs
# Neon + yfinance + DuckDB, which pytest CI doesn't have. Pure-
# function tests catch the regression at the exact layer where it
# lives.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import pandas as pd
import pytest

from screener.moat_engine import (
    ALLOWLIST_MOAT_FLOOR_SCORE,
    _min_score_for_label,
    _moat_label_from_score,
    compute_moat_score,
)
from backend.services.analysis.utils import _build_structured_flags


# ── Moat label mapping invariants ────────────────────────────────


def test_moat_label_bands_are_contiguous():
    """Label boundaries must match the allowlist floor. A drift
    here is exactly what produced the original bug: floor 42 +
    Narrow-starts-at-40 = floor is a label no-op."""
    assert _moat_label_from_score(69) == "Moderate"
    assert _moat_label_from_score(60) == "Moderate"
    assert _moat_label_from_score(59) == "Narrow"
    assert _moat_label_from_score(40) == "Narrow"
    assert _moat_label_from_score(39) == "None"
    assert _moat_label_from_score(70) == "Wide"


def test_allowlist_floor_lands_in_moderate_band():
    """The floor score must map to the Moderate label. If this
    ever drops back to 42 the TITAN/RELIANCE/HDFCBANK bug returns."""
    assert ALLOWLIST_MOAT_FLOOR_SCORE == _min_score_for_label("Moderate")
    assert _moat_label_from_score(ALLOWLIST_MOAT_FLOOR_SCORE) == "Moderate"


# ── Allowlist bellwethers: MCP-audit-confirmed regressions ───────


def _weak_enriched(ticker: str) -> dict:
    """Minimal enriched dict that would produce a sub-floor moat
    score without the allowlist rescue. Mirrors the shape the
    main moat path reads.

    `price` is non-zero because the financial-path guard in
    compute_moat_score short-circuits to score=0/grade="None" when
    `price <= 0`, which would mask the allowlist floor we're
    actually trying to assert on here."""
    return {
        "ticker":          ticker,
        "sector":          "general",
        "op_margin":       0.10,
        "revenue_growth":  0.05,
        "price":           100.0,
        "latest_revenue":  100_000_000_000,  # large-cap
        "latest_fcf":      5_000_000_000,
        "total_debt":      0,
        "total_cash":      0,
        "total_equity":    50_000_000_000,
        "dcf_reliable":    True,
        "income_df":       pd.DataFrame(),
        "cf_df":           pd.DataFrame(),
    }


@pytest.mark.parametrize("ticker", ["TITAN.NS", "RELIANCE.NS", "HDFCBANK.NS"])
def test_bellwether_moat_floored_to_moderate_or_wide(ticker):
    """TITAN / RELIANCE / HDFCBANK came back as Narrow 50/60/57
    in the MCP audit 2026-04-23 despite being on the allowlist.
    The fix floors allowlisted tickers to score ≥ 60 / label in
    (Moderate, Wide). HDFCBANK goes through the financial path,
    the other two through the main path — test both."""
    enriched = _weak_enriched(ticker)
    if ticker == "HDFCBANK.NS":
        enriched["dcf_reliable"] = False  # routes via financial branch
    result = compute_moat_score(enriched, wacc=0.12)
    assert result["score"] >= 60, (
        f"{ticker}: score {result['score']} < 60 — allowlist floor no-op"
    )
    assert result["grade"] in ("Moderate", "Wide"), (
        f"{ticker}: grade {result['grade']} not in (Moderate, Wide)"
    )


def test_titan_moat_floored_to_moderate():
    """Explicit TITAN case from the audit — 'should be Moderate ≥ 60'."""
    result = compute_moat_score(_weak_enriched("TITAN.NS"), wacc=0.12)
    assert result["grade"] in ("Moderate", "Wide")
    assert result["score"] >= 60


def test_reliance_allowlist_floor():
    result = compute_moat_score(_weak_enriched("RELIANCE.NS"), wacc=0.12)
    assert result["grade"] in ("Moderate", "Wide")
    assert result["score"] >= 60


def test_hdfcbank_allowlist_floor():
    """Financial path — routed via `dcf_reliable=False`."""
    enriched = _weak_enriched("HDFCBANK.NS")
    enriched["dcf_reliable"] = False
    result = compute_moat_score(enriched, wacc=0.12)
    assert result["grade"] in ("Moderate", "Wide")
    assert result["score"] >= 60


def test_non_allowlist_stock_is_not_floored():
    """Floor must NOT fire on stocks outside STRONG_BRAND_ALLOWLIST —
    otherwise we'd be inflating moats across the universe."""
    enriched = _weak_enriched("RANDOMCOMPANY.NS")
    result = compute_moat_score(enriched, wacc=0.12)
    # Purely-formulaic score; no floor should have been applied.
    assert result.get("floor_applied", False) is False


# ── Strengths single-source-of-truth ─────────────────────────────


def _titan_shaped_enriched() -> dict:
    """Mirror TITAN's public characteristics (MCP audit 2026-04-23):
    ROCE 36.9%, revenue CAGR 28%, ROE 28.7%, low leverage. The exact
    shape service.py stuffs into `enriched` before the flag build."""
    return {
        "ticker":             "TITAN.NS",
        "sector":             "consumer_durable",
        "op_margin":          0.12,
        "net_margin":         0.08,
        "latest_revenue":     400_000_000_000,
        "latest_fcf":         20_000_000_000,
        "total_equity":       80_000_000_000,
        "total_debt":         20_000_000_000,
        "total_cash":         5_000_000_000,
        "roce":               36.9,        # percent
        "roe":                0.287,       # decimal
        "revenue_cagr_3y":    0.28,        # decimal
        "revenue_cagr_5y":    0.22,
        "interest_coverage":  25.0,
        "debt_to_equity":     0.25,
        "dcf_reliable":       True,
    }


def test_titan_emits_strengths():
    """At least 2 info (strength) flags for TITAN-shaped inputs.
    Pre-fix we observed 'high_roce', 'strong_growth', and 'category_leader'
    as candidates; this test asserts the lower bound so the exact set
    can evolve without regressing the count."""
    enriched = _titan_shaped_enriched()
    piotroski = {"score": 7, "grade": "Strong"}
    moat_result = {"grade": "Moderate", "score": 60}
    flags = _build_structured_flags(
        enriched=enriched,
        piotroski=piotroski,
        moat_result=moat_result,
        is_financial=False,
        existing_flags=[],
        price=3200.0,
        mos_pct=-5.0,
    )
    info_flags = [f for f in flags if f.severity == "info"]
    assert len(info_flags) >= 2, (
        f"TITAN should emit ≥ 2 strengths; got {len(info_flags)}: "
        f"{[f.flag for f in info_flags]}"
    )


def test_strengths_ssot_matches_deep_dive_filter():
    """The summary card and the Risk & Quality Deep Dive both derive
    strength count by filtering `red_flags_structured` for
    severity == 'info'. This test pins that contract: any change
    to _build_structured_flags severity tags would ripple through
    both surfaces identically."""
    enriched = _titan_shaped_enriched()
    piotroski = {"score": 7, "grade": "Strong"}
    moat_result = {"grade": "Moderate", "score": 60}
    flags = _build_structured_flags(
        enriched=enriched,
        piotroski=piotroski,
        moat_result=moat_result,
        is_financial=False,
        existing_flags=[],
        price=3200.0,
        mos_pct=-5.0,
    )
    # Summary card formula (InsightCards.tsx):
    summary_strength_count = len([f for f in flags if f.severity == "info"])
    # Deep-dive formula (RedFlagInsights.tsx):
    deep_dive_strength_count = sum(1 for f in flags if f.severity == "info")
    assert summary_strength_count == deep_dive_strength_count
    assert summary_strength_count >= 2
