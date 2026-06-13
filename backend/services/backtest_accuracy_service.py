# backend/services/backtest_accuracy_service.py
# ═══════════════════════════════════════════════════════════════
# Accuracy measurement loop — verdict → forward-return backtest.
#
# THE STRATEGIC GAP THIS CLOSES
# ─────────────────────────────
# Until now we could publish a verdict but could not grade it. This
# service answers, factually and reproducibly:
#
#   * Do below-fair-value calls realise higher forward returns than
#     above-fair-value calls? (return attribution by verdict band)
#   * How often does the verdict-implied direction match the realised
#     forward price direction? (direction hit-rate)
#   * Does a higher margin-of-safety at publish time map to a higher
#     forward return? (the MoS-decile → forward-return curve — the
#     real calibration signal)
#
# …at multiple forward horizons (21 / 30 / 90 / 180 days), overall and
# per sector. This is the parity scorecard.
#
# DISTINCT FROM the neighbouring services:
#   * backtest_publisher.py    — per-sector FV-vs-price ERROR percentiles
#                                (median |error|, p90) + a single 90d
#                                direction-hit number. No horizon sweep,
#                                no MoS-decile curve, no per-verdict
#                                return attribution.
#   * fv_accuracy_service.py   — pure 12-month directional / calibration
#                                math; the router feeds it price_then /
#                                price_now rows. We reuse its SEBI-safe
#                                band vocabulary and its band-direction
#                                bands, but compute the forward prices
#                                ourselves at several horizons.
#   * verdict_attribution_*.py — per-ticker alpha-vs-benchmark episodes.
#
# QUARANTINE EPOCH
# ────────────────
# The fair_value_history table contains a documented pre-manifest epoch
# (rows dated before the `v_init_2026_05_22` manifest event) for which
# no corroboration is possible. Those rows MUST NOT be projected onto
# any accuracy claim. We enforce the epoch by DATE — the SQL hard-floors
# `fair_value_history.date >= QUARANTINE_EPOCH_DATE` — which is robust
# whether or not the at-rest `quarantine_reason` column exists in the
# target database (it does not exist in every environment). When the
# column IS present we additionally AND `quarantine_reason IS NULL`.
#
# STATISTICAL POWER (be honest)
# ─────────────────────────────
# As of mid-June 2026 only ~3 weeks of quarantine-clean history exist,
# and adj_close lags for the recent epoch (we COALESCE to close_price).
# That means the 30 / 90 / 180-day horizons currently mature ZERO
# observations — they are correct-but-empty, and become meaningful as
# history accrues. The 21-day horizon is the only one with signal today
# and exists precisely so the harness has something to grade now. Every
# bucket carries its own observation_count and a `low_n` flag so a
# consumer never mistakes a 3-observation median for a real edge.
#
# SEBI VOCABULARY
# ───────────────
# Output uses neutral, descriptive language only: median_forward_return_pct,
# direction_hit_rate_pct, forward return by band name. No advisory verbs
# and no quality claims of any kind reach the wire (see scripts/
# check_sebi_words.py BANNED_WORDS for the enforced vocabulary set).
# Verdict strings are mapped to the SEBI-safe band names
# (below_fair_value / near_fair_value / above_fair_value) before they
# ever reach the wire — the legacy "undervalued"/"overvalued" tokens are
# never emitted.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from backend.services.fv_accuracy_service import (
    ALL_BANDS,
    BAND_ABOVE,
    BAND_BELOW,
    BAND_NEAR,
    DIR_ABOVE_THRESHOLD,
    DIR_BELOW_THRESHOLD,
    DIR_NEAR_BAND,
    _to_band,
)

logger = logging.getLogger("yieldiq.backtest_accuracy")


# ─────────────────────────────────────────────────────────────────
# Quarantine epoch + horizons + low-n policy
# ─────────────────────────────────────────────────────────────────
# Rows dated before this manifest event (v_init_2026_05_22) are the
# pre-manifest epoch and are excluded by construction. Stored as an ISO
# date string so the SQL floor and the meta documentation share one
# source of truth.
QUARANTINE_EPOCH_DATE = "2026-05-22"

# Forward horizons (calendar days). The 21d horizon is the early-signal
# proxy — it is the only horizon that matures observations in the first
# weeks of clean history. 30/90/180 are the model's intended evaluation
# windows and fill in as history accrues.
FORWARD_HORIZONS_DAYS: tuple[int, ...] = (21, 30, 90, 180)

