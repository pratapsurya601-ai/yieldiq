# backend/services/fair_value_history_writer.py
# ═══════════════════════════════════════════════════════════════
# Fair-value-history WRITE-TIME sanity gate (ROOT CAUSE #12 —
# 2026-06-11).
#
# Sibling to ``backend/services/fair_value_history_gate.py``, which
# runs on the READ path. This module runs on the WRITE path:
# ``data_pipeline/sources/fv_history.py::store_today_fair_value``
# calls into ``should_persist_fv_row`` BEFORE the upsert. If the
# gate rejects the row, the writer routes it to
# ``fair_value_history_quarantine`` instead of polluting the
# canonical table.
#
# Why both?
#   * The read gate handles the pre-existing fossil layer (rows
#     written before this gate existed; the 2026-05-17 IT cohort
#     anomaly etc.). It is conservative and read-only by design.
#   * The write gate stops new anomalies at the door. The
#     HDFCBANK 2026-04-30 single-day +106.5 % FV revision visible
#     on the prod chart is exactly the class of write this gate
#     would have rejected.
#
# Decision logic
#   1. If we have no prior row for this ticker → ALWAYS persist.
#      First rows have nothing to compare against; the read gate
#      will catch them later if they end up implausible vs the
#      subsequent series.
#   2. Compute |Δ| as a fraction of the previous fair_value. If
#      |Δ| <= MAX_DAILY_FV_DELTA_PCT (default 25 %) → persist.
#   3. If |Δ| > MAX_DAILY_FV_DELTA_PCT, require CORROBORATION:
#      a) a cache_invalidation_manifest entry within ±MANIFEST_
#         WINDOW_DAYS dated covering this ticker (or "*"), OR
#      b) a corporate_actions row for this ticker dated on the
#         write date (earnings / dividend / M&A / split), OR
#      c) a concall_ai_summary row whose
#         ``concall_date`` matches the write date — treated as
#         "guidance change landed today".
#   4. If corroborated → persist with a ``corroboration`` reason
#      attached. If not → route to quarantine.
#
# The gate NEVER raises. The caller already wraps the write hook
# in try/except — keeping that contract intact.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as Date, datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger("yieldiq.fair_value_history_writer")

# Tuning knobs — exposed so tests + admin endpoint can import.
MAX_DAILY_FV_DELTA_PCT = 25.0
MANIFEST_WINDOW_DAYS = 3


@dataclass
class WriteGateDecision:
    """Result of `should_persist_fv_row`.

    Caller pattern:
        decision = should_persist_fv_row(...)
        if decision.persist:
            ... write to fair_value_history ...
        else:
            ... write to fair_value_history_quarantine with
                decision.reason as the audit note ...
    """
    persist: bool
    reason: str
    delta_pct: Optional[float] = None
    prev_fv: Optional[float] = None
    corroboration: Optional[str] = None


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _compute_delta_pct(today_fv: float, prev_fv: float) -> float:
    """Return |today - prev| / prev * 100. Caller guarantees prev > 0."""
    return abs(today_fv - prev_fv) / prev_fv * 100.0


def _matches_ticker(scope_tickers: Any, ticker: str) -> bool:
    """Match the manifest ``scope.tickers`` field against a ticker.

    Accepts:
      - "*"  (wildcard — matches everything)
      - a single ticker string (case-insensitive)
      - a list/tuple of ticker strings
    """
    if scope_tickers is None:
        return False
    if isinstance(scope_tickers, str):
        if scope_tickers.strip() == "*":
            return True
        return scope_tickers.strip().upper() == ticker.upper()
    if isinstance(scope_tickers, (list, tuple, set)):
        u = ticker.upper()
        for t in scope_tickers:
            if isinstance(t, str) and (t.strip() == "*" or t.strip().upper() == u):
                return True
    return False


