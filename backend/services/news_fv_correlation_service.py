# backend/services/news_fv_correlation_service.py
# ═══════════════════════════════════════════════════════════════
# News ↔ Fair Value correlation service (v_news_fv_correlation_2026_06_10).
#
# Surfaces a novel correlation that no peer product publishes:
# "Last week's news drove FV from ₹X to ₹Y because [headline]."
#
# Pipeline
# ────────
#   1. Pull fair_value_history rows for the ticker over `lookback_days`.
#   2. Compute consecutive-row deltas; keep only deltas where
#      |pct_change| >= fv_change_threshold_pct (default 3%).
#   3. For each material delta, pull recent news headlines via
#      backend.services.news_service.fetch_yfinance_news (already
#      filtered, sentiment-scored, tier-ranked by news_filters).
#   4. Score each headline by:
#        • recency             (article published within ±7 days,
#                                closer to delta date = higher)
#        • sentiment alignment (headline sentiment_score sign matches
#                                fv delta sign — e.g. positive
#                                headline for upward FV move)
#        • importance          (critical > high > medium > low)
#        • source tier         (A > B > C; defaults A if missing)
#      and surface the top 3 drivers per delta.
#   5. Return a list of NewsFvCorrelation dataclass instances.
#
# This service is pure: no DB writes, no network calls beyond the
# existing news + valuation-history services. Safe to call from a
# public endpoint behind the standard 1-hour public cache.
#
# SEBI posture
# ────────────
# Output describes WHAT moved and WHICH headlines may have driven it.
# Never recommends action. Cause labels use neutral phrasing
# ("Linked to:") and the headline text itself is the user's source
# of truth — we just surface the linkage, we do not interpret.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date as Date, datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("yieldiq.news_fv_correlation")


# ─────────────────────────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────────────────────────

# A headline this many days off the FV change date drops out of
# consideration entirely. Inside the window, recency is a smooth
# decay (see _recency_score).
NEWS_WINDOW_DAYS: int = 7

# Topic keywords whose presence in a headline boosts relevance score.
# Kept small and conservative — these are buckets that historically
# move FV via the engine (earnings, regulation, M&A, guidance).
TOPIC_BOOST_KEYWORDS: dict[str, float] = {
    "earnings": 0.20,
    "results": 0.20,
    "quarterly": 0.15,
    "guidance": 0.15,
    "profit": 0.10,
    "revenue": 0.10,
    "margin": 0.10,
    "sebi": 0.15,
    "regulation": 0.10,
    "merger": 0.20,
    "acquisition": 0.20,
    "demerger": 0.15,
    "dividend": 0.10,
    "buyback": 0.10,
    "fraud": 0.25,
    "downgrade": 0.20,
    "upgrade": 0.15,
}

# Floor for confidence we'd publish: if our top driver scores below
# this, we still return the correlation but mark drivers as empty so
# the UI renders an honest "FV changed; no clear news driver".
MIN_DRIVER_SCORE: float = 0.15

# Cap on how many headlines we surface per FV delta.
TOP_DRIVERS_PER_DELTA: int = 3


# ─────────────────────────────────────────────────────────────────
# Dataclass payload
# ─────────────────────────────────────────────────────────────────

@dataclass
class NewsFvCorrelation:
    """One material FV change with its likely news drivers.

    `likely_drivers` is a list of dicts (not a nested dataclass) so the
    payload serialises cleanly into a JSON API response without an
    extra Pydantic schema. Empty list is meaningful — see
    MIN_DRIVER_SCORE: "FV moved but no clear headline driver found".
    """

    fv_change_date: str          # ISO YYYY-MM-DD
    fv_before: float
    fv_after: float
    pct_change: float            # signed; +5.2 means FV rose 5.2%
    likely_drivers: list[dict] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Internal helpers — pure, easy to unit-test
# ─────────────────────────────────────────────────────────────────

