"""
Unit tests for the 2026-05-18 FMCG brand-moat premium overlay
(PR feat/fmcg-brand-moat-overlay — see docs/design/fmcg-dcf-fix.md).

The overlay multiplies the generic-DCF fair value by a curated per-
ticker factor for the FMCG brand-permanence tail (NESTLEIND, BRITANNIA,
MARICO, GODREJCP, PIDILITIND, GILLETTE, TATACONSUM, DABUR, EMAMILTD,
JYOTHYLAB). Sector-gated to FMCG — a ticker that happens to be in the
curated dict but is classified into a non-FMCG sector NEVER gets the
premium (belt-and-braces against upstream sector mis-tags).

Covers (mirrors the four cases in the task brief):
  1. NESTLEIND with FMCG sector  → multiplier 1.45 applied.
  2. NESTLEIND with non-FMCG sector → no multiplier (sector gate holds).
  3. HUL (NOT in dict) with FMCG sector → no multiplier.
  4. TCS (NOT in dict, not FMCG) → no multiplier.

Plus sanity coverage for the helpers themselves so a future refactor
can't silently regress the lookup.
"""
from __future__ import annotations

from backend.services.analysis.constants import (
    BRAND_MOAT_PREMIUM_TICKERS,
    get_brand_moat_multiplier,
    is_fmcg_sector,
)


# ─────────────────────────────────────────────────────────────────
# 1. Curated dict shape — guards against accidental deletions /
#    renames in the constants file.
# ─────────────────────────────────────────────────────────────────

def test_dict_contains_expected_tickers():
    expected = {
        "NESTLEIND", "BRITANNIA", "MARICO", "GODREJCP", "PIDILITIND",
        "GILLETTE", "TATACONSUM", "DABUR", "EMAMILTD", "JYOTHYLAB",
    }
    assert expected <= set(BRAND_MOAT_PREMIUM_TICKERS.keys()), (
        f"missing tickers: {expected - set(BRAND_MOAT_PREMIUM_TICKERS.keys())}"
    )


def test_all_multipliers_in_sane_range():
    # Per design doc §3 / §4 the multipliers must sit in [1.10, 1.45].
    # Anything below 1.10 isn't worth the overlay's maintenance cost;
    # anything above 1.45 would imply the overlay is masking a separate
    # data-quality bug rather than recognising brand permanence.
    for ticker, mult in BRAND_MOAT_PREMIUM_TICKERS.items():
        assert 1.10 <= mult <= 1.45, (
            f"{ticker} multiplier {mult} outside [1.10, 1.45]"
        )


# ─────────────────────────────────────────────────────────────────
# 2. is_fmcg_sector gate
# ─────────────────────────────────────────────────────────────────

def test_is_fmcg_sector_positives():
    assert is_fmcg_sector("FMCG") is True
    assert is_fmcg_sector("fmcg") is True
    assert is_fmcg_sector(" FMCG ") is True
    assert is_fmcg_sector("Consumer Defensive") is True
    assert is_fmcg_sector("consumer staples") is True


def test_is_fmcg_sector_negatives():
    assert is_fmcg_sector(None) is False
    assert is_fmcg_sector("") is False
    assert is_fmcg_sector("IT") is False
    assert is_fmcg_sector("Banking") is False
    assert is_fmcg_sector("Pharma") is False
    assert is_fmcg_sector("Metals & Mining") is False


# ─────────────────────────────────────────────────────────────────
# 3. get_brand_moat_multiplier — dict lookup only (no sector gate).
#    The four task-brief cases are exercised against the COMBINED
#    behaviour (lookup × sector gate) further down.
# ─────────────────────────────────────────────────────────────────

