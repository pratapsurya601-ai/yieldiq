"""Layer C — Confidence Framework (PR 1: scoring infrastructure).

Per the competitive audit Step 6, every ticker should expose three
0-100 scores so the UI and internal gating systems can reason about
how much trust to put in the headline valuation:

    data_quality_score        — How complete / fresh / scale-clean is
                                the underlying financial data?
    model_confidence_score    — How well does our valuation engine fit
                                this kind of business (large-cap DCF
                                vs recent IPO vs cyclical fallback)?
    valuation_stability_score — How stable is the FV time-series over
                                the last few weeks? Whippy FVs warn
                                the user the model is over-reacting.

PR 1 ships the pure scoring functions + wires them into
``ValuationOutput`` as additive optional fields. The verdict
intensity gate (Step 3 of the audit) lands in PR 2 and reads these
fields back out — no behavior change yet.

All three functions are deliberately defensive: every input is
``Optional``; bad / missing data degrades the score rather than
raising. They never make network calls and never mutate inputs.
"""

from __future__ import annotations

import datetime as _dt
import logging
import random as _random
from typing import Any, Iterable, Mapping, Optional

_log = logging.getLogger("yieldiq.confidence")


# ───────────────────────────────────────────────────────────────────
# Tier-1 curated set — well-covered large-caps where we trust the
# valuation engine almost unconditionally. Membership starts the
# model_confidence_score at 90; everything else starts at 70 and
# accrues deductions from there.
# Bare NSE symbols (no .NS suffix). Keep this list tight — these are
# stocks where the DCF / PB-residual engines have been hand-validated
# against analyst consensus multiple times.
# ───────────────────────────────────────────────────────────────────
TIER1_TICKERS: frozenset[str] = frozenset({
    "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM",
    "RELIANCE", "HDFCBANK", "ICICIBANK", "KOTAKBANK", "SBIN",
    "HINDUNILVR", "ITC", "NESTLEIND", "ASIANPAINT", "TITAN",
    "LT", "BAJAJFINSV", "BAJFINANCE",
    "SUNPHARMA", "DRREDDY", "CIPLA",
    "MARUTI", "M&M", "TATAMOTORS",
    "ULTRACEMCO", "JSWSTEEL", "TATASTEEL",
    "POWERGRID", "NTPC", "ONGC",
})


# Sectors / valuation methods where we systematically have less
# conviction. Each tag deducts from model_confidence_score.
_LOW_CONFIDENCE_METHODS: frozenset[str] = frozenset({
    "sector_relative_recent_ipo",   # IPO routing (< 36 months listed)
    "peer_capped",                  # DCF over-shot, capped to peer multiple
    "holding_company_sotp_required",
    "rate_base",                    # regulated utility — different model
    "etf_nav_based",
    "reit_nav_dpu_required",
})

# Sectors known to be cyclical — drag down model_confidence and
# valuation_stability (the latter is data-driven but cyclicals warrant
# a floor cap because their FVs swing with the commodity cycle).
_CYCLICAL_SECTORS: frozenset[str] = frozenset({
    "capital goods", "metals", "metals & mining", "mining",
    "auto", "automobile", "automobiles",
    "oil & gas", "oil and gas", "energy",
    "realty", "real estate", "construction",
    "shipping", "airlines",
})


# Sectors that route through residual-income / P-B / Appraisal-Value
# engines instead of FCF DCF. The sensitivity score (T2.7) is a
# DCF-input-perturbation exercise — banks/NBFCs/insurance/AMCs have
# a different mathematical shape, so perturbing WACC/FCF/TG/tax has
# no meaningful interpretation for them. Mirrors the lowercase posture
# of `composite_iv_service._is_bank()` from PR #786 branch.
_BANK_LIKE_SECTORS: frozenset[str] = frozenset({
    "banking", "banks", "nbfc", "insurance", "financial services",
})


def _bare_ticker(ticker: str) -> str:
    return (ticker or "").upper().replace(".NS", "").replace(".BO", "").strip()


def _clamp(score: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(score)))


