# backend/services/strategy_service.py
# ═══════════════════════════════════════════════════════════════
# Strategy resolver — turns a strategy_def (rich JSON from the
# Strategy Builder UI) into a list of tickers, then delegates to
# the existing backtest_service.backtest_tickers engine.
#
# This is intentionally additive: it does NOT change DCF math,
# valuation, or analysis-response shape. It only:
#   1. Reads from analysis_cache + market_metrics (existing tables)
#   2. Filters per the rule set in strategy_def["entry_rules"]
#   3. Calls backtest_tickers() unchanged
#
# Survivorship bias note: like the existing /backtest/screen/{slug}
# endpoint, this backtests the CURRENT constituents that pass the
# filter today. It is not a true rolling backtest. The UI surfaces
# this disclaimer prominently.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import secrets
import string
from typing import Any, Optional

logger = logging.getLogger("yieldiq.strategy")


# ── Strategy_def schema (validated lightly here, strictly in router) ──
# {
#   "name": "My buffett",
#   "universe": {"kind": "all" | "nifty50" | "nifty500" | "watchlist" | "sector",
#                "sector": "IT", "tickers": [...]},
#   "entry_rules": {
#       "logic": "AND" | "OR",
#       "rules": [
#           {"metric": "yieldiq_score", "op": ">=", "value": 70},
#           {"metric": "moat", "op": "in", "value": ["Wide", "Moderate"]},
#           ...
#       ]
#   },
#   "rebalance": {"freq": "monthly"|"quarterly"|"yearly",
#                 "sizing": "equal"|"score"|"top_n", "top_n": 10,
#                 "max_position_pct": 25.0},
#   "test_period": {"start": "2021-04-01", "end": "2026-04-01",
#                   "benchmark": "nifty50"|"nifty500"|"sensex"|"custom"}
# }


# ── Metric extractors ────────────────────────────────────────────────
# Map UI metric keys to extractors that pull a numeric/categorical
# value from the row dict yielded by _load_universe(). Extractors
# return None if the metric is unavailable for that ticker — the
# downstream comparator treats None as "rule fails" (skip ticker).
def _extract(metric: str, row: dict[str, Any]) -> Any:
    if metric == "yieldiq_score":
        return row.get("score")
    if metric == "piotroski":
        return row.get("piotroski")
    if metric == "moat":
        return row.get("moat") or "None"
    if metric == "mos":
        return row.get("mos")
    if metric == "pe":
        eps = row.get("eps_ttm")
        cp = row.get("current_price") or row.get("close_price")
        if eps and cp and eps > 0:
            return cp / eps
        return row.get("pe_ratio")
    if metric == "pb":
        return row.get("pb_ratio")
    if metric == "roe":
        return row.get("roe")
    if metric == "roce":
        return row.get("roce")
    if metric == "debt_equity":
        return row.get("debt_equity")
    if metric == "revenue_cagr_3y":
        return row.get("revenue_cagr_3y")
    if metric == "revenue_cagr_5y":
        return row.get("revenue_cagr_5y")
    if metric == "div_yield":
        return row.get("dividend_yield")
    if metric == "sector":
        return row.get("sector") or ""
    if metric == "market_cap_tier":
        mcap = row.get("market_cap_cr") or 0
        if mcap >= 50000:
            return "Large"
        if mcap >= 10000:
            return "Mid"
        return "Small"
    if metric == "sector_percentile_band":
        return row.get("sector_percentile_band") or ""
    return None


def _compare(actual: Any, op: str, expected: Any) -> bool:
    """Comparator. Returns False on type mismatch / None — never raises."""
    if actual is None:
        return False
    try:
        if op == ">=":
            return float(actual) >= float(expected)
        if op == "<=":
            return float(actual) <= float(expected)
        if op == ">":
            return float(actual) > float(expected)
        if op == "<":
            return float(actual) < float(expected)
        if op == "==":
            return str(actual) == str(expected)
        if op == "!=":
            return str(actual) != str(expected)
        if op == "in":
            if isinstance(expected, list):
                return str(actual) in [str(e) for e in expected]
            return False
        if op == "not_in":
            if isinstance(expected, list):
                return str(actual) not in [str(e) for e in expected]
            return True
    except (TypeError, ValueError):
        return False
    return False


