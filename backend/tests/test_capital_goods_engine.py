"""
Tests for the 2026-05-18 capital-goods sector engine (v113, PR
feat/capital-goods-sector-engine).

Covers:
  1. is_capital_goods() classifier: curated allow-list, sector match,
     hybrid-industrial-durables, negatives.
  2. _compute_fcf_base routes cap-goods tickers through the new
     `cap_goods_7y_wc_smoothed` candidate (signed median over a 7y
     window of CFO - |CapEx|).
  3. nopat_proxy fcf_conv override 0.85 → 0.60 for cap-goods tickers.
  4. Hyper-growth terminal fade (KAYNES / SIEMENS / cap-goods with
     rev_cagr_3y > 0.30) pulls terminal_g down to
     min(rev_cagr_3y × 0.5, 0.06).
  5. BHEL regime-change override restricts the FCF window to
     CAPITAL_GOODS_REGIME_CHANGE['BHEL'] = 2023.
  6. Sector mistag overrides (TIMKEN / SCHAEFFLER / GRINDWELL / KAYNES
     → "Capital Goods").
  7. Non-cap-goods (TCS) is byte-identical — no new candidate, no
     terminal change.
  8. 7y window with < 7 years available falls back gracefully (still
     produces the cap_goods candidate as long as ≥ 3 years exist).
  9. Per-ticker overrides (BHEL caveat, KAYNES terminal_growth_override).
"""
from __future__ import annotations

import pandas as pd
import pytest

from backend.services.analysis.constants import (
    is_capital_goods,
    CAPITAL_GOODS_TICKERS,
    CAPITAL_GOODS_REGIME_CHANGE,
    CAPITAL_GOODS_HYPER_GROWTH,
    HYBRID_INDUSTRIAL_DURABLES,
    TICKER_SECTOR_OVERRIDES,
)
from backend.services.analysis.ticker_overrides import (
    TICKER_OVERRIDES,
    get_override,
)
from models.forecaster import (
    _compute_fcf_base,
    FCFForecaster,
    CAPITAL_GOODS_WINDOW_YEARS,
    CAPITAL_GOODS_HYPER_GROWTH_CAGR,
    CAPITAL_GOODS_HYPER_GROWTH_TERMINAL_CAP,
    TERMINAL_FADE_G,
)


# ─────────────────────────────────────────────────────────────────
# 1. Classifier
# ─────────────────────────────────────────────────────────────────

def test_is_capital_goods_curated_allow_list():
    """Curated allow-list members all classify as capital-goods."""
    for tkr in ("LT", "SIEMENS", "ABB", "THERMAX", "CUMMINSIND",
                "BHEL", "KEC", "ELGIEQUIP", "TIMKEN", "SCHAEFFLER",
                "GRINDWELL", "KAYNES", "ISGEC", "GMMPFAUDLR"):
        assert is_capital_goods(tkr), f"{tkr} must classify as cap-goods"
        assert is_capital_goods(f"{tkr}.NS"), f"{tkr}.NS must classify"


def test_is_capital_goods_hybrid_durables():
    """HYBRID_INDUSTRIAL_DURABLES (HAVELLS / VOLTAS / BLUESTARCO) also
    pick up cap-goods FCF treatment so their B2B project tails get the
    WC-smoothed anchor — even though sector stays 'Consumer Durables'.
    """
    for tkr in ("HAVELLS", "VOLTAS", "BLUESTARCO"):
        assert is_capital_goods(tkr), (
            f"{tkr} (hybrid industrial durable) must classify"
        )


def test_is_capital_goods_sector_keyword_match():
    """Sector keyword fallback handles unenumerated names."""
    assert is_capital_goods("UNKNOWN", sector="Capital Goods")
    assert is_capital_goods("UNKNOWN", sector="Industrials")
    assert is_capital_goods("UNKNOWN", sector="Engineering")
    assert is_capital_goods("UNKNOWN", sector="Heavy Electrical Equipment")
    assert is_capital_goods("UNKNOWN", industry="Specialty Industrial Machinery")
    assert is_capital_goods("UNKNOWN", industry="Bearings")
    assert is_capital_goods("UNKNOWN", industry="Abrasives")


