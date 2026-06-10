# backend/services/verdict_attribution_service.py
# ═══════════════════════════════════════════════════════════════
# Verdict attribution — does YIQ's verdict at T-N actually translate
# into excess return relative to a benchmark over the holding period?
#
# Distinct from fv_accuracy_service.py (which evaluates DIRECTIONAL
# correctness — did the price move the way the verdict implied)
# and from yiq50_backtest_service.py (which evaluates a tradable
# rotation BASKET vs Nifty proxy). This module evaluates each
# individual verdict for one ticker, returns the per-period attribution
# rows, and rolls them up into a per-ticker track record. The output
# powers the Performance Attribution Panel on the analysis page.
#
# Pure-compute layer
# ───────────────────
# Every function here is pure: it takes already-resolved "snapshot rows"
# (dicts with verdict / FV / price_then / price_now / benchmark returns
# / sector returns) and returns dataclasses or JSON-serializable dicts.
# Loader SQL belongs to the router layer — that keeps this module
# trivially testable and lets the router swap data sources (live DB,
# fixture, mock) without touching attribution math.
#
# Holding-period convention
# ─────────────────────────
# Each VerdictAttribution row covers a "verdict episode": from the
# date YIQ first published this verdict for the ticker (period_start)
# to the next verdict change OR to the end of the lookback window,
# whichever is earlier (period_end). actual_return_pct, nifty_return_pct
# and sector_return_pct are computed over EXACTLY the same window so
# alpha is apples-to-apples.
#
# SEBI-compliant vocabulary
# ─────────────────────────
# The model emits legacy verdicts ("undervalued", "fairly_valued",
# "overvalued"). Public attribution rows preserve the verdict string
# verbatim because the analysis page maps to public bands at the UI
# layer (see backend/services/fv_accuracy_service.py for the mapping).
#
# Never use the banned words "outperform" / "underperform" / "buy" /
# "sell" / "hold" / "appears" / "should" in any field name, default
# value, log message or docstring sentence that could ship to the
# wire. Use "alpha" or "excess return" instead.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Iterable, Optional


# ─────────────────────────────────────────────────────────────────
# Direction thresholds (in percent). A verdict is "proven correct"
# when the realized excess return relative to Nifty matches the
# direction implied by the verdict:
#
#   - undervalued    → alpha_vs_nifty > +DIR_BELOW_ALPHA_PCT
#   - overvalued     → alpha_vs_nifty < -DIR_ABOVE_ALPHA_PCT
#   - fairly_valued  → |alpha_vs_nifty| ≤ DIR_NEAR_ALPHA_BAND
#
# These mirror the fv_accuracy_service thresholds (5% / 5% / 10%)
# so the two services remain conceptually consistent. Centralising
# them at module scope makes them tunable from one place.
# ─────────────────────────────────────────────────────────────────
DIR_BELOW_ALPHA_PCT: float = 5.0
DIR_ABOVE_ALPHA_PCT: float = 5.0
DIR_NEAR_ALPHA_BAND: float = 10.0

# Bucket width for the rolling-30d track record. We summarise alpha
# in 30-day rolling windows so the UI chart can render a sparkline
# without exposing per-day noise.
ROLLING_WINDOW_DAYS: int = 30


_VALID_VERDICTS: frozenset[str] = frozenset({
    "undervalued",
    "fairly_valued",
    "overvalued",
})


# ─────────────────────────────────────────────────────────────────
# Dataclasses — match the public wire shape exactly. The router
# serialises via to_dict() so any UI / API consumer can rely on
# field names and types being stable.
# ─────────────────────────────────────────────────────────────────
@dataclass
class VerdictAttribution:
    """One verdict episode and how it fared vs benchmarks."""

    ticker: str
    period_start: str          # ISO YYYY-MM-DD
    period_end: str            # ISO YYYY-MM-DD
    verdict_at_start: str      # raw model verdict (undervalued / fairly_valued / overvalued)
    fv_at_start: float
    price_at_start: float
    price_at_end: float
    actual_return_pct: float
    nifty_return_pct: float    # Nifty / broad-market benchmark over same window
    sector_return_pct: float   # Sector benchmark over same window
    alpha_vs_nifty: float      # actual − nifty (excess return)
    alpha_vs_sector: float     # actual − sector (excess return)
    verdict_proven_correct: bool


