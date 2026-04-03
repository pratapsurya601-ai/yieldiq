# screener/valuation_model.py
# ═══════════════════════════════════════════════════════════════
# VALUATION MODEL — Quantitative DCF Analysis
# ═══════════════════════════════════════════════════════════════
#
# KEY PRINCIPLES:
#
# 1. DCF ENTRY ESTIMATE
#    = IV × (1 - desired_margin_of_safety)
#    Entry level BELOW intrinsic value with a safety cushion.
#    For a STRONG company we require 20% MoS → entry at IV × 0.80
#    For GOOD: 25% MoS → IV × 0.75
#    For AVERAGE: 30% MoS → IV × 0.70
#    If current price is ALREADY below entry estimate → Undervalued by model
#    If current price is ABOVE entry estimate → price exceeds DCF entry level
#
# 2. DCF PRICE ESTIMATE (upper range)
#    = IV × (1 + premium)
#    Good companies often trade ABOVE IV due to market premium.
#    STRONG: estimate = IV × 1.15  (15% above fair value)
#    GOOD:   estimate = IV × 1.05  (5% above fair value)
#    AVERAGE:estimate = IV × 0.95  (slight discount to IV)
#    Upper estimate is always ABOVE DCF entry estimate.
#
# 3. DOWNSIDE SUPPORT LEVEL
#    = entry_estimate × (1 - sl_pct)
#    Always placed BELOW the entry estimate.
#    Based on fundamental quality and volatility.
#    STRONG: -12%  GOOD: -15%  AVERAGE: -20%  WEAK: -25%
#
# 4. RISK/REWARD
#    = (Upper Estimate - Entry) / (Entry - Downside Support)
#    Minimum 1.5:1 to be meaningful.
#
# EXAMPLE — TCS (CMP ₹2409, IV ₹1880, GOOD fundamentals):
#    DCF Entry      = 1880 × 0.75 = ₹1410  (25% MoS required)
#    DCF Estimate   = 1880 × 1.05 = ₹1974
#    Downside Level = 1410 × 0.85 = ₹1199
#    R/R            = (1974-1410)/(1410-1199) = 564/211 = 2.7x ✅
#    Signal         = "Overvalued — DCF fair value estimate ₹1880"
#
# EXAMPLE — WIPRO (CMP ₹195, IV ₹209, STRONG fundamentals):
#    DCF Entry      = 209 × 0.80 = ₹167  (20% MoS required)
#    DCF Estimate   = 209 × 1.15 = ₹240
#    Downside Level = 167 × 0.88 = ₹147
#    R/R            = (240-167)/(167-147) = 73/20 = 3.7x ✅
#    Current price ₹195 > DCF entry estimate ₹167 → price above DCF entry level
#
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
import pandas as pd
from utils.logger import get_logger

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
# FUNDAMENTAL STRENGTH SCORER
# ══════════════════════════════════════════════════════════════

