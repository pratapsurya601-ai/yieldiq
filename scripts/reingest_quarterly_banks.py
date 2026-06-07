"""Backfill Schedule III Division I bank fields for historical quarters.

This is the post-merge operator script promised by PR #747
(``fix(banks): operating_income derivation + Schedule III Div I XBRL
parser + free-tier 3y->5y cap``). PR #747 added the bank-format
columns to ``company_financials`` and taught
``data_pipeline.xbrl.yf_fetcher.extract_income_records`` to populate
``interest_earned`` / ``interest_expended`` / ``other_income`` (as
non-interest income) / ``operating_expense`` / ``total_income`` when
yfinance exposes the Schedule III Div I rows. Ongoing nightly ingest
fills these forward from the deploy date; this script fills BACKWARD
across already-ingested historical quarters that pre-date #747.

ONE-SHOT BACKFILL — not a cron job. Run once after #747 ships, then
the nightly ``data_pipeline.xbrl.run`` keeps things current.

Source of truth
---------------

- Bank universe:   ``backend.services.analysis.sector_overrides
                    .PURE_BANK_TICKERS_FOR_DE`` (38 tickers).
- Parser:          ``data_pipeline.xbrl.yf_fetcher.extract_income_records``
                   with ``period_type='quarterly'``. yfinance returns
                   the full historical quarterly income statement for a
                   ticker in one HTTP call; we slice it by ``--since`` /
                   ``--until`` rather than per-quarter loop.
- Writer:          ``data_pipeline.xbrl.db_writer.upsert_records`` —
                   same writer the regular ingest uses, with the same
                   ``ON CONFLICT (ticker_nse, period_type,
                   period_end_date, statement_type, source) DO UPDATE``
                   idempotency.
- Rate limit:      yfinance, not BSE — sleep between TICKERS (one
                   network call per ticker), not between quarters.

Usage
-----

::

    # Help.
    python scripts/reingest_quarterly_banks.py --help

    # Single-ticker dry run, one quarter window.
    python scripts/reingest_quarterly_banks.py \\
        --since 2024-12-01 --until 2024-12-31 \\
        --tickers HDFCBANK --dry-run --verbose

    # Full backfill from 2023-Q1 to today (the post-#747 operator action).
    python scripts/reingest_quarterly_banks.py --since 2023-01-01

    # Resume an interrupted run.
    python scripts/reingest_quarterly_banks.py --since 2023-01-01 \\
        --resume-from KOTAKBANK

Exit codes
----------

::

    0  ran cleanly (rows may still have been skipped — see summary)
    1  fatal init error (DATABASE_URL missing, --since unparseable, etc.)

Cache visibility
----------------

Backfilled rows surface in the Financial Statements panel on the
analysis page after the cache for the affected ticker invalidates.
PR #747 already shipped a manifest entry (wildcard scope, fields
``operating_income`` / ``ebit_margin`` / ``interest_coverage``); the
operator may force-refresh a specific ticker via the manifest if they
don't want to wait for natural TTL expiry.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import types
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("yieldiq.reingest.quarterly_banks")


# yf_fetcher.py uses flat ``from config import RUPEES_TO_CRORES`` and
# ``from tickers import get_yf_symbol`` — both rely on the sys.path
# hack the production ingest scripts apply at startup
# (``data_pipeline/xbrl/run.py`` runs from inside that directory).
# When we import yf_fetcher from a scripts/ entry point those flat
# modules are NOT on sys.path, so we register synthetic shims with the
# same constants the test suite uses.
def _install_xbrl_shims() -> None:
    if "config" not in sys.modules or not hasattr(
        sys.modules.get("config"), "RUPEES_TO_CRORES"
    ):
        shim_config = types.ModuleType("config")
        shim_config.RUPEES_TO_CRORES = 1e7
        shim_config.NSE_DELAY = 0.0
        sys.modules["config"] = shim_config
    if "tickers" not in sys.modules:
        shim_tickers = types.ModuleType("tickers")
        shim_tickers.get_yf_symbol = (
            lambda t: t if str(t).endswith(".NS") else f"{t}.NS"
        )
        sys.modules["tickers"] = shim_tickers


# ---------------------------------------------------------------------------
# Bank universe resolution
# ---------------------------------------------------------------------------

# Hardcoded fallback used ONLY when the canonical Python-side list
# cannot be imported (file moved, package broken). 30 obvious NSE
# bank tickers — kept short and obvious; the canonical list is the
# source of truth.
_FALLBACK_BANK_TICKERS: tuple[str, ...] = (
    "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
    "BAJFINANCE", "INDUSINDBK", "FEDERALBNK", "BANKBARODA", "PNB",
    "CANBK", "UNIONBANK", "IDFCFIRSTB", "RBLBANK", "YESBANK",
    "BANDHANBNK", "AUBANK", "IDBI", "J&KBANK", "KARURVYSYA",
    "KARNATAKABANK", "CITYUNIONBNK", "SOUTHBANK", "DCBBANK", "CSBBANK",
    "UJJIVANSFB", "ESAFSFB", "EQUITASBNK", "FINPIPE", "CHOLAFIN",
)


def resolve_bank_universe() -> tuple[list[str], str]:
    """Return (sorted_tickers, source_label).

    Tries the canonical Python-side list first; falls back to the
    hardcoded inline tuple if the import fails and emits a WARNING.
    """
    try:
        from backend.services.analysis.sector_overrides import (
            PURE_BANK_TICKERS_FOR_DE,
        )
        return sorted(PURE_BANK_TICKERS_FOR_DE), "PURE_BANK_TICKERS_FOR_DE"
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "could not import PURE_BANK_TICKERS_FOR_DE from "
            "backend.services.analysis.sector_overrides (%s); falling "
            "back to hardcoded inline list of %d tickers",
            exc, len(_FALLBACK_BANK_TICKERS),
        )
        return sorted(_FALLBACK_BANK_TICKERS), "fallback_inline"


# ---------------------------------------------------------------------------
# Date / period helpers
# ---------------------------------------------------------------------------

def _parse_ymd(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def _in_window(d: str | None, since: date, until: date) -> bool:
    if not d:
        return False
    try:
        x = datetime.strptime(d[:10], "%Y-%m-%d").date()
    except Exception:
        return False
    return since <= x <= until


# ---------------------------------------------------------------------------
# Core: per-ticker fetch -> filter -> upsert
# ---------------------------------------------------------------------------

# Bank-format keys we care about. The whole point of this backfill.
BANK_FIELDS = (
    "interest_earned",
    "interest_expended",
    "other_income",         # non-interest income
    "operating_expense",
    "total_income",
)


@dataclass
class TickerOutcome:
    ticker: str
    fetched_quarters: int = 0
    in_window: int = 0
    upserted: int = 0
    bank_field_rows: int = 0   # rows whose interest_earned is populated
    error: str | None = None
    skip_reason: str | None = None


def _has_bank_signal(rec: dict) -> bool:
    """A row 'has bank signal' if interest_earned is populated.

    Mirrors the yf_fetcher convention: ``interest_earned`` is the gate
    field — if it's None, the upstream extractor decided yfinance had
    no bank-format rows for this period and ``total_income`` /
    ``interest_expended`` were deliberately suppressed.
    """
    return rec.get("interest_earned") is not None


def _format_money(v: object) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f}"
    except Exception:
        return str(v)


def reingest_one_ticker(
    ticker: str,
    since: date,
    until: date,
    *,
    dry_run: bool,
    verbose: bool,
    fetch_fn: Callable[[str], dict | None] | None = None,
    extract_fn: Callable[[dict, str], list[dict]] | None = None,
    upsert_fn: Callable[[list[dict]], tuple[int, int]] | None = None,
) -> TickerOutcome:
    """Fetch + extract + (optionally) upsert one ticker's quarterly
    income statement, restricted to periods inside [since, until].

    Returns a ``TickerOutcome`` describing what happened. NEVER raises
    on a single-ticker failure — the caller iterates many tickers and
    one BSE/yfinance hiccup must not kill the run.

    The three ``*_fn`` overrides exist so the test suite can substitute
    deterministic in-memory implementations without monkey-patching
    modules across import boundaries.
    """
    out = TickerOutcome(ticker=ticker)

    # Lazy-import production functions so callers passing overrides
    # (the test suite) don't pay the import cost or require yfinance
    # to be installed.
    if fetch_fn is None or extract_fn is None:
        try:
            _install_xbrl_shims()
            from data_pipeline.xbrl.yf_fetcher import (
                fetch_yfinance_data,
                extract_income_records,
            )
            fetch_fn = fetch_fn or fetch_yfinance_data
            extract_fn = extract_fn or extract_income_records
        except Exception as exc:
            out.error = f"import failure: {exc}"
            return out

    if upsert_fn is None and not dry_run:
        try:
            from data_pipeline.xbrl.db_writer import upsert_records
            upsert_fn = upsert_records
        except Exception as exc:
            out.error = f"import failure (db_writer): {exc}"
            return out

    try:
        data = fetch_fn(ticker)
    except Exception as exc:
        out.error = f"fetch failed: {exc}"
        return out

    if not data:
        out.skip_reason = "no data from upstream"
        return out

    try:
        all_records = extract_fn(data, "quarterly")
    except Exception as exc:
        out.error = f"extract failed: {exc}"
        return out

    out.fetched_quarters = len(all_records)
    in_window = [
        r for r in all_records
        if _in_window(r.get("period_end_date"), since, until)
    ]
    out.in_window = len(in_window)
    out.bank_field_rows = sum(1 for r in in_window if _has_bank_signal(r))

    if not in_window:
        out.skip_reason = (
            f"no quarterly rows in [{since.isoformat()}, {until.isoformat()}]"
        )
        return out

    # Annotate every row so downstream readers can identify the source
    # without joining on (ticker, period). The source stays as whatever
    # the extractor stamped — we don't claim NSE_XBRL provenance for
    # rows that came from yfinance.
    for r in in_window:
        r["is_bank"] = True

    if verbose:
        for r in in_window:
            logger.info(
                "  %s %s  interest_earned=%s interest_expended=%s "
                "non_interest_income=%s operating_expense=%s "
                "total_income=%s source=%s",
                ticker,
                r.get("period_end_date"),
                _format_money(r.get("interest_earned")),
                _format_money(r.get("interest_expended")),
                _format_money(r.get("other_income")),
                _format_money(r.get("operating_expense")),
                _format_money(r.get("total_income")),
                r.get("source"),
            )

    if dry_run:
        out.upserted = 0
        return out

    try:
        inserted, errors = upsert_fn(in_window)
    except Exception as exc:
        out.error = f"upsert failed: {exc}"
        return out

    out.upserted = inserted
    if errors:
        out.error = f"{errors} row-level DB errors (see writer log)"
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill Schedule III Div I bank fields "
            "(interest_earned, interest_expended, non_interest_income, "
            "operating_expenses, total_income) on historical quarterly "
            "rows of company_financials. PR #747 follow-up."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--since", required=True,
        help="Earliest period_end to backfill (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--until", default=None,
        help="Latest period_end to backfill (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--tickers", default=None,
        help=(
            "Comma-separated NSE tickers to backfill. Default: full "
            "PURE_BANK_TICKERS_FOR_DE cohort (38 banks)."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Log what would be upserted; do not touch the DB.",
    )
    parser.add_argument(
        "--rate-limit-sec", type=float, default=1.5,
        help="Sleep between TICKERS (yfinance fetch returns all quarters in one call).",
    )
    parser.add_argument(
        "--resume-from", default=None,
        help="Skip tickers (alphabetical) that sort strictly before this one.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print every period's row before the upsert summary.",
    )
    return parser


def _resolve_tickers(arg: str | None) -> tuple[list[str], str]:
    if not arg:
        return resolve_bank_universe()
    tickers = sorted({
        t.strip().upper() for t in arg.split(",") if t.strip()
    })
    return tickers, "cli_override"


def _summary_line(o: TickerOutcome) -> str:
    if o.error:
        return f"error: {o.error}"
    if o.skip_reason:
        return f"skipped ({o.skip_reason})"
    sample_field = "interest_earned"
    return (
        f"upserted={o.upserted} (in_window={o.in_window}, "
        f"bank_signal={o.bank_field_rows}/{o.in_window} "
        f"based on populated {sample_field})"
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        since = _parse_ymd(args.since)
    except Exception as exc:
        logger.error("--since must be YYYY-MM-DD (%s)", exc)
        return 1

    if args.until:
        try:
            until = _parse_ymd(args.until)
        except Exception as exc:
            logger.error("--until must be YYYY-MM-DD (%s)", exc)
            return 1
    else:
        until = date.today()

    if until < since:
        logger.error("--until %s is before --since %s", until, since)
        return 1

    # Fail-fast on missing DATABASE_URL unless this is a dry run. The
    # writer would raise the same error on first upsert; checking up
    # front lets the operator notice before fetching 38 banks.
    if not args.dry_run and not (
        os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    ):
        logger.error(
            "DATABASE_URL is not set. Set DATABASE_URL or NEON_DATABASE_URL "
            "in the environment, or pass --dry-run."
        )
        return 1

    universe, source_label = _resolve_tickers(args.tickers)
    if args.resume_from:
        cutoff = args.resume_from.strip().upper()
        universe = [t for t in universe if t >= cutoff]

    if not universe:
        logger.error("no tickers to process after --resume-from filter")
        return 1

    logger.info(
        "reingest_quarterly_banks: since=%s until=%s tickers=%d "
        "(source=%s) dry_run=%s rate_limit_sec=%.2f resume_from=%s",
        since.isoformat(), until.isoformat(), len(universe), source_label,
        args.dry_run, args.rate_limit_sec, args.resume_from or "—",
    )

    outcomes: list[TickerOutcome] = []
    total = len(universe)

    for idx, ticker in enumerate(universe, start=1):
        try:
            outcome = reingest_one_ticker(
                ticker, since, until,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )
        except Exception as exc:  # pragma: no cover — last-ditch safety net
            outcome = TickerOutcome(
                ticker=ticker, error=f"unhandled exception: {exc}"
            )
        outcomes.append(outcome)
        logger.info(
            "[%d/%d] %-14s  %s",
            idx, total, ticker, _summary_line(outcome),
        )
        if idx < total and args.rate_limit_sec > 0:
            time.sleep(args.rate_limit_sec)

    # ---- Final summary ----
    tried = len(outcomes)
    upserted = sum(o.upserted for o in outcomes)
    errored = sum(1 for o in outcomes if o.error)
    skipped = sum(1 for o in outcomes if o.skip_reason and not o.error)
    bank_signal_rows = sum(o.bank_field_rows for o in outcomes)
    in_window_rows = sum(o.in_window for o in outcomes)

    logger.info("=" * 60)
    logger.info(
        "DONE  tried=%d  upserted=%d  skipped=%d  errored=%d  "
        "in_window_rows=%d  bank_signal_rows=%d  dry_run=%s",
        tried, upserted, skipped, errored,
        in_window_rows, bank_signal_rows, args.dry_run,
    )

    # Per-error-type counts (light grouping by the leading word).
    if errored:
        from collections import Counter
        kinds: Counter[str] = Counter()
        for o in outcomes:
            if o.error:
                kinds[o.error.split(":", 1)[0]] += 1
        for kind, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
            logger.info("  error[%s] = %d", kind, n)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
