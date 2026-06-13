# backend/services/backtest_publisher.py
# ═══════════════════════════════════════════════════════════════
# T1.2 — Per-sector backtest publisher.
#
# Computes per-sector calibration accuracy stats from existing
# fair_value_history + daily_prices rows and projects them into a
# JSON-safe shape for the public /calibration page.
#
# Distinct from:
#   * yiq50_backtest_service.py — basket-rotation YIQ50 vs Nifty
#     hypothetical (Day-89).
#   * fv_accuracy_service.py — directional accuracy / calibration
#     curve at the /methodology/accuracy admin surface.
#
# This module answers a single, public-facing question:
#   "For each sector, over the last N days, what was the typical
#    FV-to-actual-price gap, and how often did our 90-day-out
#    verdict match the direction the price actually moved?"
#
# ─────────────────────────────────────────────────────────────────
# Quarantine awareness
# ─────────────────────────────────────────────────────────────────
# Pre-manifest-epoch and write-gate-rejected rows must NEVER be
# projected onto a public accuracy claim. The exclusion contract is
# enforced by whichever mechanisms exist on the live schema:
#   * an unconditional date floor (date >= v_init_2026_05_22 epoch),
#   * the at-rest `quarantine_reason` marker column when present
#     (migration 202606031123; absent on prod as of 2026-06-13), and
#   * an anti-join against the sibling `fair_value_history_quarantine`
#     table when it exists (migration 202606111430).
# The SQL provider probes information_schema / to_regclass and only
# references the optional column / table when they are present — so a
# DB on which the superset migration never ran still serves a correct
# (non-empty) payload rather than erroring into a blank page. The meta
# block documents this so the consumer page can name the policy.
#
# ─────────────────────────────────────────────────────────────────
# SEBI vocabulary
# ─────────────────────────────────────────────────────────────────
# The public payload uses neutral, descriptive language only:
#   * median_abs_error_pct, p90_abs_error_pct → factual error stats
#   * direction_accuracy_pct → factual hit-rate
# No advisory verbs ("recommend", "outperform"), no quality claims
# ("best in class", "strong accuracy"). The page-level copy mirrors
# this discipline.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

logger = logging.getLogger("yieldiq.backtest_publisher")


# ─────────────────────────────────────────────────────────────────
# Public dataclass
# ─────────────────────────────────────────────────────────────────
@dataclass
class SectorCalibrationStat:
    """Per-sector calibration summary.

    All percent fields are wall-clock percentages (e.g. 12.3 not 0.123).
    Counts are non-negative integers. last_observation_date is an ISO
    date string in YYYY-MM-DD form.
    """
    sector: str
    ticker_count: int             # distinct tickers contributing rows
    observation_count: int        # total (ticker, date) pairs
    median_abs_error_pct: float   # median |FV - price| / price * 100
    median_signed_error_pct: float  # median (FV - price) / price * 100
    p90_abs_error_pct: float      # 90th percentile of |error|
    direction_accuracy_pct: float  # % of obs where verdict matched
                                   # 90-day forward price direction
    last_observation_date: str    # ISO YYYY-MM-DD


# ─────────────────────────────────────────────────────────────────
# Direction-accuracy thresholds (mirror fv_accuracy_service)
# ─────────────────────────────────────────────────────────────────
# A backtest observation is directionally CORRECT iff:
#   * MoS at publish-time > +5% AND 90-day return > +5%, OR
#   * MoS at publish-time < -5% AND 90-day return < -5%, OR
#   * |MoS at publish-time| <= 5% AND |90-day return| <= 10%
# These mirror the bands fv_accuracy_service uses so admin /
# /methodology/accuracy and public /calibration agree on definitions.
_MOS_BELOW_THRESHOLD = 5.0      # below: FV > price by >5%
_MOS_ABOVE_THRESHOLD = -5.0     # above: FV < price by >5% (-5% MoS)
_MOS_NEAR_BAND = 5.0            # near: |MoS| <= 5%
_RETURN_DIR_THRESHOLD = 5.0     # forward return treated as directional
_RETURN_NEAR_BAND = 10.0        # forward return treated as flat

