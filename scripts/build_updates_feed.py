"""Nightly aggregator for the Portfolio Updates Feed (P0 #1).

Scans recent rows in:
  - corporate_actions       → dividends category
  - insider_trading         → insider_trading category
  - cache_invalidation_manifest entries → valuations / intrinsic_updates
                              / risk_legal categories (via rationale)
  - financials_history (if present) → earnings category

For each new event, generates a template-driven headline+detail
(backend.services.updates_feed.templates.render) and UPSERTs into
portfolio_updates_feed. Idempotent by (ticker, event_at, category) —
re-running the same day is a no-op.

NO LLM calls. NO network calls beyond the DB. Designed to run in
.github/workflows/cron-updates-feed.yml (nightly 03:00 IST). Per
discipline rule (memory/feedback_yieldiq_discipline.md) this MUST NOT
run inside the Railway worker.

Usage:
    python scripts/build_updates_feed.py [--lookback-days 30] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Project root on sys.path so `from backend...` works whether the script
# is invoked from the repo root or from inside scripts/.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.services.updates_feed.templates import render  # noqa: E402

log = logging.getLogger("build_updates_feed")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


# ─────────────────────────── DB helpers ───────────────────────────

def _get_conn():
    """Return a raw DB connection via the pipeline engine, or None."""
    try:
        from data_pipeline.db import engine  # type: ignore
    except Exception as exc:
        log.warning("pipeline engine import failed: %s", exc)
        return None
    if engine is None:
        return None
    try:
        return engine.raw_connection()
    except Exception as exc:
        log.warning("engine.raw_connection() failed: %s", exc)
        return None


_UPSERT_SQL = """
    INSERT INTO portfolio_updates_feed
        (ticker, event_at, category, headline, detail, source_ref)
    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
    ON CONFLICT (ticker, event_at, category) DO NOTHING
