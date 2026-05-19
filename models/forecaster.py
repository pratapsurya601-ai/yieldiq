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
import os
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

try:
    from backend.services.analysis.constants import is_inventory_heavy
except Exception:  # pragma: no cover — keep forecaster importable in slim builds
    def is_inventory_heavy(ticker, sector=None, industry=None):  # type: ignore
        return False

try:
    from backend.services.analysis.constants import (
        is_capital_goods,
        CAPITAL_GOODS_REGIME_CHANGE,
        CAPITAL_GOODS_HYPER_GROWTH,
    )
except Exception:  # pragma: no cover — slim builds
    def is_capital_goods(ticker, sector=None, industry=None):  # type: ignore
        return False
    CAPITAL_GOODS_REGIME_CHANGE: dict[str, int] = {}
    CAPITAL_GOODS_HYPER_GROWTH: set[str] = set()


# Capital-goods FCF normalisation window. 7 years is long enough to
# span a single project / capex cycle for EPC + heavy-engineering names
# (LT, ABB, THERMAX) and short enough to avoid pre-2018 NSE
# classification drift. Fallback `_MIN_CAPITAL_GOODS_YEARS` lets the
# branch still fire for newer listings (KAYNES IPO'd Nov 2022, so
# fewer than 4 years of clean cf_df rows are expected).
CAPITAL_GOODS_WINDOW_YEARS: int = 7
_MIN_CAPITAL_GOODS_YEARS: int = 3