# Quantile helpers — pure Python so we don't pull in numpy on the
# request path. The observation set is bounded (tickers × days
# capped at ~2400 × 90 = 216k worst-case, but in practice a few
# thousand per sector).


def _safe_float(x) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _percentile(sorted_values: list[float], pct: float) -> Optional[float]:
    """Linear-interpolation percentile on an ALREADY-SORTED list.

    pct is in [0, 100]. Returns None on empty input.
    """
    n = len(sorted_values)
    if n == 0:
        return None
    if n == 1:
        return sorted_values[0]
    # Position on the 0..n-1 axis.
    k = (pct / 100.0) * (n - 1)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_values[lo]
    frac = k - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _median(sorted_values: list[float]) -> Optional[float]:
    return _percentile(sorted_values, 50.0)


# ─────────────────────────────────────────────────────────────────
# Pure compute layer
# ─────────────────────────────────────────────────────────────────
# Each observation row has the shape:
#   {
#     "sector": "Information Technology",
#     "ticker": "TCS",
#     "date": "2026-03-01",      # ISO date string OR datetime/date
#     "fair_value": 4200.0,
#     "price": 3800.0,           # price ON publish date
#     "mos_pct": 10.5,           # MoS at publish-time (computed)
#     "forward_price": 4100.0,   # actual price ~90 days later
#                                # (may be None — direction skipped)
#   }
#
# `mos_pct` is included rather than recomputed from FV/price so the
# row carries the engine's at-publish-time view (which respects all
# the cohort overrides, floor clamps, etc.). When mos_pct is missing
# from the row, the compute path falls back to (FV - price) / price.

def _observation_to_metrics(row: dict) -> Optional[dict]:
    """Normalise one observation row to the float fields the
    aggregation needs. Returns None when the row is unusable."""
    fv = _safe_float(row.get("fair_value"))
    price = _safe_float(row.get("price"))
    if fv is None or price is None or price <= 0:
        return None
    abs_err_pct = abs(fv - price) / price * 100.0
    signed_err_pct = (fv - price) / price * 100.0
    mos = _safe_float(row.get("mos_pct"))
    if mos is None:
        # Fallback: compute MoS from FV/price the same way the engine
        # does in the steady-state path.
        mos = signed_err_pct
    fwd = _safe_float(row.get("forward_price"))
    fwd_ret_pct: Optional[float] = None
    if fwd is not None and price > 0:
        fwd_ret_pct = (fwd - price) / price * 100.0
        if not math.isfinite(fwd_ret_pct):
            fwd_ret_pct = None
    return {
        "abs_err_pct": abs_err_pct,
        "signed_err_pct": signed_err_pct,
        "mos_pct": mos,
        "fwd_ret_pct": fwd_ret_pct,
    }


def _is_directionally_correct(mos_pct: float, fwd_ret_pct: float) -> bool:
    """Mirror fv_accuracy_service direction bands."""
    if mos_pct > _MOS_BELOW_THRESHOLD:
        return fwd_ret_pct > _RETURN_DIR_THRESHOLD
    if mos_pct < _MOS_ABOVE_THRESHOLD:
        return fwd_ret_pct < -_RETURN_DIR_THRESHOLD
    # near band
    return abs(fwd_ret_pct) <= _RETURN_NEAR_BAND


def _coerce_date_str(value) -> Optional[str]:
    """Return an ISO YYYY-MM-DD string for a date / datetime / str."""
    if value is None:
        return None
    # datetime / date both expose isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()[:10]
        except Exception:
            return None
    if isinstance(value, str):
        # Already ISO?
        return value[:10] if len(value) >= 10 else value
    return None


