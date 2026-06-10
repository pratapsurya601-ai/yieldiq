"""Inflation-regime DCF adjustment service (2026-06-10).

═══════════════════════════════════════════════════════════════
Why this exists
─────────────────────────────────────────────────────────────────────
YieldIQ's primary DCF runs in nominal terms — nominal WACC, nominal
revenue/FCF growth, nominal terminal growth. At India's long-run CPI
of ~5% this is fine: the inflation premium baked into the discount
rate cancels the inflation contribution to nominal cash-flow growth,
so present values are roughly invariant.

That invariance BREAKS at the tails:

  - When CPI is high (6-8%) and the DCF was calibrated with assumed
    growth that lags the inflation impulse, projected nominal cash
    flows under-grow relative to the discount rate — FV collapses.
  - When CPI is extreme (>8%) the spread between nominal WACC and
    nominal growth is so wide that the terminal-value approximation
    (FCF_{n+1} / (WACC - g)) becomes numerically unstable and the
    Gordon growth model mis-prices the going concern.
  - When CPI is anomalously low (<4%) the opposite happens — nominal
    growth assumptions stale at the historical-CPI baseline overshoot
    the actual cash-flow trajectory.

The fix is the textbook one (Damodaran "Valuing Distressed Companies"
ch. 7): in regimes where headline inflation diverges materially from
the inflation baked into the discount rate, recompute the DCF in
REAL terms using:

    real_wacc   = nominal_wacc   - cpi
    real_growth = nominal_growth - cpi
    real_terminal_growth = nominal_terminal_growth - cpi  (floored)

The real-terms FV is then compared to the nominal-terms FV. If they
diverge by more than a configured threshold (default 10%), the
model_note flips from "use_nominal" to "use_real" or "blended".

Caller contract
───────────────
``compute_regime_adjustment(nominal_dcf, base_fcf, nominal_wacc,
nominal_growth, terminal_growth, current_cpi, shares, net_debt)``

  Returns an InflationRegimeResult dataclass. The frontend renders
  the nominal-vs-real comparison panel; the engine remains free to
  ignore the model_note (this service is advisory by default —
  it does NOT mutate the primary FV unless the engine explicitly
  opts into the "use_real" pathway).

Confidence
──────────
This is a sanity-check overlay, not a primary engine. It surfaces
distortion that the operator and the reader can both see. The
model_note field is a CONSERVATIVE hint, not an automated
override — flipping the primary FV to real-terms requires the
engine to read this block and explicitly decide.

Hard rules honoured
───────────────────
* Pure-function core (testable without DB or network)
* Field-additive on AnalysisResponse — None on legacy payloads
* No CACHE_VERSION bump — additive engine, doesn't change shape
  of existing analyses that already have FV
* SEBI-safe: no advice vocabulary, just nominal-vs-real numbers
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Optional

logger = logging.getLogger("yieldiq.inflation_regime")


# ── Regime classification thresholds ────────────────────────────
# India CPI baseline ~5% (RBI inflation target band 4±2). Thresholds
# below pick out tails where nominal-DCF distortion materially exceeds
# noise.
REGIME_LOW_MAX = 4.0        # < this is "low"
REGIME_NORMAL_MAX = 6.0     # < this is "normal"
REGIME_HIGH_MAX = 8.0       # < this is "high"; ≥ is "extreme"

# Default DCF horizon used by the real-terms recompute. Mirrors the
# 5-year explicit horizon used by the primary DCF engine.
DEFAULT_HORIZON_YEARS = 5

# When real_growth - real_terminal_growth - 0.01 (= WACC-spread floor)
# would push the terminal denominator below this minimum spread, we
# clamp. Mirrors the engine's universal (WACC - g) > 1% floor.
MIN_TERMINAL_SPREAD = 0.01

# Distortion threshold — recommend real-terms switch when |nominal -
# real| / |nominal| exceeds this fraction.
DISTORTION_USE_REAL_FRACTION = 0.20      # >= 20% gap -> recommend real
DISTORTION_BLEND_FRACTION = 0.10         # 10–20% gap -> recommend blend


# ─────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────
@dataclass
class InflationRegimeResult:
    """Output of the inflation-regime adjustment overlay.

    Fields
    ──────
    current_cpi_pct
        The headline CPI (year-on-year, percent) the recompute used.
    regime
        One of "low", "normal", "high", "extreme" — see
        ``classify_inflation_regime``.
    real_wacc_pct
        Real-terms discount rate = nominal_wacc - cpi.
    real_growth_pct
        Real-terms FCF growth = nominal_growth - cpi.
    nominal_fv
        The nominal-terms fair value caller passed in. Echoed back for
        the frontend comparison panel. None when caller did not supply
        a nominal FV.
    real_terms_fv
        The recomputed fair value using real_wacc + real_growth. None
        when the recompute is mathematically degenerate (negative real
        rate, terminal spread below floor, base_fcf<=0).
    fv_distortion_pct
        Signed percentage gap: (real_fv - nominal_fv) / nominal_fv * 100.
        Positive means real-terms FV is higher (nominal under-prices
        in this regime). 0.0 when either side is missing.
    model_note
        One of "use_nominal", "use_real", "blended". Advisory only —
        the engine does NOT automatically switch unless it chooses to.
    """
    current_cpi_pct: float
    regime: str
    real_wacc_pct: float
    real_growth_pct: float
    nominal_fv: Optional[float]
    real_terms_fv: Optional[float]
    fv_distortion_pct: float
    model_note: str


# ─────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────
def classify_inflation_regime(cpi_pct: float) -> str:
    """Map headline CPI (percent) onto a regime band.

    <4%  -> "low"
    4–6% -> "normal"
    6–8% -> "high"
    >=8% -> "extreme"

    Non-finite / negative inputs default to "normal" (the baseline
    assumption that the primary DCF is calibrated against).
    """
    try:
        v = float(cpi_pct)
    except (TypeError, ValueError):
        return "normal"
    if not math.isfinite(v) or v < 0:
        return "normal"
    if v < REGIME_LOW_MAX:
        return "low"
    if v < REGIME_NORMAL_MAX:
        return "normal"
    if v < REGIME_HIGH_MAX:
        return "high"
    return "extreme"


def _safe_float(x, default: float = 0.0) -> float:
    """Coerce to a finite float, defaulting on garbage."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v


