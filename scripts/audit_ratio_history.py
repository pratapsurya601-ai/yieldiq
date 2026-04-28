#!/usr/bin/env python3
"""Audit `ratio_history` for unit-bug remnants and stale rows.

Purpose
-------
Peer-cap on the analysis page reads ``pe_ratio`` and ``ev_ebitda`` from
``ratio_history`` to build a sector multiple. When that table has NULL
or unit-bug-corrupted values, peer-cap silently no-ops on exactly the
mid-cap tickers it was supposed to fix (JUSTDIAL, EMAMILTD, NATCOPHARM,
SANOFI, ZYDUSLIFE, MAYURUNIQ — all surfaced 60-91% MoS in the
2026-04-28 audit).

This script is a pre-flight check: it reads the latest ratio_history
row per ticker and flags four classes of suspect data:

  1. ``null_pe`` — pe_ratio IS NULL on the latest row (and price + PAT
     are both populated, so a value SHOULD exist).
  2. ``sub_one_pe`` — pe_ratio < 1.0. Pre-PR-#126 _normalize_pct
     double-multiplied small percent values; a residual artifact is
     P/E values around 0.30 (HCLTECH), 0.25 (WIPRO), 0.36 (TECHM).
  3. ``hyper_pct`` — roe or roce > 100. The other side of the same
     unit-bug class — an unscaled decimal that already lived in
     percent form got multiplied by 100 anyway.
  4. ``stale`` — most recent period_end is more than 90 days behind
     today's date. Indicates the build_ratio_history pipeline never
     reached this ticker, or last reached it more than a quarter ago.

Output
------
Writes a CSV to ``--out`` (default: ``ratio_history_audit.csv``) with
columns: ticker, flag, latest_period_end, pe_ratio, ev_ebitda,
pb_ratio, roe, roce, days_stale, remediation_hint. Also prints a
human-readable summary to stdout.

Exit codes
----------
    0  — audit completed (CSV written), regardless of flag count.
    1  — DB connectivity / query failure.

Usage
-----
    DATABASE_URL=postgres://... python scripts/audit_ratio_history.py
    DATABASE_URL=postgres://... python scripts/audit_ratio_history.py \
        --out /tmp/audit.csv --tickers JUSTDIAL,EMAMILTD,SANOFI
    DATABASE_URL=postgres://... python scripts/audit_ratio_history.py \
        --include-canary  # also audit canary_stocks_50 + canary_outliers_7

Discipline
----------
Read-only. Never writes to ratio_history. Never touches CACHE_VERSION.
Safe to run on prod against the live Neon DSN.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("audit_ratio_history")


# ──────────────────────────────────────────────────────────────────────
# Thresholds — tuned to the 2026-04-28 audit findings
# ──────────────────────────────────────────────────────────────────────
SUB_ONE_PE_MAX = 1.0          # P/E values below this are suspect unit bugs.
HYPER_PCT_MAX = 100.0         # ROE/ROCE above this are also suspect.
STALE_DAYS = 90               # Latest period_end older than this = stale.

# Sane bounds for the verify_peer_cap_inputs.py downstream check. Kept
# here so the audit and verify scripts share a single source-of-truth.
PE_BOUNDS = (5.0, 50.0)
EV_EBITDA_BOUNDS = (3.0, 25.0)


# Tickers explicitly called out in the launch audit. Always audited
# unless --tickers narrows the scope.
KNOWN_OUTLIERS: tuple[str, ...] = (
    "JUSTDIAL", "EMAMILTD", "NATCOPHARM",
    "SANOFI", "ZYDUSLIFE", "MAYURUNIQ",
    "HCLTECH", "WIPRO", "TECHM",
)


@dataclass
class AuditRow:
    ticker: str
    latest_period_end: date | None
    pe_ratio: float | None
    ev_ebitda: float | None
    pb_ratio: float | None
    roe: float | None
    roce: float | None
    flags: list[str]
    days_stale: int | None
    remediation: str

    def as_csv_row(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "flag": ";".join(self.flags) if self.flags else "",
            "latest_period_end": (
                self.latest_period_end.isoformat()
                if self.latest_period_end else ""
            ),
            "pe_ratio": _fmt(self.pe_ratio),
            "ev_ebitda": _fmt(self.ev_ebitda),
            "pb_ratio": _fmt(self.pb_ratio),
            "roe": _fmt(self.roe),
            "roce": _fmt(self.roce),
            "days_stale": self.days_stale if self.days_stale is not None else "",
            "remediation_hint": self.remediation,
        }


def _fmt(v: float | None) -> str:
    if v is None:
        return ""
    return f"{float(v):.4f}"


# ──────────────────────────────────────────────────────────────────────
# Audit logic — pure function so tests can drive it without a DB
# ──────────────────────────────────────────────────────────────────────
def evaluate_row(
    ticker: str,
    latest_period_end: date | None,
    pe_ratio: float | None,
    ev_ebitda: float | None,
    pb_ratio: float | None,
    roe: float | None,
    roce: float | None,
    *,
    today: date | None = None,
) -> AuditRow:
    """Apply the four-flag rule set to a single latest-row tuple.

    Pure function — used directly by ``tests/test_ratio_history_audit.py``
    with synthetic inputs.
    """
    today = today or date.today()
    flags: list[str] = []

    # 1. null_pe — but only flag when there's at least SOMETHING in the
    #    row (else we'd flag tickers that legitimately have no rows yet).
    has_any = any(
        v is not None for v in (pe_ratio, ev_ebitda, pb_ratio, roe, roce)
    )
    if pe_ratio is None and has_any:
        flags.append("null_pe")

    # 2. sub_one_pe
    if pe_ratio is not None and 0 < float(pe_ratio) < SUB_ONE_PE_MAX:
        flags.append("sub_one_pe")

    # 3. hyper_pct — flag separately so remediation can target the column
    if roe is not None and float(roe) > HYPER_PCT_MAX:
        flags.append("hyper_roe")
    if roce is not None and float(roce) > HYPER_PCT_MAX:
        flags.append("hyper_roce")

    # 4. stale
    days_stale: int | None = None
    if latest_period_end is None:
        flags.append("missing")
        days_stale = None
    else:
        days_stale = (today - latest_period_end).days
        if days_stale > STALE_DAYS:
            flags.append("stale")

    remediation = _remediation_hint(flags)

    return AuditRow(
        ticker=ticker,
        latest_period_end=latest_period_end,
        pe_ratio=pe_ratio,
        ev_ebitda=ev_ebitda,
        pb_ratio=pb_ratio,
        roe=roe,
        roce=roce,
        flags=flags,
        days_stale=days_stale,
        remediation=remediation,
    )


def _remediation_hint(flags: list[str]) -> str:
    if not flags:
        return ""
    parts = []
    if "null_pe" in flags:
        parts.append("rebuild from financials (PE NULL)")
    if "sub_one_pe" in flags:
        parts.append("rebuild — pre-#126 _normalize_pct artifact")
    if "hyper_roe" in flags or "hyper_roce" in flags:
        parts.append("rebuild — unscaled decimal multiplied by 100")
    if "stale" in flags:
        parts.append("re-run scripts/build_ratio_history.py for ticker")
    if "missing" in flags:
        parts.append("no rows — confirm financials present then build")
    return "; ".join(parts)


# ──────────────────────────────────────────────────────────────────────
# DB plumbing
# ──────────────────────────────────────────────────────────────────────
def _resolve_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit(
            "ERROR: DATABASE_URL not set. Export the Neon DSN before running."
        )
    return dsn


def _load_canary_tickers(repo_root: Path) -> list[str]:
    """Pull tickers from canary_stocks_50.json + canary_outliers_7.json."""
    out: list[str] = []
    for fname in ("canary_stocks_50.json", "canary_outliers_7.json"):
        p = repo_root / "scripts" / fname
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("could not read %s: %s", p, exc)
            continue
        for s in data.get("stocks", []):
            sym = s.get("symbol")
            if sym:
                out.append(str(sym).strip().upper())
    return out


def fetch_latest_rows(
    dsn: str, tickers: Iterable[str],
) -> list[tuple[str, date | None, float | None, float | None,
               float | None, float | None, float | None]]:
    """Return one row per ticker — the latest period_end's columns.

    Lazy-imports psycopg2 so the rest of the script (and the audit unit
    tests) don't require a Postgres driver in the venv.
    """
    try:
        import psycopg2  # type: ignore[import-not-found]
        from psycopg2.extras import execute_values  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "ERROR: psycopg2 not installed. `pip install psycopg2-binary`."
        ) from exc

    sql = """
        SELECT DISTINCT ON (ticker)
            ticker,
            period_end,
            pe_ratio,
            ev_ebitda,
            pb_ratio,
            roe,
            roce
        FROM ratio_history
        WHERE ticker = ANY(%s)
        ORDER BY ticker, period_end DESC
    """
    tickers_list = sorted({t.strip().upper() for t in tickers if t})
    with psycopg2.connect(dsn) as conn:  # type: ignore[attr-defined]
        with conn.cursor() as cur:
            cur.execute(sql, (tickers_list,))
            fetched = cur.fetchall()

    rows: list = list(fetched)
    # Ensure tickers without any rows still appear (so we can flag "missing").
    seen = {r[0] for r in rows}
    for t in tickers_list:
        if t not in seen:
            rows.append((t, None, None, None, None, None, None))
    return rows


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--tickers", default="",
        help="Comma-separated tickers to audit. Default: known outliers + canary if --include-canary.",
    )
    p.add_argument(
        "--include-canary", action="store_true",
        help="Also audit canary_stocks_50 + canary_outliers_7 universe.",
    )
    p.add_argument(
        "--out", default="ratio_history_audit.csv",
        help="CSV output path (default: ratio_history_audit.csv).",
    )
    p.add_argument(
        "--dry-db", action="store_true",
        help="Skip DB; emit empty CSV. Used for self-test in CI.",
    )
    return p.parse_args(argv)


def _resolve_tickers(args: argparse.Namespace, repo_root: Path) -> list[str]:
    if args.tickers:
        explicit = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        return explicit
    out = list(KNOWN_OUTLIERS)
    if args.include_canary:
        out.extend(_load_canary_tickers(repo_root))
    # de-dupe but preserve insertion order
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t not in seen:
            deduped.append(t)
            seen.add(t)
    return deduped


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    tickers = _resolve_tickers(args, repo_root)

    if not tickers:
        logger.error("no tickers resolved — pass --tickers or --include-canary")
        return 1

    logger.info("auditing %d tickers", len(tickers))

    if args.dry_db:
        rows: list = [(t, None, None, None, None, None, None) for t in tickers]
    else:
        try:
            dsn = _resolve_dsn()
            rows = fetch_latest_rows(dsn, tickers)
        except SystemExit:
            raise
        except Exception as exc:
            logger.error("DB query failed: %s", exc)
            return 1

    today = date.today()
    audit_rows: list[AuditRow] = []
    for r in rows:
        audit_rows.append(evaluate_row(
            ticker=r[0],
            latest_period_end=r[1],
            pe_ratio=r[2],
            ev_ebitda=r[3],
            pb_ratio=r[4],
            roe=r[5],
            roce=r[6],
            today=today,
        ))

    flagged = [r for r in audit_rows if r.flags]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "ticker", "flag", "latest_period_end", "pe_ratio", "ev_ebitda",
            "pb_ratio", "roe", "roce", "days_stale", "remediation_hint",
        ])
        writer.writeheader()
        for r in audit_rows:
            writer.writerow(r.as_csv_row())

    # Stdout summary
    print()
    print("=" * 70)
    print(f"ratio_history audit — {len(audit_rows)} tickers · {len(flagged)} flagged")
    print(f"CSV: {out_path.resolve()}")
    print("=" * 70)
    by_flag: dict[str, int] = {}
    for r in flagged:
        for f in r.flags:
            by_flag[f] = by_flag.get(f, 0) + 1
    for f in sorted(by_flag):
        print(f"  {f:14s} {by_flag[f]}")
    print()
    if flagged:
        print("Flagged tickers (first 20):")
        for r in flagged[:20]:
            print(f"  {r.ticker:14s} {','.join(r.flags):28s} "
                  f"PE={_fmt(r.pe_ratio):>10s}  ROE={_fmt(r.roe):>10s}  "
                  f"ROCE={_fmt(r.roce):>10s}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
