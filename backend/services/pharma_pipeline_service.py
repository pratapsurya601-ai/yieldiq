# backend/services/pharma_pipeline_service.py
# ═══════════════════════════════════════════════════════════════
# Pharma pipeline rNPV — risk-adjusted Net Present Value engine.
#
# Indian listed pharma names (Sun Pharma, Dr Reddy's, Cipla, Lupin,
# Biocon, Zydus, Torrent, Mankind, etc.) carry substantial in-flight
# pipelines of unapproved assets — NCEs, biosimilars, complex generics
# — whose value the standard FCF-based DCF in
# ``backend/services/analysis/service.py`` cannot capture cleanly.
# A revenue-line model treats a Phase-3 oncology asset launching three
# years from today as "indistinguishable from existing revenue", which
# is wrong on two axes: (a) the asset has a probability of approval
# (POA) that is not 1.0, and (b) the cashflows are concentrated in a
# 5-12 year window after launch, then decay as exclusivity expires.
#
# Standard sell-side practice (Greenwald, biotech sell-side desks at
# JPM / MS / Jefferies) is per-asset Risk-adjusted NPV (rNPV):
#
#     rNPV_asset = POA × Σ_t [ (peak_sales × penetration_curve(t) × margin)
#                              / (1 + r) ^ t ]
#
# Where:
#   * POA varies by development phase (discovery 3% → filed 87%).
#   * Peak sales = TAM × peak market share.
#   * Penetration ramps over ~5 years from launch.
#   * Discount rate r = 12-15% (vs the standard 10% — pharma is
#     risk-adjusted with a higher cost of capital).
#   * Exclusivity duration: NCEs 10-12 years post-launch; biosimilars
#     5-7 years (faster erosion to commodity pricing).
#
# This is a Phase A standalone service:
#   * NO routing into the existing pharma DCF path. The wiring lands
#     in a separate PR after a curated pipeline-data ingestion is in
#     place. Until then, the standard franchise DCF (Day-84 cohort)
#     continues to compute pharma fair value.
#   * Reads hand-curated pipeline data from
#     ``backend/data/pharma_pipeline_seed.json`` (3 example tickers).
#   * Can also be invoked with explicit assets at the call site for
#     test/debug purposes.
#
# Routing helper:
#   ``is_pharma_pipeline_meaningful(ticker, sector, has_curated_data)``
#   returns True only when (a) the sector is pharma and (b) curated
#   pipeline data exists for the ticker. For pharma tickers WITHOUT
#   curated data the helper returns False — the caller falls back to
#   the standard DCF. We do NOT fabricate a pipeline from a generic
#   prior; that would be model-noise dressed up as signal.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import pathlib
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("yieldiq.pharma_pipeline")


DevelopmentPhase = Literal[
    "discovery",
    "preclinical",
    "phase_1",
    "phase_2",
    "phase_3",
    "filed",
    "approved",
    "marketed",
]


# ── POA by phase ────────────────────────────────────────────────
#
# Industry-consensus phase-transition probabilities, averaged across
# therapeutic areas. Specific therapy-area shaders (oncology Phase 3
# is ~55% vs cardio ~70%) are out of scope for Phase A — the seed
# JSON can pin a ``custom_poa_override`` for any asset whose CMC /
# regulatory situation diverges from this default table.
#
# Source frame: BIO/Pharmaprojects/Informa Pharma Intelligence 2021
# Clinical Development Success Rates report, blended.
POA_BY_PHASE: dict[str, float] = {
    "discovery":   0.03,
    "preclinical": 0.08,
    "phase_1":     0.13,
    "phase_2":     0.25,
    "phase_3":     0.55,
    "filed":       0.87,
    "approved":    1.00,
    "marketed":    1.00,
}


# ── Penetration curve (5-year ramp from launch) ─────────────────
#
# Industry-standard NCE ramp: ~10% peak share in year 1 of launch,
# ~20% year 2, ~50% year 3, ~75% year 4, 100% steady-state from year
# 5 onwards. Held flat at 100% until exclusivity expiry (after which
# the asset is excluded from the NPV — generic / biosimilar erosion is
# modeled by truncating the cashflow stream, not by a decay tail).
#
# Biosimilars get a faster initial ramp (rebate-driven formulary
# adoption is quicker than physician-detail-driven NCE adoption) but
# the same plateau.
_NCE_PENETRATION_CURVE: tuple[float, ...] = (0.10, 0.20, 0.50, 0.75, 1.00)
_BIOSIMILAR_PENETRATION_CURVE: tuple[float, ...] = (0.15, 0.35, 0.65, 0.85, 1.00)


