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
# Convenience: compute all three at once.
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
) -> dict[str, int]:
    """Compute all three confidence scores in one call.

    Returns a dict with keys ``data_quality``, ``model_confidence``,
    ``valuation_stability``. Never raises; defensive against every
    input being ``None`` (would just return three zeros / neutrals).
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
    return {
        "data_quality": dq,
        "model_confidence": mc,
        "valuation_stability": vs,
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
# Rule: when mos_pct <= -25 AND model_confidence >= 40, do NOT
# apply the Layer-3 cap. Pass-through and Layer-1/Layer-2 (extreme
# ratio override, triple-low under_review) remain unchanged so
# `data_limited` and genuinely low-confidence reads still gate.
BEAR_OVERVALUED_BYPASS_MOS: float = -25.0
BEAR_OVERVALUED_BYPASS_CONFIDENCE: int = 40
# Threshold below which a bear-side read deepens to
# `notably_overvalued` instead of plain `overvalued`. Matches the
# frontend `verdictFromMos` boundary so both layers agree.
BEAR_NOTABLY_OVERVALUED_MOS: float = -40.0


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
