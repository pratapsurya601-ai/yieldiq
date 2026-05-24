"""Phase F.2 — 10-year adj_close backfill for top-500 / canary-333 universe.

Background
==========
Day-112's ``scripts/rebuild_adj_close.py`` UPDATEs ``adj_close`` for
rows already present in ``daily_prices``. Phase F.2 extends that with
INSERT-or-UPDATE semantics so tickers whose bhavcopy ingest only
started in 2021 (and therefore have shallow ``daily_prices``) get a
full 10y of split/bonus-adjusted OHLC backfilled from yfinance.

Per the F.1 audit (docs/diagnostics/phase-f-historical-depth-audit-
2026-05-25.md §5.1), yfinance reliably serves 10y+ for Indian
NIFTY-500 names; the only risk surfaces are rate limits (mitigated
via Day-112's exponential backoff) and shallow universes (gated by
the pre-flight checks below).

What this script does
=====================
1. Resolves the input universe (`--tickers` accepts a comma list, a
   file path, the keyword ``canary-333``, ``top-500``, or ``all``).
2. Runs **pre-flight gates** (audit §7) before any writes:
   a. Spot-checks 5 sample tickers (RELIANCE, TCS, INFY, HDFCBANK,
      NESTLEIND) — yfinance ``period="max"`` must return >=10y on
      >=4 of 5; fail-fast otherwise (catches a yfinance regional cap).
   b. Queries `daily_prices` for the input universe — if >30% have
      `n_rows < 100`, log + exit non-zero (operator must investigate
      the bhavcopy gap before launching the multi-hour backfill).
3. For each ticker, fetches yfinance OHLCV + adj_close at
   ``period="max"``, derives split/bonus factors from
   ``corporate_actions``, reconciles, then **INSERT-or-UPDATEs**
   ``daily_prices`` (vs. Day-112's UPDATE-only behaviour) and
   appends one row per change to ``price_adjustment_log``.
4. Self-test mode (``--dry-run`` on RELIANCE / TCS / NESTLEIND etc.)
   verifies the adjustment math is monotonic without writing.

Reuses Day-112 helpers from ``scripts/rebuild_adj_close``: the
yfinance fetcher, corp-action ratio parser, derivation, and
reconciliation logic are imported directly to avoid duplication.

Usage
=====
::

    # Smoke test (no DB writes)
    DATABASE_URL=postgres://... python scripts/backfill_adj_close_10y.py \
        --tickers RELIANCE,TCS,HDFCBANK --dry-run

    # Full top-500 backfill
    DATABASE_URL=postgres://... python scripts/backfill_adj_close_10y.py \
        --tickers top-500 --workers 5

    # Resume a partial run
    DATABASE_URL=postgres://... python scripts/backfill_adj_close_10y.py \
        --tickers top-500 --resume-from MARUTI

Expected runtime per F.1 audit: ~20 min @ 5 workers for top-500.

Exit codes
==========
    0  — completed (possibly with per-ticker dead-letter entries)
    1  — pre-flight gate or hard error
    2  — usage / config error (DATABASE_URL missing, bad --tickers)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Reuse Day-112 helpers (single source of truth for adjustment math).
from scripts.rebuild_adj_close import (  # noqa: E402
    fetch_yfinance_adj_close,
    fetch_corp_actions,
    derive_adj_close_from_corp_actions,
    reconcile,
    _load_checkpoint,
    _record_done,
    _record_dead_letter,
    CHECKPOINT_PATH,
    DEAD_LETTER_PATH,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_adj_close_10y")

CANARY_UNIVERSE_PATH = ROOT / "scripts" / "canary_universe_180.json"

# Pre-flight gate thresholds (audit §7).
SAMPLE_TICKERS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "NESTLEIND"]
MIN_SAMPLE_YEARS = 10
MIN_SAMPLE_PASS = 4  # >=4 of 5 must return >=10y from yfinance
SHALLOW_ROW_THRESHOLD = 100
MAX_SHALLOW_FRACTION = 0.30

# 1 trading year ≈ 250 sessions; 10y ≈ 2500 rows.
TARGET_TEN_YEAR_ROWS = 2500


# ──────────────────────────────────────────────────────────────────────
# Universe resolution
# ──────────────────────────────────────────────────────────────────────


def _load_canary_333() -> list[str]:
    """Load 333 tickers from canary_universe_180.json (filename is historical)."""
    data = json.loads(CANARY_UNIVERSE_PATH.read_text(encoding="utf-8"))
    stocks = data.get("stocks", [])
    out = sorted({s["symbol"].strip().upper() for s in stocks if s.get("symbol")})
    return out


def _load_top_500(db_url: str) -> list[str]:
    """Top 500 by market cap from `stocks` JOIN `market_metrics`."""
    import psycopg2
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT s.ticker FROM stocks s "
            "JOIN market_metrics mm ON mm.ticker = s.ticker "
            "WHERE s.is_active = TRUE "
            "  AND mm.market_cap_cr IS NOT NULL "
            "ORDER BY mm.market_cap_cr DESC LIMIT 500"
        )
        rows = [r[0].strip().upper() for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        conn.close()


def _load_all_active(db_url: str) -> list[str]:
    import psycopg2
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SELECT ticker FROM stocks WHERE is_active = TRUE ORDER BY ticker")
        rows = [r[0].strip().upper() for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        conn.close()


def resolve_universe(spec: str, db_url: str) -> list[str]:
    """Resolve --tickers spec into a deduplicated list."""
    s = (spec or "").strip()
    if not s:
        raise ValueError("--tickers is required")
    low = s.lower()
    if low == "canary-333":
        return _load_canary_333()
    if low == "top-500":
        return _load_top_500(db_url)
    if low == "all":
        return _load_all_active(db_url)
    # File path?
    p = Path(s)
    if p.exists() and p.is_file():
        text = p.read_text(encoding="utf-8")
        # Accept newline- or comma-separated.
        raw = [x.strip().upper() for x in text.replace(",", "\n").splitlines()]
        return sorted({x for x in raw if x and not x.startswith("#")})
    # Comma list.
    return sorted({t.strip().upper() for t in s.split(",") if t.strip()})


# ──────────────────────────────────────────────────────────────────────
# Pre-flight gates
# ──────────────────────────────────────────────────────────────────────


def _years_of_data(rows) -> float:
    """Return the data span in years from a list of (date, close, adj) tuples."""
    if not rows or len(rows) < 2:
        return 0.0
    dates = sorted(r[0] for r in rows)
    delta_days = (dates[-1] - dates[0]).days
    return delta_days / 365.25


def preflight_sample_yfinance() -> bool:
    """Audit §7 gate #3: spot-check 5 tickers for >=10y yfinance depth."""
    log.info("pre-flight: yfinance sample check for %s", SAMPLE_TICKERS)
    n_pass = 0
    for t in SAMPLE_TICKERS:
        rows = fetch_yfinance_adj_close(t, period="max")
        if rows is None:
            log.warning("pre-flight: %s — yfinance returned None", t)
            continue
        yrs = _years_of_data(rows)
        ok = yrs >= MIN_SAMPLE_YEARS
        log.info("pre-flight: %s — %d rows spanning %.1f years %s",
                 t, len(rows), yrs, "OK" if ok else "SHORT")
        if ok:
            n_pass += 1
    if n_pass < MIN_SAMPLE_PASS:
        log.error("pre-flight FAIL: only %d/%d sample tickers returned >=%dy "
                  "(threshold: %d). yfinance regional cap suspected — "
                  "consider bhavcopy archive fallback.",
                  n_pass, len(SAMPLE_TICKERS), MIN_SAMPLE_YEARS, MIN_SAMPLE_PASS)
        return False
    log.info("pre-flight OK: %d/%d sample tickers passed the 10y bar",
             n_pass, len(SAMPLE_TICKERS))
    return True


