# backend/services/analyst_calibration_service.py
"""Analyst Calibration Service — T1.5 Phase A (2026-06-09).

Standalone, read-only service that computes the deviation between
YieldIQ Fair Value (DCF-based, ``valuation.fair_value`` on the
analysis payload) and Wall Street analyst price-target consensus
(``analyst_consensus.price_target.mean`` preferred, with
``wall_street_avg_target`` as a legacy fallback) across a supplied
ticker universe.

Phase A is intentionally narrow:

  - Service module + dataclasses + ``compute_calibration_report``.
  - No wiring into the analysis response.
  - No new HTTP endpoint.
  - No frontend.

Phase B (separate PR) will:

  - Wire the report into ``/api/calibration/wall-st``.
  - Surface per-ticker deviation badges on the analysis page.
  - Update CACHE_VERSION / manifest accordingly.

Why this is descriptive, not prescriptive
-----------------------------------------
Wall Street targets are NOT a ground-truth fair value — they are
sell-side estimates which themselves carry systematic biases (the
well-documented "buy-side optimism" tilt). The calibration report
is therefore framed as a *deviation* report: how far does our DCF
diverge from the analyst herd, in which direction, on which names,
and with what sectoral pattern? Banks and holdcos are NOT excluded
— their FVs are also published, and the calibration report stays
descriptive across the entire coverage universe.

Architectural notes
-------------------
- Uses a ``data_provider`` callable injection pattern so tests can
  pass a mock without instantiating any DB / cache machinery. The
  default provider reads from the persistent analysis cache via
  ``backend.services.analysis_cache_service.get_cached_latest`` — a
  one-week TTL read with no manifest revalidation, which matches the
  "we do not re-compute anything; we just read what's already there"
  contract.
- Never raises. Bad / missing data on a single ticker degrades to a
  skipped entry, not an exception. The summary's ``coverage_tickers``
  count surfaces the size of the usable subset.
- Returns plain dataclasses and a ``to_dict`` helper for JSON-safe
  serialization so the Phase B router can return the report directly
  via FastAPI without an additional Pydantic conversion layer.
"""
from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

logger = logging.getLogger("yieldiq.analyst_calibration")


# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

# A ticker is "aligned" with consensus when the absolute deviation
# is within this fraction. Default 5% per the Phase A brief; the
# threshold is a parameter on compute_calibration_report so the
# Phase B router can tune without an engine change.
DEFAULT_ALIGNED_THRESHOLD = 0.05

# Top-outliers list size — large enough to surface the systematic
# divergences, small enough to fit in a UI table at a glance.
TOP_OUTLIERS_LIMIT = 10

# Bucket name for tickers whose payload has no sector value.
UNKNOWN_SECTOR_BUCKET = "Unknown"

# Default canary universe — 180-name superset used as the calibration
# universe when no ticker list is passed. Path is resolved lazily so
# tests can run without the file present.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_UNIVERSE_PATH = _REPO_ROOT / "scripts" / "canary_universe_180.json"


# ─────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CalibrationDatapoint:
    """Per-ticker calibration row.

    deviation_pct is signed:
      - positive  => YieldIQ FV > Wall St avg (YIQ is "above")
      - negative  => YieldIQ FV < Wall St avg (YIQ is "below")
    abs_deviation_pct is the unsigned magnitude.
    direction is the categorical label keyed off the aligned threshold.
    """
    ticker: str
    yieldiq_fv: float
    wall_st_avg: float
    deviation_pct: float
    abs_deviation_pct: float
    direction: str          # "yieldiq_above" | "yieldiq_below" | "aligned"
    analyst_count: Optional[int]
    sector: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CalibrationSummary:
    """Aggregate calibration report across the supplied universe.

    Fields:
      total_tickers           total entries in the input universe
      coverage_tickers        entries that produced a valid datapoint
                              (both YIQ FV and Wall St avg present + > 0)
      median_abs_deviation_pct  median |dev| across covered tickers
      p90_abs_deviation_pct     90th-percentile |dev| across covered
      mean_signed_deviation_pct mean signed dev; positive => YIQ
                              systematically above the herd
      above_wall_st           count where YIQ FV > Wall St + threshold
      below_wall_st           count where YIQ FV < Wall St - threshold
      aligned                 count within ±threshold
      by_sector               { sector: { median_abs_dev, count,
                              signed_bias } } across covered tickers
      top_outliers            top-10 by abs_deviation_pct (descending)
      generated_at            ISO timestamp at compute time
    """
    total_tickers: int
    coverage_tickers: int
    median_abs_deviation_pct: float
    p90_abs_deviation_pct: float
    mean_signed_deviation_pct: float
    above_wall_st: int
    below_wall_st: int
    aligned: int
    by_sector: dict = field(default_factory=dict)
    top_outliers: list = field(default_factory=list)
    generated_at: str = ""


