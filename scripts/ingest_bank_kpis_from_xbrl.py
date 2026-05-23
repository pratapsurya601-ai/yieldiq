"""Phase I-ingest-a: ingest bank operational financial KPIs from
BSE quarterly XBRL into ``bank_operational_kpis`` (migration 061).

This script drives ``data_pipeline.sources.bse_bank_xbrl`` for the
canonical commercial-bank universe (``PURE_BANK_TICKERS_FOR_DE``).
For each ticker it asks the registered XBRL provider for up to
``--quarters`` rows of (gnpa_pct, nnpa_pct, pcr_pct, casa_pct,
cost_to_income_pct, credit_deposit_pct), then UPSERTs each row
into ``bank_operational_kpis`` keyed by
(ticker, period_end, period_type='quarterly', source='bse_xbrl').

The script DOES NOT itself parse XBRL element tags -- that lives
in ``bse_bank_xbrl``'s registered provider. The default provider
returns no rows, so the pre-flight gate will report
"provider not configured" and exit non-zero. This is the EXPECTED
state until an operator / dev wires a real provider; see
``data_pipeline/sources/bse_bank_xbrl.py`` for how to do that.

Usage::

    python scripts/ingest_bank_kpis_from_xbrl.py --dry-run
    python scripts/ingest_bank_kpis_from_xbrl.py --tickers HDFCBANK,SBIN,AXISBANK
    python scripts/ingest_bank_kpis_from_xbrl.py --tickers all-banks --quarters 20
    python scripts/ingest_bank_kpis_from_xbrl.py --resume-from KOTAKBANK

Flags::

    --tickers          Comma-separated ticker list, or the literal
                       "all-banks" (default) to use the full 38-ticker
                       PURE_BANK_TICKERS_FOR_DE cohort.
    --quarters N       Quarters of history to request from the
                       provider (default 20 = 5 years).
    --resume-from      Skip tickers (alphabetical) that sort
                       strictly before this value.
    --dry-run          Log what would be written; do not call the
                       provider's network paths via the persistence
                       layer (provider is still invoked because
                       that's where pre-flight signal lives).
    --skip-preflight   Bypass the 3-ticker pre-flight gate. ONLY
                       for use after a successful pre-flight on the
                       same provider revision.

Pre-flight gate (per Phase I plan)::

    Sample tickers: HDFCBANK, SBIN, AXISBANK.
    PASS condition: at least 4 of the 6 KPI fields populated on
    at least one quarterly row, for at least 2 of the 3 tickers.
    FAIL: exit 2 with a clear diagnostic; no rows written.

Exit codes::

    0  ran cleanly
    1  fatal init error (DATABASE_URL missing, etc.)
    2  pre-flight failed (provider returned too little data)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("yieldiq.ingest.bank_kpis_xbrl")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

PREFLIGHT_TICKERS = ("HDFCBANK", "SBIN", "AXISBANK")
PREFLIGHT_MIN_FIELDS_PER_ROW = 4   # >= 4 of 6 fields
PREFLIGHT_MIN_TICKERS_PASSED = 2   # on >= 2 of 3 tickers


def _resolve_universe(arg: str | None) -> list[str]:
    from backend.services.analysis.sector_overrides import (
        PURE_BANK_TICKERS_FOR_DE,
    )
    if not arg or arg.strip().lower() == "all-banks":
        return sorted(PURE_BANK_TICKERS_FOR_DE)
    tickers = [t.strip().upper() for t in arg.split(",") if t.strip()]
    return tickers


def _build_engine():
    from sqlalchemy import create_engine
    url = os.environ.get("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL not set -- aborting")
        return None
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_pre_ping=True)


def _upsert_row(conn, row) -> int:
    """UPSERT one ParsedBankKpiRow. Returns 1 on insert/update, 0 on skip.

    We never overwrite an existing row's populated columns with
    NULLs: the COALESCE-on-EXCLUDED pattern lets a later provider
    revision add fields incrementally without clobbering prior
    extractions.
    """
    from sqlalchemy import text
    if not row.is_useful():
        return 0
    sql = text(
        """
        INSERT INTO bank_operational_kpis (
            ticker, period_end, period_type,
            gnpa_pct, nnpa_pct, pcr_pct,
            casa_pct, cost_to_income_pct, credit_deposit_pct,
            source, source_url
        ) VALUES (
            :ticker, :period_end, :period_type,
            :gnpa_pct, :nnpa_pct, :pcr_pct,
            :casa_pct, :cost_to_income_pct, :credit_deposit_pct,
            :source, :source_url
        )
        ON CONFLICT (ticker, period_end, period_type, source)
        DO UPDATE SET
            gnpa_pct           = COALESCE(EXCLUDED.gnpa_pct,
                                          bank_operational_kpis.gnpa_pct),
            nnpa_pct           = COALESCE(EXCLUDED.nnpa_pct,
                                          bank_operational_kpis.nnpa_pct),
            pcr_pct            = COALESCE(EXCLUDED.pcr_pct,
                                          bank_operational_kpis.pcr_pct),
            casa_pct           = COALESCE(EXCLUDED.casa_pct,
                                          bank_operational_kpis.casa_pct),
            cost_to_income_pct = COALESCE(EXCLUDED.cost_to_income_pct,
                                          bank_operational_kpis.cost_to_income_pct),
            credit_deposit_pct = COALESCE(EXCLUDED.credit_deposit_pct,
                                          bank_operational_kpis.credit_deposit_pct),
            source_url         = COALESCE(EXCLUDED.source_url,
                                          bank_operational_kpis.source_url),
            extracted_at       = now()
        """
    )
    conn.execute(sql, {
        "ticker": row.ticker,
        "period_end": row.period_end,
        "period_type": row.period_type,
        "gnpa_pct": row.gnpa_pct,
        "nnpa_pct": row.nnpa_pct,
        "pcr_pct": row.pcr_pct,
        "casa_pct": row.casa_pct,
        "cost_to_income_pct": row.cost_to_income_pct,
        "credit_deposit_pct": row.credit_deposit_pct,
        "source": row.source,
        "source_url": row.source_url,
    })
    return 1


def _run_preflight(quarters: int) -> tuple[bool, dict[str, int]]:
    """Call the provider for each pre-flight ticker; return
    (passed, per_ticker_max_field_count).
    """
    from data_pipeline.sources import bse_bank_xbrl
    if bse_bank_xbrl.is_default_provider():
        logger.error(
            "PRE-FLIGHT FAILED: the default no-op XBRL provider is active. "
            "No real BSE XBRL schedule parser is wired into "
            "data_pipeline.sources.bse_bank_xbrl. Register a provider "
            "(see that module's docstring) before re-running, or pass "
            "--skip-preflight only if you know the provider has been "
            "wired in a non-default context."
        )
        return False, {}
    per_ticker: dict[str, int] = {}
    for t in PREFLIGHT_TICKERS:
        rows = bse_bank_xbrl.fetch_bank_kpis_for_quarter(t, quarters)
        max_fields = max(
            (r.populated_field_count() for r in rows), default=0,
        )
        per_ticker[t] = max_fields
        logger.info(
            "pre-flight: %s -> %d rows, best row has %d/6 KPI fields",
            t, len(rows), max_fields,
        )
    passed_count = sum(
        1 for v in per_ticker.values() if v >= PREFLIGHT_MIN_FIELDS_PER_ROW
    )
    passed = passed_count >= PREFLIGHT_MIN_TICKERS_PASSED
    return passed, per_ticker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default="all-banks")
    parser.add_argument("--quarters", type=int, default=20)
    parser.add_argument("--resume-from", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()

    if args.quarters <= 0:
        logger.error("--quarters must be > 0")
        return 1

    from data_pipeline.sources import bse_bank_xbrl

    if not args.skip_preflight:
        passed, per_ticker = _run_preflight(args.quarters)
        if not passed:
            logger.error(
                "PRE-FLIGHT FAILED: needed >=%d/6 fields on >=%d of %d tickers; "
                "got %s. Aborting before any DB writes.",
                PREFLIGHT_MIN_FIELDS_PER_ROW,
                PREFLIGHT_MIN_TICKERS_PASSED,
                len(PREFLIGHT_TICKERS),
                per_ticker,
            )
            return 2
        logger.info(
            "pre-flight PASSED (%s); proceeding to main batch.",
            per_ticker,
        )

    universe = _resolve_universe(args.tickers)
    if args.resume_from:
        cutoff = args.resume_from.strip().upper()
        universe = [t for t in universe if t >= cutoff]
    logger.info(
        "ingest run: tickers=%d quarters=%d dry_run=%s skip_preflight=%s",
        len(universe), args.quarters, args.dry_run, args.skip_preflight,
    )

    engine = None
    if not args.dry_run:
        engine = _build_engine()
        if engine is None:
            return 1

    total_rows = 0
    total_written = 0
    per_ticker_stats: list[tuple[str, int, int]] = []

    for ticker in universe:
        try:
            rows = bse_bank_xbrl.fetch_bank_kpis_for_quarter(
                ticker, args.quarters,
            )
        except Exception as exc:
            logger.warning("provider failed for %s: %s", ticker, exc)
            per_ticker_stats.append((ticker, 0, 0))
            continue

        useful = [r for r in rows if r.is_useful()]
        total_rows += len(useful)

        if args.dry_run:
            per_ticker_stats.append((ticker, len(useful), 0))
            logger.info(
                "[dry-run] %s: %d useful rows (would upsert)", ticker, len(useful),
            )
            continue

        written = 0
        with engine.begin() as conn:
            for r in useful:
                written += _upsert_row(conn, r)
        total_written += written
        per_ticker_stats.append((ticker, len(useful), written))
        logger.info("%s: %d rows fetched, %d written", ticker, len(useful), written)

    logger.info(
        "done. tickers=%d fetched_rows=%d written_rows=%d dry_run=%s",
        len(universe), total_rows, total_written, args.dry_run,
    )
    # Print a tiny stats table for the operator log.
    for t, fetched, written in per_ticker_stats:
        if fetched == 0 and written == 0:
            continue
        logger.info("  %-12s fetched=%-4d written=%-4d", t, fetched, written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