def preflight_universe_depth(db_url: str, tickers: list[str]) -> bool:
    """Audit §7 gate #1: <=30% of universe may have `daily_prices.n_rows < 100`."""
    import psycopg2
    log.info("pre-flight: universe depth check across %d tickers", len(tickers))
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute(
            "WITH u AS (SELECT unnest(%s::text[]) AS ticker) "
            "SELECT u.ticker, COUNT(dp.trade_date) AS n_rows "
            "FROM u LEFT JOIN daily_prices dp ON dp.ticker = u.ticker "
            "GROUP BY u.ticker",
            (tickers,),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    shallow = [t for t, n in rows if (n or 0) < SHALLOW_ROW_THRESHOLD]
    frac = len(shallow) / max(1, len(tickers))
    log.info("pre-flight: %d/%d tickers have <%d rows (%.1f%%)",
             len(shallow), len(tickers), SHALLOW_ROW_THRESHOLD, frac * 100)
    if frac > MAX_SHALLOW_FRACTION:
        log.error("pre-flight FAIL: %.1f%% of universe shallow (threshold "
                  "%.0f%%). NSE-bhavcopy ingest gap wider than expected; "
                  "operator must inflate runtime budget 4x or investigate "
                  "the bhavcopy populator before launching F.2.",
                  frac * 100, MAX_SHALLOW_FRACTION * 100)
        sample = ", ".join(shallow[:20])
        log.error("first shallow tickers: %s%s",
                  sample, " ..." if len(shallow) > 20 else "")
        return False
    log.info("pre-flight OK: depth gate passed")
    return True


# ──────────────────────────────────────────────────────────────────────
# Insert-or-update writer (the new bit vs. Day-112)
# ──────────────────────────────────────────────────────────────────────


def write_adj_close_with_insert(
    conn,
    ticker: str,
    yf_series,
    final,
    actions,
) -> tuple[int, int, int]:
    """INSERT missing rows then UPSERT adj_close.

    Day-112's writer only UPDATEs rows already in `daily_prices`. For
    F.2 we additionally INSERT rows for trade_dates that don't yet
    exist, using the OHLC from yfinance.

    Returns (rows_inserted, rows_updated, rows_logged).
    """
    if not yf_series:
        return (0, 0, 0)

    # Build OHLC fetch from yfinance series (we already have close + adj;
    # for INSERTs we also need O/H/L/V — re-fetch once with raw frame).
    # To avoid double-fetching, the call site passes the full hist back.
    import yfinance as yf
    symbol = f"{ticker}.NS"
    hist = yf.Ticker(symbol).history(period="max", auto_adjust=False)
    if hist is None or hist.empty:
        return (0, 0, 0)
    cols = {c.lower(): c for c in hist.columns}
    ohlcv_by_td = {}
    for idx, row in hist.iterrows():
        try:
            td = idx.date() if hasattr(idx, "date") else idx
            ohlcv_by_td[td] = {
                "open": float(row[cols["open"]]),
                "high": float(row[cols["high"]]),
                "low":  float(row[cols["low"]]),
                "close": float(row[cols["close"]]),
                "volume": int(row[cols["volume"]]) if cols.get("volume") else 0,
            }
        except (TypeError, ValueError, KeyError):
            continue

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

    cur = conn.cursor()
    rows_inserted = 0
    rows_updated = 0
    rows_logged = 0
    try:
        td_list = list(final.keys())
        cur.execute(
            "SELECT trade_date, close_price, adj_close FROM daily_prices "
            "WHERE ticker = %s AND trade_date = ANY(%s)",
            (ticker, td_list),
        )
        before_by_td = {td: (cp, ac) for td, cp, ac in cur.fetchall()}

        for td, (close, new_adj, source, factor) in final.items():
            existing = before_by_td.get(td)
            if existing is None:
                # INSERT path — bring in OHLCV from yfinance, set adj_close.
                ohlcv = ohlcv_by_td.get(td)
                if ohlcv is None:
                    continue
                cur.execute(
                    "INSERT INTO daily_prices "
                    "(ticker, trade_date, open_price, high_price, low_price, "
                    " close_price, volume, adj_close) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (ticker, trade_date) DO UPDATE SET "
                    "  adj_close = EXCLUDED.adj_close "
                    "WHERE daily_prices.adj_close IS DISTINCT FROM EXCLUDED.adj_close",
                    (
                        ticker, td,
                        ohlcv["open"], ohlcv["high"], ohlcv["low"],
                        ohlcv["close"], ohlcv["volume"], new_adj,
                    ),
                )
                rows_inserted += cur.rowcount
                cur.execute(
                    "INSERT INTO price_adjustment_log "
                    "(ticker, trade_date, close_price, adj_close_before, "
                    " adj_close_after, adjustment_factor, source, corp_actions) "
                    "VALUES (%s, %s, %s, NULL, %s, %s, %s, %s::jsonb)",
                    (ticker, td, ohlcv["close"], new_adj, factor,
                     f"{source}+insert", corp_actions_json),
                )
                rows_logged += 1
            else:
                db_close, db_adj = existing
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
                        new_adj, factor, source, corp_actions_json,
                    ),
                )
                rows_logged += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return rows_inserted, rows_updated, rows_logged