# ───────────────────────────────────────────────────────────────────
# 1. data_quality_score
# ───────────────────────────────────────────────────────────────────
def compute_data_quality_score(
    enriched: Optional[Mapping[str, Any]],
    raw: Optional[Mapping[str, Any]] = None,
) -> int:
    """Score the underlying financial data on a 0-100 scale.

    Heuristics (each missing/stale signal deducts; floors at 0):
      - latest_period_end within last 12 months: -15 if older / -30 if
        absent.
      - >= 3 annual rows: -15 if fewer.
      - >= 4 quarterly rows: -10 if fewer.
      - currency tagged (INR/USD/etc.) and not "unknown": -10.
      - Any explicit ``data_issues`` from validators: -5 each (cap -25).
      - Scale-corrupt flag (``scale_warning`` / ``unit_mismatch``): -20.
      - Missing current price: -10.
      - Missing shares outstanding: -10.

    Starts at 100. Designed so that a clean Tier-1 large-cap lands
    > 85 and a sparse newly-listed micro-cap lands < 50.
    """
    if not isinstance(enriched, Mapping):
        return 0

    score = 100

    # 1. Latest filing freshness
    lpe = (
        enriched.get("latest_period_end")
        or enriched.get("latest_filing_period_end")
        or (raw or {}).get("latest_period_end")
    )
    if not lpe:
        score -= 30
    else:
        try:
            if isinstance(lpe, str):
                lpe_d = _dt.date.fromisoformat(lpe[:10])
            elif isinstance(lpe, _dt.date):
                lpe_d = lpe
            else:
                lpe_d = None
            if lpe_d is not None:
                age_days = (_dt.date.today() - lpe_d).days
                if age_days > 365:
                    score -= 15
                elif age_days > 540:
                    score -= 25
        except Exception:
            score -= 10

    # 2. Annual coverage
    annual = enriched.get("annual_rows")
    if annual is None and isinstance(raw, Mapping):
        annual = raw.get("annual_rows")
    try:
        if annual is None or int(annual) < 3:
            score -= 15
    except Exception:
        score -= 15

    # 3. Quarterly coverage
    quarterly = enriched.get("quarterly_rows")
    if quarterly is None and isinstance(raw, Mapping):
        quarterly = raw.get("quarterly_rows")
    try:
        if quarterly is None or int(quarterly) < 4:
            score -= 10
    except Exception:
        score -= 10

    # 4. Currency tagged sensibly
    currency = (
        enriched.get("currency")
        or (raw or {}).get("currency")
        or (raw or {}).get("financialCurrency")
        or ""
    )
    if not currency or str(currency).strip().lower() in ("", "unknown", "n/a"):
        score -= 10

    # 5. Validator-surfaced issues
    issues = enriched.get("data_issues") or (raw or {}).get("data_issues") or []
    if isinstance(issues, Iterable) and not isinstance(issues, (str, bytes)):
        n = sum(1 for _ in issues)
        score -= min(25, 5 * n)

    # 6. Scale-corrupt rows
    if enriched.get("scale_warning") or enriched.get("unit_mismatch"):
        score -= 20

    # 7. Current price + shares
    price = (
        enriched.get("current_price")
        or (raw or {}).get("currentPrice")
        or (raw or {}).get("regularMarketPrice")
    )
    if not price:
        score -= 10
    shares = (
        enriched.get("shares_outstanding")
        or enriched.get("shares_outstanding_raw")
        or (raw or {}).get("sharesOutstanding")
    )
    if not shares:
        score -= 10

    return _clamp(score)


# ───────────────────────────────────────────────────────────────────
# 2. model_confidence_score
# ───────────────────────────────────────────────────────────────────
def compute_model_confidence_score(
    ticker: str,
    valuation_method: Optional[str] = None,
    sector: Optional[str] = None,
    is_recent_ipo: bool = False,
    extra_flags: Optional[Mapping[str, bool]] = None,
) -> int:
    """How well does our engine fit this kind of business?

    Tier-1 curated large-caps start at 90; all others start at 70.
    Deductions:
      - Recent IPO (< 36 months listed):              -25
      - Valuation method in _LOW_CONFIDENCE_METHODS:  -20
      - Cyclical sector (capital goods / metals / etc): -10
      - ``analyst_opinion_required`` flag (defense PSU): -15
      - ``data_limited`` flag:                         -15
      - ``dcf_unreliable`` flag:                       -10

    Floor at 0; ceiling at 100. A Tier-1 stable IT giant (TCS) lands
    at 90; MANKIND pre-routing (recent IPO + non-tier-1) lands at
    70 - 25 = 45. SIEMENS (capital-goods cyclical, non-tier-1):
    70 - 10 = 60.
    """
    bare = _bare_ticker(ticker)
    base = 90 if bare in TIER1_TICKERS else 70
    score = base

    method = (valuation_method or "").strip()
    if method in _LOW_CONFIDENCE_METHODS:
        score -= 20

    if is_recent_ipo:
        score -= 25

    if sector:
        if str(sector).strip().lower() in _CYCLICAL_SECTORS:
            score -= 10

    flags = dict(extra_flags or {})
    if flags.get("analyst_opinion_required"):
        score -= 15
    if flags.get("data_limited"):
        score -= 15
    if flags.get("dcf_unreliable"):
        score -= 10

    return _clamp(score)


# ───────────────────────────────────────────────────────────────────
# 3. valuation_stability_score
# ───────────────────────────────────────────────────────────────────
def compute_valuation_stability_score(
    ticker: str,
    fv_history: Optional[Iterable[float]] = None,
    sector: Optional[str] = None,
) -> int:
    """Score the stability of the fair-value time series.

    ``fv_history`` is an iterable of recent FV values (most recent
    last). Typical input: last 4 weekly FVs from FvHistoryService.

    Algorithm:
      - With < 2 points we have no signal — return 70 (neutral-ish).
      - Compute coefficient of variation (CV = stdev / |mean|) over
        the window.
      - Map: CV ≤ 5%  → 100, 5-10% → 85, 10-20% → 65,
             20-35% → 45, > 35% → 25.
      - Cyclical-sector floor cap: if a cyclical sector lands above
        70, clamp to 70 (their FVs ARE supposed to swing — don't
        present a falsely calm signal to the user).
    """
    pts: list[float] = []
    if fv_history:
        for v in fv_history:
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f > 0:
                pts.append(f)

    if len(pts) < 2:
        return 70

    mean = sum(pts) / len(pts)
    if mean <= 0:
        return 50
    var = sum((p - mean) ** 2 for p in pts) / len(pts)
    stdev = var ** 0.5
    cv = stdev / abs(mean)

    if cv <= 0.05:
        score = 100
    elif cv <= 0.10:
        score = 85
    elif cv <= 0.20:
        score = 65
    elif cv <= 0.35:
        score = 45
    else:
        score = 25

    # Cyclical floor cap — don't over-promise stability for inherently
    # cyclical businesses even if the recent window happens to be calm.
    if sector and str(sector).strip().lower() in _CYCLICAL_SECTORS:
        score = min(score, 70)

    return _clamp(score)