def _aggregate_sector(
    sector: str,
    rows: list[dict],
) -> Optional[SectorCalibrationStat]:
    """Reduce a sector's observation rows to a single stat row.

    Returns None when the sector has no usable observations (all rows
    failed the FV/price sanity check). The caller is responsible for
    enforcing the min_observations threshold.
    """
    abs_errs: list[float] = []
    signed_errs: list[float] = []
    direction_hits = 0
    direction_total = 0
    tickers: set[str] = set()
    last_dt: Optional[str] = None

    for row in rows:
        metrics = _observation_to_metrics(row)
        if metrics is None:
            continue
        abs_errs.append(metrics["abs_err_pct"])
        signed_errs.append(metrics["signed_err_pct"])
        ticker = row.get("ticker")
        if ticker:
            tickers.add(str(ticker).upper())
        dt_str = _coerce_date_str(row.get("date"))
        if dt_str is not None:
            if last_dt is None or dt_str > last_dt:
                last_dt = dt_str
        fwd_ret = metrics["fwd_ret_pct"]
        if fwd_ret is not None:
            direction_total += 1
            if _is_directionally_correct(metrics["mos_pct"], fwd_ret):
                direction_hits += 1

    if not abs_errs:
        return None

    abs_errs.sort()
    signed_errs.sort()

    median_abs = _median(abs_errs) or 0.0
    median_signed = _median(signed_errs) or 0.0
    p90_abs = _percentile(abs_errs, 90.0) or 0.0

    direction_pct = (
        round((direction_hits / direction_total) * 100.0, 1)
        if direction_total > 0
        else 0.0
    )

    return SectorCalibrationStat(
        sector=sector,
        ticker_count=len(tickers),
        observation_count=len(abs_errs),
        median_abs_error_pct=round(median_abs, 2),
        median_signed_error_pct=round(median_signed, 2),
        p90_abs_error_pct=round(p90_abs, 2),
        direction_accuracy_pct=direction_pct,
        last_observation_date=last_dt or "",
    )


# ─────────────────────────────────────────────────────────────────
# Data provider — injectable for tests (T1.5 Phase A pattern)
# ─────────────────────────────────────────────────────────────────
# Production path: read from the shared pipeline DB session.
# Test path: pass a callable returning a list of pre-baked observation
# dicts.

DataProvider = Callable[[int], Iterable[dict]]


