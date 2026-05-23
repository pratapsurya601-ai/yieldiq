"""Day-112 — rebuild daily_prices.adj_close across the full active universe.

Background
==========
Until Day-112, the NSE bhavcopy populators wrote ``adj_close = close_price``
because bhavcopy is an unadjusted feed and the original code didn't know
the difference. RELIANCE's 5y stock CAGR rendered as -7.8% in production
because the engine compared raw post-bonus close to raw pre-bonus close.

This script is the canonical owner of ``daily_prices.adj_close``. It
runs OUTSIDE Railway (multi-hour job — Railway worker tier can't host
it; see memory/feedback_yieldiq_discipline.md), on a developer machine
or a long-lived GH Actions runner.

Sources
=======
* **Source 1 — yfinance Adj Close.** ``yf.Ticker(t+".NS").history(
  period="max", auto_adjust=False)`` exposes the Yahoo-computed
  ``Adj Close`` column. This is our PRIMARY series — Yahoo applies
  split + bonus + special-dividend adjustments centrally and we
  trust it as the reference number.
* **Source 2 — corporate_actions table cross-validation.** We pull
  SPLIT/BONUS rows already ingested via ``data_pipeline.sources.
  nse_bhavcopy.download_corporate_actions`` and compute the expected
  cumulative adjustment factor from scratch. If our derived series
  disagrees with Yahoo by > 0.5% on any date, we log a
  ``corp_action_discrepancy`` row in ``price_adjustment_log`` with
  ``source='reconciled'`` and store the more conservative (smaller-
  absolute-adjustment) value. Operator can later investigate via
  ``GET /api/v1/admin/price-data-health``.

Robustness features
===================
* **Universe**: all active tickers from ``stocks`` table (~2,400+).
* **Parallel**: bounded thread pool, ``--workers`` (default 5).
* **Resumable**: per-ticker checkpoint at
  ``_rebuild_adj_close.checkpoint`` JSON. Re-run skips done tickers.
* **Dead-letter**: failures captured in
  ``_rebuild_adj_close.dead_letter.json`` with last error string.
* **Exponential backoff** on yfinance 429s: 10s -> 30s -> 90s -> 270s,
  max 4 retries.
* **Idempotent**: re-runs overwrite cleanly via ``UPDATE`` and append
  a new log row (the natural-key UNIQUE on
  ``(ticker, trade_date, rebuilt_at)`` accommodates re-runs because
  ``rebuilt_at`` defaults to ``now()``).
* **Audit trail**: every UPDATE goes through ``price_adjustment_log``
  with before/after values + source + corp-actions JSON.

Usage
=====
::

    DATABASE_URL=postgres://... python scripts/rebuild_adj_close.py
    DATABASE_URL=postgres://... python scripts/rebuild_adj_close.py --tickers RELIANCE,TCS
    DATABASE_URL=postgres://... python scripts/rebuild_adj_close.py --resume
    DATABASE_URL=postgres://... python scripts/rebuild_adj_close.py --reset-checkpoint

Expected runtime: 2-4 hours for the full active universe at 5 workers.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("rebuild_adj_close")

CHECKPOINT_PATH = ROOT / "_rebuild_adj_close.checkpoint"
DEAD_LETTER_PATH = ROOT / "_rebuild_adj_close.dead_letter.json"

# Yahoo / yfinance treats 429s as transient. Back off generously so
# we don't get IP-banned mid-rebuild.
BACKOFF_SCHEDULE_SECS = (10, 30, 90, 270)

# If yfinance Adj Close and corp_actions-derived series disagree by
# more than this on any one date, log a discrepancy and pick the more
# conservative value.
RECONCILE_TOLERANCE = 0.005  # 0.5%

_checkpoint_lock = threading.Lock()
_dead_letter_lock = threading.Lock()


# ──────────────────────────────────────────────────────────────────────
# Checkpoint + dead-letter persistence
# ──────────────────────────────────────────────────────────────────────


def _load_checkpoint() -> dict[str, str]:
    if not CHECKPOINT_PATH.exists():
        return {}
    try:
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_checkpoint(state: dict[str, str]) -> None:
    with _checkpoint_lock:
        CHECKPOINT_PATH.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _record_done(state: dict[str, str], ticker: str, status: str) -> None:
    with _checkpoint_lock:
        state[ticker] = f"{status}@{datetime.utcnow().isoformat()}"
        CHECKPOINT_PATH.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _record_dead_letter(ticker: str, error: str) -> None:
    with _dead_letter_lock:
        existing: dict[str, Any] = {}
        if DEAD_LETTER_PATH.exists():
            try:
                existing = json.loads(DEAD_LETTER_PATH.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        existing[ticker] = {
            "last_error": error,
            "failed_at": datetime.utcnow().isoformat(),
        }
        DEAD_LETTER_PATH.write_text(
            json.dumps(existing, indent=2, sort_keys=True),
            encoding="utf-8",
        )


# ──────────────────────────────────────────────────────────────────────
# yfinance fetch with exponential backoff on 429
# ──────────────────────────────────────────────────────────────────────


def fetch_yfinance_adj_close(ticker: str, period: str = "max"):
    """Return a list of (trade_date, close, adj_close) tuples or None.

    Retries 429s with exponential backoff per BACKOFF_SCHEDULE_SECS.
    Caller is responsible for treating None as a hard failure (dead
    letter).
    """
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed (pip install yfinance)")
        return None

    symbol = f"{ticker}.NS"
    last_exc: Exception | None = None

    for attempt, delay in enumerate([0, *BACKOFF_SCHEDULE_SECS]):
        if delay:
            log.warning("%s: backoff %ds before attempt %d",
                        ticker, delay, attempt)
            time.sleep(delay)
        try:
            hist = yf.Ticker(symbol).history(period=period, auto_adjust=False)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            msg = str(exc).lower()
            if "429" in msg or "rate" in msg or "too many" in msg:
                continue
            # Non-rate-limit error — fail fast.
            log.warning("%s: yfinance fetched failed: %s", ticker, exc)
            return None
        if hist is None or hist.empty:
            log.info("%s: no yfinance data", ticker)
            return None
        cols = {c.lower(): c for c in hist.columns}
        close_col = cols.get("close")
        adj_col = cols.get("adj close")
        if close_col is None or adj_col is None:
            log.warning("%s: yfinance missing Close/Adj Close columns: %s",
                        ticker, list(hist.columns))
            return None
        out: list[tuple[date, float, float]] = []
        for idx, row in hist.iterrows():
            try:
                td = idx.date() if hasattr(idx, "date") else idx
                close_v = float(row[close_col])
                adj_v = float(row[adj_col])
            except (TypeError, ValueError):
                continue
            out.append((td, close_v, adj_v))
        return out

    log.warning("%s: exhausted yfinance backoff retries (%s)", ticker, last_exc)
    return None


# ──────────────────────────────────────────────────────────────────────
# Source 2 — derive adjustment factors from corporate_actions table
# ──────────────────────────────────────────────────────────────────────


_SPLIT_RE_HINTS = ("SPLIT", "FACE VALUE", "SUB-DIVISION", "SUB DIVISION")
_BONUS_RE_HINTS = ("BONUS",)


def _parse_ratio(raw: str | None) -> float | None:
    """Parse a ratio string like "1:2" / "1:10" / "Bonus 1:1" into a
    numeric *split factor* (post-event share count / pre-event share
    count). 1:2 split -> 2.0 (each share becomes 2). 1:1 bonus -> 2.0
    (1 new share per 1 held -> total 2x). Returns None if unparseable.
    """
    if not raw:
        return None
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)", str(raw))
    if not m:
        return None
    try:
        a = float(m.group(1))
        b = float(m.group(2))
    except ValueError:
        return None
    if a <= 0 or b <= 0:
        return None
    upper = str(raw).upper()
    # Bonus 1:2 means 1 new per 2 held -> total ratio 3:2 = 1.5x.
    # Split 1:2 means each share becomes 2 -> ratio = 2.0 (often written
    # as 2:1 in NSE feeds but sometimes 1:2 ambiguously).
    if any(h in upper for h in _BONUS_RE_HINTS):
        return (a + b) / b  # 1:2 bonus -> 1.5; 1:1 -> 2.0
    # Split: 2:1 (new:old) -> 2.0; 1:2 (old:new face value) -> 2.0.
    # We canonicalize as max/min to be tolerant of NSE feed
    # inconsistencies between "1:10 face split" vs "10:1".
    return max(a, b) / min(a, b)


def fetch_corp_actions(conn, ticker: str) -> list[dict[str, Any]]:
    """Return list of {ex_date, action_type, ratio, factor} for ticker."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT ex_date, action_type, ratio, adjustment_factor "
            "FROM corporate_actions "
            "WHERE ticker = %s AND ex_date IS NOT NULL "
            "ORDER BY ex_date ASC",
            (ticker,),
        )
        rows = cur.fetchall()
    finally:
        cur.close()
    out: list[dict[str, Any]] = []
    for ex_date, action_type, ratio, factor in rows:
        at_upper = str(action_type or "").upper()
        is_split = any(h in at_upper for h in _SPLIT_RE_HINTS)
        is_bonus = any(h in at_upper for h in _BONUS_RE_HINTS)
        if not (is_split or is_bonus):
            continue
        f = _parse_ratio(ratio) or _parse_ratio(at_upper)
        if f is None:
            continue
        out.append({
            "ex_date": ex_date,
            "action_type": at_upper,
            "ratio": ratio,
            "factor": f,
        })
    return out


