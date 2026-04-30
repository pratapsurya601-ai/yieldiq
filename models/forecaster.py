# models/forecaster.py
# ═══════════════════════════════════════════════════════════════
# AI FCF FORECASTER v4 — Fixed Growth Caps + Realistic Blending
# ═══════════════════════════════════════════════════════════════
# Root-cause fixes vs v3:
#   1. MAX_FCF_GROWTH raised 20%→35% (pharma/growth stocks need room)
#   2. Rule-based mean-reversion target raised 7%→10% (India GDP+inf)
#   3. Conservative blend weight reduced: rule 60%→40%, more weight
#      to actual historical data (lr 20%→30%, rf 20%→30%)
#   4. _rule_based_growth now uses AVERAGE not MIN of rev/fcf growth
#      — taking MIN was artificially destroying high-quality companies
#   5. FCF proxy median margin cap raised 5%→15% for asset-light cos
#   6. FADE_K reduced 0.35→0.25 so high-growth stocks don't decay too fast
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import pickle, requests
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from utils.config import FORECAST_YEARS, MODEL_SAVE_PATH
from utils.logger import get_logger

log = get_logger(__name__)

# ── Growth constraints ─────────────────────────────────────────
MAX_FCF_GROWTH  =  0.35   # 35% hard cap (was 20% — too tight for pharma/IT)
MIN_FCF_GROWTH  = -0.15   # -15% floor
TERMINAL_FADE_G =  0.04   # 4% terminal growth (was 3% — India long-run ~4%)
FADE_K          =  0.25   # slower fade (was 0.35 — high-growth cos punished too early)
BLEND_WEIGHTS   = np.array([0.30, 0.30, 0.40])  # lr, rf, rule — less conservative bias


def _clamp(g: float) -> float:
    return float(np.clip(g, MIN_FCF_GROWTH, MAX_FCF_GROWTH))


def _exponential_fade(t: int, g0: float, g_terminal: float = TERMINAL_FADE_G) -> float:
    """g(t) = g_T + (g_0 - g_T) × exp(-k × t)"""
    return g_terminal + (g0 - g_terminal) * np.exp(-FADE_K * t)


def _projection_horizons(
    ticker: str | None,
    sector: str | None = None,
    industry: str | None = None,
    moat_grade: str | None = None,
) -> tuple[int, int, float]:
    """Return ``(explicit_years, fade_years, terminal_g_adjustment)``
    for the DCF projection.

    Default (10y total, 0bps terminal adjustment): 5y explicit growth
    at base_growth held flat, then 5y exponential fade to terminal.

    Wide-moat compounder (15y total, -50bps terminal): 10y explicit
    growth at base_growth, then 5y fade to terminal_growth - 0.5%.
    The longer explicit period reflects the durability of the moat
    (brand / distribution / scale / IP); the 50bps terminal haircut
    reflects that 15 years already captures more compounding so the
    long-tail growth probability declines.
    """
    try:
        from backend.services.analysis.constants import is_wide_moat_compounder
    except Exception:
        # Defensive: if constants module is unavailable for any reason
        # (e.g. running forecaster.py in isolation in a test harness
        # without the backend package on path) fall back to defaults.
        return (5, 5, 0.0)
    if is_wide_moat_compounder(ticker, sector, industry, moat_grade):
        return (10, 5, -0.005)
    return (5, 5, 0.0)