@dataclass
class AttributionSummary:
    """Per-ticker roll-up across all verdict episodes in window."""

    ticker: str
    total_verdicts_tracked: int
    direction_correct_pct: float                       # 0..100; share where verdict_proven_correct
    avg_alpha_vs_nifty_pct: float
    median_alpha_vs_nifty_pct: float
    best_verdict: Optional[VerdictAttribution]
    worst_verdict: Optional[VerdictAttribution]
    rolling_30d_track_record: list[dict] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Helpers — small, defensive numeric utilities. Each returns None
# on any input that can't be coerced to a finite float so the
# attribution pass never raises on malformed rows.
# ─────────────────────────────────────────────────────────────────
def _safe_float(x) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _return_pct(price_then: Optional[float], price_now: Optional[float]) -> Optional[float]:
    if price_then is None or price_now is None or price_then <= 0:
        return None
    r = (price_now - price_then) / price_then * 100.0
    return r if math.isfinite(r) else None


def _mean(xs: list[float]) -> Optional[float]:
    return round(sum(xs) / len(xs), 4) if xs else None


def _median(xs: list[float]) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return round(s[mid], 4)
    return round((s[mid - 1] + s[mid]) / 2.0, 4)


def _normalise_verdict(v) -> Optional[str]:
    if not v:
        return None
    s = str(v).strip().lower()
    return s if s in _VALID_VERDICTS else None


def _direction_proven(verdict: str, alpha_vs_nifty: float) -> bool:
    """Is the realised alpha consistent with the verdict's direction?

    Mirrors fv_accuracy_service.compute_directional_accuracy but uses
    ALPHA (excess return vs Nifty) rather than raw return. Why alpha:
    a +30% raw return during a +35% Nifty year is not evidence the
    verdict was correct — the market did the work. The verdict only
    earns credit if it added EXCESS return.
    """
    if verdict == "undervalued":
        return alpha_vs_nifty > DIR_BELOW_ALPHA_PCT
    if verdict == "overvalued":
        return alpha_vs_nifty < -DIR_ABOVE_ALPHA_PCT
    if verdict == "fairly_valued":
        return abs(alpha_vs_nifty) <= DIR_NEAR_ALPHA_BAND
    return False


# ─────────────────────────────────────────────────────────────────
# Episode builder
# ─────────────────────────────────────────────────────────────────
def build_attribution_from_row(row: dict) -> Optional[VerdictAttribution]:
    """Construct one VerdictAttribution from a raw snapshot dict.

    Expected keys (extras ignored):
      - ticker (str)
      - period_start (str ISO)
      - period_end (str ISO)
      - verdict_at_start (str, raw model verdict)
      - fv_at_start (float)
      - price_at_start (float)
      - price_at_end (float)
      - nifty_return_pct (float)
      - sector_return_pct (float)

    Returns None when:
      - verdict is missing / not in the known set, OR
      - either price is missing / non-positive, OR
      - either benchmark return is missing,
    so that bad rows never poison the summary.
    """
    ticker = (row.get("ticker") or "").strip().upper()
    if not ticker:
        return None

    verdict = _normalise_verdict(row.get("verdict_at_start"))
    if verdict is None:
        return None

    fv = _safe_float(row.get("fv_at_start"))
    p_start = _safe_float(row.get("price_at_start"))
    p_end = _safe_float(row.get("price_at_end"))
    actual = _return_pct(p_start, p_end)
    if fv is None or p_start is None or p_end is None or actual is None:
        return None

    nifty = _safe_float(row.get("nifty_return_pct"))
    sector = _safe_float(row.get("sector_return_pct"))
    if nifty is None or sector is None:
        return None

    alpha_n = round(actual - nifty, 4)
    alpha_s = round(actual - sector, 4)
    proven = _direction_proven(verdict, alpha_n)

    period_start = str(row.get("period_start") or "")[:10]
    period_end = str(row.get("period_end") or "")[:10]
    if not period_start or not period_end:
        return None

    return VerdictAttribution(
        ticker=ticker,
        period_start=period_start,
        period_end=period_end,
        verdict_at_start=verdict,
        fv_at_start=round(fv, 4),
        price_at_start=round(p_start, 4),
        price_at_end=round(p_end, 4),
        actual_return_pct=round(actual, 4),
        nifty_return_pct=round(nifty, 4),
        sector_return_pct=round(sector, 4),
        alpha_vs_nifty=alpha_n,
        alpha_vs_sector=alpha_s,
        verdict_proven_correct=proven,
    )