# Hyper-growth threshold (3y revenue CAGR above which the cap-goods
# branch routes terminal_g through a stricter fade). KAYNES sits at
# rev_3y ≈ 0.405; SIEMENS / ABB / LT sit below 0.20.
CAPITAL_GOODS_HYPER_GROWTH_CAGR: float = 0.30
# Hyper-growth terminal_g cap. Computed as min(reported_cagr × 0.5,
# 0.06). 0.06 = high-end India long-run nominal growth; 0.5 × cagr
# acknowledges some persistence of the near-term spike but refuses to
# perpetuity-compound a 40% growth rate.
CAPITAL_GOODS_HYPER_GROWTH_TERMINAL_CAP: float = 0.06

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

    # ── Reverse-DCF upstream normalisation (Option B per
    # docs/design/reverse-dcf-normalization.md, 2026-05-18 v2) ─────
    # Initialise the two stash keys at the TOP of the function so that
    # every code path (including the `if not candidates: return …`
    # early-exit at L~275 and any mid-function raise) leaves a
    # well-defined None on the enriched dict. Downstream readers in
    # backend/services/analysis/service.py (QualityOutput construction)
    # therefore never see a missing key — closing the class of failures
    # that took down PR #305.
    enriched["normalized_fcf_base"]   = None
    enriched["normalized_fcf_margin"] = None

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

    # ── Candidate 2b: Working-capital-smoothed 3y FCF (inventory-heavy) ──
    # For jewellery / retail / beverages (TITAN, DMART, VBL, etc.) reported
    # FCF can swing wildly year-to-year as inventory builds/depletes during
    # expansion. A single bad WC year drags the DCF base far below true cash
    # generation. Use the 3y median of (CFO - |CapEx|) as a smoothed base
    # (Damodaran-style WC normalisation). Only fires when the ticker is
    # classified inventory-heavy AND the smoothed value is positive — never
    # anchor the DCF on a 3y average of losses.
    sector_arg   = enriched.get("sector")
    industry_arg = enriched.get("industry")
    _inv_heavy = False
    try:
        _inv_heavy = is_inventory_heavy(ticker, sector_arg, industry_arg)
    except Exception:
        _inv_heavy = False
    # ── Candidate 2c: Capital-goods 7y WC-smoothed signed-median FCF ──
    # (added 2026-05-18, PR feat/capital-goods-sector-engine)
    #
    # For project-execution / heavy-engineering tickers (LT, ABB,
    # SIEMENS, THERMAX, CUMMINSIND, TIMKEN, SCHAEFFLER, GRINDWELL,
    # KAYNES, ...) trailing 1-3y FCF is structurally unreliable — one
    # milestone-billing year prints a peak, the next year's advance-
    # payment + inventory build prints a trough. The fix:
    #
    #   1. Take a 7-year window of (CFO - |CapEx|) (CFO already nets
    #      out WC deltas; subtracting |CapEx| produces the
    #      Damodaran-style operating FCF that survives capex cycles).
    #   2. If explicit `inventory` / `receivables` / `payables` columns
    #      are available in cf_df, layer in an additional WC smoothing
    #      term (subtract Δ inv + Δ rec - Δ pay) per year. In practice
    #      CFO already incorporates this — the explicit subtraction is
    #      a guard against year-tag misalignment.
    #   3. Signed median (NOT positive-only): capital-goods legitimately
    #      have negative-FCF years during heavy WC absorption; positive-
    #      only would systematically anchor on cycle peaks. This is the
    #      same shape as `cyc_10y_median` for super-cyclicals.
    #   4. For BHEL (regime change post-2023) restrict the window to
    #      years ≥ CAPITAL_GOODS_REGIME_CHANGE[ticker].
    #   5. The candidate votes in the median pool alongside latest_fcf
    #      / nopat_proxy / max_recent_fcf (see selection below).
    _cap_goods = False
    try:
        _cap_goods = is_capital_goods(ticker, sector_arg, industry_arg)
    except Exception:
        _cap_goods = False
    enriched["_is_capital_goods"] = bool(_cap_goods)
    if _cap_goods and not cf_df.empty:
        _cg_cfo_col = None
        if "cfo" in cf_df.columns:
            _cg_cfo_col = "cfo"
        elif "ocf" in cf_df.columns:
            _cg_cfo_col = "ocf"

        # Regime-change cutoff (BHEL post-2023). When applied, drop pre-
        # cutoff rows so the median doesn't reflect a dead-cycle that no
        # longer applies (PSU thermal-power orderbook contraction).
        _bare = (ticker or "").upper().replace(".NS", "").replace(".BO", "")
        _regime_year = CAPITAL_GOODS_REGIME_CHANGE.get(_bare)

        _cg_df = cf_df
        if _regime_year is not None and "year" in cf_df.columns:
            try:
                _cg_df = cf_df[cf_df["year"] >= int(_regime_year)]
                enriched["_capital_goods_regime_cutoff"] = int(_regime_year)
            except Exception:
                _cg_df = cf_df

        if _cg_cfo_col is not None and "capex" in _cg_df.columns:
            _wc_series = (
                _cg_df[_cg_cfo_col] - _cg_df["capex"].abs()
            ).tail(CAPITAL_GOODS_WINDOW_YEARS).dropna()

            # Optional explicit WC overlay: if inventory / receivables /
            # payables columns are present, subtract their year-over-year
            # deltas (Δ inv + Δ rec - Δ pay). CFO usually already nets
            # these out, but the overlay is a guard for collectors that
            # report a "pre-WC CFO" alias. Missing columns → silent skip.
            try:
                _wc_overlay_cols = {
                    "inv": next((c for c in ("inventory", "inventories")
                                 if c in _cg_df.columns), None),
                    "rec": next((c for c in ("receivables", "trade_receivables",
                                              "accounts_receivable")
                                 if c in _cg_df.columns), None),
                    "pay": next((c for c in ("payables", "trade_payables",
                                              "accounts_payable")
                                 if c in _cg_df.columns), None),
                }
                if all(_wc_overlay_cols.values()):
                    _tail = _cg_df.tail(CAPITAL_GOODS_WINDOW_YEARS + 1)
                    _d_inv = _tail[_wc_overlay_cols["inv"]].diff().tail(
                        CAPITAL_GOODS_WINDOW_YEARS)
                    _d_rec = _tail[_wc_overlay_cols["rec"]].diff().tail(
                        CAPITAL_GOODS_WINDOW_YEARS)
                    _d_pay = _tail[_wc_overlay_cols["pay"]].diff().tail(
                        CAPITAL_GOODS_WINDOW_YEARS)
                    _wc_delta = (_d_inv.fillna(0) + _d_rec.fillna(0)
                                 - _d_pay.fillna(0))
                    # Align indexes (best-effort), subtract from
                    # CFO-CapEx series. If alignment fails, fall back to
                    # the plain (CFO - |CapEx|) tail computed above.
                    try:
                        _aligned = _wc_series.copy()
                        _aligned.index = _wc_series.index
                        _wc_delta.index = _wc_series.index[-len(_wc_delta):]
                        _wc_series = _aligned.sub(_wc_delta, fill_value=0)
                    except Exception:
                        pass
            except Exception:
                pass

            if len(_wc_series) >= _MIN_CAPITAL_GOODS_YEARS:
                # 2026-05-19 Day-6: replace signed-median with trimmed-
                # mean. The signed-median variant (disabled in v117)
                # systematically picked trough years for project
                # businesses, dragging FV 50-78% below consensus.
                # Trimmed-mean (drop min + max, average the rest)
                # excludes the extreme cycle tails and centres on
                # mid-cycle. Falls back to median for series with < 5
                # years where there isn't enough data to trim.
                _sorted = sorted(_wc_series)
                if len(_sorted) >= 5:
                    _trimmed = _sorted[1:-1]
                    _cg_med = float(sum(_trimmed) / len(_trimmed))
                    _cg_method = "trimmed_mean"
                else:
                    _cg_med = float(_wc_series.median())
                    _cg_method = "median_fallback"
                candidates["cap_goods_7y_wc_smoothed"] = _cg_med
                enriched["_capital_goods_window_years"] = int(len(_wc_series))
                enriched["_capital_goods_aggregation"] = _cg_method
                log.info(
                    "[%s] capital-goods 7y WC-smoothed %s FCF: "
                    "₹%.0fCr (n=%d years, regime_cutoff=%s)",
                    ticker, _cg_method, _cg_med / 1e7, len(_wc_series),
                    _regime_year if _regime_year else "—",
                )

    if _inv_heavy and not cf_df.empty:
        # Accept either canonical "cfo" column or its "ocf" alias
        # (collector.py emits both — `cfo` is added at the data layer
        # for table configs that expect it; `ocf` is the underlying
        # field). Either is fine here.
        _cfo_col = None
        if "cfo" in cf_df.columns:
            _cfo_col = "cfo"
        elif "ocf" in cf_df.columns:
            _cfo_col = "ocf"
        if _cfo_col is not None and "capex" in cf_df.columns:
            _wc_series = (cf_df[_cfo_col] - cf_df["capex"].abs()).tail(3).dropna()
            if len(_wc_series) >= 2:
                wc_adj_fcf = float(_wc_series.median())
                if wc_adj_fcf > 0:
                    candidates["wc_adjusted_3y"] = wc_adj_fcf
                    log.info(
                        "[%s] inventory-heavy WC-smoothed FCF: ₹%.0fCr "
                        "(3y median of CFO-|CapEx|)",
                        ticker, wc_adj_fcf / 1e7,
                    )

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
        # Capital-goods override (sector_benchmarks.py::capital_goods sets
        # fcf_conv=0.60 because project businesses absorb WC + run higher
        # maintenance capex than the asset-light 0.85 default). Without
        # this, SIEMENS / ELGIEQUIP / SCHAEFFLER's nopat_proxy candidate
        # over-shoots, dragging the median selection to a peak-cycle
        # value and producing +250% MoS FVs. See docs/design/
        # capital-goods-dcf-fix.md §4 (Approach B step 3).
        if _cap_goods:
            fcf_conv = 0.60

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
    wc_adj_val = candidates.get("wc_adjusted_3y", 0)

    # ── Inventory-heavy override: prioritise wc_adjusted_3y over latest_fcf ──
    # When the ticker is inventory-heavy and the 3y WC-smoothed FCF candidate
    # is available, substitute it for `latest_val` in the median selection.
    # Pure CFO-Capex swings wildly during inventory build/depletion cycles
    # (TITAN: post-COVID gold-stock build crushed FY23 FCF to ~Rs.200 Cr from
    # a normal Rs.1,500-2,000 Cr; DMART: store-rollout WC drag distorts every
    # other year). The 3y median is closer to mid-cycle cash generation.
    if _inv_heavy and wc_adj_val > 0:
        latest_val = wc_adj_val

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
    # window. Use a SIGNED median over a long window (negative years
    # INCLUDED) to capture mid-cycle FCF. If that median is itself
    # negative (deep super-capex like GRASIM holdco), anchor the base
    # to revenue × 5% so nopat_proxy can't over-project from the
    # peak EBIT.
    #
    # Window length (2026-05-03 followup): the original 10y window
    # over-corrects in upcycles for metals/auto super-cyclicals — a
    # 10y look in 2026 captures India's 2015-2024 commodity upcycle
    # at the peak end, which biases the "mid-cycle" median ABOVE true
    # mid-cycle. Extending to 15y (SUPER_CYCLICAL_WINDOW_YEARS) pulls
    # in 2010-2014, smoothing the upcycle bias while staying signed
    # so cycle-bottom years still vote. The candidate key
    # `cyc_10y_median` is preserved for log/trace continuity.
    from backend.services.analysis.constants import (
        is_capex_super_cyclical,
        SUPER_CYCLICAL_WINDOW_YEARS,
    )
    is_super_cyc = is_capex_super_cyclical(
        ticker, enriched.get("sector"), industry_tag,
    )
    if is_super_cyc and not cf_df.empty and "fcf" in cf_df.columns:
        recent_fcfs = cf_df["fcf"].tail(SUPER_CYCLICAL_WINDOW_YEARS).dropna()
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
    #
    # ── Pharma R&D-adjusted candidate (PR feat/pharma-dcf-fix, 2026-05-18) ─
    # When `pharma_rd_adjusted` is available (sector == "pharma" + valid
    # op_margin + revenue floor satisfied — see candidate 3b above), include
    # it in the median pool. R&D is investment, not opex; the growth-R&D
    # add-back (60% × ~8% × revenue) is the standard sell-side anchor for
    # pharma economic earnings. Sector-gated via the candidate's own
    # presence, so non-pharma tickers see no change.
    pharma_rd_val = candidates.get("pharma_rd_adjusted", 0)
    cap_goods_val = candidates.get("cap_goods_7y_wc_smoothed", 0)
    enriched["_pharma_rd_used"] = False
    enriched["_capital_goods_used"] = False
    # RE-ENABLED 2026-05-19 Day-6 with two-layer safety:
    # 1. Aggregation is now trimmed-mean (drops min/max), not signed-
    #    median — the original trough-picker pathology.
    # 2. Reconciliation gate: only vote if the candidate is within 35%
    #    of nopat_proxy (a non-cycle-biased reference). If the cap-
    #    goods candidate drifts far from nopat, it's signalling a real
    #    cycle artifact; we drop it from the pool rather than letting
    #    it dominate.
    # Combined effect: the engine re-fires for BHEL/SIEMENS/THERMAX/
    # ABB/CUMMINSIND but only when the candidate is reconcilable with
    # an independent estimate. If reconciliation fails, we fall through
    # to the generic median path — same behaviour as the hotfix-disabled
    # branch, but for the specific tickers where the gate flags noise.
    _cg_reconciliation_ok = False
    if _cap_goods and cap_goods_val > 0 and nopat_val > 0:
        _cg_drift = abs(cap_goods_val - nopat_val) / max(nopat_val, 1)
        _cg_reconciliation_ok = _cg_drift < 0.35
        enriched["_capital_goods_reconciliation_drift"] = round(_cg_drift, 3)
    if _cap_goods and cap_goods_val > 0 and _cg_reconciliation_ok:
        valid_candidates = [
            v for v in [latest_val, nopat_val, max_val, cap_goods_val] if v > 0
        ]
        enriched["_capital_goods_used"] = True
    elif _sector == "pharma" and pharma_rd_val > 0:
        valid_candidates = [
            v for v in [latest_val, nopat_val, max_val, pharma_rd_val] if v > 0
        ]
        enriched["_pharma_rd_used"] = True
    else:
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

    # Capital-goods cap: when the cap-goods WC-smoothed 7y signed median
    # is the credible anchor, prevent the nopat_floor (60% of peak EBIT)
    # from smuggling a peak-cycle value back in. This is the cap-goods
    # analogue of the cyc_norm hard ceiling for super-cyclicals.
    if _cap_goods and cap_goods_val > 0:
        # Allow up to 1.5x the WC-smoothed median (so a positive cycle
        # can lift the base modestly) but never the full nopat_floor.
        _cg_ceiling = cap_goods_val * 1.5
        if base > _cg_ceiling:
            base = _cg_ceiling
            method = (
                f"capital_goods_wc_smoothed_7y_capped"
                f"(orig_method=median,wc_med=₹{cap_goods_val/1e7:.0f}Cr)"
            )
        else:
            method = "capital_goods_wc_smoothed_7y"
        _br = (ticker or "").upper().replace(".NS", "").replace(".BO", "")
        if _br in CAPITAL_GOODS_REGIME_CHANGE:
            method = f"capital_goods_regime_change({_br}≥{CAPITAL_GOODS_REGIME_CHANGE[_br]})"
        enriched["_fcf_anchor_strategy"] = method

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

    # ── Cash-flow-reality sanity gate (added 2026-05-18, DRREDDY) ──
    # Anchored on the cf_df-derived `max_recent_fcf` and the
    # post-`_get_adjusted_fcf` `latest_fcf`. Both come from the
    # yfinance cash-flow statement in native rupee units and are
    # the most unit-stable inputs in `enriched`. If `base` exceeds
    # 2.5x of this anchor, one of the revenue-scaled candidates
    # (nopat_proxy, pharma_rd_adjusted, hist_p75_margin, cyc_*) has
    # been blown up by an upstream unit mismatch — most commonly
    # `latest_revenue` arriving in ₹Cr instead of raw rupees via
    # the XBRL TTM ladder in
    # `backend/services/quarterly_results_service.py`. Pull the
    # anchor down to that cf_df reality so the DCF cannot exceed
    # a realistic earnings multiple of recent cash generation.
    #
    # Trigger evidence for DRREDDY 2026-05-18:
    #   - reverse-DCF surfaced normalized_fcf=2.43e+16 (₹2.43 ×
    #     10^9 Cr) — clearly polluted; max_recent_fcf from cf_df is
    #     ~₹4,001 Cr.
    #   - uncapped DCF FV ₹4,698 vs analyst consensus ₹1,200-1,500.
    #
    # Design notes:
    #   - 2.5x multiplier is generous enough to preserve legitimate
    #     pharma_rd_adjusted lift (~30-40% above max_recent_fcf is
    #     normal when R&D is heavy).
    #   - Only fires when cf_df-derived anchors are positive (we
    #     never tighten a base that has no reliable cf_df reference).
    #   - Always uses cf_df values directly, not enriched["latest_*"]
    #     fields, so an upstream unit corruption in those fields
    #     cannot pollute the ceiling itself.
    cf_anchor_max = 0.0
    cf_anchor_latest = 0.0
    if not cf_df.empty and "fcf" in cf_df.columns:
        _pos_for_anchor = cf_df["fcf"][cf_df["fcf"] > 0].tail(5)
        if len(_pos_for_anchor) >= 1:
            cf_anchor_max = float(_pos_for_anchor.max())
        # latest positive FCF from cf_df itself (NOT enriched["latest_fcf"]
        # which may have been substituted with a PAT proxy upstream).
        _last_fcf_series = cf_df["fcf"].dropna()
        if len(_last_fcf_series) >= 1:
            _last = float(_last_fcf_series.iloc[-1])
            if _last > 0:
                cf_anchor_latest = _last
    cf_anchor = max(cf_anchor_max, cf_anchor_latest)
    if cf_anchor > 0 and base > 2.5 * cf_anchor:
        log.warning(
            "[%s] CF-reality cap fired: base ₹%.0fCr > 2.5 × cf_anchor "
            "₹%.0fCr — pulling base to cf_anchor (likely upstream "
            "latest_revenue/op_margin unit corruption; candidates=%s)",
            ticker, base / 1e7, cf_anchor / 1e7,
            {k: f"₹{v/1e7:.0f}Cr" for k, v in candidates.items()},
        )
        base = cf_anchor
        method = f"cf_reality_cap({method})"

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
                "wc_adjusted_3y": wc_adj_val,
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

    # ── Reverse-DCF upstream normalisation (Option B per
    # docs/design/reverse-dcf-normalization.md, 2026-05-18 v2) ──
    # Serialise the already-normalised `base` (forward-DCF anchor)
    # and a separately-computed 5y median FCF margin into the
    # enriched dict so the reverse-DCF solver can read the same
    # anchor without re-deriving the cyclical-sector logic. Two
    # isolated try blocks so a failure computing the margin never
    # affects the base serialisation (and vice versa). NEITHER
    # branch references `base` from inside an except handler — the
    # value is captured into a local first, eliminating the
    # UnboundLocalError class that took down PR #305.
    _base_local = base  # snapshot — base is in scope here, always
    try:
        if _base_local is not None and float(_base_local) > 0:
            enriched["normalized_fcf_base"] = float(_base_local)
    except Exception as _e_base:  # noqa: BLE001
        log.warning(f"[{ticker}] normalized_fcf_base serialise failed: {_e_base}")
        enriched["normalized_fcf_base"] = None

    try:
        _hist_fcf_margin_5y = None
        if (not cf_df.empty and not income_df.empty
                and "fcf" in cf_df.columns and "revenue" in income_df.columns
                and "year" in cf_df.columns and "year" in income_df.columns):
            _merged = pd.merge(
                cf_df[["year", "fcf"]],
                income_df[["year", "revenue"]],
                on="year", how="inner",
            )
            _merged = _merged[(_merged["revenue"] > 0) & (_merged["fcf"] > 0)].tail(5)
            if len(_merged) >= 3:
                _margins = _merged["fcf"] / _merged["revenue"]
                _m = float(np.median(_margins))
                if np.isfinite(_m):
                    _hist_fcf_margin_5y = _m
        enriched["normalized_fcf_margin"] = _hist_fcf_margin_5y
    except Exception as _e_marg:  # noqa: BLE001
        log.warning(f"[{ticker}] normalized_fcf_margin compute failed: {_e_marg}")
        enriched["normalized_fcf_margin"] = None

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

        # Pharma WACC floor (2026-05-19 Day-5 v2): apply ONLY to generic
        # exporters (DRREDDY/AUROPHARMA/ZYDUSLIFE/GLENMARK/IPCALAB)
        # which face US-pricing-pressure risk premium. Franchise pharma
        # (SUNPHARMA, CIPLA, MANKIND, TORNTPHARM, LUPIN) have durable
        # India-domestic moats and the CAPM 9.8% is closer to truth for
        # them — a universal floor produced -40% to -60% under-shoots
        # on franchise pharma in the v1 deploy.
        # Curated generic-exporter set — US-pricing-pressure exposure,
        # narrower moats, lower terminal-growth justified. Expanded
        # 2026-05-19 Day-6 (was 9, now 15) to cover the long tail of
        # mid-cap generics that were silently routing through default
        # CAPM despite being on the wrong end of the structural pricing
        # cycle. Excludes franchise pharma (SUNPHARMA, CIPLA, MANKIND,
        # TORNTPHARM, LUPIN, BIOCON, ABBOTINDIA, GLAXO, PFIZER, SANOFI,
        # ERIS, AJANTPHARM) and CDMOs (DIVISLAB) which keep default
        # treatment.
        # Day-13 (2026-05-19): renamed "NEULAND" → "NEULANDLAB" (the
        # actual NSE ticker — old entry never fired because lookup is
        # on the bare NSE symbol). Added NATCOPHARM (US-focused generic
        # exporter, was producing DCF FV 3.57× consensus per Day-13
        # outlier scan).
        _PHARMA_GENERIC_TICKERS = frozenset({
            "DRREDDY", "AUROPHARMA", "ZYDUSLIFE", "GLENMARK", "IPCALAB",
            "LAURUSLABS", "ALEMBICLTD", "GRANULES", "WOCKPHARMA",
            # 2026-05-19 Day-6 expansion
            "NEULANDLAB", "GLANDPHARMA", "PPLPHARMA", "JBCHEPHARM",
            "STAR", "SAILIFE",
            # 2026-05-19 Day-13: NATCOPHARM (gOxford / gCopaxone /
            # gIbrance — concentrated US generic exposure)
            "NATCOPHARM",
        })
        # Day-16 (2026-05-19): Hospital chain sub-bucket. Indian listed
        # hospital + diagnostic chains were systematically under-valued
        # by 50-85% vs sell-side consensus on the Day-13 outlier scan
        # (MAXHEALTH 0.16x cons, VIJAYA 0.15x, MEDANTA 0.26x, FORTIS
        # 0.32x, KIMS 0.36x, APOLLOHOSP 0.39x, NH 0.49x).
        #
        # Root cause: standard CAPM WACC (≈ 0.11) + default terminal-g
        # cap (0.04) misprices these because:
        #   (a) Hospital service contracts (TPA + corporate + cash) are
        #       quasi-recurring and ARPU stays sticky → CFO predictability
        #       closer to an A-grade utility than to a generic industrial
        #   (b) Indian healthcare nominal spend has grown 12-15% CAGR for
        #       the last decade and is set to continue (Ayushman Bharat
        #       + insurance penetration + aging demographics)
        #   (c) Bed-expansion cycles take 7-10y to mature → 5y explicit
        #       forecast horizon misses the ramp, anchoring valuation
        #       on pre-maturity ARPU
        #
        # Treatment: floor WACC at 0.085 (-50bps vs default; closer to
        # regulated-utility risk profile) and (in the terminal-g block
        # below) bump cap to 0.055 (vs 0.04 default).
        # The diagnostic chains (LALPATHLAB, METROPOLIS) are NOT included
        # — they have lower predictability + commodity pricing pressure;
        # they keep default treatment.
        _HOSPITAL_CHAIN_TICKERS = frozenset({
            "MAXHEALTH", "FORTIS", "MEDANTA", "KIMS",
            "NH", "APOLLOHOSP", "ASTERDM", "RAINBOW",
            "VIJAYA",
            # Single-specialty chains with same characteristics
            "AGARWALEYE",
        })

        try:
            _ticker_bare = ""
            if enriched:
                _t = enriched.get("ticker") or ""
                _ticker_bare = _t.replace(".NS", "").replace(".BO", "").upper()
            if _ticker_bare in _PHARMA_GENERIC_TICKERS:
                wacc_floor = max(wacc_floor, 0.105)  # +50-100bps generic risk
            elif _ticker_bare in _HOSPITAL_CHAIN_TICKERS:
                # Pin to a tighter floor (defensive sector)
                wacc_floor = min(wacc_floor, 0.085)
        except Exception:
            pass

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