def _default_data_provider(lookback_days: int) -> list[dict]:
    """Production DB read.

    Joins fair_value_history (FV publish events) against daily_prices
    (actual market price on the publish date) and a forward-shifted
    daily_prices row (price ~90 days later). Skips quarantined rows.

    Returns rows in the shape _observation_to_metrics expects.
    """
    try:
        from data_pipeline.db import Session
    except Exception as exc:
        logger.warning("backtest_publisher: db import failed: %s", exc)
        return []
    if Session is None:
        logger.info(
            "backtest_publisher: DATABASE_URL unset, returning empty set"
        )
        return []

    from sqlalchemy import text

    sess = Session()
    try:
        # ── Quarantine-exclusion contract (schema-robust) ─────────────
        # The quarantine epoch is enforced in prod by TWO mechanisms,
        # only one of which is guaranteed to exist on a given DB:
        #
        #   1. DATE FLOOR — rows dated before the manifest epoch
        #      (v_init_2026_05_22) are pre-epoch and never servable.
        #      Always applied below.
        #
        #   2. fair_value_history.quarantine_reason — an at-rest marker
        #      column added by migration 202606031123_fair_value_history_
        #      superset.sql. That migration has NOT been applied on every
        #      environment (prod, as of 2026-06-13, has no such column).
        #      Referencing it unconditionally makes the whole query throw,
        #      and the except-wrapper below then silently returns [] — so
        #      the public /calibration page serves a blank payload. We
        #      therefore PROBE information_schema first and only AND the
        #      predicate when the column is present (mirrors the
        #      column-probe in services/data_quality/db_loaders.py).
        #
        #   3. fair_value_history_quarantine — a SEPARATE sibling table
        #      (migration 202606111430) holding write-gate-rejected rows
        #      (daily |Δ| > 25% without corroboration). When it exists we
        #      anti-join it out by (ticker, date). Guarded by to_regclass
        #      so a DB without the table still works.
        #
        # The publish-side price is fair_value_history.price (the price
        # the engine saw at publish time). The forward-side price is the
        # most-recent daily_prices.close on or before publish_date + 90d
        # — fenced ±5d so we don't pick up a price from after a big
        # corporate action window.
        #
        # Sector is read from stocks.sector. Tickers may be stored as
        # bare ("TCS") or .NS-suffixed ("TCS.NS") in fair_value_history
        # depending on the write path — we normalise to bare for the
        # JOIN against stocks.

        # Probe: which optional quarantine artifacts exist on THIS db?
        try:
            has_qr_col = bool(
                sess.execute(
                    text(
                        """
                        SELECT 1
                          FROM information_schema.columns
                         WHERE table_name = 'fair_value_history'
                           AND column_name = 'quarantine_reason'
                         LIMIT 1
                        """
                    )
                ).first()
            )
        except Exception:
            has_qr_col = False
        try:
            has_q_table = (
                sess.execute(
                    text("SELECT to_regclass('public.fair_value_history_quarantine')")
                ).scalar()
                is not None
            )
        except Exception:
            has_q_table = False

        # Build the quarantine predicate from only the mechanisms that
        # exist on this schema. The date floor is unconditional.
        quarantine_col_clause = (
            "AND fvh.quarantine_reason IS NULL\n" if has_qr_col else ""
        )
        quarantine_table_clause = (
            """AND NOT EXISTS (
                      SELECT 1 FROM fair_value_history_quarantine q
                       WHERE q.ticker = fvh.ticker
                         AND q.date = fvh.date
                  )
                  """
            if has_q_table
            else ""
        )

        sql = f"""
            WITH fv_publish AS (
                SELECT
                    UPPER(REPLACE(REPLACE(fvh.ticker, '.NS', ''), '.BO', '')) AS bare_ticker,
                    fvh.date AS publish_date,
                    fvh.fair_value,
                    fvh.price AS publish_price,
                    fvh.mos_pct
                FROM fair_value_history fvh
                WHERE fvh.date >= (CURRENT_DATE - (:lookback_days || ' days')::interval)::date
                  AND fvh.date >= DATE '2026-05-22'
                  {quarantine_col_clause}{quarantine_table_clause}AND fvh.fair_value IS NOT NULL
                  AND fvh.price IS NOT NULL
                  AND fvh.price > 0
            ),
            fwd_price AS (
                SELECT DISTINCT ON (fvp.bare_ticker, fvp.publish_date)
                    fvp.bare_ticker,
                    fvp.publish_date,
                    dp.close_price AS forward_price
                FROM fv_publish fvp
                LEFT JOIN daily_prices dp
                  ON dp.ticker = fvp.bare_ticker
                 AND dp.trade_date BETWEEN (fvp.publish_date + INTERVAL '85 days')::date
                                       AND (fvp.publish_date + INTERVAL '95 days')::date
                ORDER BY fvp.bare_ticker, fvp.publish_date, dp.trade_date ASC
            )
            SELECT
                COALESCE(NULLIF(TRIM(s.sector), ''), 'Unclassified') AS sector,
                fvp.bare_ticker AS ticker,
                fvp.publish_date AS date,
                fvp.fair_value,
                fvp.publish_price AS price,
                fvp.mos_pct,
                fp.forward_price
            FROM fv_publish fvp
            LEFT JOIN stocks s ON s.ticker = fvp.bare_ticker
            LEFT JOIN fwd_price fp
              ON fp.bare_ticker = fvp.bare_ticker
             AND fp.publish_date = fvp.publish_date
        """
        result = sess.execute(text(sql), {"lookback_days": lookback_days})
        rows: list[dict] = []
        for r in result:
            # SQLAlchemy Row → dict via _mapping for forward compat.
            try:
                m = dict(r._mapping)
            except Exception:
                # Fallback: positional tuple unpack
                m = {
                    "sector": r[0],
                    "ticker": r[1],
                    "date": r[2],
                    "fair_value": r[3],
                    "price": r[4],
                    "mos_pct": r[5],
                    "forward_price": r[6],
                }
            rows.append(m)
        return rows
    except Exception as exc:
        logger.warning(
            "backtest_publisher: SQL fetch failed (%s) — returning empty", exc
        )
        return []
    finally:
        try:
            sess.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────
