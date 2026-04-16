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

        # Reuse caller-provided .info if available — saves ~20s
        # by avoiding a duplicate yfinance quoteSummary call.
        if yf_info:
            info = yf_info
        else:
            t = yf.Ticker(ticker)
            try:
                info = t.info or {}
            except Exception:
                return self._empty(ticker)

        last_div = info.get("lastDividendValue")
        div_yield_raw = info.get("dividendYield")

        if not last_div or div_yield_raw is None:
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
