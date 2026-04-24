# backend/services/analytical_notes.py
# ═══════════════════════════════════════════════════════════════
# Contextual Analytical Notes (PR #69)
#
# Emits 1–5 user-facing, context-specific notes attached to every
# AnalysisResponse.payload. Each note flags a known structural
# limitation of the DCF / multiples engine for a given stock
# archetype (premium brand, conglomerate, regulated utility,
# cyclical trough, post-merger, high-P/E growth, ADR/USD-report).
#
# Design philosophy:
#   • Rules are PATTERN-BASED (thresholds on PE / ROE / CAGR /
#     sector), not hardcoded ticker allowlists. That way the
#     system covers the full 3,000-ticker universe without
#     curation debt.
#   • Rule 2 (Diversified Conglomerate) is the one permitted
#     exception: a small allowlist is acceptable because
#     "diversified" / "holding company" tags are inconsistent in
#     our sector metadata and missing these obvious cases would
#     undermine user trust.
#   • Notes are educational, not alarming — they explain the WHY
#     so a user can adjust their own conviction.
#   • This module is PURELY ADDITIVE. It never touches axis
#     scoring, the DCF, the moat engine, or the fair value. It
#     only annotates the response.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Literal


NoteKind = Literal[
    "premium_brand",
    "conglomerate",
    "cyclical_trough",
    "post_merger",
    "regulated_utility",
    "adr_usd_report",
    "high_pe_growth",
]

NoteSeverity = Literal["info", "caution"]


@dataclass
class AnalyticalNote:
    kind: NoteKind
    severity: NoteSeverity
    title: str
    body: str  # user-facing explanation, 1–3 sentences

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Rule 2: small, deliberately curated conglomerate list ──────
# Only tickers where the "diversified" nature is uncontroversial
# and where our sector tags don't already capture it. Keep this
# short; prefer the sector-text pattern match below where possible.
_CONGLOMERATE_TICKERS = {
    "RELIANCE", "ADANIENT", "ITC", "TATACHEM",
    "BAJAJHLDNG", "GODREJIND",
}

# Rule 2 companion: per-ticker human-readable segment hint, used
# to make the note concrete rather than generic.
_CONGLOMERATE_SEGMENTS = {
    "RELIANCE": "oil/retail/digital/chemicals",
    "ADANIENT": "ports/airports/green-energy/mining",
    "ITC": "FMCG/hotels/paperboards/agri",
    "TATACHEM": "soda-ash/specialty-chemicals/salt",
    "BAJAJHLDNG": "finance/auto-holding",
    "GODREJIND": "chemicals/agri/estates/FMCG-stakes",
}

# ─── Rule 3: regulated-utility list (kept in sync with PR #68) ──
# NOTE: PR #68 is drafting in parallel and is expected to ship a
# canonical `_REGULATED_UTILITIES` constant (likely in
# backend/services/analysis/constants.py). Until that lands we
# keep a local mirror here so this module is self-contained and
# doesn't break if imported before PR #68 merges. Post-PR-#68,
# this list should be replaced with a direct import:
#
#     from backend.services.analysis.constants import \
#         REGULATED_UTILITY_TICKERS as _REGULATED_UTILITIES
_REGULATED_UTILITIES = {
    "POWERGRID", "NTPC", "NHPC", "PFC", "RECLTD",
    "GAIL", "TORNTPOWER", "ADANITRANS",
}

# ─── Rule 7: ADR / USD-primary-listing tickers ──────────────────
# The Indian .NS listing is typically a secondary listing for
# these; primary disclosure is in USD on the NYSE/Nasdaq tape.
_ADR_TICKERS = {
    "INFY", "WIT", "HDB", "IBN", "TTM", "RDY", "SIFY", "MMYT",
}

# Sectors where the premium-brand pattern (Rule 1) applies.
_PREMIUM_SECTORS = {"fmcg", "retail", "consumer_durables", "pharma"}

