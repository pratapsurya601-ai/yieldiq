#!/usr/bin/env python3
"""Verify peer-cap precondition: flagged tickers have usable peer multiples.

Peer-cap on the analysis page works only when, for every audited
ticker, AT LEAST 3 same-industry peers have non-null + in-bounds
``pe_ratio`` AND ``ev_ebitda`` rows in ``ratio_history``. If fewer
than 3 peers qualify, peer-cap silently falls back to "no cap" — and
that is the exact failure mode that surfaced JUSTDIAL/EMAMILTD/etc.
at +60-91% MoS in the 2026-04-28 audit.

This script is the post-rebuild gate. Run it after
``rebuild_ratio_history.py --apply`` to confirm the peer set is
healthy enough that peer-cap will fire downstream.

Sane bounds (matching ``audit_ratio_history.py``)
  P/E:        5  ≤ value ≤ 50
  EV/EBITDA:  3  ≤ value ≤ 25

Exit codes
----------
    0  — every audited ticker has ≥3 in-bounds peers
    1  — at least one ticker failed the precondition
    2  — DB / argument failure

Usage
-----
    DATABASE_URL=postgres://... python scripts/verify_peer_cap_inputs.py
    DATABASE_URL=postgres://... python scripts/verify_peer_cap_inputs.py \
        --tickers JUSTDIAL,EMAMILTD --min-peers 3
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("verify_peer_cap_inputs")

PE_BOUNDS = (5.0, 50.0)
EV_EBITDA_BOUNDS = (3.0, 25.0)
DEFAULT_MIN_PEERS = 3


def _resolve_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit(
            "ERROR: DATABASE_URL not set. Export the Neon DSN before running."
        )
    return dsn


def _load_canary_universe(repo_root: Path) -> list[str]:
    """canary_50 + outliers_7 — the verification universe."""
    out: list[str] = []
    for fname in ("canary_stocks_50.json", "canary_outliers_7.json"):
        p = repo_root / "scripts" / fname
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("could not parse %s: %s", p, exc)
            continue
        for s in data.get("stocks", []):
            sym = s.get("symbol")
            if sym:
                out.append(str(sym).strip().upper())
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t not in seen:
            deduped.append(t)
            seen.add(t)
    return deduped


def count_qualified_peers(
    cur, ticker: str, *,
    pe_lo: float, pe_hi: float, ev_lo: float, ev_hi: float,
) -> tuple[int, str | None]:
    """Return (peer_count, industry) for `ticker`.

    A peer qualifies when: same ``stocks.industry``, latest
    ``ratio_history`` row has both pe_ratio AND ev_ebitda within
    bounds. ``ticker`` itself is excluded from the count.
    """
    # Resolve industry of the target ticker
    cur.execute(
        "SELECT industry FROM stocks WHERE ticker = %s",
        (ticker,),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return 0, None
    industry = row[0]

    sql = """
        WITH latest AS (
            SELECT DISTINCT ON (rh.ticker)
                rh.ticker, rh.pe_ratio, rh.ev_ebitda
            FROM ratio_history rh
            JOIN stocks s ON s.ticker = rh.ticker
            WHERE s.industry = %s
              AND rh.ticker <> %s
            ORDER BY rh.ticker, rh.period_end DESC
        )
        SELECT COUNT(*) FROM latest
        WHERE pe_ratio   BETWEEN %s AND %s
          AND ev_ebitda  BETWEEN %s AND %s
    """
    cur.execute(sql, (industry, ticker, pe_lo, pe_hi, ev_lo, ev_hi))
    n = cur.fetchone()[0] or 0
    return int(n), industry


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--tickers", default="",
        help="Comma-separated tickers to verify. Default: canary_50 + outliers_7.",
    )
    p.add_argument(
        "--min-peers", type=int, default=DEFAULT_MIN_PEERS,
        help=f"Minimum qualifying peers required (default: {DEFAULT_MIN_PEERS}).",
    )
    p.add_argument(
        "--pe-min", type=float, default=PE_BOUNDS[0],
        help=f"Lower P/E bound (default: {PE_BOUNDS[0]}).",
    )
    p.add_argument(
        "--pe-max", type=float, default=PE_BOUNDS[1],
        help=f"Upper P/E bound (default: {PE_BOUNDS[1]}).",
    )
    p.add_argument(
        "--ev-min", type=float, default=EV_EBITDA_BOUNDS[0],
        help=f"Lower EV/EBITDA bound (default: {EV_EBITDA_BOUNDS[0]}).",
    )
    p.add_argument(
        "--ev-max", type=float, default=EV_EBITDA_BOUNDS[1],
        help=f"Upper EV/EBITDA bound (default: {EV_EBITDA_BOUNDS[1]}).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = _load_canary_universe(repo_root)

    if not tickers:
        logger.error("no tickers to verify")
        return 2

    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit(
            "ERROR: psycopg2 not installed. `pip install psycopg2-binary`."
        ) from exc

    dsn = _resolve_dsn()

    failures: list[tuple[str, int, str | None]] = []
    with psycopg2.connect(dsn) as conn:  # type: ignore[attr-defined]
        with conn.cursor() as cur:
            for t in tickers:
                try:
                    n, industry = count_qualified_peers(
                        cur, t,
                        pe_lo=args.pe_min, pe_hi=args.pe_max,
                        ev_lo=args.ev_min, ev_hi=args.ev_max,
                    )
                except Exception as exc:
                    logger.error("query failed for %s: %s", t, exc)
                    failures.append((t, -1, None))
                    continue
                ok = n >= args.min_peers
                logger.info(
                    "%s industry=%s qualified_peers=%d %s",
                    t, industry or "(unknown)", n,
                    "OK" if ok else f"FAIL (<{args.min_peers})",
                )
                if not ok:
                    failures.append((t, n, industry))

    print()
    print("=" * 70)
    print(f"verify_peer_cap_inputs — {len(tickers)} tickers · {len(failures)} failures")
    print("=" * 70)
    if failures:
        for t, n, ind in failures:
            print(f"  FAIL {t:14s} industry={ind or '(unknown)'} peers={n}")
        return 1
    print("  all clear — peer-cap precondition met")
    return 0


if __name__ == "__main__":
    sys.exit(main())