def test_get_brand_moat_multiplier_curated_tickers():
    assert get_brand_moat_multiplier("NESTLEIND") == 1.45
    assert get_brand_moat_multiplier("NESTLEIND.NS") == 1.45
    assert get_brand_moat_multiplier("nestleind.ns") == 1.45
    assert get_brand_moat_multiplier("BRITANNIA") == 1.25
    assert get_brand_moat_multiplier("PIDILITIND.NS") == 1.35
    assert get_brand_moat_multiplier("GILLETTE.BO") == 1.25


def test_get_brand_moat_multiplier_unknown_returns_1():
    assert get_brand_moat_multiplier("HINDUNILVR") == 1.0
    assert get_brand_moat_multiplier("HINDUNILVR.NS") == 1.0
    assert get_brand_moat_multiplier("ITC") == 1.0
    assert get_brand_moat_multiplier("TCS.NS") == 1.0
    assert get_brand_moat_multiplier("RELIANCE.NS") == 1.0
    assert get_brand_moat_multiplier(None) == 1.0
    assert get_brand_moat_multiplier("") == 1.0


# ─────────────────────────────────────────────────────────────────
# 4. Combined behaviour — what service.py actually does.
#    Mirrors the gate at backend/services/analysis/service.py:
#        if is_fmcg_sector(sector) and get_brand_moat_multiplier(t) > 1.0:
#            iv *= mult
# ─────────────────────────────────────────────────────────────────


def _apply_gate(ticker: str, sector: str | None, iv: float) -> float:
    """Local mirror of the service.py gate so the test is independent
    of the service module (which would pull in a deep import graph).
    """
    if not is_fmcg_sector(sector):
        return iv
    mult = get_brand_moat_multiplier(ticker)
    if mult <= 1.0:
        return iv
    return iv * mult


def test_nestleind_fmcg_gated_multiplier_applied():
    # Case 1: NESTLEIND FMCG-gated → multiplier 1.45 applied.
    iv_in = 1000.0
    iv_out = _apply_gate("NESTLEIND.NS", "FMCG", iv_in)
    assert iv_out == 1450.0


def test_nestleind_non_fmcg_sector_no_multiplier():
    # Case 2: Hypothetical NESTLEIND wrongly classified as
    # sector="Industrials" → no multiplier (sector gate holds).
    iv_in = 1000.0
    iv_out = _apply_gate("NESTLEIND.NS", "Industrials", iv_in)
    assert iv_out == iv_in
    iv_out = _apply_gate("NESTLEIND.NS", "IT", iv_in)
    assert iv_out == iv_in
    iv_out = _apply_gate("NESTLEIND.NS", None, iv_in)
    assert iv_out == iv_in


def test_hul_not_in_dict_no_multiplier_even_with_fmcg_sector():
    # Case 3: HUL is NOT in the curated dict → no multiplier even
    # though sector matches. The whole point of the curated overlay
    # is to leave HUL/ITC/COLPAL untouched.
    iv_in = 2254.0
    iv_out = _apply_gate("HINDUNILVR.NS", "FMCG", iv_in)
    assert iv_out == iv_in


def test_tcs_not_fmcg_not_in_dict_no_multiplier():
    # Case 4: TCS — not in dict, not FMCG → no multiplier.
    iv_in = 3500.0
    iv_out = _apply_gate("TCS.NS", "IT", iv_in)
    assert iv_out == iv_in


# ─────────────────────────────────────────────────────────────────
# 5. Belt-and-braces: bear / base / bull all multiplied identically
#    so dispersion is preserved.
# ─────────────────────────────────────────────────────────────────

def test_bear_base_bull_dispersion_preserved():
    bear_in, base_in, bull_in = 800.0, 1000.0, 1400.0
    mult = get_brand_moat_multiplier("PIDILITIND.NS")  # 1.35
    assert mult == 1.35
    bear_out = bear_in * mult
    base_out = base_in * mult
    bull_out = bull_in * mult
    # Ratios must be unchanged within float precision.
    assert abs((bull_out / base_out) - (bull_in / base_in)) < 1e-9
    assert abs((bear_out / base_out) - (bear_in / base_in)) < 1e-9