# ───────────────────────────────────────────────────────────────────
# 4. sensitivity_score (T2.7, 2026-06-09)
# ───────────────────────────────────────────────────────────────────
# Independent 4th confidence pillar. Quantifies verdict stability
# under plausible DCF-input perturbations (Monte Carlo over WACC /
# FCF growth / terminal growth / tax rate). High score = the
# verdict survives reasonable input noise. Low score = the verdict
# sits on a knife-edge (e.g. MoS is just barely above the
# undervalued threshold) and a 50bp WACC bump flips it.
#
# Returns None (not 0) for shapes where the score is structurally
# meaningless:
#   - HOLDING_COMPANIES — SOTP-shaped, no single DCF to perturb.
#     The proper sensitivity exercise here is per-subsidiary
#     stake-value perturbation (deferred to T1.4).
#   - banks / NBFCs / insurance — residual-income / P-B / Appraisal-
#     Value engines; perturbing FCF/WACC has no interpretation.
#   - Missing base_inputs or base_verdict — no signal to compute on.
#
# The 4 perturbation magnitudes (WACC ±50bp, FCF growth ±2pp,
# terminal growth ±50bp, tax ±2pp) bracket realistic year-over-year
# drift in the underlying drivers. Wider bands would make every
# verdict look unstable; tighter would make even bad fits look firm.
#
# The FV recomputation is a deliberate LINEAR approximation rather
# than re-running the full DCF engine. Rationale: (a) the goal is
# verdict stability under perturbation, not high-fidelity revaluation;
# (b) calling back into service.py's DCF would create an import cycle
# and add seconds to the hot path; (c) the response surface is locally
# linear within the perturbation bands we use.
# ───────────────────────────────────────────────────────────────────
def compute_sensitivity_score(
    ticker: str,
    base_inputs: Optional[Mapping[str, Any]] = None,
    base_verdict: Optional[str] = None,
    sector: Optional[str] = None,
    seed: Optional[int] = None,
    n_runs: int = 200,
) -> Optional[int]:
    """Monte Carlo verdict-stability score (0-100) or None.

    ``base_inputs`` must contain (at minimum) numeric values for
    ``wacc`` (decimal, e.g. 0.115), ``fcf_growth`` (decimal),
    ``terminal_growth`` (decimal), ``tax_rate`` (decimal),
    ``current_fv`` (the DCF fair value at base inputs), and
    ``current_price``. Any missing/invalid input → return None.

    Returns:
        int in [0, 100] = % of perturbed runs preserving the verdict.
        None if the score is structurally meaningless for this shape
        (holdco, bank-like sector, missing inputs/verdict).
    """
    bare = _bare_ticker(ticker)

    # Holdco precedence — SOTP-shaped, sensitivity is meaningless
    # until per-subsidiary perturbation lands in T1.4. Imported
    # lazily to avoid a top-of-module cycle with analysis.constants.
    try:
        from backend.services.analysis.constants import HOLDING_COMPANIES
        if bare in HOLDING_COMPANIES:
            return None
    except Exception:  # pragma: no cover — defensive
        _log.exception("[%s] holdco lookup failed in sensitivity", ticker)

    # Bank-like engines (residual-income / P-B / Appraisal-Value)
    # have a different mathematical shape; perturbing FCF/WACC has
    # no interpretation. The sensitivity exercise for banks is a
    # separate task (perturbing ROE assumption + dividend payout).
    if sector and str(sector).strip().lower() in _BANK_LIKE_SECTORS:
        return None

    if not isinstance(base_inputs, Mapping) or not isinstance(base_verdict, str):
        return None
    if not base_verdict:
        return None

    # Pull the 6 required scalars; bail to None on any malformed input.
    try:
        wacc = float(base_inputs.get("wacc"))
        fcf_growth = float(base_inputs.get("fcf_growth"))
        terminal_growth = float(base_inputs.get("terminal_growth"))
        tax_rate = float(base_inputs.get("tax_rate"))
        base_fv = float(base_inputs.get("current_fv"))
        price = float(base_inputs.get("current_price"))
    except (TypeError, ValueError):
        return None
    if base_fv <= 0 or price <= 0:
        return None

    # Seeded RNG — deterministic per ticker so repeated reads emit
    # the same score (cache-friendly). Per-instance Random, never
    # touches module-level random.
    seed_value = seed if seed is not None else (hash(bare) & 0xFFFFFFFF)
    rng = _random.Random(seed_value)

    # Verdict thresholds — must match the MoS bands used elsewhere
    # in this module (see Layer-3 cap + bull/bear bypass).
    def _verdict_from_mos(m: float) -> str:
        if m >= 0.40:
            return "notably_undervalued"
        if m >= 0.10:
            return "undervalued"
        if m <= -0.40:
            return "notably_overvalued"
        if m <= -0.10:
            return "overvalued"
        return "fairly_valued"

    n = max(1, int(n_runs))
    agree = 0
    for _ in range(n):
        wacc_delta = rng.uniform(-0.005, 0.005)
        fcf_delta = rng.uniform(-0.02, 0.02)
        tg_delta = rng.uniform(-0.005, 0.005)
        tax_delta = rng.uniform(-0.02, 0.02)
        # Clamp tax to [0, 0.40] — caller passes a decimal.
        new_tax = max(0.0, min(0.40, tax_rate + tax_delta))
        effective_tax_delta = new_tax - tax_rate

        # Linear sensitivity approximation around the base FV.
        # Coefficient on tax (0.3) reflects the partial offset
        # between corporate-tax changes and reinvestment / interest
        # shield in a stylized FCFF model.
        perturbed_fv = base_fv * (
            1.0
            + fcf_delta
            + tg_delta
            - wacc_delta
            - effective_tax_delta * 0.3
        )
        if perturbed_fv <= 0:
            # A perturbation that flips FV negative implies a
            # different verdict (unavailable / under_review shape);
            # count as disagreement.
            continue

        perturbed_mos = (perturbed_fv - price) / price
        if _verdict_from_mos(perturbed_mos) == base_verdict:
            agree += 1
        # Suppress unused-var lint for wacc/fcf_growth/terminal_growth
        # — they're inputs to the perturbation, not the linearization
        # itself. Keep them in the signature so callers can pass the
        # full base-input dict without filtering.
        _ = (wacc, fcf_growth, terminal_growth)

    score = int(round(100.0 * agree / n))
    return _clamp(score)