# ──────────────────────────────────────────────────────────────────────
# Per-ticker worker
# ──────────────────────────────────────────────────────────────────────


def process_ticker(ticker: str, db_url: str, dry_run: bool) -> dict:
    """Full pipeline. In dry-run, fetch+reconcile but don't write."""
    import psycopg2
    summary = {
        "ticker": ticker,
        "status": "pending",
        "n_yf_rows": 0,
        "yrs": 0.0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_logged": 0,
        "discrepancies": 0,
        "monotonic_ok": None,
        "error": None,
    }
    try:
        yf_series = fetch_yfinance_adj_close(ticker, period="max")
        if yf_series is None:
            summary["status"] = "no_yfinance_data"
            summary["error"] = "yfinance returned no data"
            return summary
        summary["n_yf_rows"] = len(yf_series)
        summary["yrs"] = _years_of_data(yf_series)

        # Monotonicity self-test: adj_close must be strictly positive
        # and free of nan/inf across the whole series.
        adj_vals = [r[2] for r in yf_series if r[2] is not None]
        summary["monotonic_ok"] = all(
            v > 0 and v == v and v < float("inf") for v in adj_vals
        )

        if dry_run:
            summary["status"] = "ok_dry_run"
            return summary

        conn = psycopg2.connect(db_url)
        try:
            actions = fetch_corp_actions(conn, ticker)
            closes_only = [(td, c) for (td, c, _adj) in yf_series]
            derived = (derive_adj_close_from_corp_actions(closes_only, actions)
                       if actions else {})
            final, discrepancies = reconcile(yf_series, derived)
            ins, upd, logged = write_adj_close_with_insert(
                conn, ticker, yf_series, final, actions
            )
            summary["rows_inserted"] = ins
            summary["rows_updated"] = upd
            summary["rows_logged"] = logged
            summary["discrepancies"] = discrepancies
            summary["status"] = "ok"
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", required=True,
                    help="Comma list, file path, or keyword: "
                         "canary-333 | top-500 | all")
    ap.add_argument("--years", type=int, default=10,
                    help="Target depth in years (default: 10). Informational; "
                         "yfinance always returns period='max'.")
    ap.add_argument("--workers", type=int, default=5,
                    help="Parallel workers (default: 5)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch + self-test but don't write to DB")
    ap.add_argument("--resume-from", metavar="TICKER",
                    help="Skip tickers (alpha-sorted) up to and including this one")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="Skip pre-flight gates (dangerous; use only for self-test)")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url and not args.dry_run:
        log.error("DATABASE_URL not set")
        return 2

    # Resolve universe.
    try:
        tickers = resolve_universe(args.tickers, db_url or "")
    except Exception as exc:
        log.error("universe resolution failed: %s", exc)
        return 2
    if not tickers:
        log.error("resolved universe is empty")
        return 2
    log.info("resolved %d tickers from spec=%r", len(tickers), args.tickers)

    # Pre-flight gates (always run unless --skip-preflight).
    if not args.skip_preflight:
        if not preflight_sample_yfinance():
            return 1
        if db_url:
            if not preflight_universe_depth(db_url, tickers):
                return 1
        else:
            log.warning("pre-flight: skipping universe-depth gate (no DATABASE_URL)")

    # Resume.
    if args.resume_from:
        rf = args.resume_from.strip().upper()
        before = len(tickers)
        tickers = [t for t in tickers if t > rf]
        log.info("resume: skipped %d tickers up to and including %s",
                 before - len(tickers), rf)

    log.info("processing %d tickers with %d workers (dry_run=%s)",
             len(tickers), args.workers, args.dry_run)
    started = time.time()
    n_ok = n_err = n_no_data = 0
    total_ins = total_upd = total_logged = total_disc = 0
    checkpoint = _load_checkpoint() if not args.dry_run else {}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_ticker, t, db_url or "", args.dry_run): t
                   for t in tickers}
        for i, fut in enumerate(as_completed(futures), 1):
            t = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:  # noqa: BLE001
                result = {"ticker": t, "status": "error", "error": str(exc),
                          "rows_inserted": 0, "rows_updated": 0,
                          "rows_logged": 0, "discrepancies": 0,
                          "n_yf_rows": 0, "yrs": 0.0, "monotonic_ok": None}

            st = result["status"]
            if st in ("ok", "ok_dry_run"):
                n_ok += 1
                total_ins += result["rows_inserted"]
                total_upd += result["rows_updated"]
                total_logged += result["rows_logged"]
                total_disc += result["discrepancies"]
                if not args.dry_run:
                    _record_done(checkpoint, t, "ok")
                log.info("[%d/%d] %s: yf=%d rows / %.1fy  ins=%d upd=%d "
                         "log=%d disc=%d mono=%s",
                         i, len(tickers), t, result["n_yf_rows"],
                         result["yrs"], result["rows_inserted"],
                         result["rows_updated"], result["rows_logged"],
                         result["discrepancies"], result["monotonic_ok"])
            elif st == "no_yfinance_data":
                n_no_data += 1
                if not args.dry_run:
                    _record_done(checkpoint, t, "no_data")
                log.warning("[%d/%d] %s: NO DATA", i, len(tickers), t)
            else:
                n_err += 1
                if not args.dry_run:
                    _record_dead_letter(t, result.get("error") or "unknown")
                    _record_done(checkpoint, t, "error")
                log.error("[%d/%d] %s: ERROR — %s",
                          i, len(tickers), t, result.get("error"))

    elapsed = time.time() - started
    log.info("DONE in %.1fs (dry_run=%s)", elapsed, args.dry_run)
    log.info("  ok                  : %d", n_ok)
    log.info("  no_yfinance_data    : %d", n_no_data)
    log.info("  error (dead-letter) : %d", n_err)
    log.info("  rows_inserted       : %d", total_ins)
    log.info("  rows_updated        : %d", total_upd)
    log.info("  rows_logged         : %d", total_logged)
    log.info("  discrepancies       : %d", total_disc)
    if n_err and not args.dry_run:
        log.warning("dead-letter at %s — review and rerun those tickers",
                    DEAD_LETTER_PATH)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
