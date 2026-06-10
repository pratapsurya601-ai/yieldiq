# backend/services/composite_iv_service.py
# ═══════════════════════════════════════════════════════════════
# Composite Intrinsic Value — weighted average of DCF, peer-relative
# multiples, and Wall Street analyst price target.
#
# T1.1 engine refinement (2026-06-09). Addresses the systematic
# high-side bias documented in the FV cross-check vs AlphaSpread
# (HDFCBANK: YieldIQ DCF ₹1,129 vs AlphaSpread ₹803 — 40% high).
# Surfacing a composite that blends the three independent estimators
# narrows the gap to ~18% without throwing out the DCF signal.
#
# Design choices
# ──────────────
# 1. ADDITIVE. The existing `fair_value` field stays byte-identical
#    (DCF-only). The composite lives on its own field
#    `composite_intrinsic_value`. Cache layout, manifest history, and
#    downstream gates that key on `fair_value` are unchanged.
#
# 2. Weight defaults match the spec — DCF 0.50, Multiples 0.30,
#    Analyst 0.20. When any estimator is None, its weight redistributes
#    pro-rata across the survivors so the active weights always sum
#    to 1.0. A single estimator still produces a composite (weight 1.0).
#
# 3. Holdco branch: pure holding companies have no operating business,
#    so the peer-multiple estimator is meaningless (the cohort PE is
#    set on operating companies, not on pass-through SOTP vehicles).
#    For holdcos we deliberately route to DCF only and document the
#    choice in the `method` field for the frontend explainer. Future
#    T1.4 will swap in SOTP once that engine lands.
#
# 4. Bank branch: when the response's primary engine was already the
#    bank residual-income path (`pb_ratio` valuation_model on banks /
#    NBFCs / insurers), the `dcf_fv` parameter passed in by the caller
#    is the residual-income FV — not a DCF. We tag the components
#    accordingly so the frontend renders "Residual income" rather than
#    "DCF" for that pill. The weighting math is unchanged.
#
# 5. Zero / negative / non-finite inputs are rejected (treated as None).
#    Same posture as multiples_fv.py — a chip cannot rest on garbage.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("yieldiq.composite_iv")


# Default weights — Phase C update (2026-06-10).
#
# Phase A landed five new standalone estimators (DDM, EPV, Three-stage
# DCF, Liquidation, Probability-weighted) and Phase B surfaced them as
# additive fields. Phase C now folds the four estimator-class signals
# (DDM, EPV, Three-stage, Probability-weighted) into the composite IV
# average. Liquidation and Replacement stay OUT of the composite —
# they are FLOOR / Q signals, not estimators of fair value.
#
# Weight design rationale:
#   * DCF stays dominant (0.35) — it is the headline engine, the
#     reverse-DCF anchor, and the only estimator with a full forward-
#     looking cash-flow projection.
#   * Three-stage DCF (0.15) is the largest of the four new slots
#     because it directly corrects the cliff-bias of the two-stage
#     model (HDFCBANK two-stage ₹1,129 vs three-stage ₹706 closes
#     ~75% of the AlphaSpread gap on its own).
#   * Multiples (0.20) and Wall St analyst (0.15) trimmed slightly to
#     make room without dropping their qualitative roles (peer-relative
#     reality check + outside view).
#   * DDM / EPV / Probability-weighted carry small (0.05) weights —
#     each provides a meaningful sanity check on a narrow slice of the
#     opportunity surface (high-payout names for DDM, no-growth anchor
#     for EPV, scenario averaging for prob-weighted) but none are
#     applicable to every ticker.
#
# When some estimators are unavailable, surviving weights redistribute
# pro-rata so the active weights always sum to 1.0 — the same posture
# as the pre-Phase-C three-estimator design.
DEFAULT_WEIGHT_DCF: float = 0.35              # was 0.50
DEFAULT_WEIGHT_MULTIPLES: float = 0.20        # was 0.30
DEFAULT_WEIGHT_ANALYST: float = 0.15          # was 0.20
DEFAULT_WEIGHT_THREE_STAGE: float = 0.15      # NEW Phase C
DEFAULT_WEIGHT_DDM: float = 0.05              # NEW Phase C
DEFAULT_WEIGHT_EPV: float = 0.05              # NEW Phase C
DEFAULT_WEIGHT_PROBABILITY_WEIGHTED: float = 0.05  # NEW Phase C
# Total = 1.00 when all seven are present.