def _compute_fcf_base(enriched: dict) -> tuple[float, str]:
    """
    Get the best FCF base estimate used as the anchor of the two-stage
    projection.

    Default strategy: use the HIGHEST CREDIBLE estimate via a median of
    [latest_fcf, nopat_proxy, max_recent_fcf] with a 60%-of-NOPAT floor.
    For capital-cycle industries (pharma, manufacturing), one bad capex
    year drags a naive median down, so the NOPAT proxy gives the true
    earning power.

    Cyclical override (added after the BPCL 2026-04 incident — DCF FV
    Rs.716 vs analyst consensus Rs.400-500): for commodity-cycle sectors
    (oil_gas, metals, cement, chemicals, auto, sugar, airlines) the peak
    year (e.g. BPCL FY24 Rs.26,390 Cr from inventory gains) can propagate
    via max_recent_fcf and nopat (peak-margin) into the terminal. For
    these sectors we replace max_recent_fcf with the 5-year median of
    positive FCFs (2-year trimmed-mean fallback) and cap the final base
    to that value. Stable businesses keep the existing behaviour.
    """
    latest_fcf     = enriched.get("latest_fcf", 0)
    latest_revenue = enriched.get("latest_revenue", 0)
    op_margin      = enriched.get("op_margin", 0)
    cf_df          = enriched.get("cf_df", pd.DataFrame())
    income_df      = enriched.get("income_df", pd.DataFrame())
    ticker         = enriched.get("ticker", "?")
    tax_rate       = 0.25

    candidates = {}

    # ── Candidate 1: Latest FCF (strongest signal if positive) ──
    if latest_fcf > 0:
        # Sanity: FCF/revenue < 0.5% on a profitable large-cap (revenue > ₹1,000 Cr)
        # is almost always a unit bug — e.g. raw-USD freeCashflow leaking through
        # a NULL-annual-row merge in data_service.py. Reject and fall back to
        # nopat_proxy / median_recent_fcf candidates.
        if latest_revenue > 1e10 and (latest_fcf / latest_revenue) < 0.005:
            log.warning(
                "[%s] rejecting suspicious latest_fcf=%.2e vs revenue=%.2e "
                "(ratio<0.5%% — likely USD-as-rupees unit leak)",
                ticker, latest_fcf, latest_revenue,
            )
        else:
            candidates["latest_fcf"] = latest_fcf

    # ── Candidate 2: Max of last 3 positive FCF years ──────────
    # MAX not median — a company's best recent FCF year reflects
    # its true cash generation when capex is normalised
    if not cf_df.empty and "fcf" in cf_df.columns:
        pos_fcfs = cf_df["fcf"][cf_df["fcf"] > 0].tail(4)
        if len(pos_fcfs) >= 1:
            candidates["max_recent_fcf"] = float(pos_fcfs.max())
        if len(pos_fcfs) >= 2:
            candidates["median_recent_fcf"] = float(pos_fcfs.median())

    # ── Candidate 3: NOPAT proxy — THE MOST RELIABLE FOR PHARMA ─
    # NOPAT = EBIT × (1 - tax). FCF ≈ NOPAT for asset-light businesses
    # because D&A ≈ maintenance capex in steady state
    # Conversion factor: 0.85 (conservative) — pharma has low net capex
    # GUARD: Only use NOPAT proxy for companies with meaningful revenue
    # (≥ ₹100 Cr). Penny/shell stocks have tiny revenue but non-zero
    # op_margin which can produce a deceptively large NOPAT base.
    MIN_REVENUE_FOR_NOPAT = 1_000_000_000  # ₹100 Cr minimum
    # ── Margin normalisation: trailing 3-year average ──────────
    # Anchor the NOPAT proxy on a trailing 3-year average operating
    # margin instead of the (potentially peak) TTM margin. Mid-caps
    # were systematically over-valued because a single TTM margin
    # spike was being projected forward forever. Asymmetric guard:
    # if TTM > 130% of the 3y avg, we treat the TTM as cyclical and
    # fade the implied FCF base back toward the 3y-avg base over
    # years 1-3 of the projection (handled in FCFForecaster.predict).
    margin_3y_avg: float | None = None
    margin_for_nopat = op_margin
    fade_to_3y = False
    try:
        if not income_df.empty and "op_margin" in income_df.columns:
            _om_hist = income_df["op_margin"].dropna()
            # Use the most recent up-to-3 historical years
            _om_recent = _om_hist.tail(3)
            if len(_om_recent) >= 3:
                margin_3y_avg = float(_om_recent.mean())
                margin_for_nopat = margin_3y_avg
                if op_margin > 0 and margin_3y_avg > 0 and op_margin > 1.30 * margin_3y_avg:
                    fade_to_3y = True
                    log.info(
                        f"[{ticker}] TTM op_margin {op_margin:.1%} > 130% of 3y avg "
                        f"{margin_3y_avg:.1%} — fading to 3y avg over years 1-3"
                    )
    except Exception:
        pass
    # Stash for predict() to apply the margin fade on the projection.
    enriched["_margin_ttm"]    = float(op_margin or 0.0)
    enriched["_margin_3y_avg"] = float(margin_3y_avg) if margin_3y_avg else 0.0
    enriched["_margin_fade_to_3y"] = bool(fade_to_3y)

    if margin_for_nopat > 0 and latest_revenue >= MIN_REVENUE_FOR_NOPAT:
        nopat    = latest_revenue * margin_for_nopat * (1 - tax_rate)
        # FCF conversion based on the margin we are using (3y avg or TTM fallback)
        fcf_conv = 0.85 if margin_for_nopat >= 0.15 else 0.70

        # Fix 1: Use normalised capex if M&A spike was detected
        norm_capex_pct = enriched.get("norm_capex_pct", None)
        if norm_capex_pct is not None:
            # Normalised FCF = NOPAT - normalised_capex + D&A
            sector = enriched.get("sector", "general")
            da_pct = 0.035  # default D&A
            try:
                from models.industry_wacc import INDUSTRY_WACC
                da_pct = INDUSTRY_WACC.get(sector, {}).get("depreciation_pct", 0.035)
            except Exception:
                pass
            norm_fcf = nopat - (latest_revenue * norm_capex_pct) + (latest_revenue * da_pct)
            if norm_fcf > 0:
                candidates["normalised_capex_fcf"] = norm_fcf
                log.info(f"[{ticker}] Using normalised capex FCF: ₹{norm_fcf/1e9:.1f}B "
                         f"(capex {norm_capex_pct:.1%} of rev)")

        candidates["nopat_proxy"] = nopat * fcf_conv

    # ── Candidate 3b: Pharma R&D-adjusted FCF ──────────────────
    # R&D is investment, not recurring opex. 60% is growth R&D (pipeline),
    # 40% is maintenance R&D. Adding back growth R&D gives economic earnings.
    # This is standard sell-side practice (EV/EBITDA ignores R&D).
    _sector = enriched.get("sector", "general")
    if _sector == "pharma" and op_margin > 0 and latest_revenue >= MIN_REVENUE_FOR_NOPAT:
        try:
            from models.industry_wacc import INDUSTRY_WACC as _IW
            _rd_pct     = _IW.get("pharma", {}).get("rd_pct_revenue", 0.08)
            _growth_rd  = latest_revenue * _rd_pct * 0.60  # 60% = growth R&D
            _econ_nopat = latest_revenue * op_margin * (1 - tax_rate) + _growth_rd * (1 - tax_rate)
            candidates["pharma_rd_adjusted"] = _econ_nopat * 0.80  # conservative 80% conversion
        except Exception:
            pass

    # ── Candidate 4: 75th percentile historical FCF margin ──────
    if not cf_df.empty and not income_df.empty:
        try:
            merged = pd.merge(
                cf_df[["year","fcf"]], income_df[["year","revenue"]],
                on="year", how="inner"
            )
            merged = merged[(merged["revenue"] > 0) & (merged["fcf"] > 0)]
            if len(merged) >= 2:
                margins    = merged["fcf"] / merged["revenue"]
                p75_margin = float(np.clip(float(np.percentile(margins, 75)), 0.03, 0.25))
                candidates["hist_p75_margin"] = latest_revenue * p75_margin
        except Exception:
            pass

    if not candidates:
        log.debug(f"[{ticker}] No valid FCF base — unreliable")
        return 0.0, "unreliable_loss_company"

    log.debug(f"[{ticker}] FCF candidates: { {k: f'₹{v/1e7:.0f}Cr' for k,v in candidates.items()} }")

    # ── Selection strategy ──────────────────────────────────────
    # Use the NOPAT proxy as the anchor (most reliable for earnings-based cos)
    # Then take the MAX of (nopat_proxy, latest_fcf, median_recent_fcf)
    # This way one bad capex year cannot collapse the valuation

    nopat_val  = candidates.get("nopat_proxy", 0)
    latest_val = candidates.get("latest_fcf", 0)
    max_val    = candidates.get("max_recent_fcf", 0)
    median_val = candidates.get("median_recent_fcf", 0)
    p75_val    = candidates.get("hist_p75_margin", 0)

    # ── Cyclical normalisation (option (a) — sector-gated 5y median) ─
    # Ref: BPCL FY24 DCF returned FV Rs.716 vs consensus Rs.400-500. The
    # FY24 FCF of Rs.26,390 Cr (a 2-6x outlier from inventory gains on
    # falling crude) leaked into `max_recent_fcf` and — because the
    # primary-selection took the median of [latest, nopat, max] — ended
    # up dominating the terminal. For commodity / cycle-driven sectors
    # we replace `max_val` with the 5-year median of positive FCFs and
    # cap the final base to that normalised value. Stable businesses
    # (IT, FMCG, pharma, etc.) retain the existing mean/max behaviour
    # so genuine growth trajectories are not penalised.
    # Removed "cement" 2026-04-24 PM: the 5y-median cap was crushing
    # SHREECEM (fv/cmp=0.226) and ULTRACEMCO (fv/cmp=0.306) during
    # India's current infrastructure / real-estate demand boom, where
    # cement FCFs are legitimately well above their 5-year median.
    # Canary merge-gate was perma-failing on SHREECEM because of this.
    # Cement is cyclical in principle but this cycle's base is
    # structurally higher than the 5y lookback. Revisit with a
    # longer window (7-10y) post-launch.
    _CYCLICAL_SECTORS = {
        "oil_gas", "metals", "chemicals", "auto", "sugar", "airlines",
    }
    sector_tag = (enriched.get("sector") or "").lower()
    industry_tag = enriched.get("industry") or ""
    cyc_norm = None

    # ── Capex super-cyclical branch (added 2026-04-30, PR A) ─────────
    # For aluminium / steel / GRASIM-like multi-segment capex super-
    # cyclicals, the 5y positive-only filter excludes every realistic
    # data point because the cycle bottom + capex peak straddle the
    # window. Use a SIGNED median over a 10y window (negative years
    # INCLUDED) to capture mid-cycle FCF. If that median is itself
    # negative (deep super-capex like GRASIM holdco), anchor the base
    # to revenue × 5% so nopat_proxy can't over-project from the
    # peak EBIT.
    from backend.services.analysis.constants import is_capex_super_cyclical
    is_super_cyc = is_capex_super_cyclical(
        ticker, enriched.get("sector"), industry_tag,
    )
    if is_super_cyc and not cf_df.empty and "fcf" in cf_df.columns:
        recent_fcfs = cf_df["fcf"].tail(10).dropna()
        if len(recent_fcfs) >= 3:
            cyc_norm_signed = float(recent_fcfs.median())
            if cyc_norm_signed > 0:
                candidates["cyc_10y_median"] = cyc_norm_signed
                cyc_norm = cyc_norm_signed
            else:
                # All-negative signed median → use revenue × 5% as a
                # mid-cycle FCF anchor.
                if latest_revenue and latest_revenue > 1e10:
                    candidates["cyc_revenue_x_5pct"] = float(latest_revenue) * 0.05
                    cyc_norm = float(latest_revenue) * 0.05
    elif sector_tag in _CYCLICAL_SECTORS and not cf_df.empty and "fcf" in cf_df.columns:
        _pos5 = cf_df["fcf"][cf_df["fcf"] > 0].tail(5)
        if len(_pos5) >= 3:
            cyc_norm = float(_pos5.median())
            candidates["cyc_5y_median"] = cyc_norm
        elif len(_pos5) >= 2:
            # trimmed-mean fallback: drop the max, average the rest
            _trim = _pos5.sort_values().iloc[:-1]
            cyc_norm = float(_trim.mean()) if len(_trim) > 0 else None
            if cyc_norm is not None:
                candidates["cyc_5y_median"] = cyc_norm
        if cyc_norm is not None and cyc_norm > 0:
            # Override max_val so it cannot drag the selection upward
            max_val = min(max_val, cyc_norm) if max_val > 0 else cyc_norm

    # Super-cyclical names: pin max_val to cyc_norm so the
    # median(latest, nopat, max) selection cannot drag in a peak year,
    # and the cap below (`base > cyc_norm → base = cyc_norm`) acts as
    # a hard ceiling against nopat_floor smuggling peak-EBIT back in.
    if is_super_cyc and cyc_norm is not None and cyc_norm > 0:
        max_val = cyc_norm

    # Primary: median of latest_fcf, nopat_proxy, and max_recent_fcf
    # Using median instead of max prevents one outlier year from inflating the base
    valid_candidates = [v for v in [latest_val, nopat_val, max_val] if v > 0]
    if not valid_candidates:
        primary = 0
    elif len(valid_candidates) == 1:
        primary = valid_candidates[0]
    elif len(valid_candidates) == 2:
        primary = min(valid_candidates)
    else:
        primary = float(sorted(valid_candidates)[1])  # median

    nopat_floor = nopat_val * 0.60
    base = max(primary, nopat_floor) if nopat_val > 0 else primary

    method = "median(latest_fcf, nopat_proxy, max_recent_fcf)"

    # Cap cyclicals to the normalised FCF so the nopat_floor (60% of
    # peak-cycle EBIT) cannot smuggle the outlier back in.
    if cyc_norm is not None and cyc_norm > 0 and base > cyc_norm:
        base = cyc_norm
        if is_super_cyc:
            method = (
                "capex_super_cyclical_revenue_x_5pct"
                if "cyc_revenue_x_5pct" in candidates
                else "capex_super_cyclical_10y_median"
            )
        else:
            method = f"cyclical_5y_median({sector_tag})"

    # ── Hysteresis: resist flip-flopping between close candidates ──
    # When candidates are within ~10% of each other, small yfinance
    # revisions cause the median to oscillate day-to-day. The agent
    # investigation found this as the root cause of a 26% same-day
    # FV swing for RELIANCE (Apr 15-17, 2026). Anchor to yesterday's
    # source via in-memory DCF_TRACES; only switch if the new top
    # candidate beats the incumbent by >10%.
    try:
        from screener.dcf_engine import DCF_TRACES as _DT
        _prev = _DT.get(ticker) if ticker else None
        if _prev:
            _prev_src = _prev.get("fcf_base_source")
            _prev_cands = _prev.get("fcf_candidates") or {}
            # Only apply if yesterday used a known candidate slot
            _slot_map = {
                "latest_fcf": latest_val,
                "nopat_proxy": nopat_val,
                "max_recent_fcf": max_val,
                "median_recent_fcf": median_val,
                "hist_p75_margin": p75_val,
            }
            if _prev_src in _slot_map and _slot_map[_prev_src] > 0:
                incumbent = _slot_map[_prev_src]
                # Switch only if current `base` is >10% larger than incumbent
                # (otherwise stick with incumbent to preserve day-over-day stability)
                if base > 0 and incumbent > 0:
                    if abs(base - incumbent) / max(incumbent, 1e-6) <= 0.10:
                        base = incumbent
                        method = f"hysteresis({_prev_src})"
                        log.debug(
                            f"[{ticker}] hysteresis held: kept {_prev_src}=₹{incumbent/1e7:.0f}Cr "
                            f"instead of switching (delta<10%)"
                        )
    except Exception:
        pass  # DCF_TRACES import failure or missing keys -> no hysteresis

    log.debug(f"[{ticker}] FCF base: ₹{base/1e7:.0f}Cr ({method})")

    # Stash candidate breakdown in enriched so dcf_engine can surface
    # it in the DCF_TRACE ring buffer for production debugging.
    try:
        enriched["_fcf_candidates"] = {k: float(v) for k, v in candidates.items()}
        enriched["_fcf_base_source"] = (
            "nopat_floor" if nopat_val > 0 and nopat_floor > primary else
            "median" if len(valid_candidates) >= 3 else
            "min" if len(valid_candidates) == 2 else
            "only" if len(valid_candidates) == 1 else
            "none"
        )
    except Exception:
        pass

    return base, method


