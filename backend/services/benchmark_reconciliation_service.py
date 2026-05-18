"""Benchmark Reconciliation Service (Layer A of structural valuation safety).

This is the **read-only** sanity-check layer between our model FVs (in
``analysis_cache.payload->valuation->fair_value``) and the analyst
consensus targets we pull nightly into ``consensus_estimates``
(see PR #334). It does not mutate either side.

What it does
------------
1. ``get_outliers(threshold_pct, min_analysts) -> list[OutlierRow]``
   joins ``analysis_cache`` (latest payload per ticker) against
   ``latest_consensus_per_ticker`` and returns rows where
   ``|delta_pct| > threshold_pct`` AND ``analyst_count >= min_analysts``.

2. ``is_ticker_flagged(ticker, threshold_pct, min_analysts) -> CaveatInfo``
   answers the per-request question used by the analysis serializer:
   "should this ticker carry a benchmark caveat in its ``data_issues``
   list?". Returns a small struct with ``abs_delta_pct`` so the caller
   can render the generic caveat text without ever seeing the
   consensus number itself.

Why no caching at the service layer
-----------------------------------
The admin dashboard wraps this in a 1h Redis cache at the router edge.
The per-ticker analysis path calls ``is_ticker_flagged`` which executes
a tiny indexed point lookup (one row each from two tables) — adding
another cache layer there would just be a way to serve stale flags.

Discipline rules respected
--------------------------
- No CACHE_VERSION bump. Consensus does not enter the analysis cache
  key; we only enrich ``data_issues`` at serialize time.
- No Railway-worker work. All execution is request-scoped or admin.
- The user-facing caveat NEVER mentions the consensus number. The
  service exposes ``abs_delta_pct`` (an integer percentage) only —
  the wording is operator-controlled, not analyst-target-controlled.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Iterable, Optional

logger = logging.getLogger("yieldiq.benchmark_reconciliation")


# Defaults from docs/design/benchmark-reconciliation-framework.md §5.
# 30% threshold for week 1; the doc anticipates a retune to 25% at D21.
DEFAULT_THRESHOLD_PCT = 0.30
DEFAULT_MIN_ANALYSTS = 3
# Consensus is considered stale if older than this — keeps us from
# flagging a fresh FV against a month-old target after a corp action.
CONSENSUS_MAX_AGE_DAYS = 14
# Our FV is considered stale if its cache row is older than this.
OUR_FV_MAX_AGE_DAYS = 30


# ── Public types ────────────────────────────────────────────────────


@dataclass(frozen=True)
class OutlierRow:
    """One row of the admin benchmark-outliers payload.

    Note: ``consensus_fv`` IS present here because this struct only
    flows to the admin dashboard (require_admin gated). The user-facing
    caveat path uses ``CaveatInfo`` below which omits it.
    """
    ticker: str
    sector: Optional[str]
    our_fv: float
    consensus_fv: float
    delta_pct: float
    direction: str               # "over" if our_fv > consensus else "under"
    analyst_count: int
    source: str                  # "finnhub" | "yfinance"
    fetched_at: str              # ISO8601
    computed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CaveatInfo:
    """The minimal payload returned to the analysis serializer.

    ``abs_delta_pct`` is rounded to an integer percentage point — never
    sub-percent, never signed (the *direction* of the disagreement is
    not informative to a retail user and could be mis-read as a "buy"
    or "sell" signal). The consensus number itself is **deliberately
    excluded** to honour the framework's "no analyst-target leakage to
    end users" promise.
    """
    flagged: bool
    abs_delta_pct: Optional[int] = None
    analyst_count: Optional[int] = None
    direction: Optional[str] = None  # admin-only metadata for logs

    @classmethod
    def not_flagged(cls) -> "CaveatInfo":
        return cls(flagged=False)


# ── SQL ─────────────────────────────────────────────────────────────


# Single JOIN: latest analysis_cache payload per ticker × latest
# consensus row per ticker (the view already prefers Finnhub > yfinance
# and bounds itself to the last 14 days — see migration 044).
_OUTLIERS_SQL = """
SELECT
    ac.ticker                                                   AS ticker,
    (ac.payload->>'sector')                                     AS sector,
    (ac.payload->'valuation'->>'fair_value')::float             AS our_fv,
    lc.target_median::float                                     AS consensus_fv,
    lc.analyst_count                                            AS analyst_count,
    lc.source                                                   AS source,
    lc.fetched_at                                               AS fetched_at,
    ac.computed_at                                              AS computed_at