# ───────────────────────────────────────────────────────────────────
# 5. composite_agreement_score (T1.6, 2026-06-10)
# ───────────────────────────────────────────────────────────────────
# Independent 5th confidence pillar. Quantifies how tightly the
# constituent estimators of the composite intrinsic value cluster.
# High score = estimators agree = high trust in the composite.
# Low score = wide spread = composite is averaging noise.
#
# Read from the ``composite_components`` dict emitted by
# ``composite_iv_service.composite_to_dict`` (T1.1, PR #777). Each
# component is ``{"value": <per-share IV>, "weight": <renorm wt>}``;
# this pillar consumes the values only — weights are the composite's
# concern, not the agreement measure's.
#
# Returns ``None`` (not 0) when fewer than 2 components exist — a
# single-estimator path (pure holdco DCF-only, bank residual-income
# without multiples) carries no agreement signal by construction.
# Same defensive posture as ``compute_sensitivity_score``.
#
# Algorithm: coefficient of variation (CV = stdev / mean) over the
# per-component values, then a 5-bucket map to a 0-100 score. CV is
# scale-free, so the same threshold map works for a ₹15 small-cap
# and a ₹1.5L large-cap. The thresholds match the verbal description
# in the T1.6 brief (5/15/30/50% spread bands).
# ───────────────────────────────────────────────────────────────────
def compute_composite_agreement_score(
    composite_components: Optional[Mapping[str, Any]],
) -> Optional[int]:
    """5th pillar — agreement among composite IV constituent estimators.

    ``composite_components`` shape (from
    ``composite_iv_service.composite_to_dict``):

        {
            "value": float | None,
            "components": {
                "dcf":       {"value": 1129.28, "weight": 0.50},
                "multiples": {"value": 872.33,  "weight": 0.30},
                "analyst":   {"value": 803.00,  "weight": 0.20},
            },
            "method": "composite_dcf_multiples_analyst",
            "extreme_divergence": False,
        }

    Returns:
        int in [0, 100] — high = estimators cluster tightly.
        None — fewer than 2 components, malformed input, or values
        that resolve to a non-positive mean (no agreement signal).

    Score map (CV = stdev / mean over component values):
        CV <= 0.05 -> 100   (tight cluster, ~within 5% of each other)
        CV <= 0.15 ->  80   (modest spread, ~within 15%)
        CV <= 0.30 ->  60   (HDFCBANK-shape, ~within 30%)
        CV <= 0.50 ->  40   (wide spread)
        CV  > 0.50 ->  20   (extreme_divergence territory)
    """
    if not isinstance(composite_components, Mapping):
        return None

    comps = composite_components.get("components")
    if not isinstance(comps, Mapping) or not comps:
        return None

    # Extract per-component values; ignore entries without a numeric
    # positive value. The composite_iv_service guarantees positive
    # values for any active component, but be defensive against
    # legacy / malformed cached payloads.
    values: list[float] = []
    for comp in comps.values():
        if not isinstance(comp, Mapping):
            continue
        v = comp.get("value")
        try:
            vf = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            continue
        if vf > 0:
            values.append(vf)

    if len(values) < 2:
        return None

    mean = sum(values) / len(values)
    if mean <= 0:  # pragma: no cover — defensive (all-positive guard above)
        return None
    var = sum((x - mean) ** 2 for x in values) / len(values)
    stdev = var ** 0.5
    cv = stdev / abs(mean)

    if cv <= 0.05:
        score = 100
    elif cv <= 0.15:
        score = 80
    elif cv <= 0.30:
        score = 60
    elif cv <= 0.50:
        score = 40
    else:
        score = 20

    return _clamp(score)


