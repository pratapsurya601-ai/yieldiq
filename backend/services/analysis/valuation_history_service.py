# backend/services/analysis/valuation_history_service.py
# ═══════════════════════════════════════════════════════════════
# Premium Feel R3 — Valuation-History backtest aggregator.
#
# Reads fair_value_history rows for a single ticker and computes
# descriptive calibration statistics over the last N months.
#
# CONTRACT (this PR introduces no engine change):
#   * Read-only aggregate over the existing fair_value_history table.
#   * No DCF / valuation engine output is recomputed or modified.
#   * No returned valuation field can change as a result of this module.
#   * canary-diff cannot move because no engine output changes.
#
# SEBI discipline:
#   * Statistics are descriptive of past model behavior.
#   * Hypothetical "signal event" framing only — "if a position had
#     been opened when the model flagged a discount of ≥ threshold,
#     calendar-days-to-touch fair-value was N (median)".
#   * The caller (frontend) attaches an explicit "past calibration is
#     a description of model behavior, not a forecast" footnote.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import date as Date, timedelta
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("yieldiq.valuation_history_service")


# ── Tunables (locked by this PR; bump only with a sibling test) ─────
#
# DEFAULT_WINDOW_MONTHS: 60 months matches the AlphaSpread "Valuation
# History" surface; we cap to the actual data extent for younger
# tickers (fair_value_history was bootstrapped on 2026-05-22).
DEFAULT_WINDOW_MONTHS: int = 60

# A "signal event" is a date on which `price <= fair_value * (1 - X)`.
# 0.20 = 20% discount. Matches the MoS-entry chip the user already
# sees elsewhere on the analysis page; consistent UI.
SIGNAL_THRESHOLD_PCT: float = 20.0

# Crossings are de-duplicated within this many days so a noisy week
# doesn't inflate the count.
EVENT_DEDUP_DAYS: int = 30

# Holding-period cap. Hypothetical exit when price re-touches the
# model's fair-value estimate, or after this many days, whichever
# comes first.
HOLDING_CAP_DAYS: int = 365

# Minimum observations to compute calibration stats. Below this we
# return stats=None and surface the count in caveats.
MIN_OBSERVATIONS_FOR_STATS: int = 12


@dataclass(frozen=True)
class _Row:
    """Internal projection of one fair_value_history row."""

    date: Date
    price: float
    fair_value: float


def _fetch_rows(
    db: Session,
    ticker: str,
    *,
    months: int,
) -> tuple[list[_Row], int]:
    """Load (date, price, fair_value) for the served slice.

    Returns (rows, n_quarantined_excluded). Rows are ordered ascending
    by date. Quarantined rows (`quarantine_reason IS NOT NULL`) are
    excluded — they are by-construction not chartable historical
    anchors (see migration 202606031123).

    A second `quarantine_reason` query gives us the count for the
    caveat string. Low-cost — partial-index served-slice is small.
    """
    bare_candidates = _ticker_candidates(ticker)
    cutoff = Date.today() - timedelta(days=months * 31)

    served_sql = text(
        """
        SELECT date, price, fair_value
        FROM fair_value_history
        WHERE ticker = ANY(:tickers)
          AND date >= :cutoff
          AND quarantine_reason IS NULL
          AND fair_value > 0
          AND price > 0
        ORDER BY date ASC
        """
    )
    quarantine_sql = text(
        """
        SELECT COUNT(*) AS n
        FROM fair_value_history
        WHERE ticker = ANY(:tickers)
          AND date >= :cutoff
          AND quarantine_reason IS NOT NULL
        """
    )

    rows_raw = db.execute(
        served_sql,
        {"tickers": bare_candidates, "cutoff": cutoff},
    ).fetchall()
    rows = [
        _Row(date=r[0], price=float(r[1]), fair_value=float(r[2]))
        for r in rows_raw
    ]
    n_quar = int(
        db.execute(
            quarantine_sql,
            {"tickers": bare_candidates, "cutoff": cutoff},
        ).scalar()
        or 0
    )
    return rows, n_quar


def _ticker_candidates(ticker: str) -> list[str]:
    """Match either ``RELIANCE`` or ``RELIANCE.NS`` style stored values.

    fair_value_history historically accepted both forms (the migration
    coalesced future writes to the canonical form but legacy rows are
    mixed). Query against both candidates so we serve the full series.
    """
    upper = ticker.strip().upper()
    bare = upper.replace(".NS", "").replace(".BO", "")
    return [upper, bare, f"{bare}.NS", f"{bare}.BO"]


def _deviation_pct(price: float, fair_value: float) -> float:
    """Signed deviation in percent: (price - fv) / fv * 100."""
    if fair_value == 0:
        return 0.0
    return (price - fair_value) / fair_value * 100.0


def _abs_error_pct(price: float, fair_value: float) -> float:
    """|price - fv| / fv * 100 — calibration metric."""
    if fair_value == 0:
        return 0.0
    return abs(price - fair_value) / fair_value * 100.0


def _find_signal_events(
    rows: list[_Row],
    *,
    threshold_pct: float,
    dedup_days: int,
) -> list[int]:
    """Indexes into `rows` where the discount threshold was crossed.

    A "crossing" is a row where deviation ≤ -threshold_pct AND the
    previous row had deviation > -threshold_pct. Within a
    `dedup_days` window of a previous event we suppress further
    triggers so a noisy week of consecutive sub-threshold prints
    counts once.

    Returns the list of triggering row indexes in ascending order.
    """
    if not rows:
        return []
    out: list[int] = []
    last_event_date: Optional[Date] = None
    prev_dev: Optional[float] = None
    for i, r in enumerate(rows):
        dev = _deviation_pct(r.price, r.fair_value)
        crossed = dev <= -threshold_pct and (prev_dev is None or prev_dev > -threshold_pct)
        if crossed:
            if last_event_date is None or (r.date - last_event_date).days >= dedup_days:
                out.append(i)
                last_event_date = r.date
        prev_dev = dev
    return out