def test_is_capital_goods_negatives():
    """Non-cap-goods (banks, IT, FMCG, pharma) must NOT classify."""
    assert not is_capital_goods("TCS")
    assert not is_capital_goods("INFY")
    assert not is_capital_goods("HDFCBANK")
    assert not is_capital_goods("HINDUNILVR")
    assert not is_capital_goods("SUNPHARMA")
    assert not is_capital_goods("UNKNOWN", sector="IT Services")
    assert not is_capital_goods("UNKNOWN", sector="Banking")
    assert not is_capital_goods(None)
    assert not is_capital_goods("")


# ─────────────────────────────────────────────────────────────────
# 2. Sector-mistag overrides
# ─────────────────────────────────────────────────────────────────

def test_sector_mistag_overrides_present():
    """TIMKEN / SCHAEFFLER / GRINDWELL / KAYNES forced to Capital Goods."""
    for tkr in ("TIMKEN", "SCHAEFFLER", "GRINDWELL", "KAYNES"):
        assert TICKER_SECTOR_OVERRIDES.get(tkr) == "Capital Goods", (
            f"{tkr} must be re-sectored to Capital Goods"
        )
        assert TICKER_SECTOR_OVERRIDES.get(f"{tkr}.NS") == "Capital Goods"


def test_voltas_bluestarco_havells_stay_consumer_durables():
    """Per design doc §4 these stay tagged Consumer Durables (yfinance
    is right) — they get cap-goods FCF treatment via the hybrid flag,
    not via TICKER_SECTOR_OVERRIDES. Verify no override leaked in."""
    for tkr in ("VOLTAS", "BLUESTARCO", "HAVELLS"):
        assert tkr not in TICKER_SECTOR_OVERRIDES, (
            f"{tkr} must NOT be force-tagged Capital Goods (design §4)"
        )


# ─────────────────────────────────────────────────────────────────
# 3. cap_goods_7y_wc_smoothed candidate
# ─────────────────────────────────────────────────────────────────

def _lt_like_enriched(
    cfo_history,
    capex_history,
    latest_revenue: float = 2.0e12,
    op_margin: float = 0.10,
    ticker: str = "LT",
    sector: str = "Capital Goods",
    n_years: int = 7,
):
    """Build an LT-shaped enriched dict with custom CFO + capex history."""
    years = list(range(2025 - n_years + 1, 2026))
    cf_df = pd.DataFrame({
        "year":  years,
        "cfo":   cfo_history,
        "capex": capex_history,
        "fcf":   [c - abs(cx) for c, cx in zip(cfo_history, capex_history)],
    })
    income_df = pd.DataFrame({
        "year":      years,
        "revenue":   [latest_revenue * 0.9] * n_years,
        "op_margin": [op_margin] * n_years,
    })
    return {
        "ticker": ticker,
        "latest_fcf": cf_df["fcf"].iloc[-1],
        "latest_revenue": latest_revenue,
        "op_margin": op_margin,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": sector,
    }


def test_capital_goods_7y_wc_smoothed_candidate_fires():
    """LT-like ticker with lumpy CFO + capex history produces the new
    cap_goods_7y_wc_smoothed candidate."""
    # 7 years: alternating WC build / unwind years
    cfo_history   = [3e10, -5e9, 4e10, 1e10, 5e10, 2e10, 3.5e10]
    capex_history = [1e10,  1.2e10, 1e10, 1.5e10, 1.3e10, 1.4e10, 1.5e10]
    enriched = _lt_like_enriched(cfo_history, capex_history)
    base, method = _compute_fcf_base(enriched)

    cands = enriched.get("_fcf_candidates", {})
    assert "cap_goods_7y_wc_smoothed" in cands, (
        f"cap-goods branch must produce cap_goods_7y_wc_smoothed "
        f"candidate (got {list(cands.keys())})"
    )
    assert enriched.get("_capital_goods_used") is True
    assert enriched.get("_is_capital_goods") is True
    assert enriched.get("_capital_goods_window_years") == 7
    assert base > 0
    assert "capital_goods" in method.lower(), (
        f"method must record cap-goods strategy (got {method!r})"
    )