# ── Exclusivity duration defaults ───────────────────────────────
#
# Overridden per-asset via the seed JSON. The Phase A defaults are
# used only when the seed data is missing the field, which the
# loader treats as a sanity warning.
_DEFAULT_NCE_EXCLUSIVITY_YEARS = 11
_DEFAULT_BIOSIMILAR_EXCLUSIVITY_YEARS = 6


# ── Discount rate band ──────────────────────────────────────────
#
# 13% is the midpoint of the 12-15% pharma RDR band. The discount
# rate is the caller's choice; the default is exposed so the wiring
# layer can pin a value consistent with the rest of the pharma DCF
# WACC band. Below 10% the rNPV starts blowing up (lower bound of
# the band reflects post-approval-only assets where pharma is closer
# to a normal industrial); above 18% we're closer to early-stage
# biotech VC math and that is out of scope for a listed-equity model.
_RDR_FLOOR = 0.10
_RDR_CEILING = 0.18
_DEFAULT_DISCOUNT_RATE = 0.13


# ── Default seed JSON location ──────────────────────────────────
_SEED_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "pharma_pipeline_seed.json"
_SEED_CACHE: Optional[dict] = None


# ─────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────


@dataclass
class PipelineAsset:
    """A single in-flight pharma development asset.

    All numeric fields are positional inputs to the rNPV math; the
    seed JSON loader builds these directly from the curated entries.
    """
    name: str
    phase: DevelopmentPhase
    indication: str
    target_market_size_usd: float            # TAM in USD
    expected_peak_share_pct: float           # 0-100; peak market share assumption
    expected_margin_pct: float               # 0-100; operating margin on peak sales
    expected_launch_year_offset: int         # years from today until launch
    exclusivity_years: int                   # post-launch
    is_biosimilar: bool = False              # affects exclusivity floor + ramp curve
    custom_poa_override: Optional[float] = None  # override the phase-default POA


@dataclass
class PipelineAssetValuation:
    """rNPV per asset, expressed both in USD (input currency) and
    INR Crores (the unit the rest of the engine speaks)."""
    asset: PipelineAsset
    poa_applied: float
    peak_revenue_usd: float
    rnpv_usd: float
    rnpv_inr_cr: float
    contribution_pct: Optional[float] = None  # % of total pipeline value


@dataclass
class PipelineValuationResult:
    total_pipeline_rnpv_inr_cr: float
    asset_valuations: list[PipelineAssetValuation]
    top_3_drivers: list[str]                  # asset names that drive >50% of value
    sensitivity: dict                         # POA shock, peak-share shock, etc.
    sanity_warnings: list[str] = field(default_factory=list)
    method: str = "rnpv_per_asset"


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _clean_ticker(t: Optional[str]) -> str:
    return (t or "").replace(".NS", "").replace(".BO", "").upper().strip()


def _resolve_poa(asset: PipelineAsset) -> float:
    """POA applied to the asset.

    Honors a custom override if set; otherwise looks up the phase
    default. Falls back to discovery-level POA (3%) for an unknown
    phase string (defensive — the seed JSON is hand-curated so this
    branch should not fire in practice).
    """
    if asset.custom_poa_override is not None:
        # Defensive clamp to [0, 1]. A POA of 0 yields rNPV=0 (the
        # asset is dropped from the sum implicitly).
        return max(0.0, min(1.0, float(asset.custom_poa_override)))
    return POA_BY_PHASE.get(asset.phase, POA_BY_PHASE["discovery"])


def _penetration_curve(is_biosimilar: bool) -> tuple[float, ...]:
    return _BIOSIMILAR_PENETRATION_CURVE if is_biosimilar else _NCE_PENETRATION_CURVE


def _clamp_rdr(rdr: float) -> float:
    """Clamp discount rate into the documented pharma band."""
    return max(_RDR_FLOOR, min(_RDR_CEILING, float(rdr)))


# ─────────────────────────────────────────────────────────────────
# Core math
# ─────────────────────────────────────────────────────────────────