# Extreme divergence flag — when the spread between max and min
# active estimator exceeds 2x of the min, we still emit the composite
# but flag the components dict so the frontend can render a caveat.
EXTREME_DIVERGENCE_RATIO: float = 2.0


@dataclass
class CompositeIVComponent:
    """One contributor to the composite — value + (re-normalized) weight.

    The `weight` value is the FINAL active weight (after pro-rata
    redistribution of any missing-estimator slots), not the default.
    All active components' weights sum to 1.0.
    """

    value: float
    weight: float


@dataclass
class CompositeIV:
    """Composite intrinsic value result.

    Fields
    ──────
    value
        The weighted-average composite, or None when no estimator
        was usable.
    components
        Map of estimator name → component (value + weight). Keys are
        a subset of {"dcf", "multiples", "analyst", "three_stage",
        "ddm", "epv", "probability_weighted"}. The key set documents
        WHICH estimators contributed.
    method
        Short tag describing the composite assembly path. Phase C
        (2026-06-10) extended the tag set; the legacy three-estimator
        names are preserved for back-compat:
          * "composite_dcf_multiples_analyst"  (3 contributors, legacy)
          * "composite_dcf_multiples"          (analyst missing)
          * "composite_dcf_analyst"            (multiples missing)
          * "composite_multiples_analyst"      (DCF missing)
          * "composite_{N}_method"             (4-7 estimators, any
                                                Phase-C engine present)
          * "bank_composite_{N}_method"        (bank variant of above)
          * "<name>_only"                      (single estimator)
          * "holdco_dcf_only"                  (holdco branch)
          * "bank_residual_income"             (bank residual income drove dcf slot)
          * "bank_composite_residual_multiples_analyst" (legacy bank 3-way)
          * "bank_composite_residual_multiples"
          * "bank_composite_residual_analyst"
          * "unavailable"                      (no inputs)
    extreme_divergence
        True when the max/min spread among active components exceeds
        EXTREME_DIVERGENCE_RATIO. Composite is still emitted; the
        frontend uses this to surface an "estimators disagree" caveat.
    """

    value: Optional[float] = None
    components: dict[str, CompositeIVComponent] = field(default_factory=dict)
    method: str = "unavailable"
    extreme_divergence: bool = False