# Top-level compute
# ─────────────────────────────────────────────────────────────────
def compute_sector_calibration(
    min_observations: int = 30,
    lookback_days: int = 90,
    *,
    data_provider: DataProvider | None = None,
) -> list[SectorCalibrationStat]:
    """Return per-sector calibration stats.

    Sectors with fewer than ``min_observations`` observations are
    excluded — the median/percentile of a tiny sample is noise, and
    publishing it would imply more precision than we have.

    Quarantine-aware via the SQL filter inside the default provider.

    Args:
        min_observations: minimum usable (ticker, date) pairs required
            for a sector to appear in the output.
        lookback_days: how far back to look when fetching FV-publish
            events from fair_value_history.
        data_provider: callable(lookback_days) -> iterable of dicts.
            Defaults to the production DB-read path. Tests inject a
            stub.

    Returns:
        List of SectorCalibrationStat, sorted by observation_count
        descending (largest signals first). Empty list on empty input.
    """
    provider = data_provider or _default_data_provider
    try:
        rows = list(provider(lookback_days))
    except Exception as exc:
        logger.warning(
            "backtest_publisher: data provider raised (%s) — empty result",
            exc,
        )
        return []

    if not rows:
        return []

    # Group by sector.
    by_sector: dict[str, list[dict]] = {}
    for row in rows:
        sector = row.get("sector")
        if not sector or not isinstance(sector, str):
            continue
        by_sector.setdefault(sector.strip(), []).append(row)

    out: list[SectorCalibrationStat] = []
    for sector, sector_rows in by_sector.items():
        stat = _aggregate_sector(sector, sector_rows)
        if stat is None:
            continue
        if stat.observation_count < min_observations:
            continue
        out.append(stat)

    # Sort: largest observation_count first, then alphabetical tie-break
    # so the public table has a stable order even when sample sizes match.
    out.sort(key=lambda s: (-s.observation_count, s.sector.lower()))
    return out


# ─────────────────────────────────────────────────────────────────
# JSON projection
# ─────────────────────────────────────────────────────────────────
QUARANTINE_POLICY_TEXT = (
    "Pre-manifest-epoch rows (fair_value_history.date before "
    "2026-05-22) are excluded by a date floor, and write-gate-rejected "
    "rows captured in the fair_value_history_quarantine table are "
    "anti-joined out. Where the at-rest quarantine_reason marker "
    "column exists, only rows with quarantine_reason IS NULL contribute "
    "to the published stats."
)


def to_dict(
    stats: list[SectorCalibrationStat],
    *,
    lookback_days: int = 90,
    min_observations: int = 30,
) -> dict:
    """Project stats into the JSON-safe response shape.

    The shape mirrors what backend/routers/calibration.py returns so
    the router can simply call this function and forward the result.
    """
    sectors_payload = [asdict(s) for s in (stats or [])]
    return {
        "sectors": sectors_payload,
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lookback_days": int(lookback_days),
            "min_observations": int(min_observations),
            "quarantine_policy": QUARANTINE_POLICY_TEXT,
            "sector_count": len(sectors_payload),
            # Direction-band definitions, mirrored so the consumer page
            # can document the math without re-deriving it.
            "direction_bands": {
                "below_mos_threshold_pct": _MOS_BELOW_THRESHOLD,
                "above_mos_threshold_pct": _MOS_ABOVE_THRESHOLD,
                "forward_return_threshold_pct": _RETURN_DIR_THRESHOLD,
                "near_band_return_pct": _RETURN_NEAR_BAND,
            },
        },
    }