def test_capital_goods_short_history_fallback():
    """Cap-goods ticker with < 7 years of cf_df rows still fires the
    branch as long as ≥ 3 years are present (KAYNES IPO'd Nov 2022)."""
    # Only 4 years (post-IPO style)
    cfo_history   = [1e9, 2e9, 3e9, 4e9]
    capex_history = [5e8, 7e8, 1e9, 1.2e9]
    enriched = _lt_like_enriched(
        cfo_history, capex_history,
        latest_revenue=2e10, op_margin=0.15,
        ticker="KAYNES", sector="Capital Goods",
        n_years=4,
    )
    base, method = _compute_fcf_base(enriched)
    cands = enriched.get("_fcf_candidates", {})
    assert "cap_goods_7y_wc_smoothed" in cands, (
        f"cap-goods branch must fall back to available years "
        f"(got {list(cands.keys())})"
    )
    assert enriched.get("_capital_goods_window_years") == 4
    assert base > 0


def test_capital_goods_too_few_years_no_candidate():
    """Cap-goods ticker with < 3 years of cf_df rows does NOT produce
    the candidate (graceful — falls through to generic median path)."""
    cfo_history   = [1e9, 2e9]
    capex_history = [5e8, 7e8]
    enriched = _lt_like_enriched(
        cfo_history, capex_history,
        latest_revenue=2e10, op_margin=0.15,
        ticker="KAYNES", sector="Capital Goods",
        n_years=2,
    )
    _compute_fcf_base(enriched)
    cands = enriched.get("_fcf_candidates", {})
    assert "cap_goods_7y_wc_smoothed" not in cands


def test_capital_goods_signed_median_preserves_negative_years():
    """Signed median must keep negative-cycle years in the window
    (NOT positive-only) — that's the cap-goods design point."""
    # 7 years with 3 negative cycle-bottom years
    cfo_history   = [-5e9, -8e9, -2e9, 5e10, 6e10, 3e10, 4e10]
    capex_history = [1e10, 1.2e10, 1e10, 1.5e10, 1.3e10, 1.4e10, 1.5e10]
    enriched = _lt_like_enriched(cfo_history, capex_history)
    _compute_fcf_base(enriched)
    cands = enriched.get("_fcf_candidates", {})
    cg_val = cands.get("cap_goods_7y_wc_smoothed")
    assert cg_val is not None
    # Build expected signed median for cross-check
    expected = pd.Series(
        [c - abs(cx) for c, cx in zip(cfo_history, capex_history)]
    ).median()
    assert abs(cg_val - expected) < 1e-3, (
        f"signed median mismatch: cap-goods={cg_val}, expected={expected}"
    )


# ─────────────────────────────────────────────────────────────────
# 4. nopat fcf_conv override = 0.60 for cap-goods
# ─────────────────────────────────────────────────────────────────

def test_cap_goods_nopat_fcf_conv_is_0p60():
    """The nopat_proxy candidate for cap-goods uses fcf_conv=0.60
    (from sector_benchmarks.py::capital_goods), not the asset-light
    0.85 default. Cross-checked numerically via the candidate value."""
    # Margin >= 0.15 so default fcf_conv would be 0.85
    cfo_history   = [3e10, 3e10, 3e10, 3e10, 3e10, 3e10, 3e10]
    capex_history = [1e10, 1e10, 1e10, 1e10, 1e10, 1e10, 1e10]
    enriched = _lt_like_enriched(
        cfo_history, capex_history,
        latest_revenue=2e12, op_margin=0.15,
    )
    _compute_fcf_base(enriched)
    nopat = enriched["_fcf_candidates"].get("nopat_proxy", 0)
    # nopat = 2e12 × 0.15 × (1-0.25) = 2.25e11; with fcf_conv=0.60 → 1.35e11
    expected_cap_goods = 2e12 * 0.15 * (1 - 0.25) * 0.60
    assert abs(nopat - expected_cap_goods) / expected_cap_goods < 0.01, (
        f"cap-goods nopat_proxy must use fcf_conv=0.60 (got {nopat}, "
        f"expected ~{expected_cap_goods})"
    )


# ─────────────────────────────────────────────────────────────────
# 5. BHEL regime-change override
# ─────────────────────────────────────────────────────────────────