def value_single_asset(
    asset: PipelineAsset,
    discount_rate: float = _DEFAULT_DISCOUNT_RATE,
    usd_to_inr: float = 83.0,
) -> PipelineAssetValuation:
    """rNPV for a single pipeline asset.

    Formula:
        peak_revenue_usd = TAM × peak_share
        annual_peak_op_profit_usd = peak_revenue_usd × margin
        rNPV_usd = POA × Σ_t [annual_op_profit_t / (1 + r)^t]
                  where t ranges over [launch_year, launch_year + exclusivity_years - 1]
                  and annual_op_profit_t = peak × penetration(t - launch_year)
                  (penetration plateaus at 1.0 from year 5 onwards).

    Returns a fully-populated PipelineAssetValuation. ``contribution_pct``
    is left as None and is filled in by ``value_pipeline`` once the
    total is known.
    """
    if asset.target_market_size_usd <= 0:
        return PipelineAssetValuation(
            asset=asset,
            poa_applied=_resolve_poa(asset),
            peak_revenue_usd=0.0,
            rnpv_usd=0.0,
            rnpv_inr_cr=0.0,
        )

    r = _clamp_rdr(discount_rate)
    poa = _resolve_poa(asset)
    peak_share = max(0.0, float(asset.expected_peak_share_pct) / 100.0)
    margin = max(0.0, float(asset.expected_margin_pct) / 100.0)
    peak_revenue_usd = float(asset.target_market_size_usd) * peak_share
    annual_peak_op_profit_usd = peak_revenue_usd * margin

    launch_offset = max(0, int(asset.expected_launch_year_offset))
    exclusivity = max(0, int(asset.exclusivity_years))
    curve = _penetration_curve(bool(asset.is_biosimilar))

    pv_op_profit_usd = 0.0
    for k in range(exclusivity):
        # Penetration is a function of years-since-launch (k). Hold
        # at the curve plateau once we're past the ramp.
        if k < len(curve):
            penetration = curve[k]
        else:
            penetration = curve[-1]
        op_profit_t = annual_peak_op_profit_usd * penetration
        # Discount index counts from today (t = launch_offset + k).
        t = launch_offset + k
        pv_op_profit_usd += op_profit_t / ((1.0 + r) ** t)

    rnpv_usd = poa * pv_op_profit_usd
    # 1 INR Crore = 1e7 INR. USD → INR → Crores.
    rnpv_inr_cr = (rnpv_usd * float(usd_to_inr)) / 1e7

    return PipelineAssetValuation(
        asset=asset,
        poa_applied=poa,
        peak_revenue_usd=round(peak_revenue_usd, 2),
        rnpv_usd=round(rnpv_usd, 2),
        rnpv_inr_cr=round(rnpv_inr_cr, 2),
    )


def _compute_sensitivity(
    assets: list[PipelineAsset],
    discount_rate: float,
    usd_to_inr: float,
    base_total_inr_cr: float,
) -> dict:
    """Compute one-variable shocks around the base case.

    Returns a dict with three deterministic shocks: 50% POA cut,
    25% peak-share cut, and discount-rate +200 bps. Each value is
    the resulting total pipeline rNPV in INR Crores. The expected
    movement is documented per shock so consumers don't have to
    re-derive the sign / magnitude.
    """
    def total_with_assets(modded: list[PipelineAsset]) -> float:
        return round(
            sum(
                value_single_asset(a, discount_rate=discount_rate, usd_to_inr=usd_to_inr).rnpv_inr_cr
                for a in modded
            ),
            2,
        )

    # POA shock: halve every asset's POA.
    poa_shocked = [
        PipelineAsset(
            name=a.name,
            phase=a.phase,
            indication=a.indication,
            target_market_size_usd=a.target_market_size_usd,
            expected_peak_share_pct=a.expected_peak_share_pct,
            expected_margin_pct=a.expected_margin_pct,
            expected_launch_year_offset=a.expected_launch_year_offset,
            exclusivity_years=a.exclusivity_years,
            is_biosimilar=a.is_biosimilar,
            custom_poa_override=_resolve_poa(a) * 0.5,
        )
        for a in assets
    ]
    poa_shock_total = total_with_assets(poa_shocked)

    # Peak-share shock: 25% cut.
    share_shocked = [
        PipelineAsset(
            name=a.name,
            phase=a.phase,
            indication=a.indication,
            target_market_size_usd=a.target_market_size_usd,
            expected_peak_share_pct=a.expected_peak_share_pct * 0.75,
            expected_margin_pct=a.expected_margin_pct,
            expected_launch_year_offset=a.expected_launch_year_offset,
            exclusivity_years=a.exclusivity_years,
            is_biosimilar=a.is_biosimilar,
            custom_poa_override=a.custom_poa_override,
        )
        for a in assets
    ]
    share_shock_total = total_with_assets(share_shocked)

    # Discount-rate shock: +200 bps.
    rdr_shock_total = round(
        sum(
            value_single_asset(a, discount_rate=discount_rate + 0.02, usd_to_inr=usd_to_inr).rnpv_inr_cr
            for a in assets
        ),
        2,
    )

    return {
        "base_total_inr_cr": base_total_inr_cr,
        "poa_minus_50_pct": {
            "total_inr_cr": poa_shock_total,
            "delta_pct": round(
                ((poa_shock_total - base_total_inr_cr) / base_total_inr_cr * 100.0)
                if base_total_inr_cr > 0 else 0.0,
                2,
            ),
            "description": "Half the probability of approval on every asset.",
        },
        "peak_share_minus_25_pct": {
            "total_inr_cr": share_shock_total,
            "delta_pct": round(
                ((share_shock_total - base_total_inr_cr) / base_total_inr_cr * 100.0)
                if base_total_inr_cr > 0 else 0.0,
                2,
            ),
            "description": "Trim peak market share by 25%.",
        },
        "discount_rate_plus_200_bps": {
            "total_inr_cr": rdr_shock_total,
            "delta_pct": round(
                ((rdr_shock_total - base_total_inr_cr) / base_total_inr_cr * 100.0)
                if base_total_inr_cr > 0 else 0.0,
                2,
            ),
            "description": "Add 200 bps to the discount rate.",
        },
    }


