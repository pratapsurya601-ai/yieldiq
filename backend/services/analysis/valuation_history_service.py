# backend/services/analysis/valuation_history_service.py
# ═══════════════════════════════════════════════════════════════
# Phase 1 — Fair-Value History data layer (Agent A).
#
# Owns the DB query that backs GET /api/valuation-history/{ticker}
# and the annotation logic that walks the FV series to surface
# material moves. Production-faithful only: every point is the FV a
# user would have seen on that date.
#
# Annotation tiering (driven by the FV series itself, not the
# manifest):
#
#   Tier 1 high           — manifest entry between prev.date and cur.date
#                           explicitly names cur.ticker in scope.tickers
#   Tier 2 inferred       — wildcard manifest entry whose scope.fields
#                           overlaps the FV input set
#   Tier 3 data_refresh   — no qualifying manifest entry; cause is upstream
#                           financials or price refresh
#
# Sparse-region annotations fall back to explicit-ticker manifest
# matches only. Day-over-day deltas require the write-hook series
# which starts on the first 'live' row written after the 076
# superset migration. The asymmetry is by design — do not fix it
# by reconstructing historical deltas.
#
# All hardcoded cause_label strings here are SEBI-clean. Manifest
# rationales inherit SEBI compliance from the cache-invalidation
# work.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import date as Date
from typing import Iterable

from backend.models.fair_value_history import (
    FairValueAnnotation,
    FairValueHistoryPoint,
)
from backend.services.analysis.constants import FV_ANNOTATION_THRESHOLD_PCT

log = logging.getLogger("yieldiq.valuation_history")


# Fields that, when listed in a wildcard manifest entry's scope.fields,
# indicate the change could plausibly have moved FV for any ticker.
# Mirrors the engine's FV input set without duplicating it.
_FV_INPUT_FIELDS: frozenset[str] = frozenset({
    "fair_value",
    "base_case",
    "scenarios",
    "scenarios.base",
    "scenarios.bear",
    "scenarios.bull",
    "valuation.wacc",
    "valuation.terminal_growth",
    "*",
})


_DEFAULT_DATA_REFRESH_LABEL = "Data refresh (financials or price input)"
_INFERRED_SUFFIX = " (inferred)"
_LEGACY_MODEL_VERSION = "legacy_pre_phase1"


# ── DB query ─────────────────────────────────────────────────────
async def _fetch_history(ticker: str) -> list[dict]:
    """Return rows ordered oldest-first. Aliases ``date`` to
    ``as_of_date`` is handled by the caller — we keep raw column names
    here for readability. Returns [] on any DB failure (never raises).
    """
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        log.debug("data_pipeline.db unavailable: %s", exc)
        return []
    if Session is None:
        return []

    from sqlalchemy import text

    sess = None
    try:
        sess = Session()
    except Exception as exc:
        log.debug("session open failed: %s", exc)
        return []

    sql = text(
        """
        SELECT
            date AS as_of_date,
            fair_value,
            bear_iv,
            bull_iv,
            scenario_weights,
            COALESCE(model_version, :legacy_tag) AS model_version,
            provenance,
            manifest_id
        FROM fair_value_history
        WHERE ticker IN (:t_bare, :t_ns)
        ORDER BY
            date ASC,
            CASE provenance
                WHEN 'live'     THEN 0
                WHEN 'snapshot' THEN 1
                WHEN 'golden'   THEN 2
                ELSE 3
            END
        """
    )
    bare = ticker.replace(".NS", "").replace(".BO", "")
    try:
        rows = sess.execute(
            sql,
            {
                "t_bare": bare,
                "t_ns": f"{bare}.NS",
                "legacy_tag": _LEGACY_MODEL_VERSION,
            },
        ).mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:
        log.debug("fair_value_history query failed for %s: %s", ticker, exc)
        return []
    finally:
        try:
            sess.close()
        except Exception:
            pass


def _row_to_point(row: dict) -> FairValueHistoryPoint:
    """Map a raw DB row to the locked Pydantic shape."""
    sw = row.get("scenario_weights")
    if sw is not None and not isinstance(sw, dict):
        # psycopg2 may return jsonb as str under some drivers.
        try:
            import json
            sw = json.loads(sw)
        except Exception:
            sw = None

    bear_iv = row.get("bear_iv")
    bull_iv = row.get("bull_iv")
    return FairValueHistoryPoint(
        date=row["as_of_date"],
        fair_value=float(row["fair_value"]),
        bear_iv=float(bear_iv) if bear_iv is not None else None,
        bull_iv=float(bull_iv) if bull_iv is not None else None,
        scenario_weights=sw if isinstance(sw, dict) else None,
        model_version=row.get("model_version") or _LEGACY_MODEL_VERSION,
        provenance=row["provenance"],
        manifest_id=row.get("manifest_id"),
    )


# ── Manifest helpers ─────────────────────────────────────────────
def _manifest_entries_between(
    prev_date: Date | None,
    cur_date: Date,
) -> list[dict]:
    """Return manifest entries whose applied_at falls in (prev_date, cur_date].

    When ``prev_date`` is None (sparse-region first point), we still
    return matching entries on cur_date itself so explicit-ticker
    matches can drive a high-tier annotation.
    """
    try:
        from backend.services.cache_invalidation_manifest import MANIFEST
    except Exception as exc:
        log.debug("manifest import failed: %s", exc)
        return []

    out: list[dict] = []
    for entry in MANIFEST:
        applied = entry.get("applied_at")
        if applied is None:
            continue
        try:
            applied_d = applied.date() if hasattr(applied, "date") else applied
        except Exception:
            continue
        if applied_d > cur_date:
            continue
        if prev_date is not None and applied_d <= prev_date:
            continue
        out.append(entry)
    return out