def _coerce_to_date(v: Any) -> Date | None:
    if v is None:
        return None
    if isinstance(v, Date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(v[: len(fmt) + 5], fmt).date()
            except (ValueError, TypeError):
                continue
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
        except Exception:
            return None
    return None


def manifest_corroborates(
    manifest_entries: list[dict],
    *,
    ticker: str,
    write_date: Date,
    window_days: int = MANIFEST_WINDOW_DAYS,
) -> Optional[str]:
    """Return the version_id of the corroborating manifest entry, or None.

    A manifest entry corroborates the write when:
      - its ``applied_at`` is within ±window_days of write_date, AND
      - its ``scope.tickers`` matches this ticker (or is "*").

    Pure function — exposed for direct test invocation.
    """
    if not manifest_entries:
        return None
    lo = write_date - timedelta(days=window_days)
    hi = write_date + timedelta(days=window_days)
    for entry in manifest_entries:
        if not isinstance(entry, dict):
            continue
        applied = _coerce_to_date(entry.get("applied_at"))
        if applied is None:
            continue
        if applied < lo or applied > hi:
            continue
        scope = entry.get("scope") or {}
        if not isinstance(scope, dict):
            continue
        if _matches_ticker(scope.get("tickers"), ticker):
            return str(entry.get("version_id") or "<unknown>")
    return None


def _corporate_actions_corroborates(
    db_session: Any, *, ticker: str, write_date: Date,
) -> Optional[str]:
    """Return a short label describing the corporate-action on
    write_date for ticker, or None.

    Looks up the existing ``corporate_actions`` table. Tolerant —
    if the table is missing or the query errors out we return None
    and let the gate quarantine.
    """
    if db_session is None:
        return None
    try:
        from sqlalchemy import text
        row = db_session.execute(
            text(
                """
                SELECT action_type, COALESCE(symbol, ticker, '') AS sym,
                       ex_date
                FROM corporate_actions
                WHERE COALESCE(symbol, ticker, '') IN (:bare, :ns, :bo)
                  AND (ex_date = :d OR record_date = :d)
                ORDER BY ex_date DESC NULLS LAST
                LIMIT 1
                """
            ),
            {
                "bare": ticker,
                "ns": f"{ticker}.NS",
                "bo": f"{ticker}.BO",
                "d": write_date,
            },
        ).fetchone()
    except Exception as exc:
        logger.debug(
            "fv_writer: corporate_actions lookup failed for %s: %s",
            ticker, exc,
        )
        return None
    if not row:
        return None
    try:
        act = str(row[0]) if row[0] else "corporate_action"
    except Exception:
        act = "corporate_action"
    return f"corporate_actions:{act}"


def _concall_summary_corroborates(
    db_session: Any, *, ticker: str, write_date: Date,
) -> Optional[str]:
    """Return a label if a concall_ai_summary lands on write_date.

    Treated as "guidance change landed today". Defensive — the
    table may not exist on older schema; we swallow errors.
    """
    if db_session is None:
        return None
    try:
        from sqlalchemy import text
        row = db_session.execute(
            text(
                """
                SELECT 1
                FROM concall_ai_summary
                WHERE ticker IN (:bare, :ns, :bo)
                  AND DATE(COALESCE(concall_date, generated_at)) = :d
                LIMIT 1
                """
            ),
            {
                "bare": ticker,
                "ns": f"{ticker}.NS",
                "bo": f"{ticker}.BO",
                "d": write_date,
            },
        ).fetchone()
    except Exception as exc:
        logger.debug(
            "fv_writer: concall_ai_summary lookup failed for %s: %s",
            ticker, exc,
        )
        return None
    if row:
        return "concall_ai_summary:guidance_change"
    return None


def should_persist_fv_row(
    *,
    ticker: str,
    today_fv: float,
    prev_fv: float | None,
    write_date: Date,
    manifest_entries: list[dict] | None = None,
    db_session: Any | None = None,
    max_delta_pct: float = MAX_DAILY_FV_DELTA_PCT,
) -> WriteGateDecision:
    """Decide whether the row should land in fair_value_history.

    Args:
        ticker: bare ticker (RELIANCE, not RELIANCE.NS).
        today_fv: the new fair_value about to be persisted.
        prev_fv: previous day's fair_value, or None if no prior row.
        write_date: the date the row would carry.
        manifest_entries: the in-memory MANIFEST list (caller passes
            ``cache_invalidation_manifest.MANIFEST``).
        db_session: optional SQLAlchemy session — used for
            corporate-actions and concall corroboration lookups.
            None disables those lookups (treated as no corroboration).
        max_delta_pct: override the 25 % default (tests use this).

    Returns:
        WriteGateDecision. Caller treats persist=True as "go ahead"
        and persist=False as "send to quarantine".
    """
    today_fv_f = _safe_float(today_fv)
    prev_fv_f = _safe_float(prev_fv) if prev_fv is not None else None
    if today_fv_f is None or today_fv_f <= 0:
        return WriteGateDecision(
            persist=False,
            reason="degenerate_input: today_fv is None / <= 0",
        )
    if prev_fv_f is None or prev_fv_f <= 0:
        # First row for this ticker; nothing to compare against.
        return WriteGateDecision(
            persist=True,
            reason="first_row_for_ticker",
            prev_fv=None,
        )

    delta_pct = _compute_delta_pct(today_fv_f, prev_fv_f)
    if delta_pct <= max_delta_pct:
        return WriteGateDecision(
            persist=True,
            reason="within_daily_delta_band",
            delta_pct=delta_pct,
            prev_fv=prev_fv_f,
        )

    # Hot path — large daily delta. Try each corroboration source.
    manifest_hit = manifest_corroborates(
        manifest_entries or [], ticker=ticker, write_date=write_date,
    )
    if manifest_hit:
        return WriteGateDecision(
            persist=True,
            reason="corroborated_by_manifest",
            delta_pct=delta_pct,
            prev_fv=prev_fv_f,
            corroboration=manifest_hit,
        )
    ca_hit = _corporate_actions_corroborates(
        db_session, ticker=ticker, write_date=write_date,
    )
    if ca_hit:
        return WriteGateDecision(
            persist=True,
            reason="corroborated_by_corporate_action",
            delta_pct=delta_pct,
            prev_fv=prev_fv_f,
            corroboration=ca_hit,
        )
    concall_hit = _concall_summary_corroborates(
        db_session, ticker=ticker, write_date=write_date,
    )
    if concall_hit:
        return WriteGateDecision(
            persist=True,
            reason="corroborated_by_concall",
            delta_pct=delta_pct,
            prev_fv=prev_fv_f,
            corroboration=concall_hit,
        )

    return WriteGateDecision(
        persist=False,
        reason=(
            f"uncorroborated_large_delta: {delta_pct:.2f}% > "
            f"{max_delta_pct:.1f}% with no manifest / corporate "
            f"action / concall on {write_date.isoformat()}"
        ),
        delta_pct=delta_pct,
        prev_fv=prev_fv_f,
    )


# ── DB-side quarantine helpers ───────────────────────────────────
#
# The quarantine table is created out-of-band (operator migration);
# this module is tolerant of its absence and DOES NOT create it on
# the fly. When the table is missing, quarantine writes log at WARN
# and the gate still returns persist=False so the calling code can
# decide whether to retry or drop.

QUARANTINE_TABLE = "fair_value_history_quarantine"


def insert_into_quarantine(
    db_session: Any,
    *,
    ticker: str,
    write_date: Date,
    today_fv: float,
    prev_fv: float | None,
    decision: WriteGateDecision,
    price: float | None = None,
    mos_pct: float | None = None,
    verdict: str | None = None,
) -> bool:
    """Persist the rejected row to fair_value_history_quarantine.

    Best-effort. Returns True on success, False on absent table /
    DB error. Never raises. The schema expected:

        ticker TEXT, date DATE, fair_value NUMERIC, prev_fv NUMERIC,
        delta_pct NUMERIC, reason TEXT, price NUMERIC, mos_pct NUMERIC,
        verdict TEXT, created_at TIMESTAMPTZ DEFAULT now()
    """
    if db_session is None:
        return False
    try:
        from sqlalchemy import text
        db_session.execute(
            text(
                f"""
                INSERT INTO {QUARANTINE_TABLE} (
                    ticker, date, fair_value, prev_fv,
                    delta_pct, reason, price, mos_pct, verdict,
                    created_at
                ) VALUES (
                    :ticker, :d, :fv, :pfv,
                    :delta, :reason, :px, :mos, :verdict,
                    now()
                )
                ON CONFLICT (ticker, date) DO UPDATE SET
                    fair_value = EXCLUDED.fair_value,
                    prev_fv    = EXCLUDED.prev_fv,
                    delta_pct  = EXCLUDED.delta_pct,
                    reason     = EXCLUDED.reason,
                    price      = EXCLUDED.price,
                    mos_pct    = EXCLUDED.mos_pct,
                    verdict    = EXCLUDED.verdict
                """
            ),
            {
                "ticker": ticker,
                "d": write_date,
                "fv": today_fv,
                "pfv": prev_fv,
                "delta": decision.delta_pct,
                "reason": decision.reason,
                "px": price,
                "mos": mos_pct,
                "verdict": verdict,
            },
        )
        db_session.commit()
        logger.warning(
            "fv_writer: quarantined %s @ %s — %s (delta=%.2f%%, fv %.2f -> %.2f)",
            ticker, write_date.isoformat(), decision.reason,
            decision.delta_pct or 0.0,
            decision.prev_fv or 0.0, today_fv,
        )
        return True
    except Exception as exc:
        logger.warning(
            "fv_writer: quarantine insert failed for %s @ %s: %s",
            ticker, write_date.isoformat(), exc,
        )
        try:
            db_session.rollback()
        except Exception:
            pass
        return False