def _top_drivers(valuations: list[PipelineAssetValuation], threshold_pct: float = 50.0) -> list[str]:
    """Return the asset names that cumulatively account for ``threshold_pct``
    or more of total pipeline value, in descending contribution order.

    Cap at 3 names so the surface stays readable when one asset
    dominates and another two are negligible.
    """
    ranked = sorted(
        valuations,
        key=lambda v: v.rnpv_inr_cr,
        reverse=True,
    )
    cumulative = 0.0
    names: list[str] = []
    for v in ranked:
        if v.contribution_pct is None or v.rnpv_inr_cr <= 0:
            continue
        names.append(v.asset.name)
        cumulative += v.contribution_pct
        if cumulative >= threshold_pct or len(names) >= 3:
            break
    return names


def _sanity_checks(assets: list[PipelineAsset]) -> list[str]:
    """Surface obvious data-quality issues with the curated assets."""
    warnings: list[str] = []
    for a in assets:
        if a.target_market_size_usd <= 0:
            warnings.append(f"{a.name}: TAM is non-positive — asset contributes nothing.")
        if a.expected_peak_share_pct <= 0:
            warnings.append(f"{a.name}: expected peak share is non-positive.")
        if a.expected_margin_pct <= 0:
            warnings.append(f"{a.name}: expected operating margin is non-positive.")
        if a.expected_peak_share_pct > 60:
            warnings.append(
                f"{a.name}: peak share assumption of "
                f"{a.expected_peak_share_pct:.0f}% is aggressive (>60%)."
            )
        if a.exclusivity_years <= 0:
            warnings.append(f"{a.name}: exclusivity duration is zero — no value will accrete.")
        if a.is_biosimilar and a.exclusivity_years > 8:
            warnings.append(
                f"{a.name}: biosimilar exclusivity of {a.exclusivity_years}y "
                f"is longer than industry norms (~5-7y)."
            )
        if not a.is_biosimilar and a.exclusivity_years > 14:
            warnings.append(
                f"{a.name}: NCE exclusivity of {a.exclusivity_years}y "
                f"exceeds the 10-12y industry norm — verify."
            )
        if a.phase not in POA_BY_PHASE:
            warnings.append(
                f"{a.name}: phase '{a.phase}' is not recognised — defaulted to discovery POA."
            )
    return warnings