# ─────────────────────────────────────────────────────────────────
# Rolling track record
# ─────────────────────────────────────────────────────────────────
def _rolling_track_record(
    attributions: list[VerdictAttribution],
    window_days: int = ROLLING_WINDOW_DAYS,
) -> list[dict]:
    """Bucket attributions into period-end-aligned rolling windows.

    Each bucket is identified by the END date of the verdict episode
    (so the row enters the chart on the date the holding period
    closed) and reports the rolling mean alpha vs Nifty across all
    episodes whose end date falls in the same `window_days` bucket.

    The bucket key is the integer ordinal of `period_end // window_days`
    in days-since-epoch so the buckets are deterministic regardless
    of input order. Empty input yields an empty list.
    """
    if not attributions:
        return []

    from datetime import date as _D

    def _ordinal_bucket(d_iso: str) -> int:
        try:
            d = _D.fromisoformat(d_iso)
        except Exception:
            return -1
        return d.toordinal() // window_days

    grouped: dict[int, list[VerdictAttribution]] = {}
    for a in attributions:
        b = _ordinal_bucket(a.period_end)
        if b < 0:
            continue
        grouped.setdefault(b, []).append(a)

    out: list[dict] = []
    for b in sorted(grouped.keys()):
        bucket_attrs = grouped[b]
        alphas = [x.alpha_vs_nifty for x in bucket_attrs]
        # Bucket-end date = the latest period_end in the bucket.
        end_dates = sorted(x.period_end for x in bucket_attrs)
        out.append({
            "bucket_end": end_dates[-1],
            "verdict_count": len(bucket_attrs),
            "mean_alpha_vs_nifty_pct": _mean(alphas) or 0.0,
            # Direction-correct share inside the bucket — useful for a
            # chip hover-state ("8 of 10 verdicts proven correct in
            # this 30d window").
            "direction_correct_pct": round(
                100.0 * sum(1 for x in bucket_attrs if x.verdict_proven_correct) / len(bucket_attrs),
                2,
            ),
        })
    return out


# ─────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────
def summarise(
    ticker: str,
    rows: Iterable[dict],
) -> AttributionSummary:
    """Roll a stream of snapshot rows into a per-ticker summary.

    Pure: every numeric field is derived from the input rows; the
    function never touches the DB. Bad rows are silently dropped (see
    build_attribution_from_row) so the summary degrades gracefully
    when a ticker has only a few clean episodes.

    Empty input still returns a valid summary (zero counts, zero
    alpha) so the router can serialise it without branching on None.
    """
    ticker_norm = (ticker or "").strip().upper()
    attributions: list[VerdictAttribution] = []
    for r in rows:
        att = build_attribution_from_row(r)
        if att is not None:
            attributions.append(att)

    if not attributions:
        return AttributionSummary(
            ticker=ticker_norm,
            total_verdicts_tracked=0,
            direction_correct_pct=0.0,
            avg_alpha_vs_nifty_pct=0.0,
            median_alpha_vs_nifty_pct=0.0,
            best_verdict=None,
            worst_verdict=None,
            rolling_30d_track_record=[],
        )

    alphas = [a.alpha_vs_nifty for a in attributions]
    proven = sum(1 for a in attributions if a.verdict_proven_correct)
    avg_alpha = _mean(alphas) or 0.0
    med_alpha = _median(alphas) or 0.0

    best = max(attributions, key=lambda a: a.alpha_vs_nifty)
    worst = min(attributions, key=lambda a: a.alpha_vs_nifty)

    return AttributionSummary(
        ticker=ticker_norm,
        total_verdicts_tracked=len(attributions),
        direction_correct_pct=round(100.0 * proven / len(attributions), 2),
        avg_alpha_vs_nifty_pct=avg_alpha,
        median_alpha_vs_nifty_pct=med_alpha,
        best_verdict=best,
        worst_verdict=worst,
        rolling_30d_track_record=_rolling_track_record(attributions),
    )


# ─────────────────────────────────────────────────────────────────
# Public entry point — DB-aware. The router calls this. Falls back
# to an empty summary when the loader returns nothing so the route
# can always serve a 200 (the UI handles empty state).
# ─────────────────────────────────────────────────────────────────
def compute_attribution(
    ticker: str,
    lookback_days: int = 365,
    loader=None,
) -> AttributionSummary:
    """Compute the attribution summary for `ticker` over `lookback_days`.

    `loader` is an optional callable
        loader(ticker: str, lookback_days: int) -> Iterable[dict]
    that returns the snapshot rows expected by build_attribution_from_row.
    When omitted, the default Postgres loader from this module is used.
    Tests pass a fixture loader to keep compute_attribution() unit-pure.
    """
    if loader is None:
        loader = _default_snapshot_loader
    try:
        rows = list(loader(ticker, lookback_days))
    except Exception:
        # Loader failures must NEVER 500 the analysis page — log
        # surfaces in Sentry via the router catch, here we degrade
        # to an empty summary.
        rows = []
    return summarise(ticker, rows)


