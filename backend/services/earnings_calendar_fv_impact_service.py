# backend/services/earnings_calendar_fv_impact_service.py
# ═══════════════════════════════════════════════════════════════
# Forward earnings calendar + per-5%-beat FV impact preview.
#
# What this is
# ------------
# A PRE-EARNINGS positioning surface. The analysis page already
# ships:
#   - `earnings_calendar_service.get_next_earnings(ticker)` — the
#     date of the next scheduled report (NSE event calendar +
#     yfinance fallback).
#   - `earnings_impact_service.estimate_earnings_impact(...)` — a
#     POST-print heuristic that bridges the latest reported quarter
#     to a clamped FV-delta range.
#
# This module is the FORWARD half of that pair. Given a ticker, it
# combines:
#
#   1. The next-earnings date (re-used wholesale via the calendar
#      service so the four surfaces stay coherent — see the
#      "single chokepoint" docstring in earnings_calendar_service).
#   2. The consensus EPS / revenue estimate. EPS comes from Finnhub's
#      annual EPS consensus (`fetch_analyst_consensus`); we expose
#      the annual figure and a derived per-quarter estimate
#      (annual / 4) for the panel. Revenue consensus is more rarely
#      published on Finnhub for NSE listings — when missing we leave
#      the slot None rather than fabricate a number.
#   3. The ticker's HISTORICAL surprise track record — surprise_pct
#      computed from the last N (default 4) quarterly prints in
#      `company_quarterly_results`, baselined YoY same-month with
#      the engine's `implied_growth` (the same baseline math
#      `earnings_impact_service` uses, so the two surfaces tell the
#      same story).
#   4. The estimated FV impact per 5% revenue beat, using the same
#      `sector_multiplier × dampener` lever from
#      `earnings_impact_service`. We expose it as "absolute % of FV"
#      so the panel can read "+/− Y% per 5% beat" verbatim.
#
# What it is NOT
# --------------
#   - Not a fair-value recompute. The output is a HEURISTIC preview
#     of the post-print FV-delta direction & magnitude, calibrated
#     to the SAME 0.3 dampener and same sector multipliers as the
#     post-print impact panel — so the two read coherently.
#   - Not advice. The panel renders neutral framing ("Next earnings
#     in N days · consensus EPS Rs.X · per-5%-beat FV sensitivity Y%")
#     with no advisory vocabulary. SEBI words are deliberately
#     avoided in every string this module emits.
#   - Not a recommendation timer — we DO NOT say "position before
#     earnings"; we describe the numerical sensitivity and leave
#     the user to act.
#
# Caller contract: the public entry point
# `compute_earnings_calendar_fv_impact(ticker)` returns an
# `UpcomingEarnings` dataclass or None when there is no upcoming
# scheduled earnings within the lookahead window. The router
# additionally calls `to_dict` to render JSON.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional

logger = logging.getLogger("yieldiq.earnings_calendar_fv_impact")

# ── Tunables ────────────────────────────────────────────────────
# Only render the calendar card when earnings are within this
# horizon. Beyond ~45 days the consensus estimate has limited
# load-bearing meaning AND yfinance's projected earningsTimestamp
# becomes increasingly noisy. The router does NOT clamp on this —
# it is purely a "do we have something to render?" gate that the
# service makes explicit so the frontend doesn't render a panel
# for tickers reporting 6 months out.
_LOOKAHEAD_DAYS = 45

# Sector multipliers + dampener — kept in lockstep with the
# post-print earnings_impact_service so the FORWARD preview lines
# up with the BACKWARD reading on a beat/miss day. If you change
# the dampener there, change it here in the same PR (or this
# module's per-5%-beat number drifts away from the post-print
# panel's range and the two surfaces start telling different
# stories).
_SECTOR_MULTIPLIER: dict[str, float] = {
    "it services": 1.2,
    "auto": 1.2,
    "metal": 1.2,
    "real estate": 1.2,
    "pharma": 1.0,
    "consumer durables": 1.0,
    "energy": 1.0,
    "media": 1.0,
    "fmcg": 0.7,
    "bank": 0.7,
    "private bank": 0.7,
    "psu bank": 0.7,
    "financial services": 0.7,
}
_DAMPENER = 0.3
# Number of past quarters used for the historical surprise track
# record. 4 = one full fiscal year, matches the cadence a reader
# expects when they see "historical avg surprise +X%".
_TRACK_RECORD_QUARTERS = 4
# Clamp on the per-5%-beat sensitivity so an aberrant sector
# multiplier never prints a >5% per-beat figure. The post-print
# panel clamps the displayed range to +/-15%, and a 5% beat at
# multiplier 1.2 × 0.3 = 1.8% which is well inside the band; this
# clamp exists as belt-and-braces, not as a working constraint.
_PER_5PCT_CLAMP = 0.05  # +/- 5% per 5% surprise = ceiling


