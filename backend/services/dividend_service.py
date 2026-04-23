# backend/services/dividend_service.py
"""
Dividend data service.

Live-fetches dividend history and info fields from yfinance
on demand. No DB persistence — we rely on the 30-minute cache
in front of every endpoint that consumes this.

Public entry point: ``DividendService.get_dividends(ticker, enriched=None)``.
When ``enriched`` is supplied (called from inside AnalysisService),
we compute an FCF (or PAT, for banks) coverage ratio. Called from
the router, ``enriched`` is ``None`` and coverage is omitted.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

log = logging.getLogger("yieldiq.dividends")


class DividendService:
    """See module docstring."""

    def get_dividends(
        self,
        ticker: str,
        enriched: dict | None = None,
        yf_info: dict | None = None,
    ) -> dict:
        """Never raises — returns an empty response on any failure.

        ``yf_info``: if the caller already fetched yfinance ``.info``
        (e.g. the collector in analysis_service), pass it here to avoid
        a duplicate 15-30s yfinance call.
        """
        try:
            return self._fetch(ticker, enriched, yf_info)
        except Exception as exc:
            log.debug("DividendService failed for %s: %s", ticker, exc)
            return self._empty(ticker)

    # ── Core fetch ─────────────────────────────────────────────

    def _fetch(self, ticker: str, enriched: dict | None, yf_info: dict | None = None) -> dict:
        import yfinance as yf

        # ── DB-first: the `corporate_actions` table (populated from
        # the NSE feed) is the canonical source for Indian dividends.
        # Same data that powers GET /api/v1/public/dividends/{ticker}.
        # yfinance's .info drops dividend fields on ~30% of Indian
        # tickers (TCS, HCLTECH, etc observed — confirmed 2026-04-23
        # when TCS's InsightCards.dividend was rendering "None" despite
        # 20 NSE-recorded dividend payments in the last 5 years).
        # Strategy:
        #   1. Hit corporate_actions for the dividend series.
        #   2. If present, compute yield/payout from series + current
        #      price/shares (which we have in enriched/yf_info).
        #   3. Only fall back to yfinance .info when the DB is empty.
        db_series = self._fetch_from_db(ticker)
        if db_series:
            return self._build_from_series(
                ticker, db_series, enriched, yf_info
            )

        # ── yfinance path (fallback for tickers missing from NSE feed
        # or for non-Indian symbols).
        info = None
        if yf_info and (
            yf_info.get("lastDividendValue") is not None
            or yf_info.get("dividendYield") is not None
            or yf_info.get("dividendRate") is not None
        ):
            info = yf_info
        if info is None:
            t = yf.Ticker(ticker)
            try:
                info = t.info or {}
            except Exception:
                return self._empty(ticker)

        last_div = info.get("lastDividendValue")
        div_yield_raw = info.get("dividendYield")

        # ── Series fallback: if .info stripped the fields but the
        # yfinance .dividends series has rows, rebuild from that. This
        # is the gap the old code missed — it returned has_dividends=False
        # even when the underlying payment series was populated.
        if not last_div or div_yield_raw is None:
            try:
                t_fallback = yf.Ticker(ticker)
                hist_fallback = t_fallback.dividends
                if hist_fallback is not None and len(hist_fallback) > 0:
                    return self._build_from_yf_series(
                        ticker, hist_fallback, enriched, info
                    )
            except Exception as _e:
                log.debug("yfinance series fallback failed for %s: %s", ticker, _e)
            return {
                "has_dividends": False,
                "ticker": ticker,
                "message": "No dividends paid in last 5 years.",
            }

        # Defensive: yfinance flipped dividendYield from ratio (0.032)
        # to percentage (3.2) around 2024. Also guard against a legacy
        # ×100 bug in some ingest paths (would produce 320).
        div_yield = float(div_yield_raw)
        if abs(div_yield) > 50:
            div_yield = div_yield / 100

        payout_ratio_raw = float(info.get("payoutRatio") or 0)
        payout_pct = round(payout_ratio_raw * 100, 1)

        five_yr_avg = info.get("fiveYearAvgDividendYield")
        try:
            five_yr_avg_out = round(float(five_yr_avg), 2) if five_yr_avg else None
        except (TypeError, ValueError):
            five_yr_avg_out = None

        div_rate = float(info.get("dividendRate") or 0)

        # ── History → FY buckets
        try:
            hist = t.dividends
        except Exception:
            hist = None

        fy_history: list[dict] = []
        consecutive_years = 0
        if hist is not None and len(hist) > 0:
            fy_history = self._build_fy_history(hist)
            consecutive_years = self._count_consecutive(fy_history)

        # ── Next ex-date
        next_ex_date: str | None = None
        next_ex_days: int | None = None
        ex_ts = info.get("exDividendDate")
        if ex_ts:
            try:
                ex_d = datetime.fromtimestamp(int(ex_ts), tz=timezone.utc).date()
                today = date.today()
                if ex_d >= today:
                    next_ex_date = ex_d.isoformat()
                    next_ex_days = (ex_d - today).days
            except Exception:
                pass

        # ── Coverage + sustainability
        is_fin = self._is_financial(ticker, info)
        coverage = self._compute_coverage(enriched, info, is_fin, div_rate)
        sust_label, sust_reason = self._sustainability(
            payout_pct, coverage, consecutive_years
        )

        return {
            "has_dividends": True,
            "ticker": ticker,
            "message": "",
            "current_yield_pct": round(div_yield, 2),
            "payout_ratio_pct": payout_pct,
            "five_yr_avg_yield": five_yr_avg_out,
            "dividend_rate_per_share": round(div_rate, 2),
            "last_dividend_value": round(float(last_div), 2),
            "next_ex_date": next_ex_date,
            "next_ex_days": next_ex_days,
            "consecutive_years": consecutive_years,
            "fy_history": fy_history,
            "coverage_ratio": coverage,
            "sustainability": sust_label,
            "sustainability_reason": sust_reason,
        }

    # ── DB-first fetch ─────────────────────────────────────────

    def _fetch_from_db(self, ticker: str) -> list[dict] | None:
        """Return list of `{ex_date: date, amount: float}` sorted oldest→newest.

        Same corporate_actions query as the public /dividends/{ticker}
        endpoint. Returns None on any failure (DB unavailable, import
        failure, unparseable rows) so the caller falls through to
        yfinance. Returns [] if the table has zero rows for this ticker
        (genuinely no dividends).
        """
        from datetime import date, timedelta
        clean = ticker.replace(".NS", "").replace(".BO", "")
        try:
            from backend.database import SessionLocal
            from data_pipeline.models import CorporateAction
        except Exception as exc:
            log.debug("DB import failed for %s: %s", ticker, exc)
            return None

        db = None
        try:
            db = SessionLocal()
            cutoff = date.today() - timedelta(days=10 * 366)  # 10-year window
            rows = (
                db.query(CorporateAction)
                .filter(CorporateAction.ticker == clean)
                .filter(CorporateAction.ex_date.isnot(None))
                .filter(CorporateAction.ex_date >= cutoff)
                .order_by(CorporateAction.ex_date.asc())
                .all()
            )
            out: list[dict] = []
            for r in rows:
                blob = " ".join(
                    filter(None, [(r.action_type or ""), (r.remarks or "")])
                ).upper()
                if "DIVIDEND" not in blob:
                    continue
                amount = self._parse_dividend_amount(blob)
                if amount is None or amount <= 0:
                    continue
                out.append({"ex_date": r.ex_date, "amount": float(amount)})
            return out
        except Exception as exc:
            log.debug("corporate_actions query failed for %s: %s", ticker, exc)
            return None
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

    def _parse_dividend_amount(self, blob: str) -> float | None:
        """Extract rupee amount from a corporate-actions remarks blob.

        Common formats: "DIVIDEND RS 10", "INT DIV 7/-", "DIVIDEND - 25.00 PER SHARE".
        """
        import re
        # Match a decimal number anywhere in the blob
        m = re.search(r"(\d+(?:\.\d+)?)", blob)
        if not m:
            return None
        try:
            v = float(m.group(1))
            # Sanity band: anything > 5000 is almost certainly not a
            # per-share dividend amount (face value or lot size noise).
            return v if 0 < v < 5000 else None
        except ValueError:
            return None

    def _build_from_series(
        self,
        ticker: str,
        series: list[dict],
        enriched: dict | None,
        yf_info: dict | None,
    ) -> dict:
        """Build the full DividendData response from a DB-sourced series.

        Computes yield / payout / coverage from the payment series + the
        current price (from yf_info or enriched). This is the TCS fix —
        yfinance.info can have blank dividend fields but the NSE series
        still lets us show accurate, current numbers.
        """
        from datetime import date as _date, timedelta as _td
        if not series:
            return self._empty(ticker)

        today = _date.today()
        ttm_cutoff = today - _td(days=365)
        last_12m = [x for x in series if x["ex_date"] >= ttm_cutoff]
        ttm_total = sum(x["amount"] for x in last_12m) if last_12m else 0.0
        last_payment = max(series, key=lambda x: x["ex_date"])
        last_div = last_payment["amount"]

        price = None
        if yf_info:
            price = yf_info.get("currentPrice") or yf_info.get("regularMarketPrice")
        if not price and enriched:
            price = enriched.get("current_price") or enriched.get("price")
        try:
            price = float(price) if price else None
        except (TypeError, ValueError):
            price = None

        div_yield_pct = (ttm_total / price * 100) if (price and ttm_total > 0) else 0.0

        # FY buckets — pandas-free reimplementation of _build_fy_history
        # for the list-of-dicts shape we have from the DB.
        from collections import defaultdict
        fy_sum: dict[int, float] = defaultdict(float)
        fy_count: dict[int, int] = defaultdict(int)
        for item in series:
            d = item["ex_date"]
            fy = d.year + 1 if d.month >= 4 else d.year
            fy_sum[fy] += item["amount"]
            fy_count[fy] += 1
        recent_fys = sorted(fy_sum.keys(), reverse=True)[:5]
        fy_history = [
            {
                "fy": f"FY{fy}",
                "total_per_share": round(fy_sum[fy], 2),
                "payment_count": fy_count[fy],
            }
            for fy in sorted(recent_fys)
        ]
        consecutive_years = self._count_consecutive(fy_history)

        payout_raw = float((yf_info or {}).get("payoutRatio") or 0)
        payout_pct = round(payout_raw * 100, 1)
        five_yr_avg = (yf_info or {}).get("fiveYearAvgDividendYield")
        try:
            five_yr_avg_out = round(float(five_yr_avg), 2) if five_yr_avg else None
        except (TypeError, ValueError):
            five_yr_avg_out = None

        # Ex-date: NEXT_EX_DATE on the NSE feed isn't consistently
        # available; use last known + cadence inference would be
        # noisy. Defer to yf_info if present.
        next_ex_date: str | None = None
        next_ex_days: int | None = None
        ex_ts = (yf_info or {}).get("exDividendDate")
        if ex_ts:
            try:
                from datetime import datetime as _dt, timezone as _tz
                ex_d = _dt.fromtimestamp(int(ex_ts), tz=_tz.utc).date()
                if ex_d >= today:
                    next_ex_date = ex_d.isoformat()
                    next_ex_days = (ex_d - today).days
            except Exception:
                pass

        div_rate = ttm_total  # trailing 12-month sum is the live "rate"
        is_fin = self._is_financial(ticker, yf_info or {})
        coverage = self._compute_coverage(enriched, yf_info or {}, is_fin, div_rate)
        sust_label, sust_reason = self._sustainability(
            payout_pct, coverage, consecutive_years
        )

        return {
            "has_dividends": True,
            "ticker": ticker,
            "message": "",
            "current_yield_pct": round(div_yield_pct, 2),
            "payout_ratio_pct": payout_pct,
            "five_yr_avg_yield": five_yr_avg_out,
            "dividend_rate_per_share": round(div_rate, 2),
            "last_dividend_value": round(float(last_div), 2),
            "next_ex_date": next_ex_date,
            "next_ex_days": next_ex_days,
            "consecutive_years": consecutive_years,
            "fy_history": fy_history,
            "coverage_ratio": coverage,
            "sustainability": sust_label,
            "sustainability_reason": sust_reason,
        }

    def _build_from_yf_series(
        self,
        ticker: str,
        hist,
        enriched: dict | None,
        info: dict,
    ) -> dict:
        """Fallback for yfinance .info missing dividend fields but
        .dividends series having data. Converts the pandas series into
        the same list-of-dicts shape and reuses _build_from_series."""
        series = []
        for dt, amount in hist.items():
            try:
                d = dt.date() if hasattr(dt, "date") else dt
                series.append({"ex_date": d, "amount": float(amount)})
            except Exception:
                continue
        series.sort(key=lambda x: x["ex_date"])
        return self._build_from_series(ticker, series, enriched, info)

    # ── Helpers ────────────────────────────────────────────────

    def _build_fy_history(self, hist) -> list[dict]:
        """
        Aggregate payments by Indian fiscal year (Apr–Mar).
        Returns up to the last 5 FYs, oldest first:
            [{fy: "FY2025", total_per_share: 14.35, payment_count: 2}, ...]
        """
        fy_sum: dict[int, float] = defaultdict(float)
        fy_count: dict[int, int] = defaultdict(int)

        for dt, amount in hist.items():
            try:
                d = dt.date() if hasattr(dt, "date") else dt
                fy = d.year + 1 if d.month >= 4 else d.year
                fy_sum[fy] += float(amount)
                fy_count[fy] += 1
            except Exception:
                continue

        # Keep the 5 most recent FYs, return oldest → newest
        recent_fys = sorted(fy_sum.keys(), reverse=True)[:5]
        return [
            {
                "fy": f"FY{fy}",
                "total_per_share": round(fy_sum[fy], 2),
                "payment_count": fy_count[fy],
            }
            for fy in sorted(recent_fys)
        ]

    def _count_consecutive(self, fy_history: list[dict]) -> int:
        """Count consecutive paying years walking back from newest."""
        if not fy_history:
            return 0
        count = 0
        for item in reversed(fy_history):
            if item["total_per_share"] > 0:
                count += 1
            else:
                break
        return count

    def _compute_coverage(
        self,
        enriched: dict | None,
        info: dict,
        is_financial: bool,
        div_rate: float,
    ) -> float | None:
        """FCF (or PAT for banks) ÷ total dividends paid."""
        if not div_rate or not enriched:
            return None
        try:
            shares = float(enriched.get("shares") or 0)
            if shares <= 0:
                return None
            total_divs = div_rate * shares
            if total_divs <= 0:
                return None
            if is_financial:
                pat = float(enriched.get("latest_pat") or 0)
                if pat > 0:
                    return round(pat / total_divs, 2)
            else:
                fcf = float(enriched.get("latest_fcf") or 0)
                if fcf > 0:
                    return round(fcf / total_divs, 2)
        except Exception:
            pass
        return None

    def _sustainability(
        self,
        payout_pct: float,
        coverage: float | None,
        consecutive_years: int,
    ) -> tuple[str, str]:
        """Return (label, reason). Label ∈ {"strong","moderate","at_risk"}."""
        if payout_pct <= 0 and coverage is None:
            return ("moderate", "Limited data to assess dividend sustainability.")

        # At-risk gates
        if payout_pct > 90:
            return (
                "at_risk",
                f"Payout ratio of {payout_pct:.0f}% leaves almost no earnings buffer.",
            )
        if coverage is not None and coverage < 1.0:
            return (
                "at_risk",
                f"Cash flow covers dividend only {coverage:.1f}×. "
                "Risk of cut if earnings fall.",
            )

        # Strong gate (all three required)
        if (
            payout_pct < 50
            and (coverage is None or coverage >= 2.0)
            and consecutive_years >= 5
        ):
            reason = f"Payout ratio {payout_pct:.0f}% is healthy"
            if coverage:
                reason += f" and cash flow covers dividend {coverage:.1f}×"
            reason += "."
            return ("strong", reason)

        # Moderate
        if payout_pct >= 50:
            reason = (
                f"Payout ratio of {payout_pct:.0f}% is elevated but manageable."
            )
        elif coverage is not None and coverage < 2.0:
            reason = (
                f"Cash flow covers dividend {coverage:.1f}× — "
                "adequate but watch for earnings pressure."
            )
        else:
            reason = "Dividend appears sustainable based on available data."
        return ("moderate", reason)

    def _is_financial(self, ticker: str, info: dict) -> bool:
        sector = (info.get("sector") or "").lower()
        industry = (info.get("industry") or "").lower()
        keywords = ("bank", "financ", "insurance", "nbfc", "lending")
        return any(kw in sector or kw in industry for kw in keywords)

    def _empty(self, ticker: str) -> dict:
        return {
            "has_dividends": False,
            "ticker": ticker,
            "message": "Dividend data unavailable.",
        }