def _evaluate_rules(row: dict[str, Any], rules_cfg: dict[str, Any]) -> bool:
    rules = rules_cfg.get("rules") or []
    if not rules:
        return True  # no rules = match-all (still gated by universe)
    logic = (rules_cfg.get("logic") or "AND").upper()
    results = [
        _compare(_extract(r.get("metric", ""), row), r.get("op", ">="), r.get("value"))
        for r in rules
    ]
    if logic == "OR":
        return any(results)
    return all(results)


# ── Universe loader ──────────────────────────────────────────────────
def _load_universe(universe_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Pull ONE row per ticker from analysis_cache (rich YieldIQ fields)
    LEFT JOIN'd with market_metrics (raw price/PE/PB/mcap). Returns a
    list of dicts keyed by metric name — ready for _evaluate_rules().

    Universe kinds:
      - all       : every active ticker with cached analysis
      - nifty50   : Nifty 50 constituents (via nse_sector_constituents)
      - nifty500  : Nifty 500 constituents
      - watchlist : explicit ticker list
      - sector    : single sector slug
    """
    kind = (universe_cfg or {}).get("kind", "all")
    explicit = [t.upper() for t in (universe_cfg or {}).get("tickers", []) if t]
    sector = (universe_cfg or {}).get("sector")

    rows: list[dict[str, Any]] = []
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text
        if Session is None:
            return []
        sess = Session()
        try:
            # Pull the union of analysis_cache (rich fields) and market_metrics
            # (PE/PB/market_cap). LEFT JOIN so a ticker missing from one side
            # still surfaces with whatever fields it has.
            sql = text(
                """
                WITH mm_dedup AS (
                    SELECT DISTINCT ON (ticker)
                        ticker, pe_ratio, pb_ratio, market_cap_cr,
                        dividend_yield, close_price
                    FROM market_metrics
                    ORDER BY ticker, trade_date DESC
                ),
                ac AS (
                    SELECT DISTINCT ON (ticker)
                        ticker,
                        (payload->'quality'->>'yieldiq_score')::float    AS score,
                        (payload->'quality'->>'piotroski_f_score')::float AS piotroski,
                        (payload->'quality'->>'moat')                    AS moat,
                        (payload->'valuation'->>'margin_of_safety')::float AS mos,
                        (payload->'valuation'->>'eps_ttm')::float        AS eps_ttm,
                        (payload->'valuation'->>'current_price')::float  AS current_price,
                        (payload->'fundamentals'->>'roe')::float         AS roe,
                        (payload->'fundamentals'->>'roce')::float        AS roce,
                        (payload->'fundamentals'->>'debt_to_equity')::float AS debt_equity,
                        (payload->'fundamentals'->>'revenue_cagr_3y')::float AS revenue_cagr_3y,
                        (payload->'fundamentals'->>'revenue_cagr_5y')::float AS revenue_cagr_5y,
                        (payload->'sector_percentile'->>'band')          AS sector_percentile_band
                    FROM analysis_cache
                    WHERE computed_at > now() - interval '7 days'
                    ORDER BY ticker, computed_at DESC
                )
                SELECT
                    s.ticker,
                    s.company_name,
                    s.sector,
                    ac.score, ac.piotroski, ac.moat, ac.mos,
                    ac.eps_ttm, ac.current_price, ac.roe, ac.roce,
                    ac.debt_equity, ac.revenue_cagr_3y, ac.revenue_cagr_5y,
                    ac.sector_percentile_band,
                    mm.pe_ratio, mm.pb_ratio, mm.market_cap_cr,
                    mm.dividend_yield, mm.close_price
                FROM stocks s
                LEFT JOIN ac ON ac.ticker = s.ticker
                LEFT JOIN mm_dedup mm ON mm.ticker = s.ticker
                WHERE s.is_active = true
                """
            )
            for r in sess.execute(sql).fetchall():
                rows.append({
                    "ticker": r[0],
                    "company_name": r[1],
                    "sector": r[2],
                    "score": r[3], "piotroski": r[4], "moat": r[5], "mos": r[6],
                    "eps_ttm": r[7], "current_price": r[8],
                    "roe": r[9], "roce": r[10], "debt_equity": r[11],
                    "revenue_cagr_3y": r[12], "revenue_cagr_5y": r[13],
                    "sector_percentile_band": r[14],
                    "pe_ratio": r[15], "pb_ratio": r[16], "market_cap_cr": r[17],
                    "dividend_yield": r[18], "close_price": r[19],
                })
        finally:
            sess.close()
    except Exception as e:
        logger.warning("strategy: universe load failed (%s); returning empty", e)
        return []

    # Restrict to nifty50/nifty500/sector if asked.
    if kind in ("nifty50", "nifty500"):
        index_name = "NIFTY 50" if kind == "nifty50" else "NIFTY 500"
        try:
            from data_pipeline.db import Session
            from sqlalchemy import text
            sess = Session()
            try:
                idx_rows = sess.execute(
                    text("SELECT ticker FROM nse_sector_constituents WHERE nifty_index = :idx"),
                    {"idx": index_name},
                ).fetchall()
                allowed = {row[0].upper() for row in idx_rows}
                rows = [r for r in rows if (r["ticker"] or "").upper() in allowed]
            finally:
                sess.close()
        except Exception as e:
            logger.info("strategy: index filter skipped (%s)", e)
    elif kind == "watchlist" and explicit:
        allowed = set(explicit)
        rows = [
            r for r in rows
            if (r["ticker"] or "").upper() in allowed
            or f"{(r['ticker'] or '').upper()}.NS" in allowed
        ]
    elif kind == "sector" and sector:
        rows = [r for r in rows if (r.get("sector") or "").lower() == sector.lower()]

    return rows


# ── Top-level: resolve strategy_def → ticker list ─────────────────────
def resolve_strategy_tickers(strategy_def: dict[str, Any]) -> tuple[list[str], list[dict]]:
    """
    Returns (tickers_for_backtest, holdings_metadata).

    holdings_metadata = list of {ticker, score, mos, weight} for the UI
    holdings panel.
    """
    universe_cfg = strategy_def.get("universe") or {"kind": "all"}
    rules_cfg = strategy_def.get("entry_rules") or {"logic": "AND", "rules": []}
    rebalance_cfg = strategy_def.get("rebalance") or {}

    rows = _load_universe(universe_cfg)
    matched = [r for r in rows if _evaluate_rules(r, rules_cfg)]

    # Sizing
    sizing = rebalance_cfg.get("sizing", "equal")
    top_n = int(rebalance_cfg.get("top_n", 0) or 0)
    max_pos = float(rebalance_cfg.get("max_position_pct", 100) or 100)

    # Sort by score desc as the natural ranking, then take top_n if requested
    matched.sort(key=lambda r: (r.get("score") or 0), reverse=True)
    if sizing == "top_n" and top_n > 0:
        matched = matched[:top_n]
    elif top_n > 0 and len(matched) > top_n:
        # cap at top_n even for non-top_n sizings to avoid 200-stock portfolios
        matched = matched[:top_n]

    if not matched:
        return [], []

    # Compute weights
    n = len(matched)
    weights: list[float]
    if sizing == "score":
        scores = [max(0.0, float(r.get("score") or 0)) for r in matched]
        total = sum(scores) or 1.0
        weights = [s / total for s in scores]
    else:
        weights = [1.0 / n] * n

    # Apply max_position_pct cap (renormalize)
    cap = max(0.01, max_pos / 100.0)
    weights = [min(w, cap) for w in weights]
    wsum = sum(weights) or 1.0
    weights = [w / wsum for w in weights]

    holdings = []
    tickers = []
    for r, w in zip(matched, weights):
        tk = r["ticker"] or ""
        if not tk:
            continue
        full = tk if "." in tk else f"{tk}.NS"
        tickers.append(full)
        holdings.append({
            "ticker": full,
            "company_name": r.get("company_name"),
            "sector": r.get("sector"),
            "score": r.get("score"),
            "mos": r.get("mos"),
            "weight_pct": round(w * 100, 2),
        })
    return tickers, holdings


def run_strategy_backtest(strategy_def: dict[str, Any]) -> dict[str, Any]:
    """
    Resolve strategy_def → tickers → run backtest_tickers() → enrich.
    Never raises — returns {"error": ...} on failure.
    """
    try:
        tickers, holdings = resolve_strategy_tickers(strategy_def)
    except Exception as e:
        logger.exception("strategy resolution failed: %s", e)
        return {"error": f"Strategy resolution failed: {type(e).__name__}"}

    if not tickers:
        return {
            "error": "No stocks match this strategy. Try relaxing your entry rules.",
            "holdings": [],
            "tickers_matched": 0,
        }

    rebalance_cfg = strategy_def.get("rebalance") or {}
    freq = (rebalance_cfg.get("freq") or "quarterly").lower()
    rebalance_days = {"monthly": 21, "quarterly": 63, "yearly": 252}.get(freq, 63)

    test_period = strategy_def.get("test_period") or {}
    # Translate start/end to "years" for backtest_tickers (which slices by
    # CURRENT_TIMESTAMP - INTERVAL N days). Best-effort: if explicit dates
    # are given, derive years; otherwise default to 5.
    years = 5
    try:
        if test_period.get("start"):
            from datetime import date
            start = date.fromisoformat(test_period["start"])
            end_str = test_period.get("end")
            end = date.fromisoformat(end_str) if end_str else date.today()
            years = max(1, min(10, int(round((end - start).days / 365.0))))
    except Exception:
        years = 5

    try:
        from backend.services.backtest_service import backtest_tickers
        result = backtest_tickers(
            tickers=tickers,
            years=years,
            rebalance_days=rebalance_days,
            include_benchmark=True,
        )
    except Exception as e:
        logger.exception("backtest_tickers failed: %s", e)
        return {"error": f"Backtest computation failed: {type(e).__name__}"}

    if result.get("error"):
        result["holdings"] = holdings
        return result

    # Add holdings + monthly returns heatmap derived from curve
    result["holdings"] = holdings
    result["tickers_matched"] = len(tickers)
    result["strategy_def"] = strategy_def
    result["monthly_returns"] = _curve_to_monthly_returns(result.get("curve") or [])
    return result


def _curve_to_monthly_returns(curve: list[dict]) -> list[dict]:
    """
    Convert a downsampled equity curve into per-month return rows for the
    heatmap. Each row: {year, month, return_pct}. Best-effort — if the
    curve has gaps the missing months simply don't appear.
    """
    if not curve or len(curve) < 2:
        return []
    by_month: dict[str, tuple[float, float]] = {}  # key -> (first_val, last_val)
    for pt in curve:
        date_str = pt.get("date")
        val = pt.get("portfolio")
        if not date_str or val is None:
            continue
        # date_str is YYYY-MM-DD
        key = date_str[:7]
        if key not in by_month:
            by_month[key] = (val, val)
        else:
            first, _ = by_month[key]
            by_month[key] = (first, val)
    rows = []
    keys = sorted(by_month.keys())
    prev_end: Optional[float] = None
    for k in keys:
        first, last = by_month[k]
        # If we have a previous month's end, use it as the start basis
        # (smoother than using within-month first which drops the gap return).
        basis = prev_end if prev_end is not None else first
        if basis and basis > 0:
            ret = (last / basis - 1) * 100
        else:
            ret = 0.0
        year, month = k.split("-")
        rows.append({"year": int(year), "month": int(month), "return_pct": round(ret, 2)})
        prev_end = last
    return rows


# ── Public-share slug generator ───────────────────────────────────────
def generate_public_slug(length: int = 10) -> str:
    """URL-safe slug for /strategies/public/{slug}."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