def _build_features(enriched: dict) -> np.ndarray:
    rev = enriched.get("latest_revenue", 1) or 1
    fcf = enriched.get("latest_fcf", 0)
    feats = np.array([
        _clamp(enriched.get("revenue_growth", 0)),
        _clamp(enriched.get("fcf_growth",     0)),
        np.clip(enriched.get("op_margin",  0), -0.5, 0.6),
        np.clip(enriched.get("fcf_margin", 0), -0.5, 0.5),
        fcf / rev if rev != 0 else 0,
        np.log1p(abs(rev)),
        np.log1p(abs(fcf)),
        1.0 if fcf >= 0 else -1.0,
    ], dtype=float)
    return np.nan_to_num(feats, nan=0.0, posinf=0.0, neginf=0.0)


def _rule_based_growth(enriched: dict) -> float:
    """
    Sector-aware mean-reverting growth estimate.
    IB fix: pharma/IT anchor 80% to revenue growth (more stable than FCF).
    FCF growth is volatile due to capex cycles and M&A — weight it less.
    """
    rev_g  = _clamp(enriched.get("revenue_growth", 0))
    fcf_g  = _clamp(enriched.get("fcf_growth",     0))
    sector = enriched.get("sector", "general")

    # Sector-specific revenue vs FCF weighting
    # Pharma/IT: FCF is lumpy (R&D, M&A) — lean heavily on revenue
    # Cyclicals (metals, oil): FCF more volatile — use revenue even more
    # FMCG: both stable — balanced blend
    REV_WEIGHT = {
        # India sectors
        "pharma":          0.80,
        "hospital":        0.80,
        "it_services":     0.75,
        "consumer_durable":0.70,
        "fmcg":            0.65,
        "chemicals":       0.70,
        "capital_goods":   0.70,
        "defence":         0.75,
        "metals":          0.80,
        "oil_gas":         0.75,
        "airlines":        0.85,
        # US sectors
        "us_mega_tech":           0.70,
        "us_semiconductors":      0.75,
        "us_it_services":         0.72,
        "us_pharma":              0.80,
        "us_healthcare_services": 0.75,
        "us_banks":               0.65,
        "us_energy":              0.80,
        "us_industrials":         0.70,
        "us_utilities":           0.65,
        "us_consumer_staples":    0.65,
        "us_consumer_disc":       0.70,
        "us_reits":               0.65,
        "us_materials":           0.80,
        "us_communication":       0.72,
        # fallback
        "general":         0.60,
    }
    rev_weight = REV_WEIGHT.get(sector, 0.60)
    fcf_weight = 1.0 - rev_weight

    blended_growth = rev_weight * rev_g + fcf_weight * fcf_g

    # ── Growth fallback chain ─────────────────────────────────
    # If both FCF and revenue growth are ~0 (data quality issue),
    # use analyst consensus or industry average as proxy
    if abs(blended_growth) < 0.005:  # effectively 0%
        # Try analyst-implied growth from forward EPS
        _fwd_eps = enriched.get("forward_eps", 0) or 0
        _trail_eps = enriched.get("trailing_eps", 0) or 0
        if _fwd_eps > 0 and _trail_eps > 0:
            _analyst_growth = (_fwd_eps / _trail_eps) - 1
            if 0 < _analyst_growth < 0.50:
                blended_growth = _analyst_growth * 0.7  # discount by 30%
                log.info(f"[{enriched.get('ticker','?')}] Growth fallback: analyst EPS growth {_analyst_growth:.1%} -> {blended_growth:.1%}")

        # Still 0? Use revenue growth alone (even if FCF is messy)
        if abs(blended_growth) < 0.005 and abs(rev_g) > 0.01:
            blended_growth = rev_g * 0.8  # use 80% of revenue growth
            log.info(f"[{enriched.get('ticker','?')}] Growth fallback: revenue growth {rev_g:.1%} -> {blended_growth:.1%}")

        # Still 0? Use industry minimum (3% for India, 2% for US)
        if abs(blended_growth) < 0.005:
            _is_us = sector.startswith("us_")
            _min_growth = 0.02 if _is_us else 0.03
            blended_growth = _min_growth
            log.info(f"[{enriched.get('ticker','?')}] Growth fallback: industry minimum {_min_growth:.1%}")

    # Mean-revert toward long-run nominal growth
    # US sectors: ~2.5% (US nominal GDP ~2.1% + small premium)
    # India sectors: ~10% (India nominal GDP ~12% minus some discount)
    US_SECTORS = {
        "us_mega_tech","us_semiconductors","us_it_services","us_pharma",
        "us_healthcare_services","us_banks","us_energy","us_industrials",
        "us_utilities","us_consumer_staples","us_consumer_disc",
        "us_reits","us_materials","us_communication","us_general",
    }
    # Sector-specific long-run nominal growth anchors (US nominal GDP ~4% = real ~2%+inflation ~2%)
    # Growth sectors (tech, semis) anchor higher; commodities/utilities anchor at GDP rate
    US_LONG_RUN = {
        "us_mega_tech":           0.055,  # secular tailwinds — AI, cloud
        "us_semiconductors":      0.055,  # AI/data-centre capex cycle
        "us_it_services":         0.045,
        "us_pharma":              0.040,
        "us_healthcare_services": 0.040,
        "us_consumer_disc":       0.050,  # includes TSLA, AMZN retail — higher growth
        "us_communication":       0.045,
        "us_financial_data":      0.045,
    }
    if sector in US_SECTORS:
        LONG_RUN_TARGET = US_LONG_RUN.get(sector, 0.035)   # default US: 3.5%
    else:
        # India sectors: size-tiered terminal growth. Mid/small caps were
        # being over-valued by mean-reverting every name to a flat 10%
        # long-run anchor. Larger companies have lower runway, so cap their
        # terminal anchor accordingly. Bands (in INR):
        #   mcap > ₹50,000 Cr  → 6%
        #   ₹10,000-50,000 Cr  → 7%
        #   < ₹10,000 Cr       → 8%
        # 1 Cr = 1e7. Falls back to mid-tier 7% when mcap is unavailable.
        _mcap_inr = float(enriched.get("market_cap", 0) or 0)
        _mcap_cr = _mcap_inr / 1e7
        if _mcap_cr <= 0:
            LONG_RUN_TARGET = 0.07
        elif _mcap_cr > 50_000:
            LONG_RUN_TARGET = 0.06
        elif _mcap_cr >= 10_000:
            LONG_RUN_TARGET = 0.07
        else:
            LONG_RUN_TARGET = 0.08
    # 60/40 blend: trust actual historical data more, mean-revert less aggressively
    mean_reverted   = 0.60 * blended_growth + 0.40 * LONG_RUN_TARGET

    # Floor: ANY company with positive FCF gets at minimum half the sector's
    # long-run growth rate. No profitable company permanently shrinks.
    latest_fcf = enriched.get("latest_fcf", 0)
    _ticker_dbg = enriched.get('ticker', '?')
    _growth_floor = LONG_RUN_TARGET * 0.5
    log.debug(f"GROWTH_CHECK {_ticker_dbg}: blended={blended_growth:.4f} mean_rev={mean_reverted:.4f} fcf={latest_fcf} floor={_growth_floor:.4f}")
    if latest_fcf > 0 and mean_reverted < _growth_floor:
        mean_reverted = _growth_floor
        log.debug(f"GROWTH_FLOORED {_ticker_dbg}: set to {mean_reverted:.4f}")

    return _clamp(mean_reverted)


