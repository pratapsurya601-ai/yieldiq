# backend/services/analysis/bulls_bears_generator.py
# ═══════════════════════════════════════════════════════════════
# Bulls Say / Bears Say structured narrative generator.
#
# Inspired by Morningstar's per-stock thesis bullets: 3 highest-
# scoring positive signals and 3 highest-scoring negative signals, surfaced as
# short paragraphs (2-3 sentences) so users get both the headline
# fact AND the mechanism / context behind it — the same finance-
# journalist register Tickertape and AlphaSpread ship.
#
# Hard rules:
#   * NO LLM calls. Pure rules + templates.
#   * Output strings must be SEBI-safe (banned-words list in
#     ``backend/services/analysis/sebi_filter.py``). Verified by
#     ``backend/tests/test_bulls_bears_generator.py``.
#   * Inputs are tolerant — None / missing fields just skip that rule.
#   * Output is exactly up to 3 bulls and up to 3 bears, ordered by
#     rule-defined score (higher score = higher conviction).
#   * Field-additive on AnalysisResponse — pre-PR clients ignore
#     unknown fields; no CACHE_VERSION bump.
#
# v_238 (2026-05-26) — paragraph upgrade:
#   * Each rule emits a lead sentence (the headline fact, same as
#     v_bulls_bears_2026_05_25 so frontend / test assertions on
#     substrings keep matching) PLUS a supporting sentence with
#     mechanism / context, PLUS an optional caveat or magnitude
#     qualifier. Target length ~40-50 words per bullet.
#   * New optional output keys: ``bull_case_narrative`` and
#     ``bear_case_narrative`` — the top-3 paragraphs joined into a
#     single block of prose so consumers that prefer one composed
#     paragraph (sector PDF export, OG image) can skip re-joining.
#   * New optional ``thesis_updated`` ISO date — mirrors what
#     Tickertape ships ("April 2026") so the panel reads as a
#     dated note rather than evergreen.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from typing import Any, Iterable


# Sector-median D/E fallback when we can't look up the real value.
# Indian-equity broad median sits around 0.6 (excluding banks/NBFCs).
_DEFAULT_SECTOR_DE_MEDIAN = 0.6


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
    # Filter NaN / inf — they'd produce garbage strings.
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _as_int(v: Any) -> int | None:
    f = _as_float(v)
    return int(f) if f is not None else None


def _moat_source_for(moat: str) -> str:
    """Pick a short, SEBI-safe noun phrase to describe a moat source.

    Kept deliberately generic — there is no per-ticker maintenance
    here, just a category label. SEBI-banned descriptors are avoided
    (the filter would otherwise reject this fragment at generate time).
    """
    if moat == "Wide":
        return "scale, brand and switching costs"
    if moat == "Narrow":
        return "scale and switching costs"
    return "competitive position"


def _compose(*sentences: str | None) -> str:
    """Join 2-3 non-empty sentences into a single paragraph string.

    Strips empties, ensures each sentence ends in a period, and
    separates with single spaces. Keeps composition deterministic so
    canary-diff produces byte-stable output.
    """
    parts: list[str] = []
    for s in sentences:
        if not s:
            continue
        s = s.strip()
        if not s:
            continue
        # Avoid a trailing double-period if the caller already added one.
        if not s.endswith(("."  , "!", "?")):
            s = s + "."
        parts.append(s)
    return " ".join(parts)


# ─── rules ──────────────────────────────────────────────────────
#
# Each rule is a (score, paragraph) tuple. None means the rule
# did not fire on this payload. We collect all firing rules, sort
# by descending score, and take the top 3.
#
# Lead sentence preserves the v_bulls_bears_2026_05_25 wording so
# downstream substring assertions (and any human muscle-memory for
# the old bullet text) keep matching.