def derive_adj_close_from_corp_actions(
    closes: list[tuple[date, float]],
    actions: list[dict[str, Any]],
) -> dict[date, float]:
    """Walk closes oldest->newest, applying split/bonus factors.

    For an event on ex_date with factor F (e.g. 2.0 for a 2-for-1
    split), every close BEFORE ex_date gets divided by F so the
    pre-event prices line up with post-event prices on the same per-
    share basis.

    Returns {trade_date: adj_close}. Closes after the most recent
    action are unchanged.
    """
    if not closes:
        return {}
    # Sort actions oldest->newest.
    actions_sorted = sorted(actions, key=lambda a: a["ex_date"])
    # Cumulative factor for each date = product of factors for all
    # actions whose ex_date is STRICTLY AFTER this date.
    out: dict[date, float] = {}
    for td, c in closes:
        cum = 1.0
        for act in actions_sorted:
            if act["ex_date"] > td:
                cum *= float(act["factor"])
        out[td] = c / cum if cum > 0 else c
    return out


# ──────────────────────────────────────────────────────────────────────
# Reconcile + write
# ──────────────────────────────────────────────────────────────────────


def reconcile(
    yf_series: list[tuple[date, float, float]],
    derived: dict[date, float],
) -> tuple[dict[date, tuple[float, float, str, float | None]], int]:
    """For each date present in BOTH sources, pick the final adj_close.

    Returns (final_by_date, n_discrepancies).
    ``final_by_date[d] = (close, adj_close_final, source, factor)``.
    """
    final: dict[date, tuple[float, float, str, float | None]] = {}
    discrepancies = 0
    for td, close, yf_adj in yf_series:
        if close <= 0:
            continue
        # Always have yfinance.
        chosen_adj = yf_adj
        source = "yfinance"
        factor = yf_adj / close if close else None
        # If we have an independent derivation, reconcile.
        d_adj = derived.get(td)
        if d_adj is not None and yf_adj > 0 and d_adj > 0:
            rel = abs(d_adj - yf_adj) / yf_adj
            if rel > RECONCILE_TOLERANCE:
                discrepancies += 1
                # Conservative: pick the smaller adjustment magnitude
                # (closer to raw close). This is the safer choice when
                # one source has spurious extra "splits" (cf. the
                # July-2023 HDFC merger that yfinance misclassified).
                yf_delta = abs(close - yf_adj)
                d_delta = abs(close - d_adj)
                if d_delta < yf_delta:
                    chosen_adj = d_adj
                    source = "reconciled"
                    factor = d_adj / close
                else:
                    source = "reconciled"
                    # keep yfinance value but flag as reconciled
        final[td] = (close, chosen_adj, source, factor)
    return final, discrepancies


