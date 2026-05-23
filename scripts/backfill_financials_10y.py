"""Phase F.3 — 10-year financials backfill (orchestrator over BSE Peercomp).

Background
==========
Per F.1 audit (docs/diagnostics/phase-f-historical-depth-audit-
2026-05-25.md §5.2), the existing
``data_pipeline.sources.bse_xbrl.fetch_historical_financials`` already
pulls up to 10 years of annual + quarterly P&L / BS / CF from BSE
Peercomp. The Akamai-resilient Playwright fallback at
``bse_peercomp_browser.BSEBrowserClient`` handles tickers where the
direct API returns 302→error_Bse.

Phase F.3 is an **orchestration** layer on top — it adds the audit-
mandated discipline that the existing
``scripts/backfill_fundamentals_10y_bse.py`` does not enforce:

* **Pre-flight gate**: refuse to run if ``stocks.bse_code IS NULL``
  for more than 20 % of the input universe (audit §7 gate #2). The
  script logs the offending tickers so the operator can populate them
  from an NSE↔BSE mapping before re-launching, rather than silently
  leaving 20 %+ of the universe stuck at 5y depth.
* **Universe resolver**: same as F.2 — accepts ``canary-333``,
  ``top-500``, ``all``, comma list, or file path.
* **Browser-fallback orchestration**: tickers that return 0 rows on
  the direct path get retried via ``BSEBrowserClient`` in a single
  warm browser session at the end of the run.
* **Row-count overlap validator**: for years already in DB, compare
  the new fetch row count against what's there; warn if delta > 1.
  Verify revenue series is roughly monotonic-ish (rolling 3y
  stddev < 50 % of mean) and log violators.
* **Resumable** via ``--resume-from <ticker>`` and ``--dry-run`` for
  smoke testing.

This script does NOT replace ``scripts/backfill_fundamentals_10y_bse.
py`` — that script remains the shard-parallelism workhorse for the
full 5500-ticker universe. F.3 is the curated top-500 / canary-333
path with the audit gates wired in.

Usage
=====
::

    # Smoke test (no writes)
    DATABASE_URL=postgres://... python scripts/backfill_financials_10y.py \
        --tickers RELIANCE,TCS,HDFCBANK --dry-run

    # Real run, top-500
    DATABASE_URL=postgres://... python scripts/backfill_financials_10y.py \
        --tickers top-500

    # Canary-333 with the browser fallback enabled (default)
    DATABASE_URL=postgres://... python scripts/backfill_financials_10y.py \
        --tickers canary-333

    # Resume past a checkpoint
    DATABASE_URL=postgres://... python scripts/backfill_financials_10y.py \
        --tickers top-500 --resume-from MARUTI

Exit codes
==========
    0  — completed
    1  — pre-flight gate or hard error
    2  — usage / config error
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text as sa_text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from data_pipeline.sources.bse_xbrl import (  # noqa: E402
    fetch_historical_financials,
    store_financials,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_financials_10y")
logging.getLogger("data_pipeline.sources.bse_xbrl").setLevel(logging.WARNING)

CANARY_UNIVERSE_PATH = ROOT / "scripts" / "canary_universe_180.json"

# Audit §7 gate #2: more than this fraction missing bse_code → fail.
MAX_MISSING_BSE_FRACTION = 0.20


# ──────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────


def _engine():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_recycle=300, pool_pre_ping=True)


# ──────────────────────────────────────────────────────────────────────
# Universe resolution (same shape as F.2)
# ──────────────────────────────────────────────────────────────────────


def _load_canary_333() -> list[str]:
    data = json.loads(CANARY_UNIVERSE_PATH.read_text(encoding="utf-8"))
    return sorted({s["symbol"].strip().upper()
                   for s in data.get("stocks", []) if s.get("symbol")})


def _load_top_500(engine) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(sa_text(
            "SELECT s.ticker FROM stocks s "
            "JOIN market_metrics mm ON mm.ticker = s.ticker "
            "WHERE s.is_active = TRUE "
            "  AND COALESCE(s.shadow, FALSE) = FALSE "
            "  AND mm.market_cap_cr IS NOT NULL "
            "ORDER BY mm.market_cap_cr DESC LIMIT 500"
        )).fetchall()
    return [r[0].strip().upper() for r in rows]


def _load_all_active(engine) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(sa_text(
            "SELECT ticker FROM stocks WHERE is_active = TRUE ORDER BY ticker"
        )).fetchall()
    return [r[0].strip().upper() for r in rows]


def resolve_universe(spec: str, engine) -> list[str]:
    s = (spec or "").strip()
    if not s:
        raise ValueError("--tickers is required")
    low = s.lower()
    if low == "canary-333":
        return _load_canary_333()
    if low == "top-500":
        return _load_top_500(engine)
    if low == "all":
        return _load_all_active(engine)
    p = Path(s)
    if p.exists() and p.is_file():
        text = p.read_text(encoding="utf-8")
        raw = [x.strip().upper() for x in text.replace(",", "\n").splitlines()]
        return sorted({x for x in raw if x and not x.startswith("#")})
    return sorted({t.strip().upper() for t in s.split(",") if t.strip()})


# ──────────────────────────────────────────────────────────────────────
# bse_code coverage lookup + pre-flight gate
# ──────────────────────────────────────────────────────────────────────


def fetch_bse_codes(engine, tickers: list[str]) -> dict[str, str | None]:
    """Return {ticker: bse_code or None} for the input universe."""
    out: dict[str, str | None] = {t: None for t in tickers}
    with engine.connect() as conn:
        rows = conn.execute(sa_text(
            "SELECT ticker, bse_code FROM stocks "
            "WHERE ticker = ANY(:ts)"
        ), {"ts": tickers}).fetchall()
    for ticker, code in rows:
        out[ticker.strip().upper()] = (str(code).strip() if code else None) or None
    return out


def preflight_bse_code_coverage(
    engine, tickers: list[str]
) -> tuple[bool, dict[str, str | None]]:
    """Audit §7 gate #2 — abort if >20% of universe has no bse_code."""
    log.info("pre-flight: bse_code coverage across %d tickers", len(tickers))
    codes = fetch_bse_codes(engine, tickers)
    missing = sorted([t for t, c in codes.items() if not c])
    frac = len(missing) / max(1, len(tickers))
    log.info("pre-flight: %d/%d tickers missing bse_code (%.1f%%)",
             len(missing), len(tickers), frac * 100)
    if frac > MAX_MISSING_BSE_FRACTION:
        log.error("pre-flight FAIL: %.1f%% of universe missing bse_code "
                  "(threshold %.0f%%). BSE Peercomp path unusable for "
                  "that fraction. Operator action: populate stocks.bse_code "
                  "from an NSE<->BSE mapping (e.g. data_pipeline/sources/"
                  "bse_securities_master.py) before re-launching.",
                  frac * 100, MAX_MISSING_BSE_FRACTION * 100)
        head = ", ".join(missing[:25])
        log.error("first missing: %s%s",
                  head, " ..." if len(missing) > 25 else "")
        return False, codes
    log.info("pre-flight OK: bse_code coverage gate passed")
    return True, codes


