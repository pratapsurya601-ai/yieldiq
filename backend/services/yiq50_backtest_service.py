# backend/services/yiq50_backtest_service.py
# ═══════════════════════════════════════════════════════════════
# Day-89: YieldIQ-50 backtest — annual top-5 rotation vs Nifty.
#
# Answers: "Across the last N years, the top 5 stocks within the
# YieldIQ-50 universe (curated 50) by margin of safety AT YEAR
# START — held 12 months, sold at year end, repeated annually —
# what hypothetical return would the basket have produced vs an
# equal-weighted Nifty-top-5 proxy basket?"
#
# Honest caveats (returned in payload, surfaced on UI):
#   - The `fair_value_history` rows are written by the monthly
#     backfill using a `fv_today` projection — i.e. historical
#     mos_pct rows are a back-projected proxy, NOT the FV value
#     the platform would have shown at that historical date.
#     This is the "current-Score proxy" method.
#   - Survivorship: the YieldIQ-50 universe is the CURRENT canary
#     basket, not the basket as it existed at year-start.
#   - Benchmark is a Nifty-top-5 proxy basket (RELIANCE / HDFCBANK
#     / TCS / INFY / ITC), aligned with the rest of the platform's
#     backtest tooling. Index data (NIFTYBEES) is not cached here.
#
# Vocabulary discipline (SEBI): never returns "buy" / "sell" /
# "hold" / "outperform" / "underperform" / "recommend". The
# payload uses "delta_pct" not "alpha" in raw fields; the page
# layer wraps it as "delta vs Nifty proxy" in user-facing copy.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("yieldiq.yiq50_backtest")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CANARY_50 = _REPO_ROOT / "scripts" / "canary_stocks_50.json"

# Nifty proxy — same basket used by backtest_service.py for consistency.
NIFTY_PROXY = ["RELIANCE", "HDFCBANK", "TCS", "INFY", "ITC"]
NIFTY_LABEL = "Nifty 50 proxy (equal-weighted top 5)"

# How many stocks to hold each year from the YIQ50 universe.
TOP_K = 5


def _load_yiq50_universe() -> list[str]:
    """Read the 50 curated tickers from the canary universe file."""
    if not _CANARY_50.exists():
        logger.warning("canary_stocks_50.json missing at %s", _CANARY_50)
        return []
    try:
        data = json.loads(_CANARY_50.read_text(encoding="utf-8"))
        return [s["symbol"] for s in data.get("stocks", []) if s.get("symbol")]
    except Exception as e:
        logger.exception("failed to read canary universe: %s", e)
        return []


def _parquet_path(ticker: str) -> Path:
    from data_pipeline.nse_prices.db_integration import _parquet_path as _p
    return _p(ticker)


def _price_on(conn, ticker: str, on_date: date, window_days: int = 45) -> Optional[float]:
    """Closest close on or before `on_date` within a small lookback window.

    Returns None if the ticker has no parquet or no in-window row.
    """
    path = _parquet_path(ticker)
    if not path.exists():
        return None
    lo = on_date - timedelta(days=window_days)
    try:
        df = conn.execute(f"""
            SELECT date, close FROM read_parquet('{path.as_posix()}')
            WHERE date <= TIMESTAMP '{on_date.isoformat()}'
              AND date >= TIMESTAMP '{lo.isoformat()}'
            ORDER BY date DESC
            LIMIT 1
        """).fetchone()
    except Exception as e:
        logger.warning("price_on %s @ %s failed: %s", ticker, on_date, e)
        return None
    if not df:
        return None
    try:
        v = float(df[1])
        return v if v > 0 else None
    except Exception:
        return None


def _historical_mos(sess, ticker: str, on_date: date) -> Optional[float]:
    """Most-recent fair_value_history.mos_pct on or before `on_date`.

    Tries both bare and .NS-suffixed ticker forms because the live
    analysis hot path writes `.NS` rows while the monthly backfill
    writes bare rows. Returns None if neither has anything.
    """
    from sqlalchemy import text
    bare = ticker.replace(".NS", "").replace(".BO", "").upper()
    suffixed = f"{bare}.NS"
    try:
        row = sess.execute(
            text(
                """
                SELECT mos_pct FROM fair_value_history
                WHERE ticker IN (:a, :b) AND date <= :d
                ORDER BY date DESC LIMIT 1
                """
            ),
            {"a": bare, "b": suffixed, "d": on_date},
        ).fetchone()
        if row and row[0] is not None:
            return float(row[0])
    except Exception as e:
        logger.warning("historical_mos %s @ %s failed: %s", bare, on_date, e)
    return None


def _basket_return_pct(
    conn, tickers: list[str], start: date, end: date
) -> tuple[Optional[float], int]:
    """Equal-weighted return % across `tickers` from start→end.

    Returns (return_pct, n_used). Tickers that lack price on either
    end are excluded from the average rather than poisoning it.
    """
    rets: list[float] = []
    for t in tickers:
        p0 = _price_on(conn, t, start)
        p1 = _price_on(conn, t, end)
        if p0 is None or p1 is None or p0 <= 0:
            continue
        rets.append((p1 - p0) / p0)
    if not rets:
        return None, 0
    avg = sum(rets) / len(rets)
    return round(avg * 100.0, 2), len(rets)