# Sectors where the cyclical-trough pattern (Rule 4) applies.
_CYCLICAL_SECTORS = {"fmcg", "cement", "auto", "chemicals"}


# ─── small helpers ──────────────────────────────────────────────

def _strip_suffix(ticker: str) -> str:
    """RELIANCE.NS → RELIANCE; INFY.NS → INFY. Tolerates None."""
    if not ticker:
        return ""
    t = str(ticker).upper().strip()
    for suf in (".NS", ".BO", ".BSE", ".NSE"):
        if t.endswith(suf):
            return t[: -len(suf)]
    return t


def _num(x: Any) -> float | None:
    """Best-effort scalar coercion; returns None on failure."""
    try:
        if x is None:
            return None
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except Exception:
        return None


def _normalize_pct(x: Any) -> float | None:
    """Return a percent (e.g. 0.23 → 23.0, 23 → 23.0)."""
    v = _num(x)
    if v is None:
        return None
    return v * 100.0 if abs(v) < 1.5 else v


def _sector_key(sector_name: Any) -> str:
    """Lowercase, collapse spaces/dashes for pattern matching."""
    if not sector_name:
        return ""
    return (
        str(sector_name)
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
        .strip()
    )


# ─── rules ──────────────────────────────────────────────────────

def _rule_premium_brand(
    ticker: str, enriched: dict, metrics: dict
) -> AnalyticalNote | None:
    """Rule 1 — Premium Brand.

    PE > 1.5 × sector-median PE AND ROE > 18% AND sector in
    {fmcg, retail, consumer_durables, pharma}.
    """
    pe = _num(enriched.get("pe_ratio") or enriched.get("pe"))
    roe = _normalize_pct(enriched.get("roe"))
    sector = _sector_key(enriched.get("sector") or enriched.get("sector_name"))
    sector_pe = _num(metrics.get("sector_median_pe") or metrics.get("sector_pe"))

    if pe is None or roe is None or sector_pe is None:
        return None
    if sector not in _PREMIUM_SECTORS:
        return None
    if pe <= sector_pe * 1.5:
        return None
    if roe <= 18:
        return None

    return AnalyticalNote(
        kind="premium_brand",
        severity="info",
        title="Premium brand franchise",
        body=(
            f"Premium brand franchise (P/E {pe:.1f}× vs sector median "
            f"{sector_pe:.1f}×). Market has sustained this premium for "
            f"10+ years on strong brand moats. Our DCF uses sector-median "
            f"multiples; if you believe the brand premium is sustained, "
            f"FV could be 15–30% higher."
        ),
    )


def _rule_conglomerate(
    ticker: str, enriched: dict, metrics: dict
) -> AnalyticalNote | None:
    """Rule 2 — Diversified Conglomerate.

    Short hardcoded list (intentional — see header) OR sector
    name contains "diversified" / "holding company".
    """
    bare = _strip_suffix(ticker)
    sector = str(
        enriched.get("sector") or enriched.get("sector_name") or ""
    ).lower()
    matched = (
        bare in _CONGLOMERATE_TICKERS
        or "diversified" in sector
        or "holding company" in sector
        or "holding_company" in sector
    )
    if not matched:
        return None

    seg_hint = _CONGLOMERATE_SEGMENTS.get(bare, "multiple business segments")
    return AnalyticalNote(
        kind="conglomerate",
        severity="info",
        title="Diversified business group",
        body=(
            f"Diversified business group. Our DCF blends segment-level "
            f"FCF into a single projection. Sum-of-parts (SOTP) "
            f"valuation would likely produce a higher FV for "
            f"[{bare}: {seg_hint}]. Cross-reference analyst SOTP "
            f"reports for a segmental view."
        ),
    )


