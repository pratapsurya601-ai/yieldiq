#!/usr/bin/env python3
# backend/scripts/backfill_hex_history.py
# ═══════════════════════════════════════════════════════════════
# One-off / weekly backfill of the hex_history table.
#
# CLI:
#     python backfill_hex_history.py [--limit 500] [--ticker RELIANCE.NS]
#                                    [--quarters 12] [--throttle 0.05]
#                                    [--fail-if-zero-ok] [--seed-from-cache]
#
# Runs in GitHub Actions (see .github/workflows/hex_history_weekly.yml).
# NEVER run this at request time on Railway — it's 500 × 12 ≈ 6k
# snapshots and the single worker would starve.
#
# Idempotent: ON CONFLICT UPDATE in the inner upsert.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Repo root on path so `backend.*` and `data_pipeline.*` import cleanly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("backfill_hex_history")


def _resolve_dsn() -> str | None:
    """Resolve the Postgres DSN with the project's standard precedence.

    Prefer NEON_DATABASE_URL (the canonical name on Railway after the
    Aiven→Neon migration); fall back to legacy DATABASE_URL if only
    that is set. Returns None when neither is present so the caller
    can refuse to run.
    """
    return os.environ.get("NEON_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _load_top_tickers(limit: int) -> list[str]:
    """Top N NSE tickers by market_cap_cr, matching cache_warmup style."""
    try:
        from sqlalchemy import text  # type: ignore
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        log.error("cannot import pipeline DB: %s", exc)
        return []
    sess = Session()
    try:
        # DISTINCT ON (ticker) dedupes cross-listing rows. Without it,
        # dual-listed tickers (NSE+BSE, e.g. BPCL) appear twice in the
        # backfill queue. See design note in backend/routers/screener.py.
        rows = sess.execute(
            text(
                """
                SELECT ticker FROM (
                    SELECT DISTINCT ON (ticker) ticker, market_cap_cr
                    FROM market_metrics
                    WHERE market_cap_cr IS NOT NULL
                    ORDER BY ticker, trade_date DESC
                ) t
                ORDER BY market_cap_cr DESC
                LIMIT :lim
                """
            ),
            {"lim": limit},
        ).fetchall()
        out = []
        for r in rows:
            t = r[0]
            if not t:
                continue
            if not (t.endswith(".NS") or t.endswith(".BO")):
                t = f"{t}.NS"
            out.append(t)
        return out
    finally:
        try:
            sess.close()
        except Exception:
            pass


def _diagnose_empty(ticker: str) -> dict:
    """Dump row counts for the upstream tables a hex_history insert
    depends on, so the operator can tell WHICH source is empty.

    Called when ok == 0 — the workflow has produced no successful
    backfills, which historically meant either market_metrics is dry,
    company_financials never ingested, or analysis_cache hasn't been
    warmed yet. Each of those needs a different remediation.
    """
    out: dict = {"ticker": ticker, "tables": {}}
    try:
        from sqlalchemy import text  # type: ignore
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        out["error"] = f"pipeline DB import failed: {exc!r}"
        return out
    sess = Session()
    try:
        for tbl in (
            "market_metrics",
            "company_financials",
            "analysis_cache",
            "fair_value_history",
        ):
            try:
                row = sess.execute(
                    text(f"SELECT COUNT(*) FROM {tbl} WHERE ticker = :tk"),
                    {"tk": ticker},
                ).fetchone()
                out["tables"][tbl] = int(row[0]) if row and row[0] is not None else 0
            except Exception as exc:
                out["tables"][tbl] = f"error: {type(exc).__name__}: {exc}"
    finally:
        try:
            sess.close()
        except Exception:
            pass
    return out


def _seed_one_from_cache(ticker: str) -> int:
    """Synthesise a single current-quarter hex_history row using the
    SAME 6-axis derivation as the live API.

    Goes through ``backend.services.analysis.hex_axes.compute_axes_for_ticker``
    — the single source of truth that delegates to
    ``hex_service.compute_hex_safe``. Two prior bugs in this function,
    fixed together:

      (1) The previous implementation read ``payload["hex"]["axes"]``,
          a key the analysis pipeline NEVER writes into the cache row.
          Result: ``axes`` was always ``{}``, and every ticker silently
          returned 0 from the seeder. The 2026-04-25 backfill produced
          0 hex_history rows across all 50 canary tickers.

      (2) The previous INSERT targeted columns ``axes JSONB`` and
          ``source TEXT`` — neither of which exist on the
          ``hex_history`` table. The real schema (see
          ``hex_history_service._ensure_history_table``) has explicit
          ``{value,quality,growth,moat,safety,pulse}_score`` numeric
          columns plus ``overall``, ``refraction_index``,
          ``verdict_band``, and ``quarter_end`` (NOT ``period_end``).
          Even if (1) had returned data, this INSERT would have raised
          UndefinedColumn — the seeder caught the exception silently
          and continued returning 0.

    Returns the number of rows upserted (0 or 1).
    """
    try:
        from sqlalchemy import text  # type: ignore
        from data_pipeline.db import Session  # type: ignore
        from datetime import date
        # IMPORTANT: import the PURE hex_axes module only. Do NOT import
        # hex_service / compute_axes_for_ticker — those pull in the full
        # backend service stack (pydantic / fastapi / streamlit) which is
        # not installed in the slim workflow env. compute_axes_from_payload
        # has a pure-Python derivation branch for cache-row payloads.
        from backend.services.analysis.hex_axes import (
            compute_axes_from_payload,
            AXIS_WEIGHTS,
        )
    except Exception as exc:
        log.warning("seed: import failed for %s: %s", ticker, exc)
        return 0
    sess = Session()
    try:
        # Pull the actual cache row so we can derive axes from its
        # payload via the pure-Python path (no service imports).
        row = sess.execute(
            text(
                "SELECT payload FROM analysis_cache WHERE ticker = :tk "
                "ORDER BY computed_at DESC LIMIT 1"
            ),
            {"tk": ticker},
        ).fetchone()
        if not row or not row[0]:
            return 0

        payload = row[0]
        if isinstance(payload, str):
            import json as _json
            try:
                payload = _json.loads(payload)
            except Exception:
                return 0

        try:
            axes = compute_axes_from_payload(payload)
        except Exception as exc:
            log.warning("seed: axis derivation failed for %s: %s", ticker, exc)
            return 0

        # Quarter-end = first day of the current quarter (canonical key
        # used by hex_history elsewhere — column is `quarter_end`).
        today = date.today()
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        quarter_end = date(today.year, q_start_month, 1).isoformat()

        # Composite overall via the same weights the live render uses.
        # AXIS_WEIGHTS is imported from the pure hex_axes module above
        # (NOT hex_service — that path drags in the full backend stack).
        try:
            overall = (
                axes.value   * AXIS_WEIGHTS["value"]
                + axes.quality * AXIS_WEIGHTS["quality"]
                + axes.growth  * AXIS_WEIGHTS["growth"]
                + axes.moat    * AXIS_WEIGHTS["moat"]
                + axes.safety  * AXIS_WEIGHTS["safety"]
                + axes.pulse   * AXIS_WEIGHTS["pulse"]
            )
            overall = round(max(0.0, min(10.0, overall)), 2)
        except Exception:
            overall = None

        sess.execute(
            text(
                """
                INSERT INTO hex_history (
                  ticker, quarter_end,
                  value_score, quality_score, growth_score,
                  moat_score, safety_score, pulse_score,
                  overall, computed_at
                ) VALUES (
                  :tk, :qe,
                  :value, :quality, :growth,
                  :moat, :safety, :pulse,
                  :overall, now()
                )
                ON CONFLICT (ticker, quarter_end) DO UPDATE SET
                  value_score   = EXCLUDED.value_score,
                  quality_score = EXCLUDED.quality_score,
                  growth_score  = EXCLUDED.growth_score,
                  moat_score    = EXCLUDED.moat_score,
                  safety_score  = EXCLUDED.safety_score,
                  pulse_score   = EXCLUDED.pulse_score,
                  overall       = EXCLUDED.overall,
                  computed_at   = now()
                """
            ),
            {
                "tk": ticker,
                "qe": quarter_end,
                "value": axes.value,
                "quality": axes.quality,
                "growth": axes.growth,
                "moat": axes.moat,
                "safety": axes.safety,
                "pulse": axes.pulse,
                "overall": overall,
            },
        )
        sess.commit()
        return 1
    except Exception as exc:
        log.warning("seed: %s failed: %s", ticker, exc)
        try:
            sess.rollback()
        except Exception:
            pass
        return 0
    finally:
        try:
            sess.close()
        except Exception:
            pass


def _to_json(obj) -> str:
    import json as _json
    return _json.dumps(obj, default=str)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill hex_history for top-N tickers × N quarters"
    )
    parser.add_argument("--limit", type=int, default=500,
                        help="How many top tickers to backfill (default 500)")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Backfill a single ticker (overrides --limit)")
    parser.add_argument("--quarters", type=int, default=12,
                        help="Number of quarters per ticker (default 12)")
    parser.add_argument("--throttle", type=float, default=0.05,
                        help="Sleep between tickers, seconds (default 0.05)")
    parser.add_argument("--fail-if-zero-ok", action="store_true",
                        help="Exit 1 when no ticker produced a successful backfill")
    parser.add_argument("--seed-from-cache", action="store_true",
                        help="(legacy) Fallback: when the heavy path produces 0 rows, synthesise a current-quarter row from analysis_cache.")
    parser.add_argument("--cache-only", action="store_true",
                        help="Skip the heavy hex_history_service path entirely. ONLY synthesise current-quarter rows from analysis_cache via the pure hex_axes.compute_axes_from_payload. Required for slim CI runners that don't install the full backend stack (no streamlit, no requests, no yfinance, etc.). Does NOT compute historical quarters — only the current one. Use --quarters 1 to be explicit.")
    args = parser.parse_args()

    # Refuse to run without a DSN — silently no-oping in CI is the
    # exact failure mode that masked v34's empty-history bug.
    dsn = _resolve_dsn()
    if not dsn:
        log.error(
            "Refusing to run: NEON_DATABASE_URL / DATABASE_URL not set. "
            "Set one before invoking the backfill."
        )
        return 1
    # data_pipeline.db reads DATABASE_URL by name; if only NEON_* is
    # set, mirror it across so SQLAlchemy can connect.
    os.environ.setdefault("DATABASE_URL", dsn)

    # Heavy import only when needed. --cache-only mode runs in slim CI
    # runners that have no streamlit / requests / yfinance / etc., so
    # we MUST NOT import hex_history_service in that mode — it
    # transitively pulls in the full backend stack via
    # backend.services.analysis.__init__ → analysis/service.py →
    # data/collector.py.
    compute_and_store_all_history = None
    if not args.cache_only:
        from backend.services.hex_history_service import (
            compute_and_store_all_history as _heavy_path,
        )
        compute_and_store_all_history = _heavy_path

    if args.ticker:
        tickers = [args.ticker]
    else:
        tickers = _load_top_tickers(args.limit)
    if not tickers:
        log.error("No tickers loaded. Exiting.")
        return 1

    if args.cache_only:
        log.info(
            "Cache-only mode: %d tickers × current quarter (pure hex_axes; "
            "no hex_history_service import).",
            len(tickers),
        )
    else:
        log.info("Backfilling %d tickers × %d quarters (throttle=%.2fs)",
                 len(tickers), args.quarters, args.throttle)

    t0 = time.perf_counter()
    ok = 0
    empty = 0
    errors = 0
    total_rows = 0
    seeded = 0

    for idx, tk in enumerate(tickers, start=1):
        try:
            if args.cache_only:
                s = _seed_one_from_cache(tk)
                if s > 0:
                    ok += 1
                    seeded += s
                    total_rows += s
                else:
                    empty += 1
            else:
                stored = compute_and_store_all_history(tk, quarters=args.quarters)
                total_rows += stored
                if stored > 0:
                    ok += 1
                else:
                    empty += 1
                    if args.seed_from_cache:
                        s = _seed_one_from_cache(tk)
                        if s > 0:
                            seeded += s
                            total_rows += s
        except Exception as exc:
            # Should never happen — service is never-raise — but guard anyway
            errors += 1
            log.warning("backfill error %s: %s", tk, exc)

        if idx % 10 == 0:
            elapsed = time.perf_counter() - t0
            rate = idx / max(elapsed, 1e-3)
            eta = (len(tickers) - idx) / max(rate, 1e-3)
            log.info("  [%d/%d] ok=%d empty=%d err=%d rows=%d seeded=%d  rate=%.1f tk/s  eta=%.0fs",
                     idx, len(tickers), ok, empty, errors, total_rows, seeded, rate, eta)

        if args.throttle > 0:
            time.sleep(args.throttle)

    elapsed = time.perf_counter() - t0
    log.info(
        "DONE in %.1fs — tickers: %d ok / %d empty / %d error — rows upserted: %d (seeded=%d)",
        elapsed, ok, empty, errors, total_rows, seeded,
    )

    # Diagnostics: when nothing succeeded, dump upstream counts for
    # the first ticker so the operator can tell which source is dry.
    if ok == 0 and tickers:
        diag = _diagnose_empty(tickers[0])
        log.warning("DIAGNOSTICS (first ticker): %s", diag)

    if args.fail_if_zero_ok and ok == 0:
        log.error("--fail-if-zero-ok set and ok=0; exiting 1")
        return 1

    # Tolerate per-ticker failures; exit 0 unless everything failed
    if ok == 0 and empty == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