def _as_info_dict(obj) -> dict:
    """Accept either a yfinance Ticker (has .info) or a plain dict and
    return an ``info``-shaped dict.

    The DB-first refactor changed what gets passed to compute_wacc:
    the Streamlit dashboard still calls it with ``collector._ticker_obj``
    (a yfinance.Ticker) but backend/services/analysis_service.py calls
    it with ``raw`` (a dict assembled from Aiven + parquet). Both must
    keep working. Anything that isn't a dict or Ticker falls through
    as an empty dict so the caller gets default market assumptions
    instead of an exception.
    """
    if obj is None:
        return {}
    # Plain dict already → assume it's info-shaped
    if isinstance(obj, dict):
        return obj
    # yfinance.Ticker (duck-typed, don't import to avoid circular deps)
    info_attr = getattr(obj, "info", None)
    if isinstance(info_attr, dict):
        return info_attr
    return {}


def _get_financials_frame(obj):
    """Return the .financials DataFrame from a yfinance Ticker, or None.
    For dicts there's no equivalent, so we return None and let the caller
    fall back to its default Rd (cost of debt) assumption."""
    if obj is None or isinstance(obj, dict):
        return None
    return getattr(obj, "financials", None)


def compute_wacc(ticker_obj, is_indian: bool = False, enriched: dict = None) -> dict:
    """
    Compute CAPM-based WACC for a stock.

    Accepts EITHER a yfinance Ticker object (legacy Streamlit path) OR
    a dict assembled from the Aiven DB / parquet store (the new
    backend/services/analysis_service.py hot path). The DB dict keys
    follow the same shape as yfinance info — marketCap, totalDebt,
    beta, sector, industry, effectiveTaxRate — so internally we just
    normalise both into an ``info`` dict and operate on that.

    Uses live 10-year government bond yields (^TNX for US, ^INBMK for India)
    fetched via utils.config.fetch_risk_free_rate() with a 6-hour module-level
    cache.  The result dict includes rf_rate_info so callers can surface the
    live rate in UI.
    """
    from utils.config import fetch_risk_free_rate as _fetch_rf

    # ── Live risk-free rate (cached 6 h) ───────────────────────
    _market    = "india" if is_indian else "us"
    _rf_info   = _fetch_rf(_market)
    live_rf    = _rf_info["rate"]

    # ── Market defaults ─────────────────────────────────────────
    DEFAULT_WACC = 0.12 if is_indian else 0.09
    DEFAULT_RF   = live_rf                         # now live instead of hardcoded
    DEFAULT_MRP  = 0.060 if is_indian else 0.050   # Damodaran 2025: India 6%, US 5%

    result = {
        "wacc": DEFAULT_WACC, "re": DEFAULT_WACC,
        "rd": 0.06 if is_indian else 0.04,
        "beta": 1.2,
        "rf": DEFAULT_RF, "market_premium": DEFAULT_MRP,
        "tax_rate": 0.25 if is_indian else 0.21,
        "e_weight": 0.8, "d_weight": 0.2,
        "auto_computed": False,
        "rf_rate_info": _rf_info,          # expose to dashboard
    }

    SECTOR_DEFAULT_BETA = {
        "it": 1.0, "it_services": 1.0, "IT": 1.0,
        "pharma": 0.7, "Pharma": 0.7,
        "fmcg": 0.6, "FMCG": 0.6,
        "oil_gas": 0.9, "Oil & Gas": 0.9,
        "metals": 1.3, "Metals & Mining": 1.3,
        "auto": 1.1, "Automobiles": 1.1,
        "banking": 1.0, "Banking": 1.0,
        "financial_services": 1.1, "Financial Services": 1.1, "NBFC": 1.1,
        "insurance": 0.8, "Insurance": 0.8,
        "telecom": 0.8, "Telecom": 0.8,
        "power": 0.7, "Power & Utilities": 0.7,
        "chemicals": 1.0, "Chemicals": 1.0,
        "construction": 1.2, "Engineering": 1.2,
        "real_estate": 1.3, "Real Estate": 1.3,
        "general": 1.0,
    }

    try:
        info = _as_info_dict(ticker_obj)
        rf   = DEFAULT_RF
        _raw_beta = info.get("beta", None)
        if _raw_beta and _raw_beta > 0 and _raw_beta <= 3.0:
            beta = float(np.clip(_raw_beta, 0.5, 3.0))
            result["beta_source"] = "yfinance"
        else:
            # Sector-based fallback — check enriched dict first, then yfinance info
            _sector = ((enriched or {}).get("sector_name", "") or
                       info.get("sector", "") or "")
            _industry = info.get("industry", "") or ""
            beta = SECTOR_DEFAULT_BETA.get(
                _sector,
                SECTOR_DEFAULT_BETA.get(
                    _industry,
                    SECTOR_DEFAULT_BETA.get("general", 1.0)
                )
            )
            result["beta_source"] = "sector_default"
            log.info(f"Beta: using sector default {beta} for {_sector or _industry or 'unknown'}")
        mrp  = DEFAULT_MRP

        # Re floor: India 9% (country risk + inflation), US 6% (mature market)
        re_floor = 0.09 if is_indian else 0.06
        re_cap   = 0.25
        re = float(np.clip(rf + beta * mrp, re_floor, re_cap))

        rd = 0.06
        try:
            inc = _get_financials_frame(ticker_obj)
            if inc is not None and not inc.empty:
                for label in ["Interest Expense", "Interest Expense Non Operating"]:
                    if label in inc.index:
                        ie   = abs(float(inc.loc[label].iloc[0] or 0))
                        debt = float(info.get("totalDebt", 0) or 0)
                        if debt > 0 and ie > 0:
                            rd = float(np.clip(ie / debt, 0.04, 0.20))
                            break
        except Exception:
            pass
        # DB-dict path: if the dict carries interest_expense + totalDebt
        # (assembled from company_financials in the new pipeline), use
        # those directly — same formula, no DataFrame required.
        if isinstance(ticker_obj, dict):
            try:
                _ie = float(ticker_obj.get("interest_expense") or 0)
                _debt = float(info.get("totalDebt", 0) or 0)
                if _ie > 0 and _debt > 0:
                    rd = float(np.clip(_ie / _debt, 0.04, 0.20))
            except Exception:
                pass

        mkt_cap    = float(info.get("marketCap", 0) or 0)
        total_debt = float(info.get("totalDebt",  0) or 0)
        V   = mkt_cap + total_debt
        e_w = mkt_cap    / V if V > 0 else 0.8
        d_w = total_debt / V if V > 0 else 0.2

        tax_rate = float(np.clip(
            info.get("effectiveTaxRate", 0.25 if is_indian else 0.21)
            or (0.25 if is_indian else 0.21),
            0.10, 0.40,
        ))

        # CAPM WACC
        wacc_floor = 0.09 if is_indian else 0.06
        wacc = float(np.clip(
            e_w * re + d_w * rd * (1 - tax_rate),
            wacc_floor, 0.20,
        ))

        result.update({
            "wacc": wacc, "re": re, "rd": rd,
            "beta": beta, "rf": rf, "market_premium": mrp,
            "tax_rate": tax_rate, "e_weight": e_w, "d_weight": d_w,
            "auto_computed": True,
            "rf_rate_info": _rf_info,
        })
        log.info(
            f"WACC={wacc:.2%} Re={re:.2%} β={beta:.2f} Rd={rd:.2%} "
            f"Rf={rf:.2%} ({_rf_info['source']})"
        )
    except Exception as exc:
        log.warning(
            "WACC fell back to defaults (ticker_obj=%s): %s",
            type(ticker_obj).__name__, exc,
        )

    return result