def write_adj_close(
    conn,
    ticker: str,
    final: dict[date, tuple[float, float, str, float | None]],
    actions: list[dict[str, Any]],
) -> tuple[int, int]:
    """Write final adj_close to daily_prices + log every change.

    Returns (rows_updated, rows_logged).
    """
    if not final:
        return (0, 0)
    cur = conn.cursor()
    rows_updated = 0
    rows_logged = 0
    corp_actions_json = json.dumps({
        "splits": [
            {"ex_date": str(a["ex_date"]), "ratio": a["ratio"], "factor": a["factor"]}
            for a in actions if "SPLIT" in a["action_type"] or "FACE" in a["action_type"]
        ],
        "bonuses": [
            {"ex_date": str(a["ex_date"]), "ratio": a["ratio"], "factor": a["factor"]}
            for a in actions if "BONUS" in a["action_type"]
        ],
    })
    try:
        # Fetch existing (close_price, adj_close) for each date in final
        # so we can compute the delta. Bulk-fetch is faster than N
        # roundtrips.
        td_list = list(final.keys())
        cur.execute(
            "SELECT trade_date, close_price, adj_close FROM daily_prices "
            "WHERE ticker = %s AND trade_date = ANY(%s)",
            (ticker, td_list),
        )
        before_by_td = {td: (cp, ac) for td, cp, ac in cur.fetchall()}

        # Build the UPDATE batch. We only write where (a) the row exists
        # in daily_prices and (b) the new adj_close materially differs
        # from what's there (or it's NULL).
        for td, (close, new_adj, source, factor) in final.items():
            row = before_by_td.get(td)
            if row is None:
                continue  # daily_prices doesn't have this date — skip
            db_close, db_adj = row
            # Only update + log if the value actually changes.
            if db_adj is not None and abs(float(db_adj) - new_adj) < 1e-6:
                continue
            cur.execute(
                "UPDATE daily_prices SET adj_close = %s "
                "WHERE ticker = %s AND trade_date = %s",
                (new_adj, ticker, td),
            )
            rows_updated += cur.rowcount
            cur.execute(
                "INSERT INTO price_adjustment_log "
                "(ticker, trade_date, close_price, adj_close_before, "
                " adj_close_after, adjustment_factor, source, corp_actions) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                (
                    ticker, td,
                    float(db_close) if db_close is not None else None,
                    float(db_adj) if db_adj is not None else None,
                    new_adj,
                    factor,
                    source,
                    corp_actions_json,
                ),
            )
            rows_logged += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return rows_updated, rows_logged