FROM (
    SELECT DISTINCT ON (ticker) ticker, payload, computed_at
    FROM analysis_cache
    WHERE computed_at > now() - (:our_max_days || ' days')::interval
    ORDER BY ticker, computed_at DESC
) ac
JOIN latest_consensus_per_ticker lc
  ON lc.ticker = ac.ticker
WHERE lc.analyst_count >= :min_analysts
  AND lc.target_median IS NOT NULL
  AND lc.target_median > 0
  AND (ac.payload->'valuation'->>'fair_value')::float IS NOT NULL
  AND (ac.payload->'valuation'->>'fair_value')::float > 0
"""


# Per-ticker variant used by the user-caveat path. Returns at most 1 row.
_ONE_TICKER_SQL = """
SELECT
    (ac.payload->'valuation'->>'fair_value')::float AS our_fv,
    lc.target_median::float                         AS consensus_fv,
    lc.analyst_count                                AS analyst_count,
    lc.source                                       AS source,
    lc.fetched_at                                   AS fetched_at
FROM (
    SELECT ticker, payload, computed_at
    FROM analysis_cache
    WHERE ticker = :ticker
      AND computed_at > now() - (:our_max_days || ' days')::interval
    ORDER BY computed_at DESC
    LIMIT 1
) ac
JOIN latest_consensus_per_ticker lc
  ON lc.ticker = ac.ticker