def value_pipeline(
    assets: list[PipelineAsset],
    discount_rate: float = _DEFAULT_DISCOUNT_RATE,
    usd_to_inr: float = 83.0,
) -> PipelineValuationResult:
    """Sum rNPV across a list of pipeline assets.

    Empty input list returns a zero-total result with ``method =
    'unavailable'`` so callers can branch on a single attribute.
    """
    if not assets:
        return PipelineValuationResult(
            total_pipeline_rnpv_inr_cr=0.0,
            asset_valuations=[],
            top_3_drivers=[],
            sensitivity={},
            sanity_warnings=["No pipeline assets supplied."],
            method="unavailable",
        )

    valuations = [
        value_single_asset(a, discount_rate=discount_rate, usd_to_inr=usd_to_inr)
        for a in assets
    ]
    total = round(sum(v.rnpv_inr_cr for v in valuations), 2)

    # Per-asset contribution % of total.
    if total > 0:
        for v in valuations:
            v.contribution_pct = round((v.rnpv_inr_cr / total) * 100.0, 2)
    else:
        for v in valuations:
            v.contribution_pct = 0.0

    drivers = _top_drivers(valuations, threshold_pct=50.0)
    sensitivity = _compute_sensitivity(
        assets,
        discount_rate=discount_rate,
        usd_to_inr=usd_to_inr,
        base_total_inr_cr=total,
    )
    warnings = _sanity_checks(assets)

    return PipelineValuationResult(
        total_pipeline_rnpv_inr_cr=total,
        asset_valuations=valuations,
        top_3_drivers=drivers,
        sensitivity=sensitivity,
        sanity_warnings=warnings,
        method="rnpv_per_asset",
    )


# ─────────────────────────────────────────────────────────────────
# Seed-data loader
# ─────────────────────────────────────────────────────────────────


def _load_seed() -> dict:
    """Read the hand-curated pipeline seed from
    ``backend/data/pharma_pipeline_seed.json``. Lazy + cached.

    Returns an empty dict on any I/O failure so the rest of the
    engine treats the universe as "no curated pipeline data" and
    falls back to standard DCF.
    """
    global _SEED_CACHE
    if _SEED_CACHE is not None:
        return _SEED_CACHE
    try:
        with open(_SEED_PATH, "r", encoding="utf-8") as fh:
            _SEED_CACHE = json.load(fh) or {}
    except Exception as exc:
        logger.warning(
            "pharma_pipeline: failed to read seed %s: %s: %s",
            _SEED_PATH, type(exc).__name__, exc,
        )
        _SEED_CACHE = {}
    return _SEED_CACHE


def _coerce_asset(raw: dict) -> Optional[PipelineAsset]:
    """Build a PipelineAsset from a JSON dict. Returns None on any
    structurally-invalid entry (so the loader logs a warning rather
    than blowing up).
    """
    try:
        is_bio = bool(raw.get("is_biosimilar", False))
        return PipelineAsset(
            name=str(raw["name"]),
            phase=str(raw["phase"]),  # type: ignore[arg-type]
            indication=str(raw.get("indication", "")),
            target_market_size_usd=float(raw["target_market_size_usd"]),
            expected_peak_share_pct=float(raw["expected_peak_share_pct"]),
            expected_margin_pct=float(raw["expected_margin_pct"]),
            expected_launch_year_offset=int(raw["expected_launch_year_offset"]),
            exclusivity_years=int(raw.get(
                "exclusivity_years",
                _DEFAULT_BIOSIMILAR_EXCLUSIVITY_YEARS if is_bio else _DEFAULT_NCE_EXCLUSIVITY_YEARS,
            )),
            is_biosimilar=is_bio,
            custom_poa_override=(
                float(raw["custom_poa_override"])
                if raw.get("custom_poa_override") is not None
                else None
            ),
        )
    except Exception as exc:
        logger.warning(
            "pharma_pipeline: skipping malformed asset entry %r: %s: %s",
            raw, type(exc).__name__, exc,
        )
        return None


def load_curated_assets(ticker: str) -> list[PipelineAsset]:
    """Return curated pipeline assets for ``ticker`` from the seed,
    or [] when the ticker is not in the seed (which is the common
    case — only 3 tickers are curated at Phase A).
    """
    bare = _clean_ticker(ticker)
    seed = _load_seed()
    block = seed.get(bare)
    if not isinstance(block, dict):
        return []
    raw_assets = block.get("assets") or []
    if not isinstance(raw_assets, list):
        return []
    out: list[PipelineAsset] = []
    for raw in raw_assets:
        if not isinstance(raw, dict):
            continue
        asset = _coerce_asset(raw)
        if asset is not None:
            out.append(asset)
    return out


def has_curated_pipeline_data(ticker: str) -> bool:
    """True when the seed JSON carries at least one pipeline asset
    for the given ticker."""
    return bool(load_curated_assets(ticker))


# ─────────────────────────────────────────────────────────────────
# Routing helper
# ─────────────────────────────────────────────────────────────────


