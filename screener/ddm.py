# screener/ddm.py
# ═══════════════════════════════════════════════════════════════
# DIVIDEND DISCOUNT MODEL (DDM)
# ═══════════════════════════════════════════════════════════════
#
# The DDM answers a simple question:
#   "If I buy this stock today and hold it forever,
#    what stream of dividends am I paying for?"
#
# It is the CORRECT model for mature dividend-paying companies
# where dividends are stable and predictable — Coca-Cola, P&G,
# Johnson & Johnson, utilities, telecom, FMCG.
#
# For growth stocks with tiny or zero dividends (NVDA, MSFT),
# DCF is more appropriate and DDM is marked N/A.
#
# ── MODELS USED ─────────────────────────────────────────────
#
# 1. GORDON GROWTH MODEL (single-stage):
#    P = D1 / (r - g)
#    Best for: mature, slow-growth dividend payers (utilities, telecom)
#    D1 = next year dividend = D0 × (1+g)
#    r  = required return (cost of equity from CAPM)
#    g  = long-run sustainable dividend growth
#
# 2. TWO-STAGE DDM (more accurate):
#    Stage 1 (years 1-5): High growth phase
#      PV = Σ [D0 × (1+g_high)^t / (1+r)^t]
#    Stage 2 (terminal): Stable growth phase (Gordon Growth)
#      TV = D_5 × (1+g_stable) / (r - g_stable)
#      PV_TV = TV / (1+r)^5
#    Total IV = PV(Stage 1) + PV(Stage 2)
#    Best for: dividend growers (KO, JNJ, NEE)
#
# 3. H-MODEL (dividend growth fade):
#    For companies transitioning from high to stable growth
#    P = D0 × (1+g_stable)/(r-g_stable) + D0×H×(g_high-g_stable)/(r-g_stable)
#    H = half-life of high-growth period (typically 5)
#
# ── BLEND WITH DCF ──────────────────────────────────────────
#
# For dividend stocks, we blend DDM with DCF:
#   - High yield (>3%): 60% DDM / 40% DCF
#   - Medium yield (1.5-3%): 40% DDM / 60% DCF
#   - Low yield (<1.5%): 20% DDM / 80% DCF  (basically just DCF)
#
# ── SUSTAINABILITY CHECK ─────────────────────────────────────
#
# A dividend is only worth modelling if it's sustainable:
#   Payout ratio < 80% (for non-REITs)
#   FCF payout ratio < 90% (dividends covered by free cash flow)
#   Dividend growth > 0% (at least maintaining)
#
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)

# ── CONSTANTS ────────────────────────────────────────────────
MIN_YIELD_FOR_DDM   = 0.005    # 0.5% — below this DDM is not meaningful
HIGH_YIELD_THRESHOLD = 0.030   # 3.0% — above this DDM is primary model
MAX_PAYOUT_RATIO    = 0.90     # above this dividend may not be sustainable
STABLE_GROWTH_US    = 0.025    # long-run US GDP (dividend stable growth anchor)
STABLE_GROWTH_INDIA = 0.060    # long-run India GDP
DDM_STAGE1_YEARS    = 5        # years of high-growth phase in 2-stage model


# ── DIVIDEND GROWTH ESTIMATION ────────────────────────────────

def estimate_dividend_growth(
    enriched:        dict,
    div_rate:        float,
    payout_ratio:    float,
    is_indian:       bool = False,
) -> tuple[float, float, str]:
    """
    Estimate near-term and long-run dividend growth rates.

    Returns (g_high, g_stable, method_used)

    Priority:
    1. FCF growth (most reliable — dividends can only grow if cash grows)
    2. Earnings growth × retention
    3. Revenue growth (proxy)
    4. Sector-specific default
    """
    stable_gdp = STABLE_GROWTH_INDIA if is_indian else STABLE_GROWTH_US

    fcf_g   = enriched.get("fcf_growth",       0) or 0
    rev_g   = enriched.get("revenue_growth",    0) or 0
    eps_g   = enriched.get("forward_eps",       0)
    trail_e = enriched.get("trailing_eps",      0) or 0

    # Cap growth: dividends can't grow faster than FCF long-term
    fcf_g = max(min(fcf_g, 0.20), -0.05)  # cap at 20%, floor at -5%

    # Method 1: FCF-based (preferred)
    if fcf_g > 0.001:
        # Dividends grow at FCF growth rate, faded toward GDP
        g_high   = min(fcf_g, 0.15)        # near-term: FCF growth (capped)
        g_stable = min(fcf_g * 0.5, stable_gdp * 1.5)  # long-run: fade
        g_stable = max(g_stable, stable_gdp * 0.5)      # floor at 0.5× GDP
        return g_high, g_stable, f"FCF growth ({fcf_g:.1%} → {g_stable:.1%} stable)"

    # Method 2: Revenue growth proxy
    if rev_g > 0.001:
        g_high   = min(rev_g * 0.7, 0.12)  # dividends typically grow slower than revenue
        g_stable = min(rev_g * 0.4, stable_gdp * 1.5)
        g_stable = max(g_stable, stable_gdp * 0.5)
        return g_high, g_stable, f"Revenue growth proxy ({rev_g:.1%} → {g_stable:.1%})"

    # Method 3: Sector default (conservative)
    sector = enriched.get("sector", "general")
    defaults = {
        "us_consumer_staples":    (0.05, 0.03),
        "us_utilities":           (0.04, 0.025),
        "us_communication":       (0.03, 0.02),
        "us_healthcare_services": (0.06, 0.035),
        "us_pharma":              (0.05, 0.03),
        "us_energy":              (0.03, 0.02),
        "us_reits":               (0.04, 0.025),
        "us_banks":               (0.05, 0.03),
        "fmcg":                   (0.08, 0.06),
        "pharma":                 (0.08, 0.06),
        "it_services":            (0.10, 0.07),
    }
    g_high, g_stable = defaults.get(sector, (0.04, stable_gdp))
    return g_high, g_stable, f"Sector default for {sector}"


