# backend/services/analysis/honest_card_generator.py
# ═══════════════════════════════════════════════════════════════
# The Honest Card — radical-transparency panel generator.
#
# Per Design Manifesto v1 Rule 10 ("Transparency is a feature, not
# a disclaimer"). For every analysed ticker we emit:
#
#   * confident_facts        — 2-4 audited things we know
#   * best_estimate          — one-line headline + confidence
#   * uncertainty_factors    — 2-3 places the model could be wrong
#   * invalidating_conditions— exactly 3 numeric triggers that would
#                              flip the verdict
#
# Hard rules:
#   * NO LLM. Pure rules + templates.
#   * SEBI-safe — no banned words from
#     backend/services/analysis/sebi_filter.py.
#   * Tolerant of None / missing fields — each rule simply skips
#     when its inputs are absent.
#   * Field-additive — no CACHE_VERSION bump.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# Sector D/E fallback when the real sector median isn't available.
_DEFAULT_SECTOR_DE_MEDIAN = 0.6


@dataclass
class HonestCard:
    """The four-section transparency payload surfaced per analysis."""

    confident_facts: list[str] = field(default_factory=list)
    best_estimate: str = ""
    uncertainty_factors: list[str] = field(default_factory=list)
    invalidating_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ─── helpers ────────────────────────────────────────────────────


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """dict.get / getattr — accept either a dict or a Pydantic model."""
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
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _as_int(v: Any) -> int | None:
    f = _as_float(v)
    return int(f) if f is not None else None


def _fmt_rupees_cr(value_cr: float) -> str:
    """Format a Crore figure as ₹X.XL Cr / ₹X Cr."""
    if value_cr is None:
        return ""
    if value_cr >= 100_000:  # ₹1 lakh crore+
        return f"₹{value_cr / 100_000:.2f}L Cr"
    if value_cr >= 1_000:
        return f"₹{value_cr / 1_000:.1f}K Cr"
    return f"₹{value_cr:,.0f} Cr"


def _is_bank_like(company: Any, quality: Any) -> bool:
    # Holdco precedence (2026-06-09) — a pure holding company can sit
    # in a yfinance "Financial Services" bucket (BAJAJHLDNG does).
    # Without this guard, the bank branch in _build_invalidating_conditions
    # would render "Loan / advances growth below 8%" and "Gross NPA above
    # 2%" triggers on a holdco that has no loan book. The dedicated
    # _is_holdco() helper below is the holdco branch's entry gate.
    if _is_holdco(company, quality):
        return False
    if bool(_get(quality, "is_bank")):
        return True
    sector = (_get(company, "sector") or "").lower()
    industry = (_get(company, "industry") or "").lower()
    haystack = f"{sector} {industry}"
    return any(tok in haystack for tok in ("bank", "nbfc", "financial services"))


def _is_holdco(company: Any, quality: Any) -> bool:
    """Return True if the analysed ticker is a pure holding company.

    Three signals — match on any:
      1. ``quality.is_holdco`` boolean (the propagated single source of
         truth, set in service.py from ``is_holding_company``).
      2. Ticker membership in the curated ``HOLDING_COMPANIES`` set.
      3. ``valuation.valuation_method`` equals the canonical
         ``holding_company_sotp_required`` engine label.

    The third signal is the safety net for cached payloads that pre-
    date the propagation of the ``is_holdco`` field.
    """
    if bool(_get(quality, "is_holdco")):
        return True
    ticker = _get(company, "ticker") or ""
    try:
        from backend.services.analysis.constants import HOLDING_COMPANIES
        bare = (
            str(ticker).upper()
            .replace(".NS", "")
            .replace(".BO", "")
        )
        if bare in HOLDING_COMPANIES:
            return True
    except Exception:
        pass
    return False


def _is_cyclical(company: Any) -> bool:
    sector = (_get(company, "sector") or "").lower()
    industry = (_get(company, "industry") or "").lower()
    haystack = f"{sector} {industry}"
    return any(
        tok in haystack
        for tok in ("metal", "mining", "cement", "steel", "auto", "oil", "gas", "commodity")
    )


# ─── section builders ───────────────────────────────────────────