def _pick_top5_for_year(sess, universe: list[str], at: date) -> tuple[list[str], str]:
    """Pick the top 5 by historical mos_pct as of `at`.

    Returns (picks, method) where method is:
      - "fv_history" if at least 10 universe tickers had a real
        fair_value_history row on or before `at`;
      - "current_score_proxy" if FV history is too thin and we
        had to fall back to a deterministic universe slice (the
        first 5 alphabetical from the canary list, which is the
        large-cap Nifty-50 chunk by construction).
    """
    scored: list[tuple[str, float]] = []
    for t in universe:
        mos = _historical_mos(sess, t, at)
        if mos is not None:
            scored.append((t, mos))
    if len(scored) >= 10:
        scored.sort(key=lambda x: x[1], reverse=True)
        picks = [t for t, _ in scored[:TOP_K]]
        return picks, "fv_history"
    # Fallback: deterministic "next-5" slice — skip the top 5
    # canary positions (which overlap the Nifty-top-5 proxy by
    # construction) and pick positions 5..9. This keeps the
    # fallback honest (no data-driven claim) while ensuring the
    # basket is at least DIFFERENT from the benchmark so the
    # comparison is visually informative rather than a tautology.
    if len(universe) >= TOP_K + 5:
        return universe[5 : 5 + TOP_K], "current_score_proxy"
    return universe[:TOP_K], "current_score_proxy"


def run_yiq50_backtest(lookback_years: int = 3) -> dict:
    """Annual rotation backtest of the YIQ-50 universe vs Nifty proxy.

    Each year-bucket: pick top-5 by historical mos_pct at year-start,
    hold equally weighted for 365 days, settle at year-end. Compound
    the per-year returns to cumulative.
    """
    import duckdb
    universe = _load_yiq50_universe()
    if not universe:
        return {
            "error": "yiq50 universe unavailable",
            "_meta": {"method": "unavailable"},
        }

    # Coverage check (informational, surfaced in payload).
    have = sum(1 for t in universe if _parquet_path(t).exists())
    coverage_pct = round(100.0 * have / max(1, len(universe)), 1)

    today = date.today()
    # Use year-aligned anchor: start `lookback_years` years ago.
    end_anchor = today
    start_anchor = date(today.year - lookback_years, today.month, min(today.day, 28))

    # Lazy DB session — only opened if needed (testable without DB).
    sess = None
    try:
        from data_pipeline.db import Session as _S
        if _S is not None:
            sess = _S()
    except Exception:
        sess = None

    per_year: list[dict] = []
    methods_used: set[str] = set()

    yiq_cum_mult = 1.0
    bench_cum_mult = 1.0

    conn = duckdb.connect()
    try:
        for i in range(lookback_years):
            yr_start = date(start_anchor.year + i, start_anchor.month, start_anchor.day)
            yr_end_candidate = date(yr_start.year + 1, yr_start.month, yr_start.day)
            yr_end = min(yr_end_candidate, end_anchor)
            if yr_end <= yr_start:
                continue

            if sess is not None:
                picks, method = _pick_top5_for_year(sess, universe, yr_start)
            else:
                picks, method = universe[:TOP_K], "current_score_proxy"
            methods_used.add(method)

            yiq_ret, n_yiq = _basket_return_pct(conn, picks, yr_start, yr_end)
            bench_ret, n_bench = _basket_return_pct(conn, NIFTY_PROXY, yr_start, yr_end)

            per_year.append({
                "year_start": yr_start.isoformat(),
                "year_end": yr_end.isoformat(),
                "picks": picks,
                "method": method,
                "yiq50_return_pct": yiq_ret,
                "nifty_return_pct": bench_ret,
                "delta_pct": (
                    round((yiq_ret or 0.0) - (bench_ret or 0.0), 2)
                    if (yiq_ret is not None and bench_ret is not None) else None
                ),
                "tickers_priced": n_yiq,
            })

            if yiq_ret is not None:
                yiq_cum_mult *= (1.0 + yiq_ret / 100.0)
            if bench_ret is not None:
                bench_cum_mult *= (1.0 + bench_ret / 100.0)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass

    yiq_total = round((yiq_cum_mult - 1.0) * 100.0, 2)
    nifty_total = round((bench_cum_mult - 1.0) * 100.0, 2)
    delta = round(yiq_total - nifty_total, 2)

    # Method tag: "fv_history" only if every year had real data.
    # Mixed → "mixed_proxy"; all proxy → "current_score_proxy".
    if methods_used == {"fv_history"}:
        method_tag = "fv_history"
        caveat = (
            "Picks each year sourced from historical fair_value_history "
            "rows; backfilled monthly using a present-day FV projection."
        )
    elif "fv_history" in methods_used:
        method_tag = "mixed_proxy"
        caveat = (
            "Some years used historical FV rows; sparse years fell back "
            "to a deterministic large-cap slice of the YieldIQ-50."
        )
    else:
        method_tag = "current_score_proxy"
        caveat = (
            "fair_value_history is too sparse for a true historical "
            "pick; the basket uses a deterministic large-cap slice of "
            "the YieldIQ-50. Results are illustrative of universe-level "
            "behaviour, not a year-by-year pick simulation."
        )

    return {
        "lookback_years": lookback_years,
        "universe_size": len(universe),
        "universe_coverage_pct": coverage_pct,
        "yiq50_total_return_pct": yiq_total,
        "nifty_total_return_pct": nifty_total,
        "delta_pct": delta,
        "per_year_breakdown": per_year,
        "benchmark": NIFTY_LABEL,
        "_meta": {
            "method": method_tag,
            "caveat": caveat,
            "survivorship_note": (
                "Universe is the CURRENT YieldIQ-50, not the basket as "
                "it existed at year-start. Survivorship bias is present."
            ),
            "disclaimer": (
                "Hypothetical results based on backtesting methodology. "
                "Past returns are not indicative of future results. This "
                "is not investment advice. YieldIQ is not SEBI-registered "
                "as an investment adviser or research analyst."
            ),
        },
    }