def score_fundamentals(enriched: dict) -> dict:
    """
    Score company fundamentals 0-100 across 8 signals.
    IB-quality: includes ROCE, ROE, D/E ratio, gross margin.
    """
    score    = 0
    criteria = {}

    rev_growth  = enriched.get("revenue_growth",  0)
    op_margin   = enriched.get("op_margin",       0)
    fcf_growth  = enriched.get("fcf_growth",      0)
    latest_fcf  = enriched.get("latest_fcf",      0)
    income_df   = enriched.get("income_df",       pd.DataFrame())
    roe         = enriched.get("roe",             0)
    roce_proxy  = enriched.get("roce_proxy",      0)   # ROTA from Yahoo
    de_ratio    = enriched.get("de_ratio",        0)
    gross_margin= enriched.get("gross_margin",    op_margin * 1.4)  # estimate if missing

    # ── Signal 1: Revenue Growth (15 pts) ─────────────────────
    rg_score = (15 if rev_growth >= 0.15 else
                12 if rev_growth >= 0.10 else
                8  if rev_growth >= 0.05 else
                4  if rev_growth >= 0    else 0)
    score += rg_score
    criteria["Revenue Growth"] = f"{rg_score}/15 ({rev_growth:.1%} p.a.)"

    # ── Signal 2: Operating Margin (15 pts) ───────────────────
    om_score = (15 if op_margin >= 0.25 else
                12 if op_margin >= 0.15 else
                8  if op_margin >= 0.10 else
                4  if op_margin >= 0.06 else 0)
    score += om_score
    criteria["Operating Margin"] = f"{om_score}/15 ({op_margin:.1%})"

    # ── Signal 3: FCF Positive (10 pts) ───────────────────────
    fcf_score = 10 if latest_fcf > 0 else 0
    score += fcf_score
    criteria["FCF Positive"] = f"{fcf_score}/10 ({'Yes' if latest_fcf > 0 else 'No'})"

    # ── Signal 4: FCF Growth (10 pts) ─────────────────────────
    fg_score = (10 if fcf_growth >= 0.10 else
                7  if fcf_growth >= 0.05 else
                5  if fcf_growth >= 0    else 0)
    score += fg_score
    criteria["FCF Growth"] = f"{fg_score}/10 ({fcf_growth:.1%} p.a.)"

    # ── Signal 5: Revenue Stability (10 pts) ──────────────────
    rs_score = 5
    if not income_df.empty and "revenue" in income_df.columns:
        rev = income_df["revenue"].replace(0, np.nan).dropna()
        if len(rev) >= 2 and rev.mean() > 0:
            cv = rev.std() / rev.mean()
            rs_score = 10 if cv < 0.10 else 7 if cv < 0.20 else 5 if cv < 0.35 else 2
    score += rs_score
    criteria["Revenue Stability"] = f"{rs_score}/10"

    # ── Signal 6: Return on Equity / ROCE (15 pts) ────────────
    # ROE: best measure of shareholder value creation
    # Use ROCE proxy (ROTA from Yahoo) as quality filter
    if roe > 0 or roce_proxy > 0:
        best_return = max(roe, roce_proxy * 2)  # ROTA × 2 ≈ ROCE rough proxy
        roe_score = (15 if best_return >= 0.20 else
                     12 if best_return >= 0.15 else
                     8  if best_return >= 0.10 else
                     5  if best_return >= 0.05 else 2)
    else:
        # Estimate from op_margin as proxy
        roe_score = 10 if op_margin >= 0.15 else 6 if op_margin >= 0.08 else 3
    score += roe_score
    criteria["ROE / ROCE"] = f"{roe_score}/15 (ROE={roe:.1%}, ROTA={roce_proxy:.1%})"

    # ── Signal 7: Debt Safety (15 pts) ────────────────────────
    # D/E ratio: lower is better. Zero debt = full score.
    if de_ratio <= 0:
        debt_score = 15   # net cash or zero debt
    elif de_ratio <= 0.20:
        debt_score = 13
    elif de_ratio <= 0.50:
        debt_score = 10
    elif de_ratio <= 1.00:
        debt_score = 7
    elif de_ratio <= 2.00:
        debt_score = 4
    else:
        debt_score = 1   # highly leveraged
    score += debt_score
    criteria["Debt / Equity"] = f"{debt_score}/15 (D/E={de_ratio:.2f}x)"

    # ── Signal 8: Gross Margin Quality (10 pts) ───────────────
    # High gross margin = pricing power / moat indicator
    gm_score = (10 if gross_margin >= 0.50 else
                8  if gross_margin >= 0.35 else
                6  if gross_margin >= 0.20 else
                4  if gross_margin >= 0.10 else 2)
    score += gm_score
    criteria["Gross Margin"] = f"{gm_score}/10 ({gross_margin:.1%})"

    grade = ("STRONG" if score >= 80 else
             "GOOD"   if score >= 60 else
             "AVERAGE"if score >= 40 else "WEAK")
    color = {"STRONG": "#10b981", "GOOD": "#3b82f6",
             "AVERAGE": "#f59e0b", "WEAK": "#ef4444"}[grade]

    return {"score": score, "grade": grade, "color": color, "criteria": criteria}