# A forward price is accepted when a daily_prices row exists within
# ±this many calendar days of (publish_date + horizon). Widened slightly
# vs the backtest_publisher's ±5 because at short horizons a single
# market holiday can otherwise drop an observation entirely.
_FORWARD_WINDOW_TOLERANCE_DAYS = 4

# Below this observation count a bucket's median is noise. We never drop
# the bucket (callers want to see the n), but we flag it so the consumer
# can grey it out / footnote it.
LOW_N_THRESHOLD = 30

# Number of MoS deciles for the calibration curve. Ten buckets is the
# standard decile resolution; with low n the curve degrades gracefully
# (fewer populated deciles) rather than crashing.
_MOS_DECILE_COUNT = 10


# ─────────────────────────────────────────────────────────────────
# Pure numeric helpers (defensive — None on any non-finite input)
# ─────────────────────────────────────────────────────────────────
def _safe_float(x) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


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


def _forward_return_pct(price_then: Optional[float], price_fwd: Optional[float]) -> Optional[float]:
    if price_then is None or price_fwd is None or price_then <= 0:
        return None
    r = (price_fwd - price_then) / price_then * 100.0
    return r if math.isfinite(r) else None


def _direction_correct(band: str, ret_pct: float) -> bool:
    """Did the realised forward return move the way the band implied?

    Mirrors fv_accuracy_service.compute_directional_accuracy exactly so
    the public /calibration and /backtest-accuracy surfaces agree on
    what 'correct' means.
    """
    if band == BAND_BELOW:
        return ret_pct > DIR_BELOW_THRESHOLD
    if band == BAND_ABOVE:
        return ret_pct < DIR_ABOVE_THRESHOLD
    # near band
    return abs(ret_pct) <= DIR_NEAR_BAND


# ─────────────────────────────────────────────────────────────────
# Observation row shape (one per (ticker, publish_date, horizon)):
#   {
#     "sector":   "Information Technology",   # may be None / "" → "Unclassified"
#     "ticker":   "TCS",
#     "date":     "2026-05-25",               # publish date (ISO / date / datetime)
#     "verdict":  "undervalued",              # RAW legacy verdict
#     "mos_pct":  12.5,                        # MoS at publish time
#     "price":    3800.0,                      # price ON publish date
#     "horizon_days": 21,                      # which forward horizon this row is for
#     "forward_price": 3900.0,                 # actual price ~horizon days later (or None)
#   }
# Rows whose verdict does not map to a band, or whose price/forward_price
# is unusable, are silently dropped — a malformed row never poisons the
# aggregate.
# ─────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────
# Output dataclasses
# ─────────────────────────────────────────────────────────────────
@dataclass
class VerdictBucketStat:
    """Forward-return summary for one verdict band at one horizon."""
    band: str                       # SEBI-safe band name
    observation_count: int
    mean_forward_return_pct: Optional[float]
    median_forward_return_pct: Optional[float]
    direction_hit_rate_pct: Optional[float]   # 0..100 or None when n=0
    low_n: bool


@dataclass
class MosDecileStat:
    """One MoS decile's forward-return summary at one horizon."""
    decile: int                     # 1..10, 1 = lowest MoS
    observation_count: int
    avg_mos_pct: Optional[float]
    mean_forward_return_pct: Optional[float]
    median_forward_return_pct: Optional[float]
    low_n: bool


@dataclass
class HorizonScorecard:
    """The full parity scorecard at one forward horizon."""
    horizon_days: int
    observation_count: int
    # Verdict-band attribution (overall, all sectors pooled).
    by_band: list[VerdictBucketStat] = field(default_factory=list)
    # Whether realised returns are monotonic across bands in the
    # economically-expected order (below > near > above). None when any
    # band is empty.
    band_return_monotonic: Optional[bool] = None
    # Overall direction hit-rate across all evaluable observations.
    overall_direction_hit_rate_pct: Optional[float] = None
    # MoS-decile → forward-return calibration curve.
    mos_decile_curve: list[MosDecileStat] = field(default_factory=list)
    # Whether median forward return increases across populated deciles.
    mos_curve_monotonic: Optional[bool] = None