# ════════════════════════════════════════════════════════════════
# Confidence v2 (Phase 1) — design doc: docs/design/confidence-metric-v2.md
# Behind env flag CONFIDENCE_V2=1. Phase 1 ships 2 components whose inputs
# exist today: data_completeness and sector_engine_match. model_fit_quality
# is also derivable from the existing v1 inputs and is included so weights
# can be renormalized over present components (per §3 of the doc).
#
# Phase 2 (cross_engine_consistency) and Phase 3 (structural_break_clean)
# require upstream PRs (engine FV normalizer, corporate-actions overlay)
# and are intentionally NOT implemented here. Rollback = unset CONFIDENCE_V2.
# ════════════════════════════════════════════════════════════════

# Sector → preferred valuation engine. Used by sector_engine_match.
# Match value 1.0 if `primary_engine` is in the preferred list for the
# sector, 0.5 if the generic DCF fallback was used on a sector that has
# a specific engine, else 1.0 (no opinion).
SECTOR_ENGINE_MAP: dict[str, list[str]] = {
    "Financial Services": ["pb_ratio", "ddm", "excess_return", "pb_residual_income"],
    "Financials":         ["pb_ratio", "ddm", "excess_return", "pb_residual_income"],
    "Banks":              ["pb_ratio", "ddm", "excess_return", "pb_residual_income"],
    "Insurance":          ["pb_ratio", "embedded_value", "excess_return"],
    "Real Estate":        ["nav", "sotp"],
    "Energy":             ["sotp", "ev_ebitda", "dcf"],
    "Utilities":          ["dcf", "ddm"],
    "Basic Materials":    ["ev_ebitda", "dcf"],
    "Industrials":        ["dcf", "ev_ebitda"],
    "Technology":         ["dcf", "fcf_yield"],
    "Communication Services": ["dcf", "ev_ebitda"],
    "Consumer Cyclical":  ["dcf", "ev_ebitda"],
    "Consumer Defensive": ["dcf", "fcf_yield"],
    "Healthcare":         ["dcf", "fcf_yield"],
}