def _rule_regulated_utility(
    ticker: str, enriched: dict, metrics: dict
) -> AnalyticalNote | None:
    """Rule 3 — Regulated utility (CERC RoE ~15.5%)."""
    bare = _strip_suffix(ticker)
    if bare not in _REGULATED_UTILITIES:
        return None
    return AnalyticalNote(
        kind="regulated_utility",
        severity="info",
        title="CERC-regulated utility",
        body=(
            "CERC-regulated utility. Cash flows are bond-like with "
            "regulated ROE ~15.5% on the asset base. Our DCF now uses "
            "a lower WACC (9%) to reflect this, but the model still "
            "assumes equity-like volatility."
        ),
    )


def _rule_cyclical_trough(
    ticker: str, enriched: dict, metrics: dict
) -> AnalyticalNote | None:
    """Rule 4 — Cyclical trough.

    3y revenue CAGR < 2% AND current EBITDA margin is >2pp below
    its 5y median AND sector ∈ {fmcg, cement, auto, chemicals}.
    """
    cagr = _normalize_pct(
        enriched.get("revenue_cagr_3y") or enriched.get("rev_cagr_3y")
    )
    em = _normalize_pct(
        enriched.get("ebitda_margin") or enriched.get("ebitda_margin_ttm")
    )
    em_med = _normalize_pct(
        enriched.get("ebitda_margin_5y_median")
        or metrics.get("ebitda_margin_5y_median")
    )
    sector = _sector_key(enriched.get("sector") or enriched.get("sector_name"))

    if cagr is None or em is None or em_med is None:
        return None
    if sector not in _CYCLICAL_SECTORS:
        return None
    if cagr >= 2:
        return None
    if em >= em_med - 2.0:
        return None

    return AnalyticalNote(
        kind="cyclical_trough",
        severity="caution",
        title="Possible cyclical trough",
        body=(
            "Sector appears to be in a cyclical trough (margin "
            "compression, weak growth). Our DCF correctly reflects "
            "current earnings power but doesn't project cycle "
            "recovery. If you believe in sector recovery, normalised "
            "FV could be 20–40% higher."
        ),
    )


def _rule_post_merger(
    ticker: str, enriched: dict, metrics: dict
) -> AnalyticalNote | None:
    """Rule 5 — Post-merger transition.

    Shares outstanding grew > 15% in last 3 years AND a merger flag
    is present. The flag source is piotroski's
    `merger_exception_applied` from PR #67 when that lands;
    we also accept an enriched-level `merger_flag` fallback.
    """
    shares_now = _num(
        enriched.get("shares_outstanding") or enriched.get("shares")
    )
    shares_3y = _num(
        enriched.get("shares_outstanding_3y_ago")
        or enriched.get("shares_3y_ago")
    )
    merger_flag = bool(
        enriched.get("merger_flag")
        or enriched.get("merger_exception_applied")
        or metrics.get("merger_exception_applied")
    )
    if not merger_flag:
        return None
    if shares_now is None or shares_3y is None or shares_3y <= 0:
        return None
    growth = (shares_now - shares_3y) / shares_3y
    if growth <= 0.15:
        return None

    return AnalyticalNote(
        kind="post_merger",
        severity="info",
        title="Post-merger transition",
        body=(
            "Post-merger transition period. Growth metrics (revenue "
            "CAGR, ROA improvement) are distorted by the absorbed "
            "entity's balance sheet; share dilution reflects merger "
            "consideration, not operational weakness. Allow 2–3 years "
            "for normalisation."
        ),
    )