# ── Dataclass ───────────────────────────────────────────────────

@dataclass
class UpcomingEarnings:
    """Display-ready forward earnings + FV-impact preview payload."""
    ticker: str
    estimated_report_date: str              # ISO yyyy-mm-dd
    days_until: int
    consensus_eps_estimate: Optional[float]            # per-quarter estimate
    consensus_eps_estimate_annual: Optional[float]     # source annual figure
    consensus_revenue_estimate_cr: Optional[float]     # currently None on NSE
    historical_avg_surprise_pct: float                 # signed, e.g. 0.024
    historical_surprise_quarters: int                  # how many quarters fed it
    estimated_fv_impact_per_5pct_beat: float           # signed, |x| <= 0.05
    sector: Optional[str]
    sector_multiplier: float
    implied_growth_used: float
    confirmed: bool                                    # NSE filing vs yf guess
    source: str                                        # event-calendar source
    fiscal_period: Optional[str]
    notes: list[str]
    method: str = "forward_v1"
    is_heuristic: bool = True


# ── Helpers ─────────────────────────────────────────────────────

def _sector_multiplier(sector: Optional[str]) -> float:
    """Resolve the sector multiplier; unknown sector -> 1.0.

    Lower-cases the input. Kept identical to
    earnings_impact_service._sector_multiplier — see this module's
    header for why the two must move in lockstep.
    """
    if not sector:
        return 1.0
    return _SECTOR_MULTIPLIER.get(sector.strip().lower(), 1.0)


def _period_end_month(row: dict) -> Optional[int]:
    pe = row.get("period_end")
    if pe is None:
        return None
    return getattr(pe, "month", None)


def _row_revenue(row: dict) -> Optional[float]:
    v = row.get("revenue_cr")
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _historical_surprise(
    rows: list[dict],
    *,
    implied_growth: float,
    quarters: int = _TRACK_RECORD_QUARTERS,
) -> tuple[float, int]:
    """Mean YoY revenue surprise across the last `quarters` prints.

    For each of the most-recent `quarters` rows, look back to the
    same-calendar-month row roughly one year earlier and compute:

        expected = yoy_revenue * (1 + implied_growth)
        surprise = (actual - expected) / expected

    Mean across the rows for which a YoY baseline exists; returns
    (mean, n_observed). Returns (0.0, 0) if no row had a YoY
    baseline. The YoY baseline matches the lookup convention in
    earnings_impact_service._find_yoy_baseline so the two surfaces
    interpret 'YoY' identically.
    """
    if not rows:
        return 0.0, 0
    sample = rows[: max(1, quarters)]
    surprises: list[float] = []
    for i, row in enumerate(sample):
        actual = _row_revenue(row)
        if actual is None:
            continue
        month = _period_end_month(row)
        pe = row.get("period_end")
        yr = getattr(pe, "year", None) if pe else None
        if month is None or yr is None:
            continue
        # Look back in the FULL rows list (not just sample) so that a
        # short sample doesn't deprive us of an older YoY baseline.
        yoy_baseline: Optional[float] = None
        for cand in rows[i + 1:]:
            cm = _period_end_month(cand)
            cpe = cand.get("period_end")
            cyr = getattr(cpe, "year", None) if cpe else None
            if cm != month or cyr is None:
                continue
            if cyr >= yr:
                continue
            cand_rev = _row_revenue(cand)
            if cand_rev is None:
                continue
            yoy_baseline = cand_rev
            break
        if yoy_baseline is None:
            continue
        expected = yoy_baseline * (1.0 + implied_growth)
        if expected <= 0:
            continue
        surprises.append((actual - expected) / expected)
    if not surprises:
        return 0.0, 0
    return (sum(surprises) / len(surprises)), len(surprises)


def _per_5pct_beat_sensitivity(sector: Optional[str]) -> float:
    """FV-delta produced by a +5% revenue surprise.

    Identical algebra to earnings_impact_service:
        fv_delta(surprise) = surprise * sector_multiplier * 0.3
    So for surprise = 0.05:
        fv_delta = 0.05 * mult * 0.3 = 0.015 * mult
    Returns a SIGNED magnitude (always positive here — the panel
    renders it as "+/- Y% per 5% beat"). Clamped to +/-_PER_5PCT_CLAMP.
    """
    mult = _sector_multiplier(sector)
    raw = 0.05 * mult * _DAMPENER
    if raw > _PER_5PCT_CLAMP:
        return _PER_5PCT_CLAMP
    if raw < -_PER_5PCT_CLAMP:
        return -_PER_5PCT_CLAMP
    return raw