# ─────────────────────────────────────────────────────────────────
# Serialisation
# ─────────────────────────────────────────────────────────────────
def to_dict(summary: AttributionSummary) -> dict:
    """Convert an AttributionSummary to a JSON-serialisable dict.

    `best_verdict` / `worst_verdict` are unwrapped to dicts as well so
    the FastAPI layer can return the result directly without further
    massaging. Rolling track record is already list[dict].
    """
    if summary is None:
        return {}
    out = asdict(summary)
    # best/worst — already dicts after asdict() recursion.
    return out


# ─────────────────────────────────────────────────────────────────
# Default DB loader. Kept out of compute_attribution() so tests can
# patch this single symbol or pass an explicit loader.
#
# Returns iterable of dicts shaped for build_attribution_from_row.
# The loader is responsible for:
#   1. Reading fair_value_history episodes for this ticker (each
#      contiguous run of the same verdict is one episode).
#   2. Resolving price_at_start / price_at_end from daily_prices.
#   3. Resolving nifty_return_pct / sector_return_pct over the
#      identical window via the equal-weighted Nifty-top-5 proxy and
#      sector proxy basket helpers from yiq50_backtest_service.py.
#
# All DB / file reads are wrapped in try/except so a single missing
# parquet doesn't truncate the entire ticker's history — the row is
# simply omitted and the summary moves on.
# ─────────────────────────────────────────────────────────────────
def _default_snapshot_loader(ticker: str, lookback_days: int) -> list[dict]:
    """Materialise verdict episodes + benchmark returns from prod data.

    Implementation kept thin: the heavy SQL lives here so the pure
    compute pipeline above is fully exercised by tests without
    needing a database.
    """
    import logging
    from datetime import date as _D, timedelta as _Td

    logger = logging.getLogger("yieldiq.verdict_attribution")

    try:
        from sqlalchemy import text
        from backend.services.market_data_service import _get_session
    except Exception as exc:
        logger.warning("verdict_attribution loader imports failed: %s", exc)
        return []

    sess = _get_session()
    if sess is None:
        return []

    bare = ticker.replace(".NS", "").replace(".BO", "").upper()
    suffixed = f"{bare}.NS"
    today = _D.today()
    cutoff = today - _Td(days=lookback_days)

    try:
        # Fetch ordered FV-history rows in window so we can collapse
        # into verdict-change episodes downstream.
        rows = sess.execute(
            text(
                """
                SELECT date, ticker, verdict, fair_value
                FROM fair_value_history
                WHERE ticker IN (:a, :b)
                  AND date >= :cutoff
                ORDER BY date ASC
                """
            ),
            {"a": bare, "b": suffixed, "cutoff": cutoff},
        ).fetchall()
    except Exception as exc:
        logger.warning("fair_value_history read failed for %s: %s", bare, exc)
        sess.close()
        return []
    finally:
        try:
            sess.close()
        except Exception:
            pass

    if not rows:
        return []

    # Episode collapse: contiguous same-verdict runs become one row.
    episodes: list[dict] = []
    current_start_date = None
    current_verdict = None
    current_fv = None
    last_date = None

    for r in rows:
        d, _t, v, fv = r[0], r[1], r[2], r[3]
        v_norm = _normalise_verdict(v)
        if v_norm is None:
            continue
        if current_verdict is None:
            current_verdict = v_norm
            current_start_date = d
            current_fv = float(fv) if fv is not None else None
        elif v_norm != current_verdict:
            # Close previous episode at one day before this verdict change.
            episodes.append({
                "start_date": current_start_date,
                "end_date": d,
                "verdict": current_verdict,
                "fv_at_start": current_fv,
            })
            current_verdict = v_norm
            current_start_date = d
            current_fv = float(fv) if fv is not None else None
        last_date = d

    # Close the trailing open episode at today / last observed date.
    if current_verdict is not None:
        episodes.append({
            "start_date": current_start_date,
            "end_date": last_date if last_date is not None else today,
            "verdict": current_verdict,
            "fv_at_start": current_fv,
        })

    if not episodes:
        return []

    # Resolve prices + benchmark returns for each episode via the same
    # parquet-backed helpers the YIQ50 backtest service uses. Failing
    # episodes are dropped silently.
    try:
        import duckdb
        from backend.services.yiq50_backtest_service import (
            _price_on,
            _basket_return_pct,
            NIFTY_PROXY,
        )
    except Exception as exc:
        logger.warning("yiq50_backtest helpers unavailable: %s", exc)
        return []

    # Sector basket — best-effort. We do not block on its presence;
    # an episode with a missing sector return is dropped.
    sector_proxy = _resolve_sector_proxy(bare)

    conn = duckdb.connect()
    snapshots: list[dict] = []
    try:
        for ep in episodes:
            try:
                start_d = ep["start_date"]
                end_d = ep["end_date"]
                if hasattr(start_d, "date"):
                    start_d = start_d.date()
                if hasattr(end_d, "date"):
                    end_d = end_d.date()

                p_start = _price_on(conn, bare, start_d)
                p_end = _price_on(conn, bare, end_d)
                if p_start is None or p_end is None:
                    continue

                nifty_ret, _ = _basket_return_pct(conn, NIFTY_PROXY, start_d, end_d)
                sector_ret, _ = _basket_return_pct(conn, sector_proxy, start_d, end_d)
                if nifty_ret is None or sector_ret is None:
                    continue

                snapshots.append({
                    "ticker": bare,
                    "period_start": start_d.isoformat(),
                    "period_end": end_d.isoformat(),
                    "verdict_at_start": ep["verdict"],
                    "fv_at_start": ep["fv_at_start"] or 0.0,
                    "price_at_start": p_start,
                    "price_at_end": p_end,
                    "nifty_return_pct": nifty_ret,
                    "sector_return_pct": sector_ret,
                })
            except Exception as exc:
                logger.debug(
                    "verdict_attribution episode skipped for %s @ %s: %s",
                    bare, ep.get("start_date"), exc,
                )
                continue
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return snapshots


