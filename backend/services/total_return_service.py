# backend/services/total_return_service.py
# ═══════════════════════════════════════════════════════════════
# Total Return vs Price Return service.
#
# Reinvests dividend events at the close-on-ex-date so the
# resulting curve compounds — material for high-payout names
# (FMCG, IT) where 5y total return can be 30%+ above price return.
#
# Read-only at request time. No persistence — relies on the 6h
# in-router edge cache for performance. Inputs are sourced from:
#   - corporate_actions (dividend ex_date + per-share amount)
#   - daily_prices / parquet archive (close on ex_date + endpoint dates)
#
# The two existing surfaces (dividend_service._fetch_from_db and
# price_history_service.get_price_history) are reused so the same
# dividend series powers /total-return as powers /dividends, and
# the same price history powers /total-return as /price-history.
# That keeps drift between surfaces impossible by construction.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger("yieldiq.total_return")


@dataclass
class TotalReturnPoint:
    """Single point on the cumulative-return curve.

    ``price_return_pct`` and ``total_return_pct`` are cumulative
    percentages from the period start (e.g. 0.0 on day 0,
    +52.3 means the position is up 52.3%).
    """
    date: str          # ISO YYYY-MM-DD
    price_return_pct: float
    total_return_pct: float


@dataclass
class TotalReturnResult:
    """Top-level result returned by ``compute_total_return``."""
    ticker: str
    years: int
    start_date: Optional[str]
    end_date: Optional[str]
    start_price: Optional[float]
    end_price: Optional[float]
    price_return_pct: Optional[float]
    total_return_pct: Optional[float]
    dividends_paid_total: float
    dividend_count: int
    reinvested_value_per_share: Optional[float]
    initial_investment: float
    price_only_value: Optional[float]
    total_return_value: Optional[float]
    dividend_boost_pct: Optional[float]
    curve: list[TotalReturnPoint]
    data_source: str   # "db" | "yfinance" | "mixed" | "unavailable"
    notes: list[str]


# ── price helpers ──────────────────────────────────────────────


def _to_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v[:10]).date()
        except Exception:
            return None
    return None


def _price_on_or_after(
    prices_by_date: dict[date, float],
    sorted_dates: list[date],
    target: date,
    max_lookahead_days: int = 7,
) -> Optional[tuple[date, float]]:
    """Return the first (date, close_price) at or after ``target`` within
    a small forward window.

    Used so dividend ex_dates that fall on weekends / NSE holidays still
    find the next trading day's close. Returns None if no price within
    ``max_lookahead_days`` (e.g. the ex_date is in the future or after
    the last loaded close).
    """
    if not sorted_dates:
        return None
    end_window = target + timedelta(days=max_lookahead_days)
    # Linear scan is fine — sorted_dates is at most ~2,500 entries (10y).
    for d in sorted_dates:
        if d < target:
            continue
        if d > end_window:
            return None
        p = prices_by_date.get(d)
        if p is not None and p > 0:
            return (d, p)
    return None


def _price_on_or_before(
    prices_by_date: dict[date, float],
    sorted_dates: list[date],
    target: date,
    max_lookback_days: int = 7,
) -> Optional[tuple[date, float]]:
    """Mirror of ``_price_on_or_after`` but scanning backwards. Used to
    anchor the period end if `target` (e.g. today) doesn't have a
    trade row yet."""
    if not sorted_dates:
        return None
    start_window = target - timedelta(days=max_lookback_days)
    for d in reversed(sorted_dates):
        if d > target:
            continue
        if d < start_window:
            return None
        p = prices_by_date.get(d)
        if p is not None and p > 0:
            return (d, p)
    return None


# ── dividend loading ───────────────────────────────────────────


def _load_dividend_events(
    ticker: str,
    start: date,
    end: date,
) -> tuple[list[dict], str]:
    """Return list of `{ex_date, amount}` events with ex_date in
    ``[start, end]``, oldest→newest. Second tuple element is the
    data source tag ("db" | "yfinance" | "unavailable") for the
    UI's transparency line.

    Reuses ``DividendService._fetch_from_db`` so the dividend series
    matches GET /api/v1/public/dividends/{ticker} byte-for-byte (modulo
    the window filter). Falls back to yfinance .dividends on DB miss.
    """
    events: list[dict] = []
    source = "unavailable"
    try:
        from backend.services.dividend_service import DividendService
        svc = DividendService()
        db_series = svc._fetch_from_db(ticker)
        if db_series:
            source = "db"
            for row in db_series:
                ex = _to_date(row.get("ex_date"))
                amt = row.get("amount")
                if ex is None or amt is None:
                    continue
                try:
                    amt_f = float(amt)
                except (TypeError, ValueError):
                    continue
                if amt_f <= 0:
                    continue
                if ex < start or ex > end:
                    continue
                events.append({"ex_date": ex, "amount": amt_f})
            events.sort(key=lambda e: e["ex_date"])
            return events, source
    except Exception as exc:
        logger.debug("dividend DB load failed for %s: %s", ticker, exc)

    # ── yfinance fallback ────────────────────────────────────────
    try:
        import yfinance as yf
        t = yf.Ticker(ticker if ticker.endswith(".NS") or "." in ticker else f"{ticker}.NS")
        hist = t.dividends
        if hist is None or len(hist) == 0:
            return events, "unavailable"
        source = "yfinance"
        for ts, amt in hist.items():
            ex = _to_date(ts)
            if ex is None:
                continue
            try:
                amt_f = float(amt)
            except (TypeError, ValueError):
                continue
            if amt_f <= 0:
                continue
            if ex < start or ex > end:
                continue
            events.append({"ex_date": ex, "amount": amt_f})
        events.sort(key=lambda e: e["ex_date"])
    except Exception as exc:
        logger.debug("yfinance dividend fallback failed for %s: %s", ticker, exc)

    return events, source