# Critical fields used by data_completeness. Each entry is
# (key_on_enriched, predicate_returning_bool_when_present_and_usable).
def _completeness_fields(enriched: dict) -> list[tuple[str, bool]]:
    income_df = enriched.get("income_df")
    cf_df     = enriched.get("cf_df")
    bs_df     = enriched.get("balance_df")
    def _df_ok(df, col=None) -> bool:
        try:
            if df is None or getattr(df, "empty", True):
                return False
            if col is not None and col not in df.columns:
                return False
            return True
        except Exception:
            return False
    return [
        ("income_df.revenue", _df_ok(income_df, "revenue")),
        ("cf_df.fcf",         _df_ok(cf_df, "fcf")),
        ("balance_df",        _df_ok(bs_df)),
        ("shares",            bool(enriched.get("shares", 0))),
        ("price",             bool(enriched.get("price", 0))),
        ("latest_fcf",        enriched.get("latest_fcf", None) not in (None, 0)),
        ("revenue_growth",    enriched.get("revenue_growth", None) is not None),
        ("op_margin",         enriched.get("op_margin", None) is not None),
    ]


def _component_data_completeness(enriched: dict) -> dict:
    fields = _completeness_fields(enriched)
    total  = len(fields)
    have   = sum(1 for _, ok in fields if ok)
    score  = int(round(100.0 * have / total)) if total else 0
    missing = [name for name, ok in fields if not ok]
    return {
        "score":           score,
        "inputs_present":  True,  # always derivable
        "reason":          f"{have}/{total} critical fields present"
                           + (f"; missing: {', '.join(missing)}" if missing else ""),
    }


