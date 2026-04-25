# data_pipeline/sources/yfinance_supplement.py
# PRIMARY data source — yfinance works from Railway (NSE/BSE block cloud IPs).
# Downloads: prices (3yr history), financials, market metrics, beta.
#
# DECOUPLING REFACTOR (2026-04-25): `fetch_and_store_yfinance` used to bail
# with `return False` whenever `info["regularMarketPrice"]` was None, which
# silently dropped historical-financials ingest for tickers that merely had
# a price-feed glitch or post-listing delay (LTIM was the canary). The
# function is now split into three independently-gated phases:
#
#     _persist_price_snapshot      — needs a live/fallback price
#     _persist_historical_financials — needs ticker.financials / income_stmt
#     _persist_quarterly_supplement  — needs quarterly_* DataFrames
#
# The public entry point returns a structured dict
# `{price: bool, financials: bool, quarterly: bool}`. Legacy boolean
# callers keep working because we also expose `any(result.values())`
# via `__bool__` on the result class — see `YfIngestResult` below.
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from data_pipeline.models import DailyPrice, DataFreshness, Financials, MarketMetrics
from data_pipeline.ticker_aliases import (
    resolve_for_fetch as _resolve_for_fetch,
    Fetch as _Fetch,
    Skip as _Skip,
    Redirect as _Redirect,
)

logger = logging.getLogger(__name__)


@dataclass
class YfIngestResult:
    """Structured per-phase outcome for `fetch_and_store_yfinance`.

    Legacy callers that do `if fetch_and_store_yfinance(...): ...` keep
    working because `__bool__` is `any(...)` of the three phases. Callers
    that need phase-level detail should inspect the fields directly.
    """
    price: bool = False
    financials: bool = False
    quarterly: bool = False

    def __bool__(self) -> bool:  # backward-compat: `if result:` === partial-ok
        return self.price or self.financials or self.quarterly

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


def _has_live_price(info: dict | None) -> bool:
    """Price snapshot is only meaningful if one of these fields is populated."""
    if not info:
        return False
    return (
        info.get("regularMarketPrice") is not None
        or info.get("currentPrice") is not None
        or info.get("previousClose") is not None
    )


