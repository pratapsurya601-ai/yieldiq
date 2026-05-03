# backend/services/fv_accuracy_service.py
# ═══════════════════════════════════════════════════════════════
# Fair-value accuracy service — pure compute layer for the
# /methodology/accuracy backtest dashboard.
#
# Distinct from backtest_service.py (which backtests *screens* of
# tickers over recent years). This module backtests the model's
# fair-value *calls themselves*: for each (ticker, date_t) row in
# fair_value_history, did the price 12 months later move in the
# direction we predicted?
#
# All functions here are pure: they take an iterable of "snapshot
# rows" (dicts with ticker, fv_then, price_then, price_now, mos_pct,
# verdict) and return JSON-serializable summary dicts. The router
# layer is responsible for the SQL that produces those rows.
#
# SEBI-compliant vocabulary
# ─────────────────────────
# The fair_value_history table uses the legacy verdicts
# "undervalued", "fairly_valued", "overvalued" (the model still emits
# those internally). For the public dashboard we map them to the
# SEBI-safe equivalents:
#
#     undervalued    → below_fair_value
#     fairly_valued  → near_fair_value
#     overvalued     → above_fair_value
#
# Never expose "undervalued"/"overvalued" in any field name or value
# returned by these functions.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import math
from typing import Iterable, Optional


# ─────────────────────────────────────────────────────────────────
# Vocabulary mapping — single source of truth.
# Public-facing band names. Keep in sync with the frontend.
# ─────────────────────────────────────────────────────────────────
BAND_BELOW = "below_fair_value"
BAND_NEAR = "near_fair_value"
BAND_ABOVE = "above_fair_value"

ALL_BANDS = (BAND_BELOW, BAND_NEAR, BAND_ABOVE)

_LEGACY_TO_BAND = {
    "undervalued": BAND_BELOW,
    "fairly_valued": BAND_NEAR,
    "overvalued": BAND_ABOVE,
}

# Direction thresholds (in percent) used to decide whether the
# 12-month forward return matched the verdict's implied direction.
DIR_BELOW_THRESHOLD = 5.0   # below_fair_value → return > +5%
DIR_ABOVE_THRESHOLD = -5.0  # above_fair_value → return < −5%
DIR_NEAR_BAND = 10.0        # near_fair_value → |return| ≤ 10%


def _to_band(verdict: Optional[str]) -> Optional[str]:
    """Map a raw verdict string to its SEBI-safe band name (or None)."""
    if not verdict:
        return None
    v = str(verdict).strip().lower()
    return _LEGACY_TO_BAND.get(v)


def _safe_float(x) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _return_pct(price_then: float, price_now: float) -> Optional[float]:
    if price_then <= 0:
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


# ─────────────────────────────────────────────────────────────────
# 1) Directional accuracy
# ─────────────────────────────────────────────────────────────────
def compute_directional_accuracy(rows: Iterable[dict]) -> dict:
    """For each (ticker, T-12mo verdict) row, did the 12-month
    forward return move in the predicted direction?

    A row is directionally CORRECT iff:
      - band = below_fair_value AND return > +5%
      - band = above_fair_value AND return < −5%
      - band = near_fair_value AND |return| ≤ 10%

    Args:
        rows: iterable of dicts with at minimum
              {price_then, price_now, verdict}.
              Extra keys are ignored.

    Returns:
        {
          "total": int,                # rows where direction could be evaluated
          "directional_correct": int,
          "hit_rate": float | None,    # 0..1
          "by_band": {                 # per-band hit rate
            "below_fair_value": {"total": N, "correct": M, "hit_rate": M/N},
            "near_fair_value":  {...},
            "above_fair_value": {...},
          },
        }
    """
    per_band = {b: {"total": 0, "correct": 0} for b in ALL_BANDS}
    total = 0
    correct = 0

    for row in rows:
        band = _to_band(row.get("verdict"))
        if band is None:
            continue
        pt = _safe_float(row.get("price_then"))
        pn = _safe_float(row.get("price_now"))
        if pt is None or pn is None:
            continue
        ret = _return_pct(pt, pn)
        if ret is None:
            continue

        is_correct = (
            (band == BAND_BELOW and ret > DIR_BELOW_THRESHOLD)
            or (band == BAND_ABOVE and ret < DIR_ABOVE_THRESHOLD)
            or (band == BAND_NEAR and abs(ret) <= DIR_NEAR_BAND)
        )

        per_band[band]["total"] += 1
        total += 1
        if is_correct:
            per_band[band]["correct"] += 1
            correct += 1

    by_band: dict[str, dict] = {}
    for b, agg in per_band.items():
        n = agg["total"]
        by_band[b] = {
            "total": n,
            "correct": agg["correct"],
            "hit_rate": round(agg["correct"] / n, 4) if n else None,
        }

    return {
        "total": total,
        "directional_correct": correct,
        "hit_rate": round(correct / total, 4) if total else None,
        "by_band": by_band,
    }