@dataclass
class SectorHorizonStat:
    """Per-sector, per-horizon verdict-band attribution + hit-rate."""
    sector: str
    horizon_days: int
    observation_count: int
    by_band: list[VerdictBucketStat] = field(default_factory=list)
    direction_hit_rate_pct: Optional[float] = None
    low_n: bool = True


# ─────────────────────────────────────────────────────────────────
# Per-horizon aggregation
# ─────────────────────────────────────────────────────────────────
def _evaluable_rows(rows: Iterable[dict]) -> list[dict]:
    """Normalise + filter rows to those usable for forward-return math.

    Keeps only rows whose verdict maps to a band and whose price and
    forward_price are positive finite floats. Adds derived keys:
    ``band`` (SEBI-safe), ``ret_pct`` (forward return), ``mos`` (float).
    """
    out: list[dict] = []
    for r in rows:
        band = _to_band(r.get("verdict"))
        if band is None:
            continue
        price = _safe_float(r.get("price"))
        fwd = _safe_float(r.get("forward_price"))
        ret = _forward_return_pct(price, fwd)
        if ret is None:
            continue
        mos = _safe_float(r.get("mos_pct"))
        if mos is None:
            # Fall back to the FV/price-implied MoS proxy only if we can.
            # Without a usable MoS the row still counts for band/return
            # stats but is skipped from the MoS-decile curve.
            mos = None
        sector = r.get("sector")
        sector = (
            sector.strip()
            if isinstance(sector, str) and sector.strip()
            else "Unclassified"
        )
        out.append({
            "sector": sector,
            "band": band,
            "ret_pct": ret,
            "mos": mos,
        })
    return out


def _band_buckets(eval_rows: list[dict]) -> list[VerdictBucketStat]:
    """Reduce evaluable rows to per-band forward-return stats."""
    grouped: dict[str, list[dict]] = {b: [] for b in ALL_BANDS}
    for r in eval_rows:
        grouped[r["band"]].append(r)

    out: list[VerdictBucketStat] = []
    for band in ALL_BANDS:
        rs = grouped[band]
        rets = [r["ret_pct"] for r in rs]
        n = len(rets)
        if n == 0:
            out.append(VerdictBucketStat(
                band=band, observation_count=0,
                mean_forward_return_pct=None,
                median_forward_return_pct=None,
                direction_hit_rate_pct=None, low_n=True,
            ))
            continue
        hits = sum(1 for r in rs if _direction_correct(band, r["ret_pct"]))
        out.append(VerdictBucketStat(
            band=band,
            observation_count=n,
            mean_forward_return_pct=_mean(rets),
            median_forward_return_pct=_median(rets),
            direction_hit_rate_pct=round(100.0 * hits / n, 2),
            low_n=n < LOW_N_THRESHOLD,
        ))
    return out


def _band_monotonic(buckets: list[VerdictBucketStat]) -> Optional[bool]:
    """True iff median return is strictly ordered below > near > above.

    None when any of the three bands is empty (can't judge).
    """
    by_band = {b.band: b for b in buckets}
    below = by_band.get(BAND_BELOW)
    near = by_band.get(BAND_NEAR)
    above = by_band.get(BAND_ABOVE)
    if not (below and near and above):
        return None
    vals = [
        below.median_forward_return_pct,
        near.median_forward_return_pct,
        above.median_forward_return_pct,
    ]
    if any(v is None for v in vals):
        return None
    return vals[0] > vals[1] > vals[2]  # type: ignore[operator]


def _overall_hit_rate(eval_rows: list[dict]) -> Optional[float]:
    n = len(eval_rows)
    if n == 0:
        return None
    hits = sum(1 for r in eval_rows if _direction_correct(r["band"], r["ret_pct"]))
    return round(100.0 * hits / n, 2)