def test_bhel_regime_change_truncates_fcf_window():
    """BHEL's cf_df is truncated to year >= 2023 so the pre-2023
    structural-decline years don't drag the median down."""
    assert CAPITAL_GOODS_REGIME_CHANGE.get("BHEL") == 2023
    # 10 years of cf_df: 2016-2025. Pre-2023 years are loss-making.
    years = list(range(2016, 2026))
    cfo = [-5e9, -4e9, -3e9, -6e9, -2e9, -1e9, 1e9, 5e9, 8e9, 1e10]
    capex = [3e9] * 10
    cf_df = pd.DataFrame({
        "year": years, "cfo": cfo, "capex": capex,
        "fcf": [c - cx for c, cx in zip(cfo, capex)],
    })
    income_df = pd.DataFrame({
        "year": years,
        "revenue": [3e11] * 10,
        "op_margin": [0.05] * 10,
    })
    enriched = {
        "ticker": "BHEL",
        "latest_fcf": 7e9,
        "latest_revenue": 3e11,
        "op_margin": 0.05,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": "Capital Goods",
    }
    _compute_fcf_base(enriched)
    assert enriched.get("_capital_goods_regime_cutoff") == 2023
    cg_val = enriched["_fcf_candidates"].get("cap_goods_7y_wc_smoothed")
    assert cg_val is not None
    # Post-2023 rows (year>=2023): 2023, 2024, 2025 → cfo=[5,8,10]e9,
    # capex=[3,3,3]e9 → (CFO-|capex|) = [2,5,7]e9; signed median = 5e9.
    expected = pd.Series([2e9, 5e9, 7e9]).median()
    assert abs(cg_val - expected) < 1e6, (
        f"BHEL post-regime median mismatch: got {cg_val}, expected {expected}"
    )


# ─────────────────────────────────────────────────────────────────
# 6. Hyper-growth terminal fade
# ─────────────────────────────────────────────────────────────────

def test_hyper_growth_terminal_fade_kaynes():
    """KAYNES (cap-goods + rev_cagr_3y > 0.30) gets terminal_g pulled
    down to min(cagr × 0.5, 0.06) by the hyper-growth branch in
    FCFForecaster.predict()."""
    # Build minimal enriched dict for predict()
    cfo = [5e8, 1e9, 2e9, 3e9, 4e9]
    capex = [3e8, 5e8, 7e8, 9e8, 1e9]
    years = list(range(2021, 2026))
    cf_df = pd.DataFrame({
        "year": years, "cfo": cfo, "capex": capex,
        "fcf": [c - cx for c, cx in zip(cfo, capex)],
    })
    income_df = pd.DataFrame({
        "year": years,
        "revenue": [1e10] * 5,
        "op_margin": [0.10] * 5,
    })
    enriched = {
        "ticker": "KAYNES",
        "latest_fcf": 3e9,
        "latest_revenue": 5e10,
        "op_margin": 0.10,
        "revenue_growth": 0.35,
        "fcf_growth": 0.40,
        "revenue_cagr_3y": 0.405,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": "Capital Goods",
        "dcf_reliable": True,
    }
    fc = FCFForecaster()
    out = fc.predict(enriched)
    assert out["reliable"] is True

    # After the hyper-growth branch fires, the stash should record the
    # capped terminal_g at min(0.405 × 0.5, 0.06) = 0.06.
    capped = enriched.get("_capital_goods_hyper_growth_terminal_g")
    assert capped is not None, (
        "hyper-growth branch must stash the capped terminal_g"
    )
    assert capped <= CAPITAL_GOODS_HYPER_GROWTH_TERMINAL_CAP + 1e-9
    # For KAYNES: min(0.405 × 0.5, 0.06) = 0.06 (cap binds, not the half-cagr).
    assert abs(capped - CAPITAL_GOODS_HYPER_GROWTH_TERMINAL_CAP) < 1e-9, (
        f"KAYNES hyper-growth terminal_g must equal cap=0.06 "
        f"(got {capped})"
    )


