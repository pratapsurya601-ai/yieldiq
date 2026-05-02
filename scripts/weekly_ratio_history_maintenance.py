#!/usr/bin/env python3
"""Universe-wide weekly maintenance for ``ratio_history``.

Background
----------
The 2026-04-28 launch audit found that ``ratio_history`` rows can carry
stale, NULL, or sub-1 P/E values that silently break peer-cap on the
analysis page. PR #126 fixed ``_normalize_pct`` for new writes, but old
rows persist forever without active maintenance.

This script wraps the existing single-purpose tools into a self-healing
weekly cron:

  1. Audit every active ticker (``audit_ratio_history.py --all-active``).
  2. For each flagged ticker, rebuild its rows by shelling out to
     ``rebuild_ratio_history.py --ticker T --apply``.
  3. Throttle at ``--rate`` tickers/sec (default 2) so we don't hammer
     Neon during the maintenance window.
  4. Emit ``weekly_ratio_maintenance_<date>.csv`` with one row per
     processed ticker — pre-flag, post-flag, post-period_end, exit_code,
     error (if any). The CSV is the audit trail the GH Actions job
     commits to ``docs/maintenance_history/``.

Discipline
----------
- Reuses existing scripts; never duplicates rebuild logic.
- ``--dry-run`` is the default — operator must opt into ``--apply`` for
  writes (mirrors ``rebuild_ratio_history.py``'s contract).
- Read-only audit pass always runs — even ``--dry-run`` writes the CSV
  showing what *would* be rebuilt.
- Never bumps CACHE_VERSION (per CLAUDE.md rule 2).

Usage
-----
    # Dry-run on the 9 known outliers — no DB writes, but prints the plan
    DATABASE_URL=postgres://... python scripts/weekly_ratio_history_maintenance.py

    # Dry-run on every active ticker
    DATABASE_URL=postgres://... python scripts/weekly_ratio_history_maintenance.py \
        --all-active

    # Production weekly cron (matches workflow YAML)
    DATABASE_URL=postgres://... python scripts/weekly_ratio_history_maintenance.py \
        --all-active --apply --rate 2

    # Smoke test on first 50 tickers (for first-run dry runs)
    DATABASE_URL=postgres://... python scripts/weekly_ratio_history_maintenance.py \
        --all-active --limit 50

Exit codes
----------
    0  — completed; even partial-failure runs exit 0 if at least 90% of
         flagged tickers rebuilt cleanly. The CSV is the source of truth.
    1  — DB unreachable, audit failed, or > 10% of rebuilds failed.
    2  — invalid arguments.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Make scripts/ importable so we can reuse the audit pure functions.
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import audit_ratio_history as ara  # type: ignore[import-not-found]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("weekly_ratio_maintenance")

REPO_ROOT = Path(__file__).resolve().parent.parent
FAILURE_THRESHOLD_PCT = 10.0  # >10% failed rebuilds → non-zero exit


def _audit_universe(
    tickers: list[str], dsn: str | None, *, dry_db: bool,
) -> list[ara.AuditRow]:
    """Run the audit's ``evaluate_row`` over every ticker in ``tickers``.

    Reuses ``ara.fetch_latest_rows`` so we don't reinvent the SQL.
    """
    if dry_db or not dsn:
        # Synthetic mode for tests — every ticker comes back blank, which
        # means evaluate_row will tag them all as "missing".
        rows = [(t, None, None, None, None, None, None) for t in tickers]
    else:
        rows = ara.fetch_latest_rows(dsn, tickers)
    today = date.today()
    return [
        ara.evaluate_row(
            ticker=r[0],
            latest_period_end=r[1],
            pe_ratio=r[2],
            ev_ebitda=r[3],
            pb_ratio=r[4],
            roe=r[5],
            roce=r[6],
            today=today,
        )
        for r in rows
    ]


def _rebuild_ticker(
    ticker: str, dsn: str, *, dry_run: bool,
) -> tuple[int, str]:
    """Shell out to rebuild_ratio_history.py for one ticker.

    Returns ``(exit_code, error_summary)``. ``error_summary`` is "" on
    success.
    """
    rebuilder = REPO_ROOT / "scripts" / "rebuild_ratio_history.py"
    if not rebuilder.exists():
        return 1, f"rebuilder script missing: {rebuilder}"

    cmd = [sys.executable, str(rebuilder), "--ticker", ticker]
    if dry_run:
        cmd.append("--dry-run")
    else:
        cmd.append("--apply")

    env = os.environ.copy()
    env["DATABASE_URL"] = dsn

    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        return 1, "timeout (>300s)"
    except Exception as exc:  # pragma: no cover — defensive
        return 1, f"subprocess error: {exc}"

    if proc.returncode != 0:
        # Trim stderr to first 200 chars so the CSV stays readable.
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        err_msg = err[-1][:200] if err else f"exit={proc.returncode}"
        return proc.returncode, err_msg
    return 0, ""


def _post_audit(
    tickers: list[str], dsn: str | None, *, dry_db: bool,
) -> dict[str, ara.AuditRow]:
    rows = _audit_universe(tickers, dsn, dry_db=dry_db)
    return {r.ticker: r for r in rows}


def run(
    *,
    tickers: list[str],
    dsn: str | None,
    apply: bool,
    rate: float,
    out_csv: Path,
    dry_db: bool = False,
    rebuild_fn=_rebuild_ticker,  # injectable for tests
) -> int:
    """Top-level driver — audit, rebuild flagged, post-audit, write CSV.

    Returns the script exit code (0 healthy, 1 too many failures).
    """
    if not tickers:
        logger.error("no tickers to audit — aborting")
        return 2

    logger.info(
        "%s — auditing %d ticker(s)",
        "APPLY" if apply else "DRY-RUN",
        len(tickers),
    )

    pre = _audit_universe(tickers, dsn, dry_db=dry_db)
    flagged = [r for r in pre if r.flags]
    logger.info(
        "audit: %d flagged of %d (%.1f%%)",
        len(flagged), len(tickers),
        100.0 * len(flagged) / max(1, len(tickers)),
    )

    # Throttle: rate tickers per second → sleep 1/rate between calls.
    sleep_s = 0.0 if rate <= 0 else 1.0 / float(rate)

    results: list[dict[str, Any]] = []
    failures = 0
    pre_by_ticker = {r.ticker: r for r in pre}

    for idx, row in enumerate(flagged, start=1):
        rc, err = rebuild_fn(row.ticker, dsn or "", dry_run=not apply)
        if rc != 0:
            failures += 1
            logger.warning(
                "[%d/%d] %s: rebuild failed (rc=%d): %s",
                idx, len(flagged), row.ticker, rc, err,
            )
        else:
            logger.info(
                "[%d/%d] %s: rebuild OK", idx, len(flagged), row.ticker,
            )
        if sleep_s > 0 and idx < len(flagged):
            time.sleep(sleep_s)

    # ── Universe-wide stale sweep ──
    # Per-ticker rebuild above only catches tickers flagged by the audit
    # heuristics (null_pe / sub_one_pe / hyper_pct / stale latest_period_end).
    # It does NOT catch the "financials backfilled AFTER ratio_history was
    # last computed" failure mode that hit PNB/RBLBANK/UCOBANK/PSB/SOUTHBANK
    # in the 2026-05 hotfix. Shell out to build_ratio_history --rebuild-stale
    # here so future financials backfills auto-trigger ratio rebuilds.
    if apply and not dry_db:
        builder = REPO_ROOT / "scripts" / "build_ratio_history.py"
        if builder.exists() and dsn:
            logger.info("running build_ratio_history.py --rebuild-stale")
            env = os.environ.copy()
            env["DATABASE_URL"] = dsn
            try:
                proc = subprocess.run(
                    [sys.executable, str(builder), "--rebuild-stale"],
                    env=env, capture_output=True, text=True, timeout=3600,
                )
                if proc.returncode != 0:
                    logger.warning(
                        "build_ratio_history --rebuild-stale exited rc=%d: %s",
                        proc.returncode,
                        (proc.stderr or proc.stdout or "")[-200:],
                    )
                else:
                    logger.info("build_ratio_history --rebuild-stale OK")
            except subprocess.TimeoutExpired:
                logger.warning(
                    "build_ratio_history --rebuild-stale timed out (>3600s)"
                )
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning(
                    "build_ratio_history --rebuild-stale errored: %s", exc,
                )
        else:
            logger.warning(
                "skipping --rebuild-stale sweep: builder=%s exists=%s dsn=%s",
                builder, builder.exists(), bool(dsn),
            )

    # Post-audit only if we actually applied; in dry-run the second pass
    # would just show identical state.
    post_by_ticker: dict[str, ara.AuditRow] = {}
    if apply and not dry_db:
        try:
            post_by_ticker = _post_audit(
                [r.ticker for r in flagged], dsn, dry_db=dry_db,
            )
        except Exception as exc:
            logger.warning("post-audit failed: %s", exc)

    for r in pre:
        post = post_by_ticker.get(r.ticker)
        results.append({
            "ticker": r.ticker,
            "pre_flags": ";".join(r.flags),
            "pre_period_end": (
                r.latest_period_end.isoformat()
                if r.latest_period_end else ""
            ),
            "pre_pe_ratio": ara._fmt(r.pe_ratio),
            "post_flags": ";".join(post.flags) if post else "",
            "post_period_end": (
                post.latest_period_end.isoformat()
                if post and post.latest_period_end else ""
            ),
            "post_pe_ratio": ara._fmt(post.pe_ratio) if post else "",
            "rebuilt": "yes" if r.flags else "no",
            "remediation_hint": r.remediation,
        })

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker", "pre_flags", "pre_period_end", "pre_pe_ratio",
        "post_flags", "post_period_end", "post_pe_ratio",
        "rebuilt", "remediation_hint",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print()
    print("=" * 70)
    print(f"weekly ratio_history maintenance — {datetime.now().isoformat(timespec='seconds')}")
    print(f"  audited:  {len(tickers)}")
    print(f"  flagged:  {len(flagged)}")
    print(f"  rebuilt:  {len(flagged) - failures}{'  (dry-run)' if not apply else ''}")
    print(f"  failed:   {failures}")
    print(f"  CSV:      {out_csv.resolve()}")
    print("=" * 70)

    if not flagged:
        return 0
    fail_pct = 100.0 * failures / len(flagged)
    if fail_pct > FAILURE_THRESHOLD_PCT:
        logger.error(
            "rebuild failure rate %.1f%% exceeded %.1f%% threshold",
            fail_pct, FAILURE_THRESHOLD_PCT,
        )
        return 1
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--tickers", default="",
        help="Comma-separated tickers. Overrides --all-active.",
    )
    p.add_argument(
        "--all-active", action="store_true",
        help="Audit every active ticker (stocks WHERE is_active=TRUE).",
    )
    p.add_argument(
        "--limit", type=int, default=0,
        help="Limit ticker count (0=no limit).",
    )
    p.add_argument(
        "--apply", action="store_true",
        help="Actually rebuild flagged tickers. Default is dry-run.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="(Default) audit + plan only, no rebuilds.",
    )
    p.add_argument(
        "--rate", type=float, default=2.0,
        help="Rebuilds per second (throttle for Neon). Default 2.",
    )
    today = date.today().isoformat()
    p.add_argument(
        "--out",
        default=f"weekly_ratio_maintenance_{today}.csv",
        help="Output CSV path.",
    )
    p.add_argument(
        "--dry-db", action="store_true",
        help="Skip DB; used for self-test in CI.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.dry_run and args.apply:
        logger.error("--dry-run and --apply are mutually exclusive")
        return 2

    apply = bool(args.apply)
    repo_root = REPO_ROOT

    # Resolve ticker universe.
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.all_active:
        if args.dry_db:
            tickers = list(ara.KNOWN_OUTLIERS)
        else:
            try:
                dsn_for_lookup = ara._resolve_dsn()
            except SystemExit:
                logger.error("--all-active requires DATABASE_URL")
                return 1
            try:
                tickers = ara.fetch_active_tickers(dsn_for_lookup)
            except Exception as exc:
                logger.error("could not fetch active tickers: %s", exc)
                return 1
    else:
        tickers = list(ara.KNOWN_OUTLIERS)

    if args.limit and args.limit > 0:
        tickers = tickers[: args.limit]

    if not tickers:
        logger.error("no tickers resolved")
        return 1

    dsn: str | None
    if args.dry_db:
        dsn = None
    else:
        try:
            dsn = ara._resolve_dsn()
        except SystemExit:
            if not apply:
                # Dry-run: still useful to show the plan without DSN.
                dsn = None
            else:
                raise

    return run(
        tickers=tickers,
        dsn=dsn,
        apply=apply,
        rate=args.rate,
        out_csv=Path(args.out),
        dry_db=args.dry_db,
    )


if __name__ == "__main__":
    sys.exit(main())