def _mos_decile_curve(eval_rows: list[dict]) -> tuple[list[MosDecileStat], Optional[bool]]:
    """Build the MoS-decile → forward-return curve.

    Rows are ranked by publish-time MoS and split into deciles. Each
    decile reports its average MoS and the mean/median forward return.
    A model whose MoS carries signal produces a roughly monotonic curve
    (higher MoS decile → higher forward return).

    Rows without a usable MoS are excluded from the curve (they still
    count toward the band stats elsewhere).
    """
    scored = [r for r in eval_rows if r["mos"] is not None]
    scored.sort(key=lambda r: r["mos"])
    n = len(scored)
    if n == 0:
        return [], None

    curve: list[MosDecileStat] = []
    # Even split into _MOS_DECILE_COUNT buckets; the last bucket absorbs
    # the remainder. With n < decile-count some deciles are empty and are
    # emitted with observation_count 0 so the x-axis stays stable.
    base = n // _MOS_DECILE_COUNT
    rem = n % _MOS_DECILE_COUNT
    idx = 0
    for d in range(1, _MOS_DECILE_COUNT + 1):
        size = base + (1 if d <= rem else 0)
        chunk = scored[idx: idx + size]
        idx += size
        cnt = len(chunk)
        if cnt == 0:
            curve.append(MosDecileStat(
                decile=d, observation_count=0, avg_mos_pct=None,
                mean_forward_return_pct=None, median_forward_return_pct=None,
                low_n=True,
            ))
            continue
        moses = [r["mos"] for r in chunk]
        rets = [r["ret_pct"] for r in chunk]
        curve.append(MosDecileStat(
            decile=d,
            observation_count=cnt,
            avg_mos_pct=_mean(moses),
            mean_forward_return_pct=_mean(rets),
            median_forward_return_pct=_median(rets),
            low_n=cnt < max(5, LOW_N_THRESHOLD // _MOS_DECILE_COUNT),
        ))

    # Monotonicity across POPULATED deciles only.
    populated = [c for c in curve if c.observation_count > 0]
    monotonic: Optional[bool] = None
    if len(populated) >= 2:
        meds = [c.median_forward_return_pct for c in populated]
        if all(m is not None for m in meds):
            monotonic = all(
                meds[i] < meds[i + 1]  # type: ignore[operator]
                for i in range(len(meds) - 1)
            )
    return curve, monotonic


def _build_horizon_scorecard(horizon_days: int, rows: list[dict]) -> HorizonScorecard:
    eval_rows = _evaluable_rows(rows)
    buckets = _band_buckets(eval_rows)
    curve, curve_mono = _mos_decile_curve(eval_rows)
    return HorizonScorecard(
        horizon_days=horizon_days,
        observation_count=len(eval_rows),
        by_band=buckets,
        band_return_monotonic=_band_monotonic(buckets),
        overall_direction_hit_rate_pct=_overall_hit_rate(eval_rows),
        mos_decile_curve=curve,
        mos_curve_monotonic=curve_mono,
    )


def _build_sector_stats(
    horizon_days: int,
    rows: list[dict],
    *,
    min_sector_observations: int,
) -> list[SectorHorizonStat]:
    eval_rows = _evaluable_rows(rows)
    by_sector: dict[str, list[dict]] = {}
    for r in eval_rows:
        by_sector.setdefault(r["sector"], []).append(r)

    out: list[SectorHorizonStat] = []
    for sector, srows in by_sector.items():
        if len(srows) < min_sector_observations:
            continue
        buckets = _band_buckets(srows)
        out.append(SectorHorizonStat(
            sector=sector,
            horizon_days=horizon_days,
            observation_count=len(srows),
            by_band=buckets,
            direction_hit_rate_pct=_overall_hit_rate(srows),
            low_n=len(srows) < LOW_N_THRESHOLD,
        ))
    out.sort(key=lambda s: (-s.observation_count, s.sector.lower()))
    return out


# ─────────────────────────────────────────────────────────────────
# Data provider — injectable for tests
# ─────────────────────────────────────────────────────────────────
# Production: read fair_value_history (clean epoch) joined to forward
# daily_prices at each horizon. Returns one row per (ticker, date,
# horizon). Tests inject a callable that returns pre-baked rows.
DataProvider = Callable[[tuple[int, ...]], Iterable[dict]]

# Detected once per process: whether the quarantine_reason column exists
# in this database. None = not yet probed.
_QUARANTINE_COL_CACHE: Optional[bool] = None


def _quarantine_column_present(sess) -> bool:
    global _QUARANTINE_COL_CACHE
    if _QUARANTINE_COL_CACHE is not None:
        return _QUARANTINE_COL_CACHE
    from sqlalchemy import text
    try:
        r = sess.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'fair_value_history' "
            "AND column_name = 'quarantine_reason' LIMIT 1"
        )).fetchone()
        _QUARANTINE_COL_CACHE = r is not None
    except Exception:
        _QUARANTINE_COL_CACHE = False
    return _QUARANTINE_COL_CACHE