# ── SUSTAINABILITY CHECK ──────────────────────────────────────

def check_dividend_sustainability(
    div_rate:     float,
    payout_ratio: float,
    fcf_payout:   float,
    eps:          float,
    div_yield:    float,
) -> tuple[bool, str, str]:
    """
    Check if the dividend is sustainable.
    Returns (is_sustainable, warning, colour)
    """
    issues = []

    if payout_ratio > MAX_PAYOUT_RATIO:
        issues.append(f"payout ratio {payout_ratio:.0%} > 90%")
    if fcf_payout > 0.95:
        issues.append(f"FCF payout {fcf_payout:.0%} > 95%")
    if div_yield > 0.10:
        issues.append(f"yield {div_yield:.1%} may signal distress")
    if eps > 0 and div_rate > eps * 1.2:
        issues.append("dividend exceeds earnings per share")

    if not issues:
        return True, "Dividend appears well-covered by earnings and FCF", "green"
    elif len(issues) == 1:
        return True, f"Mild concern: {issues[0]}", "amber"
    else:
        return False, f"Sustainability risk: {'; '.join(issues)}", "red"


# ── GORDON GROWTH MODEL ───────────────────────────────────────

def gordon_growth_ddm(
    div_rate: float,   # D0 — current annual dividend per share
    g_stable: float,   # long-run dividend growth rate
    re:       float,   # required return (cost of equity)
) -> float:
    """
    Single-stage Gordon Growth Model.
    P = D1 / (r - g)  where D1 = D0 × (1+g)
    """
    spread = re - g_stable
    if spread <= 0.001:
        return 0.0   # model breaks when r ≈ g (infinite value)
    d1 = div_rate * (1 + g_stable)
    return d1 / spread


# ── TWO-STAGE DDM ────────────────────────────────────────────

def two_stage_ddm(
    div_rate:   float,  # D0 — current annual dividend
    g_high:     float,  # near-term growth (Stage 1)
    g_stable:   float,  # long-run growth (Stage 2)
    re:         float,  # required return
    n_high:     int = DDM_STAGE1_YEARS,
) -> tuple[float, float, float]:
    """
    Two-stage DDM.
    Returns (total_iv, pv_stage1, pv_stage2)
    """
    # Stage 1: PV of dividends during high-growth phase
    pv_stage1 = 0.0
    d_t = div_rate
    for t in range(1, n_high + 1):
        d_t = d_t * (1 + g_high)
        pv_stage1 += d_t / (1 + re) ** t

    # Stage 2: Terminal value at end of Stage 1 (Gordon Growth)
    spread = re - g_stable
    if spread <= 0.001:
        return pv_stage1, pv_stage1, 0.0

    d_n1    = d_t * (1 + g_stable)   # first dividend in stable phase
    tv      = d_n1 / spread           # terminal value at year n
    pv_tv   = tv / (1 + re) ** n_high # PV of terminal value

    total = pv_stage1 + pv_tv
    return total, pv_stage1, pv_tv


# ── MAIN DDM ANALYSIS ─────────────────────────────────────────