def _holding_outcome(
    rows: list[_Row],
    entry_idx: int,
    *,
    cap_days: int,
) -> tuple[Optional[int], Optional[float]]:
    """Compute (days_to_exit, realized_pct) for one event.

    Exit fires when price re-touches the model fair-value estimate
    (price >= fair_value) OR `cap_days` elapse, whichever first. The
    realized % is exit_price / entry_price - 1, expressed as a percent.

    Returns (None, None) when no exit fired within `cap_days` AND we
    have no more data — the event is incomplete and excluded from
    medians.
    """
    if entry_idx >= len(rows):
        return None, None
    entry = rows[entry_idx]
    deadline = entry.date + timedelta(days=cap_days)
    for j in range(entry_idx + 1, len(rows)):
        r = rows[j]
        if r.date > deadline:
            # Time-cap exit at the deadline.
            days = cap_days
            realized = (r.price - entry.price) / entry.price * 100.0
            return days, realized
        if r.price >= r.fair_value:
            days = (r.date - entry.date).days
            realized = (r.price - entry.price) / entry.price * 100.0
            return days, realized
    # Reached the end of available data without an exit or deadline.
    return None, None


def _percentile(values: Iterable[float], pct: float) -> float:
    """Quick non-interpolated percentile. `pct` in 0..100."""
    s = sorted(values)
    if not s:
        return 0.0
    if len(s) == 1:
        return s[0]
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


def compute_valuation_history(
    db: Session,
    ticker: str,
    *,
    window_months: int = DEFAULT_WINDOW_MONTHS,
) -> dict:
    """Build the `ValuationHistoryResponse`-shaped payload.

    Returns a plain dict; the FastAPI route serializes through the
    Pydantic model so any drift surfaces as a 500.

    Empty/sparse cases follow the contract: if fewer than
    MIN_OBSERVATIONS_FOR_STATS rows survive the quarantine filter,
    `stats` is None and a single caveat names the deficit.
    """
    ticker_norm = ticker.strip().upper()
    rows, n_quar = _fetch_rows(db, ticker_norm, months=window_months)

    today = Date.today()
    # Snap window_months to actual extent for the response so the UI
    # caption never claims more history than we have.
    extent_months = (
        max(1, round((today - rows[0].date).days / 30.4375)) if rows else window_months
    )
    window_actual = min(window_months, extent_months) if rows else 0

    series = [
        {
            "date": r.date,
            "price": round(r.price, 2),
            "fair_value": round(r.fair_value, 2),
            "deviation_pct": round(_deviation_pct(r.price, r.fair_value), 2),
        }
        for r in rows
    ]

    caveats: list[str] = []
    if rows:
        caveats.append(f"N={len(rows)} observations over {window_actual} months.")
    if n_quar > 0:
        caveats.append(f"Excluded {n_quar} quarantined observation(s).")

    n_obs = len(rows)
    if n_obs < MIN_OBSERVATIONS_FOR_STATS:
        if n_obs == 0:
            caveats.insert(
                0,
                "No fair-value history on record yet. History accumulates after each daily analysis.",
            )
        else:
            caveats.insert(
                0,
                (
                    f"Insufficient history — {n_obs} observation(s); calibration "
                    f"stats need at least {MIN_OBSERVATIONS_FOR_STATS} months."
                ),
            )
        return {
            "ticker": ticker_norm,
            "as_of": today,
            "history_window_months": window_actual,
            "series": series,
            "stats": None,
            "caveats": caveats,
        }

    # ── Calibration statistics ────────────────────────────────────
    abs_errors = [_abs_error_pct(r.price, r.fair_value) for r in rows]
    deviations = [_deviation_pct(r.price, r.fair_value) for r in rows]
    median_abs_error = float(statistics.median(abs_errors))
    pct_within_10 = sum(1 for d in deviations if abs(d) <= 10) / n_obs
    pct_within_20 = sum(1 for d in deviations if abs(d) <= 20) / n_obs

    # ── Hypothetical signal-event accounting ──────────────────────
    event_idxs = _find_signal_events(
        rows,
        threshold_pct=SIGNAL_THRESHOLD_PCT,
        dedup_days=EVENT_DEDUP_DAYS,
    )
    holding_days: list[int] = []
    realized_pcts: list[float] = []
    for idx in event_idxs:
        days, realized = _holding_outcome(rows, idx, cap_days=HOLDING_CAP_DAYS)
        if days is not None and realized is not None:
            holding_days.append(days)
            realized_pcts.append(realized)

    median_hold = int(statistics.median(holding_days)) if holding_days else None
    median_realized = (
        round(float(statistics.median(realized_pcts)), 2) if realized_pcts else None
    )

    stats_payload = {
        "n_observations": n_obs,
        "n_signal_events": len(event_idxs),
        "signal_threshold_pct": SIGNAL_THRESHOLD_PCT,
        "median_holding_days": median_hold,
        "median_realized_pct": median_realized,
        "median_abs_error_pct": round(median_abs_error, 2),
        "pct_within_10": round(pct_within_10, 4),
        "pct_within_20": round(pct_within_20, 4),
    }

    return {
        "ticker": ticker_norm,
        "as_of": today,
        "history_window_months": window_actual,
        "series": series,
        "stats": stats_payload,
        "caveats": caveats,
    }