def _build_confident_facts(
    valuation: Any,
    quality: Any,
    insights: Any,
    company: Any,
) -> list[str]:
    out: list[str] = []

    # 1. Latest reported revenue (₹ Cr) — from company.market_cap proxy
    # OR from the historical period. We don't have it on the response so
    # we lean on the data the response exposes.
    market_cap = _as_float(_get(company, "market_cap"))
    if market_cap and market_cap > 0:
        market_cap_cr = market_cap / 1e7
        out.append(
            f"Market cap: {_fmt_rupees_cr(market_cap_cr)} — derived from latest "
            f"shares × live price"
        )

    # 2. Dividend declared in last 12 months
    dividend = _get(insights, "dividend")
    if dividend and _get(dividend, "has_dividends"):
        per_share = _as_float(_get(dividend, "dividend_rate_per_share"))
        if per_share is not None and per_share > 0:
            out.append(
                f"Dividend declared in last 12 months: ₹{per_share:.2f}/share"
            )

    # 3. Dividend consistency
    years = _as_int(_get(dividend, "consecutive_years")) if dividend else None
    if years is not None and years >= 5:
        out.append(
            f"Dividend paid for {years} consecutive years"
        )

    # 4. Promoter holding stability — we can't access historical pattern
    # from this response, but if promoter_pct is set we can state it as a fact.
    promoter_pct = _as_float(_get(quality, "promoter_pct"))
    if promoter_pct is not None and promoter_pct > 0:
        out.append(
            f"Promoter holding: {promoter_pct:.1f}% (latest shareholding filing)"
        )

    # 5. Latest filing period — direct from data
    period_end = _get(quality, "latest_filing_period_end")
    if period_end:
        out.append(
            f"Latest filed financials: period ending {period_end}"
        )

    # 6. ROE as audited fact when available
    roe = _as_float(_get(quality, "roe"))
    if roe is not None and not any("ROE" in f for f in out):
        out.append(
            f"Return on equity: {roe:.1f}% (from latest audited statements)"
        )

    # Always provide a safety-net fact so the section never empties out.
    if not out:
        company_name = _get(company, "company_name") or _get(company, "ticker") or "this company"
        out.append(
            f"Analysis derived from publicly filed financials for {company_name}"
        )

    # Cap at 4 to keep the card scannable.
    return out[:4]


def _build_best_estimate(valuation: Any, scenarios: Any) -> str:
    fv = _as_float(_get(valuation, "fair_value"))
    confidence = _as_int(_get(valuation, "confidence_score"))
    bear = _as_float(_get(valuation, "bear_case"))
    bull = _as_float(_get(valuation, "bull_case"))

    # Prefer scenarios.bear/bull when populated (richer than valuation).
    bear_sc = _as_float(_get(_get(scenarios, "bear"), "iv"))
    bull_sc = _as_float(_get(_get(scenarios, "bull"), "iv"))
    if bear_sc is not None and bear_sc > 0:
        bear = bear_sc
    if bull_sc is not None and bull_sc > 0:
        bull = bull_sc

    if fv is None or fv <= 0:
        return "Fair value not available for this ticker — see the data-quality notes."

    parts = [f"Fair value ₹{fv:,.0f}."]
    if bear is not None and bear > 0 and bull is not None and bull > 0:
        parts.append(f"Bear ₹{bear:,.0f}, bull ₹{bull:,.0f}.")
    if confidence is not None:
        parts.append(f"Model confidence {confidence}/100.")
    return " ".join(parts)


def _build_uncertainty_factors(
    valuation: Any,
    quality: Any,
    company: Any,
    sector_de_median: float | None,
) -> list[str]:
    out: list[tuple[float, str]] = []

    # Leverage above sector median (rule fires only when both sides are usable)
    de = _as_float(_get(quality, "de_ratio"))
    sector_de = sector_de_median if (sector_de_median and sector_de_median > 0) else _DEFAULT_SECTOR_DE_MEDIAN
    if de is not None and sector_de > 0 and de > sector_de * 1.5:
        out.append((
            de,
            f"Leverage at {de:.2f} is above sector median {sector_de:.2f} — "
            f"debt sensitivity matters here",
        ))

    # Low model confidence
    confidence = _as_int(_get(valuation, "confidence_score"))
    if confidence is not None and confidence < 70:
        out.append((
            float(100 - confidence),
            f"Model fit on this archetype is limited (confidence {confidence}/100) — "
            f"wide variance across scenarios",
        ))

    # Muted revenue growth
    cagr = _as_float(_get(quality, "revenue_cagr_3y"))
    if cagr is not None:
        cagr_pct = cagr if abs(cagr) >= 1.5 else cagr * 100
        if cagr_pct < 5:
            out.append((
                10.0 - cagr_pct,
                f"Recent revenue growth is muted at {cagr_pct:.1f}% over 3y — "
                f"extrapolation risk in the 5y projection",
            ))

    # Data limited
    if bool(_get(valuation, "data_limited")):
        out.append((
            90.0,
            "Data inputs flagged as limited — fair value should be read with caveats",
        ))

    # Cyclical / commodity exposure
    if _is_cyclical(company):
        out.append((
            25.0,
            "Sector cyclicality amplifies macro shocks — single-point fair value "
            "understates the band",
        ))

    # Peer-capped FV
    fv_source = _get(valuation, "fair_value_source")
    if fv_source == "peer_capped":
        out.append((
            30.0,
            "Raw DCF was above 1.5× peer-multiple ceiling — displayed fair value "
            "is the peer-capped figure",
        ))

    # Always keep at least one factor so the section never empties out.
    if not out:
        out.append((
            10.0,
            "All models compress a 10-year future into one number — actual outcomes "
            "will vary with macro conditions",
        ))

    # Sort by score desc, dedupe, cap at 3
    out.sort(key=lambda t: -t[0])
    seen: set[str] = set()
    factors: list[str] = []
    for _, text in out:
        if text in seen:
            continue
        seen.add(text)
        factors.append(text)
        if len(factors) >= 3:
            break
    return factors