def _parse_iso_date(s: str | Date | datetime | None) -> Optional[Date]:
    """Best-effort parse to a date. Returns None on failure."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, Date):
        return s
    if not isinstance(s, str) or not s.strip():
        return None
    raw = s.strip()
    try:
        # Common ISO forms — date-only or full datetime.
        if "T" in raw or " " in raw:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.date()
        return Date.fromisoformat(raw[:10])
    except Exception:
        return None


def _pct_change(before: float, after: float) -> Optional[float]:
    """Signed percent change. None on bad input."""
    try:
        b = float(before)
        a = float(after)
    except (TypeError, ValueError):
        return None
    if b <= 0:
        return None
    raw = (a - b) / b * 100.0
    if raw != raw:  # NaN check
        return None
    return round(raw, 4)


def _recency_score(news_date: Date, fv_date: Date) -> float:
    """Smooth 1.0 → 0.0 over NEWS_WINDOW_DAYS. Zero outside window."""
    gap_days = abs((fv_date - news_date).days)
    if gap_days > NEWS_WINDOW_DAYS:
        return 0.0
    # Linear decay — gap 0 → 1.0, gap NEWS_WINDOW_DAYS → 0.0.
    return max(0.0, 1.0 - (gap_days / float(NEWS_WINDOW_DAYS)))


def _alignment_score(sentiment_score: Optional[float], fv_delta_pct: float) -> float:
    """How well does headline sentiment sign match the FV move sign?

    Returns 0.0 → 1.0. Headlines with a clear sign matching the FV
    direction (positive sentiment + FV up, or negative + FV down) score
    higher than mismatched or neutral ones.
    """
    if sentiment_score is None:
        return 0.3  # neutral-prior — don't punish missing signal
    s = float(sentiment_score)
    # Both signed; product is positive when aligned.
    aligned = (s * fv_delta_pct) > 0
    magnitude = min(1.0, abs(s))
    if aligned:
        return 0.4 + 0.6 * magnitude
    if abs(s) < 0.05:
        return 0.3  # neutral headline, no penalty
    return max(0.0, 0.3 - 0.3 * magnitude)


def _importance_score(level: Optional[str]) -> float:
    if not level:
        return 0.25
    return {
        "critical": 1.00,
        "high": 0.75,
        "medium": 0.50,
        "low": 0.25,
    }.get(str(level).lower(), 0.25)


def _source_tier_score(tier: Optional[str]) -> float:
    if not tier:
        return 0.75  # missing tier defaults to "decent" — don't penalise
    return {"A": 1.00, "B": 0.75, "C": 0.40}.get(str(tier).upper(), 0.50)


def _topic_boost(headline: str) -> float:
    if not headline or not isinstance(headline, str):
        return 0.0
    text = headline.lower()
    boost = 0.0
    for kw, weight in TOPIC_BOOST_KEYWORDS.items():
        if kw in text:
            boost += weight
    return min(0.4, boost)  # cap so a keyword-stuffed headline can't dominate


def _composite_relevance(
    *,
    sentiment_score: Optional[float],
    fv_delta_pct: float,
    news_date: Date,
    fv_date: Date,
    importance: Optional[str],
    source_tier: Optional[str],
    headline: str,
) -> float:
    """Weighted blend of the four signals. Returns score in [0, 1.0+]."""
    recency = _recency_score(news_date, fv_date)
    if recency <= 0.0:
        return 0.0
    alignment = _alignment_score(sentiment_score, fv_delta_pct)
    importance = _importance_score(importance)
    tier = _source_tier_score(source_tier)
    topic = _topic_boost(headline)
    # Weights: recency dominates (closer in time = more plausible cause),
    # alignment and importance contribute meaningfully, tier and topic
    # are smaller polish factors.
    return round(
        0.40 * recency
        + 0.25 * alignment
        + 0.20 * importance
        + 0.10 * tier
        + 0.05 * topic
        + topic,  # extra additive boost on top so a strong topic keyword
                  # (e.g. "fraud", "merger") can lift a borderline item
        4,
    )


# ─────────────────────────────────────────────────────────────────
# Data-source adapters — kept thin so tests can stub them.
# ─────────────────────────────────────────────────────────────────

def _fetch_fv_history(ticker: str, lookback_days: int) -> list[dict]:
    """Pull fair_value_history rows from the database.

    Returns rows newest-last (chronological ascending) with keys
    {date: str, fair_value: float}. Defensively returns [] on any
    failure — this is a panel, not the engine, so a DB hiccup must
    not break the analysis page.
    """
    try:
        from backend.services.analysis import db as _db  # type: ignore
    except Exception as exc:  # pragma: no cover — import safety only
        logger.warning("fv_correlation: analysis.db import failed: %s", exc)
        return []

    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=lookback_days)).isoformat()
    sql = """
        SELECT date::text AS date, fair_value::float AS fair_value
        FROM fair_value_history
        WHERE ticker = %s
          AND date >= %s::date
          AND fair_value IS NOT NULL
          AND fair_value > 0
          AND (quarantine_reason IS NULL)
        ORDER BY date ASC
    """
    try:
        conn = _db.get_connection() if hasattr(_db, "get_connection") else None
        if conn is None:
            return []
        with conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), cutoff))
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return rows
    except Exception as exc:
        logger.warning("fv_correlation: fv_history query failed for %s: %s", ticker, exc)
        return []


def _fetch_news_for_window(ticker: str, lookback_days: int) -> list[dict]:
    """Pull recent news items for the ticker.

    Wraps backend.services.news_service.fetch_yfinance_news; the items
    come through backend.services.news_filters which already adds
    sentiment_score / source_quality_tier / importance fields.
    """
    try:
        from backend.services.news_service import fetch_yfinance_news
        from backend.services.news_filters import filter_and_rank
    except Exception as exc:  # pragma: no cover — import safety only
        logger.warning("fv_correlation: news_service import failed: %s", exc)
        return []
    # Pull a generous slice — we filter down by date inside _drivers_for_delta.
    # Cap at 60 to bound the inner loop work.
    raw = fetch_yfinance_news(ticker, limit=60)
    try:
        return filter_and_rank(raw, ticker=ticker.upper())
    except Exception as exc:
        logger.warning("fv_correlation: filter_and_rank failed for %s: %s", ticker, exc)
        return raw


# ─────────────────────────────────────────────────────────────────
# Core algorithm
# ─────────────────────────────────────────────────────────────────

def _material_deltas(
    fv_rows: list[dict], threshold_pct: float,
) -> list[tuple[Date, float, float, float]]:
    """Find consecutive-row deltas whose |pct_change| >= threshold.

    Returns list of (change_date, fv_before, fv_after, pct_change).
    change_date is the second row in each pair (the "after" date).
    """
    out: list[tuple[Date, float, float, float]] = []
    if not fv_rows or len(fv_rows) < 2:
        return out
    prev: Optional[dict] = None
    for row in fv_rows:
        if prev is None:
            prev = row
            continue
        d_after = _parse_iso_date(row.get("date"))
        fv_before = prev.get("fair_value")
        fv_after = row.get("fair_value")
        pct = _pct_change(fv_before, fv_after)
        if d_after is not None and pct is not None and abs(pct) >= threshold_pct:
            out.append((d_after, float(fv_before), float(fv_after), pct))
        prev = row
    return out


def _drivers_for_delta(
    news_items: list[dict],
    fv_date: Date,
    fv_delta_pct: float,
) -> list[dict]:
    """Score every news item against this FV delta; return top N drivers."""
    scored: list[tuple[float, dict]] = []
    for n_idx, item in enumerate(news_items):
        n_date = _parse_iso_date(item.get("published_at"))
        if n_date is None:
            continue
        if abs((fv_date - n_date).days) > NEWS_WINDOW_DAYS:
            continue
        headline = str(item.get("headline") or "").strip()
        if not headline:
            continue
        score = _composite_relevance(
            sentiment_score=item.get("sentiment_score"),
            fv_delta_pct=fv_delta_pct,
            news_date=n_date,
            fv_date=fv_date,
            importance=item.get("importance"),
            source_tier=item.get("source_quality_tier"),
            headline=headline,
        )
        if score <= 0.0:
            continue
        scored.append((score, item))
    if not scored:
        return []
    scored.sort(key=lambda t: t[0], reverse=True)
    # Drop drivers below the confidence floor — keeps the UI honest.
    qualified = [(s, it) for s, it in scored if s >= MIN_DRIVER_SCORE]
    if not qualified:
        return []
    drivers: list[dict] = []
    for score, item in qualified[:TOP_DRIVERS_PER_DELTA]:
        drivers.append({
            "news_id": item.get("url") or f"{item.get('source', '')}::{item.get('headline', '')[:80]}",
            "headline": item.get("headline", ""),
            "source": item.get("source", ""),
            "url": item.get("url", ""),
            "published_at": item.get("published_at", ""),
            "sentiment_score": item.get("sentiment_score"),
            "sentiment_label": item.get("sentiment_label"),
            "importance": item.get("importance"),
            "source_quality_tier": item.get("source_quality_tier"),
            "relevance_score": round(float(score), 4),
        })
    return drivers


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def find_correlated_news(
    ticker: str,
    fv_change_threshold_pct: float = 3.0,
    lookback_days: int = 90,
    *,
    fv_rows: Optional[list[dict]] = None,
    news_items: Optional[list[dict]] = None,
) -> list[NewsFvCorrelation]:
    """For each material FV change in the lookback window, surface the
    news items (within ±NEWS_WINDOW_DAYS of the change) that most
    plausibly drove it.

    The ``fv_rows`` and ``news_items`` keyword args are escape hatches
    for unit tests — the production path leaves them as None and lets
    the function pull from the database / news service.

    Returns a list ordered by FV change date descending (most recent
    material moves first). Empty list when:
      * the ticker has fewer than 2 history rows in the window,
      * no consecutive delta crosses the threshold,
      * the news + FV-history fetches both fail.
    """
    if not ticker or not isinstance(ticker, str):
        return []
    tkr = ticker.upper().strip().replace(".NS", "").replace(".BO", "")
    if not tkr:
        return []
    threshold = max(0.5, float(fv_change_threshold_pct))
    lookback = max(7, int(lookback_days))

    rows = fv_rows if fv_rows is not None else _fetch_fv_history(tkr, lookback)
    deltas = _material_deltas(rows, threshold)
    if not deltas:
        return []

    news = news_items if news_items is not None else _fetch_news_for_window(tkr, lookback)

    correlations: list[NewsFvCorrelation] = []
    for d_after, fv_before, fv_after, pct in deltas:
        drivers = _drivers_for_delta(news, d_after, pct)
        correlations.append(NewsFvCorrelation(
            fv_change_date=d_after.isoformat(),
            fv_before=round(fv_before, 2),
            fv_after=round(fv_after, 2),
            pct_change=round(pct, 2),
            likely_drivers=drivers,
        ))
    # Most recent moves first — that's what the UI surfaces.
    correlations.sort(key=lambda c: c.fv_change_date, reverse=True)
    return correlations


def to_dict(correlations: list[NewsFvCorrelation]) -> dict:
    """JSON-serialisable payload wrapping the list.

    Includes a small summary block so the UI can render an
    explanation strip without recomputing aggregates client-side.
    """
    items = [asdict(c) for c in (correlations or [])]
    total = len(items)
    with_drivers = sum(1 for it in items if it.get("likely_drivers"))
    return {
        "correlations": items,
        "summary": {
            "total_material_moves": total,
            "moves_with_drivers": with_drivers,
            "window_days": NEWS_WINDOW_DAYS,
            "min_driver_score": MIN_DRIVER_SCORE,
            "top_drivers_per_move": TOP_DRIVERS_PER_DELTA,
        },
    }
