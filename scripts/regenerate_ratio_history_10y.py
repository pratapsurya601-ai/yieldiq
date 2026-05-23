"""Phase F.4 — regenerate ratio_history for the F.2 + F.3 ticker union.

Background
==========
F.2 backfilled `daily_prices.adj_close` to 10y. F.3 backfilled
`financials` to 10y. `ratio_history` is purely derived from
`financials` + `market_metrics` via the existing
`scripts/build_ratio_history.py` (no external source).

F.4 is the thin wrapper that:

1. Resolves the same `--tickers` spec the F.2 / F.3 scripts accepted
   (`canary-333` / `top-500` / `all` / file / comma list).
2. Delegates to `build_ratio_history.py` for the actual recomputation
   (subprocess call — keeps the canonical single-owner code path).
3. Runs a post-regen validator: queries `ratio_history` for the input
   universe; if `pe_ratio` null-rate exceeds 10 %, logs a warning
   with the affected tickers (Phase A issue #546 surfaced a 50.9 %
   null spike; F.4 prevents that from silently regressing).

The companion manifest entry `v_phase_f_historical_depth_2026_05_25`
ships in this same PR — it covers the read-path invalidation for
`cagr_3y`, `cagr_5y`, `cagr_10y`, `ratio_history`, and
`compounded_growth` fields across all tickers.

Usage
=====
::

    DATABASE_URL=postgres://... python scripts/regenerate_ratio_history_10y.py \
        --tickers canary-333

    # Dry-run validator only (no recompute).
    DATABASE_URL=postgres://... python scripts/regenerate_ratio_history_10y.py \
        --tickers top-500 --validate-only

    # Both period types (default) or restrict.
    DATABASE_URL=postgres://... python scripts/regenerate_ratio_history_10y.py \
        --tickers canary-333 --period-types annual

Exit codes
==========
    0  — completed (validator may have logged warnings — non-fatal)
    1  — recompute subprocess failed
    2  — usage / config error
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text as sa_text  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("regenerate_ratio_history_10y")

CANARY_UNIVERSE_PATH = ROOT / "scripts" / "canary_universe_180.json"
BUILD_SCRIPT = ROOT / "scripts" / "build_ratio_history.py"

# Audit-mandated threshold (Phase A issue #546).
PE_NULL_WARN_THRESHOLD = 0.10


# ──────────────────────────────────────────────────────────────────────
# Universe resolution (same shape as F.2 / F.3)
# ──────────────────────────────────────────────────────────────────────


def _engine():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_recycle=300, pool_pre_ping=True)


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
# Subprocess delegate to build_ratio_history.py
# ──────────────────────────────────────────────────────────────────────


def run_build_ratio_history(
    tickers: list[str],
    period_types: str,
) -> int:
    """Invoke the canonical builder. Chunks --tickers to stay under
    typical command-line length limits (~32 KiB on Windows)."""
    CHUNK = 200  # comfortable margin for ticker symbols ~10 chars
    chunks = [tickers[i:i + CHUNK] for i in range(0, len(tickers), CHUNK)]
    for i, chunk in enumerate(chunks, 1):
        spec = ",".join(chunk)
        log.info("invoking build_ratio_history [%d/%d] — %d tickers",
                 i, len(chunks), len(chunk))
        cmd = [
            sys.executable, str(BUILD_SCRIPT),
            "--tickers", spec,
            "--period-types", period_types,
        ]
        proc = subprocess.run(cmd, cwd=str(ROOT), check=False)
        if proc.returncode != 0:
            log.error("build_ratio_history exited %d on chunk %d/%d",
                      proc.returncode, i, len(chunks))
            return proc.returncode
    return 0


# ──────────────────────────────────────────────────────────────────────
# Post-regen validator (audit deliverable; Phase A issue #546)
# ──────────────────────────────────────────────────────────────────────


def validate_pe_null_rate(engine, tickers: list[str]) -> dict:
    """Query ratio_history.pe_ratio null-rate per ticker. Returns summary."""
    with engine.connect() as conn:
        rows = conn.execute(sa_text(
            "WITH u AS (SELECT unnest(:ts::text[]) AS ticker) "
            "SELECT u.ticker, "
            "       COUNT(r.id) AS n_rows, "
            "       SUM(CASE WHEN r.pe_ratio IS NULL THEN 1 ELSE 0 END) "
            "         AS n_null "
            "FROM   u "
            "LEFT JOIN ratio_history r ON r.ticker = u.ticker "
            "                          AND r.period_type = 'annual' "
            "GROUP BY u.ticker"
        ), {"ts": tickers}).fetchall()

    affected: list[tuple[str, int, int, float]] = []
    n_total_rows = 0
    n_total_null = 0
    for ticker, n_rows, n_null in rows:
        n = int(n_rows or 0)
        nn = int(n_null or 0)
        n_total_rows += n
        n_total_null += nn
        if n == 0:
            continue
        rate = nn / n
        if rate > PE_NULL_WARN_THRESHOLD:
            affected.append((ticker, n, nn, rate))

    overall_rate = (n_total_null / n_total_rows) if n_total_rows else 0.0
    return {
        "n_tickers": len(rows),
        "n_total_rows": n_total_rows,
        "n_total_null": n_total_null,
        "overall_null_rate": overall_rate,
        "affected": sorted(affected, key=lambda x: -x[3]),
    }


def report_validator(summary: dict) -> None:
    log.info("pe_ratio validator: %d tickers, %d ratio_history rows, "
             "%d nulls (%.1f%% overall)",
             summary["n_tickers"], summary["n_total_rows"],
             summary["n_total_null"], summary["overall_null_rate"] * 100)
    aff = summary["affected"]
    if not aff:
        log.info("pe_ratio validator OK: no tickers exceed %.0f%% null rate",
                 PE_NULL_WARN_THRESHOLD * 100)
        return
    log.warning("pe_ratio validator WARNING: %d tickers exceed %.0f%% null "
                "rate (Phase A issue #546 watchlist)",
                len(aff), PE_NULL_WARN_THRESHOLD * 100)
    for ticker, n, nn, rate in aff[:25]:
        log.warning("  %s — %d/%d null (%.1f%%)", ticker, nn, n, rate * 100)
    if len(aff) > 25:
        log.warning("  ... and %d more", len(aff) - 25)


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", required=True,
                    help="Comma list, file path, or keyword: "
                         "canary-333 | top-500 | all")
    ap.add_argument("--period-types", default="annual,quarterly",
                    help="Forwarded to build_ratio_history.py "
                         "(default: annual,quarterly)")
    ap.add_argument("--validate-only", action="store_true",
                    help="Skip the regenerate step; just run the "
                         "pe_ratio null-rate validator")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        log.error("DATABASE_URL not set")
        return 2

    engine = _engine()
    try:
        tickers = resolve_universe(args.tickers, engine)
    except Exception as exc:
        log.error("universe resolution failed: %s", exc)
        return 2
    if not tickers:
        log.error("resolved universe is empty")
        return 2
    log.info("resolved %d tickers from spec=%r", len(tickers), args.tickers)

    if not args.validate_only:
        rc = run_build_ratio_history(tickers, args.period_types)
        if rc != 0:
            return 1

    summary = validate_pe_null_rate(engine, tickers)
    report_validator(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