def _rule_high_pe_growth(
    ticker: str,
    enriched: dict,
    metrics: dict,
    premium_brand_fired: bool,
) -> AnalyticalNote | None:
    """Rule 6 — High-P/E growth stock.

    PE > 60 AND 3y revenue CAGR > 20% AND Rule 1 did NOT fire.
    """
    if premium_brand_fired:
        return None
    pe = _num(enriched.get("pe_ratio") or enriched.get("pe"))
    cagr = _normalize_pct(
        enriched.get("revenue_cagr_3y") or enriched.get("rev_cagr_3y")
    )
    if pe is None or cagr is None:
        return None
    if pe <= 60:
        return None
    if cagr <= 20:
        return None

    return AnalyticalNote(
        kind="high_pe_growth",
        severity="caution",
        title="Priced for sustained high growth",
        body=(
            "High-growth stock priced for 20%+ sustained growth. "
            "Market is paying for future earnings, not current ones. "
            "Our DCF reflects current fundamentals; if growth "
            "sustains, significant upside vs our FV."
        ),
    )


def _rule_adr_usd_report(
    ticker: str, enriched: dict, metrics: dict
) -> AnalyticalNote | None:
    """Rule 7 — ADR / USD-primary reporting."""
    bare = _strip_suffix(ticker)
    original_ccy = str(
        enriched.get("currency_original")
        or enriched.get("source_currency")
        or ""
    ).upper()
    listed_on = str(
        enriched.get("primary_exchange") or enriched.get("primary_listing") or ""
    ).lower()
    is_adr = (
        bare in _ADR_TICKERS
        or original_ccy == "USD"
        or "nyse" in listed_on
        or "nasdaq" in listed_on
    )
    if not is_adr:
        return None
    return AnalyticalNote(
        kind="adr_usd_report",
        severity="info",
        title="Cross-listed (ADR / USD reporting)",
        body=(
            "Cross-listed on NYSE (ADR). Financial statements may be "
            "reported in USD; our view uses INR conversion. Quarterly "
            "reports are timed to the US calendar."
        ),
    )


# ─── public entry point ─────────────────────────────────────────

def compute_notes(
    enriched: dict,
    analysis_output: dict,
    metrics: dict,
) -> list[AnalyticalNote]:
    """Run all rules in order and return the matching notes.

    Parameters
    ----------
    enriched : dict
        The enriched ticker bundle (output of
        `data.processor.compute_metrics`). Must at minimum contain
        `ticker` (or a ticker is looked up in analysis_output).
    analysis_output : dict
        A (possibly partial) view of the AnalysisResponse being
        assembled — used to avoid re-deriving sector/currency.
        May be empty; rules degrade gracefully.
    metrics : dict
        Optional sector / market context (e.g.
        `sector_median_pe`, `ebitda_margin_5y_median`) — may be
        empty. Rules that can't evaluate silently return None.

    Returns
    -------
    list[AnalyticalNote]
        0–7 notes. Order is deterministic: premium_brand,
        conglomerate, regulated_utility, cyclical_trough,
        post_merger, high_pe_growth, adr_usd_report. Capped at
        5 to avoid overwhelming the UI.
    """
    enriched = enriched or {}
    analysis_output = analysis_output or {}
    metrics = metrics or {}

    ticker = (
        enriched.get("ticker")
        or analysis_output.get("ticker")
        or ""
    )

    notes: list[AnalyticalNote] = []

    n1 = _rule_premium_brand(ticker, enriched, metrics)
    if n1:
        notes.append(n1)

    n2 = _rule_conglomerate(ticker, enriched, metrics)
    if n2:
        notes.append(n2)

    n3 = _rule_regulated_utility(ticker, enriched, metrics)
    if n3:
        notes.append(n3)

    n4 = _rule_cyclical_trough(ticker, enriched, metrics)
    if n4:
        notes.append(n4)

    n5 = _rule_post_merger(ticker, enriched, metrics)
    if n5:
        notes.append(n5)

    n6 = _rule_high_pe_growth(
        ticker, enriched, metrics, premium_brand_fired=(n1 is not None)
    )
    if n6:
        notes.append(n6)

    n7 = _rule_adr_usd_report(ticker, enriched, metrics)
    if n7:
        notes.append(n7)

    # UI contract: surface at most 5 notes.
    return notes[:5]
