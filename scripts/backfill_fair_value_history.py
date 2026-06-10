"""
backfill_fair_value_history.py
═══════════════════════════════════════════════════════════════
Dense day-level interpolation backfill of ``fair_value_history``
(ROOT CAUSE #12 — 2026-06-11).

Why this exists
───────────────
The HDFCBANK 12-month MoS calendar on prod shows 331 no-data days
of 365. The existing monthly seeder
(``backend/scripts/backfill_fair_value_history_monthly.py``) writes
one row per (ticker, month) which is enough for the sparkline
collapse logic but leaves the daily calendar full of holes. The
live write-hook fills today's row only; gaps from any day the
ticker was not analyzed remain forever.

This script closes the gap by INTERPOLATING between adjacent
recompute days, marking the interpolated rows with
``source='interpolated'`` (a string in the verdict-or-comment
column when no dedicated source column is present — we use
``confidence = -1`` as a sentinel mark + a verdict suffix
"_interpolated" so a downstream reader can filter them out of
the model's training set).

Strategy per ticker
───────────────────
  1. Pull every existing row from fair_value_history for the
     window [today - days, today].
  2. Group into anchors (one row per date).
  3. Walk consecutive anchor pairs (A, B) where B.date - A.date
     > 1 day. For each missing day D in (A.date, B.date):
        weight = (D - A.date) / (B.date - A.date)
        fv     = A.fv + weight * (B.fv - A.fv)
        price  = A.price + weight * (B.price - A.price)
     and upsert with source-tag.
  4. Idempotent: re-runs OVERWRITE only rows we previously
     interpolated (confidence == -1 sentinel). Rows written by
     the live hook (confidence != -1) are NEVER overwritten —
     they're production-faithful and must win.

Universe
────────
Defaults to ``scripts/canary_universe_180.json`` (180 tickers).
A ``--ticker`` flag accepts a single bare ticker for spot-check
runs. ``--days 365`` is the default window.

Idempotency / safety
────────────────────
The script does NOT alter the schema. It assumes
fair_value_history has the existing columns (ticker, date,
fair_value, price, mos_pct, verdict, wacc, confidence,
updated_at). If your DB has an extra ``source`` text column
(post-Agent-A-v3-superset migration), the script will additionally
set ``source='interpolated'`` on inserts (the SET clause is
guarded by a try/except so older schemas keep working).

Exit code
─────────
0 — DB reachable, walked all tickers (per-ticker failures logged
    but not fatal).
1 — DB unreachable / zero tickers loaded.

Usage
─────
    python scripts/backfill_fair_value_history.py \\
        [--days 365] [--throttle 0.02]
    python scripts/backfill_fair_value_history.py \\
        --ticker HDFCBANK --days 365

Never run from Railway request path. Invoked manually via
workflow_dispatch.
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

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=os.environ.get("BACKFILL_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("backfill_fv_history_dense")


# ── Universe loading ────────────────────────────────────────────
def _load_canary_universe(path: str | None = None) -> list[str]:
    """Return bare-ticker list from canary_universe_180.json.

    Falls back to canary_stocks_50.json if the larger file is
    absent (e.g. an older checkout). Returns [] on any failure —
    caller decides whether to abort.
    """
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    candidates.append(_REPO_ROOT / "scripts" / "canary_universe_180.json")
    candidates.append(_REPO_ROOT / "scripts" / "canary_stocks_50.json")
    for p in candidates:
        if not p.exists():
            continue
        try:
            with p.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            log.warning("canary universe load failed for %s: %s", p, exc)
            continue
        out: list[str] = []
        if isinstance(data, list):
            for r in data:
                if isinstance(r, str):
                    out.append(r.strip())
                elif isinstance(r, dict):
                    t = r.get("ticker") or r.get("symbol") or ""
                    if isinstance(t, str) and t.strip():
                        out.append(t.strip())
        elif isinstance(data, dict):
            tickers = data.get("tickers") or data.get("universe") or []
            if isinstance(tickers, list):
                for t in tickers:
                    if isinstance(t, str) and t.strip():
                        out.append(t.strip())
        # Strip suffixes — fair_value_history stores bare.
        bare: list[str] = []
        for t in out:
            tt = t.upper()
            if tt.endswith(".NS") or tt.endswith(".BO"):
                tt = tt.rsplit(".", 1)[0]
            bare.append(tt)
        if bare:
            log.info("loaded %d tickers from %s", len(bare), p.name)
            return bare
    log.warning("no canary universe file found; tried %s", candidates)
    return []


# ── DB plumbing ─────────────────────────────────────────────────
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


def _has_source_column(sess) -> bool:
    """Probe information_schema once per process. The post-
    Agent-A-v3 migration adds a ``source`` text column; older
    schemas don't have it."""
    from sqlalchemy import text
    try:
        row = sess.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'fair_value_history'
                  AND column_name = 'source'
                LIMIT 1
                """
            )
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _fetch_existing_rows(sess, bare_ticker: str, start: date, end: date
                         ) -> list[tuple[date, float, float]]:
    """Return chronological [(date, fv, price), ...] within the window.

    Excludes interpolated rows (confidence = -1) so they don't
    anchor further interpolation passes — we only chain off
    production-faithful anchors.
    """
    from sqlalchemy import text
    try:
        rows = sess.execute(
            text(
                """
                SELECT date, fair_value, price
                FROM fair_value_history
                WHERE ticker IN (:a, :b)
                  AND date >= :start AND date <= :end
                  AND fair_value IS NOT NULL
                  AND price IS NOT NULL
                  AND (confidence IS NULL OR confidence <> -1)
                ORDER BY date ASC
                """
            ),
            {
                "a": bare_ticker,
                "b": f"{bare_ticker}.NS",
                "start": start,
                "end": end,
            },
        ).fetchall()
    except Exception as exc:
        log.debug("anchor query failed for %s: %s", bare_ticker, exc)
        return []
    out: list[tuple[date, float, float]] = []
    for r in rows:
        try:
            d, fv, px = r[0], float(r[1]), float(r[2])
        except (TypeError, ValueError):
            continue
        if fv <= 0 or px <= 0:
            continue
        out.append((d, fv, px))
    return out


def _interpolate_gaps(
    anchors: list[tuple[date, float, float]],
) -> list[tuple[date, float, float]]:
    """Walk consecutive anchor pairs and yield (D, fv, price) for
    every missing intermediate day.
    """
    out: list[tuple[date, float, float]] = []
    for i in range(len(anchors) - 1):
        a_d, a_fv, a_px = anchors[i]
        b_d, b_fv, b_px = anchors[i + 1]
        gap = (b_d - a_d).days
        if gap <= 1:
            continue
        for k in range(1, gap):
            w = k / gap
            fv = a_fv + w * (b_fv - a_fv)
            px = a_px + w * (b_px - a_px)
            out.append((a_d + timedelta(days=k), fv, px))
    return out


def _upsert_interpolated(
    sess,
    bare_ticker: str,
    rows: list[tuple[date, float, float]],
    has_source_col: bool,
) -> int:
    """Insert interpolated rows. Returns count actually written.

    confidence=-1 is the sentinel that marks the row as
    interpolated (the live writer never writes -1; max real
    confidence is 100). The verdict carries the same intent via
    suffix so a CSV export reader can spot them too.
    """
    from sqlalchemy import text
    if not rows:
        return 0
    written = 0
    for d, fv, px in rows:
        try:
            mos_pct = round((fv - px) / px * 100.0, 2) if px > 0 else 0.0
        except Exception:
            continue
        if mos_pct > 200:
            mos_pct = 200.0
        if mos_pct < -90:
            mos_pct = -90.0
        verdict = (
            "undervalued_interpolated" if mos_pct > 10
            else "fairly_valued_interpolated" if mos_pct > -10
            else "overvalued_interpolated"
        )
        sql_with_source = (
            """
            INSERT INTO fair_value_history (
                ticker, date, fair_value, price, mos_pct,
                verdict, wacc, confidence, source, updated_at
            ) VALUES (
                :t, :d, :fv, :px, :mos,
                :v, NULL, -1, 'interpolated', now()
            )
            ON CONFLICT (ticker, date) DO UPDATE SET
                fair_value = EXCLUDED.fair_value,
                price      = EXCLUDED.price,
                mos_pct    = EXCLUDED.mos_pct,
                verdict    = EXCLUDED.verdict,
                source     = EXCLUDED.source,
                updated_at = now()
            WHERE fair_value_history.confidence = -1
            """
        )
        sql_no_source = (
            """
            INSERT INTO fair_value_history (
                ticker, date, fair_value, price, mos_pct,
                verdict, wacc, confidence, updated_at
            ) VALUES (
                :t, :d, :fv, :px, :mos,
                :v, NULL, -1, now()
            )
            ON CONFLICT (ticker, date) DO UPDATE SET
                fair_value = EXCLUDED.fair_value,
                price      = EXCLUDED.price,
                mos_pct    = EXCLUDED.mos_pct,
                verdict    = EXCLUDED.verdict,
                updated_at = now()
            WHERE fair_value_history.confidence = -1
            """
        )
        sql = sql_with_source if has_source_col else sql_no_source
        try:
            sess.execute(
                text(sql),
                {
                    "t": bare_ticker,
                    "d": d,
                    "fv": round(fv, 2),
                    "px": round(px, 2),
                    "mos": mos_pct,
                    "v": verdict,
                },
            )
            written += 1
        except Exception as exc:
            log.debug("interp upsert failed %s @ %s: %s", bare_ticker, d, exc)
            try:
                sess.rollback()
            except Exception:
                pass
            return written
    try:
        sess.commit()
    except Exception:
        try:
            sess.rollback()
        except Exception:
            pass
    return written


def _process_ticker(sess_factory, bare_ticker: str, days: int) -> tuple[int, int]:
    """Returns (anchor_count, interpolated_count)."""
    sess = sess_factory()
    if sess is None:
        return (0, 0)
    try:
        end = date.today()
        start = end - timedelta(days=days)
        anchors = _fetch_existing_rows(sess, bare_ticker, start, end)
        if len(anchors) < 2:
            return (len(anchors), 0)
        interp = _interpolate_gaps(anchors)
        if not interp:
            return (len(anchors), 0)
        has_src = _has_source_column(sess)
        written = _upsert_interpolated(
            sess, bare_ticker, interp, has_src,
        )
        return (len(anchors), written)
    finally:
        try:
            sess.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dense day-level FV history interpolation backfill.",
    )
    parser.add_argument(
        "--ticker", type=str, default=None,
        help="Single ticker override (bare form, e.g. HDFCBANK).",
    )
    parser.add_argument(
        "--days", type=int, default=365,
        help="Window backfill, in days (default 365).",
    )
    parser.add_argument(
        "--throttle", type=float, default=0.02,
        help="Per-ticker sleep, seconds (default 0.02).",
    )
    parser.add_argument(
        "--universe", type=str, default=None,
        help="Override canary universe path (default: canary_universe_180.json).",
    )
    args = parser.parse_args()

    if args.ticker:
        bare = args.ticker.upper()
        if bare.endswith(".NS") or bare.endswith(".BO"):
            bare = bare.rsplit(".", 1)[0]
        targets = [bare]
    else:
        targets = _load_canary_universe(args.universe)
        if not targets:
            log.error("zero tickers loaded — aborting.")
            return 1

    log.info(
        "dense FV interpolation backfill: %d tickers × %d days "
        "(throttle=%.2fs)",
        len(targets), args.days, args.throttle,
    )

    t0 = time.perf_counter()
    ok = 0
    skipped = 0
    anchors_seen = 0
    interp_total = 0
    for idx, tk in enumerate(targets, start=1):
        try:
            anchors, interp = _process_ticker(_get_session, tk, args.days)
        except Exception as exc:
            log.warning("unhandled error for %s: %s", tk, exc)
            anchors, interp = (0, 0)
        anchors_seen += anchors
        interp_total += interp
        if anchors >= 2 or interp > 0:
            ok += 1
        else:
            skipped += 1
        if idx % 20 == 0:
            elapsed = time.perf_counter() - t0
            rate = idx / max(elapsed, 1e-3)
            eta = (len(targets) - idx) / max(rate, 1e-3)
            log.info(
                "  [%d/%d] ok=%d skip=%d anchors=%d interp=%d "
                "rate=%.1f tk/s eta=%.0fs",
                idx, len(targets), ok, skipped, anchors_seen,
                interp_total, rate, eta,
            )
        if args.throttle > 0:
            time.sleep(args.throttle)

    elapsed = time.perf_counter() - t0
    log.info(
        "DONE in %.1fs — %d ok / %d skipped — %d anchors "
        "seen, %d rows interpolated",
        elapsed, ok, skipped, anchors_seen, interp_total,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