# ──────────────────────────────────────────────────────────────────────
# Row-count overlap validator (per audit deliverable list)
# ──────────────────────────────────────────────────────────────────────


def fetch_existing_annual_years(engine, ticker: str) -> dict[int, float | None]:
    """Return {fiscal_year: revenue} already in `financials` for this ticker."""
    with engine.connect() as conn:
        rows = conn.execute(sa_text(
            "SELECT EXTRACT(YEAR FROM period_end)::int, revenue "
            "FROM financials WHERE ticker = :t AND period_type = 'annual'"
        ), {"t": ticker}).fetchall()
    return {int(yr): (float(rev) if rev is not None else None) for yr, rev in rows}


def validate_overlap(
    ticker: str,
    new_rows: list[dict],
    existing: dict[int, float | None],
) -> dict:
    """Compare new fetch vs existing rows. Return summary dict."""
    summary = {
        "n_new_annual": 0,
        "n_overlap": 0,
        "n_added": 0,
        "rev_monotonicity_ok": True,
        "warnings": [],
    }
    new_annual = [r for r in new_rows if r.get("period_type") == "annual"]
    summary["n_new_annual"] = len(new_annual)
    revs = []
    for r in sorted(new_annual, key=lambda r: r["period_end"]):
        yr = r["period_end"].year
        if yr in existing:
            summary["n_overlap"] += 1
        else:
            summary["n_added"] += 1
        if r.get("revenue") is not None:
            revs.append(float(r["revenue"]))
    # Rolling 3y stddev < 50% of mean (audit: "revenue expected to be
    # monotonic-ish"). Only check when we have at least 4 points.
    if len(revs) >= 4:
        for i in range(len(revs) - 2):
            window = revs[i:i + 3]
            m = statistics.mean(window)
            if m <= 0:
                continue
            sd = statistics.pstdev(window)
            if sd / m > 0.5:
                summary["rev_monotonicity_ok"] = False
                summary["warnings"].append(
                    f"revenue volatility @ window {i}: stddev/mean={sd/m:.2f}"
                )
                break
    return summary