def test_hyper_growth_not_fired_for_modest_growers():
    """LT-style cap-goods name with rev_cagr_3y = 0.15 (below the 0.30
    threshold) does NOT trigger the hyper-growth fade."""
    cfo = [3e10] * 7
    capex = [1e10] * 7
    years = list(range(2019, 2026))
    cf_df = pd.DataFrame({
        "year": years, "cfo": cfo, "capex": capex,
        "fcf": [c - cx for c, cx in zip(cfo, capex)],
    })
    income_df = pd.DataFrame({
        "year": years,
        "revenue": [2e12] * 7,
        "op_margin": [0.10] * 7,
    })
    enriched = {
        "ticker": "LT",
        "latest_fcf": 2e10,
        "latest_revenue": 2e12,
        "op_margin": 0.10,
        "revenue_growth": 0.16,
        "fcf_growth": 0.10,
        "revenue_cagr_3y": 0.163,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": "Capital Goods",
        "dcf_reliable": True,
    }
    fc = FCFForecaster()
    fc.predict(enriched)
    assert enriched.get("_capital_goods_hyper_growth_terminal_g") is None


# ─────────────────────────────────────────────────────────────────
# 7. Non-cap-goods (TCS) — byte-identical (no new candidate)
# ─────────────────────────────────────────────────────────────────

def test_tcs_unchanged_no_capital_goods_candidate():
    """TCS (IT services, not cap-goods) must NOT pick up the new
    cap_goods_7y_wc_smoothed candidate. Regression guard."""
    cfo = [4e11, 4.5e11, 5e11, 5.5e11, 6e11]
    capex = [3e10] * 5
    years = list(range(2021, 2026))
    cf_df = pd.DataFrame({
        "year": years, "cfo": cfo, "capex": capex,
        "fcf": [c - cx for c, cx in zip(cfo, capex)],
    })
    income_df = pd.DataFrame({
        "year": years,
        "revenue": [2.5e12] * 5,
        "op_margin": [0.25] * 5,
    })
    enriched = {
        "ticker": "TCS",
        "latest_fcf": 6e11 - 3e10,
        "latest_revenue": 2.5e12,
        "op_margin": 0.25,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": "IT",
    }
    _compute_fcf_base(enriched)
    cands = enriched.get("_fcf_candidates", {})
    assert "cap_goods_7y_wc_smoothed" not in cands, (
        f"TCS must not get cap-goods candidate (got {list(cands.keys())})"
    )
    assert enriched.get("_is_capital_goods") is False
    assert enriched.get("_capital_goods_used") is False


# ─────────────────────────────────────────────────────────────────
# 8. Per-ticker overrides (BHEL + KAYNES caveats)
# ─────────────────────────────────────────────────────────────────

def test_bhel_override_present():
    entry = get_override("BHEL")
    assert entry is not None
    assert "regime change" in entry["model_caveat"].lower() or \
           "post-2023" in entry["model_caveat"].lower()
    # alias .NS resolves to the same entry
    assert get_override("BHEL.NS") is entry


def test_kaynes_override_terminal_growth_cap():
    entry = get_override("KAYNES")
    assert entry is not None
    assert entry.get("terminal_growth_override") == 0.06, (
        "KAYNES must have terminal_growth_override = 0.06 (cap-goods "
        "hyper-growth cap)"
    )
    assert get_override("KAYNES.NS") is entry
    assert get_override("KAYNESTECH") is entry


def test_kaynes_hyper_growth_set_membership():
    assert "KAYNES" in CAPITAL_GOODS_HYPER_GROWTH


def test_sector_mistag_caveat_strings_present():
    for tkr in ("TIMKEN", "SCHAEFFLER", "GRINDWELL"):
        entry = get_override(tkr)
        assert entry is not None, f"{tkr} must have an override entry"
        assert "re-sectored" in entry["model_caveat"].lower() or \
               "capital goods" in entry["model_caveat"].lower()


# ─────────────────────────────────────────────────────────────────
# 9. Constants — sanity
# ─────────────────────────────────────────────────────────────────

def test_capital_goods_constants_sanity():
    assert CAPITAL_GOODS_WINDOW_YEARS == 7
    assert CAPITAL_GOODS_HYPER_GROWTH_CAGR == 0.30
    assert CAPITAL_GOODS_HYPER_GROWTH_TERMINAL_CAP == 0.06
    assert isinstance(CAPITAL_GOODS_TICKERS, set)
    assert "LT" in CAPITAL_GOODS_TICKERS
    assert "KAYNES" in CAPITAL_GOODS_TICKERS
    assert isinstance(HYBRID_INDUSTRIAL_DURABLES, set)
    assert "VOLTAS" in HYBRID_INDUSTRIAL_DURABLES