# ── Public API ──────────────────────────────────────────────────

def compute_earnings_calendar_fv_impact(
    ticker: str,
) -> Optional[UpcomingEarnings]:
    """Build the forward earnings + per-5%-beat preview for `ticker`.

    Returns None when:
      - there is no scheduled earnings event within _LOOKAHEAD_DAYS, or
      - the calendar lookup raises (graceful degradation — the
        analysis page must never break because the calendar surface
        is missing).

    The function makes a DB lookup via the earnings calendar service,
    a Finnhub fetch for the consensus EPS, and a quarterly-results
    lookup for the historical surprise track record. Each is wrapped
    so a transient failure on any one downgrades the slot but does
    not collapse the whole payload — the panel renders with the
    slots it does have.
    """
    raw = (ticker or "").strip()
    if not raw:
        return None

    notes: list[str] = []

    # ── 1. Next scheduled earnings (NSE first, yfinance fallback) ──
    ev = _safe_get_next_earnings(raw)
    if ev is None:
        return None
    try:
        ev_date = date.fromisoformat(ev.date)
    except Exception:
        logger.debug("forward_earnings: bad event date %r for %s", ev.date, raw)
        return None
    days_until = ev.days_until
    if days_until < 0:
        # The calendar service should not return past events, but be
        # defensive: treat as no upcoming event.
        return None
    if days_until > _LOOKAHEAD_DAYS:
        # Don't render the panel for a 6-months-out filing — the
        # consensus estimate is too stale to be useful and the
        # yfinance fallback gets noisier the further out it projects.
        return None

    # ── 2. Sector + implied growth from cached analysis ──
    sector, implied_growth = _safe_resolve_sector_and_growth(raw)
    growth = implied_growth if implied_growth is not None else 0.10
    if implied_growth is None:
        notes.append("implied_growth_missing_fallback_10pct")
    # Defensive clamp identical to earnings_impact_service.
    if growth < -0.5:
        growth = -0.5
        notes.append("implied_growth_clamped_low")
    elif growth > 1.0:
        growth = 1.0
        notes.append("implied_growth_clamped_high")

    # ── 3. Consensus EPS from Finnhub (annual; derive per-quarter) ──
    eps_annual, eps_quarterly = _safe_consensus_eps(raw)
    if eps_annual is None:
        notes.append("consensus_eps_missing")
    # Revenue consensus is not consistently published for NSE
    # tickers by Finnhub; we expose the slot so the API contract is
    # stable but leave it None when we don't have a number rather
    # than back-fill from a YieldIQ projection (that would be a
    # different signal entirely).
    consensus_revenue_cr: Optional[float] = None
    notes.append("consensus_revenue_unavailable")

    # ── 4. Historical surprise track record ──
    rows = _safe_quarterly_rows(raw, n_quarters=_TRACK_RECORD_QUARTERS + 4)
    hist_surprise, hist_n = _historical_surprise(
        rows, implied_growth=growth, quarters=_TRACK_RECORD_QUARTERS,
    )
    if hist_n == 0:
        notes.append("no_historical_surprise_baseline")

    # ── 5. Per-5%-beat FV sensitivity ──
    per5 = _per_5pct_beat_sensitivity(sector)
    mult = _sector_multiplier(sector)

    return UpcomingEarnings(
        ticker=_strip_suffix(raw),
        estimated_report_date=ev_date.isoformat(),
        days_until=days_until,
        consensus_eps_estimate=eps_quarterly,
        consensus_eps_estimate_annual=eps_annual,
        consensus_revenue_estimate_cr=consensus_revenue_cr,
        historical_avg_surprise_pct=hist_surprise,
        historical_surprise_quarters=hist_n,
        estimated_fv_impact_per_5pct_beat=per5,
        sector=sector,
        sector_multiplier=mult,
        implied_growth_used=growth,
        confirmed=bool(ev.confirmed),
        source=ev.source,
        fiscal_period=ev.fiscal_period,
        notes=notes,
    )


def to_dict(impact: Optional[UpcomingEarnings]) -> Optional[dict]:
    """Dict-shaped wrapper for routers / JSON encoders."""
    if impact is None:
        return None
    return asdict(impact)


