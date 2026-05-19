"""Story-DCF valuation engine for loss-making / early-stage platforms.

═══════════════════════════════════════════════════════════════
Why this exists
─────────────────────────────────────────────────────────────────────
A handful of Indian listed platforms (PAYTM, GROWW, MEESHO, NUVAMA,
POLICYBZR) cannot be valued by ANY existing engine:
  - DCF: trailing FCF near zero → collapses to ₹0
  - P/B: asset-light, BVPS tiny, multiplier explosive
  - Tier 2 cohort (P/E): requires positive peer EPS → returns None
  - Platform P/S engine (PR #389): requires ≥3 peers with valid P/S
    — works for some but PAYTM/MEESHO still hit ₹0 because their
    cohort's P/S is itself volatile.

Damodaran's "narrative + numbers" framework is the academy-recommended
approach for these: build an explicit revenue forecast with margin
convergence, then DCF it. The "story" is operator-curated (revenue
CAGR fade trajectory, target operating margin, reinvestment rate)
and lives in a JSON config file alongside the existing
``insurance_appraisal_inputs`` and ``realty_land_bank_inputs``
patterns — not in the DB to keep canary-stable + snapshot-able per
``docs/CLAUDE.md`` Rule 2.

Caller contract
───────────────
``compute_story_dcf_fair_value(ticker, sector, financials,
story_params=None)``

  Returns Optional[dict] with the standard valuation-engine shape:
  fair_value, bear_case, base_case, bull_case, verdict, method,
  valuation_method, confidence_score, _meta.

  Returns None when:
    - sector is not a supported platform/fintech key
    - no story_params for this ticker (neither override nor
      industry default)
    - revenue / shares / current_price missing

Wired as the THIRD safety-net rung in dcf_collapse_safety_net.py,
after platform P/S engine (which is already after Tier 2 cohort).
Strict-additive: never promoted to a primary engine.

Confidence
──────────
Capped at 50 (vs 65 for platform P/S, 75 for Tier 2, 70-90 for DCF).
Story DCFs are operator-curated narratives — inherently more
uncertain than peer-anchored multiples. The _meta block carries the
full assumption set so the frontend can render "this is a story,
not a fact" copy.

Hard rules honoured
───────────────────
* Pure-function core (testable without DB or network)
* Per-ticker overrides via JSON (operator can edit without code
  change — same pattern as insurance EV admin UI)
* No CACHE_VERSION bump — additive engine, doesn't change shape
  of existing analyses that already have FV
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger("yieldiq.story_dcf")


# ── Sector key normalisation ────────────────────────────────────
# Map prod sector strings + the canonical internet_platform / fintech_
# broker keys we use elsewhere. Returns the industry default key used
# in ``INDUSTRY_STORY_DEFAULTS``.
_SECTOR_TO_INDUSTRY_KEY: dict[str, str] = {
    "internet platform":     "ecommerce",   # default; per-ticker overrides for payments etc.
    "internet_platform":     "ecommerce",
    "e-commerce":            "ecommerce",
    "ecommerce":             "ecommerce",
    "internet":              "ecommerce",
    "payments":              "payments",

    "fintech":               "fintech_broker",
    "fintech_broker":        "fintech_broker",
    "online broker":         "fintech_broker",
    "capital markets":       "fintech_broker",
    "wealth management":     "wealth_mgmt",
    "insurance aggregator":  "insurance_aggregator",
}


@dataclass(frozen=True)
class StoryParams:
    """Curated narrative + numbers per Damodaran. All defaults are
    industry-typical; per-ticker overrides are loaded from
    ``config/story_dcf_overrides.json`` at startup."""
    initial_growth: float          # Year-1 revenue growth (0.30 = 30%)
    target_op_margin: float        # Steady-state EBIT margin (after fade)
    terminal_growth: float = 0.05  # Perpetuity growth
    fade_years: int = 10           # Explicit forecast horizon
    margin_convergence_yr: int = 5 # Year by which target margin is reached
    reinvestment_rate: float = 0.65  # Capex+ΔWC as % of ΔRevenue
    wacc: float = 0.13             # Risk-adjusted discount rate
    tax_rate: float = 0.25
    confidence_floor: int = 35
    confidence_cap: int = 50


# Industry defaults — start-of-fade growth + steady-state margin assumptions
# anchored to peer-set medians (verified against listed-co disclosures).
INDUSTRY_STORY_DEFAULTS: dict[str, StoryParams] = {
    "payments": StoryParams(
        initial_growth=0.25, target_op_margin=0.25,
        reinvestment_rate=0.65, wacc=0.13,
    ),
    "fintech_broker": StoryParams(
        initial_growth=0.20, target_op_margin=0.20,
        reinvestment_rate=0.60, wacc=0.13,
    ),
    "ecommerce": StoryParams(
        initial_growth=0.30, target_op_margin=0.15,
        reinvestment_rate=0.75, wacc=0.14,
    ),
    "wealth_mgmt": StoryParams(
        initial_growth=0.22, target_op_margin=0.30,
        reinvestment_rate=0.55, wacc=0.12,
    ),
    "insurance_aggregator": StoryParams(
        initial_growth=0.28, target_op_margin=0.18,
        reinvestment_rate=0.70, wacc=0.13,
    ),
}


# Per-ticker overrides path (JSON). Operator can edit without code change.
_OVERRIDES_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "config" / "story_dcf_overrides.json"
)


@lru_cache(maxsize=1)
def _load_overrides() -> dict[str, dict]:
    """Cache the operator-curated override file. Returns {} if absent
    or malformed (graceful degradation — caller falls through to
    industry default)."""
    try:
        if not _OVERRIDES_PATH.exists():
            return {}
        with open(_OVERRIDES_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("story_dcf overrides load failed: %s", exc)
        return {}


def _params_for(ticker: str, sector_key: str) -> Optional[StoryParams]:
    """Return the StoryParams to use for ``ticker`` — per-ticker override
    overlay on top of the industry default. None if neither exists."""
    bare = (ticker or "").replace(".NS", "").replace(".BO", "").upper()
    base = INDUSTRY_STORY_DEFAULTS.get(sector_key)
    overrides = _load_overrides()
    override = overrides.get(bare)
    if not base and not override:
        return None
    if not base:
        # Override-only — must contain at least the required fields
        try:
            return StoryParams(**override)
        except (TypeError, ValueError):
            logger.warning(
                "story_dcf: %s has override but missing required fields", bare,
            )
            return None
    if not override:
        return base
    # Merge override onto base
    try:
        return replace(base, **{
            k: v for k, v in override.items()
            if k in base.__dataclass_fields__
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("story_dcf merge failed for %s: %s", bare, exc)
        return base


# ── Pure-function cashflow path ─────────────────────────────────
def _revenue_path(rev0: float, g0: float, g_term: float, n: int) -> list[float]:
    """Linear fade in growth rate from g0 (year 1) to g_term (year n)."""
    if n <= 0:
        return []
    out: list[float] = []
    cur = float(rev0)
    for t in range(1, n + 1):
        # Linear fade — for a smoother curve consider exponential
        frac = (t - 1) / max(n - 1, 1)
        g_t = g0 * (1.0 - frac) + g_term * frac
        cur = cur * (1.0 + g_t)
        out.append(cur)
    return out


def _margin_path(m_target: float, conv_yr: int, n: int) -> list[float]:
    """Linear ramp from 0 to m_target over conv_yr years, flat after."""
    if n <= 0:
        return []
    out: list[float] = []
    for t in range(1, n + 1):
        if t < conv_yr:
            out.append(m_target * (t / conv_yr))
        else:
            out.append(m_target)
    return out


def _fcff_path(
    revs: list[float], margins: list[float],
    reinvest_rate: float, tax: float,
) -> list[float]:
    """FCFF = EBIT × (1 - tax) - reinvestment.

    Reinvestment is reinvest_rate × ΔRevenue (typical asset-light
    platform proxy)."""
    if not revs or len(revs) != len(margins):
        return []
    out: list[float] = []
    prev_rev: float = 0.0
    for rev, margin in zip(revs, margins):
        ebit = rev * margin
        nopat = ebit * (1.0 - tax)
        delta_rev = max(rev - prev_rev, 0.0)
        reinvest = delta_rev * reinvest_rate
        out.append(nopat - reinvest)
        prev_rev = rev
    return out


def _terminal_value(
    fcff_n: float, g_term: float, wacc: float,
) -> Optional[float]:
    """Gordon constant-growth. Refuses if wacc - g < 0.03 (model
    breaks down at near-zero denominator)."""
    if wacc - g_term < 0.03:
        return None
    if fcff_n <= 0:
        return None
    return float(fcff_n * (1.0 + g_term) / (wacc - g_term))


def _discount(cashflows: list[float], tv: float, wacc: float) -> float:
    """PV of explicit FCFFs + TV at year n."""
    pv = 0.0
    for t, cf in enumerate(cashflows, start=1):
        pv += cf / ((1.0 + wacc) ** t)
    if tv:
        pv += tv / ((1.0 + wacc) ** len(cashflows))
    return pv


# ── Public entry point ──────────────────────────────────────────
def compute_story_dcf_fair_value(
    ticker: str,
    sector: Optional[str],
    financials: dict,
    story_params: Optional[StoryParams] = None,
) -> Optional[dict]:
    """Compute story-DCF fair value for a platform/fintech ticker.

    Returns the standard valuation-engine dict shape, or None if
    inputs / sector don't support story-DCF.
    """
    # Sector → industry key
    sec_norm = (sector or "").strip().lower()
    industry_key = _SECTOR_TO_INDUSTRY_KEY.get(sec_norm)
    if industry_key is None:
        return None

    # Params — explicit override > per-ticker > industry default
    params = story_params or _params_for(ticker, industry_key)
    if params is None:
        return None

    # Inputs
    try:
        rev0 = float(financials.get("revenue") or financials.get("latest_revenue") or 0)
        shares = float(financials.get("shares") or 0)
        price = float(financials.get("current_price") or 0)
        net_debt = float(financials.get("net_debt") or 0)
    except (TypeError, ValueError):
        return None

    if rev0 <= 0 or shares <= 0 or price <= 0:
        return None

    # Build cashflow path
    revs = _revenue_path(
        rev0=rev0,
        g0=params.initial_growth,
        g_term=params.terminal_growth,
        n=params.fade_years,
    )
    margins = _margin_path(
        m_target=params.target_op_margin,
        conv_yr=params.margin_convergence_yr,
        n=params.fade_years,
    )
    fcffs = _fcff_path(
        revs=revs, margins=margins,
        reinvest_rate=params.reinvestment_rate,
        tax=params.tax_rate,
    )
    if not fcffs:
        return None

    tv = _terminal_value(
        fcff_n=fcffs[-1],
        g_term=params.terminal_growth,
        wacc=params.wacc,
    )
    if tv is None:
        return None

    enterprise_value = _discount(fcffs, tv, params.wacc)
    if enterprise_value <= 0:
        return None

    equity_value = enterprise_value - net_debt
    base_fv = equity_value / shares
    if base_fv <= 0:
        return None

    base_fv = round(base_fv, 2)
    bear = round(base_fv * 0.70, 2)   # wider band than peer-relative
    bull = round(base_fv * 1.45, 2)

    mos_pct = ((base_fv - price) / price * 100.0) if price > 0 else 0.0
    buffett_mos = (
        ((base_fv - price) / base_fv * 100.0) if base_fv > 0 else None
    )

    # Confidence: floor + bump if revenue base is large (more
    # auditable), capped per StoryParams.
    conf = params.confidence_floor + min(
        15, max(0, int((rev0 / 1e10)))  # +1 per ₹1B revenue, max +15
    )
    conf = min(params.confidence_cap, conf)

    # PV-of-TV / enterprise_value — high values mean the model is
    # mostly story (terminal); lower values mean the explicit forecast
    # carries more of the FV. Useful for the frontend "story" badge.
    tv_pv = tv / ((1.0 + params.wacc) ** params.fade_years)
    tv_pct_of_ev = tv_pv / enterprise_value if enterprise_value > 0 else 0.0

    return {
        "fair_value": base_fv,
        "margin_of_safety": round(mos_pct, 1),
        "buffett_mos_pct": (
            round(buffett_mos, 1) if buffett_mos is not None else None
        ),
        "verdict": _verdict_from_mos(mos_pct),
        "bear_case": bear,
        "base_case": base_fv,
        "bull_case": bull,
        "method": "story_dcf",
        "valuation_method": "story_dcf",
        "confidence_score": conf,
        "_meta": {
            "industry": industry_key,
            "initial_growth": params.initial_growth,
            "terminal_growth": params.terminal_growth,
            "target_op_margin": params.target_op_margin,
            "margin_convergence_yr": params.margin_convergence_yr,
            "reinvestment_rate": params.reinvestment_rate,
            "wacc": params.wacc,
            "tax_rate": params.tax_rate,
            "fade_years": params.fade_years,
            "revenue_year1": round(revs[0], 2) if revs else None,
            "revenue_year_n": round(revs[-1], 2) if revs else None,
            "fcff_year_n": round(fcffs[-1], 2) if fcffs else None,
            "terminal_value": round(tv, 2),
            "enterprise_value": round(enterprise_value, 2),
            "equity_value": round(equity_value, 2),
            "tv_pct_of_ev": round(tv_pct_of_ev, 3),
        },
    }


def _verdict_from_mos(mos_pct: float) -> str:
    if mos_pct > 25:
        return "undervalued"
    if mos_pct > -25:
        return "fairly_valued"
    return "overvalued"


__all__ = [
    "compute_story_dcf_fair_value",
    "StoryParams",
    "INDUSTRY_STORY_DEFAULTS",
]