# ─────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────


def _safe_float(value) -> Optional[float]:
    """Return float(value) or None on any failure (incl. NaN/inf)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # Reject NaN and infinity — these propagate poison through medians
    # and break JSON serialization.
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _extract_yieldiq_fv(payload: dict) -> Optional[float]:
    """Pull DCF fair value from an analysis payload.

    Path: payload["valuation"]["fair_value"]. Defensive against
    missing keys / non-numeric values. Rejects non-positive values
    (a zero FV is the engine's "data_limited" sentinel — not a
    meaningful calibration anchor).
    """
    try:
        valuation = payload.get("valuation") or {}
    except AttributeError:
        return None
    fv = _safe_float(valuation.get("fair_value"))
    if fv is None or fv <= 0:
        return None
    return fv


def _extract_wall_st_avg(payload: dict) -> tuple[Optional[float], Optional[int]]:
    """Pull Wall St avg target + analyst count from a payload.

    Preferred source: analyst_consensus.price_target.mean
    (paired with analyst_consensus.coverage_count for the count).
    Legacy fallback: insight_cards.wall_street_avg_target /
    wall_street_target_count.

    Returns (avg, analyst_count) — either can be None independently.
    """
    avg: Optional[float] = None
    count: Optional[int] = None

    # Preferred: structured Finnhub consensus.
    try:
        consensus = payload.get("analyst_consensus") or {}
        price_target = consensus.get("price_target") or {}
        avg = _safe_float(price_target.get("mean"))
        raw_count = consensus.get("coverage_count")
        if raw_count is not None:
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                count = None
    except AttributeError:
        consensus = {}

    # Fallback to legacy insight_cards field if preferred is missing.
    if avg is None:
        try:
            cards = payload.get("insight_cards") or {}
            avg = _safe_float(cards.get("wall_street_avg_target"))
            if count is None and cards.get("wall_street_target_count") is not None:
                try:
                    count = int(cards.get("wall_street_target_count"))
                except (TypeError, ValueError):
                    count = None
        except AttributeError:
            pass

    if avg is not None and avg <= 0:
        avg = None
    return avg, count


def _extract_sector(payload: dict) -> Optional[str]:
    """Pull company.sector from a payload (defensive)."""
    try:
        company = payload.get("company") or {}
        sector = company.get("sector")
        if sector is None:
            return None
        sector = str(sector).strip()
        return sector or None
    except AttributeError:
        return None


def _direction(deviation_pct: float, aligned_threshold: float) -> str:
    if abs(deviation_pct) <= aligned_threshold:
        return "aligned"
    return "yieldiq_above" if deviation_pct > 0 else "yieldiq_below"


def _percentile(values: list[float], pct: float) -> float:
    """Compute the pct-th percentile (0..1) of values.

    Uses linear interpolation between sorted neighbors — the same
    method ``statistics.quantiles`` uses internally. Returns 0.0 on
    an empty list so downstream JSON stays clean.
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    s = sorted(values)
    if pct <= 0:
        return s[0]
    if pct >= 1:
        return s[-1]
    rank = pct * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] + frac * (s[hi] - s[lo])