def compute_real_terms_dcf(
    base_fcf: float,
    nominal_wacc: float,
    nominal_growth: float,
    terminal_growth: float,
    current_cpi: float,
    shares: float,
    net_debt: float,
    *,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
) -> Optional[float]:
    """Recompute a per-share DCF using REAL discount + growth rates.

    All percentage inputs are in PERCENT (not fractions): a 12.5% WACC
    is ``nominal_wacc=12.5``, not 0.125. CPI follows the same
    convention.

    Returns the per-share fair value, or None when the inputs are
    degenerate (real_wacc <= terminal spread floor, shares <= 0,
    base_fcf <= 0).
    """
    bf = _safe_float(base_fcf)
    nw = _safe_float(nominal_wacc)
    ng = _safe_float(nominal_growth)
    tg = _safe_float(terminal_growth)
    cpi = _safe_float(current_cpi)
    sh = _safe_float(shares)
    nd = _safe_float(net_debt)

    if bf <= 0 or sh <= 0:
        return None

    # Convert percent inputs to fractions.
    real_wacc = (nw - cpi) / 100.0
    real_growth = (ng - cpi) / 100.0
    # Terminal growth follows the same real-conversion. In high-CPI
    # regimes nominal terminal growth (e.g. 5%) goes NEGATIVE in real
    # terms when CPI > terminal — which is economically defensible
    # (real economy shrinks), but the Gordon model needs WACC > g, so
    # we let it pass through unclamped here and rely on the spread
    # floor below.
    real_terminal = (tg - cpi) / 100.0

    # Spread floor — Gordon model blows up as (WACC - g) -> 0.
    if (real_wacc - real_terminal) < MIN_TERMINAL_SPREAD:
        # The real-terms model is too distorted to be meaningful here.
        # Return None so the caller renders "not computable in real
        # terms" rather than a hallucinated number.
        return None

    # Real-terms WACC must be positive after the floor; if the floor
    # would push us below 0 the present-value math inverts.
    if real_wacc <= 0:
        return None

    # Project FCF in real terms for ``horizon_years`` then discount
    # plus a terminal value at year H.
    pv_fcfs = 0.0
    fcf = bf
    for t in range(1, int(max(1, horizon_years)) + 1):
        fcf = fcf * (1.0 + real_growth)
        pv_fcfs += fcf / ((1.0 + real_wacc) ** t)

    # Terminal value at end of horizon, then discount one extra year.
    terminal_value = (fcf * (1.0 + real_terminal)) / (real_wacc - real_terminal)
    pv_terminal = terminal_value / ((1.0 + real_wacc) ** horizon_years)

    enterprise_value = pv_fcfs + pv_terminal
    equity_value = enterprise_value - nd
    if equity_value <= 0:
        return None
    per_share = equity_value / sh
    if not math.isfinite(per_share) or per_share <= 0:
        return None
    return per_share


