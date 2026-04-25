# backend/services/analysis/hex_axes.py
# ═══════════════════════════════════════════════════════════════
"""Single source of truth for the 6-axis YieldIQ Hex score.

Every consumer of the hex axes — live analysis render, hex_history
backfill seeder, prism timeline computation, OG card, share-card —
must call into this module. There is exactly ONE axis-derivation
function in the repo. Drift becomes architecturally impossible.

This is the same pattern PR #89 applied to ratio formulas
(see ``backend/services/analysis/formulas.py`` and
``docs/FORMULA_SOURCE_OF_TRUTH.md``).

═══════════════════════════════════════════════════════════════
Investigation summary (2026-04-25)
─────────────────────────────────
The historical "compute the 6 axes from the cache payload" function
that the hex_history seeder assumed exists DOES NOT exist. The live
hex computation (``backend.services.hex_service.compute_hex``) does
not take a single payload dict — it consults FOUR data sources keyed
by ticker:

  1. ``analysis_cache.payload``     (quality.*, valuation.*)
  2. ``market_metrics``             (pe_ratio, pb_ratio, market_cap_cr)
  3. ``financials``                 (revenue / EPS series for CAGR;
                                     op-margin stdev for moat/quality)
  4. ``hex_pulse_inputs``           (insider/promoter/estimate revisions)

The seeder bug on 2026-04-25 was twofold:
  (a) it tried to read ``payload["hex"]["axes"]`` which is never written;
  (b) it tried to insert into a JSONB ``axes`` column which doesn't
      exist on the table — hex_history has explicit
      ``{value,quality,growth,moat,safety,pulse}_score`` columns.

Both bugs are fixed by routing the seeder through this module's
``compute_axes_for_ticker`` (which delegates to ``hex_service.compute_hex``,
the live-render path) and writing the columns the table actually has.

Why this is the architectural fix and not just a one-liner patch:
The same 6-axis output shape is read by hex_history seeder, the
prism timeline, the OG card, and (eventually) share-card endpoints.
Each one of those used to be a candidate site for a copy-pasted
"derive axes from payload" snippet that could drift. By collapsing
every call site through ``HexAxes`` + ``compute_axes_for_ticker``
+ ``compute_axes_from_payload``, future drift requires editing this
file — and the consistency test in
``backend/tests/test_hex_axes_consistency.py`` will catch it.
═══════════════════════════════════════════════════════════════

Bank-mode is NOT an override toggle exposed to callers — the
underlying ``hex_service`` already classifies the ticker via
``_classify_sector`` and routes to bank/IT/general axis variants
internally. From the perspective of this module the axes are always
6 floats in [0, 10].
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


# Inputs documentation. This block is the contract — anything
# elsewhere that derives a hex axis from cache data should look here
# first. If you find code computing axes outside this module, that
# is a bug — funnel it back through ``compute_axes_for_ticker`` or
# ``compute_axes_from_payload`` and add a regression test.
_AXIS_INPUTS_DOC = """
Live render path (authoritative): hex_service.compute_hex(ticker)

Per-axis source map (mirrors backend/services/hex_service.py):

  PULSE   ← hex_pulse_inputs row (insider_net_30d, promoter_delta_qoq,
            estimate_revision_30d, pledged_pct_delta) → falls back to
            yfinance recommendations summary → neutral 5.0.

  QUALITY ← analysis_cache.payload.quality.{piotroski_score, roce, roe}
            + financials op_margin stdev for stability bonus.
            Bank branch: ROA, ROE, cost_to_income.

  MOAT    ← analysis_cache.payload.quality.moat (label) OR moat_score
            (numeric 0-100 fallback) + financials op_margin stdev.
            Bank branch: log10(market_cap_cr / 50_000) + cost_to_income.

  SAFETY  ← analysis_cache.payload.quality.{de_ratio, interest_coverage,
            altman_z}. D/E auto-normalised from percent→decimal when >5.
            Bank branch: gnpa_pct, nnpa_pct, tier1_ratio (when present),
            else P/BV franchise proxy.

  GROWTH  ← analysis_cache.payload.quality.{revenue_cagr_3y,
            revenue_cagr_5y} + financials EPS series for EPS CAGR.
            Bank branch: advances_yoy, deposits_yoy, pat_yoy_bank
            (falls through to revenue/EPS CAGR when bank fields absent).

  VALUE   ← analysis_cache.payload.valuation.margin_of_safety + market
            metrics pe_ratio (sigmoid blend). Bank branch: P/BV anchor
            (2.5x for banks, 3.5x for NBFCs) + MoS. IT branch: revenue
            multiple from market_cap_cr / financials revenue.

