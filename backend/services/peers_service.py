# backend/services/peers_service.py
"""
Peer comparison service.

Composes peer data from three sources in priority order:
  1. In-process cache of ``AnalysisResponse`` objects — used for
     YieldIQ score / grade / fair value / MoS / verdict. If a peer
     has not been analysed recently these fields are ``None``.
  2. ``market_metrics`` DB table — valuation multiples (PE, PB,
     EV/EBITDA, market cap, dividend yield) within the last 30 days.
  3. ``financials`` DB table — latest annual row for ROE, net
     margin, D/E, FCF yield.
  4. yfinance ``_fetch_peer_metrics`` — live fallback for tickers
     missing from both DB tables. Already parallelised (6 threads,
     30-min cache, 15s timeout) — we just wrap it.

Never calls ``AnalysisService.get_full_analysis()`` per peer.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger("yieldiq.peers")

# Metrics where a higher value is "better in sector"
_HIGHER_BETTER = {
    "yieldiq_score", "mos_pct", "roe_pct",
    "net_margin_pct", "fcf_yield_pct", "dividend_yield",
}
# Metrics where a lower value is "better in sector"
_LOWER_BETTER = {
    "pe_ratio", "pb_ratio", "ev_ebitda", "debt_to_equity",
}


def _strip(t: str) -> str:
    return (t or "").replace(".NS", "").replace(".BO", "")


def _r1(v: Any) -> float | None:
    return round(v, 1) if v is not None else None


def _r2(v: Any) -> float | None:
    return round(v, 2) if v is not None else None


def _pct_norm(v: Any) -> float | None:
    """Normalize ratios-or-percentages to percentage form."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f * 100, 1) if abs(f) <= 1 else round(f, 1)


def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