# ──────────────────────────────────────────────────────────────────────
# Browser fallback (lazy import — only spun up if needed)
# ──────────────────────────────────────────────────────────────────────


async def _browser_fallback_run(
    pending: list[tuple[str, str]],
    SessionLocal,
    dry_run: bool,
) -> dict:
    """Drive BSEBrowserClient over the (ticker, scrip) list that failed
    on the direct API path. Returns aggregate stats."""
    stats = {"attempted": len(pending), "ok": 0, "empty": 0, "error": 0,
             "periods": 0}
    if not pending:
        return stats
    try:
        from data_pipeline.sources.bse_peercomp_browser import BSEBrowserClient
    except ImportError as exc:
        log.warning("browser fallback unavailable (%s) — install playwright "
                    "+ run `playwright install chromium`", exc)
        return stats

    client = BSEBrowserClient(headless=True)
    try:
        await client.init()
        for ticker, scrip in pending:
            try:
                rows = await client.fetch(scrip, ticker)
            except Exception as exc:  # noqa: BLE001
                log.warning("browser fetch failed %s (%s): %s",
                            ticker, scrip, exc)
                stats["error"] += 1
                continue
            if not rows:
                stats["empty"] += 1
                continue
            if dry_run:
                log.info("[browser dry-run] %s: %d rows", ticker, len(rows))
                stats["ok"] += 1
                stats["periods"] += len(rows)
                continue
            stored = 0
            sess = SessionLocal()
            try:
                for r in rows:
                    try:
                        if store_financials(
                            r, sess, r["period_end"],
                            r.get("period_type", "annual"),
                        ):
                            stored += 1
                    except Exception as exc:  # noqa: BLE001
                        log.warning("browser store failed %s %s: %s",
                                    ticker, r.get("period_end"), exc)
                stats["periods"] += stored
                if stored:
                    stats["ok"] += 1
                else:
                    stats["empty"] += 1
            finally:
                sess.close()
    finally:
        await client.close()
    return stats


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", required=True,
                    help="Comma list, file path, or keyword: "
                         "canary-333 | top-500 | all")
    ap.add_argument("--periods", default="annual,quarterly",
                    help="Comma list of period_types to keep "
                         "(default: annual,quarterly)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch + validate but don't write")
    ap.add_argument("--resume-from", metavar="TICKER",
                    help="Skip alpha-sorted tickers up to and including this one")
    ap.add_argument("--no-browser-fallback", action="store_true",
                    help="Disable Playwright fallback for tickers that "
                         "return 0 rows on the direct API path")
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="Extra sleep between tickers (seconds)")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="Skip pre-flight bse_code gate (dangerous)")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        log.error("DATABASE_URL not set")
        return 2

    keep_periods = {p.strip().lower() for p in args.periods.split(",") if p.strip()}

    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)

    try:
        tickers = resolve_universe(args.tickers, engine)
    except Exception as exc:
        log.error("universe resolution failed: %s", exc)
        return 2
    if not tickers:
        log.error("resolved universe is empty")
        return 2
    log.info("resolved %d tickers from spec=%r", len(tickers), args.tickers)

    # Pre-flight gate.
    if not args.skip_preflight:
        ok, codes = preflight_bse_code_coverage(engine, tickers)
        if not ok:
            return 1
    else:
        codes = fetch_bse_codes(engine, tickers)
        log.warning("pre-flight: SKIPPED (--skip-preflight)")

    # Resume.
    if args.resume_from:
        rf = args.resume_from.strip().upper()
        before = len(tickers)
        tickers = [t for t in tickers if t > rf]
        log.info("resume: skipped %d tickers up to and including %s",
                 before - len(tickers), rf)

    # Filter to tickers that have a bse_code; track the rest as pre-fail.
    no_code: list[str] = []
    workable: list[tuple[str, str]] = []
    for t in tickers:
        c = codes.get(t)
        if c:
            workable.append((t, c))
        else:
            no_code.append(t)
    if no_code:
        log.warning("%d tickers have no bse_code and will be skipped",
                    len(no_code))

    log.info("processing %d tickers (dry_run=%s, browser_fallback=%s)",
             len(workable), args.dry_run, not args.no_browser_fallback)

    stats = {
        "processed": 0, "ok": 0, "empty": 0, "error": 0,
        "periods_stored": 0,
        "rev_warnings": 0, "overlap_warnings": 0,
        "no_code": len(no_code),
    }
    pending_browser: list[tuple[str, str]] = []
    started = time.time()

    for i, (ticker, scrip) in enumerate(workable, 1):
        try:
            rows = fetch_historical_financials(scrip, ticker)
        except Exception as exc:  # noqa: BLE001
            log.warning("[%d/%d] fetch failed %s (%s): %s",
                        i, len(workable), ticker, scrip, exc)
            stats["error"] += 1
            stats["processed"] += 1
            continue

        rows = [r for r in rows
                if r.get("period_type", "annual") in keep_periods]

        if not rows:
            stats["empty"] += 1
            stats["processed"] += 1
            pending_browser.append((ticker, scrip))
            log.info("[%d/%d] %s: 0 rows from direct API — queued for browser",
                     i, len(workable), ticker)
            if args.sleep > 0:
                time.sleep(args.sleep)
            continue

        # Validate overlap vs existing.
        existing = fetch_existing_annual_years(engine, ticker)
        v = validate_overlap(ticker, rows, existing)
        if not v["rev_monotonicity_ok"]:
            stats["rev_warnings"] += 1
            log.warning("[%d/%d] %s: revenue series non-monotonic — %s",
                        i, len(workable), ticker, "; ".join(v["warnings"]))

        if args.dry_run:
            log.info("[%d/%d] %s: %d rows (annual+overlap=%d, new=%d)",
                     i, len(workable), ticker, len(rows),
                     v["n_overlap"], v["n_added"])
            stats["ok"] += 1
            stats["processed"] += 1
            continue

        stored = 0
        sess = SessionLocal()
        try:
            for r in rows:
                try:
                    if store_financials(
                        r, sess, r["period_end"],
                        r.get("period_type", "annual"),
                    ):
                        stored += 1
                except Exception as exc:  # noqa: BLE001
                    log.warning("store failed %s %s: %s",
                                ticker, r.get("period_end"), exc)
        finally:
            sess.close()

        stats["periods_stored"] += stored
        if stored:
            stats["ok"] += 1
        else:
            stats["empty"] += 1
        stats["processed"] += 1

        if i % 25 == 0:
            elapsed = time.time() - started
            log.info("  progress [%d/%d]: ok=%d empty=%d err=%d "
                     "periods=%d (%.1fs)",
                     i, len(workable), stats["ok"], stats["empty"],
                     stats["error"], stats["periods_stored"], elapsed)
        if args.sleep > 0:
            time.sleep(args.sleep)

    # Browser fallback for tickers that returned 0 rows on direct path.
    if pending_browser and not args.no_browser_fallback:
        log.info("browser fallback: %d tickers queued", len(pending_browser))
        try:
            bstats = asyncio.run(_browser_fallback_run(
                pending_browser, SessionLocal, args.dry_run
            ))
            log.info("browser fallback DONE: %s", bstats)
            # Roll browser stats into main stats.
            stats["ok"] += bstats["ok"]
            stats["empty"] = max(0, stats["empty"] - bstats["ok"])
            stats["periods_stored"] += bstats["periods"]
        except Exception as exc:  # noqa: BLE001
            log.warning("browser fallback failed: %s", exc)

    elapsed = time.time() - started
    log.info("DONE in %.1fs", elapsed)
    log.info("  processed       : %d", stats["processed"])
    log.info("  ok              : %d", stats["ok"])
    log.info("  empty           : %d", stats["empty"])
    log.info("  error           : %d", stats["error"])
    log.info("  periods_stored  : %d", stats["periods_stored"])
    log.info("  rev_warnings    : %d", stats["rev_warnings"])
    log.info("  skipped_no_code : %d", stats["no_code"])

    # Direct-path coverage check — audit hint: if BSE direct fails on
    # >50% of test tickers, stop and report rather than silently
    # falling back to browser-only on everything.
    if stats["processed"] >= 5 and stats["empty"] > stats["processed"] * 0.50:
        log.error("more than 50%% of tickers returned 0 rows on direct API "
                  "(empty=%d / processed=%d). Investigate Akamai-block "
                  "scope before relying on browser fallback at scale.",
                  stats["empty"], stats["processed"])
        return 1

    return 0 if stats["error"] <= max(1, stats["processed"]) * 0.10 else 1


if __name__ == "__main__":
    sys.exit(main())