def compute_confidence_score(enriched: dict) -> dict:
    score   = 0
    factors = {}
    warnings = []
    income_df = enriched.get("income_df", pd.DataFrame())
    cf_df     = enriched.get("cf_df",     pd.DataFrame())

    # Note: dcf_reliable=False means DCF is not used for valuation,
    # but we still compute a confidence score for the underlying business quality.

    # ── Revenue stability (20 pts) ─────────────────────────────
    if not income_df.empty and "revenue" in income_df.columns:
        rev = income_df["revenue"].replace(0, np.nan).dropna()
        if len(rev) >= 2:
            cv = rev.std() / rev.mean() if rev.mean() != 0 else 1
            s  = max(0, 20 - int(cv * 80))
            factors["Revenue Stability"] = f"{s}/20"
            score += s

            # Detect revenue deceleration / decline
            if len(rev) >= 3:
                recent_yoy  = (rev.iloc[-1] / rev.iloc[-2]) - 1
                prev_yoy    = (rev.iloc[-2] / rev.iloc[-3]) - 1
                decel       = prev_yoy - recent_yoy
                if recent_yoy < -0.05:
                    warnings.append(f"Revenue DECLINING {recent_yoy:.1%} YoY — forward estimates likely much lower")
                    score = max(0, score - 20)   # heavy penalty
                elif recent_yoy < 0:
                    warnings.append(f"Revenue slightly negative {recent_yoy:.1%} YoY")
                elif decel > 0.10 and recent_yoy < 0.15:
                    # Only warn if deceleration brings growth below 15%
                    warnings.append(f"Revenue decelerating: {prev_yoy:.1%} → {recent_yoy:.1%} YoY")
                    score = max(0, score - 10)
    else:
        factors["Revenue Stability"] = "0/20"

    # ── FCF volatility (20 pts) ────────────────────────────────
    if not cf_df.empty and "fcf" in cf_df.columns:
        fcf = cf_df["fcf"].dropna()
        if len(fcf) >= 2 and fcf.mean() != 0:
            cv = fcf.std() / abs(fcf.mean())
            s  = max(0, 20 - int(cv * 40))
            factors["FCF Stability"] = f"{s}/20"
            score += s

            # Detect FCF spike — may be one-time (patent, asset sale)
            # But exclude genuine hypergrowth (revenue also grew similarly)
            if len(fcf) >= 3:
                recent_fcf = float(fcf.iloc[-1])
                median_fcf = float(fcf.median())
                _rev_also_spiked = False
                if not rev.empty and len(rev) >= 3:
                    _rev_ratio = float(rev.iloc[-1]) / float(rev.median()) if float(rev.median()) > 0 else 1
                    _rev_also_spiked = _rev_ratio > 2.0
                if median_fcf > 0 and recent_fcf > median_fcf * 2.5 and not _rev_also_spiked:
                    warnings.append("FCF spike detected — may be one-time (patent/asset sale). Forward FCF likely lower.")
                    score = max(0, score - 15)
                elif recent_fcf < 0:
                    warnings.append("FCF turned negative — monitor closely")
    else:
        factors["FCF Stability"] = "0/20"

    # ── Leverage (20 pts) ──────────────────────────────────────
    debt     = enriched.get("total_debt", 0)
    cash     = enriched.get("total_cash", 0)
    net_debt = debt - cash
    fcf_base = max(enriched.get("latest_fcf", 1), 1)
    lev_s    = max(0, 20 - int((net_debt / (fcf_base * 10)) * 20))
    factors["Leverage"] = f"{lev_s}/20"
    score += lev_s

    # ── FCF positivity (20 pts) ────────────────────────────────
    if not cf_df.empty and "fcf" in cf_df.columns:
        fcf_vals = cf_df["fcf"].dropna()
        pct_pos  = (fcf_vals > 0).mean() if len(fcf_vals) > 0 else 0
        pos_s    = int(pct_pos * 20)
        factors["FCF Positivity"] = f"{pos_s}/20 ({pct_pos:.0%})"
        score += pos_s
    else:
        factors["FCF Positivity"] = "0/20"

    # ── Growth quality (20 pts) ────────────────────────────────
    rev_growth = enriched.get("revenue_growth", 0)
    fcf_growth = enriched.get("fcf_growth", 0)
    op_margin  = enriched.get("op_margin", 0)

    # Check if FCF growth and revenue growth are aligned
    if rev_growth > 0.05 and fcf_growth > 0.05:
        growth_s = 20
    elif rev_growth > 0 and fcf_growth > 0:
        growth_s = 14
    elif rev_growth > 0 or fcf_growth > 0:
        growth_s = 8
    else:
        growth_s = 0
        warnings.append("Both revenue and FCF growth are negative or zero")

    # Bonus for high and stable margin
    if op_margin >= 0.20: growth_s = min(20, growth_s + 3)

    factors["Growth Quality"] = f"{growth_s}/20"
    score += growth_s

    # ── Final grade ────────────────────────────────────────────
    grade = "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW"
    color = "#10b981" if grade == "HIGH" else "#f59e0b" if grade == "MEDIUM" else "#ef4444"

    return {
        "score":    score,
        "grade":    grade,
        "color":    color,
        "factors":  factors,
        "warnings": warnings,
    }