WHERE lc.analyst_count IS NOT NULL
LIMIT 1
"""


# ── Core algorithm (pure, testable without a DB) ────────────────────


def _classify(
    our_fv: Optional[float],
    consensus_fv: Optional[float],
    analyst_count: Optional[int],
    threshold_pct: float,
    min_analysts: int,
) -> Optional[float]:
    """Return signed delta_pct iff this row qualifies as an outlier,
    else None. Skips low-signal (too few analysts), missing inputs, and
    non-positive divisors. Pure function — used directly in unit tests."""
    if our_fv is None or consensus_fv is None:
        return None
    if consensus_fv <= 0 or our_fv <= 0:
        return None
    if analyst_count is None or analyst_count < min_analysts:
        return None
    delta = (our_fv - consensus_fv) / consensus_fv
    if abs(delta) <= threshold_pct:
        return None
    return delta


def _row_from_record(
    record: dict, threshold_pct: float, min_analysts: int,
) -> Optional[OutlierRow]:
    delta = _classify(
        record.get("our_fv"), record.get("consensus_fv"),
        record.get("analyst_count"), threshold_pct, min_analysts,
    )
    if delta is None:
        return None
    return OutlierRow(
        ticker=record["ticker"],
        sector=record.get("sector"),
        our_fv=float(record["our_fv"]),
        consensus_fv=float(record["consensus_fv"]),
        delta_pct=round(delta, 4),
        direction="over" if delta > 0 else "under",
        analyst_count=int(record["analyst_count"]),
        source=record.get("source") or "unknown",
        fetched_at=str(record.get("fetched_at") or ""),
        computed_at=str(record.get("computed_at")) if record.get("computed_at") else None,
    )


def compute_outliers_from_records(
    records: Iterable[dict],
    *,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    min_analysts: int = DEFAULT_MIN_ANALYSTS,
    direction: str = "both",
    limit: Optional[int] = None,
) -> list[OutlierRow]:
    """Pure-function entry point. Given an iterable of row-dicts (the
    SQL output), classify and sort. Used both by the live admin path
    and by unit tests that bypass the DB entirely."""
    out: list[OutlierRow] = []
    for r in records:
        row = _row_from_record(r, threshold_pct, min_analysts)
        if row is None:
            continue
        if direction == "over" and row.direction != "over":
            continue
        if direction == "under" and row.direction != "under":
            continue
        out.append(row)
    out.sort(key=lambda x: abs(x.delta_pct), reverse=True)
    if limit is not None and limit > 0:
        out = out[: int(limit)]
    return out


# ── DB-backed entry points ──────────────────────────────────────────


def _get_session():
    """Lazy import so unit tests can run without the analysis stack."""
    try:
        from backend.services.analysis_cache_service import _get_session as _s
        return _s()
    except Exception as exc:  # noqa: BLE001
        logger.warning("benchmark_reconciliation: no session: %s", exc)
        return None


def get_outliers(
    *,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    min_analysts: int = DEFAULT_MIN_ANALYSTS,
    direction: str = "both",
    limit: Optional[int] = 50,
    session=None,
) -> list[OutlierRow]:
    """Live admin dashboard query. Returns at most ``limit`` rows sorted
    by ``|delta_pct|`` desc. Empty list on any DB issue — admin UI
    renders "no outliers found" rather than a 500.
    """
    from sqlalchemy import text  # local import; keeps module importable in tests
    sess = session if session is not None else _get_session()
    if sess is None:
        return []
    try:
        rows = sess.execute(
            text(_OUTLIERS_SQL),
            {"min_analysts": min_analysts, "our_max_days": OUR_FV_MAX_AGE_DAYS},
        ).mappings().all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("benchmark_reconciliation.get_outliers SQL failed: %s", exc)
        return []
    finally:
        if session is None:
            try:
                sess.close()
            except Exception:
                pass
    return compute_outliers_from_records(
        [dict(r) for r in rows],
        threshold_pct=threshold_pct,
        min_analysts=min_analysts,
        direction=direction,
        limit=limit,
    )


def is_ticker_flagged(
    ticker: str,
    *,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    min_analysts: int = DEFAULT_MIN_ANALYSTS,
    session=None,
) -> CaveatInfo:
    """Per-request hook used by the analysis serializer.

    Returns a ``CaveatInfo`` with ``flagged=True`` iff this ticker is
    currently an outlier. Never raises — DB issues degrade silently to
    ``not_flagged`` so a transient outage cannot break the analysis
    response.
    """
    if not ticker:
        return CaveatInfo.not_flagged()
    from sqlalchemy import text
    sess = session if session is not None else _get_session()
    if sess is None:
        return CaveatInfo.not_flagged()
    try:
        row = sess.execute(
            text(_ONE_TICKER_SQL),
            {"ticker": ticker, "our_max_days": OUR_FV_MAX_AGE_DAYS},
        ).mappings().first()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "benchmark_reconciliation.is_ticker_flagged failed for %s: %s",
            ticker, exc,
        )
        return CaveatInfo.not_flagged()
    finally:
        if session is None:
            try:
                sess.close()
            except Exception:
                pass
    if row is None:
        return CaveatInfo.not_flagged()
    delta = _classify(
        row.get("our_fv"), row.get("consensus_fv"),
        row.get("analyst_count"), threshold_pct, min_analysts,
    )
    if delta is None:
        return CaveatInfo.not_flagged()
    return CaveatInfo(
        flagged=True,
        abs_delta_pct=int(round(abs(delta) * 100)),
        analyst_count=int(row["analyst_count"]),
        direction="over" if delta > 0 else "under",
    )


# ── User-facing caveat string ───────────────────────────────────────
#
# Centralized so the wording lives in one place. Per design §6.3,
# we expose the *abs* delta in whole-percent units and explicitly
# DO NOT include the consensus number or the direction. Phrasing
# was reviewed against the design doc before merge.

_CAVEAT_TEMPLATE = (
    "Our model fair value differs from current analyst consensus by "
    "~{pct}%; reasons may include sector engine gap, recent corporate "
    "action, or genuine model insight. Operator review pending."
)


def caveat_text(info: CaveatInfo) -> Optional[str]:
    """Build the user-facing caveat string from a CaveatInfo, or None
    if the ticker is not flagged. The returned string never reveals
    the consensus value or the direction of the disagreement."""
    if not info.flagged or info.abs_delta_pct is None:
        return None
    return _CAVEAT_TEMPLATE.format(pct=int(info.abs_delta_pct))