def compute_ddm(
    enriched:      dict,
    current_price: float,
    dcf_iv:        float,
    wacc:          float,
    fx:            float = 1.0,
) -> dict:
    """
    Full DDM analysis. Returns blended IV incorporating DDM.

    Returns:
        applicable:      bool — is DDM meaningful for this stock?
        div_yield:       float
        div_rate:        float — annual dividend per share
        ddm_iv_gordon:   float — single-stage IV
        ddm_iv_2stage:   float — two-stage IV
        blended_iv:      float — DDM + DCF blend
        blend_weight:    float — DDM weight in blend (0-1)
        g_high:          float — assumed near-term growth
        g_stable:        float — assumed long-run growth
        sustainable:     bool
        sustainability_msg: str
        mos_ddm:         float — MoS using DDM IV
        mos_blended:     float — MoS using blended IV
        summary:         str
        not_applicable_reason: str
    """
    ticker    = enriched.get("ticker", "?")
    sector    = enriched.get("sector", "general")
    shares    = enriched.get("shares", 0)
    fcf       = enriched.get("yahoo_fcf_ttm") or enriched.get("latest_fcf", 0)
    eps       = enriched.get("trailing_eps", 0) or enriched.get("forward_eps", 0) or 0
    is_indian = ticker.upper().endswith(".NS") or ticker.upper().endswith(".BO")

    # ── Get dividend data ─────────────────────────────────────
    div_yield    = enriched.get("dividend_yield", 0) or 0
    div_rate     = enriched.get("dividend_rate", 0) or 0
    payout_ratio = enriched.get("payout_ratio", 0) or 0
    five_yr_avg  = enriched.get("five_yr_avg_div_yield", 0) or 0

    # Reconstruct div_rate from yield if not available
    if div_rate == 0 and div_yield > 0 and current_price > 0:
        div_rate = div_yield * current_price

    # ── Check applicability ───────────────────────────────────
    if div_yield < MIN_YIELD_FOR_DDM or div_rate <= 0:
        reason = (
            f"Dividend yield {div_yield*100:.2f}% is below the {MIN_YIELD_FOR_DDM*100:.1f}% "
            f"threshold for DDM — use DCF instead"
        )
        return {
            "applicable": False,
            "not_applicable_reason": reason,
            "div_yield": div_yield,
            "blended_iv": dcf_iv,
            "blend_weight": 0.0,
        }

    # ── Cost of equity (required return) ─────────────────────
    # Use WACC as proxy (for unleveraged or equity-heavy companies)
    # For utility/REIT, use slightly lower (less equity risk)
    re = wacc
    is_low_risk = sector in ("us_utilities", "us_reits", "us_consumer_staples", "fmcg")
    if is_low_risk:
        re = max(wacc * 0.85, 0.055)  # floor at 5.5%

    # ── Estimate growth rates ─────────────────────────────────
    g_high, g_stable, growth_method = estimate_dividend_growth(
        enriched, div_rate, payout_ratio, is_indian
    )

    # Safety: g must be < re for Gordon Growth to work
    g_stable = min(g_stable, re - 0.01)
    g_high   = min(g_high,   re - 0.005)

    # ── FCF payout ratio ─────────────────────────────────────
    div_total   = div_rate * shares if shares > 0 else 0
    fcf_payout  = div_total / fcf if fcf > 0 else 1.0

    # ── Sustainability check ──────────────────────────────────
    sustainable, sustain_msg, sustain_colour = check_dividend_sustainability(
        div_rate=div_rate,
        payout_ratio=payout_ratio,
        fcf_payout=min(fcf_payout, 2.0),
        eps=eps,
        div_yield=div_yield,
    )

    # ── Run DDM models ───────────────────────────────────────
    gordon_iv = gordon_growth_ddm(div_rate, g_stable, re)
    two_iv, pv1, pv2 = two_stage_ddm(div_rate, g_high, g_stable, re)

    # Apply FX
    gordon_iv_d = gordon_iv * fx
    two_iv_d    = two_iv   * fx
    div_rate_d  = div_rate * fx

    # ── Select primary DDM IV ─────────────────────────────────
    # Use 2-stage for dividend growers, Gordon for mature payers
    if g_high > g_stable * 1.5:
        ddm_iv = two_iv   # significant growth → 2-stage
        model_used = "Two-Stage DDM"
    else:
        # Weight 2-stage and Gordon equally for stability
        ddm_iv = (two_iv + gordon_iv) / 2
        model_used = "Avg Gordon + Two-Stage"

    ddm_iv_d = ddm_iv * fx

    # ── Blend DDM with DCF ───────────────────────────────────
    if div_yield >= HIGH_YIELD_THRESHOLD:
        ddm_weight = 0.60   # high yield → DDM is primary
    elif div_yield >= 0.015:
        ddm_weight = 0.40   # medium yield → equal weight
    else:
        ddm_weight = 0.20   # low yield → DCF dominates

    # Reduce DDM weight if dividend is unsustainable
    if not sustainable:
        ddm_weight = min(ddm_weight, 0.25)

    dcf_weight  = 1 - ddm_weight
    blended_iv  = (ddm_weight * ddm_iv + dcf_weight * dcf_iv) * fx

    # ── MoS calculations ─────────────────────────────────────
    price_d    = current_price * fx
    mos_ddm    = (ddm_iv_d - price_d) / price_d   if price_d > 0 else 0
    mos_blend  = (blended_iv - price_d) / price_d  if price_d > 0 else 0
    mos_dcf    = (dcf_iv * fx - price_d) / price_d if price_d > 0 else 0

    # ── Bear / Base / Bull DDM scenarios ─────────────────────
    scenarios = {}
    for label, g_h_mult, g_s_mult in [
        ("Bear 🐻", 0.5,  0.7),
        ("Base 📊", 1.0,  1.0),
        ("Bull 🐂", 1.5,  1.3),
    ]:
        g_h = min(g_high  * g_h_mult, re - 0.005)
        g_s = min(g_stable * g_s_mult, re - 0.01)
        iv_s, _, _ = two_stage_ddm(div_rate, g_h, g_s, re)
        scenarios[label] = {
            "g_high":   g_h,
            "g_stable": g_s,
            "iv":       iv_s * fx,
            "mos":      (iv_s * fx - price_d) / price_d if price_d > 0 else 0,
        }

    # ── Summary ──────────────────────────────────────────────
    summary = _build_summary(
        ticker=ticker,
        div_yield=div_yield,
        div_rate_d=div_rate_d,
        g_high=g_high,
        g_stable=g_stable,
        ddm_iv_d=ddm_iv_d,
        blended_iv=blended_iv,
        price_d=price_d,
        mos_blend=mos_blend,
        mos_ddm=mos_ddm,
        mos_dcf=mos_dcf,
        ddm_weight=ddm_weight,
        model_used=model_used,
        sustainable=sustainable,
        sustain_msg=sustain_msg,
        growth_method=growth_method,
    )

    return {
        "applicable":         True,
        "ticker":             ticker,
        "div_yield":          div_yield,
        "div_rate":           div_rate_d,
        "payout_ratio":       payout_ratio,
        "fcf_payout":         fcf_payout,
        "five_yr_avg_yield":  five_yr_avg,
        "g_high":             g_high,
        "g_stable":           g_stable,
        "growth_method":      growth_method,
        "re":                 re,
        "ddm_iv_gordon":      gordon_iv_d,
        "ddm_iv_2stage":      two_iv_d,
        "pv_stage1":          pv1 * fx,
        "pv_stage2":          pv2 * fx,
        "ddm_iv":             ddm_iv_d,
        "model_used":         model_used,
        "dcf_iv":             dcf_iv * fx,
        "ddm_weight":         ddm_weight,
        "dcf_weight":         dcf_weight,
        "blended_iv":         blended_iv,
        "mos_ddm":            mos_ddm,
        "mos_blended":        mos_blend,
        "mos_dcf":            mos_dcf,
        "sustainable":        sustainable,
        "sustainability_msg": sustain_msg,
        "sustainability_colour": sustain_colour,
        "scenarios":          scenarios,
        "summary":            summary,
    }