def _default_data_provider(horizons: tuple[int, ...]) -> list[dict]:
    """Production DB read.

    For every clean (post-epoch) fair_value_history publish event and
    every requested horizon, finds the nearest daily_prices row within
    ±tolerance of (publish_date + horizon) and emits one observation
    row. Price source is COALESCE(adj_close, close_price) — adj_close is
    preferred (split/dividend-adjusted) but lags for the recent epoch,
    so close_price is the fallback.

    The epoch is enforced by DATE (robust to schema variance); when the
    quarantine_reason column exists it is additionally required to be
    NULL.
    """
    try:
        from backend.services.market_data_service import _get_session
    except Exception as exc:
        logger.warning("backtest_accuracy: session import failed: %s", exc)
        return []

    sess = _get_session()
    if sess is None:
        logger.info("backtest_accuracy: DATABASE_URL unset / no session — empty set")
        return []

    from sqlalchemy import text

    try:
        quarantine_clause = ""
        if _quarantine_column_present(sess):
            quarantine_clause = "AND fvh.quarantine_reason IS NULL"

        # One UNION-free pass per horizon would be simplest, but a single
        # query keyed by a horizon array keeps the round-trips down. We
        # CROSS JOIN the publish events against the horizon list, then
        # DISTINCT-ON the nearest forward price per (ticker, date, horizon).
        sql = f"""
            WITH horizons AS (
                SELECT UNNEST(:horizons ::int[]) AS h
            ),
            fv_publish AS (
                SELECT
                    UPPER(REPLACE(REPLACE(fvh.ticker, '.NS', ''), '.BO', '')) AS bare_ticker,
                    fvh.date AS publish_date,
                    fvh.verdict,
                    fvh.price AS publish_price,
                    fvh.mos_pct
                FROM fair_value_history fvh
                WHERE fvh.date >= CAST(:epoch AS date)
                  {quarantine_clause}
                  AND fvh.price IS NOT NULL
                  AND fvh.price > 0
                  AND fvh.verdict IS NOT NULL
            ),
            events AS (
                SELECT fvp.*, h.h AS horizon_days
                FROM fv_publish fvp
                CROSS JOIN horizons h
            ),
            matched AS (
                SELECT DISTINCT ON (e.bare_ticker, e.publish_date, e.horizon_days)
                    e.bare_ticker,
                    e.publish_date,
                    e.verdict,
                    e.publish_price,
                    e.mos_pct,
                    e.horizon_days,
                    COALESCE(dp.adj_close, dp.close_price) AS forward_price
                FROM events e
                LEFT JOIN daily_prices dp
                  ON dp.ticker = e.bare_ticker
                 AND dp.trade_date BETWEEN (e.publish_date + (e.horizon_days - :tol) * INTERVAL '1 day')::date
                                       AND (e.publish_date + (e.horizon_days + :tol) * INTERVAL '1 day')::date
                 AND COALESCE(dp.adj_close, dp.close_price) > 0
                ORDER BY e.bare_ticker, e.publish_date, e.horizon_days, dp.trade_date ASC
            )
            SELECT
                COALESCE(NULLIF(TRIM(s.sector), ''), 'Unclassified') AS sector,
                m.bare_ticker AS ticker,
                m.publish_date AS date,
                m.verdict,
                m.mos_pct,
                m.publish_price AS price,
                m.horizon_days,
                m.forward_price
            FROM matched m
            LEFT JOIN stocks s ON s.ticker = m.bare_ticker
            WHERE m.forward_price IS NOT NULL
        """
        result = sess.execute(
            text(sql),
            {
                "horizons": list(horizons),
                "epoch": QUARANTINE_EPOCH_DATE,
                "tol": _FORWARD_WINDOW_TOLERANCE_DAYS,
            },
        )
        rows: list[dict] = []
        for r in result:
            try:
                rows.append(dict(r._mapping))
            except Exception:
                rows.append({
                    "sector": r[0], "ticker": r[1], "date": r[2],
                    "verdict": r[3], "mos_pct": r[4], "price": r[5],
                    "horizon_days": r[6], "forward_price": r[7],
                })
        return rows
    except Exception as exc:
        logger.warning("backtest_accuracy: SQL fetch failed (%s) — empty", exc)
        return []
    finally:
        try:
            sess.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────