def _explicit_ticker_match(entry: dict, ticker: str) -> bool:
    """True iff entry scope.tickers is a list AND names ticker (bare)."""
    scope = entry.get("scope") or {}
    scoped = scope.get("tickers")
    if scoped == "*":
        return False  # wildcard handled by Tier 2
    if not isinstance(scoped, (list, tuple, set)):
        return False
    bare = ticker.replace(".NS", "").replace(".BO", "").upper()
    scoped_bare = {
        (t or "").replace(".NS", "").replace(".BO", "").upper()
        for t in scoped
    }
    return bare in scoped_bare


def _wildcard_fv_input_match(entry: dict) -> bool:
    """True iff entry is wildcard-ticker AND scope.fields overlaps FV inputs."""
    scope = entry.get("scope") or {}
    if scope.get("tickers") != "*":
        return False
    fields = scope.get("fields")
    if fields == "*":
        return True
    if not isinstance(fields, (list, tuple, set)):
        return False
    for f in fields:
        if f in _FV_INPUT_FIELDS:
            return True
        # Match prefix patterns like "scenarios.*" against our input set.
        if isinstance(f, str) and f.endswith(".*"):
            prefix = f[:-2]
            if any(p.startswith(prefix + ".") or p == prefix
                   for p in _FV_INPUT_FIELDS):
                return True
    return False


def _truncate_label(raw: str, suffix: str = "") -> str:
    """Truncate to 80 chars, appending suffix if room."""
    raw = (raw or "").strip()
    budget = 80 - len(suffix)
    if len(raw) > budget:
        raw = raw[: max(0, budget - 1)].rstrip() + "…"
    return raw + suffix


# ── Annotation emission ──────────────────────────────────────────
def _emit_annotations(
    ticker: str,
    points: list[FairValueHistoryPoint],
) -> list[FairValueAnnotation]:
    """Walk points pairwise; emit one annotation per material move.

    Sparse-region (no prev_fv) emits only Tier 1 (explicit-ticker
    manifest matches on the snapshot date). Day-over-day deltas
    require the write-hook series.
    """
    annotations: list[FairValueAnnotation] = []
    if not points:
        return annotations

    # Sparse-region pass for the very first point: only explicit-ticker.
    first = points[0]
    for entry in _manifest_entries_between(None, first.date):
        if _explicit_ticker_match(entry, ticker):
            annotations.append(
                FairValueAnnotation(
                    date=first.date,
                    fv_delta_pct=0.0,
                    manifest_id=entry.get("version_id"),
                    cause_label=_truncate_label(entry.get("rationale", "")),
                    confidence="high",
                )
            )
            break  # one annotation per snapshot date

    # Pairwise pass for material deltas.
    for prev, cur in zip(points, points[1:]):
        if prev.fair_value == 0:
            continue
        try:
            delta_pct = (cur.fair_value - prev.fair_value) / prev.fair_value * 100.0
        except Exception:
            continue
        if abs(delta_pct) < FV_ANNOTATION_THRESHOLD_PCT:
            continue

        entries = _manifest_entries_between(prev.date, cur.date)

        # Tier 1: explicit-ticker manifest entry.
        tier1 = next(
            (e for e in entries if _explicit_ticker_match(e, ticker)),
            None,
        )
        if tier1 is not None:
            annotations.append(
                FairValueAnnotation(
                    date=cur.date,
                    fv_delta_pct=round(delta_pct, 2),
                    manifest_id=tier1.get("version_id"),
                    cause_label=_truncate_label(tier1.get("rationale", "")),
                    confidence="high",
                )
            )
            continue

        # Tier 2: wildcard FV-input manifest entry.
        tier2 = next(
            (e for e in entries if _wildcard_fv_input_match(e)),
            None,
        )
        if tier2 is not None:
            annotations.append(
                FairValueAnnotation(
                    date=cur.date,
                    fv_delta_pct=round(delta_pct, 2),
                    manifest_id=tier2.get("version_id"),
                    cause_label=_truncate_label(
                        tier2.get("rationale", ""), _INFERRED_SUFFIX
                    ),
                    confidence="inferred",
                )
            )
            continue

        # Tier 3: data refresh.
        annotations.append(
            FairValueAnnotation(
                date=cur.date,
                fv_delta_pct=round(delta_pct, 2),
                manifest_id=None,
                cause_label=_DEFAULT_DATA_REFRESH_LABEL,
                confidence="data_refresh",
            )
        )

    return annotations


# ── Public entry ─────────────────────────────────────────────────
async def fetch_history_payload(ticker: str):
    """Compose the full /api/valuation-history payload for one ticker.

    Returns the Pydantic response model. Never raises — returns the
    empty-shape on any internal failure so the router stays a stable
    contract.
    """
    from backend.models.fair_value_history import FairValueHistoryResponse

    ticker_upper = ticker.upper().strip()
    rows = await _fetch_history(ticker_upper)
    try:
        points = [_row_to_point(r) for r in rows]
    except Exception as exc:
        log.warning("row mapping failed for %s: %s", ticker_upper, exc)
        points = []
    annotations = _emit_annotations(ticker_upper, points)
    return FairValueHistoryResponse(
        ticker=ticker_upper,
        points=points,
        annotations=annotations,
        starts_at=points[0].date if points else None,
        points_count=len(points),
        is_sparse=len(points) < 3,
    )