def _load_default_universe() -> list[str]:
    """Read the canary_universe_180.json file for default tickers.

    Returns an empty list if the file is missing or malformed — the
    caller's responsibility to surface that as an empty report rather
    than a crash.
    """
    path = _DEFAULT_UNIVERSE_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "analyst_calibration: failed to load default universe (%s): %s",
            path, exc,
        )
        return []
    stocks = data.get("stocks") or []
    tickers: list[str] = []
    for entry in stocks:
        if isinstance(entry, dict):
            sym = entry.get("symbol")
            if isinstance(sym, str) and sym.strip():
                tickers.append(sym.strip())
        elif isinstance(entry, str) and entry.strip():
            tickers.append(entry.strip())
    return tickers


def _default_data_provider(ticker: str) -> Optional[dict]:
    """Fetch a cached analysis payload via the persistent cache.

    Uses ``get_cached_latest`` which is the same read path the
    sector-landing aggregator uses — a 7-day TTL window, no manifest
    revalidation. That matches Phase A's read-only contract: we
    surface what's already in cache, we do not re-compute.

    Returns None if the cache_service import fails (e.g. running
    outside the FastAPI process) or if the cache has no row.
    """
    try:
        from backend.services.analysis_cache_service import get_cached_latest
    except Exception as exc:  # pragma: no cover - import only fails outside app
        logger.debug(
            "analyst_calibration: cache_service unavailable (%s); "
            "skipping ticker=%s", exc, ticker,
        )
        return None
    try:
        return get_cached_latest(ticker)
    except Exception as exc:
        logger.warning(
            "analyst_calibration: get_cached_latest(%s) raised: %s",
            ticker, exc,
        )
        return None


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