def _model_note_from_distortion(distortion_pct: float, regime: str) -> str:
    """Map the |nominal - real| / nominal gap onto an advisory tag.

    The model_note also factors regime: in "low" / "normal" regimes
    a 25% gap is more likely to reflect a numerical edge-case than a
    real distortion, so we hold the line at "use_nominal" unless the
    regime itself is high/extreme.
    """
    abs_pct = abs(distortion_pct)
    if regime in ("high", "extreme"):
        if abs_pct >= DISTORTION_USE_REAL_FRACTION * 100.0:
            return "use_real"
        if abs_pct >= DISTORTION_BLEND_FRACTION * 100.0:
            return "blended"
    # Low / normal regimes: nominal stays canonical regardless of gap.
    return "use_nominal"


def compute_regime_adjustment(
    nominal_dcf: Optional[float],
    base_fcf: float,
    nominal_wacc: float,
    nominal_growth: float,
    terminal_growth: float,
    current_cpi: float,
    shares: float,
    net_debt: float,
    *,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
) -> InflationRegimeResult:
    """Build the full inflation-regime overlay result.

    ``nominal_dcf`` is the per-share fair value that the primary
    nominal DCF produced (caller passes it in; we don't recompute it
    here — keeping the service pure). If None, the distortion gap is
    reported as 0.0 and the model_note defaults to "use_nominal".
    """
    cpi = _safe_float(current_cpi)
    regime = classify_inflation_regime(cpi)
    nw = _safe_float(nominal_wacc)
    ng = _safe_float(nominal_growth)
    real_wacc_pct = nw - cpi
    real_growth_pct = ng - cpi

    real_fv = compute_real_terms_dcf(
        base_fcf=base_fcf,
        nominal_wacc=nominal_wacc,
        nominal_growth=nominal_growth,
        terminal_growth=terminal_growth,
        current_cpi=current_cpi,
        shares=shares,
        net_debt=net_debt,
        horizon_years=horizon_years,
    )

    nominal_clean: Optional[float] = None
    if nominal_dcf is not None:
        nf = _safe_float(nominal_dcf, default=float("nan"))
        if math.isfinite(nf) and nf > 0:
            nominal_clean = nf

    distortion_pct = 0.0
    if nominal_clean is not None and real_fv is not None and nominal_clean > 0:
        distortion_pct = (real_fv - nominal_clean) / nominal_clean * 100.0
        if not math.isfinite(distortion_pct):
            distortion_pct = 0.0

    model_note = _model_note_from_distortion(distortion_pct, regime)

    # Guard: if real_fv is None we cannot recommend "use_real" no
    # matter how distorted nominal looks. Fall back to "use_nominal".
    if real_fv is None and model_note == "use_real":
        model_note = "use_nominal"

    return InflationRegimeResult(
        current_cpi_pct=round(cpi, 2),
        regime=regime,
        real_wacc_pct=round(real_wacc_pct, 2),
        real_growth_pct=round(real_growth_pct, 2),
        nominal_fv=round(nominal_clean, 2) if nominal_clean is not None else None,
        real_terms_fv=round(real_fv, 2) if real_fv is not None else None,
        fv_distortion_pct=round(distortion_pct, 2),
        model_note=model_note,
    )


def to_dict(result: InflationRegimeResult) -> dict:
    """Serialise an InflationRegimeResult to a JSON-friendly dict.

    Round-trip safe: every field is either a primitive float / str /
    None. Kept as a free function (not a method) so the dataclass
    stays a plain value type and so callers can dict-ify legacy
    payloads built from raw fields.
    """
    if result is None:
        return {}
    return asdict(result)