# ─────────────────────────────────────────────────────────────────
# 2) Return attribution
# ─────────────────────────────────────────────────────────────────
def compute_return_attribution(rows: Iterable[dict]) -> dict:
    """Mean and median 12-month forward return per verdict band.

    A model that adds value should show:
        below_fair_value > near_fair_value > above_fair_value

    Returns:
        {
          "by_band": {
            "below_fair_value": {"count": N, "mean_return_pct": x, "median_return_pct": y},
            ...
          },
          "overall": {"count": N, "mean_return_pct": x, "median_return_pct": y},
          "monotonic": bool | None,   # True iff mean(below) > mean(near) > mean(above)
        }
    """
    bucket: dict[str, list[float]] = {b: [] for b in ALL_BANDS}
    overall: list[float] = []

    for row in rows:
        band = _to_band(row.get("verdict"))
        pt = _safe_float(row.get("price_then"))
        pn = _safe_float(row.get("price_now"))
        if pt is None or pn is None:
            continue
        ret = _return_pct(pt, pn)
        if ret is None:
            continue
        overall.append(ret)
        if band is not None:
            bucket[band].append(ret)

    by_band: dict[str, dict] = {}
    for b, xs in bucket.items():
        by_band[b] = {
            "count": len(xs),
            "mean_return_pct": _mean(xs),
            "median_return_pct": _median(xs),
        }

    # Monotonic ordering check — only meaningful if all three buckets
    # have data.
    monotonic: Optional[bool] = None
    means = [by_band[b]["mean_return_pct"] for b in (BAND_BELOW, BAND_NEAR, BAND_ABOVE)]
    if all(m is not None for m in means):
        monotonic = means[0] > means[1] > means[2]  # type: ignore[operator]

    return {
        "by_band": by_band,
        "overall": {
            "count": len(overall),
            "mean_return_pct": _mean(overall),
            "median_return_pct": _median(overall),
        },
        "monotonic": monotonic,
    }


# ─────────────────────────────────────────────────────────────────
# 3) Calibration curve
# ─────────────────────────────────────────────────────────────────
# MoS bucket edges in percent. A row with mos_pct = -50 falls into the
# "<= -40" bucket; mos_pct = +30 falls into "+20 to +40"; etc.
# Buckets are closed-left, open-right except the last one.
CALIBRATION_BUCKETS: list[tuple[float, float, str]] = [
    (-math.inf, -40.0, "<= -40%"),
    (-40.0, -20.0, "-40% to -20%"),
    (-20.0, 0.0, "-20% to 0%"),
    (0.0, 20.0, "0% to +20%"),
    (20.0, 40.0, "+20% to +40%"),
    (40.0, math.inf, ">= +40%"),
]


def _bucket_for_mos(mos: float) -> Optional[str]:
    for lo, hi, label in CALIBRATION_BUCKETS:
        if lo <= mos < hi:
            return label
    # Right edge of the last bucket — include +inf in ">= +40%".
    if mos >= CALIBRATION_BUCKETS[-1][0]:
        return CALIBRATION_BUCKETS[-1][2]
    return None


def compute_calibration_curve(rows: Iterable[dict]) -> dict:
    """For each MoS bucket at T-12mo, what was the average actual
    12-month return?

    A well-calibrated model produces a roughly monotonic curve:
    higher MoS at T-12mo → higher mean return over the next 12mo.

    Args:
        rows: iterable of dicts with {mos_pct, price_then, price_now}.

    Returns:
        {
          "buckets": [
            {"label": "<= -40%", "mos_midpoint_pct": -50,
             "count": N, "mean_return_pct": x, "median_return_pct": y},
            ...
          ],
          "monotonic": bool | None,   # True iff mean increases across
                                      # *populated* buckets in order.
        }
    """
    grouped: dict[str, list[float]] = {label: [] for _, _, label in CALIBRATION_BUCKETS}

    for row in rows:
        mos = _safe_float(row.get("mos_pct"))
        if mos is None:
            continue
        pt = _safe_float(row.get("price_then"))
        pn = _safe_float(row.get("price_now"))
        if pt is None or pn is None:
            continue
        ret = _return_pct(pt, pn)
        if ret is None:
            continue
        label = _bucket_for_mos(mos)
        if label is not None:
            grouped[label].append(ret)

    # Midpoints for charting (the calibration scatter plot uses these
    # as the x-axis). For unbounded buckets we use a synthetic midpoint
    # at ±50 so they still plot.
    midpoints = {
        "<= -40%": -50.0,
        "-40% to -20%": -30.0,
        "-20% to 0%": -10.0,
        "0% to +20%": 10.0,
        "+20% to +40%": 30.0,
        ">= +40%": 50.0,
    }

    bucket_dicts: list[dict] = []
    for _, _, label in CALIBRATION_BUCKETS:
        xs = grouped[label]
        bucket_dicts.append(
            {
                "label": label,
                "mos_midpoint_pct": midpoints[label],
                "count": len(xs),
                "mean_return_pct": _mean(xs),
                "median_return_pct": _median(xs),
            }
        )

    populated = [b for b in bucket_dicts if b["count"] > 0]
    monotonic: Optional[bool] = None
    if len(populated) >= 2:
        means = [b["mean_return_pct"] for b in populated]
        monotonic = all(
            means[i] is not None and means[i + 1] is not None
            and means[i] < means[i + 1]  # type: ignore[operator]
            for i in range(len(means) - 1)
        )

    return {
        "buckets": bucket_dicts,
        "monotonic": monotonic,
    }