def _component_sector_engine_match(enriched: dict) -> dict:
    sector = (enriched.get("sector") or enriched.get("sector_name") or "").strip()
    engine = (enriched.get("primary_engine") or enriched.get("valuation_model")
              or enriched.get("engine") or "").strip().lower()
    if not sector or not engine:
        return {"score": 0, "inputs_present": False,
                "reason": "missing sector or primary_engine"}
    preferred = [e.lower() for e in SECTOR_ENGINE_MAP.get(sector, [])]
    if not preferred:
        # No opinion for this sector — neutral full match.
        return {"score": 100, "inputs_present": True,
                "reason": f"no sector preference for '{sector}'; engine={engine}"}
    if engine in preferred:
        return {"score": 100, "inputs_present": True,
                "reason": f"engine '{engine}' matches sector '{sector}'"}
    # Generic DCF fallback used on sector that needed a specific engine.
    if engine in ("dcf", "fcf_dcf"):
        return {"score": 50, "inputs_present": True,
                "reason": f"generic DCF fallback on '{sector}' "
                          f"(prefers {preferred[0]})"}
    return {"score": 25, "inputs_present": True,
            "reason": f"engine '{engine}' mismatched for '{sector}' "
                      f"(prefers {preferred[0]})"}


def _component_model_fit_quality(enriched: dict) -> dict:
    """Refactor of v1 Revenue+FCF Stability + FCF Positivity into one number.

    Shipped in Phase 1 so renormalization has a third anchor; v1 logic
    is preserved verbatim inside this helper.
    """
    income_df = enriched.get("income_df", pd.DataFrame())
    cf_df     = enriched.get("cf_df",     pd.DataFrame())
    parts: list[float] = []
    try:
        if not income_df.empty and "revenue" in income_df.columns:
            rev = income_df["revenue"].replace(0, np.nan).dropna()
            if len(rev) >= 2 and rev.mean() != 0:
                cv = rev.std() / rev.mean()
                parts.append(max(0.0, 100.0 - float(cv) * 400.0))
        if not cf_df.empty and "fcf" in cf_df.columns:
            fcf = cf_df["fcf"].dropna()
            if len(fcf) >= 2 and fcf.mean() != 0:
                cv = fcf.std() / abs(fcf.mean())
                parts.append(max(0.0, 100.0 - float(cv) * 200.0))
            if len(fcf) > 0:
                pct_pos = float((fcf > 0).mean())
                parts.append(pct_pos * 100.0)
    except Exception:
        pass
    if not parts:
        return {"score": 0, "inputs_present": False,
                "reason": "income/cf dataframes absent"}
    score = int(round(sum(parts) / len(parts)))
    return {"score": score, "inputs_present": True,
            "reason": f"avg of {len(parts)} fit sub-scores"}


