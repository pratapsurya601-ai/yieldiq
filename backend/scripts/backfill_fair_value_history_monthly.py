"""
backfill_fair_value_history_monthly.py
═══════════════════════════════════════════════════════════════

One-shot / monthly backfill that seeds ``fair_value_history`` with
*monthly* rows (one per ticker per calendar month) reaching back up
to ``--months`` months. This is the data source for the 12-month
score sparkline on the analysis page (``backend.services.prism_service
._score_history_12m``), and for the 52-week-low / lowest-P/E rails.

Why this exists
───────────────
Historically ``fair_value_history`` has been populated only by the
live analysis hot path (``store_today_fair_value``), which writes
one row per ticker per *day* — and only for the handful of tickers
a user actually opened. The visible symptom: every Nifty-50 stock's
12-month sparkline showed **"Insufficient history"** because the
month-bucket collapse in ``_score_history_12m`` turned 14 same-month
rows into a single bucket (< 2 → empty).

This script closes the gap. For each target ticker it:
  1. Reads today's fair_value from ``analysis_cache`` (the live,
     stable anchor).
  2. Walks back ``--months`` calendar months; picks the last trading
     day's ``close_price`` from ``daily_prices`` as that month's
     reference price.
  3. Computes ``mos_pct = (fv_today - close_month) / close_month * 100``
     as a best-effort historical MoS. This is an *approximation* —
     fair value isn't literally constant through time — but it
     captures the price contribution to MoS, which is what the
     sparkline is meant to visualise. (Same approximation family
     as ``hex_history_service._compute_value_axis``.)
  4. Upserts one row per (ticker, first-of-month) into
     ``fair_value_history``. Idempotent — ``ON CONFLICT (ticker, date)
     DO UPDATE`` so re-runs refine values rather than duplicating rows.

Never runs at request time on Railway. Invoked by
``.github/workflows/fair_value_history_monthly.yml`` (monthly cron +
manual dispatch).

Usage
─────
    python backend/scripts/backfill_fair_value_history_monthly.py \\
        [--limit 500] [--months 14] [--throttle 0.02]
    python backend/scripts/backfill_fair_value_history_monthly.py \\
        --ticker RELIANCE --months 14

Exit 0 on success (even if per-ticker writes failed — tolerant).
Exit 1 only if DB is unreachable or zero tickers could be loaded.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=os.environ.get("BACKFILL_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("backfill_fv_history_monthly")


# ── DB plumbing ───────────────────────────────────────────────────
def _get_session():
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        log.error("cannot import data_pipeline.db: %s", exc)
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception as exc:
        log.error("cannot open session: %s", exc)
        return None


# ── Target ticker loading ────────────────────────────────────────
def _load_top_tickers(sess, limit: int) -> list[str]:
    """Top-N by market cap. Returns *bare* tickers (no .NS) because
    daily_prices, stocks, and fair_value_history all store bare."""
    from sqlalchemy import text
    try:
        rows = sess.execute(
            text(
                """
                SELECT ticker FROM (
                    SELECT DISTINCT ON (ticker) ticker, market_cap_cr
                    FROM market_metrics
                    WHERE market_cap_cr IS NOT NULL AND market_cap_cr > 0
                    ORDER BY ticker, trade_date DESC
                ) t
                ORDER BY market_cap_cr DESC
                LIMIT :lim
                """
            ),
            {"lim": limit},
        ).fetchall()
    except Exception as exc:
        log.error("load_top_tickers failed: %s", exc)
        return []
    out: list[str] = []
    for r in rows:
        t = (r[0] or "").strip()
        if not t:
            continue
        # Store bare — daily_prices uses bare; fair_value_history accepts
        # both but the reader (prism_service._score_history_12m) queries
        # BOTH forms, so either write form works for it. We pick bare to
        # match daily_prices and avoid double-write drift.
        if t.endswith(".NS") or t.endswith(".BO"):
            t = t.rsplit(".", 1)[0]
        out.append(t)
    return out


# ── Price + FV lookups ───────────────────────────────────────────
def _month_starts(n_months: int, today: date | None = None) -> list[date]:
    """Return the first-of-month dates for the last n_months calendar
    months, oldest first, ending with the current month."""
    today = today or date.today()
    out: list[date] = []
    y, m = today.year, today.month
    for _ in range(n_months):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(out))


def _fetch_current_fv(sess, bare_ticker: str) -> float | None:
    """Pull today's fair_value from analysis_cache (preferred) or the
    most-recent fair_value_history row (fallback)."""
    from sqlalchemy import text
    # Prefer analysis_cache (canonical form uses .NS suffix).
    for form in (f"{bare_ticker}.NS", bare_ticker):
        try:
            row = sess.execute(
                text("SELECT payload FROM analysis_cache WHERE ticker = :t"),
                {"t": form},
            ).fetchone()
        except Exception:
            row = None
        if not row or row[0] is None:
            continue
        payload = row[0]
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        if isinstance(payload, dict):
            val = payload.get("valuation") or {}
            if isinstance(val, dict):
                fv = val.get("fair_value")
                try:
                    f = float(fv)
                    if f > 0:
                        return f
                except (TypeError, ValueError):
                    pass

    # Fallback — most recent fair_value_history row.
    try:
        row = sess.execute(
            text(
                """
                SELECT fair_value FROM fair_value_history
                WHERE ticker IN (:a, :b) AND fair_value IS NOT NULL
                ORDER BY date DESC LIMIT 1
                """
            ),
            {"a": bare_ticker, "b": f"{bare_ticker}.NS"},
        ).fetchone()
    except Exception:
        row = None
    if row and row[0] is not None:
        try:
            f = float(row[0])
            if f > 0:
                return f
        except (TypeError, ValueError):
            pass
    return None


def _fetch_monthly_closes(sess, bare_ticker: str, months: list[date]
                          ) -> dict[date, tuple[date, float]]:
    """For each month-start date in ``months``, return the last-trading-day
    close_price within that month. Result: {month_start: (trade_date, close)}.
    """
    from sqlalchemy import text
    if not months:
        return {}
    start = months[0]
    end = date(months[-1].year + (1 if months[-1].month == 12 else 0),
               (months[-1].month % 12) + 1, 1)
    try:
        rows = sess.execute(
            text(
                """
                SELECT trade_date, close_price
                FROM daily_prices
                WHERE ticker IN (:a, :b)
                  AND trade_date >= :start AND trade_date < :end
                  AND close_price IS NOT NULL
                ORDER BY trade_date ASC
                """
            ),
            {"a": bare_ticker, "b": f"{bare_ticker}.NS",
             "start": start, "end": end},
        ).fetchall()
    except Exception as exc:
        log.debug("monthly_closes query failed for %s: %s", bare_ticker, exc)
        return {}

    # Keep the LAST close within each (year, month).
    last_of_month: dict[tuple[int, int], tuple[date, float]] = {}
    for r in rows:
        d, c = r[0], r[1]
        if d is None or c is None:
            continue
        try:
            key = (d.year, d.month)
            last_of_month[key] = (d, float(c))
        except Exception:
            continue

    out: dict[date, tuple[date, float]] = {}
    for ms in months:
        v = last_of_month.get((ms.year, ms.month))
        if v is not None:
            out[ms] = v
    return out


# ── Upsert ────────────────────────────────────────────────────────
def _upsert_rows(sess, bare_ticker: str, fv_today: float,
                 monthly_closes: dict[date, tuple[date, float]]) -> int:
    """Upsert one fair_value_history row per month for this ticker.

    We write the row dated at the actual last-trading-day of the month
    (not the 1st) so it blends cleanly with daily rows already present
    for the current month. The primary key is (ticker, date); same-day
    rewrites are idempotent via ON CONFLICT UPDATE.
    """
    from sqlalchemy import text
    if fv_today <= 0 or not monthly_closes:
        return 0
    written = 0
    for ms, (trade_dt, close_px) in monthly_closes.items():
        if close_px <= 0:
            continue
        try:
            mos_pct = round((fv_today - close_px) / close_px * 100.0, 2)
        except Exception:
            continue
        # Clamp extreme values — matches downstream display-side clamp.
        if mos_pct > 200 or mos_pct < -90:
            # Still insert, but clamp so month buckets don't pull the
            # sparkline off-canvas. Mirrors prism_service's clamp band.
            mos_pct = max(-90.0, min(200.0, mos_pct))
        try:
            sess.execute(
                text(
                    """
                    INSERT INTO fair_value_history
                        (ticker, date, fair_value, price, mos_pct,
                         verdict, wacc, confidence, updated_at)
                    VALUES
                        (:ticker, :d, :fv, :price, :mos,
                         :verdict, NULL, :conf, now())
                    ON CONFLICT (ticker, date) DO UPDATE SET
                        fair_value = EXCLUDED.fair_value,
                        price      = EXCLUDED.price,
                        mos_pct    = EXCLUDED.mos_pct,
                        verdict    = EXCLUDED.verdict,
                        updated_at = now()
                    """
                ),
                {
                    "ticker": bare_ticker,
                    "d": trade_dt,
                    "fv": round(fv_today, 2),
                    "price": round(close_px, 2),
                    "mos": mos_pct,
                    "verdict": (
                        "undervalued" if mos_pct > 10
                        else "fairly_valued" if mos_pct > -10
                        else "overvalued"
                    ),
                    "conf": 40,  # Historical synthesis — lower confidence
                },
            )
            written += 1
        except Exception as exc:
            log.debug("upsert failed %s @ %s: %s", bare_ticker, trade_dt, exc)
            try:
                sess.rollback()
            except Exception:
                pass
            # After a rollback the session may be in a broken state for
            # Postgres; re-open for the next ticker rather than limping.
            return written
    try:
        sess.commit()
    except Exception:
        try:
            sess.rollback()
        except Exception:
            pass
    return written


def _process_ticker(sess_factory, bare_ticker: str, months: int) -> int:
    sess = sess_factory()
    if sess is None:
        return 0
    try:
        fv = _fetch_current_fv(sess, bare_ticker)
        if fv is None:
            return 0
        month_list = _month_starts(months)
        closes = _fetch_monthly_closes(sess, bare_ticker, month_list)
        if not closes:
            return 0
        return _upsert_rows(sess, bare_ticker, fv, closes)
    finally:
        try:
            sess.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Monthly fair_value_history backfill for the 12M "
                    "score sparkline."
    )
    parser.add_argument("--limit", type=int, default=500,
                        help="How many top tickers by market cap (default 500).")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Single ticker override (bare form, e.g. RELIANCE).")
    parser.add_argument("--months", type=int, default=14,
                        help="How many months back to seed (default 14).")
    parser.add_argument("--throttle", type=float, default=0.02,
                        help="Per-ticker sleep, seconds (default 0.02).")
    args = parser.parse_args()

    # Single-ticker path: open a session just for ticker loading vs the
    # per-ticker factory. main() ultimately re-opens a fresh session per
    # ticker to keep connection count bounded on Neon free tier.
    sess = _get_session()
    if sess is None:
        log.error("DB session unavailable — aborting.")
        return 1

    if args.ticker:
        bare = args.ticker.rsplit(".", 1)[0] if (
            args.ticker.endswith(".NS") or args.ticker.endswith(".BO")
        ) else args.ticker
        targets = [bare]
        try:
            sess.close()
        except Exception:
            pass
    else:
        try:
            targets = _load_top_tickers(sess, args.limit)
        finally:
            try:
                sess.close()
            except Exception:
                pass
        if not targets:
            log.error("Zero tickers loaded — aborting.")
            return 1

    log.info("Backfilling %d tickers × up to %d months (throttle=%.2fs)",
             len(targets), args.months, args.throttle)

    t0 = time.perf_counter()
    ok = 0
    empty = 0
    total_rows = 0
    for idx, tk in enumerate(targets, start=1):
        try:
            wrote = _process_ticker(_get_session, tk, args.months)
        except Exception as exc:
            log.warning("unhandled error for %s: %s", tk, exc)
            wrote = 0
        if wrote > 0:
            ok += 1
            total_rows += wrote
        else:
            empty += 1
        if idx % 25 == 0:
            elapsed = time.perf_counter() - t0
            rate = idx / max(elapsed, 1e-3)
            eta = (len(targets) - idx) / max(rate, 1e-3)
            log.info("  [%d/%d] ok=%d empty=%d rows=%d  rate=%.1f tk/s  eta=%.0fs",
                     idx, len(targets), ok, empty, total_rows, rate, eta)
        if args.throttle > 0:
            time.sleep(args.throttle)

    elapsed = time.perf_counter() - t0
    log.info("DONE in %.1fs — %d ok / %d empty — %d rows upserted",
             elapsed, ok, empty, total_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
