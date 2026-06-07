"""One-shot Kite Connect price backfill for a tiny set of tickers.

Why this script exists
======================

A Phase-0 audit (``redesign/followups/kite-connect-integration-phase0.md``)
established that:

* HDFCBANK's stored close (~Rs.747) was stale *and* missed the 1:1 bonus
  ex-26-Aug-2025 corp-action adjustment (live tape was ~Rs.2,000).
* TCS's stored close (~Rs.2,199) was simply stale (live tape was ~Rs.3,500+).
* Zerodha Kite Connect's ``historical_data`` endpoint returns
  **split / bonus-adjusted** OHLC out of the box, which makes it the
  cheapest fix for the specific stale-and-corp-action-missed shape
  these two tickers exhibit.
* Automating Kite in cron requires daily access-token refresh at 06:00
  IST, which we deliberately do NOT want to take on right now.

The recommended path was therefore: **a one-shot operator-run script**.
The operator generates a fresh access_token via the Kite login flow,
exports it, runs this script for the offending tickers, then triggers
an analysis recompute so the engine picks up the new prices.

This script does NOT:

* Modify any code under ``data_pipeline/`` (no change to ingest crons).
* Automate Kite access-token refresh.
* Touch any ticker outside the CLI argument list.
* Bump CACHE_VERSION (it is data-only; engine recomputes naturally).

Operator workflow
=================

1. Get a fresh Kite Connect access_token:
       https://kite.trade/docs/connect/v3/user/#login-flow
   In short: visit
       https://kite.zerodha.com/connect/login?v=3&api_key=YOUR_API_KEY
   complete the 2FA flow, capture the ``request_token`` from the
   redirect URL, then exchange it via
   ``KiteConnect(api_key).generate_session(request_token, api_secret)``
   to obtain ``access_token``. Tokens expire at ~06:00 IST the next
   morning, so do this fresh each session.

2. Set env vars in your shell:

       export KITE_API_KEY=...
       export KITE_API_SECRET=...
       export KITE_ACCESS_TOKEN=...
       export DATABASE_URL=postgresql://...    # the YieldIQ Aiven URL

3. Dry-run first (the default; refuses to write):

       python scripts/kite_oneshot_backfill.py --dry-run HDFCBANK TCS

   Inspect the printed before/after summary. The script prints, per
   ticker:
     - how many ``daily_prices`` rows would be inserted or updated,
     - the latest pre-existing close (so the corp-action gap is
       visible),
     - the latest Kite close (so the new state is visible),
     - the count of rows rejected by the sanity floor / ceiling.

4. If the output looks correct, commit:

       python scripts/kite_oneshot_backfill.py --commit HDFCBANK TCS

   Add ``--update-live-quotes`` if you also want ``live_quotes`` to
   reflect the last Kite close immediately (useful so the stale-CMP
   path unblocks before the next live-quotes cron tick):

       python scripts/kite_oneshot_backfill.py \\
           --commit --update-live-quotes HDFCBANK TCS

5. Trigger a recompute so cached analysis picks up the new prices:

       curl -X POST https://<api>/analysis/HDFCBANK?force=true
       curl -X POST https://<api>/analysis/TCS?force=true

6. Verify the new prices show up in the UI scorecard and that the
   FV step looks corp-action-consistent.

Rollback
========

The script writes only to ``daily_prices`` (and optionally to
``live_quotes`` for the two tickers passed). To roll back, either:

* Delete the affected rows by ``trade_date`` window for the ticker
  in question, e.g.::

      DELETE FROM daily_prices
       WHERE ticker = 'HDFCBANK'
         AND trade_date BETWEEN '2024-06-07' AND '2026-06-07';

  then re-run the legacy NSE-bhavcopy backfill for the same window
  (``scripts/backfill_daily_prices_gap.py``) to restore the prior
  unadjusted series.

* Or, if only ``live_quotes`` was tampered with, simply wait for the
  next live-quotes cron tick (every 15 min) — it overwrites.

Idempotency
===========

All writes are ``INSERT ... ON CONFLICT (ticker, trade_date) DO
UPDATE``. Re-running the script with the same arguments is safe and
converges to the same end state.

Sanity guards
=============

The script refuses to write any row whose Kite close is below 1 or
above 1e6, on the theory that an Indian equity outside that band is
almost certainly a Kite parser glitch or a wrong instrument_token
mapping.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("kite_oneshot_backfill")

# Sanity bounds — any close outside this band is rejected.
SANITY_FLOOR = 1.0          # rupees
SANITY_CEILING = 1_000_000.0  # rupees

# Instrument-cache path. Reusing across invocations avoids re-fetching
# the ~5 MB NSE instrument CSV every run.
DEFAULT_INSTRUMENT_CACHE = Path.home() / ".cache" / "yieldiq" / "kite_instruments_nse.json"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KiteBar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class TickerOutcome:
    ticker: str
    instrument_token: Optional[int]
    bars_fetched: int
    rows_written: int
    rows_rejected: int
    pre_existing_latest_close: Optional[float]
    pre_existing_latest_date: Optional[date]
    new_latest_close: Optional[float]
    new_latest_date: Optional[date]
    live_quote_updated: bool


# ---------------------------------------------------------------------------
# Kite helpers — these are the only places the script touches the SDK.
# ---------------------------------------------------------------------------


def _build_kite_client(api_key: str, access_token: str):  # pragma: no cover - thin wrapper
    from kiteconnect import KiteConnect  # type: ignore

    kc = KiteConnect(api_key=api_key)
    kc.set_access_token(access_token)
    return kc


def _load_instruments(
    kc: Any,
    *,
    cache_path: Optional[Path] = DEFAULT_INSTRUMENT_CACHE,
    cache_max_age: timedelta = timedelta(hours=24),
) -> list[dict[str, Any]]:
    """Return the NSE instrument list, hitting the on-disk cache first.

    Kite's ``instruments("NSE")`` returns a ~5 MB CSV; we cache the
    parsed JSON so re-running the script for a different ticker doesn't
    re-fetch.
    """
    if cache_path is not None and cache_path.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        if age < cache_max_age:
            try:
                with cache_path.open("r", encoding="utf-8") as fh:
                    cached = json.load(fh)
                if isinstance(cached, list):
                    logger.info("instrument cache hit: %s (%d entries)", cache_path, len(cached))
                    return cached
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("instrument cache unreadable, refetching: %s", exc)

    logger.info("fetching NSE instrument master from Kite ...")
    raw = kc.instruments("NSE")
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("w", encoding="utf-8") as fh:
                json.dump(_jsonable(raw), fh, default=str)
            logger.info("instrument cache written: %s (%d entries)", cache_path, len(raw))
        except OSError as exc:
            logger.warning("could not write instrument cache: %s", exc)
    return list(raw)


def _jsonable(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        out.append({k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in row.items()})
    return out


def resolve_instrument_token(
    instruments: Sequence[Mapping[str, Any]],
    ticker: str,
) -> Optional[int]:
    """Map a YieldIQ ticker (e.g. 'HDFCBANK') to its NSE instrument_token.

    Match rule: ``segment == 'NSE'`` AND ``tradingsymbol == TICKER`` AND
    ``instrument_type == 'EQ'``. We deliberately require the EQ filter
    because NSE has same-symbol instruments across segments (futures /
    options legs) and we only ever want the cash leg.
    """
    target = ticker.strip().upper()
    for row in instruments:
        if str(row.get("tradingsymbol", "")).upper() != target:
            continue
        if str(row.get("instrument_type", "")).upper() != "EQ":
            continue
        seg = str(row.get("segment", "")).upper()
        if seg and seg != "NSE":
            continue
        try:
            return int(row["instrument_token"])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def fetch_historical(
    kc: Any,
    instrument_token: int,
    from_date: date,
    to_date: date,
) -> list[KiteBar]:
    """Wrap ``kc.historical_data`` and normalise its rows."""
    raw = kc.historical_data(instrument_token, from_date, to_date, "day")
    out: list[KiteBar] = []
    for r in raw:
        try:
            d = r["date"]
            if isinstance(d, datetime):
                d = d.date()
            elif isinstance(d, str):
                d = datetime.fromisoformat(d.split("T")[0]).date()
            bar = KiteBar(
                trade_date=d,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=int(r.get("volume", 0) or 0),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("skipping malformed bar %r: %s", r, exc)
            continue
        out.append(bar)
    out.sort(key=lambda b: b.trade_date)
    return out


def _sanity_filter(bars: Sequence[KiteBar]) -> tuple[list[KiteBar], int]:
    kept: list[KiteBar] = []
    rejected = 0
    for b in bars:
        if b.close < SANITY_FLOOR or b.close > SANITY_CEILING:
            logger.warning(
                "rejecting bar outside sanity band: date=%s close=%s",
                b.trade_date, b.close,
            )
            rejected += 1
            continue
        kept.append(b)
    return kept, rejected


# ---------------------------------------------------------------------------
# DB layer — kept narrow so tests can pass an sqlite engine.
# ---------------------------------------------------------------------------


def _build_engine(database_url: str):  # pragma: no cover - trivial wrapper
    from sqlalchemy import create_engine

    url = database_url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_pre_ping=True)


def _is_postgres(engine: Any) -> bool:
    name = getattr(getattr(engine, "dialect", None), "name", "") or ""
    return name.startswith("postgres")


def _upsert_sql(engine: Any) -> str:
    """Return the dialect-appropriate UPSERT for ``daily_prices``.

    Postgres has the ``ON CONFLICT`` clause; sqlite (used by tests)
    supports the same syntax since 3.24 but we target the constraint
    by column tuple to avoid depending on the named UNIQUE constraint.
    """
    return """
        INSERT INTO daily_prices (
            ticker, trade_date, open_price, high_price, low_price,
            close_price, volume
        ) VALUES (
            :ticker, :trade_date, :open, :high, :low, :close, :volume
        )
        ON CONFLICT (ticker, trade_date) DO UPDATE SET
            open_price  = EXCLUDED.open_price,
            high_price  = EXCLUDED.high_price,
            low_price   = EXCLUDED.low_price,
            close_price = EXCLUDED.close_price,
            volume      = EXCLUDED.volume
    """


def _live_quotes_upsert_sql(engine: Any) -> str:
    return """
        INSERT INTO live_quotes (ticker, price, as_of)
        VALUES (:ticker, :price, :as_of)
        ON CONFLICT (ticker) DO UPDATE SET
            price = EXCLUDED.price,
            as_of = EXCLUDED.as_of
    """


def fetch_pre_existing_latest(
    engine: Any,
    ticker: str,
) -> tuple[Optional[float], Optional[date]]:
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT close_price, trade_date FROM daily_prices "
                "WHERE ticker = :t ORDER BY trade_date DESC LIMIT 1"
            ),
            {"t": ticker},
        ).fetchone()
    if row is None:
        return None, None
    close = row[0]
    d = row[1]
    if isinstance(d, str):
        d = datetime.fromisoformat(d).date()
    return (float(close) if close is not None else None, d)


def write_bars(
    engine: Any,
    ticker: str,
    bars: Sequence[KiteBar],
) -> int:
    if not bars:
        return 0
    from sqlalchemy import text

    sql = text(_upsert_sql(engine))
    written = 0
    with engine.begin() as conn:
        for b in bars:
            conn.execute(
                sql,
                {
                    "ticker": ticker,
                    "trade_date": b.trade_date,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                },
            )
            written += 1
    return written


def write_live_quote(engine: Any, ticker: str, price: float, as_of: datetime) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(_live_quotes_upsert_sql(engine)),
            {"ticker": ticker, "price": price, "as_of": as_of},
        )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_for_ticker(
    *,
    ticker: str,
    instruments: Sequence[Mapping[str, Any]],
    kc: Any,
    engine: Any,
    from_date: date,
    to_date: date,
    commit: bool,
    update_live_quotes: bool,
) -> TickerOutcome:
    token = resolve_instrument_token(instruments, ticker)
    if token is None:
        logger.error("no NSE EQ instrument_token found for %s", ticker)
        return TickerOutcome(
            ticker=ticker, instrument_token=None,
            bars_fetched=0, rows_written=0, rows_rejected=0,
            pre_existing_latest_close=None, pre_existing_latest_date=None,
            new_latest_close=None, new_latest_date=None,
            live_quote_updated=False,
        )

    pre_close, pre_date = fetch_pre_existing_latest(engine, ticker)

    bars = fetch_historical(kc, token, from_date, to_date)
    bars, rejected = _sanity_filter(bars)

    new_close = bars[-1].close if bars else None
    new_date = bars[-1].trade_date if bars else None

    if commit and bars:
        rows_written = write_bars(engine, ticker, bars)
    else:
        rows_written = 0

    live_quote_updated = False
    if commit and update_live_quotes and new_close is not None:
        write_live_quote(engine, ticker, new_close, datetime.now(timezone.utc))
        live_quote_updated = True

    return TickerOutcome(
        ticker=ticker,
        instrument_token=token,
        bars_fetched=len(bars),
        rows_written=rows_written,
        rows_rejected=rejected,
        pre_existing_latest_close=pre_close,
        pre_existing_latest_date=pre_date,
        new_latest_close=new_close,
        new_latest_date=new_date,
        live_quote_updated=live_quote_updated,
    )


def _print_outcome(o: TickerOutcome, *, commit: bool) -> None:
    verb = "wrote" if commit else "would write"
    print(f"--- {o.ticker} ---")
    if o.instrument_token is None:
        print(f"  ERROR: no NSE EQ instrument_token resolved; skipping.")
        return
    print(f"  instrument_token        : {o.instrument_token}")
    print(f"  bars fetched (sanity-ok): {o.bars_fetched}")
    print(f"  bars rejected (oob)     : {o.rows_rejected}")
    if o.pre_existing_latest_date is not None:
        print(
            f"  pre-existing latest     : Rs.{o.pre_existing_latest_close} "
            f"on {o.pre_existing_latest_date}"
        )
    else:
        print(f"  pre-existing latest     : (none)")
    if o.new_latest_date is not None:
        print(
            f"  kite latest             : Rs.{o.new_latest_close} on {o.new_latest_date}"
        )
    print(f"  daily_prices            : {verb} {o.rows_written if commit else o.bars_fetched} rows")
    print(f"  live_quotes updated     : {'YES' if o.live_quote_updated else 'no'}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="One-shot Kite Connect price backfill for a tiny ticker list."
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", default=True,
                      help="Print intended writes but do not touch the DB (default).")
    mode.add_argument("--commit", dest="commit", action="store_true", default=False,
                     help="Actually write rows. Required to mutate the DB.")
    ap.add_argument("--from", dest="from_date", default=None,
                    help="ISO date (default: today - 2 years).")
    ap.add_argument("--to", dest="to_date", default=None,
                    help="ISO date (default: today).")
    ap.add_argument("--update-live-quotes", action="store_true", default=False,
                    help="Also upsert live_quotes with the last Kite close.")
    ap.add_argument("--no-instrument-cache", action="store_true", default=False,
                    help="Bypass the on-disk instrument cache (debug).")
    ap.add_argument("tickers", nargs="+", help="Tickers to backfill, e.g. HDFCBANK TCS")
    args = ap.parse_args(argv)

    commit = bool(args.commit)
    # argparse leaves --dry-run True by default; --commit toggles the real action.
    dry_run = not commit

    today = date.today()
    to_d = (
        datetime.strptime(args.to_date, "%Y-%m-%d").date()
        if args.to_date else today
    )
    from_d = (
        datetime.strptime(args.from_date, "%Y-%m-%d").date()
        if args.from_date else (to_d - timedelta(days=365 * 2))
    )
    if from_d > to_d:
        print(f"--from {from_d} is after --to {to_d}; nothing to do", file=sys.stderr)
        return 2

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    api_key = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")  # noqa: F841 - read for parity / future use
    access_token = os.environ.get("KITE_ACCESS_TOKEN")
    if not (api_key and access_token):
        print("KITE_API_KEY and KITE_ACCESS_TOKEN must be set in the environment",
              file=sys.stderr)
        return 2

    logger.info("mode=%s window=%s..%s tickers=%s",
                "COMMIT" if commit else "DRY-RUN", from_d, to_d, args.tickers)

    kc = _build_kite_client(api_key, access_token)
    engine = _build_engine(db_url)
    instruments = _load_instruments(
        kc,
        cache_path=None if args.no_instrument_cache else DEFAULT_INSTRUMENT_CACHE,
    )

    outcomes: list[TickerOutcome] = []
    for ticker in args.tickers:
        ticker_u = ticker.strip().upper()
        outcome = run_for_ticker(
            ticker=ticker_u,
            instruments=instruments,
            kc=kc,
            engine=engine,
            from_date=from_d,
            to_date=to_d,
            commit=commit,
            update_live_quotes=args.update_live_quotes,
        )
        outcomes.append(outcome)
        _print_outcome(outcome, commit=commit)

    print()
    print("=== summary ===")
    total_written = sum(o.rows_written for o in outcomes)
    total_fetched = sum(o.bars_fetched for o in outcomes)
    any_live_updated = any(o.live_quote_updated for o in outcomes)
    if commit:
        print(f"  daily_prices rows written : {total_written}")
        print(f"  live_quotes updated       : {'YES' if any_live_updated else 'no'}")
        print(
            "  next operator step        : POST /analysis/<TICKER>?force=true "
            "for each ticker above to force a recompute."
        )
    else:
        print(f"  daily_prices rows that WOULD be written: {total_fetched}")
        print(f"  (dry-run; pass --commit to actually write)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
