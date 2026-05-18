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
# Verdict-intensity gate (PR 2 — Step 3 of the audit)
# ───────────────────────────────────────────────────────────────────
# Per the audit's Step 3: "Verdict intensity should scale WITH
# confidence. High confidence + 30% undervalued -> 'Notably
# undervalued'. Low confidence + 30% undervalued -> 'Under Review'."
#
# The gate operates on the three scores produced by the functions
# above and the original verdict (already set by the upstream DCF /
# PB / peer-cap / IPO logic). It can only narrow / suppress the
# verdict — it never amplifies. Verdicts that are already
# data_limited / unavailable / under_review pass through unchanged.

_INTENSITY_VERDICTS: frozenset[str] = frozenset({"undervalued", "overvalued"})
_PASSTHROUGH_VERDICTS: frozenset[str] = frozenset({
    "data_limited", "unavailable", "under_review", "avoid",
})


def _any_below(threshold: int, *vals: Optional[int]) -> bool:
    return any(isinstance(v, int) and v < threshold for v in vals)


def apply_confidence_verdict_gate(
    verdict: str,
    data_quality: Optional[int],
    model_confidence: Optional[int],
    valuation_stability: Optional[int],
    data_issues: Optional[list[str]] = None,
) -> tuple[str, list[str]]:
    """Gate verdict intensity by the three confidence scores.

    Logic table (matches the audit's Step 3 spec exactly):

      | data_quality | model_confidence | valuation_stability | Result                       |
      | >=80         | >=80             | >=80                | unchanged                    |
      | >=70         | >=70             | >=70                | unchanged                    |
      | <70 any      | any              | any                 | cap intensity                |
      |              |                  |                     |  (under/overvalued ->        |
      |              |                  |                     |   fairly_valued)             |
      | <50 any      | <50              | <50                 | force `under_review`         |

    Returns ``(new_verdict, new_data_issues)``. ``data_issues`` is
    extended with a human-readable note explaining why the gate
    fired so the UI can render a caveat.

    Pass-through verdicts (``data_limited``, ``unavailable``,
    ``under_review``, ``avoid``) are never modified. Non-intensity
    verdicts (``fairly_valued``) are likewise never escalated; the
    gate can only narrow, never amplify. The lone exception is the
    "force under_review" branch (triple-low confidence), which is
    the audit's explicit policy.
    """
    issues = list(data_issues or [])
    if not isinstance(verdict, str) or verdict in _PASSTHROUGH_VERDICTS:
        return verdict, issues

    # Tier 3 — triple-low confidence: force under_review regardless
    # of MoS or verdict. Catches the audit's worst case:
    # "Low confidence + 30% undervalued -> Under Review".
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

    # Tier 2 — any score below 70: cap intensity verdicts down to
    # fairly_valued. fairly_valued / avoid pass through unchanged.
    if _any_below(70, data_quality, model_confidence, valuation_stability):
        if verdict in _INTENSITY_VERDICTS:
            issues.append(
                "[confidence_gate] Confidence below threshold "
                f"(dq={data_quality}, mc={model_confidence}, "
                f"vs={valuation_stability}) - '{verdict}' verdict "
                "capped to 'fairly_valued'."
            )
            return "fairly_valued", issues
        return verdict, issues

    # Tier 1 — all scores >= 70: original verdict unchanged.
    return verdict, issues
