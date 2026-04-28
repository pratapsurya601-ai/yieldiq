"""
backend.services.units — centralised unit canonicaliser.

Single source of truth for "which API field is in which unit" and how to
move between them. This module is purely **additive**: existing helpers
like ``_normalize_pct`` (in ``backend/services/analysis/utils.py`` and
``backend/services/analytical_notes.py``) and
``_normalize_pct_to_decimal`` (in ``data/collector.py``) keep their
exact heuristics — this module just adds:

  * Hint-first variants so callers that *know* the input shape can be
    explicit (``hint="decimal"``, ``hint="percent"``, ``hint="raw_inr"``,
    ``hint="crore"``, ``hint="lakh"``).
  * Boundary-warning logging so values close to the heuristic threshold
    surface in DEBUG/WARNING streams. Those are exactly the rows that
    silently flip when the threshold shifts (the GRASIM/window ±5 → ±1
    bug class).
  * Lightweight ``assert_percent`` / ``assert_decimal`` invariants
    callers can sprinkle in without changing values.

Heuristic-only behaviour is preserved when ``hint=None`` so this module
can be dropped in front of every existing call-site without changing
canary FV/screener output. See ``docs/units_canonical_reference.md`` for
the field-by-field unit map.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

_logger = logging.getLogger(__name__)

# ─── thresholds (kept aligned with existing helpers) ────────────────
# `_normalize_pct` in analysis/utils.py treats |v| < 1 as decimal and
# |v| >= 1 as percent. The previous bug used (-5, 5) which double-
# multiplied small percent values. We define the threshold once here
# so future changes are reviewable in one place.
PCT_DECIMAL_BOUND = 1.0  # |v| < 1 → decimal, |v| >= 1 → percent
PCT_BOUNDARY_BAND = 0.05  # values within 5% of the bound are "ambiguous"

# Crore detection: any amount > 1e10 (₹1,000 crore) is unmistakably
# raw-INR-already (idempotency guard in analysis/db.py::_convert_row_to_inr).
RAW_INR_DOUBLE_CONVERT_GUARD = 1e10
ONE_CRORE = 1e7
ONE_LAKH = 1e5

_VALID_HINTS = {"decimal", "percent", "raw_inr", "crore", "lakh"}


# ─── primitives ─────────────────────────────────────────────────────


def _coerce_float(v: Any) -> Optional[float]:
    """Best-effort float coercion that returns None for NaN/inf/None/junk."""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def _check_hint(hint: Optional[str]) -> Optional[str]:
    if hint is None:
        return None
    if hint not in _VALID_HINTS:
        raise ValueError(
            f"unknown unit hint {hint!r}; expected one of {sorted(_VALID_HINTS)}"
        )
    return hint


def _near_boundary(v: float) -> bool:
    """True when |v| is within PCT_BOUNDARY_BAND of PCT_DECIMAL_BOUND.

    Boundary values flip class when the threshold shifts. Logging them
    at WARNING gives operators a way to discover misclassifications
    before they corrupt downstream metrics.
    """
    return abs(abs(v) - PCT_DECIMAL_BOUND) <= PCT_BOUNDARY_BAND


# ─── percent / decimal canonicalisation ─────────────────────────────


def to_percent(value: Any, hint: Optional[str] = None,
               name: str = "value") -> Optional[float]:
    """Return ``value`` in **percent** form (23.5 means 23.5%).

    Behaviour matches ``_normalize_pct`` in analysis/utils.py when
    ``hint`` is None — kept identical so existing callers can be
    migrated incrementally without changing canary output.

    ``hint``:
      * ``"decimal"`` — caller knows the input is decimal (0.235);
        always multiply by 100.
      * ``"percent"`` — caller knows the input is already percent
        (23.5); pass through.
      * None — heuristic (|v| < 1 ⇒ decimal, else percent).
    """
    _check_hint(hint)
    v = _coerce_float(value)
    if v is None:
        return None
    if v == 0:
        return 0.0

    if hint == "decimal":
        out = round(v * 100.0, 2)
        _logger.debug("normalize_pct[%s]: hint=decimal v=%g -> %g%%", name, v, out)
        return out
    if hint == "percent":
        _logger.debug("normalize_pct[%s]: hint=percent v=%g (passthrough)", name, v)
        return round(v, 2)

    # heuristic path
    if _near_boundary(v):
        _logger.warning(
            "normalize_pct[%s]: v=%g within %g of decimal/percent boundary "
            "%g — classification may be wrong",
            name, v, PCT_BOUNDARY_BAND, PCT_DECIMAL_BOUND,
        )
    if -PCT_DECIMAL_BOUND < v < PCT_DECIMAL_BOUND:
        out = round(v * 100.0, 2)
        _logger.debug(
            "normalize_pct[%s]: detected decimal (v=%g) -> %g%%", name, v, out,
        )
        return out
    _logger.debug(
        "normalize_pct[%s]: detected percent (v=%g, passthrough)", name, v,
    )
    return round(v, 2)


def to_decimal(value: Any, hint: Optional[str] = None,
               name: str = "value") -> Optional[float]:
    """Return ``value`` in **decimal** form (0.235 means 23.5%).

    Mirrors ``to_percent`` but yields the decimal representation.

    ``hint``:
      * ``"decimal"`` — pass through.
      * ``"percent"`` — divide by 100.
      * None — heuristic (|v| < 1 ⇒ already decimal, else percent).
    """
    _check_hint(hint)
    v = _coerce_float(value)
    if v is None:
        return None
    if v == 0:
        return 0.0

    if hint == "decimal":
        _logger.debug("to_decimal[%s]: hint=decimal v=%g (passthrough)", name, v)
        return v
    if hint == "percent":
        out = v / 100.0
        _logger.debug("to_decimal[%s]: hint=percent v=%g -> %g", name, v, out)
        return out

    if _near_boundary(v):
        _logger.warning(
            "to_decimal[%s]: v=%g within %g of decimal/percent boundary",
            name, v, PCT_BOUNDARY_BAND,
        )
    if -PCT_DECIMAL_BOUND < v < PCT_DECIMAL_BOUND:
        _logger.debug("to_decimal[%s]: detected decimal (v=%g)", name, v)
        return v
    out = v / 100.0
    _logger.debug("to_decimal[%s]: detected percent (v=%g) -> %g", name, v, out)
    return out


# ─── INR / crore / lakh ─────────────────────────────────────────────


def to_inr_crore(value: Any, hint: Optional[str] = None,
                 name: str = "value") -> Optional[float]:
    """Return a monetary value in **₹ crore**.

    ``hint``:
      * ``"crore"`` — already in crore; pass through.
      * ``"raw_inr"`` — raw INR; divide by 1e7.
      * ``"lakh"`` — divide by 100 (1 crore = 100 lakh).
      * None — heuristic: any value > RAW_INR_DOUBLE_CONVERT_GUARD
        (₹1,000 crore = 1e10) is treated as raw-INR-already, matching
        the long-standing idempotency guard in
        ``backend/services/analysis/db.py::_convert_row_to_inr``.
        Smaller values are assumed to be already-crore.
    """
    _check_hint(hint)
    v = _coerce_float(value)
    if v is None:
        return None

    if hint == "crore":
        return v
    if hint == "raw_inr":
        return v / ONE_CRORE
    if hint == "lakh":
        return v / 100.0

    if abs(v) > RAW_INR_DOUBLE_CONVERT_GUARD:
        out = v / ONE_CRORE
        _logger.debug(
            "to_inr_crore[%s]: detected raw_inr (v=%.3e) -> %.3f Cr",
            name, v, out,
        )
        return out
    _logger.debug(
        "to_inr_crore[%s]: detected crore-already (v=%g)", name, v,
    )
    return v


# ─── invariants ─────────────────────────────────────────────────────


def assert_percent(value: Any, name: str = "value") -> Optional[float]:
    """Soft assertion: log a WARNING when ``value`` looks like a decimal
    but the caller claims it is a percent.

    Returns the coerced float (or None) — never raises in production.
    The goal is to surface double-normalisation bugs in logs without
    breaking running pipelines. Callers that want a hard check can
    wrap with ``assert``.
    """
    v = _coerce_float(value)
    if v is None or v == 0:
        return v
    if -PCT_DECIMAL_BOUND < v < PCT_DECIMAL_BOUND:
        _logger.warning(
            "assert_percent[%s]: v=%g looks like a decimal — possible "
            "missed normalisation upstream", name, v,
        )
    return v


def assert_decimal(value: Any, name: str = "value") -> Optional[float]:
    """Soft assertion: log a WARNING when ``value`` looks like a percent
    but the caller claims it is a decimal.

    Mirror of :func:`assert_percent` for the decimal direction.
    """
    v = _coerce_float(value)
    if v is None or v == 0:
        return v
    if abs(v) >= PCT_DECIMAL_BOUND:
        _logger.warning(
            "assert_decimal[%s]: v=%g looks like a percent — possible "
            "double normalisation downstream", name, v,
        )
    return v


# ─── double-normalisation sentinel ──────────────────────────────────


_NORMALISED_FLAG = "_normalized_units"


def mark_normalised(obj: dict, field: str) -> None:
    """Mark ``field`` of a dict-like ``obj`` as already-normalised.

    Downstream consumers can call :func:`is_normalised` to detect a
    double-conversion attempt. We attach a set under
    ``obj[_NORMALISED_FLAG]`` rather than mutating individual values so
    JSON-serialisable output is unaffected unless the caller
    explicitly serialises the sentinel.
    """
    if not isinstance(obj, dict):
        return
    flags = obj.get(_NORMALISED_FLAG)
    if not isinstance(flags, set):
        flags = set(flags) if flags else set()
        obj[_NORMALISED_FLAG] = flags
    flags.add(field)


def is_normalised(obj: Any, field: str) -> bool:
    """True iff :func:`mark_normalised` was called on ``obj`` for ``field``."""
    if not isinstance(obj, dict):
        return False
    flags = obj.get(_NORMALISED_FLAG)
    if isinstance(flags, (set, frozenset, list, tuple)):
        return field in flags
    return False


__all__ = [
    "PCT_DECIMAL_BOUND",
    "PCT_BOUNDARY_BAND",
    "RAW_INR_DOUBLE_CONVERT_GUARD",
    "ONE_CRORE",
    "ONE_LAKH",
    "to_percent",
    "to_decimal",
    "to_inr_crore",
    "assert_percent",
    "assert_decimal",
    "mark_normalised",
    "is_normalised",
]