# ───────────────────────────────────────────────────────────────────
# Convenience: compute all five at once.
# ───────────────────────────────────────────────────────────────────
def compute_all_scores(
    ticker: str,
    enriched: Optional[Mapping[str, Any]] = None,
    raw: Optional[Mapping[str, Any]] = None,
    valuation_method: Optional[str] = None,
    sector: Optional[str] = None,
    is_recent_ipo: bool = False,
    fv_history: Optional[Iterable[float]] = None,
    extra_flags: Optional[Mapping[str, bool]] = None,
    base_inputs: Optional[Mapping[str, Any]] = None,
    base_verdict: Optional[str] = None,
    composite_components: Optional[Mapping[str, Any]] = None,
) -> dict[str, Optional[int]]:
    """Compute all five confidence scores in one call.

    Returns a dict with keys ``data_quality``, ``model_confidence``,
    ``valuation_stability``, ``sensitivity``, ``composite_agreement``.
    Never raises; defensive against every input being ``None``.

    T2.7 (2026-06-09) added the 4th key ``sensitivity`` as an
    additive pillar. It is ``None`` for holdcos, banks, and any call
    where ``base_inputs`` / ``base_verdict`` are missing.

    T1.6 (2026-06-10) added the 5th key ``composite_agreement``.
    Measures how tightly the composite IV constituent estimators
    cluster. ``None`` when fewer than 2 estimators are in the
    composite (single-estimator paths, malformed input). The
    existing four pillars are byte-identical to T2.7.
    """
    try:
        dq = compute_data_quality_score(enriched, raw)
    except Exception:  # pragma: no cover — defensive
        _log.exception("[%s] data_quality_score failed", ticker)
        dq = 0
    try:
        mc = compute_model_confidence_score(
            ticker,
            valuation_method=valuation_method,
            sector=sector,
            is_recent_ipo=is_recent_ipo,
            extra_flags=extra_flags,
        )
    except Exception:  # pragma: no cover
        _log.exception("[%s] model_confidence_score failed", ticker)
        mc = 0
    try:
        vs = compute_valuation_stability_score(
            ticker, fv_history=fv_history, sector=sector
        )
    except Exception:  # pragma: no cover
        _log.exception("[%s] valuation_stability_score failed", ticker)
        vs = 0
    try:
        sens = compute_sensitivity_score(
            ticker,
            base_inputs=base_inputs,
            base_verdict=base_verdict,
            sector=sector,
        )
    except Exception:  # pragma: no cover
        _log.exception("[%s] sensitivity_score failed", ticker)
        sens = None
    try:
        agree = compute_composite_agreement_score(composite_components)
    except Exception:  # pragma: no cover
        _log.exception("[%s] composite_agreement_score failed", ticker)
        agree = None
    return {
        "data_quality": dq,
        "model_confidence": mc,
        "valuation_stability": vs,
        "sensitivity": sens,
        "composite_agreement": agree,
    }


# ───────────────────────────────────────────────────────────────────
# Verdict-intensity gate (PR #342 — Layer C Step 3)
# ───────────────────────────────────────────────────────────────────
# Per the competitive audit: "Verdict intensity should scale WITH
# confidence." Reads the three scores above and may narrow (never
# amplify) the verdict.
#
# Extended 2026-05-19 with an extreme-FV/price-ratio override: if
# the model's FV is more than 5× off the market price in either
# direction AND model_confidence OR data_quality is below 70, force
# `under_review` regardless of the intensity-cap logic below. This
# catches the post-Layer-C residual outlier class (INDIACEM FV=0.77
# at CMP=405, PAYTM FV=41 at CMP=1400, TMPV FV=1904 at CMP=370)
# where the ratio screams data-quality problem but confidence sits
# just above the triple-low floor.

_INTENSITY_VERDICTS: frozenset[str] = frozenset({
    "undervalued",
    "overvalued",
    "notably_undervalued",
    "notably_overvalued",
})
_PASSTHROUGH_VERDICTS: frozenset[str] = frozenset({
    "data_limited", "unavailable", "under_review", "avoid",
})

# Valuation models where wide FV/price ratios are legitimate (the
# engine is intentionally different math, not a data-quality issue):
#   rate_base                       — regulated utilities, RAB×ROE
#   appraisal_value                 — insurance EV+VNB
#   reit_nav_dpu_required           — REIT/InvIT NAV skip-path
#   holding_company_sotp_required   — holdcos, SOTP not single FV
#   etf_nav_based                   — ETFs, NAV not DCF
_RATIO_OVERRIDE_CARVEOUTS: frozenset[str] = frozenset({
    "rate_base",
    "appraisal_value",
    "reit_nav_dpu_required",
    "holding_company_sotp_required",
    "etf_nav_based",
})

# Extreme-ratio thresholds (FV / price). Symmetric on log scale —
# 5× off in either direction. INDIACEM (0.77/405 = 0.0019) and
# TMPV (1904/370 = 5.15) both cross.
_RATIO_LOW = 0.2
_RATIO_HIGH = 5.0
# Confidence floor below which an extreme ratio forces under_review.
_RATIO_OVERRIDE_CONF_FLOOR = 70