# Top-level compute
# ─────────────────────────────────────────────────────────────────
@dataclass
class BacktestAccuracyResult:
    horizons: list[HorizonScorecard] = field(default_factory=list)
    sectors: list[SectorHorizonStat] = field(default_factory=list)


def compute_backtest_accuracy(
    *,
    horizons: tuple[int, ...] = FORWARD_HORIZONS_DAYS,
    min_sector_observations: int = 15,
    data_provider: DataProvider | None = None,
) -> BacktestAccuracyResult:
    """Compute the verdict→forward-return parity scorecard.

    Args:
        horizons: forward horizons (calendar days) to evaluate.
        min_sector_observations: minimum evaluable observations for a
            (sector, horizon) cell to be published.
        data_provider: callable(horizons) -> iterable of observation
            dicts. Defaults to the production DB read.

    Returns:
        BacktestAccuracyResult — empty (but well-shaped) on empty input.
    """
    provider = data_provider or _default_data_provider
    try:
        all_rows = list(provider(tuple(horizons)))
    except Exception as exc:
        logger.warning("backtest_accuracy: provider raised (%s) — empty", exc)
        # Degrade to well-shaped empty horizon cards (one per requested
        # horizon) rather than a bare result — consumers iterate the
        # horizon list and need each window at observation_count 0
        # instead of a structurally different empty shape.
        return BacktestAccuracyResult(
            horizons=[_build_horizon_scorecard(h, []) for h in horizons],
            sectors=[],
        )

    # Partition rows by horizon.
    by_horizon: dict[int, list[dict]] = {h: [] for h in horizons}
    for r in all_rows:
        h = r.get("horizon_days")
        try:
            h = int(h)
        except (TypeError, ValueError):
            continue
        if h in by_horizon:
            by_horizon[h].append(r)

    horizon_cards: list[HorizonScorecard] = []
    sector_stats: list[SectorHorizonStat] = []
    for h in horizons:
        rows = by_horizon.get(h, [])
        horizon_cards.append(_build_horizon_scorecard(h, rows))
        sector_stats.extend(
            _build_sector_stats(h, rows, min_sector_observations=min_sector_observations)
        )

    return BacktestAccuracyResult(horizons=horizon_cards, sectors=sector_stats)


# ─────────────────────────────────────────────────────────────────
# JSON projection
# ─────────────────────────────────────────────────────────────────
EPOCH_POLICY_TEXT = (
    "Only fair_value_history rows dated on or after the "
    f"{QUARANTINE_EPOCH_DATE} manifest event (v_init_2026_05_22) "
    "contribute. Pre-manifest-epoch rows cannot be corroborated and are "
    "excluded by construction."
)

POWER_NOTE_TEXT = (
    "Forward returns require price history to mature past each horizon. "
    "Horizons and buckets with low observation counts are flagged "
    "(low_n) — their medians are not yet statistically meaningful and "
    "fill in as clean history accrues."
)


def to_dict(
    result: BacktestAccuracyResult,
    *,
    horizons: tuple[int, ...] = FORWARD_HORIZONS_DAYS,
    min_sector_observations: int = 15,
) -> dict:
    """Project the result into the JSON-safe response shape."""
    result = result or BacktestAccuracyResult()
    horizons_payload = [asdict(h) for h in result.horizons]
    sectors_payload = [asdict(s) for s in result.sectors]
    total_obs = sum(h.get("observation_count", 0) for h in horizons_payload)
    return {
        "horizons": horizons_payload,
        "sectors": sectors_payload,
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "quarantine_epoch_date": QUARANTINE_EPOCH_DATE,
            "epoch_policy": EPOCH_POLICY_TEXT,
            "statistical_power_note": POWER_NOTE_TEXT,
            "forward_horizons_days": list(horizons),
            "min_sector_observations": int(min_sector_observations),
            "low_n_threshold": LOW_N_THRESHOLD,
            "total_evaluable_observations": int(total_obs),
            "bands": list(ALL_BANDS),
            "direction_bands": {
                "below_threshold_pct": DIR_BELOW_THRESHOLD,
                "above_threshold_pct": DIR_ABOVE_THRESHOLD,
                "near_band_pct": DIR_NEAR_BAND,
            },
        },
    }