# Phase-1 weights per design doc §5 (renormalized over 3 available comps).
_V2_WEIGHTS_PHASE1: dict[str, float] = {
    "data_completeness":   0.40,
    "model_fit_quality":   0.35,
    "sector_engine_match": 0.25,
}


def compute_confidence_score_v2(enriched: dict) -> dict:
    """Confidence v2 — Phase 1. See docs/design/confidence-metric-v2.md.

    Returns the same top-level keys as v1 (`score`, `grade`, `color`,
    `factors`, `warnings`) plus a `components` sub-dict and a
    `version: "v2"` marker so downstream readers can branch.
    """
    components: dict[str, dict] = {
        "data_completeness":   _component_data_completeness(enriched),
        "model_fit_quality":   _component_model_fit_quality(enriched),
        "sector_engine_match": _component_sector_engine_match(enriched),
    }
    # Renormalize weights over components whose inputs are present.
    present = {k: v for k, v in components.items() if v.get("inputs_present")}
    if not present:
        score = 0
    else:
        w_sum = sum(_V2_WEIGHTS_PHASE1[k] for k in present)
        score = int(round(
            sum(_V2_WEIGHTS_PHASE1[k] * present[k]["score"] for k in present) / w_sum
        ))

    grade = "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW"
    color = "#10b981" if grade == "HIGH" else "#f59e0b" if grade == "MEDIUM" else "#ef4444"

    # Mirror the v1 `factors` dict shape so the existing frontend keeps
    # rendering something readable even before the v2-aware UI ships.
    factors = {
        "Data Completeness":   f"{components['data_completeness']['score']}/100",
        "Model Fit Quality":   f"{components['model_fit_quality']['score']}/100",
        "Sector–Engine Match": f"{components['sector_engine_match']['score']}/100",
    }
    warnings: list[str] = []
    for name, comp in components.items():
        if comp.get("inputs_present") and comp.get("score", 100) < 50:
            warnings.append(f"{name}: {comp.get('reason', 'low score')}")

    return {
        "score":      score,
        "grade":      grade,
        "color":      color,
        "factors":    factors,
        "warnings":   warnings,
        "components": components,
        "version":    "v2",
    }