# ─────────────────────────────────────────────────────────────────
# Sector proxy basket — small mapping from canonical sector to a
# representative 3-5 ticker basket. Mirrors the spirit of
# sector_benchmarks.py but returns BARE tickers that
# yiq50_backtest_service._basket_return_pct can price from parquet
# (the ^CNX* tickers in sector_benchmarks aren't in our parquet
# archive, so we use the underlying constituents instead).
# ─────────────────────────────────────────────────────────────────
_SECTOR_PROXY_BASKETS: dict[str, list[str]] = {
    "IT Services":          ["TCS", "INFY", "WIPRO", "HCLTECH"],
    "Banks":                ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK"],
    "Pharma":               ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB"],
    "FMCG":                 ["HINDUNILVR", "ITC", "NESTLEIND", "DABUR"],
    "Auto":                 ["MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO"],
    "Metals":               ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL"],
    "Energy":               ["RELIANCE", "ONGC", "NTPC", "POWERGRID"],
    "Financial Services":   ["BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE"],
    # Default = Nifty proxy itself; ensures we always emit a return.
    "_default":             ["RELIANCE", "HDFCBANK", "TCS", "INFY", "ITC"],
}


def _resolve_sector_proxy(ticker: str) -> list[str]:
    """Best-effort: read stocks.sector and map to a proxy basket.

    Pure-fallback to the default basket on any read error so the
    attribution loader never blocks on missing sector metadata.
    """
    try:
        from sqlalchemy import text
        from backend.services.market_data_service import _get_session
    except Exception:
        return _SECTOR_PROXY_BASKETS["_default"]

    sess = _get_session()
    if sess is None:
        return _SECTOR_PROXY_BASKETS["_default"]
    try:
        row = sess.execute(
            text("SELECT sector FROM stocks WHERE ticker = :t LIMIT 1"),
            {"t": ticker},
        ).fetchone()
    except Exception:
        return _SECTOR_PROXY_BASKETS["_default"]
    finally:
        try:
            sess.close()
        except Exception:
            pass
    if row is None or row[0] is None:
        return _SECTOR_PROXY_BASKETS["_default"]

    # Light alias resolution — keep the proxy table small and let
    # sector_benchmarks own the full alias map. We do a case-insensitive
    # contains check against canonical keys.
    sector = str(row[0]).strip()
    lower = sector.lower()
    for canonical, basket in _SECTOR_PROXY_BASKETS.items():
        if canonical == "_default":
            continue
        if canonical.lower() in lower or lower in canonical.lower():
            return basket
    return _SECTOR_PROXY_BASKETS["_default"]