def _coerce_pos_float(v: Any) -> Optional[float]:
    """Float-coerce that drops None, NaN, infinity, and non-positive values.

    Same posture as multiples_fv._coerce_pos_float. Zero / negative
    inputs are dropped because a composite that includes a zero
    pulls the weighted average toward nonsense; non-finite values
    are also dropped because they would propagate through the
    arithmetic and poison every downstream field.
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    if f == float("inf") or f == float("-inf"):
        return None
    if f <= 0:
        return None
    return f


def _is_holdco(stock_kind: Optional[str], ticker: Optional[str]) -> bool:
    """Return True if the ticker should route through the holdco branch.

    Two independent signals — match on either:
      1. `stock_kind` argument carries "holdco" / "holding" (the caller
         has already classified — preferred path).
      2. Ticker is in `HOLDING_COMPANIES` (belt-and-braces fallback so
         callers that pass only `ticker` still route correctly).

    The lazy import isolates the dependency — callers that pass
    `stock_kind` directly never trigger the import.
    """
    if stock_kind:
        kind_lower = str(stock_kind).strip().lower()
        if kind_lower in {"holdco", "holding", "holding_company"}:
            return True
    if ticker:
        try:
            from backend.services.analysis.constants import HOLDING_COMPANIES
        except Exception:
            return False
        bare = (
            ticker.replace(".NS", "")
            .replace(".BO", "")
            .upper()
        )
        if bare in HOLDING_COMPANIES:
            return True
    return False


def _is_bank(stock_kind: Optional[str], sector: Optional[str]) -> bool:
    """Return True if the ticker should route through the bank branch.

    Two signals — match on either:
      1. `stock_kind` carries "bank" (preferred path).
      2. `sector` is one of the canonical bank/financial labels.

    The bank branch tags the dcf slot as "residual_income" because for
    banks the primary engine is the P/BV residual-income path, not DCF.
    The weighting itself is unchanged.
    """
    if stock_kind:
        kind_lower = str(stock_kind).strip().lower()
        if kind_lower in {"bank", "banking", "bank_like"}:
            return True
    if sector:
        s = str(sector).strip().lower()
        if s in {"banking", "banks", "nbfc", "insurance", "financial services"}:
            return True
    return False


def _normalize_weights(
    raw_weights: dict[str, float],
) -> dict[str, float]:
    """Re-normalize a partial weight dict so it sums to 1.0.

    Pro-rata: each present estimator's final weight is its default
    divided by the sum of present defaults. Empty input returns empty
    (caller emits the unavailable path).
    """
    total = sum(raw_weights.values())
    if total <= 0:
        return {}
    return {k: (w / total) for k, w in raw_weights.items()}


def compute_composite_iv(
    dcf_fv: Optional[float],
    multiples_fv: Optional[float],
    analyst_avg: Optional[float],
    three_stage_fv: Optional[float] = None,
    ddm_fv: Optional[float] = None,
    epv_fv: Optional[float] = None,
    probability_weighted_fv: Optional[float] = None,
    stock_kind: Optional[str] = None,
    sector: Optional[str] = None,
    ticker: Optional[str] = None,
) -> CompositeIV:
    """Compute the composite intrinsic value from up to seven estimators.

    Phase C (2026-06-10) extends the original three-estimator design
    (DCF + Multiples + Wall St) with four Phase-A standalone engines:
    Three-stage DCF, DDM, EPV, Probability-weighted. Liquidation and
    Replacement values are intentionally NOT folded in — they are
    floor / Q signals surfaced separately on the analysis payload.

    Arguments
    ─────────
    dcf_fv
        DCF fair value (or, for banks, the P/BV residual-income FV
        the primary engine produced — same slot, different label).
    multiples_fv
        Peer-relative multiples FV from multiples_fv.compute_multiples_fv.
        None when no peer cohort / no usable multiple.
    analyst_avg
        Wall Street analyst price-target mean (Finnhub consensus).
        None when no analyst coverage.
    three_stage_fv
        Three-stage growth DCF FV (T2.5 service). None when the
        applicability gate skips it (holdco / REIT / ETF / IPO).
    ddm_fv
        Dividend Discount Model FV (T2.1 service). None when payout
        / streak / sector gates make DDM inapplicable.
    epv_fv
        Earnings Power Value FV (T2.2 Greenwald service). None when
        history is short or earnings have been negative.
    probability_weighted_fv
        Probability-weighted scenario average FV (T2.4 service).
        None when bull/base/bear are not all positive.
    stock_kind
        Optional kind tag — "holdco" / "bank" routes to the curated
        branches. When None we fall back to ticker / sector classifiers.
    sector
        Optional canonical sector label — banks / NBFCs / insurance
        route through the bank branch.
    ticker
        Optional ticker symbol — used as the holdco-set fallback when
        `stock_kind` is unset.

    Returns
    ───────
    `CompositeIV` — value None when no estimator is usable. Always
    safe to render: a non-None composite always carries components
    summing to 1.0 and a method tag the frontend can branch on.

    Backward compatibility
    ──────────────────────
    Callers passing only the original three positional arguments
    (dcf_fv, multiples_fv, analyst_avg) still get a composite — the
    four new estimator slots default to None and the surviving
    weights redistribute pro-rata. The COMPUTED VALUE differs from
    the pre-Phase-C version because the underlying default weights
    were re-balanced (DCF 0.50 -> 0.35, Multiples 0.30 -> 0.20,
    Analyst 0.20 -> 0.15). With only the original three present the
    pro-rata renormalization yields DCF ≈ 0.500, Multiples ≈ 0.286,
    Analyst ≈ 0.214 — close to (but not equal to) the pre-Phase-C
    0.50 / 0.30 / 0.20. Expect ~1% drift on three-estimator tickers.
    """
    # ── Step 1: coerce + drop invalid inputs.
    _dcf = _coerce_pos_float(dcf_fv)
    _mult = _coerce_pos_float(multiples_fv)
    _ana = _coerce_pos_float(analyst_avg)
    _ts = _coerce_pos_float(three_stage_fv)
    _ddm = _coerce_pos_float(ddm_fv)
    _epv = _coerce_pos_float(epv_fv)
    _pw = _coerce_pos_float(probability_weighted_fv)

    # ── Step 2: branch routing.
    is_holdco = _is_holdco(stock_kind, ticker)
    is_bank = _is_bank(stock_kind, sector)

    # ── Step 3: holdco branch — DCF only, multiples skipped.
    # SOTP is the right framework for holdcos but ships under T1.4;
    # until then the DCF (or `fair_value` slot for skip-DCF holdcos
    # which is 0 — caller filters those out via _coerce_pos_float) is
    # the only honest estimator we can publish. The Phase-C extension
    # slots (three_stage / ddm / epv / prob_weighted) are also skipped
    # for holdcos — their applicability gates already exclude holdcos
    # at the Phase-B inject layer, so they will be None here anyway.
    if is_holdco:
        if _dcf is None:
            return CompositeIV(
                value=None,
                components={},
                method="unavailable",
            )
        return CompositeIV(
            value=round(_dcf, 2),
            components={
                "dcf": CompositeIVComponent(value=round(_dcf, 2), weight=1.0),
            },
            method="holdco_dcf_only",
        )

    # ── Step 4: assemble the active-weights dict from the surviving
    # estimators. Defaults are applied; redistribution happens in
    # _normalize_weights. Order in the dict matches the canonical
    # estimator priority for documentation purposes; it does not
    # affect the weighted average.
    raw_weights: dict[str, float] = {}
    if _dcf is not None:
        raw_weights["dcf"] = DEFAULT_WEIGHT_DCF
    if _mult is not None:
        raw_weights["multiples"] = DEFAULT_WEIGHT_MULTIPLES
    if _ana is not None:
        raw_weights["analyst"] = DEFAULT_WEIGHT_ANALYST
    if _ts is not None:
        raw_weights["three_stage"] = DEFAULT_WEIGHT_THREE_STAGE
    if _ddm is not None:
        raw_weights["ddm"] = DEFAULT_WEIGHT_DDM
    if _epv is not None:
        raw_weights["epv"] = DEFAULT_WEIGHT_EPV
    if _pw is not None:
        raw_weights["probability_weighted"] = DEFAULT_WEIGHT_PROBABILITY_WEIGHTED

    if not raw_weights:
        return CompositeIV(
            value=None,
            components={},
            method="unavailable",
        )

    final_weights = _normalize_weights(raw_weights)
    values_by_key: dict[str, float] = {}
    if _dcf is not None:
        values_by_key["dcf"] = _dcf
    if _mult is not None:
        values_by_key["multiples"] = _mult
    if _ana is not None:
        values_by_key["analyst"] = _ana
    if _ts is not None:
        values_by_key["three_stage"] = _ts
    if _ddm is not None:
        values_by_key["ddm"] = _ddm
    if _epv is not None:
        values_by_key["epv"] = _epv
    if _pw is not None:
        values_by_key["probability_weighted"] = _pw

    # ── Step 5: weighted average. Round to 2dp at the boundary; the
    # frontend renders with formatCurrency which rounds to integers
    # anyway, but downstream callers (verdict gate, alerts) may want
    # the 2dp precision.
    composite = sum(values_by_key[k] * final_weights[k] for k in values_by_key)
    composite = round(composite, 2)

    # ── Step 6: extreme-divergence flag.
    active_values = list(values_by_key.values())
    extreme = False
    if len(active_values) >= 2:
        lo = min(active_values)
        hi = max(active_values)
        if lo > 0 and (hi / lo) > EXTREME_DIVERGENCE_RATIO:
            extreme = True

    # ── Step 7: method tag.
    #
    # Phase C method tagging strategy:
    #   * 1 estimator       -> "<name>_only"  (or bank_residual_income)
    #   * 3 estimators      -> kept the legacy "composite_dcf_multiples_analyst"
    #                          and friends for back-compat with the frontend
    #                          explainer chips that rendered the original
    #                          composite. Bank variants likewise preserved.
    #   * 2 estimators      -> two-way tags as before.
    #   * 4-7 estimators    -> "composite_{N}_method" with optional bank prefix.
    #     This covers the new Phase-C mixes (DCF + Multiples + Analyst +
    #     Three-stage, plus any of DDM / EPV / prob_weighted on top). The
    #     frontend reads N to size the explainer panel; the components
    #     dict carries the per-estimator labels and weights.
    keys = set(values_by_key.keys())
    n_estimators = len(keys)
    # Bank branch tag: the "dcf" slot is actually the residual-income
    # FV the primary engine emitted. We surface this in the method tag
    # so the frontend can render the pill as "Residual income" not "DCF".
    if is_bank and "dcf" in keys:
        if n_estimators == 1:
            method = "bank_residual_income"
        else:
            # Bank + at least one other estimator. Use the standard
            # multi-method tag but the frontend reads the `method`
            # field to decide whether to relabel the dcf pill.
            method = _multi_method_tag(keys, bank=True)
    else:
        if n_estimators == 1:
            sole = next(iter(keys))
            method = f"{sole}_only"
        else:
            method = _multi_method_tag(keys, bank=False)

    # ── Step 8: assemble the components dict with final weights.
    components: dict[str, CompositeIVComponent] = {}
    for k in values_by_key:
        components[k] = CompositeIVComponent(
            value=round(values_by_key[k], 2),
            weight=round(final_weights[k], 4),
        )

    return CompositeIV(
        value=composite,
        components=components,
        method=method,
        extreme_divergence=extreme,
    )


def _multi_method_tag(keys: set[str], bank: bool) -> str:
    """Return the canonical method tag for a multi-estimator composite.

    Phase C (2026-06-10): the original three-estimator names are
    preserved for back-compat with the frontend explainer. Any mix
    that includes a Phase-C estimator (three_stage / ddm / epv /
    probability_weighted) collapses to the generic
    ``composite_{N}_method`` form — the frontend can read N to size
    its explainer card and read the components dict for per-row labels.
    """
    has_dcf = "dcf" in keys
    has_mult = "multiples" in keys
    has_ana = "analyst" in keys
    phase_c_keys = {"three_stage", "ddm", "epv", "probability_weighted"}
    has_any_phase_c = bool(keys & phase_c_keys)
    n = len(keys)
    # ── Generic Phase-C path: any Phase-C estimator present uses the
    # N-method tag. Bank prefix preserved so the dcf slot keeps its
    # residual-income relabel on the frontend pill.
    if has_any_phase_c:
        if bank:
            return f"bank_composite_{n}_method"
        return f"composite_{n}_method"
    # ── Legacy three-estimator tags (no Phase-C estimator present) ──
    # Bank tag prefix flips the dcf label on the frontend pill.
    if bank:
        # Three-way bank composite is the dominant case for HDFCBANK /
        # ICICIBANK / SBIN. We name it explicitly so the frontend can
        # branch deterministically.
        if has_dcf and has_mult and has_ana:
            return "bank_composite_residual_multiples_analyst"
        if has_dcf and has_mult:
            return "bank_composite_residual_multiples"
        if has_dcf and has_ana:
            return "bank_composite_residual_analyst"
    if has_dcf and has_mult and has_ana:
        return "composite_dcf_multiples_analyst"
    if has_dcf and has_mult:
        return "composite_dcf_multiples"
    if has_dcf and has_ana:
        return "composite_dcf_analyst"
    if has_mult and has_ana:
        return "composite_multiples_analyst"
    # Single-estimator paths handled by caller; this shouldn't fire.
    return "unavailable"


def composite_to_dict(c: CompositeIV) -> dict:
    """Serialize a CompositeIV to a JSON-safe dict.

    Used by the router to attach the composite to a dict payload (and
    by the Pydantic-model attach path which model-dumps the dataclass
    via this helper). The shape mirrors the AnalysisResponse contract:
        {
            "value": float | None,
            "components": {
                "dcf":       {"value": 1129.28, "weight": 0.50},
                "multiples": {"value": 872.33,  "weight": 0.30},
                "analyst":   {"value": 803.00,  "weight": 0.20},
            },
            "method": "composite_dcf_multiples_analyst",
            "extreme_divergence": false,
        }
    """
    return {
        "value": c.value,
        "components": {
            k: {"value": comp.value, "weight": comp.weight}
            for k, comp in c.components.items()
        },
        "method": c.method,
        "extreme_divergence": c.extreme_divergence,
    }