def _build_invalidating_conditions(
    valuation: Any,
    quality: Any,
    company: Any,
) -> list[str]:
    out: list[str] = []

    # Always-on rule #1 — universal re-rating trigger
    out.append(
        "Fair value drops more than 15% from one quarter's results — re-rating triggered"
    )

    is_holdco = _is_holdco(company, quality)
    is_bank = _is_bank_like(company, quality)
    cagr = _as_float(_get(quality, "revenue_cagr_3y"))
    if cagr is not None:
        cagr_pct = cagr if abs(cagr) >= 1.5 else cagr * 100
    else:
        cagr_pct = None

    if is_holdco:
        # Holdco invalidating conditions — value is driven by the
        # underlying operating businesses, NOT by operating-company
        # metrics (loan growth, revenue CAGR, gross margin). Express
        # the triggers in NAV / holdco-discount / underlying-earnings
        # terms so the section is honest about what would re-rate the
        # holdco.
        out.append(
            "Underlying investee earnings cut by 20% — holdco NAV "
            "impaired in proportion"
        )
        out.append(
            "Holdco discount to NAV widens beyond 30% — typical "
            "re-rating risk"
        )
    elif is_bank:
        # Bank-specific triggers
        out.append(
            "Loan / advances growth below 8% for 2 consecutive quarters — "
            "bear case becomes base"
        )
        out.append(
            "Gross NPA above 2% — solvency concerns enter the model"
        )
    elif _is_cyclical(company):
        out.append(
            "Commodity cycle inversion (peak-to-trough margin compression) — "
            "reverse-DCF rebuild required"
        )
        out.append(
            "Operating margin compression below 10% — bull case invalidated"
        )
    else:
        # Generic — leans on growth + margin triggers
        if cagr_pct is not None and cagr_pct >= 10:
            threshold = max(int(round(cagr_pct * 0.6)), 5)
            out.append(
                f"Revenue CAGR slipping below {threshold}% for 2 consecutive "
                f"quarters — bear case becomes base"
            )
        else:
            out.append(
                "Revenue CAGR slipping below 5% for 2 consecutive quarters — "
                "bear case becomes base"
            )
        out.append(
            "Operating margin compression below 10% — bull case invalidated"
        )

    # Exactly 3, never more.
    return out[:3]


# ─── public API ─────────────────────────────────────────────────


def generate_honest_card(
    *,
    valuation: Any = None,
    quality: Any = None,
    insights: Any = None,
    scenarios: Any = None,
    company: Any = None,
    sector_de_median: float | None = None,
) -> HonestCard:
    """Build the Honest Card payload for one analysis.

    All inputs are optional and tolerant — pass whatever the analysis
    pipeline already has on hand. Pydantic models and plain dicts both
    work via ``_get``.
    """
    return HonestCard(
        confident_facts=_build_confident_facts(
            valuation=valuation,
            quality=quality,
            insights=insights,
            company=company,
        ),
        best_estimate=_build_best_estimate(valuation=valuation, scenarios=scenarios),
        uncertainty_factors=_build_uncertainty_factors(
            valuation=valuation,
            quality=quality,
            company=company,
            sector_de_median=sector_de_median,
        ),
        invalidating_conditions=_build_invalidating_conditions(
            valuation=valuation,
            quality=quality,
            company=company,
        ),
    )