# ── Audit#6 (2026-05-22): bear-side overvalued bypass ─────────────
# Mirror of the frontend PR #499 / Day-94 rule in
# `frontend/src/lib/utils.ts::shouldGateVerdict`. The Layer-3
# intensity cap below collapses `overvalued` / `notably_overvalued`
# down to `fairly_valued` whenever ANY of the three confidence
# scores sits below 70. That symmetric cap is correct on the BULL
# side (a moderately-confident "notably_undervalued" can mislead a
# reader into acting on a noisy deep-value signal). It is wrong on
# the BEAR side: SUNPHARMA (mos -33%), MARUTI (-31%), SBIN (-31%),
# ASIANPAINT (-47%) all surfaced `fairly_valued` on the public API
# at 50-65% model_confidence despite the model clearly flagging a
# premium to fair value. Flattening an overvalued read into
# `fairly_valued` is materially more harmful than flattening an
# undervalued read — the first reads as a green light to a name
# that the model thinks is rich, the second merely declines to
# surface a value idea. Frontend PR #499 added the asymmetric
# bypass at the UI layer; this constant + bypass mirrors it into
# the backend so /api/v1/public/stock-summary, og-data, push
# notifications, email alerts, and any analytics keying off
# verdict all see the same string.
#
# Rule: when mos_pct <= the threshold AND model_confidence >= 40, do
# NOT apply the Layer-3 cap. Pass-through and Layer-1/Layer-2 (extreme
# ratio override, triple-low under_review) remain unchanged so
# `data_limited` and genuinely low-confidence reads still gate.
# Calibration audit (2026-06-14): lowered -25 -> -15. The Layer-3 cap
# fires on ANY of the three confidence pillars < 70, which was
# flattening genuinely-overvalued names with high HEADLINE model
# confidence into "fairly_valued" — e.g. SBIN -24% and SUNPHARMA -25%
# (90%-confidence reads) surfaced "fairly_valued" because they sat just
# inside the old -25 dead zone. -15 aligns the bypass with the base
# verdict band (overvalued at mos <= -10) so meaningful directional
# reads survive the cap; the model_confidence >= 40 floor still gates
# genuinely low-confidence names.
BEAR_OVERVALUED_BYPASS_MOS: float = -15.0
BEAR_OVERVALUED_BYPASS_CONFIDENCE: int = 40
# Threshold below which a bear-side read deepens to
# `notably_overvalued` instead of plain `overvalued`. Matches the
# frontend `verdictFromMos` boundary so both layers agree.
BEAR_NOTABLY_OVERVALUED_MOS: float = -40.0

# ── Day-111c (2026-05-23): symmetric BULL-side undervalued bypass ─
# Audit-#7 follow-up. The Day-111 top-100 audit surfaced 19 tickers
# (most egregious: LICI at +95.3% MoS) where the Layer-3 confidence
# cap collapsed the engine's "undervalued"/"notably_undervalued" read
# down to "fairly_valued" because ANY of the three confidence scores
# sat below 70. Labeling a name with +95% MoS as "fairly valued" is
# a credibility-breaking bug — at that gap, even moderate model
# confidence is enough to communicate that the engine sees a large
# discount to fair value. The bear-side bypass already mirrors this
# logic on the opposite tail (Audit#6 / PR #503). This block adds
# the symmetric bull-side rule.
#
# Asymmetry note (per spec): the bull-side confidence floor is set
# LOWER than the bear-side floor (30 vs 40). Rationale: being too
# cautious about "this is cheap" merely declines to surface a value
# idea (neutral outcome); being too cautious about "this is
# expensive" reads as a green light to a name the model thinks is
# rich (harmful outcome). The MoS bar is set HIGHER on the bull
# side (50 vs 25) because optimistic FVs are easier to over-fit
# than pessimistic ones — we require a wider gap before bypassing.
#
# The bull bypass ONLY overrides "fairly_valued" → "undervalued" /
# "notably_undervalued" when the inbound verdict was already in the
# bull intensity band. It NEVER overrides data_limited / unavailable
# / under_review / avoid (those need stronger gates than just MoS)
# and Layer-1 (extreme FV/price ratio) and Layer-2 (triple-low
# under_review) still fire first.
# Phase B.2 (2026-05-24): lowered 50 → 40 after HDFCBANK landed at
# MoS=+43.1% with model_confidence=90 but the original 50% threshold
# kept the Layer-3 cap from clearing — verdict surfaced as
# `fairly_valued` to the public stock-summary endpoint despite a
# clear +43% margin of safety and a Wide moat + Piotroski 6 + recent
# Day-109a banking-cohort re-anchor.
# Calibration audit (2026-06-14): lowered 40 → 15. The dead zone
# between the base band (undervalued at mos >= +10) and the old +40
# bypass was flattening clearly-undervalued names with high HEADLINE
# model confidence — e.g. KOTAKBANK +35% at 90% confidence and
# POWERGRID +25% surfaced "fairly_valued" because a sub-pillar (data
# quality / valuation stability) sat < 70 and the +40 bypass missed
# them. +15 aligns the bull bypass with the audited band (undervalued
# at mos >= +15) so meaningful directional reads survive the Layer-3
# cap; the model_confidence >= 30 floor still gates low-confidence reads.
BULL_UNDERVALUED_BYPASS_MOS: float = 15.0
BULL_UNDERVALUED_BYPASS_CONFIDENCE: int = 30
# Threshold above which a bull-side read deepens to
# `notably_undervalued` instead of plain `undervalued`. Higher than
# the frontend `verdictFromMos` 25% boundary because the backend
# only deepens at the extreme tail where the gap is too large for
# even a moderately uncertain model read to plausibly be wrong.
BULL_NOTABLY_UNDERVALUED_MOS: float = 80.0


def _any_below(threshold: int, *vals: Optional[int]) -> bool:
    return any(isinstance(v, int) and v < threshold for v in vals)