# ──────────────────────────────────────────────────────────────────────
# Per-ticker worker
# ──────────────────────────────────────────────────────────────────────


def process_ticker(ticker: str, db_url: str) -> dict[str, Any]:
    """Full pipeline for one ticker. Returns summary dict."""
    import psycopg2
    summary: dict[str, Any] = {
        "ticker": ticker,
        "status": "pending",
        "rows_updated": 0,
        "rows_logged": 0,
        "discrepancies": 0,
        "error": None,
    }
    try:
        yf_series = fetch_yfinance_adj_close(ticker)
        if yf_series is None:
            summary["status"] = "no_yfinance_data"
            summary["error"] = "yfinance returned no data"
            return summary

        conn = psycopg2.connect(db_url)
        try:
            actions = fetch_corp_actions(conn, ticker)
            closes_only = [(td, c) for (td, c, _adj) in yf_series]
            derived = derive_adj_close_from_corp_actions(closes_only, actions) if actions else {}
            final, discrepancies = reconcile(yf_series, derived)
            rows_updated, rows_logged = write_adj_close(conn, ticker, final, actions)
            summary["status"] = "ok"
            summary["rows_updated"] = rows_updated
            summary["rows_logged"] = rows_logged
            summary["discrepancies"] = discrepancies
            return summary
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        summary["status"] = "error"
        summary["error"] = f"{type(exc).__name__}: {exc}"
        return summary


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def _fetch_active_tickers(db_url: str) -> list[str]:
    import psycopg2
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT ticker FROM stocks WHERE is_active = TRUE ORDER BY ticker"
        )
        rows = [r[0] for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", help="Comma-separated subset (default: full active universe)")
    ap.add_argument("--workers", type=int, default=5, help="Parallel workers (default: 5)")
    ap.add_argument("--resume", action="store_true",
                    help="Skip tickers already in checkpoint with status=ok")
    ap.add_argument("--reset-checkpoint", action="store_true",
                    help="Delete checkpoint + dead-letter and start fresh")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL not set")
        return 2

    if args.reset_checkpoint:
        CHECKPOINT_PATH.unlink(missing_ok=True)
        DEAD_LETTER_PATH.unlink(missing_ok=True)
        log.info("checkpoint + dead-letter cleared")

    checkpoint = _load_checkpoint()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = _fetch_active_tickers(db_url)

    if args.resume:
        before = len(tickers)
        tickers = [t for t in tickers if not checkpoint.get(t, "").startswith("ok@")]
        log.info("resume mode: %d tickers (skipped %d already done)",
                 len(tickers), before - len(tickers))

    log.info("processing %d tickers with %d workers", len(tickers), args.workers)
    started = time.time()
    n_ok = n_err = n_no_data = 0
    total_updated = total_logged = total_disc = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_ticker, t, db_url): t for t in tickers}
        for i, fut in enumerate(as_completed(futures), 1):
            t = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:  # noqa: BLE001
                result = {"ticker": t, "status": "error", "error": str(exc),
                          "rows_updated": 0, "rows_logged": 0, "discrepancies": 0}

            status = result["status"]
            if status == "ok":
                n_ok += 1
                total_updated += result["rows_updated"]
                total_logged += result["rows_logged"]
                total_disc += result["discrepancies"]
                _record_done(checkpoint, t, "ok")
            elif status == "no_yfinance_data":
                n_no_data += 1
                _record_done(checkpoint, t, "no_data")
            else:
                n_err += 1
                _record_dead_letter(t, result.get("error") or "unknown")
                _record_done(checkpoint, t, "error")

            if i % 25 == 0 or i == len(tickers):
                elapsed = time.time() - started
                log.info(
                    "[%d/%d] ok=%d no_data=%d err=%d updated=%d logged=%d disc=%d (%.1fs)",
                    i, len(tickers), n_ok, n_no_data, n_err,
                    total_updated, total_logged, total_disc, elapsed,
                )

    elapsed = time.time() - started
    log.info("DONE in %.1fs", elapsed)
    log.info("  ok                  : %d", n_ok)
    log.info("  no_yfinance_data    : %d", n_no_data)
    log.info("  error (dead-letter) : %d", n_err)
    log.info("  rows_updated        : %d", total_updated)
    log.info("  rows_logged         : %d", total_logged)
    log.info("  discrepancies       : %d", total_disc)
    if n_err:
        log.warning("dead-letter at %s — review and rerun those tickers",
                    DEAD_LETTER_PATH)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