def _build_summary(
    ticker, div_yield, div_rate_d, g_high, g_stable,
    ddm_iv_d, blended_iv, price_d, mos_blend, mos_ddm, mos_dcf,
    ddm_weight, model_used, sustainable, sustain_msg, growth_method,
) -> str:
    sym = "₹"  # simplified — dashboard will format with actual sym

    line1 = (
        f"{ticker} pays a {div_yield*100:.1f}% dividend yield "
        f"({sym}{div_rate_d:.2f}/share annually). "
        f"The {model_used} assumes {g_high*100:.1f}% near-term growth "
        f"fading to {g_stable*100:.1f}% long-run, giving a DDM fair value "
        f"of {sym}{ddm_iv_d:.0f}."
    )

    line2 = (
        f"Blended with DCF ({ddm_weight:.0%} DDM / {1-ddm_weight:.0%} DCF), "
        f"the combined fair value is {sym}{blended_iv:.0f} — "
        f"{'a ' + f'{mos_blend*100:.0f}% discount' if mos_blend > 0 else 'a ' + f'{abs(mos_blend)*100:.0f}% premium'} "
        f"to today's price."
    )

    if not sustainable:
        line3 = f"⚠️ Sustainability concern: {sustain_msg}"
    else:
        line3 = f"The dividend appears well-covered: {sustain_msg}"

    return f"{line1} {line2} {line3}"