# ── price loading ──────────────────────────────────────────────


def _load_prices(
    ticker: str,
    start: date,
    end: date,
) -> dict[date, float]:
    """Return {trade_date: close_price} for the inclusive window.

    Delegates to ``price_history_service.get_price_history`` which
    unions the PG live table with the Parquet archive. Empty dict
    on any error — caller treats as "data unavailable".
    """
    out: dict[date, float] = {}
    try:
        from backend.services.price_history_service import get_price_history
        clean = ticker.replace(".NS", "").replace(".BO", "").upper()
        df = get_price_history(clean, start=start, end=end)
        if df is None or df.empty:
            return out
        for r in df.to_dict(orient="records"):
            td = _to_date(r.get("trade_date"))
            cp = r.get("close_price")
            if td is None or cp is None:
                continue
            try:
                cp_f = float(cp)
            except (TypeError, ValueError):
                continue
            if cp_f <= 0:
                continue
            out[td] = cp_f
    except Exception as exc:
        logger.debug("price history load failed for %s: %s", ticker, exc)
    return out


# ── main compute ───────────────────────────────────────────────


def compute_total_return(
    ticker: str,
    years: int,
    initial_investment: float = 100_000.0,
    curve_points: int = 60,
) -> TotalReturnResult:
    """Compute price return + total return (reinvested dividends) for
    ``ticker`` over the trailing ``years``-year window.

    Args:
        ticker:  NSE/BSE symbol; suffix optional (we normalise both
            strip and ``.NS`` forms for the two underlying services).
        years:   horizon in years (1/3/5/10 are the UI choices but any
            positive int works).
        initial_investment:  notional rupee amount used so the UI can
            show "₹X became ₹Y" framing. Defaults to ₹1,00,000.
        curve_points: target number of points on the chart curve.
            We downsample evenly from the daily series to keep the
            JSON payload small.

    Returns:
        TotalReturnResult — always populated. ``price_return_pct`` and
        ``total_return_pct`` are None when prices are unavailable, in
        which case the UI surfaces an "unavailable" state.

    Compounding model:
        At each dividend ex_date inside the window we add
        (dividend_per_share / close_on_or_after_ex_date) to a running
        "reinvested share count" multiplier. The total-return value on
        the end date is therefore:
            end_price * (1 + sum(div_t / px_t for t in events))
        normalised by the start price. This is the standard textbook
        TR formula (no DRIP fractional-share rounding, no tax drag).
    """
    if years <= 0:
        raise ValueError("years must be positive")

    today = date.today()
    end = today
    start = today.replace(year=today.year - years) if today.year - years >= 1900 else today

    prices_by_date = _load_prices(ticker, start - timedelta(days=14), end + timedelta(days=14))
    sorted_dates = sorted(prices_by_date.keys())

    notes: list[str] = []
    if not sorted_dates:
        return TotalReturnResult(
            ticker=ticker.upper(),
            years=years,
            start_date=None,
            end_date=None,
            start_price=None,
            end_price=None,
            price_return_pct=None,
            total_return_pct=None,
            dividends_paid_total=0.0,
            dividend_count=0,
            reinvested_value_per_share=None,
            initial_investment=initial_investment,
            price_only_value=None,
            total_return_value=None,
            dividend_boost_pct=None,
            curve=[],
            data_source="unavailable",
            notes=["No price history available for this ticker in the window."],
        )

    # Anchor start and end to the nearest in-window trade dates.
    anchor_start = _price_on_or_after(prices_by_date, sorted_dates, start)
    anchor_end = _price_on_or_before(prices_by_date, sorted_dates, end)
    if anchor_start is None or anchor_end is None:
        return TotalReturnResult(
            ticker=ticker.upper(),
            years=years,
            start_date=None,
            end_date=None,
            start_price=None,
            end_price=None,
            price_return_pct=None,
            total_return_pct=None,
            dividends_paid_total=0.0,
            dividend_count=0,
            reinvested_value_per_share=None,
            initial_investment=initial_investment,
            price_only_value=None,
            total_return_value=None,
            dividend_boost_pct=None,
            curve=[],
            data_source="unavailable",
            notes=["Insufficient price data to anchor the requested window."],
        )

    start_date, start_price = anchor_start
    end_date, end_price = anchor_end

    if start_date >= end_date:
        notes.append("Anchor dates collapsed — using same-day fallback.")

    # ── dividend events inside the window ─────────────────────
    div_events, div_source = _load_dividend_events(ticker, start_date, end_date)

    # Build reinvest multiplier: each event reinvests its per-share
    # amount at the close on/after ex_date. Sum the per-share share
    # accumulations (div_t / px_t) so:
    #   final_shares = 1 + sum(div_t / px_t)
    reinvest_share_acc = 0.0
    dividends_paid_total = 0.0
    used_event_count = 0
    for ev in div_events:
        anchor = _price_on_or_after(prices_by_date, sorted_dates, ev["ex_date"])
        if anchor is None:
            continue
        _, px_at = anchor
        if px_at <= 0:
            continue
        amt = float(ev["amount"])
        reinvest_share_acc += amt / px_at
        dividends_paid_total += amt
        used_event_count += 1

    # ── headline returns ──────────────────────────────────────
    price_return_pct = (end_price / start_price - 1.0) * 100.0
    total_shares_per_initial = 1.0 + reinvest_share_acc
    total_return_pct = (
        (end_price * total_shares_per_initial) / start_price - 1.0
    ) * 100.0

    price_only_value = initial_investment * (1.0 + price_return_pct / 100.0)
    total_return_value = initial_investment * (1.0 + total_return_pct / 100.0)
    dividend_boost_pct = total_return_pct - price_return_pct

    # ── curve: downsample to curve_points evenly along sorted_dates,
    # restricted to in-window trade dates. ────────────────────────
    in_window = [d for d in sorted_dates if start_date <= d <= end_date]
    curve: list[TotalReturnPoint] = []
    if in_window:
        n = len(in_window)
        step = max(1, n // max(1, curve_points))
        # Pre-compute running cumulative reinvest at each in-window date.
        event_idx = 0
        events_sorted = sorted(div_events, key=lambda e: e["ex_date"])
        running_acc = 0.0
        for i, d in enumerate(in_window):
            # apply any events with ex_date <= d that we haven't yet
            while event_idx < len(events_sorted) and events_sorted[event_idx]["ex_date"] <= d:
                ev = events_sorted[event_idx]
                anchor = _price_on_or_after(prices_by_date, sorted_dates, ev["ex_date"])
                if anchor is not None:
                    _, px_at = anchor
                    if px_at > 0:
                        running_acc += float(ev["amount"]) / px_at
                event_idx += 1

            if i % step != 0 and i != n - 1:
                continue
            px = prices_by_date.get(d)
            if px is None or px <= 0:
                continue
            pr = (px / start_price - 1.0) * 100.0
            tr = (px * (1.0 + running_acc) / start_price - 1.0) * 100.0
            curve.append(TotalReturnPoint(
                date=d.isoformat(),
                price_return_pct=round(pr, 4),
                total_return_pct=round(tr, 4),
            ))

    return TotalReturnResult(
        ticker=ticker.upper(),
        years=years,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        start_price=round(start_price, 4),
        end_price=round(end_price, 4),
        price_return_pct=round(price_return_pct, 4),
        total_return_pct=round(total_return_pct, 4),
        dividends_paid_total=round(dividends_paid_total, 4),
        dividend_count=used_event_count,
        reinvested_value_per_share=round(end_price * total_shares_per_initial, 4),
        initial_investment=initial_investment,
        price_only_value=round(price_only_value, 2),
        total_return_value=round(total_return_value, 2),
        dividend_boost_pct=round(dividend_boost_pct, 4),
        curve=curve,
        data_source=div_source if used_event_count > 0 else ("price_only" if not div_events else div_source),
        notes=notes,
    )


def result_to_dict(r: TotalReturnResult) -> dict:
    """Pydantic-free serializer — keeps the router slim and the
    response shape testable without an extra schema layer."""
    return {
        "ticker": r.ticker,
        "years": r.years,
        "start_date": r.start_date,
        "end_date": r.end_date,
        "start_price": r.start_price,
        "end_price": r.end_price,
        "price_return": r.price_return_pct,
        "total_return": r.total_return_pct,
        "dividends_paid_total": r.dividends_paid_total,
        "dividend_count": r.dividend_count,
        "reinvested_value": r.reinvested_value_per_share,
        "initial_investment": r.initial_investment,
        "price_only_value": r.price_only_value,
        "total_return_value": r.total_return_value,
        "dividend_boost_pct": r.dividend_boost_pct,
        "curve": [
            {
                "date": p.date,
                "price_return": p.price_return_pct,
                "total_return": p.total_return_pct,
            }
            for p in r.curve
        ],
        "data_source": r.data_source,
        "notes": r.notes,
    }