class FCFForecaster:
    def __init__(self):
        self.lr_model = Ridge(alpha=1.0)
        self.rf_model = RandomForestRegressor(n_estimators=100, max_depth=4, random_state=42, n_jobs=-1)
        self.scaler   = StandardScaler()
        self._trained = False

    def train(self, enriched_list: list[dict]) -> None:
        X, y = [], []
        for e in enriched_list:
            if not e or e.get("latest_fcf", 0) <= 0:
                continue
            if not e.get("dcf_reliable", True):
                continue
            X.append(_build_features(e))
            y.append(_clamp(e.get("fcf_growth", 0)))
        if len(X) < 5:
            log.warning("Too few samples — rule-based only.")
            return
        X_arr    = np.array(X)
        y_arr    = np.array(y)
        X_scaled = self.scaler.fit_transform(X_arr)
        self.lr_model.fit(X_scaled, y_arr)
        self.rf_model.fit(X_arr,    y_arr)
        self._trained = True
        log.info(f"Trained on {len(X)} stocks.")

    def predict_growth_rate(self, enriched: dict) -> float:
        rule_g = _rule_based_growth(enriched)
        if not self._trained:
            return rule_g
        feats  = _build_features(enriched).reshape(1, -1)
        lr_g   = _clamp(float(self.lr_model.predict(self.scaler.transform(feats))[0]))
        rf_g   = _clamp(float(self.rf_model.predict(feats)[0]))
        return _clamp(float(np.dot(BLEND_WEIGHTS, [lr_g, rf_g, rule_g])))

    def predict(self, enriched: dict, years: int = FORECAST_YEARS) -> dict:
        ticker      = enriched.get("ticker", "?")

        # CRITICAL: Skip unreliable companies
        if not enriched.get("dcf_reliable", True):
            return {
                "projections":       [0.0] * years,
                "base_growth":       0.0,
                "terminal_fcf_norm": 0.0,
                "fcf_base":          0.0,
                "fcf_base_method":   "unreliable",
                "growth_schedule":   [0.0] * years,
                "reliable":          False,
            }

        fcf_base, method = _compute_fcf_base(enriched)

        # If FCF base is 0 or negative after all checks — unreliable
        if fcf_base <= 0:
            log.warning(f"[{ticker}] FCF base = 0 after all methods — marking unreliable")
            return {
                "projections":       [0.0] * years,
                "base_growth":       0.0,
                "terminal_fcf_norm": 0.0,
                "fcf_base":          0.0,
                "fcf_base_method":   "unreliable_zero_fcf",
                "growth_schedule":   [0.0] * years,
                "reliable":          False,
            }

        base_growth     = self.predict_growth_rate(enriched)
        projections     = []
        growth_schedule = []
        fcf = fcf_base

        # ── Projection horizon (compounder vs default) ────────────
        # Wide-moat compounders (HUL, NESTLEIND, ASIANPAINT, TITAN,
        # PIDILITIND, TCS, INFY, HCLTECH, WIPRO, HDFCAMC, etc.) get a
        # 15-year explicit+fade projection (10y explicit at base_growth,
        # then 5y fade) plus a 50bps haircut on terminal growth. The
        # default (10y total: 5y explicit + 5y fade) applies to every
        # other ticker. Banks / NBFCs / capex super-cyclicals are
        # explicitly excluded inside is_wide_moat_compounder().
        _explicit_years, _fade_years, _terminal_g_adj = _projection_horizons(
            ticker,
            sector=enriched.get("sector_name") or enriched.get("sector"),
            industry=enriched.get("industry_name") or enriched.get("industry"),
            moat_grade=enriched.get("moat_grade"),
        )
        _g_terminal_eff = TERMINAL_FADE_G + _terminal_g_adj
        _total_horizon = _explicit_years + _fade_years
        # Use the compounder horizon when applicable, otherwise honour
        # the caller-supplied ``years`` (default FORECAST_YEARS = 10).
        if _total_horizon != 10:
            years = _total_horizon

        # ── Asymmetric margin-fade scaffold ───────────────────
        # When TTM op_margin > 130% of trailing-3y avg, _compute_fcf_base
        # already anchors NOPAT on the 3y-avg margin. But for non-NOPAT
        # bases (latest_fcf, max_recent_fcf) the TTM peak may have leaked
        # in. To compensate, we taper the projected FCF in years 1-3 by
        # the ratio (3y_avg / TTM), interpolating linearly from a partial
        # haircut in year 1 to the full 3y-avg level by year 3, then
        # leaving years 4+ untouched. This is a one-sided guard — when
        # TTM <= 1.3x 3y avg the multiplier is 1.0 throughout.
        _fade = bool(enriched.get("_margin_fade_to_3y", False))
        _ttm_m = float(enriched.get("_margin_ttm", 0) or 0)
        _avg_m = float(enriched.get("_margin_3y_avg", 0) or 0)
        if _fade and _ttm_m > 0 and _avg_m > 0 and _avg_m < _ttm_m:
            _terminal_ratio = _avg_m / _ttm_m   # < 1.0
        else:
            _terminal_ratio = 1.0

        # Per-year incremental fade multipliers. The cumulative product
        # over years 1, 2, 3 must equal `_terminal_ratio` so that by year
        # 3 the projection has fully migrated to the 3y-avg-margin level.
        # Years 4+ get a multiplier of 1.0 (the year-3 haircut sticks).
        if _terminal_ratio < 1.0:
            _per_year_mult = _terminal_ratio ** (1.0 / 3.0)
        else:
            _per_year_mult = 1.0

        # Compounder path: longer horizon with explicit-flat growth
        # for the explicit window, then exponential fade. Default path:
        # preserves the legacy continuous exponential fade from yr=1
        # (the projection-horizon work intentionally avoids changing
        # FV for non-compounder tickers).
        _is_compounder = (_total_horizon != 10) or (_terminal_g_adj != 0.0)
        for yr in range(1, years + 1):
            if _is_compounder:
                if yr <= _explicit_years:
                    g = _clamp(base_growth)
                else:
                    fade_t = yr - _explicit_years
                    g = _clamp(_exponential_fade(fade_t, base_growth, _g_terminal_eff))
            else:
                g = _clamp(_exponential_fade(yr, base_growth))
            fcf = fcf * (1 + g)
            if _terminal_ratio < 1.0 and yr <= 3:
                fcf = fcf * _per_year_mult
            projections.append(fcf)
            growth_schedule.append(g)

        terminal_norm = float(np.mean(projections[-3:])) if len(projections) >= 3 else projections[-1]

        log.debug(f"[{ticker}] base={fcf_base/1e9:.2f}B ({method}) g0={base_growth:.2%} g10={growth_schedule[-1]:.2%}")

        return {
            "projections":       projections,
            "base_growth":       base_growth,
            "terminal_fcf_norm": terminal_norm,
            "fcf_base":          fcf_base,
            "fcf_base_method":   method,
            "growth_schedule":   growth_schedule,
            "reliable":          True,
        }

    def save(self, path: str = MODEL_SAVE_PATH) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str = MODEL_SAVE_PATH) -> "FCFForecaster":
        with open(path, "rb") as f:
            return pickle.load(f)