# ══════════════════════════════════════════════════════════════
# HOLDING PERIOD ESTIMATOR
# ══════════════════════════════════════════════════════════════

def estimate_holding_period(mos, fundamental_score, rev_growth, fcf_growth) -> dict:
    """Estimate suggested holding period based on DCF inputs."""
    # Base from MoS
    if mos >= 0.40:
        base_min, base_max = 18, 48
    elif mos >= 0.20:
        base_min, base_max = 12, 36
    elif mos >= 0.05:
        base_min, base_max = 6, 18
    else:
        base_min, base_max = 12, 36  # overvalued → wait and hold long if entering at dip

    # Adjust for strength
    if fundamental_score >= 80:
        base_max = int(base_max * 1.5)
        strength_note = "Strong fundamentals support long-term compounding"
    elif fundamental_score >= 60:
        base_max = int(base_max * 1.2)
        strength_note = "Good fundamentals — medium to long term"
    elif fundamental_score < 40:
        base_max = max(base_max // 2, 6)
        strength_note = "Weak fundamentals — shorter hold recommended"
    else:
        strength_note = "Average fundamentals"

    avg_growth = (rev_growth + fcf_growth) / 2
    growth_note = ""
    if avg_growth >= 0.15:
        growth_note = "High growth company — re-rating can happen faster"
        base_max = min(base_max, 30)
    elif avg_growth < 0.03:
        growth_note = "Low growth — patience required for value realisation"

    label = "Long Term (3+ years)" if base_max >= 36 else \
            "Medium Term (1.5–3 years)" if base_max >= 18 else \
            "Short-Medium (9–18 months)" if base_max >= 9 else \
            "Short Term (3–9 months)"

    rationale = strength_note
    if growth_note:
        rationale += f". {growth_note}"

    return {"min_months": base_min, "max_months": base_max,
            "label": label, "rationale": rationale}


# ══════════════════════════════════════════════════════════════
# PRICE TARGETS — CORRECTED LOGIC
# ══════════════════════════════════════════════════════════════

def compute_price_targets(
    current_price:     float,
    intrinsic_value:   float,
    mos:               float,
    fundamental_score: int,
    enriched:          dict = None,
) -> dict:
    """
    Quantitative price level estimates.

    DCF ENTRY ESTIMATE:
    - If stock is UNDERVALUED (IV > price): entry = IV × (1 - MoS) as before
    - If stock is OVERVALUED (price > IV): entry = current price × (1 - dip%)
      because waiting for IV is unrealistic — target a realistic correction

    DCF PRICE ESTIMATE (IB standard):
    - If forward EPS available: estimate = forward EPS × sector PE (FY+1 basis)
    - Else: estimate = IV × quality premium (fallback)

    DOWNSIDE SUPPORT LEVEL:
    - Always anchored to DCF entry estimate, not IV
    """
    if intrinsic_value <= 0 or current_price <= 0:
        return {
            "buy_price": None, "target_price": None, "stop_loss": None,
            "rr_ratio": None, "entry_signal": "Insufficient Data — no valid IV",
            "target_upside_pct": None, "sl_pct": None,
        }

    enriched = enriched or {}

    # ── Quality parameters ─────────────────────────────────────
    if fundamental_score >= 80:
        required_mos    = 0.20
        quality_premium = 0.15
        sl_pct          = 0.12
        dip_target      = 0.10   # wait for 10% dip if overvalued
    elif fundamental_score >= 60:
        required_mos    = 0.25
        quality_premium = 0.05
        sl_pct          = 0.15
        dip_target      = 0.12
    elif fundamental_score >= 40:
        required_mos    = 0.30
        quality_premium = -0.05
        sl_pct          = 0.20
        dip_target      = 0.15
    else:
        required_mos    = 0.35
        quality_premium = -0.15
        sl_pct          = 0.25
        dip_target      = 0.20

    # ── DCF entry estimate ─────────────────────────────────────
    iv_buy_price = intrinsic_value * (1 - required_mos)

    if current_price <= iv_buy_price:
        # Already deeply undervalued — entry zone IS current price
        # Show entry zone slightly below current to give a small buffer
        buy_price    = current_price * 0.98   # 2% below current = entry zone
        entry_signal = f"Undervalued by {abs(mos)*100:.0f}% — current price {current_price:.0f} below DCF fair value"
    elif mos >= -0.10:
        # Slightly overvalued (<10%) — near DCF fair value
        buy_price    = current_price * (1 - dip_target * 0.5)
        entry_signal = f"Near DCF Fair Value — DCF entry estimate {buy_price:.0f}"
    else:
        # Overvalued — target realistic correction, not theoretical IV level
        market_buy   = current_price * (1 - dip_target)
        buy_price    = max(market_buy, iv_buy_price)
        # For SEVERELY overvalued (>30%), cap buy_price at IV
        if mos < -0.30:
            buy_price = min(buy_price, intrinsic_value * 1.05)
        pct_ov       = abs(mos) * 100
        entry_signal = f"Overvalued by {pct_ov:.0f}% — DCF fair value estimate {intrinsic_value:.0f}"

    # ── DCF price estimate (IB: use forward PE if available) ───
    target_price = None

    # Try forward EPS × PE first (IB standard)
    forward_eps = enriched.get("forward_eps", 0)
    sector      = enriched.get("sector", "general")
    if forward_eps > 0:
        from screener.valuation_crosscheck import SECTOR_PE
        sector_pe_data = SECTOR_PE.get(sector, SECTOR_PE["general"])
        pe_median      = sector_pe_data["pe_median"]

        # Sanity check: reject adjusted/cash EPS that implies unrealistically low P/E
        price_now = enriched.get("price", 0) or current_price
        _is_financial = sector in {"us_banks", "us_reits"}
        _pe_floor = 5 if _is_financial else 8
        implied_fwd_pe = price_now / forward_eps if forward_eps > 0 else 0

        if implied_fwd_pe >= _pe_floor:
            # EPS looks like genuine GAAP EPS — use it
            current_fwd_pe = enriched.get("forward_pe", 0) or implied_fwd_pe
            if current_fwd_pe > _pe_floor:
                pe_target = min(pe_median, current_fwd_pe * 1.10)
            else:
                pe_target = pe_median

            actual_growth = enriched.get("revenue_growth", 0)
            fwd_growth    = max(0.03, 0.60 * actual_growth + 0.40 * 0.10)
            fy1_eps       = forward_eps * (1 + fwd_growth)
            target_price  = fy1_eps * pe_target
            log.debug(f"DCF estimate: EPS {forward_eps:.2f} × (1+{fwd_growth:.1%}) × "
                      f"{pe_target:.1f}x PE = {target_price:.0f}")
        else:
            # Adjusted/cash EPS — skip PE target, fall through to IV-based estimate
            log.debug(f"[{enriched.get('ticker','?')}] forward_eps {forward_eps:.2f} implies "
                      f"P/E {implied_fwd_pe:.1f}x < floor {_pe_floor}x — using IV estimate instead")

    # Fallback: IV × quality premium
    if not target_price or target_price <= 0:
        target_price = intrinsic_value * (1 + quality_premium)

    # Hard cap: DCF estimate cannot exceed 1.5× intrinsic value for cyclicals,
    # 2× for all others.
    CYCLICAL_SECTORS = {"us_energy","us_materials","us_consumer_disc",
                        "us_communication","us_banks","us_reits"}
    iv_cap_mult = 1.5 if sector in CYCLICAL_SECTORS else 2.0
    if intrinsic_value > 0 and target_price > intrinsic_value * iv_cap_mult:
        log.warning(f"DCF estimate {target_price:.0f} > {iv_cap_mult}×IV {intrinsic_value*iv_cap_mult:.0f} — capping")
        target_price = intrinsic_value * (1 + quality_premium)

    # DCF estimate must be above entry level with meaningful upside
    # Never set estimate above intrinsic value when stock is overvalued
    if target_price <= buy_price * 1.10:
        if mos >= 0:
            target_price = max(buy_price * 1.25, intrinsic_value * 1.05)
        else:
            target_price = max(intrinsic_value * 1.05, buy_price * 1.05)

    # ── Downside support level ──────────────────────────────────
    stop_loss = buy_price * (1 - sl_pct)

    # ── R/R from entry estimate ─────────────────────────────────
    upside   = target_price - buy_price
    downside = buy_price - stop_loss
    rr_ratio = round(upside / downside, 2) if downside > 0 else 0

    target_upside_pct = round(
        ((target_price - current_price) / current_price) * 100, 1
    )

    return {
        "buy_price":         round(buy_price,      2),
        "target_price":      round(target_price,   2),
        "stop_loss":         round(stop_loss,       2),
        "rr_ratio":          rr_ratio,
        "sl_pct":            round(sl_pct * 100,   1),
        "required_mos_pct":  round(required_mos * 100, 0),
        "entry_signal":      entry_signal,
        "target_upside_pct": target_upside_pct,
    }


# ══════════════════════════════════════════════════════════════
# MASTER FUNCTION
# ══════════════════════════════════════════════════════════════

def generate_valuation_summary(
    enriched:        dict,
    current_price:   float,
    intrinsic_value: float,
    mos:             float,
) -> dict:
    """Generate complete valuation summary."""
    if not enriched.get("dcf_reliable", True):
        # Still score fundamentals — DCF may be unreliable but the business quality
        # is real and should be shown (e.g. NVDA, TSLA are fundamentally strong)
        fundamental = score_fundamentals(enriched)
        grade  = fundamental["grade"]
        score  = fundamental["score"]
        reason = enriched.get("unreliable_reason", "hyper-growth / negative FCF")
        return {
            "fundamental":    fundamental,
            "price_targets":  {
                "entry_signal":      f"DCF unreliable ({reason}) — use P/E, PEG, or EV/Sales",
                "buy_price":         None,
                "target_price":      None,
                "stop_loss":         None,
                "rr_ratio":          None,
                "target_upside_pct": None,
                "sl_pct":            None,
            },
            "holding_period": {"label": "N/A", "rationale": f"DCF not applicable — {reason}"},
            "summary":        f"⚡ {grade} ({score}/100) — DCF unreliable ({reason}), use relative valuation",
        }

    fundamental   = score_fundamentals(enriched)
    price_targets = compute_price_targets(
        current_price=current_price,
        intrinsic_value=intrinsic_value,
        mos=mos,
        fundamental_score=fundamental["score"],
        enriched=enriched,
    )
    holding_period = estimate_holding_period(
        mos=mos,
        fundamental_score=fundamental["score"],
        rev_growth=enriched.get("revenue_growth", 0),
        fcf_growth=enriched.get("fcf_growth",     0),
    )

    grade  = fundamental["grade"]
    hp     = holding_period["label"]
    entry  = price_targets["entry_signal"]
    rr     = price_targets.get("rr_ratio", 0) or 0
    bp     = price_targets.get("buy_price", 0) or 0
    tp     = price_targets.get("target_price", 0) or 0

    if current_price <= bp and fundamental["score"] >= 60:
        summary = f"✅ {grade} · Undervalued — DCF fair value {intrinsic_value:.0f} · DCF estimate {tp:.0f} · R/R {rr:.1f}x · {hp}"
    elif mos >= 0:
        summary = f"👀 {grade} · Undervalued — DCF entry estimate {bp:.0f} · DCF estimate {tp:.0f} · R/R {rr:.1f}x"
    elif mos >= -0.20:
        summary = f"⚖️ {grade} · Near DCF fair value · DCF entry estimate {bp:.0f} on dips"
    else:
        summary = f"❌ Overvalued {abs(mos)*100:.0f}% · DCF fair value {intrinsic_value:.0f} · Insufficient Data at market price"

    return {
        "fundamental":    fundamental,
        "price_targets":  price_targets,
        "holding_period": holding_period,
        "summary":        summary,
    }


# ══════════════════════════════════════════════════════════════
# BACKWARDS COMPATIBILITY ALIAS
# ══════════════════════════════════════════════════════════════
generate_investment_plan = generate_valuation_summary