def compute_calibration_report(
    tickers: Optional[Iterable[str]] = None,
    aligned_threshold: float = DEFAULT_ALIGNED_THRESHOLD,
    data_provider: Optional[Callable[[str], Optional[dict]]] = None,
) -> CalibrationSummary:
    """Compute the YIQ-vs-Wall-St calibration report.

    Args:
      tickers: iterable of bare or .NS-suffixed tickers. When None,
        defaults to the canary_universe_180 universe.
      aligned_threshold: fraction within which YIQ and Wall St are
        considered "aligned" (default 0.05 == 5%).
      data_provider: callable (ticker) -> payload-dict-or-None. When
        None, uses the persistent analysis cache. Injected by tests.

    Returns:
      CalibrationSummary. Never raises — bad / missing inputs degrade
      to skipped tickers, surfaced in coverage_tickers vs total.
    """
    # ── Resolve inputs ─────────────────────────────────────────────
    if tickers is None:
        ticker_list = _load_default_universe()
    else:
        ticker_list = [t for t in tickers if isinstance(t, str) and t.strip()]

    provider = data_provider if data_provider is not None else _default_data_provider

    # Guard the aligned threshold — negative / NaN would silently
    # corrupt the direction assignment.
    try:
        threshold = float(aligned_threshold)
        if threshold < 0 or threshold != threshold:  # NaN check
            threshold = DEFAULT_ALIGNED_THRESHOLD
    except (TypeError, ValueError):
        threshold = DEFAULT_ALIGNED_THRESHOLD

    # ── Build per-ticker datapoints ───────────────────────────────
    datapoints: list[CalibrationDatapoint] = []
    for ticker in ticker_list:
        try:
            payload = provider(ticker)
        except Exception as exc:
            logger.warning(
                "analyst_calibration: provider raised for %s: %s",
                ticker, exc,
            )
            continue
        if not isinstance(payload, dict):
            continue

        yiq_fv = _extract_yieldiq_fv(payload)
        wall_avg, analyst_count = _extract_wall_st_avg(payload)
        if yiq_fv is None or wall_avg is None:
            continue

        # Defensive: wall_avg already proven > 0 by extractor, but
        # guard against a freshly-introduced extractor regression.
        if wall_avg == 0:
            continue

        try:
            deviation = (yiq_fv - wall_avg) / wall_avg
        except ZeroDivisionError:
            continue
        abs_dev = abs(deviation)

        datapoints.append(CalibrationDatapoint(
            ticker=ticker,
            yieldiq_fv=yiq_fv,
            wall_st_avg=wall_avg,
            deviation_pct=deviation,
            abs_deviation_pct=abs_dev,
            direction=_direction(deviation, threshold),
            analyst_count=analyst_count,
            sector=_extract_sector(payload),
        ))

    # ── Summary aggregates ────────────────────────────────────────
    total = len(ticker_list)
    coverage = len(datapoints)

    if coverage == 0:
        return CalibrationSummary(
            total_tickers=total,
            coverage_tickers=0,
            median_abs_deviation_pct=0.0,
            p90_abs_deviation_pct=0.0,
            mean_signed_deviation_pct=0.0,
            above_wall_st=0,
            below_wall_st=0,
            aligned=0,
            by_sector={},
            top_outliers=[],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    abs_devs = [d.abs_deviation_pct for d in datapoints]
    signed_devs = [d.deviation_pct for d in datapoints]
    median_abs = statistics.median(abs_devs)
    p90_abs = _percentile(abs_devs, 0.90)
    mean_signed = statistics.fmean(signed_devs)

    above = sum(1 for d in datapoints if d.direction == "yieldiq_above")
    below = sum(1 for d in datapoints if d.direction == "yieldiq_below")
    aligned = sum(1 for d in datapoints if d.direction == "aligned")

    # By-sector bucketing. Sector None -> "Unknown" bucket so the
    # frontend can render it explicitly rather than dropping silently.
    sector_buckets: dict[str, list[CalibrationDatapoint]] = {}
    for d in datapoints:
        key = d.sector or UNKNOWN_SECTOR_BUCKET
        sector_buckets.setdefault(key, []).append(d)
    by_sector: dict[str, dict] = {}
    for sector_name, rows in sector_buckets.items():
        s_abs = [r.abs_deviation_pct for r in rows]
        s_signed = [r.deviation_pct for r in rows]
        by_sector[sector_name] = {
            "count": len(rows),
            "median_abs_dev": statistics.median(s_abs) if s_abs else 0.0,
            "signed_bias": statistics.fmean(s_signed) if s_signed else 0.0,
        }

    top_outliers = sorted(
        datapoints, key=lambda d: d.abs_deviation_pct, reverse=True,
    )[:TOP_OUTLIERS_LIMIT]

    return CalibrationSummary(
        total_tickers=total,
        coverage_tickers=coverage,
        median_abs_deviation_pct=median_abs,
        p90_abs_deviation_pct=p90_abs,
        mean_signed_deviation_pct=mean_signed,
        above_wall_st=above,
        below_wall_st=below,
        aligned=aligned,
        by_sector=by_sector,
        top_outliers=list(top_outliers),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def to_dict(summary: CalibrationSummary) -> dict:
    """JSON-safe serialization of a CalibrationSummary.

    Converts nested CalibrationDatapoint dataclasses in top_outliers
    to dicts so the returned object survives ``json.dumps`` without
    a custom encoder.
    """
    return {
        "total_tickers": summary.total_tickers,
        "coverage_tickers": summary.coverage_tickers,
        "median_abs_deviation_pct": summary.median_abs_deviation_pct,
        "p90_abs_deviation_pct": summary.p90_abs_deviation_pct,
        "mean_signed_deviation_pct": summary.mean_signed_deviation_pct,
        "above_wall_st": summary.above_wall_st,
        "below_wall_st": summary.below_wall_st,
        "aligned": summary.aligned,
        "by_sector": dict(summary.by_sector),
        "top_outliers": [d.to_dict() for d in summary.top_outliers],
        "generated_at": summary.generated_at,
    }