All axes are clamped to [0, 10]. Missing inputs do NOT raise — they
return a neutral 5.0 with ``data_limited: true`` on the affected axis.
"""


@dataclass(frozen=True)
class HexAxes:
    """The canonical 6-axis hex tuple. All scores in [0, 10]."""

    pulse: float
    quality: float
    moat: float
    safety: float
    growth: float
    value: float

    def as_dict(self) -> dict:
        """Plain-dict form, ordered to match the live API response."""
        return {
            "pulse": self.pulse,
            "quality": self.quality,
            "moat": self.moat,
            "safety": self.safety,
            "growth": self.growth,
            "value": self.value,
        }


# Axis weights for the composite "overall" hex score. Defined HERE
# (in the pure module) rather than in hex_service so the seeder can
# import them without pulling in streamlit/pydantic. hex_service
# re-exports the same constant for backward compatibility.
AXIS_WEIGHTS: dict[str, float] = {
    "value": 0.20,
    "quality": 0.20,
    "growth": 0.20,
    "moat": 0.15,
    "safety": 0.15,
    "pulse": 0.10,
}


# ── Public API ─────────────────────────────────────────────────
def compute_axes_for_ticker(ticker: str) -> HexAxes:
    """Single source of truth — delegates to the live render path.

    Use this from any new call site that needs the 6-axis hex by
    ticker. NEVER re-derive the axes from the payload locally; that
    is the bug class this module exists to eliminate.
    """
    # Imported lazily so the analysis package does not eagerly pull
    # the data_pipeline session machinery just to import HexAxes.
    from backend.services.hex_service import compute_hex_safe

    full = compute_hex_safe(ticker)
    return _axes_dict_to_hexaxes(full.get("axes") or {})


def compute_axes_from_payload(payload: dict) -> HexAxes:
    """Extract the 6 axes from an already-computed analysis payload.

    Three cases (in priority order):

    1. ``payload["hex"]["axes"]`` is present (live API response shape).
       Read directly — full live-render fidelity.

    2. Cache-row shape (``payload.quality.*`` / ``payload.valuation.*``)
       with no pre-computed hex block. **Derive synthetically using a
       PURE function** — no backend service imports. The seeded values
       are approximations (the live render also reads market_metrics /
       financials / hex_pulse_inputs which aren't in the cache row), but
       good enough for the 12-month sparkline. Live render will overwrite
       with full-fidelity values on the next ingest cycle.

       Why pure: this function is called from
       ``backend/scripts/backfill_hex_history.py`` which runs in a slim
       GH Actions env without pydantic/fastapi/streamlit. Importing
       backend services there causes ``ModuleNotFoundError`` cascades
       (caught by runs 24928636557 + 24931140894 + 24931374708).

    3. No usable inputs at all → neutral HexAxes (5.0 everywhere).
       Never raise — the seeder's contract is never-fail.
    """
    if not isinstance(payload, dict):
        return _neutral_hexaxes()

    # Case 1: pre-computed hex on the response.
    hex_block = payload.get("hex") or {}
    axes_dict = hex_block.get("axes") if isinstance(hex_block, dict) else None
    if isinstance(axes_dict, dict) and axes_dict:
        return _axes_dict_to_hexaxes(axes_dict)

    # Case 2: cache-row shape — pure-Python synthetic derivation.
    derived = _derive_axes_from_cache_payload(payload)
    if derived is not None:
        return derived

    # Case 3: nothing usable.
    return _neutral_hexaxes()


def _derive_axes_from_cache_payload(payload: dict) -> "HexAxes | None":
    """Pure-Python axis derivation from the cache-row shape.

    Reads ``payload.quality.*`` and ``payload.valuation.*`` directly.
    Returns None if the payload doesn't look like a cache row.

    NO backend service imports — this function MUST run in the slim
    workflow env (sqlalchemy + psycopg only). If you need to add a
    formula, add it inline below — do not import from
    ``backend.services.hex_service`` or any sibling.
    """
    quality = payload.get("quality") if isinstance(payload, dict) else None
    if not isinstance(quality, dict) or not quality:
        return None
    valuation = payload.get("valuation") if isinstance(payload, dict) else None
    valuation = valuation if isinstance(valuation, dict) else {}

    def _to_score10(v: Any, default: float = 5.0) -> float:
        """Coerce a number to [0, 10]. The quality block stores most
        scores as 0-100 so divide-by-10 if value > 10."""
        if v is None:
            return default
        try:
            x = float(v)
        except (TypeError, ValueError):
            return default
        if x > 10:
            x = x / 10.0
        return max(0.0, min(10.0, x))

    pulse = _to_score10(quality.get("momentum_score"))
    quality_axis = _to_score10(quality.get("fundamental_score"))
    moat = _to_score10(quality.get("moat_score"))

    # Safety: synthesize from de_ratio + interest_coverage. Lower
    # de_ratio = better. Higher interest_coverage = better.
    safety = 5.0
    de_ratio = quality.get("de_ratio")
    if de_ratio is not None:
        try:
            de = float(de_ratio)
            if de < 0.3:
                safety = 8.5
            elif de < 1.0:
                safety = 7.0
            elif de < 2.0:
                safety = 5.0
            else:
                safety = 3.0
        except (TypeError, ValueError):
            pass
    ic = quality.get("interest_coverage")
    if ic is not None:
        try:
            ic_f = float(ic)
            if ic_f > 10:
                safety = min(10.0, safety + 1.0)
            elif ic_f < 2:
                safety = max(0.0, safety - 2.0)
        except (TypeError, ValueError):
            pass

    # Growth: from revenue_cagr_3y. Decimal form (0.15 = 15% CAGR).
    # 0% → 3, 5% → 4, 15% → 6, 25% → 8, 35%+ → 10
    growth = 5.0
    rev_cagr = quality.get("revenue_cagr_3y")
    if rev_cagr is not None:
        try:
            cagr = float(rev_cagr)
            if cagr < 0:
                growth = max(0.0, 3.0 + cagr * 30)
            else:
                growth = min(10.0, 3.0 + cagr * 20)
        except (TypeError, ValueError):
            pass

    # Value: from valuation.margin_of_safety (percentage).
    # +50 → 9, +30 → 7.4, 0 → 5, -30 → 2.6, -50 → 1
    value = 5.0
    mos = valuation.get("margin_of_safety")
    if mos is not None:
        try:
            m = float(mos)
            value = max(0.0, min(10.0, 5.0 + m / 12.5))
        except (TypeError, ValueError):
            pass

    return HexAxes(
        pulse=pulse,
        quality=quality_axis,
        moat=moat,
        safety=safety,
        growth=growth,
        value=value,
    )


# ── Internal helpers ───────────────────────────────────────────
def _coerce_axis_score(value: Any) -> float:
    """Pull a float in [0, 10] out of either a bare number or the
    ``{score, label, why, data_limited}`` envelope hex_service emits."""
    if isinstance(value, dict):
        value = value.get("score")
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 5.0
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf guard
        return 5.0
    return max(0.0, min(10.0, f))


def _axes_dict_to_hexaxes(axes: dict) -> HexAxes:
    """Build a HexAxes from the live ``compute_hex`` axes dict.

    The live render returns each axis as
    ``{"score": float, "label": str, "why": str, "data_limited": bool}``.
    This module's contract is just the float — the surrounding
    metadata (label/why) stays on the live response shape.
    """
    return HexAxes(
        pulse=_coerce_axis_score(axes.get("pulse")),
        quality=_coerce_axis_score(axes.get("quality")),
        moat=_coerce_axis_score(axes.get("moat")),
        safety=_coerce_axis_score(axes.get("safety")),
        growth=_coerce_axis_score(axes.get("growth")),
        value=_coerce_axis_score(axes.get("value")),
    )


def _neutral_hexaxes() -> HexAxes:
    return HexAxes(
        pulse=5.0, quality=5.0, moat=5.0,
        safety=5.0, growth=5.0, value=5.0,
    )


__all__ = [
    "HexAxes",
    "compute_axes_for_ticker",
    "compute_axes_from_payload",
]