def _persist_price_snapshot(ticker: str, info: dict, db: Session) -> bool:
    """Upsert today's MarketMetrics row. Returns True on successful commit.

    Only call this after `_has_live_price(info)` is True.
    """
    try:
        today = date.today()
        existing_metric = db.query(MarketMetrics).filter_by(
            ticker=ticker, trade_date=today
        ).first()
        # yfinance now returns dividendYield as a percentage (e.g. 4.8).
        # Guard against an accidental double-multiplication (e.g. 480)
        # by dividing values > 50 back down. Matches the defensive
        # pattern used in backend/services/dividend_service.py.
        _raw_yield = info.get("dividendYield") or 0
        _dividend_yield = _raw_yield if _raw_yield <= 50 else _raw_yield / 100

        if existing_metric:
            existing_metric.market_cap_cr = _to_cr(info.get("marketCap"))
            existing_metric.pe_ratio = info.get("trailingPE")
            existing_metric.pb_ratio = info.get("priceToBook")
            existing_metric.dividend_yield = _dividend_yield
            existing_metric.beta_1yr = info.get("beta")
            existing_metric.ev_cr = _to_cr(info.get("enterpriseValue"))
        else:
            db.add(MarketMetrics(
                ticker=ticker,
                trade_date=today,
                market_cap_cr=_to_cr(info.get("marketCap")),
                pe_ratio=info.get("trailingPE"),
                pb_ratio=info.get("priceToBook"),
                dividend_yield=_dividend_yield,
                beta_1yr=info.get("beta"),
                ev_cr=_to_cr(info.get("enterpriseValue")),
            ))

        db.commit()
        return True
    except Exception as exc:
        logger.error(
            "Market metrics commit failed for %s: %s: %s",
            ticker, type(exc).__name__, exc,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return False


def _persist_historical_financials(
    ticker: str, stock: "yf.Ticker", info: dict | None, db: Session
) -> bool:
    """Write annual Financials rows from stock.cashflow / income_stmt /
    balance_sheet. Returns True iff at least one row was added/updated and
    the surrounding commit succeeded.

    Independent of the price snapshot: runs whenever yfinance has any
    historical income/cashflow data, regardless of whether the intraday
    price feed is live.
    """
    try:
        cf = stock.cashflow
        bs = stock.balance_sheet
        inc = stock.income_stmt
    except Exception as e:
        logger.warning(
            "Financial statements fetch failed for %s: %s: %s",
            ticker, type(e).__name__, e,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return False

    # Phase is only meaningful if we have an income statement OR cashflow.
    if (cf is None or cf.empty) and (inc is None or inc.empty):
        return False

    # Use whichever frame has columns to drive the period loop.
    driver = cf if (cf is not None and not cf.empty) else inc
    rows_written = 0
    shares_out = info.get("sharesOutstanding") if info else None

    for col in driver.columns[:5]:
        try:
            period_date = col.date() if hasattr(col, "date") else col

            cfo = _get_val(cf, "Operating Cash Flow", col) if (cf is not None and not cf.empty) else None
            capex = _get_val(cf, "Capital Expenditure", col) if (cf is not None and not cf.empty) else None
            fcf = (cfo - abs(capex)) if cfo and capex else None
            revenue = _get_val(inc, "Total Revenue", col) if inc is not None and not inc.empty else None
            pat = _get_val(inc, "Net Income", col) if inc is not None and not inc.empty else None
            ebitda = _get_val(inc, "EBITDA", col) if inc is not None and not inc.empty else None
            # BUG FIX 2026-04-24: was "Total Equity Gross Minority Interest"
            # which includes minority interest + Tier-1 perpetuals. For banks
            # this inflated equity ~50% — e.g. HDFCBANK stored 862k Cr vs real
            # ~570k Cr, halving ROE (7.8% vs real 11.8%) and cascading through
            # fair_value / HEX quality axes / composite score. Correct field is
            # "Stockholders Equity" (excludes minority interest), with fallback
            # to "Common Stock Equity" for tickers where the first field is absent.
            total_equity = (
                _get_val(bs, "Stockholders Equity", col) if bs is not None and not bs.empty else None
            )
            if total_equity is None and bs is not None and not bs.empty:
                total_equity = _get_val(bs, "Common Stock Equity", col)
            if total_equity is None and bs is not None and not bs.empty:
                # Last-resort fallback to the old (wrong-for-banks) field
                # rather than returning None for non-bank tickers where
                # minority interest is negligible or absent.
                total_equity = _get_val(bs, "Total Equity Gross Minority Interest", col)
            total_assets = _get_val(bs, "Total Assets", col) if bs is not None and not bs.empty else None

            fin = Financials(
                ticker=ticker,
                period_end=period_date,
                period_type="annual",
                revenue=_to_cr(revenue),
                pat=_to_cr(pat),
                ebitda=_to_cr(ebitda),
                cfo=_to_cr(cfo),
                capex=_to_cr(capex),
                free_cash_flow=_to_cr(fcf),
                total_debt=_to_cr(
                    _get_val(bs, "Total Debt", col) if bs is not None and not bs.empty else None
                ),
                cash_and_equivalents=_to_cr(
                    _get_val(bs, "Cash And Cash Equivalents", col) if bs is not None and not bs.empty else None
                ),
                total_equity=_to_cr(total_equity),
                total_assets=_to_cr(total_assets),
                shares_outstanding=_to_lakhs(shares_out),
                roe=(_safe_pct(pat, total_equity)) if pat and total_equity else None,
                roa=(_safe_pct(pat, total_assets)) if pat and total_assets else None,
                net_margin=(_safe_pct(pat, revenue)) if pat and revenue else None,
                data_source="yfinance",
                # yfinance normalises all `.NS` / `.BO` financials
                # to INR regardless of how the issuer files, so
                # we always tag INR here.
                currency="INR",
            )

            if revenue and revenue > 0:
                existing_fin = db.query(Financials).filter_by(
                    ticker=ticker, period_end=period_date, period_type="annual"
                ).first()
                if existing_fin:
                    for attr in ["revenue", "pat", "ebitda", "cfo", "capex",
                                 "free_cash_flow", "total_debt", "cash_and_equivalents",
                                 "total_equity", "total_assets", "shares_outstanding",
                                 "roe", "roa", "net_margin"]:
                        val = getattr(fin, attr, None)
                        if val is not None:
                            setattr(existing_fin, attr, val)
                    rows_written += 1
                else:
                    db.add(fin)
                    rows_written += 1
        except Exception as row_exc:
            # If the autoflush / add raised (e.g. UNIQUE on
            # (ticker, period_end, period_type)), the session
            # is pending-rollback. Clear it before moving on.
            logger.debug(
                "Financials row skipped for %s: %s: %s",
                ticker, type(row_exc).__name__, row_exc,
            )
            try:
                db.rollback()
            except Exception:
                pass
            continue

    if rows_written == 0:
        return False

    try:
        db.commit()
        return True
    except Exception as commit_exc:
        logger.error(
            "Historical financials commit failed for %s: %s: %s",
            ticker, type(commit_exc).__name__, commit_exc,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return False


def _persist_quarterly_supplement(
    ticker: str, stock: "yf.Ticker", db: Session
) -> bool:
    """Placeholder for parity with the yf_fetcher quarterly path.

    This module historically only wrote annual rows into `financials`.
    The quarterly pipeline that populates `company_financials` lives in
    `data_pipeline/xbrl/yf_fetcher.py` + `db_writer.py` and is invoked
    separately. We keep the phase here so the structured return value
    stays symmetric and so a future migration can slot quarterly writes
    into this module without changing any caller signatures.

    Returns False today because this module does not currently persist
    quarterly rows — the quarterly phase is handled by the XBRL path.
    """
    # Intentionally a no-op today. Guarded for future extension.
    try:
        _ = stock.quarterly_income_stmt  # probe to confirm symbol works
    except Exception:
        pass
    return False


def fetch_and_store_yfinance(
    ticker_ns: str, ticker: str, db: Session
) -> YfIngestResult:
    """
    Fetch comprehensive financial data from yfinance for one stock.
    ticker_ns: e.g. "RELIANCE.NS"
    ticker: e.g. "RELIANCE"

    Returns a `YfIngestResult` dataclass with independent per-phase booleans:

        result.price       — today's MarketMetrics row written
        result.financials  — at least one annual Financials row written
        result.quarterly   — quarterly rows written (currently always False;
                             quarterly path lives in xbrl/yf_fetcher.py)

    Legacy boolean usage (`if fetch_and_store_yfinance(...): ...`) still
    works because `__bool__` on the result returns `any(...)` of the
    three phases (= "partial success or better").
    """
    result = YfIngestResult()
    # Corporate-actions alias gate. Consult BEFORE yfinance so a
    # demerged/delisted parent doesn't generate Sentry 404 noise.
    _res = _resolve_for_fetch(ticker)
    if isinstance(_res, _Skip):
        logger.info(
            "ticker_aliases: skipping %s (reason=%s)", ticker, _res.reason
        )
        return result
    if isinstance(_res, _Redirect):
        logger.info(
            "ticker_aliases: %s demerged; fetching successors %s",
            ticker, [s.ticker for s in _res.successors],
        )
        for succ in _res.successors:
            if not succ.fetch_symbol:
                continue
            try:
                sub = fetch_and_store_yfinance(succ.fetch_symbol, succ.ticker, db)
                # OR-merge per-phase flags so the caller sees true if
                # ANY successor produced a row of that phase.
                result.price = result.price or sub.price
                result.financials = result.financials or sub.financials
                result.quarterly = result.quarterly or sub.quarterly
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ticker_aliases: successor %s fetch failed: %s",
                    succ.ticker, exc,
                )
        return result
    if isinstance(_res, _Fetch) and _res.symbol:
        # Prefer the alias-resolved Yahoo symbol (handles fetch_symbol
        # overrides for renamed tickers); falls back to caller-supplied
        # ticker_ns otherwise.
        ticker_ns = _res.symbol
    try:
        stock = yf.Ticker(ticker_ns)
        try:
            info = stock.info or {}
        except Exception:
            info = {}

        # --- Phase 1: price snapshot (independent) ---
        if _has_live_price(info):
            result.price = _persist_price_snapshot(ticker, info, db)
        else:
            logger.info(
                "ticker=%s price=skipped reason=no_live_price_in_info",
                ticker,
            )

        # --- Phase 2: historical annual financials (independent) ---
        result.financials = _persist_historical_financials(ticker, stock, info, db)

        # --- Phase 3: quarterly supplement (independent, currently no-op) ---
        result.quarterly = _persist_quarterly_supplement(ticker, stock, db)

        # --- Partial-success logging ---
        # Warnings are reserved for things humans need to act on. A missing
        # price feed on a ticker whose financials ingested fine is expected
        # (post-listing delay, weekend, temporary yfinance glitch) and
        # should be INFO only.
        if result.financials and not result.price:
            logger.info(
                "ticker=%s financials=ok price=failed quarterly=%s",
                ticker, "ok" if result.quarterly else "skipped",
            )
        elif not result.financials and not result.price and not result.quarterly:
            logger.warning(
                "ticker=%s all_phases_failed (info_keys=%d)",
                ticker, len(info) if info else 0,
            )
        else:
            logger.info(
                "ticker=%s price=%s financials=%s quarterly=%s",
                ticker,
                "ok" if result.price else "skipped",
                "ok" if result.financials else "skipped",
                "ok" if result.quarterly else "skipped",
            )

        return result

    except Exception as e:
        logger.error(
            "yfinance fetch failed for %s: %s: %s",
            ticker_ns, type(e).__name__, e,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return result


def fetch_price_history(ticker_ns: str, ticker: str, db: Session,
                        period: str = "3y") -> int:
    """
    Download price history from yfinance and store in daily_prices.
    Uses Ticker.history() which worked for the first 50 stocks.

    Session discipline: every exit path — whether success, early return
    from an empty frame, a yfinance exception, or an ORM IntegrityError
    during flush/commit — leaves the session in a clean state. Without
    this, one ticker's UNIQUE constraint violation on (ticker, trade_date)
    poisons the session and every subsequent ticker in the same batch
    fails with "This Session's transaction has been rolled back due to
    a previous exception during flush" (see Sentry PYTHON-FASTAPI-3A/3B/38/39).
    """
    try:
        stock = yf.Ticker(ticker_ns)

        # Try auto_adjust=True first (newer yfinance), fall back to False
        df = None
        for auto_adj in [True, False]:
            try:
                df = stock.history(period=period, auto_adjust=auto_adj)
                if df is not None and not df.empty:
                    break
            except Exception:
                continue

        if df is None or df.empty:
            logger.warning(f"No price history for {ticker_ns}")
            # Nothing was added to the session, but roll back defensively
            # in case a previous caller left pending state.
            try:
                db.rollback()
            except Exception:
                pass
            return 0

        logger.info(f"{ticker}: got {len(df)} rows, columns={list(df.columns)}")

        stored = 0
        for idx, row in df.iterrows():
            try:
                trade_date = idx.date() if hasattr(idx, "date") else idx

                # Try multiple column name variants
                close = _safe_float(
                    row.get("Close") or row.get("Adj Close") or row.get("close")
                )
                if close is None or close <= 0:
                    continue

                existing = db.query(DailyPrice).filter_by(
                    ticker=ticker, trade_date=trade_date,
                ).first()
                if existing:
                    continue

                price = DailyPrice(
                    ticker=ticker,
                    trade_date=trade_date,
                    open_price=_safe_float(row.get("Open") or row.get("open")),
                    high_price=_safe_float(row.get("High") or row.get("high")),
                    low_price=_safe_float(row.get("Low") or row.get("low")),
                    close_price=close,
                    volume=int(row.get("Volume") or row.get("volume") or 0),
                    adj_close=close,
                )
                db.add(price)
                stored += 1
            except Exception as row_exc:
                # A single malformed row must not poison the session for
                # the remaining rows of THIS ticker. If the exception came
                # from an autoflush (e.g. UNIQUE violation on a duplicate
                # trade_date), the session is already in pending-rollback
                # state — rollback before continuing.
                logger.debug(
                    "Row skipped for %s (%s): %s: %s",
                    ticker, getattr(idx, "date", lambda: idx)(),
                    type(row_exc).__name__, row_exc,
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                continue

        try:
            db.commit()
        except Exception as commit_exc:
            # Surface the ORIGINAL exception (IntegrityError, DataError,
            # etc.) rather than the cascading "transaction rolled back"
            # message that would hit the outer handler otherwise.
            logger.error(
                "Price history commit failed for %s: %s: %s",
                ticker_ns, type(commit_exc).__name__, commit_exc,
            )
            try:
                db.rollback()
            except Exception:
                pass
            return 0
        return stored

    except Exception as e:
        # Log the real exception type + message so Sentry doesn't just
        # show the downstream "rolled back due to previous exception"
        # cascade. ALWAYS rollback — without this, one ticker's flush
        # failure poisons the shared session for every subsequent ticker
        # in batch_fetch_prices (root cause of the 4-ticker cascade seen
        # on 2026-04-21 at 11:00:13–15 UTC).
        logger.error(
            "Price history failed for %s: %s: %s",
            ticker_ns, type(e).__name__, e,
        )
        try:
            db.rollback()
        except Exception as rb_exc:
            logger.warning(
                "Rollback after price-history failure also failed for %s: %s",
                ticker_ns, rb_exc,
            )
        return 0


def batch_fetch_prices(tickers: list[str], db: Session,
                       period: str = "3y") -> tuple[int, int]:
    """
    Download price history for a batch of tickers.
    Resilient: retries on failure, skips already-loaded stocks,
    saves progress every 10 stocks.
    """
    success = 0
    total_records = 0

    # Skip tickers that already have price data
    tickers_to_fetch = []
    for ticker in tickers:
        existing = db.query(DailyPrice).filter_by(ticker=ticker).first()
        if existing:
            success += 1
            logger.info(f"Skipping {ticker} — already has price data")
        else:
            tickers_to_fetch.append(ticker)

    logger.info(f"Prices: {len(tickers_to_fetch)} to fetch, {success} already loaded")

    for i, ticker in enumerate(tickers_to_fetch):
        ticker_ns = f"{ticker}.NS"
        try:
            records = fetch_price_history(ticker_ns, ticker, db, period)
            if records > 0:
                success += 1
                total_records += records
                logger.info(f"[{i+1}/{len(tickers_to_fetch)}] {ticker}: {records} price records")
            else:
                logger.warning(f"[{i+1}/{len(tickers_to_fetch)}] {ticker}: no price data")
        except Exception as e:
            logger.error(
                "[%d/%d] %s FAILED: %s: %s",
                i + 1, len(tickers_to_fetch), ticker, type(e).__name__, e,
            )
            # Belt-and-braces: fetch_price_history should already have
            # rolled back, but if any exception escaped the inner handler
            # we must clear the session before the next ticker queries it.
            try:
                db.rollback()
            except Exception:
                pass
            # On rate limit, wait longer then retry once
            if "Too Many Requests" in str(e) or "429" in str(e):
                logger.info("Rate limited — waiting 30s before retry")
                time.sleep(30)
                try:
                    records = fetch_price_history(ticker_ns, ticker, db, period)
                    if records > 0:
                        success += 1
                        total_records += records
                except Exception as retry_exc:
                    logger.warning(
                        "Retry after rate-limit failed for %s: %s: %s",
                        ticker, type(retry_exc).__name__, retry_exc,
                    )
                    try:
                        db.rollback()
                    except Exception:
                        pass

        # Rate limit — 2s between calls to avoid yfinance blocking
        time.sleep(2)

        # Save progress every 10 stocks
        if (i + 1) % 10 == 0:
            _update_freshness(db, "prices_yfinance", total_records, "in_progress")
            logger.info(f"Progress: {i+1}/{len(tickers_to_fetch)} stocks, {total_records} total records")

    _update_freshness(db, "prices_yfinance", total_records, "success")
    logger.info(f"Batch prices: {success}/{len(tickers)} stocks, {total_records} records")
    return success, total_records


def batch_fetch_fundamentals(tickers: list[str], db: Session) -> tuple[int, int]:
    """
    Download fundamentals for a batch of tickers.
    Resilient: retries on rate limit, saves progress.
    """
    success = 0
    failed = 0

    for i, ticker in enumerate(tickers):
        ticker_ns = f"{ticker}.NS"
        try:
            result = fetch_and_store_yfinance(ticker_ns, ticker, db)
            # Count a ticker as success if ANY phase wrote rows (partial
            # success is still a win — e.g. financials=ok / price=failed
            # for a post-listing-delay ticker like LTIM).
            if result.financials or result.price or result.quarterly:
                success += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(
                "Fundamentals failed for %s: %s: %s",
                ticker, type(e).__name__, e,
            )
            # Defensive rollback: fetch_and_store_yfinance handles its own
            # cleanup, but a surprise exception path (e.g. network error
            # mid-flush) could leave the shared session pending-rollback
            # and take down every subsequent ticker in the batch.
            try:
                db.rollback()
            except Exception:
                pass
            failed += 1
            if "Too Many Requests" in str(e) or "429" in str(e):
                logger.info("Rate limited — waiting 30s")
                time.sleep(30)

        # Rate limit — 1s between calls
        time.sleep(1)

        if (i + 1) % 10 == 0:
            _update_freshness(db, "fundamentals_yfinance", success, "in_progress")
            logger.info(f"Fundamentals progress: {i+1}/{len(tickers)} ({success} ok, {failed} failed)")

    _update_freshness(db, "fundamentals_yfinance", success, "success")
    logger.info(f"Batch fundamentals: {success} ok, {failed} failed out of {len(tickers)}")
    return success, failed


def _update_freshness(db: Session, data_type: str, count: int, status: str):
    """Update DataFreshness tracker (called periodically during batch)."""
    try:
        freshness = db.query(DataFreshness).filter_by(data_type=data_type).first()
        if not freshness:
            freshness = DataFreshness(data_type=data_type)
            db.add(freshness)
        freshness.last_updated = datetime.utcnow()
        freshness.records_updated = count
        freshness.status = status
        db.commit()
    except Exception as e:
        logger.warning(
            "Freshness update failed: %s: %s", type(e).__name__, e,
        )
        # Same rule as everywhere else in this module: a failed commit
        # leaves the session pending-rollback. Clear it so the next
        # ticker loop iteration doesn't cascade-fail.
        try:
            db.rollback()
        except Exception:
            pass


def _to_cr(value) -> float | None:
    """Convert from raw rupees to Crore."""
    try:
        if value is None:
            return None
        return float(value) / 1e7
    except Exception:
        return None


def _to_lakhs(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value) / 1e5
    except Exception:
        return None


def _safe_float(value) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _safe_pct(numerator, denominator) -> float | None:
    try:
        if numerator and denominator and denominator != 0:
            return (numerator / denominator) * 100
        return None
    except Exception:
        return None


def _get_val(df: pd.DataFrame, row_name: str, col):
    try:
        if row_name in df.index:
            val = df.loc[row_name, col]
            return float(val) if val is not None and not pd.isna(val) else None
        return None
    except Exception:
        return None