def _apply_confidence_verdict_gate(
    verdict: str,
    data_quality: Optional[int],
    model_confidence: Optional[int],
    valuation_stability: Optional[int],
    data_issues: Optional[list[str]] = None,
    *,
    fair_value: Optional[float] = None,
    current_price: Optional[float] = None,
    valuation_model: Optional[str] = None,
) -> tuple[str, list[str]]:
    """Gate verdict intensity by confidence scores + extreme FV ratio.

    Two layers, applied in order:

    1. **Extreme FV/price ratio override (added 2026-05-19).**
       If FV/price < 0.2 or > 5.0 AND (model_confidence < 70 OR
       data_quality < 70), force `under_review`. Skipped for the
       carve-out valuation models in ``_RATIO_OVERRIDE_CARVEOUTS``
       (rate_base utilities, appraisal-value insurance, REIT/holdco/
       ETF skip-paths) where wide ratios are legitimate.

    2. **Confidence intensity cap (original PR #342 logic).**
       Triple-low (all three scores < 50) -> force `under_review`.
       Any score < 70 -> cap intensity verdicts down to
       `fairly_valued`. All >= 70 -> unchanged.

    Pass-through verdicts (`data_limited`, `unavailable`,
    `under_review`, `avoid`) are never modified by either layer.
    Returns ``(new_verdict, new_data_issues)``.
    """
    issues = list(data_issues or [])
    if not isinstance(verdict, str) or verdict in _PASSTHROUGH_VERDICTS:
        return verdict, issues

    # ── Layer 1: extreme FV/price ratio override ─────────────────
    # Fires independently of the intensity-cap logic. Carve-outs
    # for engines where wide ratios are mathematically expected.
    vm = (valuation_model or "").strip()
    if vm not in _RATIO_OVERRIDE_CARVEOUTS:
        try:
            fv_f = float(fair_value) if fair_value is not None else 0.0
            px_f = float(current_price) if current_price is not None else 0.0
        except (TypeError, ValueError):
            fv_f = 0.0
            px_f = 0.0
        if fv_f > 0 and px_f > 0:
            ratio = fv_f / px_f
            extreme = ratio < _RATIO_LOW or ratio > _RATIO_HIGH
            low_conf = (
                (isinstance(model_confidence, int)
                 and model_confidence < _RATIO_OVERRIDE_CONF_FLOOR)
                or (isinstance(data_quality, int)
                    and data_quality < _RATIO_OVERRIDE_CONF_FLOOR)
            )
            if extreme and low_conf:
                issues.append(
                    f"[under_review] FV/price ratio ({ratio:.2f}) is "
                    f"extreme; model confidence "
                    f"{model_confidence if model_confidence is not None else 'n/a'}"
                    f"/100 too low to support a directional verdict. "
                    f"Manual review required."
                )
                return "under_review", issues

    # ── Layer 2: triple-low confidence -> force under_review ─────
    if (
        isinstance(data_quality, int) and data_quality < 50
        and isinstance(model_confidence, int) and model_confidence < 50
        and isinstance(valuation_stability, int) and valuation_stability < 50
    ):
        issues.append(
            "[confidence_gate] All three confidence scores below 50 "
            f"(dq={data_quality}, mc={model_confidence}, "
            f"vs={valuation_stability}) - verdict forced to under_review."
        )
        return "under_review", issues

    # ── Layer 3: any score below 70 -> cap intensity verdicts ────
    if _any_below(70, data_quality, model_confidence, valuation_stability):
        if verdict in _INTENSITY_VERDICTS:
            # Audit#6 bear-side bypass — mirror of frontend PR #499.
            # See module-level BEAR_OVERVALUED_BYPASS_* docstring.
            # Compute MoS from FV/price (the gate already has both
            # for Layer 1) so callers do not have to pass it
            # separately. mos_pct = (fv - price) / price * 100.
            # Day-111c bull-side symmetric bypass — see module-level
            # BULL_UNDERVALUED_BYPASS_* docstring. Same shape as the
            # bear branch below: re-derive mos_pct from FV/price,
            # require mos_pct >= BULL_UNDERVALUED_BYPASS_MOS AND
            # model_confidence >= BULL_UNDERVALUED_BYPASS_CONFIDENCE,
            # clamp output to a valid ValuationOutput.verdict literal
            # ("undervalued") and surface the intensity_hint in
            # issues. Fixes the Day-111 audit's 19 verdict-mismatch
            # tickers (LICI at +95% MoS labeled fairly_valued, etc).
            if verdict in ("undervalued", "notably_undervalued"):
                try:
                    _fv = float(fair_value) if fair_value is not None else 0.0
                    _px = float(current_price) if current_price is not None else 0.0
                except (TypeError, ValueError):
                    _fv = 0.0
                    _px = 0.0
                if _fv > 0 and _px > 0:
                    mos_pct = (_fv - _px) / _px * 100.0
                    if (
                        mos_pct >= BULL_UNDERVALUED_BYPASS_MOS
                        and isinstance(model_confidence, int)
                        and model_confidence >= BULL_UNDERVALUED_BYPASS_CONFIDENCE
                    ):
                        # Clamp to "undervalued" — the only bull
                        # intensity literal allowed by
                        # ValuationOutput.verdict (see Audit#7 P0
                        # comment further down for the bear-side
                        # parallel). The frontend's verdictFromMos
                        # derives the "Notably Undervalued" pill
                        # from mos_pct directly, so the pill still
                        # shows the deeper intensity client-side.
                        bypassed = "undervalued"
                        intensity_hint = (
                            "notably_undervalued"
                            if mos_pct >= BULL_NOTABLY_UNDERVALUED_MOS
                            else "undervalued"
                        )
                        issues.append(
                            "[confidence_gate] Bull-side bypass: "
                            f"mos={mos_pct:.1f}% >= "
                            f"{BULL_UNDERVALUED_BYPASS_MOS}% with "
                            f"mc={model_confidence} >= "
                            f"{BULL_UNDERVALUED_BYPASS_CONFIDENCE}; "
                            f"surfaced as '{bypassed}' "
                            f"(intensity_hint='{intensity_hint}', "
                            "Day-111c symmetric mirror of "
                            "BEAR_OVERVALUED_BYPASS rule)."
                        )
                        return bypassed, issues
            if verdict in ("overvalued", "notably_overvalued"):
                try:
                    _fv = float(fair_value) if fair_value is not None else 0.0
                    _px = float(current_price) if current_price is not None else 0.0
                except (TypeError, ValueError):
                    _fv = 0.0
                    _px = 0.0
                if _fv > 0 and _px > 0:
                    mos_pct = (_fv - _px) / _px * 100.0
                    if (
                        mos_pct <= BEAR_OVERVALUED_BYPASS_MOS
                        and isinstance(model_confidence, int)
                        and model_confidence >= BEAR_OVERVALUED_BYPASS_CONFIDENCE
                    ):
                        # Audit#7 P0 (2026-05-22): the original PR #503
                        # implementation returned "notably_overvalued"
                        # for mos_pct <= -40 (ASIANPAINT at -47.8%).
                        # That string is NOT a member of
                        # ValuationOutput.verdict's Literal[…] in
                        # backend/models/responses.py (which allows only
                        # undervalued|fairly_valued|overvalued|avoid|
                        # data_limited|unavailable), so pydantic raised
                        # ValidationError inside get_full_analysis,
                        # the public stock-summary endpoint caught the
                        # exception in the cache-miss recompute path
                        # (backend/routers/public.py:672), and every
                        # subsequent fetch returned the opaque
                        # "cache_miss_recompute_failed" placeholder.
                        #
                        # SUNPHARMA (-33%), MARUTI (-31%), SBIN (-31%)
                        # were unaffected because they fall ABOVE the
                        # -40% BEAR_NOTABLY_OVERVALUED_MOS threshold
                        # and returned plain "overvalued" (a valid
                        # literal). ASIANPAINT, with the deepest
                        # negative MoS in the universe, was the only
                        # ticker that hit the unmodeled branch.
                        #
                        # The frontend can render "notably_overvalued"
                        # as a distinct pill because
                        # frontend/src/lib/utils.ts::verdictFromMos
                        # derives the label from mos_pct on the
                        # client side. The backend's verdict literal
                        # remains the canonical 6-value set; widening
                        # it would touch validators, og-data, push,
                        # email-alerts, analytics, and the cached
                        # rows for every ticker. Out of scope for a
                        # P0 fix.
                        #
                        # Fix: clamp the bypass output to "overvalued"
                        # (a valid literal) and surface the intensity
                        # in the issues log for analytics. The
                        # frontend pill renderer (verdictFromMos)
                        # is unaffected because it does not consume
                        # this string — it derives its own label from
                        # the mos_pct field, which still resolves to
                        # "notably overvalued" on the client.
                        bypassed = "overvalued"
                        # Defensive: if the engine emits a literal we
                        # cannot return (future drift), log + fall
                        # through to the symmetric cap rather than
                        # wedging the whole recompute. Reason string
                        # is diagnosable instead of opaque.
                        if bypassed not in _INTENSITY_VERDICTS and bypassed != "overvalued":
                            issues.append(
                                "[confidence_gate] verdict_gate_inconsistent: "
                                f"bypass produced '{bypassed}' which is not a "
                                "valid ValuationOutput.verdict literal; "
                                "falling through to symmetric cap."
                            )
                            return "fairly_valued", issues
                        intensity_hint = (
                            "notably_overvalued"
                            if mos_pct <= BEAR_NOTABLY_OVERVALUED_MOS
                            else "overvalued"
                        )
                        issues.append(
                            "[confidence_gate] Bear-side bypass: "
                            f"mos={mos_pct:.1f}% <= "
                            f"{BEAR_OVERVALUED_BYPASS_MOS}% with "
                            f"mc={model_confidence} >= "
                            f"{BEAR_OVERVALUED_BYPASS_CONFIDENCE}; "
                            f"surfaced as '{bypassed}' "
                            f"(intensity_hint='{intensity_hint}', "
                            "Audit#7 P0 clamp — see PR #503 + "
                            "ValuationOutput.verdict literal)."
                        )
                        return bypassed, issues
            issues.append(
                "[confidence_gate] Confidence below threshold "
                f"(dq={data_quality}, mc={model_confidence}, "
                f"vs={valuation_stability}) - '{verdict}' verdict "
                "capped to 'fairly_valued'."
            )
            return "fairly_valued", issues
        return verdict, issues

    return verdict, issues


# Public alias for callers that prefer the non-underscored name.
apply_confidence_verdict_gate = _apply_confidence_verdict_gate