def confidence_v2_enabled() -> bool:
    """Single source of truth for the v2 rollout flag."""
    return os.environ.get("CONFIDENCE_V2", "0") == "1"


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

        # ── Pharma terminal-g cap (2026-05-19 Day-5 v2) ──────────────
        # Apply ONLY to generic exporters (US-pricing-pressure exposure).
        # Franchise pharma (SUNPHARMA/MANKIND/CIPLA/TORNTPHARM/LUPIN)
        # have durable India-domestic moats — TERMINAL_FADE_G=0.04 is
        # appropriate for them. Universal cap in v1 deploy produced
        # -40% to -60% under-shoots on franchise names.
        # Day-13: sync TG set with the WACC-floor set so generic-
        # exporter treatment is consistent. The earlier split (TG list
        # was 9, WACC list was 15) meant the 6 Day-6 expansion tickers
        # got WACC tightening but not terminal-g tightening, leaving
        # them at default 0.04 terminal-g for a 30y model. Result: still
        # +25-50% over consensus.
        _PHARMA_GENERIC_TICKERS_TG = frozenset({
            "DRREDDY", "AUROPHARMA", "ZYDUSLIFE", "GLENMARK", "IPCALAB",
            "LAURUSLABS", "ALEMBICLTD", "GRANULES", "WOCKPHARMA",
            "NEULANDLAB", "GLANDPHARMA", "PPLPHARMA", "JBCHEPHARM",
            "STAR", "SAILIFE", "NATCOPHARM",
        })
        try:
            _t_bare_tg = ""
            if enriched:
                _t_raw = enriched.get("ticker") or ""
                _t_bare_tg = _t_raw.replace(".NS", "").replace(".BO", "").upper()
            if _t_bare_tg in _PHARMA_GENERIC_TICKERS_TG and _g_terminal_eff > 0.035:
                _g_terminal_eff = 0.035
                enriched["_pharma_generic_terminal_g_capped"] = True
        except Exception:
            pass

        # ── Hospital chain terminal-g lift (2026-05-19 Day-16) ──────
        # Mirrors the WACC-floor block above. For the 10 listed hospital
        # chains, raise terminal-g floor from the default 0.04 to 0.055.
        # Justification: Indian nominal healthcare spend has compounded
        # 12-15% over the last decade and is set to continue per
        # IRDAI penetration data + Ayushman Bharat coverage expansion +
        # demographic aging. A 5.5% perpetuity is conservative against
        # those numbers. Combined with the 0.085 WACC floor, the
        # implied WACC - g spread of ~3% is still inside the Gordon-
        # model safety band (must stay > 0.03 to avoid TV blow-up).
        _HOSPITAL_CHAIN_TICKERS_TG = frozenset({
            "MAXHEALTH", "FORTIS", "MEDANTA", "KIMS",
            "NH", "APOLLOHOSP", "ASTERDM", "RAINBOW",
            "VIJAYA", "AGARWALEYE",
        })
        try:
            if _t_bare_tg in _HOSPITAL_CHAIN_TICKERS_TG and _g_terminal_eff < 0.055:
                _g_terminal_eff = 0.055
                enriched["_hospital_chain_terminal_g_lifted"] = True
        except Exception:
            pass

        # ── Capital-goods hyper-growth fade (added 2026-05-18, v113) ──
        # KAYNES sits at rev_3y ≈ 0.405; SIEMENS / SCHAEFFLER / ELGIEQUIP
        # at peak-cycle margins. A 30%+ near-term grower cannot
        # compound to perpetuity at TERMINAL_FADE_G = 0.04 because the
        # 5y exponential fade decays slowly enough to leave year-5
        # growth still in the high-teens; the perpetuity then anchors
        # the terminal value to that.
        #
        # Branch fires when:
        #   - is_capital_goods(ticker) = True (sector-gated; non-cap-
        #     goods hyper-growers are not affected)
        #   - revenue_cagr_3y > CAPITAL_GOODS_HYPER_GROWTH_CAGR (0.30)
        #     OR ticker ∈ CAPITAL_GOODS_HYPER_GROWTH curated set
        #
        # Effect: terminal_g pulled to min(reported_cagr × 0.5, 0.06)
        # so the perpetuity caps even when the 5y fade hasn't fully
        # decayed. 0.5x reflects partial persistence of the spike;
        # 0.06 ceiling = high-end India long-run nominal growth.
        try:
            _is_cap_goods = bool(enriched.get("_is_capital_goods", False))
        except Exception:
            _is_cap_goods = False
        _cg_bare = (ticker or "").upper().replace(".NS", "").replace(".BO", "")
        _is_hyper_named = _cg_bare in CAPITAL_GOODS_HYPER_GROWTH
        _rev_cagr_3y = float(enriched.get("revenue_cagr_3y") or 0.0)
        # HOTFIX 2026-05-18 — Hyper-growth fade DISABLED for capital goods.
        # Post-PR #337 smoke test showed SIEMENS/LT/ABB FVs crushed; the
        # terminal_g pull-down was over-aggressive. The KAYNES override in
        # ticker_overrides.py (terminal_growth_override=0.06) provides
        # the same effect without affecting the rest of the cohort. Once
        # benchmark reconciliation (Layer A) is in place to gate further
        # changes, the fade can be re-enabled with verified bounds.
        if False and _is_cap_goods and (
            _rev_cagr_3y > CAPITAL_GOODS_HYPER_GROWTH_CAGR or _is_hyper_named
        ):
            _hyper_terminal = min(
                max(_rev_cagr_3y, 0.0) * 0.5,
                CAPITAL_GOODS_HYPER_GROWTH_TERMINAL_CAP,
            )
            # Always apply the cap (it's the design's ceiling regardless
            # of whether it raises or lowers the default 0.04). The real
            # taming for hyper-growers like KAYNES happens via:
            #   - MAX_FCF_GROWTH = 0.35 capping base growth in
            #     _clamp(_exponential_fade(...)),
            #   - the ticker_overrides[KAYNES].terminal_growth_override
            #     = 0.06 cap propagated through service.py → DCFEngine.
            # The _g_terminal_eff adjustment here primarily aligns the
            # FCF projection's fade asymptote with the cap so the
            # forecaster's last-3-year mean (`terminal_fcf_norm`) is
            # consistent with the perpetuity_g used downstream.
            _g_terminal_eff = _hyper_terminal
            enriched["_capital_goods_hyper_growth_terminal_g"] = _g_terminal_eff
            log.info(
                "[%s] capital-goods hyper-growth fade: rev_cagr_3y=%.2f → "
                "terminal_g=%.3f (cap=%.3f)",
                ticker, _rev_cagr_3y, _g_terminal_eff,
                CAPITAL_GOODS_HYPER_GROWTH_TERMINAL_CAP,
            )
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
                g = _clamp(_exponential_fade(yr, base_growth, _g_terminal_eff))
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