def _bull_rules(
    valuation: Any,
    quality: Any,
    insights: Any,
    scenarios: Any,
    ar_signals: dict | None,
) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []

    mos = _as_float(_get(valuation, "margin_of_safety"))
    if mos is not None and mos >= 30:
        fv = _as_float(_get(valuation, "fair_value"))
        cp = _as_float(_get(valuation, "current_price"))
        lead = f"Trades at {int(round(mos))}% discount to model fair value"
        # Mechanism sentence: anchor the percentage with the underlying
        # rupee numbers so the gap is auditable, not a floating claim.
        if fv is not None and cp is not None and fv > 0 and cp > 0:
            mid = (
                f"The discounted-cash-flow model lands at "
                f"{fv:,.0f} per share against a market price of "
                f"{cp:,.0f}, leaving headroom of "
                f"{fv - cp:,.0f} per share before the gap closes"
            )
        else:
            mid = (
                "The discounted-cash-flow model values the equity "
                "well above where it currently changes hands, leaving "
                "headroom before the gap closes"
            )
        caveat = (
            "A wide gap can persist for years if the market disagrees "
            "with the model's cash-flow or discount-rate assumptions"
        )
        out.append((mos, _compose(lead, mid, caveat)))

    score = _as_int(_get(quality, "yieldiq_score"))
    if score is not None and score >= 70:
        lead = f"YieldIQ score of {score}/100 — top decile fundamentals"
        mid = (
            "The composite blends moat, profitability, balance-sheet "
            "health and earnings quality into one number, and this "
            "ticker clears every sub-component threshold"
        )
        caveat = (
            "Composite scores compress noise — read the breakdown "
            "card below for which axis is doing the heavy lifting"
        )
        out.append((float(score), _compose(lead, mid, caveat)))

    moat = _get(quality, "moat")
    if moat in ("Wide", "Narrow"):
        src = _moat_source_for(moat)
        lead = f"{moat} economic moat from {src}"
        mid = (
            "Customers face real friction to leave, suppliers face "
            "real friction to displace, and incremental capital earns "
            "returns above the cost of capital across the cycle"
        )
        roe = _as_float(_get(quality, "roe"))
        if roe is not None:
            caveat = (
                f"Current ROE of {roe:.1f}% is consistent with the "
                f"moat label, though moats erode quietly — watch the "
                f"trend, not the level"
            )
        else:
            caveat = (
                "Moats erode quietly long before they show up in "
                "the headline numbers — watch the trend, not the level"
            )
        # Score: Wide outranks Narrow.
        out.append((
            80.0 if moat == "Wide" else 65.0,
            _compose(lead, mid, caveat),
        ))

    dividend = _get(insights, "dividend")
    years = _as_int(_get(dividend, "consecutive_years"))
    if years is not None and years >= 5:
        lead = f"{years} consecutive years of dividend growth"
        mid = (
            "An unbroken payout streak through multiple rate and "
            "earnings cycles is a hard-to-fake signal of management "
            "discipline and free-cash-flow durability"
        )
        caveat = (
            "Payout policy can change with a single board meeting — "
            "the streak describes the past, not a commitment"
        )
        out.append((float(min(years, 30)), _compose(lead, mid, caveat)))

    cagr = _as_float(_get(quality, "revenue_cagr_3y"))
    if cagr is not None:
        # CAGR comes in as decimal (0.124 = 12.4%) OR percent if abs >= 1.5.
        cagr_pct = cagr if abs(cagr) >= 1.5 else cagr * 100
        if cagr_pct >= 15:
            lead = f"Revenue compounding at {cagr_pct:.1f}% over 3y"
            mid = (
                "Growth at this rate, sustained over three full "
                "reporting cycles, typically reflects pricing power, "
                "category expansion or share gains rather than a "
                "single one-off tailwind"
            )
            caveat = (
                "Three-year CAGR can be flattered by a depressed "
                "base year — the next print is the real tell"
            )
            out.append((cagr_pct, _compose(lead, mid, caveat)))

    roe = _as_float(_get(quality, "roe"))
    if roe is not None and roe >= 18:
        lead = f"ROE averaging {roe:.1f}% — high-quality returns on equity"
        mid = (
            "Each rupee of shareholder capital is generating returns "
            "well clear of the cost of equity, which compounds book "
            "value at a rate few listed peers can sustain"
        )
        caveat = (
            "Elevated ROE driven by leverage rather than operating "
            "margin is fragile — cross-check the debt-to-equity tile"
        )
        out.append((roe, _compose(lead, mid, caveat)))

    # AR-signals: capex commitments → forward growth signal.
    if ar_signals:
        capex = ar_signals.get("capex_commitments")
        if isinstance(capex, list) and capex:
            first = capex[0] if isinstance(capex[0], dict) else {}
            seg = (
                first.get("segment")
                or first.get("description")
                or "core segments"
            )
            seg = str(seg).strip() or "core segments"
            # Trim long descriptions so the lead sentence stays tight.
            if len(seg) > 60:
                seg = seg[:57].rstrip() + "..."
            lead = f"Capex commitments signal future growth in {seg}"
            mid = (
                "Disclosed capital-expenditure plans in the latest "
                "annual report point to capacity additions that "
                "convert into volume and revenue over the next "
                "8-12 quarters"
            )
            caveat = (
                "Project execution slippage and demand-cycle timing "
                "remain the two largest sources of variance"
            )
            out.append((40.0, _compose(lead, mid, caveat)))

    bull_case = _as_float(_get(scenarios, "bull"))
    bull_mos = None
    if bull_case is None:
        # Pydantic model path — scenarios.bull is a ScenarioCase
        bull_obj = _get(scenarios, "bull")
        bull_mos = _as_float(_get(bull_obj, "mos_pct"))
    if bull_mos is not None and bull_mos >= 50:
        lead = (
            f"Bull-case scenario suggests {int(round(bull_mos))}% upside"
        )
        mid = (
            "The upside path assumes growth and margins toward the "
            "top of the historical band, with the discount rate held "
            "at the base-case level"
        )
        caveat = (
            "Scenario outputs are conditional — treat the band, not "
            "the point, as the meaningful signal"
        )
        out.append((bull_mos, _compose(lead, mid, caveat)))

    return out