# ──────────────────────────────────────────────────────────────────
# Internal — safe wrappers that the public function relies on
# ──────────────────────────────────────────────────────────────────

def _strip_suffix(ticker: str) -> str:
    return ticker.replace(".NS", "").replace(".BO", "").upper()


def _safe_get_next_earnings(ticker: str):
    """Pull the next earnings event without ever raising.

    Re-uses earnings_calendar_service so the four "next earnings"
    surfaces (analysis page card, discover strip, home strip,
    earnings calendar page, and now this forward FV-impact panel)
    all agree on the date. A DB-less test context returns None
    gracefully.
    """
    try:
        from backend.services.earnings_calendar_service import (
            get_next_earnings,
        )
        from backend.services.analysis.db import _get_pipeline_session
    except Exception as exc:
        logger.debug("forward_earnings: import failure: %s", exc)
        return None
    db = None
    try:
        db = _get_pipeline_session()
        if db is None:
            return None
        return get_next_earnings(ticker, db)
    except Exception as exc:
        logger.debug("forward_earnings: calendar lookup failed for %s: %s", ticker, exc)
        return None
    finally:
        try:
            if db is not None:
                db.close()
        except Exception:
            pass


def _safe_resolve_sector_and_growth(
    ticker: str,
) -> tuple[Optional[str], Optional[float]]:
    """Mirror earnings_impact router's resolver — see that module's
    docstring for the cache-hit reasoning. Sector / growth are
    optional inputs; this function is best-effort, returning
    (None, None) when the full-analysis lookup fails (e.g. in test
    contexts that don't wire AnalysisService)."""
    try:
        from backend.services.analysis_service import AnalysisService
    except Exception:
        return None, None
    try:
        svc = AnalysisService()
        analysis = svc.get_full_analysis(ticker)
    except Exception as exc:
        logger.info(
            "forward_earnings: full-analysis lookup failed for %s (%s); "
            "falling back to None sector / None growth",
            ticker, str(exc)[:120],
        )
        return None, None

    sector: Optional[str] = None
    growth: Optional[float] = None
    try:
        sector = getattr(analysis.company, "sector", None) or None
    except Exception:
        sector = None
    try:
        g = getattr(analysis.valuation, "fcf_growth_rate", None)
        if g is not None and g != 0:
            growth = float(g)
    except Exception:
        growth = None
    return sector, growth


def _safe_consensus_eps(
    ticker: str,
) -> tuple[Optional[float], Optional[float]]:
    """Return (annual_eps_consensus, per_quarter_eps_consensus).

    Finnhub publishes ANNUAL EPS consensus for the FY current and
    FY next periods (see finnhub_analyst_service.fetch_analyst_consensus
    → eps_estimate.fy_current). Indian filers report quarterly, so
    for the panel we want a per-quarter estimate; we derive it as
    annual / 4. This is a known approximation — the seasonality of
    quarterly EPS isn't flat — but it gives the reader a number on
    the same cadence as the report they're awaiting. The panel
    surfaces both so a sophisticated reader can see the annual
    consensus too.

    Returns (None, None) when Finnhub is unconfigured / returns no
    coverage. Never raises.
    """
    yf_ticker = ticker if ticker.endswith((".NS", ".BO")) else f"{ticker}.NS"
    try:
        from backend.services.finnhub_analyst_service import (
            fetch_analyst_consensus,
        )
    except Exception:
        return None, None
    try:
        payload = fetch_analyst_consensus(yf_ticker)
    except Exception as exc:
        logger.debug("forward_earnings: finnhub fetch failed for %s: %s", yf_ticker, exc)
        return None, None
    if not payload:
        return None, None
    eps = payload.get("eps_estimate") or {}
    annual = eps.get("fy_current")
    try:
        annual_f = float(annual) if annual is not None else None
    except (TypeError, ValueError):
        annual_f = None
    if annual_f is None:
        return None, None
    return annual_f, annual_f / 4.0


def _safe_quarterly_rows(ticker: str, *, n_quarters: int) -> list[dict]:
    """Pull the last N quarterly P&L rows for the ticker. Returns []
    on any failure — every downstream caller treats empty as "no
    track record" rather than as an error."""
    try:
        from backend.services.quarterly_results_service import (
            get_quarterly_results,
        )
    except Exception:
        return []
    try:
        rows = get_quarterly_results(ticker, n_quarters=n_quarters, consolidated=True)
    except Exception as exc:
        logger.debug(
            "forward_earnings: quarterly fetch failed for %s: %s",
            ticker, str(exc)[:120],
        )
        return []
    return rows or []
