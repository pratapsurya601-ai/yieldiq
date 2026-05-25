# backend/services/analysis/bulls_bears_generator.py
# ═══════════════════════════════════════════════════════════════
# Bulls Say / Bears Say structured narrative generator.
#
# Inspired by Morningstar's per-stock thesis bullets: 3 strongest
# positive signals and 3 strongest negative signals, surfaced as
# short factual sentences so users see BOTH sides of the thesis at
# a glance.
#
# Hard rules:
#   * NO LLM calls. Pure rules + templates.
#   * Output strings must be SEBI-safe (banned-words list in
#     ``backend/services/analysis/sebi_filter.py``). Verified by
#     ``backend/tests/test_bulls_bears_generator.py``.
#   * Inputs are tolerant — None / missing fields just skip that rule.
#   * Output is exactly up to 3 bulls and up to 3 bears, ordered by
#     rule-defined strength (higher score = stronger conviction).
#   * Field-additive on AnalysisResponse — pre-PR clients ignore
#     unknown fields; no CACHE_VERSION bump.
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
    here, just a category label. Banned words are avoided ("strong",
    "weak", "attractive" etc. would all trip the SEBI filter).
    """
    if moat == "Wide":
        return "scale, brand and switching costs"
    if moat == "Narrow":
        return "scale and switching costs"
    return "competitive position"


# ─── rules ──────────────────────────────────────────────────────
#
# Each rule is a (score, text-or-None) tuple. None means the rule
# did not fire on this payload. We collect all firing rules, sort
# by descending score, and take the top 3.


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
        out.append((
            mos,
            f"Trades at {int(round(mos))}% discount to model fair value",
        ))

    score = _as_int(_get(quality, "yieldiq_score"))
    if score is not None and score >= 70:
        out.append((
            float(score),
            f"YieldIQ score of {score}/100 — top decile fundamentals",
        ))

    moat = _get(quality, "moat")
    if moat in ("Wide", "Narrow"):
        src = _moat_source_for(moat)
        # Score: Wide outranks Narrow.
        out.append((
            80.0 if moat == "Wide" else 65.0,
            f"{moat} economic moat from {src}",
        ))

    dividend = _get(insights, "dividend")
    years = _as_int(_get(dividend, "consecutive_years"))
    if years is not None and years >= 5:
        out.append((
            float(min(years, 30)),
            f"{years} consecutive years of dividend growth",
        ))

    cagr = _as_float(_get(quality, "revenue_cagr_3y"))
    if cagr is not None:
        # CAGR comes in as decimal (0.124 = 12.4%) OR percent if abs >= 1.5.
        cagr_pct = cagr if abs(cagr) >= 1.5 else cagr * 100
        if cagr_pct >= 15:
            out.append((
                cagr_pct,
                f"Revenue compounding at {cagr_pct:.1f}% over 3y",
            ))

    roe = _as_float(_get(quality, "roe"))
    if roe is not None and roe >= 18:
        out.append((
            roe,
            f"ROE averaging {roe:.1f}% — high-quality returns on equity",
        ))

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
            # Trim long descriptions so the bullet stays one line.
            if len(seg) > 60:
                seg = seg[:57].rstrip() + "..."
            out.append((
                40.0,
                f"Capex commitments signal future growth in {seg}",
            ))

    bull_case = _as_float(_get(scenarios, "bull"))
    bull_mos = None
    if bull_case is None:
        # Pydantic model path — scenarios.bull is a ScenarioCase
        bull_obj = _get(scenarios, "bull")
        bull_mos = _as_float(_get(bull_obj, "mos_pct"))
    if bull_mos is not None and bull_mos >= 50:
        out.append((
            bull_mos,
            f"Bull-case scenario suggests {int(round(bull_mos))}% upside",
        ))

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
        out.append((
            abs(mos),
            f"Trades at {int(round(abs(mos)))}% premium to model fair value",
        ))

    confidence = _as_int(_get(valuation, "confidence_score"))
    if confidence is not None and confidence <= 35:
        out.append((
            float(100 - confidence),
            f"Model confidence is low ({confidence}/100) — wide input variance",
        ))

    de = _as_float(_get(quality, "de_ratio"))
    sector_de = sector_de_median or _DEFAULT_SECTOR_DE_MEDIAN
    if de is not None and sector_de > 0 and de > sector_de * 1.5:
        out.append((
            de,
            f"Leverage at {de:.2f} is above sector median of {sector_de:.2f}",
        ))

    if ar_signals:
        flags = ar_signals.get("auditor_flags")
        if isinstance(flags, list):
            for f in flags:
                if not isinstance(f, dict):
                    continue
                kind = str(f.get("type") or "").lower()
                if "key_audit_matter" in kind or kind == "kam":
                    out.append((
                        70.0,
                        "Key Audit Matter flagged in latest annual report",
                    ))
                    break

    cagr = _as_float(_get(quality, "revenue_cagr_3y"))
    if cagr is not None:
        cagr_pct = cagr if abs(cagr) >= 1.5 else cagr * 100
        if cagr_pct < 0:
            out.append((
                abs(cagr_pct),
                f"Revenue contracting at {abs(cagr_pct):.1f}% over 3y",
            ))

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
                out.append((35.0, text))

    bear_obj = _get(scenarios, "bear")
    bear_mos = _as_float(_get(bear_obj, "mos_pct"))
    if bear_mos is not None and bear_mos <= -20:
        out.append((
            abs(bear_mos),
            f"Bear-case scenario suggests {int(round(abs(bear_mos)))}% downside",
        ))

    red_flags = _get(insights, "red_flags_structured")
    if isinstance(red_flags, Iterable):
        try:
            count = sum(1 for _ in red_flags)
        except TypeError:
            count = 0
        if count > 0:
            out.append((
                30.0 + count,
                "Red flags surfaced by our data-quality validators",
            ))

    return out


# ─── public API ─────────────────────────────────────────────────


def generate_bulls_bears(
    *,
    valuation: Any = None,
    quality: Any = None,
    insights: Any = None,
    scenarios: Any = None,
    ar_signals: dict | None = None,
    sector_de_median: float | None = None,
) -> dict[str, list[str]]:
    """Return ``{"bulls": [...], "bears": [...]}`` — up to 3 each.

    All inputs are optional and tolerant — pass whatever the analysis
    pipeline already has on hand. Pydantic models and plain dicts both
    work via ``_get``.

    Bullets are ordered by rule strength (most compelling first) so
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

    return {
        "bulls": _top3(bull_hits),
        "bears": _top3(bear_hits),
    }