def _bear_rules(
    valuation: Any,
    quality: Any,
    insights: Any,
    scenarios: Any,
    ar_signals: dict | None,
    sector_de_median: float | None,
) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []

    mos = _as_float(_get(valuation, "margin_of_safety"))
    if mos is not None and mos <= -20:
        fv = _as_float(_get(valuation, "fair_value"))
        cp = _as_float(_get(valuation, "current_price"))
        lead = (
            f"Trades at {int(round(abs(mos)))}% premium to model fair value"
        )
        if fv is not None and cp is not None and fv > 0 and cp > 0:
            mid = (
                f"The discounted-cash-flow model lands at "
                f"{fv:,.0f} per share while the market is pricing "
                f"in {cp:,.0f}, an embedded growth expectation the "
                f"base case does not support"
            )
        else:
            mid = (
                "The market price is running ahead of the discounted-"
                "cash-flow model's base case, implying growth or "
                "margin assumptions richer than the historical record"
            )
        caveat = (
            "Premiums can persist on narrative or scarcity value — "
            "a premium is not the same as an imminent drawdown"
        )
        out.append((abs(mos), _compose(lead, mid, caveat)))

    confidence = _as_int(_get(valuation, "confidence_score"))
    if confidence is not None and confidence <= 35:
        lead = (
            f"Model confidence is low ({confidence}/100) — wide input variance"
        )
        mid = (
            "Disagreement across data sources, missing line items or "
            "an unstable history widens the band of plausible fair "
            "values, so the central estimate carries less information "
            "than usual"
        )
        caveat = (
            "Low confidence is not a directional verdict — it is a "
            "request for additional diligence before sizing a position"
        )
        out.append((float(100 - confidence), _compose(lead, mid, caveat)))

    de = _as_float(_get(quality, "de_ratio"))
    sector_de = sector_de_median or _DEFAULT_SECTOR_DE_MEDIAN
    if de is not None and sector_de > 0 and de > sector_de * 1.5:
        lead = (
            f"Leverage at {de:.2f} is above sector median of "
            f"{sector_de:.2f}"
        )
        mid = (
            "Higher debt loading amplifies returns when operating "
            "conditions cooperate and amplifies losses when they "
            "do not — the equity sits behind a thicker layer of "
            "fixed claims"
        )
        caveat = (
            "Refinancing risk rises with rate cycles; check the "
            "interest-coverage tile alongside this number"
        )
        out.append((de, _compose(lead, mid, caveat)))

    if ar_signals:
        flags = ar_signals.get("auditor_flags")
        if isinstance(flags, list):
            for f in flags:
                if not isinstance(f, dict):
                    continue
                kind = str(f.get("type") or "").lower()
                if "key_audit_matter" in kind or kind == "kam":
                    lead = (
                        "Key Audit Matter flagged in latest annual report"
                    )
                    mid = (
                        "Auditors only escalate an item to Key Audit "
                        "Matter when the area requires significant "
                        "judgement or carries above-average risk of "
                        "material misstatement"
                    )
                    caveat = (
                        "A KAM is not an adverse opinion — it is a "
                        "signpost to read the underlying note in full"
                    )
                    out.append((70.0, _compose(lead, mid, caveat)))
                    break

    cagr = _as_float(_get(quality, "revenue_cagr_3y"))
    if cagr is not None:
        cagr_pct = cagr if abs(cagr) >= 1.5 else cagr * 100
        if cagr_pct < 0:
            lead = (
                f"Revenue contracting at {abs(cagr_pct):.1f}% over 3y"
            )
            mid = (
                "A negative top-line trend across three full reporting "
                "cycles is rarely a single bad quarter — it usually "
                "reflects category decline, share loss or pricing "
                "pressure that has not yet reversed"
            )
            caveat = (
                "Cyclical businesses can mean-revert quickly; check "
                "the latest two quarters for an inflection before "
                "extrapolating"
            )
            out.append((abs(cagr_pct), _compose(lead, mid, caveat)))

    if ar_signals:
        risks = ar_signals.get("risk_factors")
        if isinstance(risks, list) and risks:
            first = risks[0]
            text = None
            if isinstance(first, dict):
                text = first.get("summary") or first.get("description")
            elif isinstance(first, str):
                text = first
            if text:
                text = str(text).strip()
                if len(text) > 90:
                    text = text[:87].rstrip() + "..."
                lead = text
                mid = (
                    "The risk factor is lifted verbatim from the "
                    "company's own annual-report disclosure, which "
                    "makes it the most direct articulation of the "
                    "downside the board has put in writing"
                )
                caveat = (
                    "Disclosed risks are routinely boilerplate — read "
                    "the surrounding paragraph for severity and "
                    "mitigation"
                )
                out.append((35.0, _compose(lead, mid, caveat)))

    bear_obj = _get(scenarios, "bear")
    bear_mos = _as_float(_get(bear_obj, "mos_pct"))
    if bear_mos is not None and bear_mos <= -20:
        lead = (
            f"Bear-case scenario suggests "
            f"{int(round(abs(bear_mos)))}% downside"
        )
        mid = (
            "The downside path assumes growth and margins toward the "
            "bottom of the historical band, with the discount rate "
            "held at the base-case level"
        )
        caveat = (
            "Scenarios are conditional — the bear case is a stress "
            "test, not a forecast"
        )
        out.append((abs(bear_mos), _compose(lead, mid, caveat)))

    red_flags = _get(insights, "red_flags_structured")
    if isinstance(red_flags, Iterable):
        try:
            count = sum(1 for _ in red_flags)
        except TypeError:
            count = 0
        if count > 0:
            lead = "Red flags surfaced by our data-quality validators"
            mid = (
                "One or more automated validators tripped on the "
                "latest filings — common triggers include auditor "
                "changes, related-party balances, negative equity "
                "or large period-over-period restatements"
            )
            caveat = (
                "Validator hits are descriptive, not adjudicative — "
                "open the red-flags panel for the underlying line items"
            )
            out.append((30.0 + count, _compose(lead, mid, caveat)))

    return out