class PeersService:
    """See module docstring."""

    def get_peer_comparison(self, ticker: str, db, cache) -> dict:
        ticker = (ticker or "").upper().strip()

        # Late imports — the peer fetcher pulls numpy/pandas, which
        # we don't want on the import path of the router module.
        from screener.sector_relative import (
            get_peers_for_ticker,
            get_sector_label_for_ticker,
            _fetch_peer_metrics,
        )

        peers = get_peers_for_ticker(ticker)
        sector_label = get_sector_label_for_ticker(ticker)

        if not peers:
            return {
                "ticker": ticker,
                "has_peers": False,
                "sector_label": None,
                "peers_count": 0,
                "best_in_sector": {},
                "peers": [],
                "message": "Peer comparison not available for this stock yet.",
            }

        all_tickers = [ticker] + peers
        db_tickers = [_strip(t) for t in all_tickers]

        # ── Bulk DB reads ──────────────────────────────────────
        from data_pipeline.models import MarketMetrics, Financials
        mm_map: dict[str, Any] = {}
        fin_map: dict[str, Any] = {}

        if db is not None:
            try:
                cutoff = date.today() - timedelta(days=30)
                mm_rows = (
                    db.query(MarketMetrics)
                    .filter(
                        MarketMetrics.ticker.in_(db_tickers),
                        MarketMetrics.trade_date >= cutoff,
                    )
                    .order_by(
                        MarketMetrics.ticker,
                        MarketMetrics.trade_date.desc(),
                    )
                    .all()
                )
                for row in mm_rows:
                    if row.ticker not in mm_map:
                        mm_map[row.ticker] = row
            except Exception as exc:
                logger.warning("market_metrics query failed: %s", exc)

            try:
                fin_rows = (
                    db.query(Financials)
                    .filter(
                        Financials.ticker.in_(db_tickers),
                        Financials.period_type == "annual",
                    )
                    .order_by(
                        Financials.ticker,
                        Financials.period_end.desc(),
                    )
                    .all()
                )
                for row in fin_rows:
                    if row.ticker not in fin_map:
                        fin_map[row.ticker] = row
            except Exception as exc:
                logger.warning("financials query failed: %s", exc)

        # ── Live fallback for tickers missing from DB ──────────
        missing_live = [t for t in all_tickers if _strip(t) not in mm_map]
        live_metrics: dict[str, dict] = {}
        if missing_live:
            try:
                # exclude_ticker must be a str (None would crash .upper())
                results = _fetch_peer_metrics(missing_live, exclude_ticker="")
                for r in results:
                    if r and r.get("ticker"):
                        live_metrics[r["ticker"]] = r
            except Exception as exc:
                logger.warning("live peer fetch failed: %s", exc)

        # ── Build rows ─────────────────────────────────────────
        rows = [
            self._build_row(t, is_main=(t == ticker),
                            mm_map=mm_map, fin_map=fin_map,
                            live=live_metrics, cache=cache)
            for t in all_tickers
        ]

        # ── Best-in-sector highlights ──────────────────────────
        best = self._compute_best(rows)

        return {
            "ticker": ticker,
            "has_peers": True,
            "sector_label": sector_label,
            "peers_count": len(peers),
            "best_in_sector": best,
            "peers": rows,
        }

    # ── Private helpers ────────────────────────────────────────

    def _cached_score(self, t: str, cache) -> dict:
        """Read score data off cached AnalysisResponse, if present."""
        empty = {
            "yieldiq_score": None, "grade": None,
            "fair_value": None, "mos_pct": None,
            "verdict": None, "company_name": None,
        }
        if cache is None:
            return empty
        try:
            obj = cache.get(f"analysis:{t}")
        except Exception:
            return empty
        if obj is None:
            return empty
        try:
            return {
                "yieldiq_score": getattr(obj.quality, "yieldiq_score", None)
                                 if getattr(obj, "quality", None) else None,
                "grade": getattr(obj.quality, "grade", None)
                         if getattr(obj, "quality", None) else None,
                "fair_value": getattr(obj.valuation, "fair_value", None)
                              if getattr(obj, "valuation", None) else None,
                "mos_pct": getattr(obj.valuation, "margin_of_safety", None)
                           if getattr(obj, "valuation", None) else None,
                "verdict": getattr(obj.valuation, "verdict", None)
                           if getattr(obj, "valuation", None) else None,
                "company_name": getattr(obj.company, "company_name", None)
                                if getattr(obj, "company", None) else None,
            }
        except Exception:
            return empty

    def _build_row(
        self, t: str, is_main: bool,
        mm_map: dict, fin_map: dict, live: dict, cache,
    ) -> dict:
        st = _strip(t)
        mm = mm_map.get(st)
        fin = fin_map.get(st)
        lv = live.get(t, {})
        score = self._cached_score(t, cache)

        # Valuation multiples
        pe = _first(mm.pe_ratio if mm else None, lv.get("pe"))
        pb = _first(mm.pb_ratio if mm else None)
        ev_ebitda = _first(mm.ev_ebitda if mm else None, lv.get("ev_ebitda"))
        div_yield = _first(mm.dividend_yield if mm else None)

        # Market cap — DB is in Cr, live is in billions (rupees)
        market_cap_cr: float | None = None
        if mm and mm.market_cap_cr is not None:
            market_cap_cr = float(mm.market_cap_cr)
        elif lv.get("mktcap_b") is not None:
            market_cap_cr = round(float(lv["mktcap_b"]) * 100, 1)

        # Quality fields from financials (percentages in DB already for some;
        # _pct_norm handles the "ratio vs percentage" ambiguity defensively)
        roe = _first(fin.roe if fin else None)
        net_margin = _first(fin.net_margin if fin else None)
        de = _first(fin.debt_to_equity if fin else None)
        if de is None and fin is not None and fin.total_debt is not None and fin.total_equity:
            try:
                de = round(fin.total_debt / fin.total_equity, 2)
            except Exception:
                de = None

        # FCF yield = FCF / market_cap (both in Cr)
        fcf_yield_pct = None
        if fin and fin.free_cash_flow and market_cap_cr and market_cap_cr > 0:
            try:
                fcf_yield_pct = round(
                    fin.free_cash_flow / market_cap_cr * 100, 1
                )
            except Exception:
                fcf_yield_pct = None

        company_name = (
            score.get("company_name")
            or lv.get("name")
            or st
        )

        return {
            "ticker": t,
            "is_main": is_main,
            "company_name": company_name,

            # YieldIQ (cache only)
            "yieldiq_score": score.get("yieldiq_score"),
            "grade": score.get("grade"),
            "fair_value": _r2(score.get("fair_value")),
            "mos_pct": _r1(score.get("mos_pct")),
            "verdict": score.get("verdict"),

            # Valuation multiples
            "pe_ratio": _r1(pe),
            "pb_ratio": _r1(pb),
            "ev_ebitda": _r1(ev_ebitda),
            "market_cap_cr": _r1(market_cap_cr),
            "dividend_yield": _r1(div_yield),

            # Quality
            "roe_pct": _pct_norm(roe),
            "net_margin_pct": _pct_norm(net_margin),
            "debt_to_equity": _r1(de),
            "fcf_yield_pct": fcf_yield_pct,
        }

    def _compute_best(self, rows: list[dict]) -> dict[str, str]:
        """For each comparable metric, find the best ticker."""
        best: dict[str, str] = {}
        if len(rows) < 2:
            return best
        all_metrics = _HIGHER_BETTER | _LOWER_BETTER
        for metric in all_metrics:
            values = [
                (r["ticker"], r.get(metric))
                for r in rows
                if r.get(metric) is not None
            ]
            if len(values) < 2:
                continue
            if metric in _HIGHER_BETTER:
                winner = max(values, key=lambda x: x[1])
            else:
                # For LOWER_BETTER ignore non-positive values
                positive = [v for v in values if v[1] > 0]
                if len(positive) < 2:
                    continue
                winner = min(positive, key=lambda x: x[1])
            best[metric] = winner[0]
        return best