"""


def _upsert(cur, ticker: str, event_at: datetime, category: str,
            headline: str, detail: str, source_ref: str | None) -> bool:
    """Returns True if a row was inserted, False if skipped (conflict)."""
    cur.execute(
        _UPSERT_SQL,
        (ticker, event_at, category, headline, detail, source_ref),
    )
    # psycopg2 returns rowcount=1 on insert, 0 on ON CONFLICT DO NOTHING.
    return bool(cur.rowcount)


# ─────────────────────── source-row scanners ──────────────────────

def scan_dividends(cur, since: datetime) -> list[dict[str, Any]]:
    """Return dividend rows from corporate_actions since `since`."""
    try:
        cur.execute(
            """
            SELECT ticker, ex_date, ratio, remarks
            FROM corporate_actions
            WHERE action_type IN ('DIVIDEND', 'CASH_DIVIDEND', 'INTERIM_DIVIDEND', 'FINAL_DIVIDEND')
              AND ex_date >= %s::date
            ORDER BY ex_date DESC
            LIMIT 5000
            """,
            (since.date(),),
        )
    except Exception as exc:
        log.warning("scan_dividends failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in cur.fetchall():
        ticker, ex_date, ratio, remarks = r
        out.append({
            "ticker": (ticker or "").strip().upper(),
            "event_at": datetime.combine(ex_date, datetime.min.time(), tzinfo=timezone.utc),
            "category": "dividends",
            "event": {
                "period": remarks or "Dividend",
                "amount": float(ratio) if ratio is not None else None,
                "ex_date": ex_date,
            },
            "source_ref": '{"table":"corporate_actions"}',
        })
    return out


def scan_insider(cur, since: datetime) -> list[dict[str, Any]]:
    try:
        cur.execute(
            """
            SELECT ticker, filing_date, acquirer_name, acquirer_category,
                   buy_qty, sell_qty, transaction_value_cr
            FROM insider_trading
            WHERE filing_date >= %s::date
            ORDER BY filing_date DESC
            LIMIT 5000
            """,
            (since.date(),),
        )
    except Exception as exc:
        log.warning("scan_insider failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in cur.fetchall():
        ticker, filing_date, name, category, buy_qty, sell_qty, txn_cr = r
        out.append({
            "ticker": (ticker or "").strip().upper(),
            "event_at": datetime.combine(filing_date, datetime.min.time(), tzinfo=timezone.utc),
            "category": "insider_trading",
            "event": {
                "acquirer_name": name,
                "acquirer_category": category,
                "buy_qty": buy_qty,
                "sell_qty": sell_qty,
                "transaction_value_cr": txn_cr,
                "filing_date": filing_date,
            },
            "source_ref": '{"table":"insider_trading"}',
        })
    return out


def scan_manifest(since: datetime) -> list[dict[str, Any]]:
    """Manifest entries are in-code (cache_invalidation_manifest.MANIFEST).
    Each entry with a recent applied_at becomes either a `valuations` or
    `risk_legal` row depending on the rationale text. Wildcard ("*")
    entries are recorded with sentinel ticker "*" and joined in for
    every user at read time.
    """
    try:
        from backend.services.cache_invalidation_manifest import MANIFEST  # type: ignore
    except Exception as exc:
        log.warning("manifest import failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for entry in MANIFEST:
        applied_at = entry.get("applied_at")
        if not isinstance(applied_at, datetime):
            continue
        if applied_at < since:
            continue
        rationale = (entry.get("rationale") or "").lower()
        category = "valuations"
        if any(w in rationale for w in ("risk", "sebi", "audit", "fraud", "litig")):
            category = "risk_legal"
        scope = entry.get("scope") or {}
        tickers = scope.get("tickers") or []
        if tickers == "*":
            tickers_iter: list[str] = ["*"]
        else:
            tickers_iter = [str(t).strip().upper() for t in tickers if t]
        for t in tickers_iter:
            if category == "risk_legal":
                event = {
                    "flag": entry.get("version_id") or "Engine flag",
                    "description": entry.get("rationale") or "",
                    "as_of": applied_at,
                }
            else:
                event = {
                    "old_fv": None,
                    "new_fv": None,
                    "reason": entry.get("rationale") or "",
                }
            out.append({
                "ticker": t,
                "event_at": applied_at,
                "category": category,
                "event": event,
                "source_ref": (
                    '{"table":"manifest","version_id":'
                    f'"{entry.get("version_id") or ""}"' + "}"
                ),
            })
    return out


def scan_financials(cur, since: datetime) -> list[dict[str, Any]]:
    """Earnings rows from financials_history (if the table exists).
    Silently returns [] if the table is missing — the feature still
    works on dividends + insider + manifest in that case."""
    try:
        cur.execute(
            """
            SELECT to_regclass('public.financials_history')
            """
        )
        if not (cur.fetchone() or [None])[0]:
            return []
    except Exception:
        return []
    try:
        cur.execute(
            """
            SELECT ticker, period_end, period_label,
                   eps, revenue
            FROM financials_history
            WHERE period_end >= %s::date
            ORDER BY period_end DESC
            LIMIT 5000
            """,
            (since.date(),),
        )
    except Exception as exc:
        log.warning("scan_financials failed: %s", exc)
        return []
    # Build a (ticker -> sorted rows) lookup so we can pick prior period
    by_ticker: dict[str, list[tuple]] = {}
    for r in cur.fetchall():
        ticker = (r[0] or "").strip().upper()
        by_ticker.setdefault(ticker, []).append(r)
    out: list[dict[str, Any]] = []
    for ticker, rows in by_ticker.items():
        # Already DESC; pair index i with i+1 for prior.
        for i, r in enumerate(rows):
            period_end, period_label, eps, revenue = r[1], r[2], r[3], r[4]
            prior = rows[i + 1] if i + 1 < len(rows) else (None, None, None, None, None)
            out.append({
                "ticker": ticker,
                "event_at": datetime.combine(period_end, datetime.min.time(), tzinfo=timezone.utc),
                "category": "earnings",
                "event": {
                    "period": period_label,
                    "prior_period": prior[2],
                    "eps": float(eps) if eps is not None else None,
                    "eps_prior": float(prior[3]) if prior[3] is not None else None,
                    "revenue": float(revenue) if revenue is not None else None,
                    "revenue_prior": float(prior[4]) if prior[4] is not None else None,
                },
                "source_ref": '{"table":"financials_history"}',
            })
    return out


# ─────────────────────────── main loop ───────────────────────────

def run(lookback_days: int = 30, dry_run: bool = False) -> dict[str, int]:
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    log.info("scanning events since %s (lookback=%dd)", since.isoformat(), lookback_days)

    conn = _get_conn()
    if conn is None:
        log.error("no DB connection; aborting")
        return {"inserted": 0, "skipped": 0, "scanned": 0}
    cur = conn.cursor()

    events: list[dict[str, Any]] = []
    events += scan_dividends(cur, since)
    events += scan_insider(cur, since)
    events += scan_financials(cur, since)
    events += scan_manifest(since)

    log.info("scanned %d candidate events", len(events))

    inserted = skipped = 0
    for ev in events:
        ticker = ev["ticker"]
        if not ticker:
            skipped += 1
            continue
        rendered = render(ev["category"], ev["event"])
        if dry_run:
            log.info(
                "DRY %s %s %s :: %s",
                ticker, ev["event_at"].isoformat(), ev["category"],
                rendered["headline"],
            )
            continue
        try:
            ok = _upsert(
                cur, ticker, ev["event_at"], ev["category"],
                rendered["headline"], rendered["detail"], ev.get("source_ref"),
            )
            if ok:
                inserted += 1
            else:
                skipped += 1
        except Exception as exc:
            log.warning("upsert failed for %s/%s: %s", ticker, ev["category"], exc)
            skipped += 1

    if not dry_run:
        conn.commit()
    cur.close()
    conn.close()
    log.info("done: inserted=%d skipped=%d scanned=%d", inserted, skipped, len(events))
    return {"inserted": inserted, "skipped": skipped, "scanned": len(events)}


def main() -> int:
    p = argparse.ArgumentParser(description="Build portfolio_updates_feed")
    p.add_argument("--lookback-days", type=int, default=30)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    stats = run(lookback_days=args.lookback_days, dry_run=args.dry_run)
    return 0 if stats.get("inserted", 0) >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