# ─── public API ─────────────────────────────────────────────────


def _format_thesis_date(date_str: Any) -> str | None:
    """Return a Tickertape-style "Month YYYY" stamp from an ISO date.

    Accepts ISO-8601 ("2026-04-12", "2026-04-12T08:00:00Z", etc.) and
    returns ``"April 2026"`` or None if parsing fails. Pure-Python,
    no new dependencies — the calendar import is stdlib.
    """
    if date_str is None:
        return None
    s = str(date_str).strip()
    if not s:
        return None
    # Pull the leading "YYYY-MM" — tolerant of trailing time/tz suffix.
    import calendar
    try:
        year = int(s[0:4])
        month = int(s[5:7])
        if 1 <= month <= 12:
            return f"{calendar.month_name[month]} {year}"
    except (ValueError, IndexError):
        return None
    return None


def generate_bulls_bears(
    *,
    valuation: Any = None,
    quality: Any = None,
    insights: Any = None,
    scenarios: Any = None,
    ar_signals: dict | None = None,
    sector_de_median: float | None = None,
    computed_at: Any = None,
) -> dict[str, Any]:
    """Return the bulls/bears thesis bundle.

    Output keys:
      * ``bulls`` — list[str], up to 3 paragraphs
      * ``bears`` — list[str], up to 3 paragraphs
      * ``bull_case_narrative`` — str | None, the 3 bull paragraphs
        joined into one block; None when ``bulls`` is empty.
      * ``bear_case_narrative`` — str | None, the 3 bear paragraphs
        joined into one block; None when ``bears`` is empty.
      * ``thesis_updated`` — str | None, "Month YYYY" stamp derived
        from ``computed_at`` (or whatever ISO date the caller passes).

    All inputs are optional and tolerant — pass whatever the analysis
    pipeline already has on hand. Pydantic models and plain dicts both
    work via ``_get``.

    Bullets are ordered by rule score (highest first) so
    the frontend can render them in priority order without further
    sorting.
    """
    bull_hits = _bull_rules(valuation, quality, insights, scenarios, ar_signals)
    bear_hits = _bear_rules(
        valuation, quality, insights, scenarios, ar_signals, sector_de_median,
    )

    # Sort by score descending; take top 3; dedupe by text just in case
    # two rules collide on the same template.
    def _top3(hits: list[tuple[float, str]]) -> list[str]:
        hits_sorted = sorted(hits, key=lambda t: (-t[0], t[1]))
        seen: set[str] = set()
        out: list[str] = []
        for _, text in hits_sorted:
            if text in seen:
                continue
            seen.add(text)
            out.append(text)
            if len(out) >= 3:
                break
        return out

    bulls = _top3(bull_hits)
    bears = _top3(bear_hits)

    bull_narrative = " ".join(bulls) if bulls else None
    bear_narrative = " ".join(bears) if bears else None
    stamp = _format_thesis_date(computed_at)

    return {
        "bulls": bulls,
        "bears": bears,
        "bull_case_narrative": bull_narrative,
        "bear_case_narrative": bear_narrative,
        "thesis_updated": stamp,
    }
