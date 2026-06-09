# backend/services/analysis/worry_index.py
"""
The Worry Index — 0-100 emotional risk composite (Phase-3, 2026-05-25).

Manifesto rule 2: every number has context. The Worry Index turns the
dozens of risk signals strewn across the analysis page into a single
0-100 score with plain-English copy. Lower is calmer, higher is louder.

Pure rules + weighted blend — no LLM, no DB lookups, no network. Inputs
are the already-computed ``ValuationOutput`` / ``QualityOutput`` /
``InsightCards`` blocks on the assembled ``AnalysisResponse`` plus an
optional ``peer_context`` dict for valuation-stretch math.

═══════════════════════════════════════════════════════════════
Weighting (must sum to 100)
═══════════════════════════════════════════════════════════════
  Solvency               30  -- D/E, current ratio, interest coverage, Z-proxy
  Earnings quality       25  -- ROE consistency, margin trend, accruals proxy
  Valuation stretch      20  -- distance from FV, PE relative to peer median
  Market signals         15  -- beta / volatility, drawdown from 52w high
  Governance / disclosure 10  -- red-flag count, promoter pledge, audit flags

Each component returns a 0-100 sub-score where higher = MORE worry.

═══════════════════════════════════════════════════════════════
Tiers (must cover 0-100 with no gaps)
═══════════════════════════════════════════════════════════════
   0-20  sleep_well            "Sleep well — this is a defensive blue-chip"
  20-40  normal                "Normal market risk — boring is a feature"
  40-60  watch_closely         "Watch the next earnings closely"
  60-80  read_bears            "Read the bear case carefully"
  80-100 significant_concerns  "Significant concerns flagged — see deep dive"

All tier copy is SEBI-safe by construction (verified in
``test_worry_index``). No directional verbs.

═══════════════════════════════════════════════════════════════
Hard rules
═══════════════════════════════════════════════════════════════
  * Tolerant of missing inputs — components with no signal contribute
    a neutral 50 (mid-tier) so a thinly-covered ticker doesn't collapse
    to 0 ("nothing to worry about") or 100 ("everything is broken").
  * Field-additive on AnalysisResponse — pre-PR clients ignore the
    extra field; no CACHE_VERSION bump.
  * Pure function — same inputs → same outputs, no side effects.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


# ─── Public types ──────────────────────────────────────────────

Tier = Literal[
    "sleep_well",
    "normal",
    "watch_closely",
    "read_bears",
    "significant_concerns",
]


@dataclass
class Contributor:
    component: str          # "solvency" | "earnings_quality" | ...
    label: str              # human label for the UI
    weight: int             # 10 / 15 / 20 / 25 / 30
    score: int              # 0-100, higher = more worry
    detail: str = ""        # one-line "why" sentence (SEBI-safe)


@dataclass
class WorryIndex:
    score: int                       # 0-100 composite
    tier: Tier
    headline: str                    # tier copy, Apple-marketing-clear
    contributors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Tier copy (frozen — verified SEBI-safe in tests) ──────────

_TIER_COPY: dict[Tier, str] = {
    "sleep_well":           "Sleep well — this is a defensive blue-chip",
    "normal":               "Normal market risk — boring is a feature",
    "watch_closely":        "Watch the next earnings closely",
    "read_bears":           "Read the bear case carefully",
    "significant_concerns": "Significant concerns flagged — see deep dive",
}

_TIER_BOUNDARIES: list[tuple[int, Tier]] = [
    (20,  "sleep_well"),
    (40,  "normal"),
    (60,  "watch_closely"),
    (80,  "read_bears"),
    (101, "significant_concerns"),  # 101 because boundary is exclusive
]


def _tier_for(score: int) -> Tier:
    for upper, tier in _TIER_BOUNDARIES:
        if score < upper:
            return tier
    return "significant_concerns"


# ─── Helpers ───────────────────────────────────────────────────


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _lerp_worry(value: float, calm_at: float, worried_at: float) -> float:
    """Map a metric to a 0-100 worry score.

    ``calm_at`` is the value at which worry = 0; ``worried_at`` is the
    value at which worry = 100. Linear in between. Direction is inferred
    from the relative ordering of the two anchors so the same helper
    serves both higher-is-worse and lower-is-worse metrics.
    """
    if calm_at == worried_at:
        return 50.0
    t = (value - calm_at) / (worried_at - calm_at)
    return _clamp(t * 100.0)


# ─── Component scorers ─────────────────────────────────────────


def _score_solvency(quality: Any) -> tuple[int, str]:
    """30% weight. Higher = more worry."""
    de        = _as_float(_get(quality, "de_ratio"))
    cr        = _as_float(_get(quality, "current_ratio"))
    int_cov   = _as_float(_get(quality, "interest_coverage"))
    debt_ebit = _as_float(_get(quality, "debt_ebitda"))
    is_bank   = bool(_get(quality, "is_bank", False))
    is_holdco = bool(_get(quality, "is_holdco", False))

    subs: list[float] = []
    detail_bits: list[str] = []

    # Holdco precedence (2026-06-09) — pure holding companies have
    # near-zero operating revenue, intermittent dividend-receipts CFO,
    # and minimal external debt. Generic D/E + current-ratio +
    # interest-coverage maths produce noise (the holdco has no
    # operations to fund). Bank ROA framing is wrong by construction
    # (no loan book). Surface NAV-cover / holdco-discount as the
    # honest solvency angle. We don't have either metric on
    # QualityOutput today, so we emit a neutral 40 (slightly calm —
    # holdcos are structurally low-risk on solvency since they don't
    # operate) with explanatory copy. Future PR: wire NAV cover from
    # holdco_underlyings.json + live underlying prices.
    if is_holdco:
        return 40, (
            "Solvency drivers: holdco — no loan book, no operating "
            "WC, no meaningful D/E; risk is in NAV cover and "
            "holdco discount to SOTP."
        )
    # Banks: leverage maths differ. Use ROA as a thin proxy and skip
    # the generic ratios so we don't penalise deposit-funded firms.
    if is_bank:
        roa = _as_float(_get(quality, "roa"))
        if roa is not None:
            # ROA: >1.4% calm, <0.4% loud
            subs.append(_lerp_worry(roa, calm_at=1.4, worried_at=0.4))
            detail_bits.append(f"bank ROA {roa:.2f}%")
    else:
        if de is not None:
            # D/E: 0 calm, 2.0+ loud
            subs.append(_lerp_worry(de, calm_at=0.3, worried_at=2.0))
            detail_bits.append(f"D/E {de:.2f}")
        if cr is not None:
            # Current ratio inverted: 2.0 calm, 0.8 loud
            subs.append(_lerp_worry(cr, calm_at=2.0, worried_at=0.8))
            detail_bits.append(f"current ratio {cr:.2f}")
        if int_cov is not None:
            # Interest coverage inverted: 10x calm, 1.5x loud
            subs.append(_lerp_worry(int_cov, calm_at=10.0, worried_at=1.5))
            detail_bits.append(f"int. coverage {int_cov:.1f}x")
        if debt_ebit is not None:
            # Debt/EBITDA: 1x calm, 5x loud
            subs.append(_lerp_worry(debt_ebit, calm_at=1.0, worried_at=5.0))
            detail_bits.append(f"debt/EBITDA {debt_ebit:.2f}x")

    if not subs:
        return 50, "Solvency inputs unavailable."
    avg = int(round(sum(subs) / len(subs)))
    return avg, "Solvency drivers: " + ", ".join(detail_bits) + "."


def _score_earnings_quality(quality: Any, insights: Any) -> tuple[int, str]:
    """25% weight."""
    roe        = _as_float(_get(quality, "roe"))
    net_margin = _as_float(_get(quality, "net_margin"))
    rev_cagr_3 = _as_float(_get(quality, "revenue_cagr_3y"))
    score_raw  = _as_float(_get(quality, "yieldiq_score"))

    subs: list[float] = []
    detail_bits: list[str] = []

    if roe is not None:
        subs.append(_lerp_worry(roe, calm_at=18.0, worried_at=4.0))
        detail_bits.append(f"ROE {roe:.1f}%")
    if net_margin is not None:
        # net margin sometimes arrives as a ratio (0.12) sometimes pct
        m = net_margin * 100 if abs(net_margin) <= 1 else net_margin
        subs.append(_lerp_worry(m, calm_at=18.0, worried_at=2.0))
        detail_bits.append(f"net margin {m:.1f}%")
    if rev_cagr_3 is not None:
        # Decimal in QualityOutput
        pct = rev_cagr_3 * 100
        subs.append(_lerp_worry(pct, calm_at=15.0, worried_at=-2.0))
        detail_bits.append(f"3y rev CAGR {pct:.1f}%")
    if score_raw is not None:
        # YieldIQ score inverted: 80 calm, 30 loud
        subs.append(_lerp_worry(score_raw, calm_at=80.0, worried_at=30.0))
        detail_bits.append(f"score {int(score_raw)}")

    # Accruals proxy: if insights expose earnings_quality_flag or
    # accruals_ratio, fold it in. We don't fail the rule when absent.
    accruals = _as_float(_get(insights, "accruals_ratio"))
    if accruals is not None:
        # |accruals| > 0.10 of assets is a yellow flag in literature
        a = abs(accruals)
        subs.append(_lerp_worry(a, calm_at=0.02, worried_at=0.15))
        detail_bits.append(f"|accruals| {a:.2f}")

    if not subs:
        return 50, "Earnings-quality inputs unavailable."
    avg = int(round(sum(subs) / len(subs)))
    return avg, "Earnings drivers: " + ", ".join(detail_bits) + "."


def _score_valuation_stretch(
    valuation: Any,
    insights: Any,
    peer_context: dict | None,
) -> tuple[int, str]:
    """20% weight."""
    mos       = _as_float(_get(valuation, "margin_of_safety"))  # percent
    pe        = _as_float(_get(insights, "pe_ratio"))
    subs: list[float] = []
    detail_bits: list[str] = []

    if mos is not None:
        # MoS +50 calm (fairly priced cheap), -40 loud (rich)
        # Higher worry when MoS is very negative (overpriced).
        # Note: MoS > 0 means undervalued in this codebase.
        subs.append(_lerp_worry(mos, calm_at=30.0, worried_at=-40.0))
        detail_bits.append(f"discount {mos:.0f}%")

    pe_peer_median = None
    if peer_context and isinstance(peer_context, dict):
        pe_block = peer_context.get("pe_ratio") or peer_context.get("pe")
        if isinstance(pe_block, dict):
            pe_peer_median = _as_float(pe_block.get("median"))

    if pe is not None and pe > 0:
        if pe_peer_median is not None and pe_peer_median > 0:
            # Relative premium: 0% premium calm, 100%+ premium loud.
            premium = (pe / pe_peer_median - 1.0) * 100
            subs.append(_lerp_worry(premium, calm_at=-20.0, worried_at=100.0))
            detail_bits.append(
                f"PE {pe:.1f}x vs peer {pe_peer_median:.1f}x"
            )
        else:
            # No peer median — use an absolute anchor for Indian broad market
            subs.append(_lerp_worry(pe, calm_at=15.0, worried_at=60.0))
            detail_bits.append(f"PE {pe:.1f}x")

    if not subs:
        return 50, "Valuation-stretch inputs unavailable."
    avg = int(round(sum(subs) / len(subs)))
    return avg, "Valuation drivers: " + ", ".join(detail_bits) + "."


def _score_market_signals(
    valuation: Any,
    insights: Any,
) -> tuple[int, str]:
    """15% weight."""
    beta = _as_float(_get(insights, "beta"))
    drawdown_52w = _as_float(_get(insights, "drawdown_from_52w_high"))
    if drawdown_52w is None:
        # Derive when 52w high + current price are available
        high_52 = _as_float(_get(insights, "high_52w")) or _as_float(_get(valuation, "high_52w"))
        cp = _as_float(_get(valuation, "current_price"))
        if high_52 and cp and high_52 > 0:
            drawdown_52w = (cp - high_52) / high_52 * 100.0  # negative %

    subs: list[float] = []
    detail_bits: list[str] = []

    if beta is not None:
        # Beta 0.6 calm, 1.8 loud
        subs.append(_lerp_worry(beta, calm_at=0.6, worried_at=1.8))
        detail_bits.append(f"beta {beta:.2f}")
    if drawdown_52w is not None:
        # Drawdown is negative-or-zero. -5% calm, -45% loud.
        subs.append(_lerp_worry(drawdown_52w, calm_at=-5.0, worried_at=-45.0))
        detail_bits.append(f"drawdown {drawdown_52w:.0f}% from 52w high")

    if not subs:
        return 50, "Market-signal inputs unavailable."
    avg = int(round(sum(subs) / len(subs)))
    return avg, "Market drivers: " + ", ".join(detail_bits) + "."


def _score_governance(quality: Any, insights: Any) -> tuple[int, str]:
    """10% weight."""
    red_flags = _get(insights, "red_flags_structured") or _get(insights, "red_flags") or []
    try:
        flag_count = len(red_flags)
    except TypeError:
        flag_count = 0

    pledge = _as_float(_get(quality, "promoter_pledge_pct"))

    subs: list[float] = []
    detail_bits: list[str] = []

    # 0 flags calm, 6+ flags loud
    subs.append(_lerp_worry(float(flag_count), calm_at=0.0, worried_at=6.0))
    detail_bits.append(f"{flag_count} red flag(s)")

    if pledge is not None:
        # 0% pledge calm, 50%+ pledge loud
        subs.append(_lerp_worry(pledge, calm_at=0.0, worried_at=50.0))
        detail_bits.append(f"promoter pledge {pledge:.1f}%")

    avg = int(round(sum(subs) / len(subs)))
    return avg, "Governance drivers: " + ", ".join(detail_bits) + "."


# ─── Composite ─────────────────────────────────────────────────


_COMPONENT_WEIGHTS: list[tuple[str, str, int]] = [
    ("solvency",          "Solvency",           30),
    ("earnings_quality",  "Earnings quality",   25),
    ("valuation_stretch", "Valuation stretch",  20),
    ("market_signals",    "Market signals",     15),
    ("governance",        "Governance",         10),
]


def compute_worry_index(
    *,
    valuation: Any = None,
    quality: Any = None,
    insights: Any = None,
    peer_context: dict | None = None,
) -> WorryIndex:
    """Compute the Worry Index from the assembled AnalysisResponse pieces.

    Pure function. Returns a ``WorryIndex`` whose ``score`` is a single
    integer 0-100 and ``contributors`` lists each component's score +
    weight + plain-English driver line.
    """
    component_results: dict[str, tuple[int, str]] = {
        "solvency":          _score_solvency(quality),
        "earnings_quality":  _score_earnings_quality(quality, insights),
        "valuation_stretch": _score_valuation_stretch(valuation, insights, peer_context),
        "market_signals":    _score_market_signals(valuation, insights),
        "governance":        _score_governance(quality, insights),
    }

    contributors: list[dict] = []
    weighted_sum = 0.0
    for key, label, weight in _COMPONENT_WEIGHTS:
        sub_score, detail = component_results[key]
        contributors.append({
            "component": key,
            "label": label,
            "weight": weight,
            "score": int(sub_score),
            "detail": detail,
        })
        weighted_sum += sub_score * weight

    composite = int(round(weighted_sum / 100.0))
    composite = max(0, min(100, composite))
    tier = _tier_for(composite)
    return WorryIndex(
        score=composite,
        tier=tier,
        headline=_TIER_COPY[tier],
        contributors=contributors,
    )