# Pharma-cohort tickers that we recognise as candidates for the
# pipeline engine. Mirrors ``_PHARMA_FRANCHISE_TICKERS_INLINE`` in
# ``backend/services/analysis/service.py`` plus the broader generic /
# biosimilar peers — the routing helper accepts the whole pharma
# universe and then defers to the seed-presence check for the
# actual gate. Kept here as a private module set so the helper is
# stand-alone (no import into ``analysis/`` from this Phase A PR).
_PHARMA_COHORT: frozenset[str] = frozenset({
    # Franchise tier
    "MANKIND", "SUNPHARMA", "CIPLA", "TORNTPHARM", "DRREDDY",
    "DIVISLAB", "ABBOTINDIA", "GLAND", "GLAXO", "PFIZER",
    # Generic / biosimilar broader peers
    "LUPIN", "AUROPHARMA", "GLENMARK", "BIOCON", "ZYDUSLIFE",
    "ALKEM", "IPCALAB", "AJANTPHARM", "JBCHEPHARM", "ERIS",
    "NATCOPHARM", "FDC", "MARKSANS", "GRANULES",
})


def _is_pharma_sector(sector: Optional[str]) -> bool:
    if not sector:
        return False
    s = str(sector).strip().lower()
    return s in {
        "pharma",
        "pharmaceuticals",
        "pharmaceutical",
        "healthcare",
        "health care",
        "drugs",
        "biotech",
        "biotechnology",
    }


def is_pharma_pipeline_meaningful(
    ticker: str,
    sector: Optional[str],
    has_curated_pipeline_data: bool,  # noqa: ARG001 — name preserved per contract
) -> tuple[bool, str]:
    """Decide whether the pipeline rNPV path should fire for a ticker.

    Returns ``(meaningful, reason)``. Meaningful only when:
      1. The sector (or our hardcoded pharma cohort) marks the ticker
         as pharma, AND
      2. The caller has confirmed curated pipeline data exists for
         the ticker.

    For pharma tickers WITHOUT curated data we explicitly return False
    rather than fabricating a generic-prior pipeline. The standard
    franchise DCF path handles those.

    The ``has_curated_pipeline_data`` parameter is the caller's gate so
    the helper stays pure (no I/O); callers that don't already know
    can use ``backend.services.pharma_pipeline_service.has_curated_pipeline_data``.
    """
    bare = _clean_ticker(ticker)
    if not bare:
        return (False, "empty ticker")
    if not (_is_pharma_sector(sector) or bare in _PHARMA_COHORT):
        return (False, "ticker is not in the pharma cohort")
    if not has_curated_pipeline_data:
        return (False, "no curated pipeline data — fall back to standard DCF")
    return (True, "pharma cohort + curated pipeline data available")


# ─────────────────────────────────────────────────────────────────
# JSON serialisation
# ─────────────────────────────────────────────────────────────────


def to_dict(result: PipelineValuationResult) -> dict:
    """JSON-safe projection of a PipelineValuationResult.

    Shape:
        {
          "method": "rnpv_per_asset" | "unavailable",
          "total_pipeline_rnpv_inr_cr": float,
          "top_3_drivers": [str, ...],
          "asset_valuations": [
            {
              "name": str, "phase": str, "indication": str,
              "is_biosimilar": bool,
              "poa_applied": float,
              "peak_revenue_usd": float,
              "rnpv_usd": float,
              "rnpv_inr_cr": float,
              "contribution_pct": float | None
            }, ...
          ],
          "sensitivity": { ... },
          "sanity_warnings": [str, ...]
        }
    """
    return {
        "method": result.method,
        "total_pipeline_rnpv_inr_cr": result.total_pipeline_rnpv_inr_cr,
        "top_3_drivers": list(result.top_3_drivers),
        "asset_valuations": [
            {
                "name": v.asset.name,
                "phase": v.asset.phase,
                "indication": v.asset.indication,
                "is_biosimilar": v.asset.is_biosimilar,
                "poa_applied": round(v.poa_applied, 4),
                "peak_revenue_usd": v.peak_revenue_usd,
                "rnpv_usd": v.rnpv_usd,
                "rnpv_inr_cr": v.rnpv_inr_cr,
                "contribution_pct": v.contribution_pct,
            }
            for v in result.asset_valuations
        ],
        "sensitivity": result.sensitivity,
        "sanity_warnings": list(result.sanity_warnings),
    }
