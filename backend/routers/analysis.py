# backend/routers/analysis.py
from __future__ import annotations
import sys
from pathlib import Path

# Ensure project root and dashboard root are on sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
_DASHBOARD_ROOT = str(Path(_PROJECT_ROOT) / "dashboard")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse as _FastAPIJSONResponse
from backend.models.responses import AnalysisResponse, ScreenerResponse, ScreenerStock
from backend.services.analysis_service import AnalysisService, TickerNotFoundError
from backend.services.cache_service import cache
from backend.services import analysis_cache_service
from backend.middleware.auth import (
    get_current_user,
    get_current_user_optional,
    check_analysis_limit,
    require_email_verified,
)
from backend.middleware.api_auth import get_user_from_api_key
from backend.services import api_keys_service as _api_keys_svc
from backend.services.ticker_search import search_tickers
from backend.services.tier_caps import cap_for
from datetime import date
from typing import Any, Optional
from fastapi import Header


async def _auth_jwt_or_api_key(
    response: Response,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Auth for /analysis/{ticker} accepting EITHER JWT or API key.

    Header sniffing happens FIRST so we never invoke the JWT-counter
    increment for an API-key request. The per-user JWT counter and
    the per-key API quota are deliberately separate (a Pro user with
    5 keys gets 5 x 100 = 500 req/day by design — see
    api_keys_service module docstring).

    Routing:
      * If ``Authorization: Bearer yk_...`` or ``X-API-Key: yk_...`` ->
        validate via ``get_user_from_api_key`` (raises 401/403/429).
      * Otherwise fall through to the existing JWT path
        (``check_analysis_limit``) which preserves the free-tier
        5/day cap, the X-Analyses-Today headers, and superuser bypass.
    """
    is_api_key = False
    if authorization and authorization.startswith("Bearer "):
        if authorization[len("Bearer "):].strip().startswith(
                _api_keys_svc.RAW_KEY_PREFIX):
            is_api_key = True
    if not is_api_key and x_api_key and x_api_key.strip().startswith(
            _api_keys_svc.RAW_KEY_PREFIX):
        is_api_key = True

    if is_api_key:
        return await get_user_from_api_key(
            authorization=authorization, x_api_key=x_api_key,
        )

    # JWT path — call the existing dependency manually so the response
    # headers / counter side-effects fire identically to before.
    from fastapi.security import HTTPAuthorizationCredentials
    creds = None
    if authorization and authorization.startswith("Bearer "):
        creds = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=authorization[len("Bearer "):],
        )
    jwt_user = await get_current_user(creds)
    return check_analysis_limit(response, jwt_user)

router = APIRouter(prefix="/api/v1", tags=["analysis"])
service = AnalysisService()

# require_admin lives in backend.routers.admin (defined above
# debug_router so it's importable at module-load time without
# circular-import issues — admin doesn't import this module). The
# /debug/* endpoints below were unauthenticated before 2026-04-25;
# gating them prevents leaking DCF traces / parquet paths / local
# assembler internals to anonymous callers.
from backend.routers.admin import require_admin as _require_admin  # noqa: E402

# ── Ticker renames ────────────────────────────────────────────
# Map retired symbols → canonical symbol. Requests hit the new
# ticker silently; frontend detects the mismatch between the URL
# ticker and response.ticker to show a rename banner.
TICKER_ALIASES: dict[str, str] = {
    # Renames / rebrands
    "ZOMATO.NS":       "ETERNAL.NS",    # Zomato → Eternal Ltd (Nov 2024 rebrand)
    "ZOMATO":          "ETERNAL.NS",
    "ADANITRANS.NS":   "ADANIENSOL.NS", # Adani Transmission → Adani Energy Solutions (2024 rename)
    "ADANITRANS":      "ADANIENSOL.NS",
    # Demerger successors (redirect to primary business post-split)
    "TATAMOTORS.NS":   "TMPV.NS",       # Tata Motors → TMPV (passenger vehicles, post-demerger)
    "TATAMOTORS":      "TMPV.NS",
    # Common short/wrong forms → canonical NSE symbol
    "KPIT.NS":         "KPITTECH.NS",   # KPIT → KPITTECH
    "KPIT":            "KPITTECH.NS",
    "BERGERPAINTS.NS": "BERGEPAINT.NS", # typo in our universe list
    "BERGERPAINTS":    "BERGEPAINT.NS",
    "DALMIA.NS":       "DALBHARAT.NS",  # Dalmia Bharat
    "DALMIA":          "DALBHARAT.NS",
    "DOMINOS.NS":      "JUBLFOOD.NS",   # Domino's franchisee = Jubilant FoodWorks
    "DOMINOS":         "JUBLFOOD.NS",
    "BLUESTAR.NS":     "BLUESTARCO.NS", # Blue Star Ltd (NSE canonical)
    "BLUESTAR":        "BLUESTARCO.NS",
    # Mindtree merged into LTI → LTIMindtree (Nov 2022). Old ticker
    # LTI kept listing but was renamed LTIM which itself was later
    # relisted as LTIMINDTREE. Legacy user bookmarks + some of our
    # own TICKER_ALIASES in external scripts still hit LTIM.NS — it
    # exists on yfinance but returns stale/partial data. Sentry sees
    # 208+ events/day from this one symbol. Redirect to the canonical.
    "LTIM.NS":         "LTIMINDTREE.NS",
    "LTIM":            "LTIMINDTREE.NS",
    # Company-name slug → listing-symbol mismatches (P1 2026-05-02).
    # Reddit user reports of "not found" because the URL slug from
    # autocomplete/screen results differed from the NSE ticker.
    "GESHIPPING.NS":   "GESHIP.NS",     # Great Eastern Shipping
    "GESHIPPING":      "GESHIP.NS",
    "STERLITETECH.NS": "STLTECH.NS",    # Sterlite Technologies
    "STERLITETECH":    "STLTECH.NS",
    "GVTD.NS":         "GVT&D.NS",      # GE Vernova T&D India
    "GVTD":            "GVT&D.NS",
}

# ── Known-broken upstream tickers ─────────────────────────────
# When yfinance can't fetch a genuinely-listed stock (data-provider
# gap rather than delisted ticker), surface a specific note instead
# of the generic "check the symbol" message.
KNOWN_BROKEN_TICKERS: dict[str, str] = {
    # TATAMOTORS is now handled via TICKER_ALIASES → TMPV.NS (post-demerger)
}


def _inject_sector_medians_dict(payload: dict, ticker: str) -> dict:
    """Mutate-and-return a dict payload with sector_medians populated.

    Called on every return path of GET /analysis/{ticker} so warm cache
    hits (which were written before this field existed) still surface
    the chip context. Lookup is in-process + 15-min TTL so the warm
    path overhead is a single dict copy. Never raises — a lookup
    failure leaves the field absent (frontend chip self-hides).
    """
    if not isinstance(payload, dict):
        return payload
    try:
        from backend.services.sector_medians_for_ticker import (
            get_sector_medians_for_ticker,
        )
        payload["sector_medians"] = get_sector_medians_for_ticker(ticker)
    except Exception:
        # Field is descriptive only — never break the response.
        pass
    return payload


def _inject_sector_medians_model(result: "AnalysisResponse", ticker: str) -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_sector_medians_dict`.

    Used on the cold-compute return path where the response is still a
    typed `AnalysisResponse` instance. Mutates in place — the field is
    Optional and additive so no validation re-run is required.
    """
    try:
        from backend.services.sector_medians_for_ticker import (
            get_sector_medians_for_ticker,
        )
        result.sector_medians = get_sector_medians_for_ticker(ticker)
    except Exception:
        pass
    return result


def _inject_multiples_fv_dict(payload: dict) -> dict:
    """Populate `multiples_based_fv` + `multiples_method` on a dict payload.

    Sprint A2 (2026-06-09) — peer-relative cross-confirmation fair
    value. MUST run AFTER `_inject_sector_medians_dict` because it
    reads `payload["sector_medians"]`. Pure derivation from the
    response's own ticker PE/PB + cohort medians — no DB / cache I/O,
    so safe on every warm-path return (~microseconds).

    Never raises — chip failure leaves both fields absent (frontend
    pill row self-hides).
    """
    if not isinstance(payload, dict):
        return payload
    try:
        from backend.services.multiples_fv import compute_multiples_fv
        fv, method = compute_multiples_fv(payload, payload.get("sector_medians"))
        payload["multiples_based_fv"] = fv
        payload["multiples_method"] = method
    except Exception:
        # Field is purely descriptive — never break the response.
        pass
    return payload


def _inject_multiples_fv_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_multiples_fv_dict`.

    Used on the cold-compute return path. MUST run AFTER
    `_inject_sector_medians_model` so the sector medians are present
    on the response. Mutates in place — both fields are Optional and
    additive, no validation re-run required.
    """
    try:
        from backend.services.multiples_fv import compute_multiples_fv
        # Serialize the minimum needed slots — we only read
        # quality.{pe,pb}_ratio + valuation.current_price + sector_medians.
        # Using model_dump on the full result here would be cheap but a
        # focused dict keeps the contract obvious.
        _qual = result.quality.model_dump() if result.quality else {}
        _val = result.valuation.model_dump() if result.valuation else {}
        _payload_min = {
            "quality": _qual,
            "valuation": _val,
        }
        fv, method = compute_multiples_fv(_payload_min, result.sector_medians)
        result.multiples_based_fv = fv
        result.multiples_method = method
    except Exception:
        pass
    return result


def _composite_inputs_from_dict(payload: dict) -> dict:
    """Extract the composite-IV input set from a dict payload.

    Returns a kwargs dict for ``composite_iv_service.compute_composite_iv``
    so the four Phase-C estimator slots can be added without changing the
    call-site signature. Pulled out so the cold and warm paths share the
    exact same extraction logic.

    The analyst slot prefers the full Finnhub consensus block's
    ``price_target.mean`` (most precise); falls back to the legacy
    ``wall_street_avg_target`` slot for older cached payloads. The four
    Phase-C estimator slots (three_stage_fv / ddm_fv / epv_per_share /
    probability_weighted_fv) are read from the additive fields written
    by the Phase-B inject helpers — caller MUST run those injects
    BEFORE composite. None on any slot is honest: the composite service
    pro-rata redistributes the surviving weights.
    """
    valuation = payload.get("valuation") or {}
    insights = payload.get("insights") or {}
    quality = payload.get("quality") or {}
    company = payload.get("company") or {}
    dcf_fv = valuation.get("fair_value")
    multiples_fv = payload.get("multiples_based_fv")
    # Wall St analyst price-target mean — prefer the structured
    # consensus block (Finnhub-shaped, populated by service.py) over
    # the loose `wall_street_avg_target` slot.
    analyst_avg = None
    consensus = insights.get("analyst_consensus")
    if isinstance(consensus, dict):
        pt = consensus.get("price_target") or {}
        analyst_avg = pt.get("mean") or pt.get("median")
    if analyst_avg is None:
        analyst_avg = insights.get("wall_street_avg_target")
    # Phase-C estimator slots — populated by the Phase-B inject helpers.
    # Read straight off the payload; None when the helper's applicability
    # gate trimmed the estimator (correct posture: composite_iv_service
    # redistributes the surviving weights).
    three_stage_fv = payload.get("three_stage_fv")
    ddm_fv = payload.get("ddm_fv")
    epv_fv = payload.get("epv_per_share")
    probability_weighted_fv = payload.get("probability_weighted_fv")
    # Phase B mega-wiring (2026-06-10) — sector-primary engine output.
    # Populated by `_inject_sector_specific_dict` upstream. None for
    # tickers that don't route to any of the 13 sector-primary
    # engines (NBFC ROA / Insurance EV+VNB / Pharma pipeline / Telecom
    # ARPU / Oil&Gas / Auto OEM / Cement / Steel / RE developer /
    # Consumer durables / Media / Logistics / Holdco SOTP). When
    # present, composite_iv_service tilts the weights toward this
    # slot (0.40 default) and reduces DCF/Multiples/Analyst.
    sector_specific_fv = payload.get("sector_specific_fv")
    sector_specific_label = payload.get("sector_specific_label")
    # Stock kind / sector / ticker — used by the composite branch logic.
    stock_kind: str | None = None
    if quality.get("is_holdco"):
        stock_kind = "holdco"
    elif quality.get("is_bank"):
        stock_kind = "bank"
    sector = company.get("sector")
    ticker = payload.get("ticker") or company.get("ticker")
    return {
        "dcf_fv": dcf_fv,
        "multiples_fv": multiples_fv,
        "analyst_avg": analyst_avg,
        "three_stage_fv": three_stage_fv,
        "ddm_fv": ddm_fv,
        "epv_fv": epv_fv,
        "probability_weighted_fv": probability_weighted_fv,
        "sector_specific_fv": sector_specific_fv,
        "sector_specific_label": sector_specific_label,
        "stock_kind": stock_kind,
        "sector": sector,
        "ticker": ticker,
    }


def _inject_composite_iv_dict(payload: dict) -> dict:
    """Populate `composite_intrinsic_value` + `composite_components` on a
    dict payload.

    T1.1 engine refinement (2026-06-09) — weighted average of DCF +
    Multiples + Wall St.

    Phase C (2026-06-10) extends the average with the four additive
    Phase-B estimators (Three-stage DCF, DDM, EPV, Probability-
    weighted). Composite MUST therefore run AFTER both
    ``_inject_multiples_fv_dict`` AND the full Phase-B inject chain
    so the new estimator slots on the payload are populated when
    ``_composite_inputs_from_dict`` reads them. The call-chain
    orchestrator (`_inject_phase_b_estimators_dict` + this helper)
    is sequenced in the cache-path call sites accordingly. Pure
    derivation, no DB / cache I/O, safe on every warm-path return.

    Never raises — composite failure leaves both fields absent (the
    frontend falls back to the DCF-only "Fair Value" headline).
    """
    if not isinstance(payload, dict):
        return payload
    try:
        from backend.services.composite_iv_service import (
            compute_composite_iv,
            composite_to_dict,
        )
        inputs = _composite_inputs_from_dict(payload)
        result = compute_composite_iv(**inputs)
        as_dict = composite_to_dict(result)
        # ── Phase B mega-wiring: apply overlay multiplier when set ──
        # Overlay injects (`_inject_overlay_dict`) run BEFORE composite
        # and write `sector_overlay_multiplier` + `sector_overlay_label`
        # on the payload. The multiplier is applied here so the
        # composite's weighted-average math runs FIRST and the overlay
        # adjusts the headline value at the boundary.
        from backend.services.composite_iv_service import (
            apply_overlay_to_composite,
        )
        overlay_mult = payload.get("sector_overlay_multiplier")
        overlay_label = payload.get("sector_overlay_label")
        if as_dict["value"] is not None and overlay_mult is not None:
            adjusted, applied_mult, applied_label = apply_overlay_to_composite(
                as_dict["value"], overlay_mult, overlay_label or "overlay",
            )
            if adjusted is not None and applied_mult is not None:
                as_dict["value"] = adjusted
                if isinstance(as_dict.get("components"), dict):
                    as_dict["components"]["overlay_applied"] = {
                        "multiplier": applied_mult,
                        "label": applied_label,
                    }
        payload["composite_intrinsic_value"] = as_dict["value"]
        # composite_components carries both the per-estimator values
        # AND the method tag + extreme_divergence flag so the frontend
        # can branch on a single object without a parallel lookup.
        if as_dict["value"] is not None:
            payload["composite_components"] = {
                "components": as_dict["components"],
                "method": as_dict["method"],
                "extreme_divergence": as_dict["extreme_divergence"],
                "sector_specific_label": as_dict.get("sector_specific_label"),
            }
        else:
            payload["composite_components"] = None
        # ── Composite Composition transparency (2026-06-10) ──
        # Build the per-estimator breakdown payload so the frontend
        # can render the "Composite from N of 7 estimators" panel.
        # Pure derivation from composite_components + the *_fv slots
        # populated by the Phase-B inject chain — never touches I/O.
        # Defensive: a composition failure leaves the field absent
        # and the panel self-hides. See composite_composition_service.
        try:
            from backend.services.composite_composition_service import (
                build_composite_composition,
                composition_to_dict,
            )
            composition = build_composite_composition(
                payload=payload,
                composite_components=payload.get("composite_components"),
            )
            payload["composite_composition"] = composition_to_dict(composition)
        except Exception:
            # Inner-try mirror — the outer try only catches the import
            # / compute failure; the composition pass has its own guard
            # so a composition failure cannot poison the composite
            # write above (which has already succeeded by this point).
            payload["composite_composition"] = None
    except Exception:
        # Field is purely additive — never break the response.
        pass
    return payload


def _inject_composite_iv_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_composite_iv_dict`.

    Used on the cold-compute return path. MUST run AFTER
    `_inject_multiples_fv_model` AND the full Phase-B inject chain so
    the four Phase-C estimator slots (three_stage_fv / ddm_fv /
    epv_per_share / probability_weighted_fv) are populated on the
    AnalysisResponse model when this helper reads them. Mutates in
    place — both fields are Optional, no re-validation required.
    """
    try:
        from backend.services.composite_iv_service import (
            compute_composite_iv,
            composite_to_dict,
        )
        # Build a focused dict so we re-use the same extractor as the
        # warm path. Mirrors the multiples_fv_model contract. The four
        # Phase-C estimator fields are mirrored straight off the model
        # (populated by `_inject_phase_b_estimators_model` upstream).
        _qual = result.quality.model_dump() if result.quality else {}
        _val = result.valuation.model_dump() if result.valuation else {}
        _ins = result.insights.model_dump() if result.insights else {}
        _co = result.company.model_dump() if result.company else {}
        _payload = {
            "valuation": _val,
            "quality": _qual,
            "insights": _ins,
            "company": _co,
            "multiples_based_fv": result.multiples_based_fv,
            "three_stage_fv": getattr(result, "three_stage_fv", None),
            "ddm_fv": getattr(result, "ddm_fv", None),
            "epv_per_share": getattr(result, "epv_per_share", None),
            "probability_weighted_fv": getattr(
                result, "probability_weighted_fv", None
            ),
            "sector_specific_fv": getattr(result, "sector_specific_fv", None),
            "sector_specific_label": getattr(
                result, "sector_specific_label", None
            ),
            "ticker": result.ticker,
        }
        inputs = _composite_inputs_from_dict(_payload)
        composite = compute_composite_iv(**inputs)
        as_dict = composite_to_dict(composite)
        # ── Phase B mega-wiring: apply overlay multiplier when set ──
        # Overlay injects (`_inject_overlay_*`) run BEFORE composite and
        # write `sector_overlay_multiplier` + `sector_overlay_label` on
        # the model. The multiplier is applied here so the composite's
        # weighted-average math runs FIRST and the overlay adjusts the
        # headline value at the boundary.
        from backend.services.composite_iv_service import (
            apply_overlay_to_composite,
        )
        overlay_mult = getattr(result, "sector_overlay_multiplier", None)
        overlay_label = getattr(result, "sector_overlay_label", None)
        if as_dict["value"] is not None and overlay_mult is not None:
            adjusted, applied_mult, applied_label = apply_overlay_to_composite(
                as_dict["value"], overlay_mult, overlay_label or "overlay",
            )
            if adjusted is not None and applied_mult is not None:
                as_dict["value"] = adjusted
                # Stamp the overlay on the components dict so the
                # frontend can render an "overlay applied" badge.
                if isinstance(as_dict.get("components"), dict):
                    as_dict["components"]["overlay_applied"] = {
                        "multiplier": applied_mult,
                        "label": applied_label,
                    }
        result.composite_intrinsic_value = as_dict["value"]
        if as_dict["value"] is not None:
            result.composite_components = {
                "components": as_dict["components"],
                "method": as_dict["method"],
                "extreme_divergence": as_dict["extreme_divergence"],
                "sector_specific_label": as_dict.get("sector_specific_label"),
            }
        else:
            result.composite_components = None
        # ── Composite Composition transparency (2026-06-10) ──
        # Build the per-estimator breakdown payload so the frontend
        # can render the "Composite from N of 7 estimators" panel.
        # Mirrors the dict-variant inject above. Constructs a focused
        # dict view of the relevant model fields, passes it to the
        # shared service, writes the resulting payload back. Inner
        # try guard so a composition failure leaves the field absent
        # rather than tripping the outer composite handler.
        try:
            from backend.services.composite_composition_service import (
                build_composite_composition,
                composition_to_dict,
            )
            _comp_payload = {
                "valuation": _val,
                "insights": _ins,
                "multiples_based_fv": result.multiples_based_fv,
                "three_stage_fv": getattr(result, "three_stage_fv", None),
                "ddm_fv": getattr(result, "ddm_fv", None),
                "epv_per_share": getattr(result, "epv_per_share", None),
                "probability_weighted_fv": getattr(
                    result, "probability_weighted_fv", None
                ),
                "composite_intrinsic_value": result.composite_intrinsic_value,
                "ddm_reason": getattr(result, "ddm_reason", None),
                "epv_reason": getattr(result, "epv_reason", None),
                "three_stage_reason": getattr(
                    result, "three_stage_reason", None
                ),
                "probability_weighted_reason": getattr(
                    result, "probability_weighted_reason", None
                ),
            }
            composition = build_composite_composition(
                payload=_comp_payload,
                composite_components=result.composite_components,
            )
            result.composite_composition = composition_to_dict(composition)
        except Exception:
            result.composite_composition = None
    except Exception:
        pass
    return result


# ─────────────────────────────────────────────────────────────────
# Phase B — additive standalone-estimator surfacing (2026-06-10)
# ─────────────────────────────────────────────────────────────────
# Each of the five estimators below is a thin projection of its
# standalone Phase-A service into the AnalysisResponse payload. They
# follow the SAME contract as _inject_composite_iv_* above:
#
#   1. Lazy import — keeps cold start fast and avoids circular
#      dependency surprises if the service module shifts.
#   2. Pure derivation from the in-payload inputs — no DB, no cache,
#      no I/O.
#   3. Defensive — wrapped in try/except so a single ticker that
#      trips the estimator never breaks the wider response. Failure
#      leaves the field None and the frontend hides the chip.
#   4. Phase-B injects run AFTER the sector-medians + multiples
#      chain so the per-payload extraction sees the freshly-injected
#      multiples values. Phase C (2026-06-10) added an additional
#      ordering constraint: Phase-B injects MUST run BEFORE the
#      composite inject so the composite extractor can read the four
#      new estimator slots (three_stage_fv / ddm_fv / epv_per_share /
#      probability_weighted_fv) populated by the Phase-B helpers.
#      Canonical chain order (all five cache paths):
#          sector_medians -> multiples_fv -> phase_b -> composite
#
# Phase C (2026-06-10) extended the composite weighted average to
# include Three-stage DCF, DDM, EPV, and Probability-weighted FV.
# Liquidation and Replacement values surface as separate floor /
# Q signals on the analysis payload — they are NOT folded into the
# composite. See backend/services/composite_iv_service.py for the
# new weight distribution.
# ─────────────────────────────────────────────────────────────────

def _safe_payload_section(payload: dict, key: str) -> dict:
    """Return ``payload[key]`` as a dict, with a defensive {} fallback.

    Used by the Phase-B inject helpers to keep their input-extraction
    code branchless. Payloads coming off the cache occasionally carry
    legacy null sections (pre-PR-X payloads); a None section would
    otherwise raise AttributeError on the first .get() call.
    """
    section = payload.get(key)
    if not isinstance(section, dict):
        return {}
    return section


def _log_phase_b_inject_failure(
    estimator: str,
    ticker: "str | None",
    err: BaseException,
) -> None:
    """Structured-log a Phase-B inject helper exception.

    v_fix_phase_b_estimator_coverage_2026_06_10 — before this fix the
    five `_inject_*_dict` helpers swallowed every exception silently,
    which is why the HDFCBANK valuation-methods panel showed only 3 of
    9 estimators in prod. The helpers continue to never break the
    response — but they now emit one diagnosable structured line per
    failure so the next divergence is caught at the log layer rather
    than via a UI audit.

    Defensive — the logger itself is wrapped in try/except so a logger
    failure cannot escape and break the response either.
    """
    try:
        from backend.services.structured_logging import log_event
        log_event(
            "phase_b.inject_failed",
            level="WARN",
            estimator=estimator,
            ticker=ticker,
            error=str(err),
            error_type=type(err).__name__,
        )
    except Exception:  # noqa: BLE001 — defensive
        # Logging is best-effort. A logger failure must not propagate.
        pass


def _inject_ddm_dict(payload: dict) -> dict:
    """Populate ``ddm_fv`` + ``ddm_method`` on a dict payload.

    T2.1 (2026-06-10) — wires the standalone DDM service. Phase C
    (2026-06-10) reordered the inject chain — this helper now runs
    BEFORE `_inject_composite_iv_dict` so the composite extractor
    can read the ddm_fv slot it writes. Defensive — never raises;
    leaves both fields None on failure.

    Applicability is decided up-front by
    ``dividend_discount_model_service.is_ddm_applicable``: payout >=
    30%, dividend streak >= 5y, sector not in the excluded set
    (recent IPO, biotech, deep cyclical, holdco). When inapplicable
    the field stays None and the frontend hides the DDM chip.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        from backend.services.dividend_discount_model_service import (
            DDMInputs,
            is_ddm_applicable,
            select_and_compute,
        )
        quality = _safe_payload_section(payload, "quality")
        valuation = _safe_payload_section(payload, "valuation")
        insights = _safe_payload_section(payload, "insights")
        company = _safe_payload_section(payload, "company")
        ticker = payload.get("ticker") or company.get("ticker") or ""
        sector = company.get("sector")
        # ── Applicability gate ──
        # The canonical AnalysisResponse carries `payout_ratio_pct` on
        # DividendData as a percent (45.0, not 0.45). Try a decimal
        # `payout_ratio` slot first for any caller that mirrors it,
        # then derive from the pct field on the dividend block.
        dividend_block = insights.get("dividend") if isinstance(insights.get("dividend"), dict) else {}
        payout = quality.get("payout_ratio")
        if payout is None:
            payout_pct = dividend_block.get("payout_ratio_pct")
            if payout_pct is not None:
                try:
                    payout = float(payout_pct) / 100.0
                except (TypeError, ValueError):
                    payout = None
        # Streak — prefer the dividend.consecutive_years slot, fall
        # back to a quality slot for callers that mirror it there.
        streak = dividend_block.get("consecutive_years")
        if streak is None:
            streak = quality.get("dividend_streak_years")
        applicable, _reason = is_ddm_applicable(
            ticker=ticker,
            sector=sector,
            payout_ratio=payout,
            dividend_streak_years=streak,
        )
        if not applicable:
            payload["ddm_fv"] = None
            payload["ddm_method"] = None
            payload["ddm_reason"] = _reason
            return payload
        # ── Build DDM inputs ──
        # `current_dividend` is annual ₹/share — prefer the explicit
        # rate field, fall back to the last paid value, then to nothing.
        current_dividend = (
            dividend_block.get("dividend_rate_per_share")
            or dividend_block.get("last_dividend_value")
            or 0.0
        )
        # `cost_of_equity` — use the engine's discount_rate (WACC is the
        # closest proxy; pure cost-of-equity isn't surfaced).
        cost_of_equity = valuation.get("discount_rate") or valuation.get("wacc") or 0.115
        # `stable_growth` — terminal growth from the DCF.
        stable_growth = valuation.get("terminal_growth") or 0.04
        ddm_inputs = DDMInputs(
            current_dividend=float(current_dividend or 0.0),
            cost_of_equity=float(cost_of_equity or 0.0),
            stable_growth=float(stable_growth or 0.0),
            expected_payout_ratio=float(payout) if payout is not None else None,
        )
        result = select_and_compute(
            ticker=ticker,
            sector=sector,
            inputs=ddm_inputs,
        )
        payload["ddm_fv"] = result.fair_value
        payload["ddm_method"] = result.method
        if result.fair_value is None:
            payload["ddm_reason"] = (
                f"DDM compute returned method={result.method}; inputs "
                f"insufficient for a usable estimate"
            )
    except Exception as e:
        # Defensive — never break the response on a single estimator,
        # but emit a structured log so the failure mode is diagnosable
        # rather than vanishing into `pass`. v_fix_phase_b_estimator_
        # coverage_2026_06_10.
        _log_phase_b_inject_failure("ddm", payload.get("ticker"), e)
        payload["ddm_reason"] = "compute_failed"
    return payload


def _inject_ddm_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_ddm_dict`.

    Used on the cold-compute return path. Mirrors the warm-path
    contract: same extraction, same fallback chain, defensive.
    """
    try:
        _payload = {
            "ticker": result.ticker,
            "quality": result.quality.model_dump() if result.quality else {},
            "valuation": result.valuation.model_dump() if result.valuation else {},
            "insights": result.insights.model_dump() if result.insights else {},
            "company": result.company.model_dump() if result.company else {},
        }
        _inject_ddm_dict(_payload)
        result.ddm_fv = _payload.get("ddm_fv")
        result.ddm_method = _payload.get("ddm_method")
        result.ddm_reason = _payload.get("ddm_reason")
    except Exception as e:
        _log_phase_b_inject_failure("ddm_model", result.ticker, e)
    return result


def _inject_epv_dict(payload: dict) -> dict:
    """Populate ``epv_per_share`` + ``epv_growth_value_gap``.

    T2.2 (2026-06-10) — wires the standalone EPV (Greenwald) service.
    Phase C (2026-06-10) reordered the inject chain — this helper
    now runs BEFORE `_inject_composite_iv_dict` so the composite
    extractor can read the field it writes. Defensive.

    EPV needs full balance-sheet history arrays (revenue / EBIT / D&A
    / capex / working capital) which are NOT carried on the standard
    AnalysisResponse payload — they live in the financials table the
    analysis service queries during compute. When the history arrays
    aren't available on the payload (the warm cache path), this
    inject is a no-op (epv_per_share stays None and the frontend
    hides the chip). The cold compute path could be augmented to
    populate these from the financials lookup in a follow-up; Phase
    B's contract is "additive surfacing", not "wire new data source".
    """
    if not isinstance(payload, dict):
        return payload
    try:
        from backend.services.epv_service import (
            EPVInputs,
            compute_epv,
            is_epv_applicable,
        )
        quality = _safe_payload_section(payload, "quality")
        valuation = _safe_payload_section(payload, "valuation")
        company = _safe_payload_section(payload, "company")
        ticker = payload.get("ticker") or company.get("ticker") or ""
        sector = company.get("sector")
        # ── Pull history arrays ──
        # `computation_inputs` is the snapshot persisted alongside the
        # FV at compute time (see AnalysisResponse.computation_inputs).
        # We look for the EPV-shaped sub-block; absent means the cache
        # path didn't carry it.
        ci = payload.get("computation_inputs") if isinstance(payload.get("computation_inputs"), dict) else {}
        epv_block = ci.get("epv") if isinstance(ci.get("epv"), dict) else {}
        revenue_history = epv_block.get("revenue_history") or []
        ebit_history = epv_block.get("ebit_history") or []
        da_history = epv_block.get("da_history") or []
        capex_history = epv_block.get("capex_history") or []
        working_capital_history = epv_block.get("working_capital_history") or []
        # ── Applicability gate ──
        # Without history we can't compute — surface None cleanly.
        history_years = len(revenue_history) if isinstance(revenue_history, list) else 0
        has_neg_earnings = any(
            isinstance(e, (int, float)) and float(e) < 0 for e in (ebit_history or [])
        )
        applicable, _reason = is_epv_applicable(
            ticker=ticker,
            sector=sector,
            revenue_history_years=history_years,
            has_negative_earnings=has_neg_earnings,
        )
        if not applicable:
            payload["epv_per_share"] = None
            payload["epv_growth_value_gap"] = None
            payload["epv_reason"] = _reason
            return payload
        current_revenue = epv_block.get("current_revenue") or 0.0
        cost_of_capital = valuation.get("discount_rate") or valuation.get("wacc") or 0.115
        tax_rate = epv_block.get("tax_rate") or 0.25
        shares_outstanding = (
            epv_block.get("shares_outstanding")
            or quality.get("shares_outstanding")
            or 0.0
        )
        epv_inputs = EPVInputs(
            revenue_history=list(revenue_history),
            ebit_history=list(ebit_history),
            da_history=list(da_history),
            capex_history=list(capex_history),
            working_capital_history=list(working_capital_history),
            current_revenue=float(current_revenue or 0.0),
            cost_of_capital=float(cost_of_capital or 0.0),
            tax_rate=float(tax_rate or 0.0),
            shares_outstanding=float(shares_outstanding or 0.0),
        )
        # Pass the engine's DCF fair_value so the service computes the
        # growth_value_gap (DCF - EPV) in one shot.
        dcf_fv = valuation.get("fair_value")
        result = compute_epv(epv_inputs, dcf_fv=dcf_fv)
        payload["epv_per_share"] = result.epv_per_share
        payload["epv_growth_value_gap"] = result.growth_value_gap
        if result.epv_per_share is None:
            payload["epv_reason"] = (
                f"EPV compute returned method={getattr(result, 'method', 'unavailable')}; "
                "inputs insufficient for a meaningful estimate"
            )
    except Exception as e:
        _log_phase_b_inject_failure("epv", payload.get("ticker"), e)
        payload["epv_reason"] = "compute_failed"
    return payload


def _inject_epv_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_epv_dict`."""
    try:
        _payload = {
            "ticker": result.ticker,
            "quality": result.quality.model_dump() if result.quality else {},
            "valuation": result.valuation.model_dump() if result.valuation else {},
            "company": result.company.model_dump() if result.company else {},
            "computation_inputs": result.computation_inputs,
        }
        _inject_epv_dict(_payload)
        result.epv_per_share = _payload.get("epv_per_share")
        result.epv_growth_value_gap = _payload.get("epv_growth_value_gap")
        result.epv_reason = _payload.get("epv_reason")
    except Exception as e:
        _log_phase_b_inject_failure("epv_model", result.ticker, e)
    return result


def _inject_three_stage_dict(payload: dict) -> dict:
    """Populate ``three_stage_fv`` + ``three_stage_method``.

    T2.5 (2026-06-10) — wires the standalone three-stage DCF service.
    Phase C (2026-06-10) reordered the inject chain — this helper
    now runs BEFORE `_inject_composite_iv_dict` so the composite
    extractor can read the field it writes. Defensive.

    Uses `select_three_stage_default_horizons(sector)` to derive the
    (N1, N2) horizon defaults per cohort. The engine's existing
    high-growth-rate / terminal-growth / WACC are reused; net_debt
    comes from quality if available.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        from backend.services.three_stage_dcf_service import (
            ThreeStageInputs,
            compute_three_stage_dcf,
            is_three_stage_applicable,
            select_three_stage_default_horizons,
        )
        quality = _safe_payload_section(payload, "quality")
        valuation = _safe_payload_section(payload, "valuation")
        company = _safe_payload_section(payload, "company")
        ticker = payload.get("ticker") or company.get("ticker") or ""
        sector = company.get("sector")
        # ── Pull base FCF ──
        # Prefer the explicit normalized_fcf_cr (the reverse-DCF anchor —
        # already cyclical-aware), fall back to a fcf_history-derived
        # base from computation_inputs, fall back to None (which trips
        # the applicability gate).
        base_year_fcf = quality.get("normalized_fcf_cr")
        if base_year_fcf is None:
            ci = payload.get("computation_inputs") if isinstance(payload.get("computation_inputs"), dict) else {}
            ts_block = ci.get("three_stage") if isinstance(ci.get("three_stage"), dict) else {}
            base_year_fcf = ts_block.get("base_year_fcf")
        # ── Applicability gate ──
        # Need positive base FCF + at least 3y history; skip holdcos,
        # REITs, InvITs, ETFs (all dedicated frameworks).
        # FCF history years: best effort — we don't have a count on the
        # payload, so use 5 (a working default) when we DO have a base.
        # `is_three_stage_applicable` does an independent sector skip.
        applicable, _reason = is_three_stage_applicable(
            ticker=ticker,
            sector=sector,
            base_year_fcf=base_year_fcf,
            fcf_history_years=5,  # working default; real count lives in service.py
        )
        if not applicable:
            payload["three_stage_fv"] = None
            payload["three_stage_method"] = None
            payload["three_stage_reason"] = _reason
            return payload
        # ── Build inputs ──
        n1, n2 = select_three_stage_default_horizons(sector, is_recent_ipo=False)
        high_growth_rate = (
            valuation.get("fcf_growth_rate")
            or valuation.get("fcf_growth")
            or 0.10
        )
        terminal_growth = valuation.get("terminal_growth") or 0.04
        discount_rate = valuation.get("wacc") or valuation.get("discount_rate") or 0.115
        shares_outstanding = quality.get("shares_outstanding") or 0.0
        net_debt = quality.get("net_debt") or 0.0
        # Engine's existing two-stage FV — passed for gap reporting on the
        # internal result (we don't surface the gap as a field yet but the
        # service uses it to populate gap_to_two_stage_dcf for diagnostics).
        two_stage_fv = valuation.get("fair_value")
        ts_inputs = ThreeStageInputs(
            base_year_fcf=float(base_year_fcf or 0.0),
            high_growth_rate=float(high_growth_rate or 0.0),
            high_growth_years=int(n1),
            fade_years=int(n2),
            terminal_growth=float(terminal_growth or 0.0),
            discount_rate=float(discount_rate or 0.0),
            shares_outstanding=float(shares_outstanding or 0.0),
            net_debt=float(net_debt or 0.0),
        )
        result = compute_three_stage_dcf(
            ts_inputs,
            two_stage_dcf_for_comparison=two_stage_fv,
        )
        payload["three_stage_fv"] = result.fair_value_per_share
        payload["three_stage_method"] = result.method
        if result.fair_value_per_share is None:
            payload["three_stage_reason"] = (
                f"Three-stage DCF compute returned method={result.method}; "
                "inputs insufficient for a meaningful estimate"
            )
    except Exception as e:
        _log_phase_b_inject_failure("three_stage", payload.get("ticker"), e)
        payload["three_stage_reason"] = "compute_failed"
    return payload


def _inject_three_stage_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_three_stage_dict`."""
    try:
        _payload = {
            "ticker": result.ticker,
            "quality": result.quality.model_dump() if result.quality else {},
            "valuation": result.valuation.model_dump() if result.valuation else {},
            "company": result.company.model_dump() if result.company else {},
            "computation_inputs": result.computation_inputs,
        }
        _inject_three_stage_dict(_payload)
        result.three_stage_fv = _payload.get("three_stage_fv")
        result.three_stage_method = _payload.get("three_stage_method")
        result.three_stage_reason = _payload.get("three_stage_reason")
    except Exception as e:
        _log_phase_b_inject_failure("three_stage_model", result.ticker, e)
    return result


def _inject_liquidation_dict(payload: dict) -> dict:
    """Populate ``liquidation_per_share`` + ``liquidation_floor_safety_margin``.

    T2.8 (2026-06-10) — wires the standalone Graham-style liquidation
    service. MUST run AFTER `_inject_composite_iv_dict`. Defensive.

    Skipped for banks / NBFCs / insurers (capital-adequacy framework
    applies instead) and for asset-light cohorts (IT services, AMCs)
    where the floor under-states franchise value. Balance-sheet line
    items come from `computation_inputs.liquidation` when the snapshot
    captured them; absent means the chip stays hidden.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        from backend.services.liquidation_value_service import (
            LiquidationInputs,
            compute_liquidation_value,
            is_liquidation_meaningful,
        )
        quality = _safe_payload_section(payload, "quality")
        valuation = _safe_payload_section(payload, "valuation")
        company = _safe_payload_section(payload, "company")
        ticker = payload.get("ticker") or company.get("ticker") or ""
        sector = company.get("sector")
        # ── Applicability gate ──
        # The is_bank flag carries the bank classification we already
        # made; for the PP&E ratio we don't have a precomputed value
        # on the payload — pass None so the helper falls back to the
        # sector-level decision.
        meaningful, _reason = is_liquidation_meaningful(
            ticker=ticker,
            sector=sector,
            ppe_ratio=None,
        )
        if not meaningful:
            payload["liquidation_per_share"] = None
            payload["liquidation_floor_safety_margin"] = None
            payload["liquidation_reason"] = _reason
            return payload
        # Bank flag is a hard skip — even if the sector string doesn't
        # carry "bank", quality.is_bank is the canonical source.
        if quality.get("is_bank"):
            payload["liquidation_per_share"] = None
            payload["liquidation_floor_safety_margin"] = None
            payload["liquidation_reason"] = (
                "Not applicable for banks — regulatory capital ratios "
                "(CET1, Tier-1) are the canonical floor, not asset "
                "recovery"
            )
            return payload
        # ── Pull balance sheet ──
        ci = payload.get("computation_inputs") if isinstance(payload.get("computation_inputs"), dict) else {}
        bs = ci.get("liquidation") if isinstance(ci.get("liquidation"), dict) else {}
        # Without ANY balance-sheet line items, the floor would be 0
        # minus liabilities — a misleading negative. Surface None instead.
        if not bs:
            payload["liquidation_per_share"] = None
            payload["liquidation_floor_safety_margin"] = None
            payload["liquidation_reason"] = (
                "Balance-sheet line items required for the Graham "
                "liquidation floor are not captured on this snapshot"
            )
            return payload
        liq_inputs = LiquidationInputs(
            cash_and_equivalents=float(bs.get("cash_and_equivalents") or 0.0),
            short_term_investments=float(bs.get("short_term_investments") or 0.0),
            receivables=float(bs.get("receivables") or 0.0),
            inventory=float(bs.get("inventory") or 0.0),
            inventory_raw_materials=bs.get("inventory_raw_materials"),
            inventory_wip=bs.get("inventory_wip"),
            inventory_finished=bs.get("inventory_finished"),
            ppe_gross=float(bs.get("ppe_gross") or 0.0),
            ppe_net=float(bs.get("ppe_net") or 0.0),
            intangibles=float(bs.get("intangibles") or 0.0),
            goodwill=float(bs.get("goodwill") or 0.0),
            long_term_investments=float(bs.get("long_term_investments") or 0.0),
            other_assets=float(bs.get("other_assets") or 0.0),
            short_term_debt=float(bs.get("short_term_debt") or 0.0),
            long_term_debt=float(bs.get("long_term_debt") or 0.0),
            accounts_payable=float(bs.get("accounts_payable") or 0.0),
            other_liabilities=float(bs.get("other_liabilities") or 0.0),
            shares_outstanding=float(bs.get("shares_outstanding") or quality.get("shares_outstanding") or 0.0),
            sector=sector,
        )
        current_price = valuation.get("current_price")
        result = compute_liquidation_value(liq_inputs, current_price=current_price)
        payload["liquidation_per_share"] = result.liquidation_per_share
        payload["liquidation_floor_safety_margin"] = result.floor_safety_margin
        if result.liquidation_per_share is None:
            payload["liquidation_reason"] = (
                "Liquidation compute returned no per-share floor — "
                "balance-sheet line items insufficient"
            )
    except Exception as e:
        _log_phase_b_inject_failure("liquidation", payload.get("ticker"), e)
        payload["liquidation_reason"] = "compute_failed"
    return payload


def _inject_liquidation_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_liquidation_dict`."""
    try:
        _payload = {
            "ticker": result.ticker,
            "quality": result.quality.model_dump() if result.quality else {},
            "valuation": result.valuation.model_dump() if result.valuation else {},
            "company": result.company.model_dump() if result.company else {},
            "computation_inputs": result.computation_inputs,
        }
        _inject_liquidation_dict(_payload)
        result.liquidation_per_share = _payload.get("liquidation_per_share")
        result.liquidation_floor_safety_margin = _payload.get(
            "liquidation_floor_safety_margin"
        )
        result.liquidation_reason = _payload.get("liquidation_reason")
    except Exception as e:
        _log_phase_b_inject_failure("liquidation_model", result.ticker, e)
    return result


def _inject_probability_weighted_dict(payload: dict) -> dict:
    """Populate ``probability_weighted_fv`` + ``probability_weighted_method``.

    T2.4 (2026-06-10) — wires the standalone probability-weighted FV
    service. MUST run AFTER `_inject_composite_iv_dict`. Defensive.

    Inputs are the existing bull/base/bear scenarios already on the
    valuation block — no new data source. Weight adjustments are
    derived from sector (cyclical flatten) and beta (high-beta widen
    tails). Earnings revisions and macro regime are left None for
    now — they'd require integrating the analyst-revision and macro
    services and add complexity for marginal gain.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        from backend.services.probability_weighted_fv_service import (
            ScenarioInputs,
            compute_probability_weighted_fv,
        )
        valuation = _safe_payload_section(payload, "valuation")
        quality = _safe_payload_section(payload, "quality")
        company = _safe_payload_section(payload, "company")
        bull_fv = valuation.get("bull_case")
        base_fv = valuation.get("base_case") or valuation.get("fair_value")
        bear_fv = valuation.get("bear_case")
        # ── Applicability gate ──
        # All three scenarios must be positive for a meaningful mix; the
        # service itself returns method="unavailable" otherwise, but we
        # also gate here so the field stays clean None rather than the
        # unavailable tag.
        try:
            _b1 = float(bull_fv or 0.0)
            _b2 = float(base_fv or 0.0)
            _b3 = float(bear_fv or 0.0)
        except (TypeError, ValueError):
            payload["probability_weighted_fv"] = None
            payload["probability_weighted_method"] = None
            payload["probability_weighted_reason"] = (
                "bull/base/bear scenarios not numeric"
            )
            return payload
        if _b1 <= 0 or _b2 <= 0 or _b3 <= 0:
            payload["probability_weighted_fv"] = None
            payload["probability_weighted_method"] = None
            payload["probability_weighted_reason"] = (
                "At least one of bull/base/bear scenarios is non-positive; "
                "weighted mix requires three credible scenario FVs"
            )
            return payload
        scenario_inputs = ScenarioInputs(
            bull_fv=_b1,
            base_fv=_b2,
            bear_fv=_b3,
            sector=company.get("sector"),
            beta=quality.get("beta"),
        )
        result = compute_probability_weighted_fv(scenario_inputs)
        payload["probability_weighted_fv"] = result.weighted_fv
        payload["probability_weighted_method"] = result.method
        if result.weighted_fv is None:
            payload["probability_weighted_reason"] = (
                f"Probability-weighted compute returned method={result.method}; "
                "scenarios insufficient for a defensible mix"
            )
    except Exception as e:
        _log_phase_b_inject_failure(
            "probability_weighted", payload.get("ticker"), e,
        )
        payload["probability_weighted_reason"] = "compute_failed"
    return payload


def _inject_probability_weighted_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_probability_weighted_dict`."""
    try:
        _payload = {
            "valuation": result.valuation.model_dump() if result.valuation else {},
            "quality": result.quality.model_dump() if result.quality else {},
            "company": result.company.model_dump() if result.company else {},
        }
        _inject_probability_weighted_dict(_payload)
        result.probability_weighted_fv = _payload.get("probability_weighted_fv")
        result.probability_weighted_method = _payload.get(
            "probability_weighted_method"
        )
        result.probability_weighted_reason = _payload.get(
            "probability_weighted_reason"
        )
    except Exception as e:
        _log_phase_b_inject_failure(
            "probability_weighted_model", result.ticker, e,
        )
    return result


#: Sector keywords where the Tobin-Q-style replacement-value frame
#: distorts more than it informs. Banks / NBFCs / insurers value
#: the franchise (deposit base, capital, embedded value), not the
#: replaceable asset base. AMCs and IT services are asset-light —
#: replacement understates them. v_fix_phase_b_estimator_coverage_2026_06_10.
_REPLACEMENT_SECTOR_SKIP_KEYWORDS: tuple[str, ...] = (
    "bank",
    "banking",
    "nbfc",
    "insurance",
    "insurer",
    "life insurance",
    "general insurance",
    "amc",
    "asset management",
    "broker",
    "exchange",
    "financial services",
    "diversified financials",
)


def _inject_replacement_dict(payload: dict) -> dict:
    """Populate ``replacement_per_share`` + ``replacement_method``.

    T2.3 Phase B wiring (v_fix_phase_b_estimator_coverage_2026_06_10).
    Wraps ``backend.services.replacement_value_service`` so the
    Valuation Methods Panel can render the Tobin-Q-style rebuild cost
    alongside the Graham liquidation floor. Defensive — never raises.

    Applicability — skipped for the financial cohort (banks, NBFCs,
    insurers, AMCs, brokers, exchanges): for those names the asset
    base does NOT carry franchise value and the rebuild-cost frame
    misleads. The ``replacement_reason`` carries the "Not applicable
    for ..." explanation so the frontend can surface a clean
    descriptor instead of a hidden field.

    Balance-sheet inputs come from ``computation_inputs.replacement``
    when the snapshot captured them; absent leaves ``method``
    unavailable with a reason tag.
    """
    if not isinstance(payload, dict):
        return payload
    payload.setdefault("replacement_per_share", None)
    payload.setdefault("replacement_method", None)
    payload.setdefault("replacement_reason", None)
    try:
        from backend.services.replacement_value_service import (
            ReplacementValueInputs,
            compute_replacement_value,
        )
        quality = _safe_payload_section(payload, "quality")
        valuation = _safe_payload_section(payload, "valuation")
        company = _safe_payload_section(payload, "company")
        ticker = payload.get("ticker") or company.get("ticker") or ""
        sector = company.get("sector")
        # ── Applicability gate ──
        # Bank flag is the canonical source (matches the liquidation
        # path). After that, the sector keyword set covers the rest of
        # the financial / asset-light cohort.
        if quality.get("is_bank"):
            payload["replacement_reason"] = (
                "Not applicable for banks — the franchise is the "
                "deposit base + capital, not the rebuildable asset "
                "base"
            )
            return payload
        if sector:
            sector_lower = str(sector).strip().lower()
            for kw in _REPLACEMENT_SECTOR_SKIP_KEYWORDS:
                if kw in sector_lower:
                    payload["replacement_reason"] = (
                        f"Not applicable for {sector} — replacement "
                        "value distorts for financial / asset-light "
                        "businesses where the asset base does not "
                        "carry the franchise"
                    )
                    return payload
        # ── Pull balance sheet ──
        ci = payload.get("computation_inputs") if isinstance(
            payload.get("computation_inputs"), dict
        ) else {}
        rep_block = ci.get("replacement") if isinstance(ci.get("replacement"), dict) else {}
        # Without PP&E we cannot compute a defensible rebuild cost.
        # Try the liquidation block as a fallback — it carries
        # ppe_gross and is captured by the same balance-sheet
        # snapshot.
        if not rep_block:
            rep_block = ci.get("liquidation") if isinstance(ci.get("liquidation"), dict) else {}
        ppe_gross = rep_block.get("ppe_gross") if rep_block else None
        if ppe_gross is None or float(ppe_gross or 0.0) <= 0.0:
            payload["replacement_reason"] = (
                "Balance-sheet PP&E required for the replacement-cost "
                "estimate is not captured on this snapshot"
            )
            return payload
        rep_inputs = ReplacementValueInputs(
            ppe_gross=float(ppe_gross or 0.0),
            intangibles_book=float(rep_block.get("intangibles") or 0.0),
            goodwill=float(rep_block.get("goodwill") or 0.0),
            working_capital_required=float(
                rep_block.get("working_capital_required")
                or rep_block.get("working_capital")
                or 0.0
            ),
            cash_required_for_ops=float(
                rep_block.get("cash_required_for_ops")
                or rep_block.get("cash_and_equivalents")
                or 0.0
            ),
            total_debt=float(
                rep_block.get("total_debt")
                or (
                    (rep_block.get("short_term_debt") or 0.0)
                    + (rep_block.get("long_term_debt") or 0.0)
                )
            ),
            shares_outstanding=float(
                rep_block.get("shares_outstanding")
                or quality.get("shares_outstanding")
                or 0.0
            ),
            sector=sector,
        )
        market_cap = valuation.get("market_cap_inr_cr") or quality.get(
            "market_cap_inr_cr"
        )
        result = compute_replacement_value(
            rep_inputs,
            market_cap_inr_cr=(
                float(market_cap) if market_cap is not None else None
            ),
        )
        payload["replacement_per_share"] = result.replacement_value_per_share
        payload["replacement_method"] = result.method
        if result.replacement_value_per_share is None:
            payload["replacement_reason"] = (
                f"Replacement compute returned method={result.method} — "
                "inputs insufficient for a defensible per-share rebuild "
                "cost"
            )
    except Exception as e:
        _log_phase_b_inject_failure("replacement", payload.get("ticker"), e)
        payload["replacement_reason"] = "compute_failed"
    return payload


def _inject_replacement_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_replacement_dict`."""
    try:
        _payload = {
            "ticker": result.ticker,
            "quality": result.quality.model_dump() if result.quality else {},
            "valuation": result.valuation.model_dump() if result.valuation else {},
            "company": result.company.model_dump() if result.company else {},
            "computation_inputs": result.computation_inputs,
        }
        _inject_replacement_dict(_payload)
        result.replacement_per_share = _payload.get("replacement_per_share")
        result.replacement_method = _payload.get("replacement_method")
        result.replacement_reason = _payload.get("replacement_reason")
    except Exception as e:
        _log_phase_b_inject_failure("replacement_model", result.ticker, e)
    return result


def _inject_sector_specific_dict(payload: dict) -> dict:
    """Populate ``sector_specific_fv`` + ``sector_specific_label``.

    Phase B mega-wiring (2026-06-10). Routes the ticker through the
    appropriate sector-primary engine when applicable. Returns the
    same dict with two new keys set (both None on a non-routed ticker).

    Engines tried, in priority order — first that returns a positive
    FV wins:
      1. Holdco SOTP        (HOLDING_COMPANIES set membership)
      2. NBFC ROA tree      (NBFC_TICKERS map)
      3. Insurance EV+VNB   (life insurance ticker set)
      4. Pharma pipeline    (pharma cohort + curated seed data)
      5. Telecom ARPU DCF   (TELECOM_TICKERS set)
      6. Oil&Gas SOTP       (OIL_GAS_TICKERS map)
      7. Auto OEM cycle     (AUTO_OEM_TICKERS map)
      8. Cement utilization (CEMENT_TICKERS map)
      9. Steel cost curve   (STEEL_TICKERS map)
     10. RE developer NAV   (RE_DEVELOPER_TICKERS map)
     11. Consumer durables  (CONSUMER_DURABLES_TICKERS set)
     12. Media LTV          (MEDIA_TICKERS map)
     13. Logistics freight  (LOGISTICS_TICKERS map)

    Each engine call is wrapped in its own try/except so a single
    engine failing for one ticker can never break the response — the
    field stays None and the composite falls back to the headline
    DCF + Multiples + Wall St scheme. Engines that need data the
    payload doesn't carry (e.g. operating-cycle history for consumer
    durables, full subscriber forecasts for telecom) return None
    here and the composite is unaffected.
    """
    if not isinstance(payload, dict):
        return payload
    # Defensive default — never let downstream readers crash on a
    # missing key.
    payload.setdefault("sector_specific_fv", None)
    payload.setdefault("sector_specific_label", None)
    try:
        company = _safe_payload_section(payload, "company")
        ticker = payload.get("ticker") or company.get("ticker") or ""
        sector = company.get("sector")
        fv, label = _resolve_sector_primary_fv(ticker, sector, payload)
        if fv is not None and label:
            payload["sector_specific_fv"] = fv
            payload["sector_specific_label"] = label
    except Exception:
        # Defensive — never break the response on a single estimator.
        pass
    return payload


def _inject_sector_specific_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_sector_specific_dict`."""
    try:
        _payload = {
            "ticker": result.ticker,
            "quality": result.quality.model_dump() if result.quality else {},
            "valuation": result.valuation.model_dump() if result.valuation else {},
            "company": result.company.model_dump() if result.company else {},
            "insights": result.insights.model_dump() if result.insights else {},
            "computation_inputs": result.computation_inputs,
        }
        _inject_sector_specific_dict(_payload)
        result.sector_specific_fv = _payload.get("sector_specific_fv")
        result.sector_specific_label = _payload.get("sector_specific_label")
    except Exception:
        pass
    return result


def _inject_overlay_dict(payload: dict) -> dict:
    """Populate ``sector_overlay_multiplier`` + ``sector_overlay_label``.

    Phase B mega-wiring (2026-06-10). Two overlay engines:

      * IT services overlay (`it_services_overlay_service.compute_it_overlay`)
        — applies to TCS / INFY / WIPRO / HCLTECH / TECHM / LTIM and the
        broader IT_TICKERS set. Compound multiplier in [0.74, 1.16].
      * Utilities maintenance (`utilities_maintenance_capex_service`)
        — applies to POWERGRID / NTPC and the broader UTILITIES_TICKERS
        set. Owner-earnings / reported-FCF ratio as multiplier.

    The multiplier is APPLIED to the composite by
    `_inject_composite_iv_dict` AFTER it computes the weighted average
    — this helper just records the multiplier on the payload so the
    composite step can pick it up. Setting two fields keeps the
    contract symmetric with sector_specific (both are populated by
    inject helpers; both are consumed by the composite step).

    Defensive — when neither overlay applies, both fields stay None
    and the composite goes through unchanged.
    """
    if not isinstance(payload, dict):
        return payload
    payload.setdefault("sector_overlay_multiplier", None)
    payload.setdefault("sector_overlay_label", None)
    try:
        company = _safe_payload_section(payload, "company")
        ticker = payload.get("ticker") or company.get("ticker") or ""
        sector = company.get("sector")
        mult, label = _resolve_overlay_multiplier(ticker, sector, payload)
        if mult is not None and label:
            payload["sector_overlay_multiplier"] = mult
            payload["sector_overlay_label"] = label
    except Exception:
        pass
    return payload


def _inject_overlay_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_overlay_dict`."""
    try:
        _payload = {
            "ticker": result.ticker,
            "quality": result.quality.model_dump() if result.quality else {},
            "valuation": result.valuation.model_dump() if result.valuation else {},
            "company": result.company.model_dump() if result.company else {},
            "computation_inputs": result.computation_inputs,
        }
        _inject_overlay_dict(_payload)
        result.sector_overlay_multiplier = _payload.get(
            "sector_overlay_multiplier"
        )
        result.sector_overlay_label = _payload.get("sector_overlay_label")
    except Exception:
        pass
    return result


def _resolve_sector_primary_fv(
    ticker: str,
    sector: "str | None",
    payload: dict,
) -> "tuple[float | None, str | None]":
    """Try each sector-primary engine in priority order.

    Returns ``(fair_value_per_share, engine_label)`` on the first
    engine that emits a positive FV. ``(None, None)`` when no engine
    applies OR when every applicable engine returned None.

    The dispatcher uses the payload to source inputs for each engine.
    When the payload doesn't carry an engine's required inputs (e.g.
    `computation_inputs.nbfc_inputs` missing for a routed NBFC ticker),
    that engine returns None and the dispatcher falls through to the
    next candidate. Per-engine input mapping lives in
    `_compute_<engine>_fv` helpers below for testability.
    """
    if not ticker:
        return None, None
    quality = _safe_payload_section(payload, "quality")
    valuation = _safe_payload_section(payload, "valuation")
    insights = _safe_payload_section(payload, "insights")
    company = _safe_payload_section(payload, "company")
    ci = payload.get("computation_inputs") if isinstance(
        payload.get("computation_inputs"), dict
    ) else {}

    # ── 1. Holdco SOTP — pure holding companies bypass everything.
    try:
        from backend.services.holdco_sotp_service import (
            is_holdco_sotp_applicable,
        )
        from backend.services.analysis.constants import HOLDING_COMPANIES
        applicable, _ = is_holdco_sotp_applicable(ticker, HOLDING_COMPANIES)
        if applicable:
            fv = _compute_holdco_sotp_fv(ticker, ci, quality)
            if fv is not None:
                return fv, "holdco_sotp"
            # If applicable but FV failed, still no fallback to
            # NBFC/other sector engines — holdcos are a hard route.
            return None, None
    except Exception:
        pass

    # ── 1b. Bank deepened residual income (T3.1 Phase A).
    # Wired in v_fix_phase_b_estimator_coverage_2026_06_10. When the
    # ticker / sector is in the bank/NBFC/insurance cohort AND we have
    # NIM data on the snapshot, the deepened engine is the primary FV
    # — surfaces as `sector_specific_fv` with label
    # "bank_residual_income_deepened" so the composite weighting + the
    # frontend valuation panel both see it as a sector-specific signal
    # (distinct from the headline DCF row which uses pb_residual_income).
    try:
        from backend.services.financial_valuation_service import (
            is_bank_deepening_meaningful,
        )
        bank_ci = ci.get("bank_deepened") if isinstance(ci.get("bank_deepened"), dict) else {}
        has_nim_data = bool(bank_ci.get("nim_pct"))
        meaningful, _ = is_bank_deepening_meaningful(
            ticker=ticker,
            sector=sector,
            has_nim_data=has_nim_data,
        )
        if meaningful:
            fv = _compute_bank_deepened_fv(ticker, ci, quality, valuation)
            if fv is not None:
                return fv, "bank_residual_income_deepened"
            # When NIM data exists but the compute returns None
            # (degenerate inputs), still no fallthrough to NBFC — the
            # bank route is the canonical home and the composite
            # tolerates None sector_specific.
            if quality.get("is_bank"):
                return None, None
    except Exception:
        pass

    # ── 2. NBFC ROA tree.
    try:
        from backend.services.nbfc_roa_service import is_nbfc_applicable
        applicable, _ = is_nbfc_applicable(ticker, sector)
        if applicable:
            fv = _compute_nbfc_fv(ticker, ci, quality, valuation)
            if fv is not None:
                return fv, "nbfc_roa"
    except Exception:
        pass

    # ── 3. Insurance EV+VNB.
    try:
        from backend.services.insurance_appraisal_service import (
            is_ev_vnb_applicable,
        )
        if is_ev_vnb_applicable(ticker, sector):
            fv = _compute_insurance_fv(ticker, ci, quality)
            if fv is not None:
                return fv, "insurance_ev_vnb"
    except Exception:
        pass

    # ── 4. Pharma pipeline rNPV (only with curated data).
    try:
        from backend.services.pharma_pipeline_service import (
            has_curated_pipeline_data,
            is_pharma_pipeline_meaningful,
        )
        has_data = False
        try:
            has_data = bool(has_curated_pipeline_data(ticker))
        except Exception:
            has_data = False
        meaningful, _ = is_pharma_pipeline_meaningful(
            ticker, sector, has_data,
        )
        if meaningful:
            fv = _compute_pharma_pipeline_fv(ticker, ci, quality)
            if fv is not None:
                return fv, "pharma_pipeline"
    except Exception:
        pass

    # ── 5. Telecom ARPU DCF.
    try:
        from backend.services.telecom_arpu_service import (
            is_telecom_arpu_applicable,
        )
        applicable, _ = is_telecom_arpu_applicable(ticker, sector)
        if applicable:
            fv = _compute_telecom_fv(ticker, ci, quality, valuation)
            if fv is not None:
                return fv, "telecom_arpu"
    except Exception:
        pass

    # ── 6. Oil & Gas (upstream / downstream / integrated SOTP).
    try:
        from backend.services.oil_gas_valuation_service import (
            is_oil_gas_applicable,
        )
        applicable, _ = is_oil_gas_applicable(ticker, sector)
        if applicable:
            fv = _compute_oil_gas_fv(ticker, ci, quality)
            if fv is not None:
                return fv, "oil_gas"
    except Exception:
        pass

    # ── 7. Auto OEM cycle-adjusted.
    try:
        from backend.services.auto_oem_cycle_service import (
            is_auto_oem_applicable,
        )
        applicable, _ = is_auto_oem_applicable(ticker, sector)
        if applicable:
            fv = _compute_auto_oem_fv(ticker, ci, quality)
            if fv is not None:
                return fv, "auto_oem_cycle"
    except Exception:
        pass

    # ── 8. Cement capacity utilization.
    try:
        from backend.services.cement_utilization_service import (
            is_cement_applicable,
        )
        applicable, _ = is_cement_applicable(ticker, sector)
        if applicable:
            fv = _compute_cement_fv(ticker, ci, quality)
            if fv is not None:
                return fv, "cement_utilization"
    except Exception:
        pass

    # ── 9. Steel cost-curve quartile.
    try:
        from backend.services.steel_cost_curve_service import (
            is_steel_applicable,
        )
        applicable, _ = is_steel_applicable(ticker, sector)
        if applicable:
            fv = _compute_steel_fv(ticker, ci, quality)
            if fv is not None:
                return fv, "steel_cost_curve"
    except Exception:
        pass

    # ── 10. Real estate developer NAV.
    try:
        from backend.services.real_estate_developer_service import (
            is_re_developer_applicable,
        )
        gate_result = is_re_developer_applicable(ticker, sector)
        # service returns either (bool, str) tuple or just bool depending
        # on caller — normalize defensively.
        applicable = (
            gate_result[0] if isinstance(gate_result, tuple) else bool(gate_result)
        )
        if applicable:
            fv = _compute_re_developer_fv(ticker, ci, quality)
            if fv is not None:
                return fv, "re_developer_nav"
    except Exception:
        pass

    # ── 11. Consumer durables WC drag.
    try:
        from backend.services.consumer_durables_wc_service import (
            is_consumer_durables_applicable,
        )
        applicable, _ = is_consumer_durables_applicable(ticker, sector)
        if applicable:
            fv = _compute_consumer_durables_fv(ticker, ci, quality)
            if fv is not None:
                return fv, "consumer_durables_wc"
    except Exception:
        pass

    # ── 12. Media subscriber LTV.
    try:
        from backend.services.media_subscriber_ltv_service import (
            is_media_applicable,
        )
        applicable, _ = is_media_applicable(ticker, sector)
        if applicable:
            fv = _compute_media_fv(ticker, ci, quality)
            if fv is not None:
                return fv, "media_subscriber_ltv"
    except Exception:
        pass

    # ── 13. Logistics freight volume × yield.
    try:
        from backend.services.logistics_freight_service import (
            is_logistics_applicable,
        )
        applicable, _ = is_logistics_applicable(ticker, sector)
        if applicable:
            fv = _compute_logistics_fv(ticker, ci, quality)
            if fv is not None:
                return fv, "logistics_freight"
    except Exception:
        pass

    return None, None


def _resolve_overlay_multiplier(
    ticker: str,
    sector: "str | None",
    payload: dict,
) -> "tuple[float | None, str | None]":
    """Try IT-services and utilities-maintenance overlays in priority order.

    Returns ``(multiplier, label)`` on the first applicable overlay.
    ``(None, None)`` when no overlay applies or when the engine
    couldn't compute (missing inputs).

    Only ONE overlay is applied per ticker — IT services takes
    precedence over utilities maintenance because the IT_TICKERS and
    UTILITIES_TICKERS sets don't intersect in practice anyway, but
    documenting the priority makes the contract explicit.
    """
    if not ticker:
        return None, None
    quality = _safe_payload_section(payload, "quality")
    valuation = _safe_payload_section(payload, "valuation")
    company = _safe_payload_section(payload, "company")
    ci = payload.get("computation_inputs") if isinstance(
        payload.get("computation_inputs"), dict
    ) else {}

    # ── IT services overlay.
    try:
        from backend.services.it_services_overlay_service import (
            is_it_overlay_applicable,
        )
        applicable, _ = is_it_overlay_applicable(ticker, sector)
        if applicable:
            mult = _compute_it_overlay_multiplier(ticker, ci, quality, valuation)
            if mult is not None:
                return mult, "it_services_overlay"
    except Exception:
        pass

    # ── Utilities maintenance overlay.
    try:
        from backend.services.utilities_maintenance_capex_service import (
            is_utilities_maint_applicable,
        )
        applicable, _ = is_utilities_maint_applicable(ticker, sector)
        if applicable:
            mult = _compute_utilities_overlay_multiplier(
                ticker, ci, quality, valuation,
            )
            if mult is not None:
                return mult, "utilities_maintenance"
    except Exception:
        pass

    return None, None


# ─────────────────────────────────────────────────────────────────
# Per-engine FV helpers — each pulls inputs from the payload-level
# `computation_inputs` snapshot (when the cold-compute path captured
# them) and short-circuits to None when the inputs aren't available.
# Returning None is honest — the dispatcher falls through and the
# composite uses the headline DCF + Multiples + Wall St scheme.
# ─────────────────────────────────────────────────────────────────


def _ci_block(ci: dict, key: str) -> dict:
    """Return ``ci[key]`` as a dict, with a defensive {} fallback."""
    if not isinstance(ci, dict):
        return {}
    block = ci.get(key)
    if not isinstance(block, dict):
        return {}
    return block


def _coerce_pos(value) -> "float | None":
    """Return float(value) > 0, else None. Same posture as composite_iv_service."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")) or f <= 0:
        return None
    return f


def _compute_bank_deepened_fv(
    ticker: str,
    ci: dict,
    quality: dict,
    valuation: dict,
) -> "float | None":
    """Compute bank deepened residual-income FV per share.

    v_fix_phase_b_estimator_coverage_2026_06_10 — wires the T3.1 Phase A
    deepened-bank service (NIM + CASA + PCR + DuPont attribution) into
    ``_resolve_sector_primary_fv`` so HDFCBANK and the rest of the
    private + PSU bank + HFC + life-insurance cohort emit a
    ``sector_specific_fv`` distinct from the headline DCF row.

    Inputs come from the ``computation_inputs.bank_deepened`` block
    when the snapshot captured them. Without NIM data the upstream
    gate has already rejected the route, so this helper only runs
    with a meaningful block.

    Returns ``None`` on any failure — the dispatcher then surfaces
    None for ``sector_specific_fv`` and the composite weights pro-rata
    redistribute among the engines that DID compute.
    """
    try:
        from backend.services.financial_valuation_service import (
            BankDeepenedInputs,
            compute_deepened_bank_valuation,
        )
        block = _ci_block(ci, "bank_deepened")
        # Book value + ROE + COE + g + payout are the always-required
        # five P/B residual-income anchors. Fall back to quality fields
        # for the items mirrored there.
        bvps = _coerce_pos(
            block.get("book_value_per_share")
            or quality.get("book_value_per_share")
        )
        roe = block.get("roe_pct")
        if roe is None:
            roe_pct = quality.get("roe_pct")
            if roe_pct is not None:
                try:
                    roe = float(roe_pct) / 100.0
                except (TypeError, ValueError):
                    roe = None
        if bvps is None or roe is None:
            return None
        coe = float(
            block.get("cost_of_equity")
            or valuation.get("discount_rate")
            or valuation.get("wacc")
            or 0.125
        )
        g = float(
            block.get("sustainable_growth")
            or valuation.get("terminal_growth")
            or 0.10
        )
        payout = block.get("payout_ratio")
        if payout is None:
            payout = quality.get("payout_ratio")
            if payout is None:
                payout_pct = quality.get("payout_ratio_pct")
                if payout_pct is not None:
                    try:
                        payout = float(payout_pct) / 100.0
                    except (TypeError, ValueError):
                        payout = None
        inputs = BankDeepenedInputs(
            book_value_per_share=float(bvps),
            roe_pct=float(roe),
            cost_of_equity=float(coe),
            sustainable_growth=float(g),
            payout_ratio=float(payout) if payout is not None else 0.25,
            nim_pct=block.get("nim_pct"),
            yield_on_advances_pct=block.get("yield_on_advances_pct"),
            cost_of_funds_pct=block.get("cost_of_funds_pct"),
            casa_mix_pct=block.get("casa_mix_pct"),
            provision_coverage_pct=block.get("provision_coverage_pct"),
            gnpa_pct=block.get("gnpa_pct"),
            loan_growth_pct=block.get("loan_growth_pct"),
            fee_income_pct_of_revenue=block.get("fee_income_pct_of_revenue"),
            cost_to_income_pct=block.get("cost_to_income_pct"),
            tax_rate_pct=block.get("tax_rate_pct"),
            credit_cost_pct=block.get("credit_cost_pct"),
            equity_to_assets_pct=block.get("equity_to_assets_pct"),
        )
        result = compute_deepened_bank_valuation(inputs)
        return _coerce_pos(result.fair_value_per_share)
    except Exception as e:
        _log_phase_b_inject_failure("bank_deepened_fv", ticker, e)
        return None


def _compute_holdco_sotp_fv(ticker: str, ci: dict, quality: dict) -> "float | None":
    try:
        from backend.services.holdco_sotp_service import (
            HoldcoSOTPInputs,
            UnderlyingHolding,
            compute_sotp,
        )
        block = _ci_block(ci, "holdco_sotp")
        underlyings_raw = block.get("underlyings") or []
        if not isinstance(underlyings_raw, list) or not underlyings_raw:
            return None
        underlyings = []
        for u in underlyings_raw:
            if not isinstance(u, dict):
                continue
            try:
                underlyings.append(UnderlyingHolding(
                    ticker=str(u.get("ticker") or ""),
                    stake_pct=float(u.get("stake_pct") or 0.0),
                    underlying_market_cap_inr_cr=(
                        float(u["underlying_market_cap_inr_cr"])
                        if u.get("underlying_market_cap_inr_cr") is not None
                        else None
                    ),
                    is_listed=bool(u.get("is_listed", True)),
                ))
            except (TypeError, ValueError):
                continue
        if not underlyings:
            return None
        inputs = HoldcoSOTPInputs(
            holdco_ticker=ticker,
            underlyings=underlyings,
            holdco_net_cash_inr_cr=float(block.get("net_cash_inr_cr") or 0.0),
            holdco_shares_outstanding=float(
                block.get("shares_outstanding") or quality.get("shares_outstanding") or 0.0
            ),
        )
        result = compute_sotp(inputs)
        return _coerce_pos(result.sotp_per_share)
    except Exception:
        return None


def _compute_nbfc_fv(ticker: str, ci: dict, quality: dict, valuation: dict) -> "float | None":
    try:
        from backend.services.nbfc_roa_service import (
            NBFCInputs,
            NBFC_TICKERS,
            compute_nbfc_fair_value,
            get_segment_defaults,
        )
        block = _ci_block(ci, "nbfc")
        bare = ticker.replace(".NS", "").replace(".BO", "").upper()
        segment = NBFC_TICKERS.get(bare, "diversified")
        defaults = get_segment_defaults(segment)
        avg_assets = _coerce_pos(block.get("average_assets_inr_cr"))
        if avg_assets is None:
            return None
        avg_equity = _coerce_pos(block.get("average_equity_inr_cr")) or (avg_assets * 0.12)
        inputs = NBFCInputs(
            average_assets_inr_cr=avg_assets,
            average_equity_inr_cr=avg_equity,
            yield_on_assets_pct=float(block.get("yield_on_assets_pct") or defaults["expected_yield"]),
            cost_of_funds_pct=float(block.get("cost_of_funds_pct") or defaults["expected_cof"]),
            credit_cost_pct=float(block.get("credit_cost_pct") or defaults["expected_credit_cost"]),
            opex_ratio_pct=float(block.get("opex_ratio_pct") or defaults["expected_opex_ratio"]),
            fee_income_pct=float(block.get("fee_income_pct") or 0.0),
            tax_rate=float(block.get("tax_rate") or 0.25),
            expected_loan_growth_pct=float(block.get("expected_loan_growth_pct") or defaults["expected_growth"]),
            payout_ratio=float(block.get("payout_ratio") or quality.get("payout_ratio") or 0.20),
            cost_of_equity=float(block.get("cost_of_equity") or defaults["cost_of_equity"]),
            sustainable_growth=float(block.get("sustainable_growth") or 0.10),
            shares_outstanding=float(block.get("shares_outstanding") or quality.get("shares_outstanding") or 0.0),
            book_value_per_share=float(block.get("book_value_per_share") or quality.get("book_value_per_share") or 0.0),
            segment=segment,
        )
        result = compute_nbfc_fair_value(inputs)
        return _coerce_pos(result.fair_value_per_share)
    except Exception:
        return None


def _compute_insurance_fv(ticker: str, ci: dict, quality: dict) -> "float | None":
    try:
        from backend.services.insurance_appraisal_service import (
            EVVNBInputs,
            compute_ev_vnb_appraisal,
            select_vnb_multiple,
        )
        block = _ci_block(ci, "insurance")
        ev = _coerce_pos(block.get("embedded_value"))
        if ev is None:
            return None
        vnb = float(block.get("new_business_value") or 0.0)
        # select_vnb_multiple returns a recommended multiple; defensive fallback to 22 mid-band.
        try:
            mult = select_vnb_multiple(ticker)
            if not mult or mult <= 0:
                mult = 22.0
        except Exception:
            mult = 22.0
        inputs = EVVNBInputs(
            embedded_value=ev,
            new_business_value=vnb,
            vnb_multiple=float(block.get("vnb_multiple") or mult),
        )
        shares = float(block.get("shares_outstanding") or quality.get("shares_outstanding") or 0.0)
        result = compute_ev_vnb_appraisal(inputs, shares_outstanding=shares if shares > 0 else None)
        return _coerce_pos(result.appraisal_per_share)
    except Exception:
        return None


def _compute_pharma_pipeline_fv(ticker: str, ci: dict, quality: dict) -> "float | None":
    try:
        from backend.services.pharma_pipeline_service import (
            load_curated_assets,
            value_pipeline,
        )
        assets = load_curated_assets(ticker)
        if not assets:
            return None
        result = value_pipeline(assets)
        if result.method == "unavailable":
            return None
        # Aggregate INR-cr → per-share. shares_outstanding in Cr per
        # Indian convention; total_pipeline_rnpv_inr_cr / shares = ₹/share.
        block = _ci_block(ci, "pharma_pipeline")
        shares = (
            _coerce_pos(block.get("shares_outstanding"))
            or _coerce_pos(quality.get("shares_outstanding"))
        )
        if shares is None:
            return None
        per_share = result.total_pipeline_rnpv_inr_cr / shares
        return _coerce_pos(per_share)
    except Exception:
        return None


def _compute_telecom_fv(ticker: str, ci: dict, quality: dict, valuation: dict) -> "float | None":
    try:
        from backend.services.telecom_arpu_service import (
            TelecomInputs,
            compute_arpu_driven_fv,
        )
        block = _ci_block(ci, "telecom")
        current_subs = _coerce_pos(block.get("current_subscribers_millions"))
        current_arpu = _coerce_pos(block.get("current_arpu_inr"))
        if current_subs is None or current_arpu is None:
            return None
        inputs = TelecomInputs(
            current_subscribers_millions=current_subs,
            current_arpu_inr=current_arpu,
            forecast_horizon_years=int(block.get("forecast_horizon_years") or 5),
            operating_margin_pct=float(block.get("operating_margin_pct") or 30.0),
            maintenance_capex_pct_of_revenue=float(
                block.get("maintenance_capex_pct_of_revenue") or 12.0
            ),
            growth_capex_pct_of_revenue=float(
                block.get("growth_capex_pct_of_revenue") or 5.0
            ),
            spectrum_capex_one_time=float(block.get("spectrum_capex_one_time") or 0.0),
            tax_rate=float(block.get("tax_rate") or 0.22),
            discount_rate=float(
                block.get("discount_rate")
                or valuation.get("discount_rate")
                or valuation.get("wacc")
                or 0.11
            ),
            terminal_growth=float(
                block.get("terminal_growth") or valuation.get("terminal_growth") or 0.04
            ),
            shares_outstanding=float(
                block.get("shares_outstanding") or quality.get("shares_outstanding") or 0.0
            ),
        )
        result = compute_arpu_driven_fv(inputs)
        return _coerce_pos(result.fair_value_per_share)
    except Exception:
        return None


def _compute_oil_gas_fv(ticker: str, ci: dict, quality: dict) -> "float | None":
    """Resolve per-share FV for the oil & gas cohort.

    The oil_gas service returns AGGREGATE values (₹Cr) — this helper
    handles the per-share conversion (equity_value_inr_cr × 1e7 / shares).
    Each segment helper returns a dict; integrated SOTP returns the
    OilGasValuationResult with fair_value_per_share already.
    """
    try:
        from backend.services.oil_gas_valuation_service import (
            UpstreamReserveInputs,
            DownstreamRefiningInputs,
            CityGasInputs,
            compute_integrated_sotp,
            compute_upstream_reserves_npv,
            compute_downstream_ev_ebitda,
            compute_city_gas_value,
            select_method_for_ticker,
        )
        segment = select_method_for_ticker(ticker)
        if not segment:
            return None
        block = _ci_block(ci, "oil_gas")
        shares = float(
            block.get("shares_outstanding")
            or quality.get("shares_outstanding")
            or 0.0
        )
        if shares <= 0:
            return None

        def _to_per_share(equity_cr: "float | None") -> "float | None":
            if equity_cr is None or equity_cr <= 0:
                return None
            return (float(equity_cr) * 1e7) / shares

        if segment == "upstream":
            ups = block.get("upstream") if isinstance(block.get("upstream"), dict) else block
            if not _coerce_pos(ups.get("proved_reserves_mmboe")):
                return None
            ui = UpstreamReserveInputs(
                proved_reserves_mmboe=float(ups["proved_reserves_mmboe"]),
                probable_reserves_mmboe=float(ups.get("probable_reserves_mmboe") or 0.0),
                annual_production_mmboe=float(ups.get("annual_production_mmboe") or 0.0),
                realized_price_usd_per_boe=float(ups.get("realized_price_usd_per_boe") or 70.0),
                operating_cost_usd_per_boe=float(ups.get("operating_cost_usd_per_boe") or 25.0),
                royalty_pct=float(ups.get("royalty_pct") or 20.0),
                cess_pct=float(ups.get("cess_pct") or 20.0),
                income_tax_pct=float(ups.get("income_tax_pct") or 25.0),
                discount_rate=float(ups.get("discount_rate") or 0.12),
            )
            res = compute_upstream_reserves_npv(ui)
            npv_cr = res.get("npv_inr_cr")
            net_debt = float(ups.get("net_debt_inr_cr") or block.get("net_debt_inr_cr") or 0.0)
            equity_cr = (npv_cr or 0.0) - net_debt
            return _coerce_pos(_to_per_share(equity_cr))
        if segment == "downstream":
            ds = block.get("downstream") if isinstance(block.get("downstream"), dict) else block
            if not _coerce_pos(ds.get("refining_throughput_mmt")):
                return None
            di = DownstreamRefiningInputs(
                refining_throughput_mmt=float(ds["refining_throughput_mmt"]),
                gross_refining_margin_usd_per_bbl=float(ds.get("gross_refining_margin_usd_per_bbl") or 8.0),
                capacity_utilization_pct=float(ds.get("capacity_utilization_pct") or 95.0),
                ev_ebitda_multiple=float(ds.get("ev_ebitda_multiple") or 6.5),
                net_debt_inr_cr=float(ds.get("net_debt_inr_cr") or 0.0),
            )
            res = compute_downstream_ev_ebitda(di)
            return _coerce_pos(_to_per_share(res.get("equity_value_inr_cr")))
        if segment == "city_gas":
            cg = block.get("city_gas") if isinstance(block.get("city_gas"), dict) else block
            if not (_coerce_pos(cg.get("cng_volume_mmscm_per_day")) or _coerce_pos(cg.get("png_volume_mmscm_per_day"))):
                return None
            ci_in = CityGasInputs(
                cng_volume_mmscm_per_day=float(cg.get("cng_volume_mmscm_per_day") or 0.0),
                png_volume_mmscm_per_day=float(cg.get("png_volume_mmscm_per_day") or 0.0),
                ebitda_per_unit_inr_per_scm=float(cg.get("ebitda_per_unit_inr_per_scm") or 6.5),
                ebitda_multiple=float(cg.get("ebitda_multiple") or 14.0),
                net_debt_inr_cr=float(cg.get("net_debt_inr_cr") or 0.0),
            )
            res = compute_city_gas_value(ci_in)
            return _coerce_pos(_to_per_share(res.get("equity_value_inr_cr")))
        if segment == "integrated":
            # compute_integrated_sotp takes per-segment EQUITY VALUES,
            # not Inputs dataclasses. Read pre-computed segment values
            # from the block; absent segments contribute None.
            res = compute_integrated_sotp(
                upstream_value_inr_cr=block.get("upstream_value_inr_cr"),
                downstream_value_inr_cr=block.get("downstream_value_inr_cr"),
                petrochem_value_inr_cr=block.get("petrochem_value_inr_cr"),
                other_value_inr_cr=block.get("other_value_inr_cr"),
                net_debt_inr_cr=float(block.get("net_debt_inr_cr") or 0.0),
                shares_outstanding=shares,
            )
            return _coerce_pos(res.fair_value_per_share)
        # gas_transmission has no dedicated method — fall through.
        return None
    except Exception:
        return None


def _compute_auto_oem_fv(ticker: str, ci: dict, quality: dict) -> "float | None":
    try:
        from backend.services.auto_oem_cycle_service import (
            AUTO_OEM_TICKERS,
            AutoOEMInputs,
            compute_auto_oem_fv,
        )
        block = _ci_block(ci, "auto_oem")
        bare = ticker.replace(".NS", "").replace(".BO", "").upper()
        segment = AUTO_OEM_TICKERS.get(bare, "pv_4w")
        current = _coerce_pos(block.get("current_year_volume_units"))
        peak = _coerce_pos(block.get("peak_year_volume_units"))
        trough = _coerce_pos(block.get("trough_year_volume_units"))
        realization = _coerce_pos(block.get("realization_per_unit_inr"))
        if not (current and peak and trough and realization):
            return None
        inputs = AutoOEMInputs(
            current_year_volume_units=current,
            peak_year_volume_units=peak,
            trough_year_volume_units=trough,
            realization_per_unit_inr=realization,
            operating_margin_current_pct=float(block.get("operating_margin_current_pct") or 11.0),
            operating_margin_mid_cycle_pct=float(block.get("operating_margin_mid_cycle_pct") or 12.0),
            ev_ebitda_multiple_mid_cycle=float(block.get("ev_ebitda_multiple_mid_cycle") or 12.0),
            net_debt_inr_cr=float(block.get("net_debt_inr_cr") or 0.0),
            shares_outstanding=float(
                block.get("shares_outstanding") or quality.get("shares_outstanding") or 0.0
            ),
            segment=segment,
        )
        result = compute_auto_oem_fv(inputs)
        return _coerce_pos(result.fair_value_per_share)
    except Exception:
        return None


def _compute_cement_fv(ticker: str, ci: dict, quality: dict) -> "float | None":
    try:
        from backend.services.cement_utilization_service import (
            CEMENT_TICKERS,
            CementInputs,
            compute_cement_fv,
        )
        block = _ci_block(ci, "cement")
        bare = ticker.replace(".NS", "").replace(".BO", "").upper()
        sub_segment = CEMENT_TICKERS.get(bare, "mid_tier")
        capacity = _coerce_pos(block.get("installed_capacity_mtpa"))
        if capacity is None:
            return None
        inputs = CementInputs(
            installed_capacity_mtpa=capacity,
            current_utilization_pct=float(block.get("current_utilization_pct") or 80.0),
            mid_cycle_utilization_pct=float(block.get("mid_cycle_utilization_pct") or 80.0),
            realization_per_tonne_inr=float(block.get("realization_per_tonne_inr") or 5800.0),
            ebitda_per_tonne_inr=float(block.get("ebitda_per_tonne_inr") or 1100.0),
            ev_ebitda_multiple=float(block.get("ev_ebitda_multiple") or 14.0),
            net_debt_inr_cr=float(block.get("net_debt_inr_cr") or 0.0),
            shares_outstanding=float(
                block.get("shares_outstanding") or quality.get("shares_outstanding") or 0.0
            ),
            sub_segment=sub_segment,
        )
        result = compute_cement_fv(inputs)
        return _coerce_pos(result.fair_value_per_share)
    except Exception:
        return None


def _compute_steel_fv(ticker: str, ci: dict, quality: dict) -> "float | None":
    try:
        from backend.services.steel_cost_curve_service import (
            STEEL_TICKERS,
            SteelInputs,
            compute_steel_fv,
        )
        block = _ci_block(ci, "steel")
        bare = ticker.replace(".NS", "").replace(".BO", "").upper()
        quartile = STEEL_TICKERS.get(bare, "second_quartile")
        capacity = _coerce_pos(block.get("crude_steel_capacity_mtpa"))
        if capacity is None:
            return None
        inputs = SteelInputs(
            crude_steel_capacity_mtpa=capacity,
            current_utilization_pct=float(block.get("current_utilization_pct") or 80.0),
            mid_cycle_utilization_pct=float(block.get("mid_cycle_utilization_pct") or 82.0),
            realization_per_tonne_inr=float(
                block.get("realization_per_tonne_inr") or 55000.0
            ),
            cost_per_tonne_inr=float(
                block.get("cost_per_tonne_inr") or 45000.0
            ),
            cost_curve_quartile=quartile,
            ev_ebitda_multiple_mid_cycle=float(
                block.get("ev_ebitda_multiple_mid_cycle") or 6.0
            ),
            iron_ore_integration_pct=float(block.get("iron_ore_integration_pct") or 0.0),
            net_debt_inr_cr=float(block.get("net_debt_inr_cr") or 0.0),
            shares_outstanding=float(
                block.get("shares_outstanding") or quality.get("shares_outstanding") or 0.0
            ),
        )
        result = compute_steel_fv(inputs)
        return _coerce_pos(result.fair_value_per_share)
    except Exception:
        return None


def _compute_re_developer_fv(ticker: str, ci: dict, quality: dict) -> "float | None":
    try:
        from backend.services.real_estate_developer_service import (
            REDeveloperInputs,
            compute_developer_nav,
        )
        block = _ci_block(ci, "re_developer")
        # NAV needs at least a land bank value. When missing, skip.
        if not block:
            return None
        try:
            inputs = REDeveloperInputs(**block)
        except TypeError:
            return None
        result = compute_developer_nav(inputs)
        return _coerce_pos(result.nav_per_share)
    except Exception:
        return None


def _compute_consumer_durables_fv(ticker: str, ci: dict, quality: dict) -> "float | None":
    try:
        from backend.services.consumer_durables_wc_service import (
            ConsumerDurablesInputs,
            compute_consumer_durables_fv,
        )
        block = _ci_block(ci, "consumer_durables")
        revenue = _coerce_pos(block.get("revenue_inr_cr"))
        if revenue is None:
            return None
        inputs = ConsumerDurablesInputs(
            revenue_inr_cr=revenue,
            inventory_inr_cr=float(block.get("inventory_inr_cr") or 0.0),
            receivables_inr_cr=float(block.get("receivables_inr_cr") or 0.0),
            payables_inr_cr=float(block.get("payables_inr_cr") or 0.0),
            operating_cycle_days_history=list(block.get("operating_cycle_days_history") or []),
            wc_intensity_pct_history=list(block.get("wc_intensity_pct_history") or []),
            margin_pct=float(block.get("margin_pct") or 12.0),
            ev_ebitda_multiple=float(block.get("ev_ebitda_multiple") or 20.0),
            net_debt_inr_cr=float(block.get("net_debt_inr_cr") or 0.0),
            shares_outstanding=float(
                block.get("shares_outstanding") or quality.get("shares_outstanding") or 0.0
            ),
            cost_of_equity=float(block.get("cost_of_equity") or 0.115),
        )
        result = compute_consumer_durables_fv(inputs)
        return _coerce_pos(result.fair_value_per_share)
    except Exception:
        return None


def _compute_media_fv(ticker: str, ci: dict, quality: dict) -> "float | None":
    try:
        from backend.services.media_subscriber_ltv_service import (
            MediaSubscriberInputs,
            compute_media_fv,
        )
        block = _ci_block(ci, "media")
        if not block:
            return None
        try:
            inputs = MediaSubscriberInputs(**block)
        except TypeError:
            return None
        result = compute_media_fv(inputs)
        return _coerce_pos(result.fair_value_per_share)
    except Exception:
        return None


def _compute_logistics_fv(ticker: str, ci: dict, quality: dict) -> "float | None":
    try:
        from backend.services.logistics_freight_service import (
            LogisticsInputs,
            compute_logistics_fv,
        )
        block = _ci_block(ci, "logistics")
        if not block:
            return None
        try:
            inputs = LogisticsInputs(**block)
        except TypeError:
            return None
        result = compute_logistics_fv(inputs)
        return _coerce_pos(result.fair_value_per_share)
    except Exception:
        return None


def _compute_it_overlay_multiplier(
    ticker: str, ci: dict, quality: dict, valuation: dict,
) -> "float | None":
    try:
        from backend.services.it_services_overlay_service import (
            IT_TICKERS,
            ITServicesOverlayInputs,
            compute_it_overlay,
        )
        block = _ci_block(ci, "it_overlay")
        bare = ticker.replace(".NS", "").replace(".BO", "").upper()
        tier = IT_TICKERS.get(bare, "tier_2")
        base_dcf = _coerce_pos(valuation.get("fair_value")) or 100.0
        inputs = ITServicesOverlayInputs(
            base_dcf_fv=base_dcf,
            top_5_client_concentration_pct=float(
                block.get("top_5_client_concentration_pct") or 25.0
            ),
            bfsi_revenue_share_pct=float(
                block.get("bfsi_revenue_share_pct")
                or block.get("bfsi_revenue_pct")
                or 30.0
            ),
            usd_revenue_share_pct=float(
                block.get("usd_revenue_share_pct")
                or block.get("us_revenue_pct")
                or 50.0
            ),
            europe_revenue_share_pct=float(
                block.get("europe_revenue_share_pct")
                or block.get("europe_revenue_pct")
                or 25.0
            ),
            sbc_pct_of_fcf=float(block.get("sbc_pct_of_fcf") or 5.0),
            headcount_growth_pct=float(
                block.get("headcount_growth_pct")
                or block.get("headcount_growth_yoy_pct")
                or 8.0
            ),
            revenue_growth_3y_cagr_pct=float(
                block.get("revenue_growth_3y_cagr_pct")
                or block.get("revenue_growth_yoy_pct")
                or 10.0
            ),
            operating_margin_pct=float(block.get("operating_margin_pct") or 24.0),
            tier=tier,
        )
        result = compute_it_overlay(inputs)
        if result.adjusted_fv is None or base_dcf <= 0:
            adjustments = result.adjustments or {}
            mult = adjustments.get("compound_multiplier")
            return _coerce_pos(mult)
        mult = float(result.adjusted_fv) / float(base_dcf)
        return _coerce_pos(mult)
    except Exception:
        return None


def _compute_utilities_overlay_multiplier(
    ticker: str, ci: dict, quality: dict, valuation: dict,
) -> "float | None":
    try:
        from backend.services.utilities_maintenance_capex_service import (
            UTILITIES_TICKERS,
            UtilitiesMaintenanceInputs,
            compute_maintenance_adjustment,
        )
        block = _ci_block(ci, "utilities_maintenance")
        bare = ticker.replace(".NS", "").replace(".BO", "").upper()
        sub_segment = UTILITIES_TICKERS.get(bare, "generation_thermal")
        reported_fcf = _coerce_pos(block.get("reported_fcf_inr_cr"))
        if reported_fcf is None:
            return None
        inputs = UtilitiesMaintenanceInputs(
            reported_fcf_inr_cr=reported_fcf,
            da_inr_cr=float(block.get("da_inr_cr") or 0.0),
            total_capex_inr_cr=float(block.get("total_capex_inr_cr") or 0.0),
            maintenance_capex_fraction=float(
                block.get("maintenance_capex_fraction") or 0.65
            ),
            growth_capex_inr_cr=(
                float(block["growth_capex_inr_cr"])
                if block.get("growth_capex_inr_cr") is not None
                else None
            ),
            asset_base_age_years=(
                float(block["asset_base_age_years"])
                if block.get("asset_base_age_years") is not None
                else None
            ),
            rab_per_unit_inr_cr=float(block.get("rab_per_unit_inr_cr") or 0.0),
            sub_segment=sub_segment,
        )
        result = compute_maintenance_adjustment(inputs)
        # owner_earnings / reported_fcf is the relevant multiplier on FV.
        if result.reported_fcf <= 0:
            return None
        mult = result.owner_earnings_inr_cr / result.reported_fcf
        return _coerce_pos(mult)
    except Exception:
        return None


def _inject_phase_b_estimators_dict(payload: dict) -> dict:
    """Run all five Phase-B estimator injects against a dict payload.

    Single call-site so the cache paths don't drift — every new
    estimator added in Phase C+ goes here. Phase C (2026-06-10)
    reordered the cache-path chains so this orchestrator runs BEFORE
    `_inject_composite_iv_dict` (its outputs feed the composite
    weighted average).

    Phase B mega-wiring (2026-06-10) — also runs the sector-specific
    router and the overlay router so the composite has all per-ticker
    signals available before the weighted average runs.
    """
    _inject_ddm_dict(payload)
    _inject_epv_dict(payload)
    _inject_three_stage_dict(payload)
    _inject_liquidation_dict(payload)
    _inject_replacement_dict(payload)
    _inject_probability_weighted_dict(payload)
    _inject_sector_specific_dict(payload)
    _inject_overlay_dict(payload)
    return payload


def _inject_phase_b_estimators_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Run all five Phase-B estimator injects against a Pydantic model.

    Single call-site for the cold-compute path.
    """
    _inject_ddm_model(result)
    _inject_epv_model(result)
    _inject_three_stage_model(result)
    _inject_liquidation_model(result)
    _inject_replacement_model(result)
    _inject_probability_weighted_model(result)
    _inject_sector_specific_model(result)
    _inject_overlay_model(result)
    return result


# ─────────────────────────────────────────────────────────────────
# T5.3 (2026-06-10) — derived insights inject
# ─────────────────────────────────────────────────────────────────
# Synthesizes the rich payload (composite + Phase-B estimators + 5
# confidence pillars + Graham liquidation floor + Tobin replacement
# ceiling + per-sector backtest accuracy) into 4 human-readable
# callouts. See backend/services/derived_insights_service.py for
# the math. Follows the proven Phase-B/composite inject contract:
#   1. Lazy import — keeps cold start fast.
#   2. Pure derivation from in-payload inputs — no DB/cache.
#   3. Defensive — try/except wraps the entire body; failure leaves
#      derived_insights absent and the frontend hides the panel.
#   4. Runs AFTER `_inject_phase_b_estimators_*` AND AFTER
#      `_inject_composite_iv_*` — both feed the insight extractor
#      (composite_components for clustering, liquidation_per_share
#      for floor/ceiling). Canonical chain order (every cache path):
#          sector_medians -> multiples_fv -> phase_b -> composite
#                         -> derived_insights
#
# Sector calibration uses an injected provider so the public
# /calibration cache (24h router-layer cache from
# backend/routers/calibration.py) is reused — no per-analysis DB
# hit. The provider returns None on cache miss / no-data, which
# the service treats as "no sector calibration insight available"
# rather than recomputing inline.
# ─────────────────────────────────────────────────────────────────


def _sector_calibration_lookup(sector: str) -> dict | None:
    """Look up a single sector's calibration stats from the public cache.

    Returns a dict matching the SectorCalibrationStat shape, or None
    when the sector lacks the published 30-observation threshold
    (backend.services.backtest_publisher). Defensive — any failure
    returns None and the insight surfaces as absent.
    """
    try:
        from backend.routers.calibration import (
            _CACHE_KEY as _CAL_CACHE_KEY,
            _build_payload as _cal_build,
        )
        from backend.services.cache_service import cache as _cal_cache
        cached = _cal_cache.get(_CAL_CACHE_KEY)
        if cached is None:
            # Build once and seed the public cache so the next analysis
            # request reuses it. _cal_build is the same function the
            # /calibration router uses on a cold cache.
            try:
                cached = _cal_build()
                _cal_cache.set(_CAL_CACHE_KEY, cached, ttl=86_400)
            except Exception:
                return None
        if not isinstance(cached, dict):
            return None
        sectors = cached.get("sectors") or []
        # Case-insensitive sector match — payload sectors are
        # canonical-cased ("Financial Services") but free-form sector
        # strings on the analysis payload occasionally arrive lowercased.
        target = sector.strip().lower()
        for row in sectors:
            if not isinstance(row, dict):
                continue
            row_sector = row.get("sector")
            if isinstance(row_sector, str) and row_sector.strip().lower() == target:
                return row
    except Exception:
        return None
    return None


def _derived_insights_inputs_from_dict(payload: dict) -> dict:
    """Extract the 9 inputs the derived insights service needs.

    Mirrors the contract of _composite_inputs_from_dict — single
    extractor shared by the warm-dict and cold-model paths. Returns a
    dict keyed by the kwargs of compute_all_insights so the call
    site stays a one-liner.
    """
    valuation = payload.get("valuation") if isinstance(payload.get("valuation"), dict) else {}
    company = payload.get("company") if isinstance(payload.get("company"), dict) else {}
    # Confidence pillar scores — three live on ValuationOutput (PR #340
    # + T2.7), two are top-level slots (T1.6 + T2.7 mirror). All
    # Optional[int]; the service treats missing as absent.
    confidence_scores = {
        "data_quality": valuation.get("data_quality_score"),
        "model_fit": valuation.get("model_confidence_score"),
        "stability": valuation.get("valuation_stability_score"),
        "sensitivity": payload.get("confidence_sensitivity"),
        "estimator_agreement": payload.get("confidence_composite_agreement"),
    }
    return {
        "confidence_scores": confidence_scores,
        "composite_components": payload.get("composite_components"),
        "liquidation": payload.get("liquidation_per_share"),
        # T2.3 replacement-value Phase A landed the engine only — no
        # response field yet. Pass None so the insight surfaces the
        # liquidation-only frame; once Phase B wires the field this
        # extractor needs no change.
        "replacement": payload.get("replacement_per_share"),
        "current_price": valuation.get("current_price"),
        "dcf_fv": valuation.get("fair_value"),
        "composite_iv": payload.get("composite_intrinsic_value"),
        "sector": company.get("sector"),
    }


def _inject_derived_insights_dict(payload: dict) -> dict:
    """Populate ``derived_insights`` on a dict payload.

    T5.3 (2026-06-10). Composes confidence summary, estimator
    clustering, floor/ceiling anchor, and sector calibration into
    one bundle and writes it to ``payload['derived_insights']`` as
    a JSON-safe dict. MUST run AFTER both
    ``_inject_phase_b_estimators_dict`` AND
    ``_inject_composite_iv_dict``.

    Never raises — insight failure leaves the field None (or absent
    for a single slot inside) and the frontend hides the panel.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        from backend.services.derived_insights_service import (
            compute_all_insights,
            to_dict as _di_to_dict,
        )
        inputs = _derived_insights_inputs_from_dict(payload)
        insights = compute_all_insights(
            sector_calibration_provider=_sector_calibration_lookup,
            **inputs,
        )
        payload["derived_insights"] = _di_to_dict(insights)
    except Exception:
        # Pure derivation — never break the response.
        pass
    return payload


def _inject_derived_insights_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_derived_insights_dict`.

    Used on the cold-compute return path. Mirrors the warm-path
    contract: builds a focused dict view of the relevant model
    fields, reuses the shared extractor, writes the resulting dict
    to ``result.derived_insights``.
    """
    try:
        _val = result.valuation.model_dump() if result.valuation else {}
        _co = result.company.model_dump() if result.company else {}
        _payload = {
            "valuation": _val,
            "company": _co,
            "composite_components": getattr(result, "composite_components", None),
            "composite_intrinsic_value": getattr(result, "composite_intrinsic_value", None),
            "liquidation_per_share": getattr(result, "liquidation_per_share", None),
            "replacement_per_share": getattr(result, "replacement_per_share", None),
            "confidence_sensitivity": getattr(result, "confidence_sensitivity", None),
            "confidence_composite_agreement": getattr(
                result, "confidence_composite_agreement", None
            ),
        }
        _inject_derived_insights_dict(_payload)
        result.derived_insights = _payload.get("derived_insights")
    except Exception:
        pass
    return result


# ─────────────────────────────────────────────────────────────────
# Cross-engine consensus signal inject (2026-06-10)
# ─────────────────────────────────────────────────────────────────
# Pulls every standalone estimator the composite saw — DCF, Multiples,
# Wall Street, Three-stage, DDM, EPV, Probability-weighted — plus the
# composite IV itself, and asks how many of them point in the SAME
# DIRECTION vs the live price. Different question from
# ``composite_intrinsic_value`` (a weighted-magnitude blend) and from
# ``derived_insights.estimator_clustering`` (a magnitude-proximity
# measure). When N of 7 agree, that is a stronger directional read
# than any single estimator.
#
# MUST run AFTER:
#   - ``_inject_multiples_fv_*``  (populates multiples_based_fv)
#   - ``_inject_phase_b_estimators_*`` (populates 4 Phase-B slots)
#   - ``_inject_composite_iv_*`` (populates composite_intrinsic_value)
# The orchestrator runs it AFTER derived_insights so derived_insights
# stays the last semantic-synthesis step; the consensus inject is a
# raw counting derivation that doesn't depend on derived_insights and
# vice-versa. Order between the two is irrelevant to correctness.
# ─────────────────────────────────────────────────────────────────


def _consensus_estimator_values_from_dict(payload: dict) -> dict:
    """Extract every standalone estimator value off the payload.

    Returns a ``{slot: float|None}`` map suitable for passing to
    ``consensus_signal_service.compute_consensus_signal``. Slot names
    mirror those in ``_composite_inputs_from_dict`` so the consensus
    surface and the composite surface stay aligned.

    The composite intrinsic value itself is intentionally OMITTED —
    it is a derived blend of the listed estimators, so counting it
    would double-count. Counting only the constituents preserves the
    "how many independent methodologies agree" semantics.
    """
    valuation = payload.get("valuation") or {}
    insights = payload.get("insights") or {}
    # Wall St analyst price-target mean — same precedence chain as
    # ``_composite_inputs_from_dict``: structured consensus block first,
    # then the loose legacy slot.
    analyst_avg = None
    consensus = insights.get("analyst_consensus")
    if isinstance(consensus, dict):
        pt = consensus.get("price_target") or {}
        analyst_avg = pt.get("mean") or pt.get("median")
    if analyst_avg is None:
        analyst_avg = insights.get("wall_street_avg_target")
    return {
        "dcf": valuation.get("fair_value"),
        "multiples": payload.get("multiples_based_fv"),
        "analyst": analyst_avg,
        "three_stage": payload.get("three_stage_fv"),
        "ddm": payload.get("ddm_fv"),
        "epv": payload.get("epv_per_share"),
        "probability_weighted": payload.get("probability_weighted_fv"),
    }


def _inject_consensus_signal_dict(payload: dict) -> dict:
    """Populate ``cross_engine_consensus`` on a dict payload.

    See module-level comment for sequencing requirements. Pure
    derivation — never raises, never touches I/O. On failure the
    field is left absent so the frontend hides the badge.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        from backend.services.consensus_signal_service import (
            build_estimator_breakdown,
            compute_consensus_signal,
            to_dict as _cs_to_dict,
        )
        valuation = payload.get("valuation") or {}
        current_price = valuation.get("current_price")
        estimator_values = _consensus_estimator_values_from_dict(payload)
        signal = compute_consensus_signal(
            estimator_values=estimator_values,
            current_price=current_price or 0.0,
        )
        out = _cs_to_dict(signal)
        # Fill the per-estimator breakdown using the same bucketing
        # the headline used so the UI list matches the headline count.
        out["estimator_breakdown"] = build_estimator_breakdown(
            estimator_values=estimator_values,
            current_price=current_price or 0.0,
        )
        payload["cross_engine_consensus"] = out
    except Exception:
        # Additive field only — never break the response.
        pass
    return payload


def _inject_consensus_signal_model(result: "AnalysisResponse") -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_consensus_signal_dict`.

    Used on the cold-compute return path. Builds a focused dict view
    of the relevant model fields, reuses the shared extractor, writes
    the resulting dict back to ``result.cross_engine_consensus``.
    """
    try:
        _val = result.valuation.model_dump() if result.valuation else {}
        _insights = result.insights.model_dump() if result.insights else {}
        _payload = {
            "valuation": _val,
            "insights": _insights,
            "multiples_based_fv": getattr(result, "multiples_based_fv", None),
            "three_stage_fv": getattr(result, "three_stage_fv", None),
            "ddm_fv": getattr(result, "ddm_fv", None),
            "epv_per_share": getattr(result, "epv_per_share", None),
            "probability_weighted_fv": getattr(
                result, "probability_weighted_fv", None
            ),
        }
        _inject_consensus_signal_dict(_payload)
        result.cross_engine_consensus = _payload.get("cross_engine_consensus")
    except Exception:
        pass
    return result


# ─────────────────────────────────────────────────────────────────
# Canonical headline Fair Value inject (2026-06-10 — ROOT CAUSE #1)
# ─────────────────────────────────────────────────────────────────
# Picks the single number that EVERY user-visible "Fair Value" pill,
# caveat line, AI-Why paragraph, FAQ answer, OG card and JSON-LD
# document MUST agree on. See the field-level docstring on
# ``AnalysisResponse.headline_fair_value`` for the full rationale.
#
# Rule:
#   composite_intrinsic_value     -> when finite + > 0  ("composite")
#   else valuation.fair_value     -> when finite + > 0  ("dcf")
#   else None                                              (None)
#
# MUST run AFTER ``_inject_composite_iv_*`` so the composite slot is
# populated when we read it. Sequenced in the orchestrator call-sites
# accordingly. Pure derivation, no I/O. Never raises — failure leaves
# the field None and the frontend's resolver supplies the same fallback
# chain client-side (legacy / cached payloads behave correctly).
# ─────────────────────────────────────────────────────────────────


def _resolve_headline_fair_value(
    composite_iv,
    dcf_fv,
):
    """Pure helper — used by both the dict and model inject paths.

    Returns ``(value, method)`` where ``method`` is one of
    "composite" | "dcf" | None.
    """
    try:
        if composite_iv is not None:
            try:
                cv = float(composite_iv)
            except (TypeError, ValueError):
                cv = None
            if cv is not None and cv > 0 and cv == cv:  # cv == cv excludes NaN
                return (round(cv, 2), "composite")
    except Exception:
        pass
    try:
        if dcf_fv is not None:
            try:
                dv = float(dcf_fv)
            except (TypeError, ValueError):
                dv = None
            if dv is not None and dv > 0 and dv == dv:
                return (round(dv, 2), "dcf")
    except Exception:
        pass
    return (None, None)


def _inject_headline_fair_value_dict(payload: dict) -> dict:
    """Populate ``headline_fair_value`` + ``headline_fair_value_method``
    on a dict payload. See module docstring above. MUST run AFTER
    ``_inject_composite_iv_dict``.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        composite_iv = payload.get("composite_intrinsic_value")
        valuation = payload.get("valuation") or {}
        dcf_fv = valuation.get("fair_value") if isinstance(valuation, dict) else None
        value, method = _resolve_headline_fair_value(composite_iv, dcf_fv)
        payload["headline_fair_value"] = value
        payload["headline_fair_value_method"] = method
    except Exception:
        # Additive field only — never break the response. The frontend
        # resolver supplies the same fallback chain client-side.
        pass
    return payload


def _inject_headline_fair_value_model(
    result: "AnalysisResponse",
) -> "AnalysisResponse":
    """Pydantic-model variant of `_inject_headline_fair_value_dict`."""
    try:
        composite_iv = getattr(result, "composite_intrinsic_value", None)
        dcf_fv = result.valuation.fair_value if result.valuation else None
        value, method = _resolve_headline_fair_value(composite_iv, dcf_fv)
        result.headline_fair_value = value
        result.headline_fair_value_method = method
    except Exception:
        pass
    return result


@router.get("/analysis/{ticker}", response_model=AnalysisResponse)
async def get_analysis(
    ticker: str,
    request: Request,
    background_tasks: BackgroundTasks,
    include_summary: bool = Query(
        True,
        description=(
            "If false, skip AI summary generation so the response returns "
            "instantly. Callers should then hit "
            "GET /api/v1/analysis/{ticker}/summary separately. Default is "
            "true for backward compatibility."
        ),
    ),
    user: dict = Depends(_auth_jwt_or_api_key),
):
    # ── Telemetry (additive, never blocks) ──
    # Record signed-in page view so admin/user-activity can answer
    # "did user X view any analysis page after signup?". Fire-and-forget.
    try:
        from backend.services.page_view_service import record_page_view as _rpv
        _email = (user or {}).get("email") if isinstance(user, dict) else None
        if _email:
            background_tasks.add_task(
                _rpv,
                user_email=_email,
                page_kind="analysis",
                ticker=ticker.upper().strip(),
                path=str(request.url.path),
                user_agent=request.headers.get("user-agent"),
                referrer=request.headers.get("referer"),
            )
    except Exception:
        pass
    """
    Full stock analysis with DCF, quality scores, scenarios, and insights.
    Rate limited by tier: Free=5/day, Starter=50/day, Pro=unlimited.

    Auth: Either a Bearer JWT (browser/app) OR a Pro-tier API key
    (``Authorization: Bearer yk_...`` or ``X-API-Key: yk_...``). API
    keys have their own per-key 100 req/day quota independent of the
    per-user JWT counter.

    Cache tiers (in order): in-memory cache_service -> analysis_cache
    (Postgres) -> compute. The persistent tier survives worker restarts
    and is shared across Railway workers; it is invalidated implicitly
    whenever CACHE_VERSION is bumped.

    Frontend contract (2026-04): the AI summary (Gemini/Groq) can add
    5-15s on a cold request. Callers rendering the summary asynchronously
    should pass ``?include_summary=false`` and hit
    ``/analysis/{ticker}/summary`` separately. When ``include_summary``
    is false, the ``ai_summary`` field in the returned payload is always
    ``None``. Default stays ``true`` so pre-existing callers keep the
    synchronous behaviour they had before this split.
    """
    import time as _time
    original_ticker = ticker.upper().strip()
    # Route renamed symbols to their canonical equivalent. Response
    # will carry the canonical ticker — frontend compares URL param
    # to response.ticker to show a "renamed to …" banner.
    ticker = TICKER_ALIASES.get(original_ticker, original_ticker)

    # ── Ticker existence gate (P1 2026-05-02) ───────────────────────
    # Refuse junk symbols (HEALTHCARE, SHAQUAK, etc.) before any
    # compute path runs. Cheap — backed by the in-memory
    # _known_indian_bare set (loaded once per worker). Aliases above
    # already routed legit slug-mismatches (GESHIPPING → GESHIP.NS),
    # so by this point we only refuse genuinely-unknown symbols.
    try:
        from backend.services.analysis.utils import _is_known_ticker
        if not _is_known_ticker(ticker):
            raise HTTPException(
                status_code=404,
                detail={"error": "Ticker not found", "ticker": original_ticker},
            )
    except HTTPException:
        raise
    except Exception:
        # Validator failure must never block analysis.
        pass

    # ── Nickname rewrite (HUL → HINDUNILVR, etc.) ───────────────────
    # YAML `status: nickname` entries are colloquial aliases — rewrite
    # to canonical here so cache keys, compute, and the corp-action
    # gate below all see the real ticker. Caught in PR #83 health audit
    # (`/analysis/preview/HUL` was 404-ing in prod).
    try:
        from data_pipeline import ticker_aliases as _aliases_mod
        _canonical = _aliases_mod.resolve_nickname(original_ticker)
        if _canonical:
            ticker = _canonical if "." in _canonical else f"{_canonical}.NS"
    except Exception:
        pass

    # ── Corporate-action redirect gate ──────────────────────────────
    # If the ticker is in our alias YAML as demerged / demerged_pending
    # / delisted, return a SIBLING redirect payload (not the normal
    # AnalysisResponse shape) so the frontend can route the user to the
    # successor entity / show a delisting notice without us trying to
    # value a defunct ISIN. The active-ticker happy path is byte-
    # identical to before — this branch only fires for non-active.
    # `nickname` is intentionally excluded — those are routing rewrites
    # (handled above), NOT corporate actions, and must pass through to
    # a normal analysis under the canonical ticker.
    try:
        from data_pipeline import ticker_aliases as _aliases
        _status = _aliases.get_status(original_ticker)
        if _status in ("demerged", "demerged_pending", "delisted"):
            from fastapi.responses import JSONResponse as _JSONResponse
            _payload = _aliases.get_successors_payload(original_ticker) or {}
            _redirect = {
                "result_kind": "corporate_action_redirect",
                "status": _status,
                "successors": _payload.get("successors", []),
                "effective_date": _payload.get("effective_date"),
                "note": _payload.get("note"),
            }
            return _JSONResponse(content=_redirect)
    except Exception:
        # Aliases module is best-effort — never break analysis on its
        # import / parse failure. Active tickers fall through cleanly.
        pass

    # Build the usage headers dict once — must be merged into EVERY
    # JSONResponse returned below. When a cache tier hits, FastAPI uses
    # that new JSONResponse's headers and discards the ones the
    # check_analysis_limit dependency set on its injected Response.
    # Without this, the nav counter stayed at 0/5 on every cache hit
    # (confirmed in prod 2026-04-23 via browser fetch probe).
    _usage_headers = {
        "X-Analyses-Today": str(user.get("analyses_today", "")),
        "X-Analyses-Limit": str(user.get("analysis_limit", "")),
    }

    # Tier 0: in-memory RAW dict cache (fastest path — no Pydantic).
    # Set by the tier-2 DB-cache fast path below. Warm-warm requests
    # on the same worker return via this branch in ~5-10ms.
    _cache_key = f"analysis:{ticker}"
    _raw_cached = cache.get(_cache_key + ":raw")
    if _raw_cached:
        from fastapi.responses import JSONResponse as _JSONResponse
        # _raw_cached is already a dict with cached=True set.
        # Respect include_summary toggle via a shallow copy.
        if not include_summary and _raw_cached.get("ai_summary") is not None:
            _out = dict(_raw_cached)
            _out["ai_summary"] = None
            _inject_sector_medians_dict(_out, ticker)
            _inject_multiples_fv_dict(_out)
            # Phase C (2026-06-10): Phase-B estimators MUST run BEFORE
            # composite so the four new estimator slots
            # (three_stage_fv / ddm_fv / epv_per_share /
            # probability_weighted_fv) are populated when the composite
            # extractor reads them. Was the reverse pre-Phase-C.
            _inject_phase_b_estimators_dict(_out)
            _inject_composite_iv_dict(_out)
            # T5.3 (2026-06-10) — derived insights synthesize composite
            # + confidence + floor/ceiling + sector calibration. MUST
            # run AFTER composite (reads composite_components) and
            # AFTER Phase B (reads liquidation_per_share).
            _inject_derived_insights_dict(_out)
            # Cross-engine consensus signal (2026-06-10) — additive,
            # MUST run after composite + Phase-B so every estimator
            # is reachable. Pure derivation; safe on every warm path.
            _inject_consensus_signal_dict(_out)
            # ROOT CAUSE #1 (2026-06-10): canonical headline FV — single
            # source of truth for hero / caveat / FAQ / OG / JSON-LD /
            # peer / AI-Why / Chat / PDF. MUST run AFTER composite so
            # the composite_intrinsic_value slot is populated.
            _inject_headline_fair_value_dict(_out)
            return _JSONResponse(content=_out, headers={"X-Cache": "HIT-MEM-RAW", **_usage_headers})
        # Shallow-copy so we don't mutate the cached dict in place
        # (other handlers may read it concurrently).
        _out = dict(_raw_cached)
        _inject_sector_medians_dict(_out, ticker)
        _inject_multiples_fv_dict(_out)
        # Phase C ordering — see comment in the include_summary=False
        # branch above. Phase-B inject populates the inputs the
        # composite extractor consumes.
        _inject_phase_b_estimators_dict(_out)
        _inject_composite_iv_dict(_out)
        _inject_derived_insights_dict(_out)
        _inject_consensus_signal_dict(_out)
        _inject_headline_fair_value_dict(_out)
        return _JSONResponse(content=_out, headers={"X-Cache": "HIT-MEM-RAW", **_usage_headers})

    # Tier 1: in-memory Pydantic cache (legacy, for paths that set
    # the object form). Slower than tier-0 because FastAPI re-serializes.
    cached = cache.get(_cache_key)
    if cached:
        cached.cached = True
        if not include_summary:
            # Caller asked to defer summary generation — strip it from the
            # cached payload so the client always gets a consistent contract.
            # The cached object is shared; mutate a shallow copy rather than
            # the original or subsequent ?include_summary=true reads would
            # see null too.
            try:
                cached = cached.model_copy(update={"ai_summary": None})
            except Exception:
                cached.ai_summary = None
        # Return as JSONResponse so the X-Cache header is set ONCE.
        # Previously we mutated `response.headers["X-Cache"]` on the
        # Response param AND a parallel branch returned JSONResponse
        # with its own X-Cache header — FastAPI merged the two,
        # producing the comma-joined "HIT-MEM-RAW, MISS" bug.
        from fastapi.responses import JSONResponse as _JSONResponse
        from fastapi.encoders import jsonable_encoder as _je
        _enc = _je(cached)
        _inject_sector_medians_dict(_enc, ticker)
        _inject_multiples_fv_dict(_enc)
        # Phase C (2026-06-10): Phase-B estimators MUST run BEFORE
        # composite so the four new estimator slots are populated
        # when the composite extractor reads them.
        _inject_phase_b_estimators_dict(_enc)
        _inject_composite_iv_dict(_enc)
        _inject_derived_insights_dict(_enc)
        _inject_consensus_signal_dict(_enc)
        _inject_headline_fair_value_dict(_enc)
        return _JSONResponse(
            content=_enc,
            headers={"X-Cache": "HIT-MEM", **_usage_headers},
        )

    # Tier 2: persistent DB cache (shared across workers, survives restart).
    # Never raises — failures degrade to compute.
    try:
        _db_cached = analysis_cache_service.get_cached(ticker)
    except Exception:
        _db_cached = None
    if _db_cached:
        try:
            # FAST PATH — return the cached JSON directly without
            # re-validating through Pydantic or letting FastAPI
            # re-serialize the Pydantic object. Perf measurement showed
            # the warm-cache path was ~2.6s — almost all of that was
            # model_validate + FastAPI's response serialization on a
            # large AnalysisResponse payload. The payload was already
            # validated when originally cached (it passed validate_analysis
            # at compute time), so we can trust it.
            #
            # Schema tolerance (unknown keys stripped) is still applied
            # in case we've removed fields since the cache was written —
            # but this is a cheap dict filter, not model validation.
            from fastapi.responses import JSONResponse as _JSONResponse
            _cls_fields = set(AnalysisResponse.model_fields.keys())
            _clean = {k: v for k, v in _db_cached.items() if k in _cls_fields}
            _clean["cached"] = True
            if not include_summary:
                _clean["ai_summary"] = None
            # Populate tier-1 with the raw dict too. Next request on this
            # worker skips DB + all validation. We drop the Pydantic form
            # from tier-1 for the same reason — the warm-warm path is now
            # dict → JSONResponse, effectively zero-cost serialization.
            cache.set(_cache_key + ":raw", _clean, ttl=86400)
            # Inject after cache.set so the cached dict stays stable
            # across requests — only this response carries the field.
            _out = dict(_clean)
            _inject_sector_medians_dict(_out, ticker)
            _inject_multiples_fv_dict(_out)
            # Phase C (2026-06-10): Phase-B estimators MUST run BEFORE
            # composite so the four new estimator slots are populated
            # when the composite extractor reads them.
            _inject_phase_b_estimators_dict(_out)
            _inject_composite_iv_dict(_out)
            _inject_derived_insights_dict(_out)
            _inject_consensus_signal_dict(_out)
            _inject_headline_fair_value_dict(_out)
            return _JSONResponse(content=_out, headers={"X-Cache": "HIT-DB-FAST", **_usage_headers})
        except Exception as _exc:
            import logging as _logging
            _logging.getLogger("yieldiq.analysis").warning(
                "analysis_cache: fast-path failed for %s (%s: %s) — recomputing + invalidating",
                ticker, type(_exc).__name__, _exc,
            )
            try:
                analysis_cache_service.invalidate(ticker)
            except Exception:
                pass
            # fall through to compute

    _compute_start = _time.monotonic()
    try:
        # PERF: get_full_analysis is a SYNC function that does blocking
        # I/O (yfinance HTTP, Postgres queries, an internal time.sleep
        # retry backoff). Calling it directly from this async handler
        # blocks the event loop — every concurrent request gets
        # serialized, killing throughput. Push it onto the thread-pool
        # executor so the loop stays responsive. Caught in 2026-04-25
        # health audit (PR #83).
        import asyncio as _asyncio
        result = await _asyncio.to_thread(service.get_full_analysis, ticker)

        # ── Output sanity gate ──────────────────────────────────
        # Two-layer defense:
        #   1. validate_analysis() — bounds + cross-field (WACC, MoS, FV/CMP,
        #      piotroski, moat-ROE consistency, DCF trace). Fires on any
        #      critical-severity failure anywhere in the response.
        #   2. FV/MoS ratio gate — defensive second layer tuned for the
        #      specific 'fair value is absurd' class of bug.
        # Either triggering flips verdict to 'data_limited' and zeroes the
        # numbers, keeping quality/moat/piotroski intact since those are
        # computed independently.
        _suspicious = False
        try:
            from backend.services.validators import validate_analysis, log_validation
            _vr = validate_analysis(result)
            if not _vr.ok and _vr.severity == "critical":
                _suspicious = True
                log_validation(ticker, _vr)
        except Exception:
            pass
        try:
            _fv = float(result.valuation.fair_value or 0)
            _px = float(result.valuation.current_price or 0)
            _mos = float(result.valuation.margin_of_safety or 0)
            # Financials use the peer-median P/BV or P/E path, not DCF.
            _is_financial_path = (
                getattr(result.valuation, "valuation_model", "") == "pb_ratio"
            )

            # ── FV bound-clamp (replaces the old FV=0 blanking) ─────
            # Pre-2026-04-25 behaviour was to zero out FV / MoS when
            # any of the four sentinels tripped:
            #   * FV <= 0 with PX > 0          (fv_zero)
            #   * FV/PX > 3.0                  (iv_px_high)
            #   * FV/PX < 0.1                  (iv_px_low)
            #   * |MoS| >= 95%                 (mos_extreme)
            # That hid the symptom from the user (chip showed FV=0,
            # verdict=data_limited) without giving them any signal
            # WHY the model couldn't price the stock. We now clamp
            # FV to the nearest plausible bound, recompute MoS off
            # the clamped FV, set ``valuation.data_limited = True``
            # and append a ``data_quality`` AnalyticalNoteOutput so
            # the UI can surface a caution chip with reason-specific
            # body copy.
            _trigger: str | None = None
            _clamped_fv: float | None = None
            if _px > 0:
                if _fv <= 0:
                    _trigger = "fv_zero"
                    _clamped_fv = round(_px * 0.1, 2)
                else:
                    _r = _fv / _px
                    if _r > 3.0:
                        _trigger = "iv_px_high"
                        _clamped_fv = round(_px * 3.0, 2)
                    elif _r < 0.1:
                        _trigger = "iv_px_low"
                        _clamped_fv = round(_px * 0.1, 2)

            if _trigger is None and abs(_mos) >= 95:
                # MoS-extreme path — pick clamp side from sign of MoS.
                # Positive MoS = price below FV (FV >> px → high side).
                # Negative MoS = price above FV (FV << px → low side).
                _trigger = "mos_extreme"
                if _mos >= 0:
                    _clamped_fv = round(_px * 3.0, 2) if _px > 0 else 0.0
                else:
                    _clamped_fv = round(_px * 0.1, 2) if _px > 0 else 0.0

            if _trigger is not None and _px > 0 and _clamped_fv is not None:
                # Replace FV + recompute MoS off the clamped bound.
                result.valuation.fair_value = _clamped_fv
                _new_mos = round(((_clamped_fv - _px) / _px) * 100.0, 2)
                result.valuation.margin_of_safety = _new_mos
                result.valuation.margin_of_safety_display = _new_mos
                result.valuation.mos_is_extreme = False
                result.valuation.mos_extreme_note = None
                result.valuation.data_limited = True
                # Preserve existing data_issues text — clamp adds to it,
                # never silently replaces.
                _issues = list(getattr(result, "data_issues", []) or [])
                _issues.append(
                    "[caution] Fair value clamped to plausible bound — "
                    f"trigger={_trigger}."
                )
                result.data_issues = _issues
                # Emit a structured caution note (cap at 5 to match
                # AnalyticalNoteOutput contract in models/responses.py).
                try:
                    from backend.models.responses import AnalyticalNoteOutput
                    _bodies = {
                        "fv_zero": (
                            "Computed fair value was zero or negative — likely "
                            "missing or NULL upstream cash-flow inputs. We have "
                            "clamped the displayed fair value to 10% of the "
                            "current price as a floor; treat the headline number "
                            "as a data-quality signal rather than a price target."
                        ),
                        "iv_px_high": (
                            "Computed fair value was more than 3x the current "
                            "price. This usually reflects an extrapolation "
                            "issue (negative discount rate, extreme growth "
                            "input, or a one-off cash-flow spike). We have "
                            "clamped the displayed fair value to 3x price."
                        ),
                        "iv_px_low": (
                            "Computed fair value was less than 10% of the "
                            "current price. This usually reflects depressed "
                            "trough cash flows or a peer-band miss. We have "
                            "clamped the displayed fair value to 10% of price."
                        ),
                        "mos_extreme": (
                            "Computed margin of safety exceeded ±95% — beyond "
                            "what the model can claim with confidence. Fair "
                            "value has been clamped to the nearest plausible "
                            "bound; the displayed MoS reflects the clamped FV."
                        ),
                    }
                    _note = AnalyticalNoteOutput(
                        kind="data_quality",
                        severity="caution",
                        title="Fair value clamped — data quality",
                        body=_bodies.get(_trigger, _bodies["fv_zero"]),
                    )
                    _notes = list(getattr(result, "analytical_notes", []) or [])
                    if len(_notes) < 5:
                        _notes.append(_note)
                        result.analytical_notes = _notes
                except Exception:
                    pass
        except Exception:
            pass

        # Cache for 24h — analysis data doesn't change fast, and cold-recomputes
        # hit yfinance which is the slowest link.
        cache.set(_cache_key, result, ttl=86400)
        # Also populate tier-0 raw dict so subsequent requests on this
        # worker skip Pydantic re-validation + FastAPI serialization
        # entirely (the slow parts of the warm path).
        try:
            _raw = result.model_dump(mode="json") if hasattr(result, "model_dump") else result.dict()
            _raw["cached"] = True
            cache.set(_cache_key + ":raw", _raw, ttl=86400)
        except Exception:
            pass

        # Tier-2 write-back: persist so other workers / post-restart
        # requests skip compute. Best-effort; failures are logged and
        # swallowed inside the service (must never fail the response).
        try:
            _compute_ms = int((_time.monotonic() - _compute_start) * 1000)
            _payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result.dict()
            analysis_cache_service.save_cached(ticker, _payload, _compute_ms)
        except Exception as _write_exc:
            import logging as _logging
            _logging.getLogger("yieldiq.analysis").warning(
                "analysis_cache: write-back failed for %s: %s", ticker, _write_exc
            )

        if not include_summary:
            # Cache retains the full object (including any ai_summary the
            # service populated); only the response to this caller is trimmed.
            try:
                result = result.model_copy(update={"ai_summary": None})
            except Exception:
                result.ai_summary = None
        # Return as JSONResponse so the X-Cache=MISS header is the
        # only X-Cache value set on this response. Mutating the
        # `response: Response` param previously caused FastAPI to
        # merge it with JSONResponse-set headers from the fast paths,
        # which surfaced as "X-Cache: HIT-MEM-RAW, MISS" at the wire.
        from fastapi.responses import JSONResponse as _JSONResponse
        from fastapi.encoders import jsonable_encoder as _je
        _inject_sector_medians_model(result, ticker)
        _inject_multiples_fv_model(result)
        # Phase C (2026-06-10): Phase-B estimators MUST run BEFORE
        # composite so the four new estimator slots
        # (three_stage_fv / ddm_fv / epv_per_share /
        # probability_weighted_fv) are populated on the model when
        # the composite helper reads them via getattr().
        _inject_phase_b_estimators_model(result)
        _inject_composite_iv_model(result)
        # T5.3 (2026-06-10) — derived insights synthesize composite
        # + confidence + floor/ceiling + sector calibration. Runs
        # AFTER composite + Phase B on the cold-compute path.
        _inject_derived_insights_model(result)
        # Cross-engine consensus signal (2026-06-10) — direction
        # agreement count across DCF + Multiples + Wall St + four
        # Phase-B estimators. Additive field; runs after composite +
        # Phase B so every estimator is reachable.
        _inject_consensus_signal_model(result)
        # ROOT CAUSE #1 (2026-06-10): canonical headline FV — single
        # source of truth for hero / caveat / FAQ / AI-Why / OG /
        # JSON-LD / peer / Chat / PDF. MUST run AFTER composite.
        _inject_headline_fair_value_model(result)
        return _JSONResponse(
            content=_je(result),
            headers={"X-Cache": "MISS", **_usage_headers},
        )
    except TickerNotFoundError:
        # Data provider returned nothing for this symbol. 404 lets the
        # frontend distinguish "bad ticker" from "our service broke".
        _detail: dict = {"error": "Ticker not found", "ticker": original_ticker}
        _note = KNOWN_BROKEN_TICKERS.get(original_ticker)
        if _note:
            _detail["note"] = _note
        raise HTTPException(status_code=404, detail=_detail)
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.analysis").error(f"Analysis failed for {ticker}: {e}", exc_info=True)
        # str(e) can include env-var values (e.g. DATABASE_URL with password,
        # JWT_SECRET) when they get concatenated into upstream error messages.
        raise HTTPException(status_code=500, detail=f"Analysis failed: {type(e).__name__}")


class _UTF8JSONResponse(_FastAPIJSONResponse):
    """JSONResponse that declares `charset=utf-8` on the Content-Type.

    FastAPI's stock JSONResponse sets `media_type = "application/json"`
    with NO charset parameter. The body bytes are UTF-8 (json.dumps
    default), but downstream consumers without an explicit charset
    declaration may fall back to latin-1 — which decodes the UTF-8
    bytes `e2 82 b9` (₹) as the three latin-1 chars `â‚¹`. See the
    `get_og_data` docstring for the boundary this fixes.
    """

    media_type = "application/json; charset=utf-8"


@router.get(
    "/analysis/{ticker}/og-data",
    response_class=_UTF8JSONResponse,
)
async def get_og_data(
    ticker: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    """Return Open Graph data for social sharing. No auth required.

    Encoding boundary (2026-06-07, fix/og-data-utf8-mojibake):
        The response body contains literal ₹ (U+20B9) in the `description`
        field. FastAPI's default `application/json` Content-Type does NOT
        include a `charset=utf-8` parameter, and downstream consumers
        (Next.js Satori Edge runtime fetch, OG scrapers like WhatsApp /
        Twitterbot / Slackbot) fall back to latin-1 when no charset is
        declared, decoding the UTF-8 bytes `e2 82 b9` as the three latin-1
        chars `â‚¹`. Result: OG-image titles on yieldiq.in rendered
        "â‚¹1,146" instead of "₹1,146" on every social share preview.
        Fix: explicit `application/json; charset=utf-8` on every return
        path below via `_OG_JSON_MEDIA_TYPE`. Bytes in the body are
        unchanged; only the Content-Type header gains the charset
        parameter so consumers stop guessing.

    Cache-source unification (2026-04-22):
        Previously called `service.get_full_analysis()` directly and
        cached the result under its own `og:{ticker}` key. That meant
        og-data served a DIFFERENT canonical value than
        /public/stock-summary when the two computed in different
        contexts (cold worker, partial yfinance outage, etc.).

        INFY.NS and NESTLEIND.NS were observed returning fv=0/price=0
        /verdict=under_review via og-data while /public/stock-summary
        returned real numbers (fv=1916.74, score=76, undervalued) — the
        og: cache had poisoned zeros from an earlier failed compute,
        and the 1-hour TTL was re-poisoning itself every cycle.

        New path matches /public/stock-summary's tiered lookup:
            1. Local og: cache (1h) — fast path
            2. `analysis:{ticker}` tier-1 in-memory cache (24h)
            3. `analysis_cache_service.get_cached()` tier-2 Postgres
            4. `service.get_full_analysis()` live compute (last resort)

        Same source of truth as /public/stock-summary + the authed
        /analysis endpoint. Also adds a zero-poison guard: if the
        resolved payload has both fair_value and current_price == 0,
        we do NOT write it into the og: cache — a fresh compute gets
        to try again on the next request.
    """
    original_ticker = ticker.upper().strip()
    # Route renamed/rebranded symbols to the canonical equivalent BEFORE
    # any cache lookup or compute. Without this, /og-data/LTIM.NS bypasses
    # the LTIM.NS → LTIMINDTREE.NS alias the other endpoints honor and
    # cold-computes against the stale yfinance row, producing fv=0/px=0
    # and tripping VALIDATION CRITICAL on every page-view (Sentry flood
    # 2026-05-03: 13,964 events/24h on LTIM alone). Mirrors the rewrite
    # that GET /analysis/{ticker} and /analysis/preview/{ticker} apply.
    ticker = TICKER_ALIASES.get(original_ticker, original_ticker)
    # ── Telemetry (additive) ── only fires for signed-in callers.
    # Records the canonical (post-alias) ticker so analytics aggregate
    # LTIM.NS hits under LTIMINDTREE.NS like the cache does.
    try:
        from backend.services.page_view_service import record_page_view as _rpv
        _email = (user or {}).get("email") if isinstance(user, dict) else None
        if _email:
            background_tasks.add_task(
                _rpv,
                user_email=_email,
                page_kind="analysis",
                ticker=ticker,
                path=str(request.url.path),
                user_agent=request.headers.get("user-agent"),
                referrer=request.headers.get("referer"),
            )
    except Exception:
        pass
    _cache_key = f"og:{ticker}"
    # version_keyed=True (2026-05-16): the og cache previously poisoned ITC.NS
    # with fv=0/data_limited because the mos-suspicion gate below was tripping
    # on legitimate deep-value FMCG MoS (~107%), and a CACHE_VERSION bump had
    # no way to flush this projection — the 1h TTL kept re-poisoning. Making
    # og: version-keyed means a CACHE_VERSION bump (or this PR's deploy, since
    # the unversioned `og:ITC.NS` entry becomes unreachable on read) moves us
    # into a fresh key namespace and stale entries TTL-reap in the background.
    cached = cache.get(_cache_key, version_keyed=True)
    if cached:
        return cached

    try:
        # Tiered cache resolution — matches public/stock-summary so all
        # three endpoints (og-data, public stock-summary, authed analysis)
        # serve the same canonical AnalysisResponse.
        result = cache.get(f"analysis:{ticker}")
        if result is None or not hasattr(result, "valuation"):
            try:
                from backend.services import analysis_cache_service
                from backend.models.responses import AnalysisResponse
                _db_payload = analysis_cache_service.get_cached(ticker)
                if _db_payload:
                    result = AnalysisResponse(**_db_payload)
                    cache.set(f"analysis:{ticker}", result, ttl=86400)
            except Exception:
                result = None
        if result is None or not hasattr(result, "valuation"):
            # Last resort: live compute. Any output zeros here will be
            # caught by the zero-poison guard below rather than cached.
            # PERF: blocking sync call → thread pool. See PR #83 note.
            import asyncio as _asyncio
            result = await _asyncio.to_thread(service.get_full_analysis, ticker)
        display_ticker = ticker.replace(".NS", "").replace(".BO", "")

        # ── Output sanity gate (router-level defense in depth) ──
        # If FV/price ratio > 3x or |MoS| > 200%, suppress the numbers
        # here at the edge so users never see them even if some upstream
        # path forgot to gate. Defensive — the analysis_service also
        # has this check, but duplicating at the router is cheap.
        # AUDIT5_P0B_FAIR_VALUE_FLOOR parity (Day-100, 2026-05-22):
        # Apply the same engine-FV→base_case fallthrough that
        # _extract_analysis_summary uses, via the shared helper in
        # backend/services/summary_projection.py. Without this, og-data
        # rendered "₹0 fair value" on ULTRACEMCO.NS OG cards while the
        # public stock-summary endpoint surfaced base_case=3028 — same
        # AnalysisResponse, two different user-facing numbers.
        from backend.services.summary_projection import (
            resolve_display_mos as _resolve_mos,
            resolve_fair_value as _resolve_fv,
        )
        _fv_resolved = _resolve_fv(
            result.valuation.fair_value,
            getattr(result.valuation, "base_case", None),
        )
        _fv = float(_fv_resolved if _fv_resolved is not None else 0)
        _px = float(result.valuation.current_price or 0)
        # ── EXTREME_MOS_DISPLAY_SUPPRESSION (2026-05-24) ──────────
        # Public-surface parity with /public/stock-summary: when the
        # analysis pipeline flagged `mos_is_extreme=True` (e.g. KALYANI.NS
        # MoS=829% / verdict=under_review), surface None so the OG card
        # / share-link consumer renders "—" instead of "+829% upside".
        # `_suspicious` below still gets to run on the raw value so the
        # router's defense-in-depth gate keeps catching genuine outliers.
        _raw_mos = result.valuation.margin_of_safety
        _mos_extreme_flag = bool(getattr(result.valuation, "mos_is_extreme", False))
        _mos_display = _resolve_mos(_raw_mos, _mos_extreme_flag)
        _mos = float(_raw_mos or 0)
        _verdict = result.valuation.verdict
        _suspicious = False
        try:
            # Positive price with zero/negative FV → NBFC-style DCF
            # failure (e.g. PFC.NS). The validator was firing
            # mos=-100% on these; gate it here too.
            if _px > 0 and _fv <= 0:
                _suspicious = True
            if _px > 0 and _fv > 0:
                _r = _fv / _px
                if _r > 3.0 or _r < 0.1:
                    _suspicious = True
            # Reverted from |mos|>=95 → >200 on 2026-05-16. The tighter
            # threshold was added to catch a -100% case, but that case is
            # already covered by the explicit `_px > 0 and _fv <= 0` guard
            # above, and the FV/price ratio bounds (0.1/3.0) catch real
            # outliers symmetrically. The 95% threshold false-positived on
            # legitimate deep-value FMCG (ITC.NS: mos=107%, fv=640, px=309,
            # ratio=2.07 — well inside the ratio gate). Public stock-summary
            # never applied this gate and was already serving the correct
            # value, so divergence between og-data and stock-summary was
            # entirely produced by this single line.
            if abs(_mos) > 200:
                _suspicious = True
        except Exception:
            pass
        if _suspicious:
            _verdict = "data_limited"
            _fv = 0.0
            _mos = 0.0
            _mos_display = 0.0

        verdict_text = _verdict.replace("_", " ").title()
        if _suspicious:
            desc = (
                f"{result.company.company_name} — valuation under review. "
                f"Current price ₹{_px:,.0f}. Fair value temporarily unavailable."
            )
        else:
            desc = (
                f"{result.company.company_name} fair value ₹{_fv:,.0f} "
                f"vs price ₹{_px:,.0f}. "
                f"Score: {result.quality.yieldiq_score}/100. "
                f"Moat: {result.quality.moat}."
            )

        og = {
            "title": f"{display_ticker} — {verdict_text} | YieldIQ",
            "description": desc,
            "ticker": ticker,
            "score": result.quality.yieldiq_score,
            "verdict": _verdict,
            "fair_value": _fv,
            "price": _px,
            # `_mos_display` is None when mos_is_extreme fired (raw _mos
            # could be 829 in that case — see EXTREME_MOS_DISPLAY_SUPPRESSION
            # above). Frontend renders "—" for null.
            "mos": _mos_display,
        }

        # ── Scenario + ratio fields (feat/ogdata-add-scenarios-ratios) ──
        # Additive plumbing only — these values are already computed and
        # cached as part of the AnalysisResponse. Exposing them here lets
        # the canary harness exercise Gates 3 (scenario_dispersion) and
        # 4 (canary_bounds) against the unauth /og-data endpoint after
        # PR #243 switched canary off the admin-gated /analysis path.
        #
        # When `_suspicious` zero-clamped the headline FV/MoS above, also
        # suppress scenario IVs so we don't surface DCF outputs that the
        # router just declared unreliable. Ratios (roe/roce/ev_ebitda)
        # come from non-DCF paths and stay valid even in data_limited.
        # All getters are guarded; None is returned for any missing field
        # (e.g. banks legitimately have no ev_ebitda).
        def _safe_attr(obj: Any, *path: str) -> Any:
            for p in path:
                if obj is None:
                    return None
                obj = getattr(obj, p, None)
            return obj

        if _suspicious:
            og["bear_case"] = None
            og["base_case"] = None
            og["bull_case"] = None
        else:
            og["bear_case"] = _safe_attr(result, "valuation", "bear_case")
            og["base_case"] = _safe_attr(result, "valuation", "base_case")
            og["bull_case"] = _safe_attr(result, "valuation", "bull_case")
        og["roe"] = _safe_attr(result, "quality", "roe")
        og["roce"] = _safe_attr(result, "quality", "roce")
        og["wacc"] = _safe_attr(result, "valuation", "wacc")
        og["ev_ebitda"] = _safe_attr(result, "insights", "ev_ebitda")
        # feat/wire-quarterly-xbrl-to-analysis: TTM source provenance.
        # Lets the canary harness verify nse_xbrl fires for the 41
        # NIFTY-50 tickers and yfinance fires for everything else.
        og["ttm_source"] = _safe_attr(result, "valuation", "ttm_source")
        og["quarterly_last_filed_at"] = _safe_attr(
            result, "valuation", "quarterly_last_filed_at",
        )

        # ── Coverage tier (feat/coverage-tier-system) ──
        # Additive labeling only — tells the user how confident we are in
        # the modeled output. Never modifies FV/score/verdict. Returns
        # None on failure so a tier-service hiccup can't break og-data.
        # See backend/services/coverage_tier_service.py for the rubric.
        try:
            from backend.services import coverage_tier_service as _cts
            _ct = _cts.summary_for_og(ticker)
            if _ct:
                og["coverage_tier"] = _ct
        except Exception:
            pass
        # Zero-poison guard: if both fv and price ended up 0 (cold compute
        # failure, upstream data gap, etc.), skip the cache write so the
        # next request gets a fresh attempt. Previously the 1-hour TTL
        # on bad data created a self-perpetuating poison cycle for any
        # ticker that failed a single cold compute. Verdict-based cases
        # (real "under_review" with a known-bad reason) still cache —
        # they have a valid price and are legitimately labeled.
        if _fv == 0 and _px == 0:
            return og
        cache.set(_cache_key, og, ttl=3600, version_keyed=True)
        return og
    except Exception as exc:
        # SEO stub fallback when the analysis pipeline raises.
        # Historically a bare `except: pass` swallowed every error here,
        # which is why the LTIMINDTREE silent crash in PR #673 went
        # undetected for hours — the response shape stayed valid but
        # Railway/Sentry never saw the underlying traceback. Always
        # emit a structured log + Sentry capture so a future regression
        # surfaces immediately. Never let the logging path itself raise.
        import logging as _logging
        _log = _logging.getLogger("yieldiq.analysis")
        try:
            _log.exception(
                "og_data_analysis_failed",
                extra={
                    "ticker": ticker,
                    "exception_type": type(exc).__name__,
                },
            )
        except Exception:
            pass
        try:
            import sentry_sdk as _sentry_sdk
            _sentry_sdk.capture_exception(exc)
        except Exception:
            pass
        return {
            "title": f"{ticker} Stock Analysis | YieldIQ",
            "description": "Free DCF valuation for Indian stocks. Know if a stock is undervalued.",
        }


@router.get("/analysis/preview/{ticker}")
async def get_analysis_preview(ticker: str):
    """
    Public preview of stock analysis — no auth required.
    Returns limited data for share links.
    Rate limited to prevent abuse.
    """
    ticker = ticker.upper().strip()

    # Apply alias rewrites (renames + nicknames) so colloquial requests
    # like /analysis/preview/HUL resolve to HINDUNILVR.NS instead of
    # 404-ing through TickerNotFoundError. Caught in PR #83 health audit.
    # MUST run BEFORE the cache key is computed below so HUL and HINDUNILVR
    # share a single edge-cache + in-memory cache entry.
    ticker = TICKER_ALIASES.get(ticker, ticker)
    try:
        from data_pipeline import ticker_aliases as _aliases_mod
        _canonical = _aliases_mod.resolve_nickname(ticker)
        if _canonical:
            ticker = _canonical if "." in _canonical else f"{_canonical}.NS"
    except Exception:
        pass

    # PERF (egress, PR #85): wrap responses with Vercel-edge Cache-Control
    # so repeat hits to share/preview links are absorbed by the CDN without
    # backend (and Neon) round-trips. Public preview is identical for every
    # viewer of a given ticker - no per-user data, no JWT - so a public
    # s-maxage is safe.
    from fastapi.responses import JSONResponse as _JSONResponse
    _CC = "public, s-maxage=900, stale-while-revalidate=3600"

    # Check cache first
    _cache_key = f"preview:{ticker}"
    cached = cache.get(_cache_key)
    if cached:
        return _JSONResponse(content=cached, headers={"Cache-Control": _CC})

    try:
        # PERF: blocking sync call → thread pool. See PR #83 note.
        import asyncio as _asyncio
        result = await _asyncio.to_thread(service.get_full_analysis, ticker)

        # Output sanity gate — same as og-data and main /analysis
        _fv = float(result.valuation.fair_value or 0)
        _px = float(result.valuation.current_price or 0)
        _mos = float(result.valuation.margin_of_safety or 0)
        _verdict = result.valuation.verdict
        # ── EXTREME_MOS_DISPLAY_SUPPRESSION (2026-05-24) ──────────
        # Parity with /og-data and /public/stock-summary: suppress the
        # displayed MoS to None when the pipeline flagged it as extreme.
        from backend.services.summary_projection import (
            resolve_display_mos as _resolve_mos_preview,
        )
        _mos_display = _resolve_mos_preview(
            result.valuation.margin_of_safety,
            bool(getattr(result.valuation, "mos_is_extreme", False)),
        )
        try:
            _suspicious = False
            if _px > 0 and _fv > 0:
                _r = _fv / _px
                if _r > 3.0 or _r < 0.1:
                    _suspicious = True
            if abs(_mos) > 200:
                _suspicious = True
            if _suspicious:
                _verdict = "data_limited"
                _fv = 0.0
                _mos = 0.0
                _mos_display = 0.0
        except Exception:
            pass

        # Strip sensitive/premium data for public preview
        # NOTE: result.company is a Pydantic CompanyInfo — must convert to
        # dict before going into the response dict, else FastAPI's JSONEncoder
        # raises TypeError: Object of type CompanyInfo is not JSON serializable.
        # Hotfix #313.
        _company_dict = (
            result.company.model_dump(mode="json") if hasattr(result.company, "model_dump")
            else (result.company.dict() if hasattr(result.company, "dict") else dict(result.company))
        )
        preview = {
            "ticker": result.ticker,
            "company": _company_dict,
            "valuation": {
                "fair_value": _fv,
                "current_price": _px,
                "margin_of_safety": _mos_display,
                "verdict": _verdict,
                "wacc": result.valuation.wacc,
                "confidence_score": result.valuation.confidence_score,
            },
            "quality": {
                "yieldiq_score": result.quality.yieldiq_score,
                "grade": result.quality.grade,
                "piotroski_score": result.quality.piotroski_score,
                "moat": result.quality.moat,
            },
            "preview": True,
            "cta": "Sign up free to see full analysis with scenarios, insights, and more",
        }
        cache.set(_cache_key, preview, ttl=3600)  # 1 hour cache
        return _JSONResponse(content=preview, headers={"Cache-Control": _CC})
    except Exception as e:
        import logging
        import traceback as _tb
        # Full traceback to console + Sentry so diagnosis isn't lost.
        # PR #305 was reverted partly because the masked "(details
        # suppressed)" response in the client made it impossible to
        # tell whether the failure was UnboundLocalError vs Pydantic
        # validation vs upstream data. exc_info=True hands the full
        # exception chain to the configured logging handlers (Sentry
        # picks it up via the LoggingIntegration breadcrumbs already
        # wired in backend/observability/sentry.py).
        _log = logging.getLogger("yieldiq.analysis")
        _log.error(
            "og-data failed for %s: %s", ticker, type(e).__name__,
            exc_info=True,
        )
        # Explicit Sentry capture in case the LoggingIntegration is
        # downgraded (we have seen breadcrumb-only mode in staging).
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:  # noqa: BLE001
            pass
        # Defence-in-depth: also dump to stderr so docker/Railway logs
        # capture the trace even if the Python logger is misconfigured.
        _tb.print_exc()
        # Never return raw str(e) — can leak env-var values
        # (DATABASE_URL, JWT_SECRET, etc.) embedded in upstream
        # exception messages.
        return {"error": f"{type(e).__name__} (details suppressed)", "ticker": ticker}


# Timeout for the underlying LLM call (Gemini → Groq fallback). If the
# provider hangs beyond this, we return 503 rather than let the HTTP
# request block indefinitely. 10s matches what the frontend is willing
# to wait before showing a retry affordance.
_AI_SUMMARY_TIMEOUT_S = 10.0

# 24h TTL for the summary cache. Summary is derived from analysis which
# itself caches 24h, so there's no point re-asking the LLM more often.
_AI_SUMMARY_CACHE_TTL_S = 86400


@router.get("/analysis/{ticker}/summary")
async def get_ai_summary(ticker: str, user: dict = Depends(get_current_user)):
    """AI plain-English summary for a ticker.

    Returns ``{ticker, summary, model, generated_at, cached}``.

    Separate endpoint so the main ``/analysis/{ticker}`` payload can
    return instantly without waiting 5-15s for Gemini/Groq. Cache is
    the in-memory ``cache_service`` keyed by ``ai_summary:{ticker}`` for
    24h. On upstream LLM timeout or failure, returns 503 with
    ``{error: "summary_unavailable", retry_after: 30}`` so the frontend
    can degrade gracefully rather than render a fake summary.
    """
    import asyncio
    import logging
    from datetime import datetime, timezone

    ticker = ticker.upper().strip()
    _log = logging.getLogger("yieldiq.ai_summary")

    # ── Tier 1: in-memory cache ─────────────────────────────────
    _summary_cache_key = f"ai_summary:{ticker}"
    cached_summary = cache.get(_summary_cache_key)
    if cached_summary:
        return {**cached_summary, "cached": True}

    # ── Need the underlying analysis to build the summary prompt ─
    _analysis_cache_key = f"analysis:{ticker}"
    analysis = cache.get(_analysis_cache_key)
    if analysis is None:
        try:
            # PERF: blocking sync call → thread pool. See PR #83 note.
            analysis = await asyncio.to_thread(service.get_full_analysis, ticker)
        except TickerNotFoundError:
            raise HTTPException(
                status_code=404,
                detail={"error": "Ticker not found", "ticker": ticker},
            )

    # ── Call the LLM with a hard timeout ────────────────────────
    # generate_ai_summary is sync (HTTP-bound), so offload to a thread
    # and wrap with asyncio.wait_for for a clean cancellation boundary.
    try:
        summary = await asyncio.wait_for(
            asyncio.to_thread(service.get_ai_summary, ticker, analysis),
            timeout=_AI_SUMMARY_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        _log.warning(f"[{ticker}] AI summary timed out after {_AI_SUMMARY_TIMEOUT_S}s")
        raise HTTPException(
            status_code=503,
            detail={"error": "summary_unavailable", "retry_after": 30},
        )
    except Exception as exc:  # noqa: BLE001 — surface any LLM failure as 503
        _log.error(f"[{ticker}] AI summary failed: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=503,
            detail={"error": "summary_unavailable", "retry_after": 30},
        )

    # service.get_ai_summary swallows LLM errors and returns "" — treat
    # that as an upstream failure for this endpoint (the contract says
    # no fake/empty summaries). The main /analysis endpoint keeps the
    # swallow-and-return-empty behaviour separately so legacy callers
    # that embed summary inline don't regress.
    if not summary:
        raise HTTPException(
            status_code=503,
            detail={"error": "summary_unavailable", "retry_after": 30},
        )

    payload = {
        "ticker": ticker,
        "summary": summary,
        # Model identity isn't plumbed back from data_helpers.generate_ai_summary
        # today (it tries Gemini first, then Groq). Report the family name so
        # the frontend can display something useful without us lying about it.
        "model": "groq-llama-3.3-70b-versatile",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
    cache.set(_summary_cache_key, payload, ttl=_AI_SUMMARY_CACHE_TTL_S)
    return payload


def _load_screener_csv() -> list[ScreenerStock]:
    """Read screener_results.csv if available. Returns [] on any error."""
    try:
        import pandas as pd
        from pathlib import Path
        _path = Path(__file__).resolve().parent.parent.parent / "data" / "screener_results.csv"
        if not _path.exists():
            return []
        df = pd.read_csv(_path)
        _score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score", "yiq_score")), None)
        _ticker_col = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), df.columns[0])
        _mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct", "margin_of_safety")), None)
        _company_col = next((c for c in df.columns if c.lower() in ("company", "company_name", "name")), None)
        _moat_col = next((c for c in df.columns if "moat" in c.lower()), None)
        _sector_col = next((c for c in df.columns if c.lower() in ("sector", "sector_name")), None)
        if _score_col:
            df = df.nlargest(50, _score_col)
        out: list[ScreenerStock] = []
        for _, row in df.iterrows():
            _s = int(row.get(_score_col, 0)) if _score_col else 0
            _m = float(row.get(_mos_col, 0)) if _mos_col else 0.0
            if _s > 0:
                out.append(ScreenerStock(
                    ticker=str(row.get(_ticker_col, "")),
                    company_name=str(row.get(_company_col, "")) if _company_col else "",
                    score=_s,
                    margin_of_safety=_m,
                    moat=str(row.get(_moat_col, "")) if _moat_col else "",
                    sector=str(row.get(_sector_col, "")) if _sector_col else "",
                ))
        return out
    except Exception:
        return []


def _load_cached_analyses() -> list[ScreenerStock]:
    """Read warm AnalysisResponse entries from the in-process cache."""
    out: list[ScreenerStock] = []
    try:
        for key in list(cache._store.keys()):
            if key.startswith("analysis:") and ".NS" in key:
                val = cache.get(key)
                if val and hasattr(val, "quality") and val.quality.yieldiq_score > 30:
                    out.append(ScreenerStock(
                        ticker=val.ticker,
                        company_name=val.company.company_name,
                        score=val.quality.yieldiq_score,
                        margin_of_safety=round(val.valuation.margin_of_safety, 1),
                        # Step B (2026-05-17): surface true Buffett MoS so
                        # leaderboard sort + UI labels can use the right field.
                        buffett_mos_pct=getattr(val.valuation, "buffett_mos_pct", None),
                        moat=val.quality.moat,
                        sector=val.company.sector,
                        verdict=val.valuation.verdict,
                    ))
    except Exception:
        pass
    return out


async def _build_yieldiq50() -> ScreenerResponse:
    """Build the YieldIQ 50 ScreenerResponse (no HTTP concerns).

    Split out from the HTTP handler so internal callers (e.g.
    get_top_pick) can consume the pydantic model directly, without
    the JSONResponse wrapping the HTTP endpoint applies for cache
    headers.
    """
    _cache_key = f"yieldiq50:{date.today().isoformat()}"

    # RAW dict cache — rebuild ScreenerResponse from the dict so the
    # return type is stable for all callers. HTTP handler adds cache
    # headers separately; internal callers get the model.
    _raw = cache.get(_cache_key + ":raw")
    if _raw is not None:
        try:
            return ScreenerResponse(**_raw)
        except Exception:
            # Corrupt/old raw cache — fall through and rebuild.
            pass

    cached = cache.get(_cache_key)
    if cached:
        try:
            _dump = cached.model_dump(mode="json") if hasattr(cached, "model_dump") else cached
            cache.set(_cache_key + ":raw", _dump, ttl=86400)
        except Exception:
            pass
        return cached

    by_ticker: dict[str, ScreenerStock] = {}
    # Merge in priority order; first-seen wins per ticker.
    for source in (_load_screener_csv(), _load_cached_analyses()):
        for s in source:
            if s.ticker and s.ticker not in by_ticker:
                by_ticker[s.ticker] = s

    # 2026-04-21 fix: previous behaviour returned 1 stock when CSV +
    # warm cache were both empty. Discover page looked broken. Add a
    # 3rd source: query fair_value_history + stocks directly from DB
    # so YieldIQ 50 always has the actual top-50 by score, even on a
    # cold cache.
    #
    # 2026-04-22 P0-#2/#3 fix: the DB fallback previously surfaced
    # negative-MoS rows and micro-caps with blown-up MoS (e.g. ADSL
    # +164%, NAM-INDIA -73%) into the "top undervalued" rail. Two
    # guardrails now applied at the SQL layer:
    #   - require mos_pct strictly > 0 AND verdict NOT IN bad-list
    #   - require market_cap_cr >= 1000 (small-cap floor) — micro-caps
    #     with tiny denominators produce unreliable DCF outputs that
    #     should not anchor the headline Discover rail.
    # Extra in-Python |mos|<=100 clamp catches any rows that slipped
    # past the SQL market-cap check (e.g. missing market_metrics row).
    if len(by_ticker) < 50:
        try:
            from data_pipeline.db import Session as _S
            from sqlalchemy import text as _t
            if _S is not None:
                _db = _S()
                try:
                    rows = _db.execute(_t("""
                        -- 2026-04-29 fix: fair_value_history.ticker is mixed-form.
                        -- The live analysis hot path (store_today_fair_value) writes
                        -- canonical ".NS"-suffixed tickers; the monthly backfill
                        -- script writes bare ones. stocks.ticker is always bare,
                        -- so the previous JOIN s.ticker = fv.ticker silently
                        -- dropped every row written by the live path — i.e. all
                        -- recently-analysed stocks (the ones most likely to have
                        -- a fresh, valid MoS). Result: the DB fallback returned
                        -- few or zero rows and Discover rendered "warming up".
                        -- Normalise fv.ticker to bare form on the JOIN so both
                        -- writers' rows participate.
                        WITH latest_fv AS (
                          SELECT DISTINCT ON (ticker)
                            ticker,
                            -- bare form for joining to stocks/market_metrics
                            CASE
                              WHEN ticker LIKE '%.NS' OR ticker LIKE '%.BO'
                                THEN split_part(ticker, '.', 1)
                              ELSE ticker
                            END AS ticker_bare,
                            fair_value, price, mos_pct, verdict
                          FROM fair_value_history
                          ORDER BY ticker, date DESC
                        ),
                        latest_mm AS (
                          -- 2026-04-25 fix: market_metrics' date column is
                          -- `trade_date`, not `date`. Previously this CTE
                          -- raised UndefinedColumn at runtime; the outer
                          -- try/except swallowed it and the entire DB
                          -- fallback returned zero rows, leaving Discover
                          -- to render "YieldIQ 50 is warming up" whenever
                          -- the in-process cache and CSV were empty.
                          -- PR #218 read-path fallback: skip NULL-mcap rows + prefer high-trust source.
                          -- Prevents 2026-04-30 yfinance-NULL incident class.
                          SELECT DISTINCT ON (ticker)
                            ticker, market_cap_cr
                          FROM market_metrics
                          WHERE market_cap_cr IS NOT NULL AND market_cap_cr > 0
                          ORDER BY ticker, COALESCE(data_quality_rank, 50) ASC, trade_date DESC
                        )
                        SELECT
                          fv.ticker_bare AS ticker,
                          s.company_name,
                          s.sector,
                          fv.mos_pct,
                          fv.verdict,
                          mm.market_cap_cr,
                          fv.fair_value,
                          fv.price
                        FROM latest_fv fv
                        JOIN stocks s ON s.ticker = fv.ticker_bare
                        LEFT JOIN latest_mm mm ON mm.ticker = fv.ticker_bare
                        WHERE fv.mos_pct IS NOT NULL
                          AND fv.mos_pct > 0
                          -- 2026-05-17 tighten: cap MoS at 50% (was 100).
                          -- |mos|>50 implies tiny FV/price denominators —
                          -- HUHTAMAKI surfaced at +99% under the old cap.
                          AND fv.mos_pct <= 50
                          -- Positive fair value required — fv=0 means the
                          -- DCF blew up / IPO row with no model output.
                          AND fv.fair_value > 0
                          AND s.is_active = TRUE
                          AND (fv.verdict IS NULL OR fv.verdict NOT IN (
                            'avoid','under_review','data_limited','overvalued'
                          ))
                          AND COALESCE(mm.market_cap_cr, 0) >= 1000
                          -- Stale fair_value_history rows must not surface
                          -- when the live analysis_cache verdict has since
                          -- flipped to a bad bucket. YESBANK was the case
                          -- in point (overvalued in cache, "undervalued"
                          -- in the day-old fair_value_history row).
                          --
                          -- 2026-05-18 fix: analysis_cache stores tickers
                          -- in their CANONICAL form (e.g. RELIANCE.NS) per
                          -- analysis_cache_service._canonical_cache_key,
                          -- but fv.ticker_bare is bare (RELIANCE). The
                          -- previous `ac.ticker = fv.ticker_bare` join
                          -- never matched for Indian tickers, so the
                          -- EXISTS clause rejected every row from the
                          -- DB fallback — leaving Discover stuck on
                          -- "warming up" whenever the in-process cache
                          -- and screener_results.csv were empty (i.e.
                          -- after every Railway cold-start). Match both
                          -- bare and .NS-suffixed forms via IN so the
                          -- check works regardless of writer source.
                          AND EXISTS (
                            SELECT 1 FROM analysis_cache ac
                            WHERE ac.ticker IN (
                                fv.ticker_bare,
                                fv.ticker_bare || '.NS',
                                fv.ticker_bare || '.BO'
                              )
                              AND (ac.payload->'valuation'->>'verdict') NOT IN (
                                'avoid','under_review','data_limited','overvalued'
                              )
                          )
                        ORDER BY fv.mos_pct DESC NULLS LAST
                        LIMIT 80
                    """)).fetchall()
                    for r in rows:
                        t = r[0]
                        if t in by_ticker:
                            continue
                        # Score not persisted in fair_value_history;
                        # synthesize a reasonable proxy from MoS so the
                        # row renders without "—".
                        mos = float(r[3]) if r[3] is not None else 0.0
                        # Defensive clamp — SQL already filters mos<=50
                        # (2026-05-17 tighten) but belt-and-braces for any
                        # historical row that slipped through with stale value.
                        if not (0 < mos <= 50):
                            continue
                        # synth_score capped at 50 floor so the downstream
                        # `_ok_for_top50(score>=50)` gate never drops a
                        # row purely on the synthesised proxy. Real cache
                        # override (below) replaces with live score.
                        synth_score = min(95, max(50, int(50 + mos * 0.5)))
                        _row_fv = float(r[6]) if len(r) > 6 and r[6] is not None else 0.0
                        _row_cp = float(r[7]) if len(r) > 7 and r[7] is not None else 0.0
                        # 2026-04-29 hotfix: ScreenerStock.moat / sector are
                        # typed as `str` (non-Optional, default ""), so passing
                        # `None` here raised a pydantic ValidationError on the
                        # FIRST row and the outer `except Exception: pass`
                        # below swallowed it — emptying `by_ticker` and
                        # leaving the endpoint with 0 results. Pass empty
                        # strings to match the schema. PR #181's ticker
                        # normalisation was correct upstream; this is the
                        # downstream construction bug that hid behind it.
                        # Step B (2026-05-17): derive Buffett MoS from upside.
                        # upside = (fv-cp)/cp; buffett = (fv-cp)/fv = upside/(1+upside).
                        _u_dec = mos / 100.0
                        _buffett = (
                            round(_u_dec / (1 + _u_dec) * 100.0, 1)
                            if (1 + _u_dec) > 0 else None
                        )
                        by_ticker[t] = ScreenerStock(
                            ticker=t,
                            company_name=r[1] or t,
                            score=synth_score,
                            fair_value=_row_fv,
                            current_price=_row_cp,
                            margin_of_safety=round(mos, 1),
                            buffett_mos_pct=_buffett,
                            moat="",
                            sector=r[2] or "",
                            verdict=r[4] or (
                                "undervalued" if mos > 10
                                else "fairly_valued"
                            ),
                        )
                        if len(by_ticker) >= 50:
                            break
                finally:
                    _db.close()
        except Exception:
            pass  # never block the response on the DB fallback

    # Re-fetch each known ticker against the LIVE PG-cached row so we
    # never serve a stale score/MoS once the live cache has fresher data.
    # Iterates only over tickers we already discovered above (CSV +
    # warm cache) — no static seed list any more.
    for t in list(by_ticker.keys()):
        try:
            cached_payload = analysis_cache_service.get_cached(t)
        except Exception:
            cached_payload = None
        if not cached_payload:
            continue
        try:
            v = cached_payload.get("valuation", {}) or {}
            q = cached_payload.get("quality", {}) or {}
            c = cached_payload.get("company", {}) or {}
            live_mos = v.get("margin_of_safety")
            live_score = q.get("yieldiq_score")
            if live_mos is None or live_score is None:
                continue
            prev = by_ticker[t]
            # Step B (2026-05-17): pull buffett_mos_pct from the cached
            # payload when present; otherwise derive from upside (live_mos).
            _live_buffett = v.get("buffett_mos_pct")
            if _live_buffett is None:
                try:
                    _u_dec = float(live_mos) / 100.0
                    _live_buffett = round(_u_dec / (1 + _u_dec) * 100.0, 1) if (1 + _u_dec) > 0 else None
                except Exception:
                    _live_buffett = None
            # 2026-05-17: surface fair_value + current_price from the
            # cached payload so the downstream `_ok_for_top50` integrity
            # filter can enforce fv>0 (rejects DCF blow-ups / IPO rows
            # like WAAREEINDO that pass score/MoS but have no real FV).
            _live_fv = v.get("fair_value") or 0
            _live_cp = v.get("current_price") or v.get("price") or 0
            by_ticker[t] = ScreenerStock(
                ticker=t,
                company_name=c.get("company_name") or prev.company_name,
                score=int(live_score),
                fair_value=float(_live_fv) if _live_fv is not None else 0,
                current_price=float(_live_cp) if _live_cp is not None else 0,
                margin_of_safety=round(float(live_mos), 1),
                buffett_mos_pct=_live_buffett,
                moat=q.get("moat") or prev.moat,
                sector=c.get("sector") or prev.sector,
                verdict=v.get("verdict") or (
                    "undervalued" if live_mos > 10 else "fairly_valued" if live_mos > -10 else "overvalued"
                ),
            )
        except Exception:
            # Best-effort — keep the pre-override row from the source merge
            continue

    # ── P0-#2/#3 integrity filter (2026-04-22) ─────────────────
    # The YieldIQ 50 is shipped to Discover as the "top undervalued
    # picks" rail. It must never surface:
    #   - negative-MoS stocks (the model says OVERvalued)
    #   - |MoS| > 100% (micro-cap DCF blow-ups with tiny FV or price
    #     denominators — ADSL +164%, INDIANHUME +100% etc.)
    #   - verdicts that explicitly say "don't trust this":
    #     avoid / under_review / data_limited / overvalued
    #   - micro-caps < ₹1,000 Cr (FV volatility dominates in this
    #     bucket; better to hide than to rank #1)
    # ScreenerStock has no market_cap field, so the micro-cap gate is
    # enforced upstream in the fair_value_history SQL + by preferring
    # the analysis_cache override (which only exists for analysed
    # tickers that have passed the per-ticker validator). If a
    # ScreenerStock reaches this point with |mos|>100 or a bad
    # verdict, drop it unconditionally.
    _BAD_VERDICTS = {"avoid", "under_review", "data_limited", "overvalued"}
    def _ok_for_top50(s: "ScreenerStock") -> bool:
        try:
            mos = float(s.margin_of_safety)
        except Exception:
            return False
        # 2026-05-17 tighten: cap MoS at 50% (was 100). HUHTAMAKI was
        # surfacing at the +99% clamp ceiling — implausible for a mid-
        # cap consumer name and a clear signal of FV/price-denominator
        # blow-up rather than a genuine bargain.
        if not (0 < mos <= 50):
            return False
        if (s.verdict or "").lower() in _BAD_VERDICTS:
            return False
        # Score floor: anything below 50 is below the "quality" line
        # of the YieldIQ score (a 0-100 composite). COALINDIA/ORBTEXP/
        # EMBDL were surfacing at score=40 with 40-70% MoS.
        if (getattr(s, "score", None) or 0) < 50:
            return False
        # Positive fair value required — fv<0 is always a broken DCF run
        # (recent IPOs / data-sparse names like WAAREEINDO). We allow
        # fv==0 to mean "source didn't set the field" (CSV / pre-cache-
        # merge rows) so we don't blank the rail; upstream SQL + the
        # cache-merge path explicitly enforce fv>0 when they touch the row.
        try:
            fv = float(getattr(s, "fair_value", 0) or 0)
        except Exception:
            fv = 0.0
        if fv < 0:
            return False
        # dcf_reliable check when the field exists on the row (analysis
        # cache merge path attaches it; the fair_value_history fallback
        # path does not — it'll just no-op via the hasattr guard).
        if hasattr(s, "dcf_reliable") and getattr(s, "dcf_reliable") is False:
            return False
        return True

    _filtered = [s for s in by_ticker.values() if _ok_for_top50(s)]

    # ── Foundation PR (2026-04-29): data-completeness gate ─────
    # YieldIQ 50 must never surface tickers with sparse fundamentals.
    # `data_completeness_score` is a 0-1 confidence aggregator over
    # annual financials count, key-field population, classifier
    # confidence, quality-metric computability, and market-cap
    # presence. Threshold YIELDIQ50_MIN_COMPLETENESS (0.70) drops
    # tickers like CAPLIPOINT (sector="General/Diversified",
    # industry="") and CAPITALSFB (mis-tagged "Chemicals" sector)
    # that previously slipped past the curated-set guards.
    #
    # Soft-fail: if the DB session is unavailable or the gate
    # raises for any reason, keep the pre-gate list — never blank
    # the rail. Logs every drop for the post-launch audit.
    try:
        from backend.services.data_quality import (
            data_completeness_score,
            YIELDIQ50_MIN_COMPLETENESS,
        )
        from data_pipeline.db import Session as _GateSession
        _gated: list[ScreenerStock] = []
        _gate_db = _GateSession() if _GateSession is not None else None
        if _gate_db is not None:
            try:
                for s in _filtered:
                    try:
                        rep = data_completeness_score(s.ticker, _gate_db)
                    except Exception:
                        # Per-ticker failure: keep the row (don't punish
                        # a transient DB hiccup by hiding good stocks).
                        _gated.append(s)
                        continue
                    if rep.score >= YIELDIQ50_MIN_COMPLETENESS:
                        _gated.append(s)
                _filtered = _gated
            finally:
                try:
                    _gate_db.close()
                except Exception:
                    pass
    except Exception:
        # Module import / global DB failure — fall through to the
        # pre-gate list so the rail never blanks on a foundation bug.
        pass

    # Step B (2026-05-17): sort by `buffett_mos_pct` (the true discount
    # to fair value) when present, falling back to legacy `margin_of_safety`
    # (upside %) for rows that pre-date the field. Both sorts produce the
    # same ordering when FV > CP (monotone transform), so the change is
    # cosmetically additive — but Buffett MoS is the honest leaderboard
    # key going forward. Tie-break by score for stability.
    def _sort_key(s):
        b = getattr(s, "buffett_mos_pct", None)
        return (b if b is not None else s.margin_of_safety, s.score)
    stocks = sorted(_filtered, key=_sort_key, reverse=True)[:50]
    result = ScreenerResponse(results=stocks, total=len(stocks))
    if stocks:
        # PR-DISCOVER-CONSISTENCY: TTL was 24h. Audit found Discover
        # served ITC at static 38% MoS all day even after the SEO page
        # showed live -1.7%. Root cause: this cache was set at the
        # first morning request when analysis_cache for ITC was empty,
        # so the static seed won and got frozen for 24h. Shortening to
        # 5 min lets the per-ticker override (lines ~722-750) re-run
        # frequently — within 5 min of any user-triggered analysis,
        # Discover reflects the updated MoS.
        cache.set(_cache_key, result, ttl=300)
        try:
            cache.set(_cache_key + ":raw", result.model_dump(mode="json"), ttl=300)
        except Exception:
            pass
    return result


@router.get("/yieldiq50", response_model=ScreenerResponse)
async def get_yieldiq50(response: Response, user: dict = Depends(get_current_user)):
    """Top 50 undervalued high-quality stocks. Cached for 5 minutes.

    Sources are merged (not exclusive) and deduped by ticker:
      1. Real screener CSV output (highest priority — real scores)
      2. Warm AnalysisResponse cache (real scores from recent runs)

    On a cold cache (no screener CSV, no warm in-process entries) we
    return an empty list with HTTP 200 — frontend should treat
    `total == 0` as "warming, check back shortly".

    HTTP-layer concern: when the raw dict cache is warm, set edge
    cache headers so Vercel/CDN can reuse responses. Auth-gated data,
    so private. 1h max-age is fine since the list is recomputed daily.
    The underlying data build is delegated to _build_yieldiq50 so that
    internal callers (get_top_pick) get a typed ScreenerResponse and
    are not affected by this HTTP-only wrapping.
    """
    _cache_key = f"yieldiq50:{date.today().isoformat()}"
    if cache.get(_cache_key + ":raw") is not None:
        response.headers["X-Cache"] = "HIT-MEM-RAW"
        response.headers["Cache-Control"] = "private, max-age=3600"
    return await _build_yieldiq50()


@router.get("/top-pick")
async def get_top_pick(user: dict = Depends(get_current_user)):
    """Highest conviction stock from YieldIQ 50. Never returns score 0."""
    yiq50 = await _build_yieldiq50()

    # Defensive: `_build_yieldiq50` can return a bare dict or a cached
    # JSONResponse on rare fallback paths (e.g. a stale raw-cache entry
    # that failed ScreenerResponse rehydration). Guard against both
    # rather than crash with 'JSONResponse' object has no attribute 'results'.
    results = getattr(yiq50, "results", None)
    if results is None and isinstance(yiq50, dict):
        results = yiq50.get("results")
    if not results:
        return None

    # Filter for valid high-conviction stocks.
    # 2026-05-17 tighten: the headline "top pick" card on the home
    # dashboard needs a higher bar than the rail. Require score >= 60
    # and 10% <= MoS <= 40% so we never surface either low-quality
    # names or implausibly-large discounts (typical signal of a stale
    # FV or DCF blow-up).
    valid = [
        r for r in results
        if getattr(r, "score", 0) >= 60
        and 10 <= getattr(r, "margin_of_safety", 0) <= 40
    ]

    if valid:
        # Sort by combined conviction: 60% score + 40% MoS (capped at 50)
        best = max(valid, key=lambda r: getattr(r, "score", 0) * 0.6 + min(getattr(r, "margin_of_safety", 0), 50) * 0.4)
        return {
            "ticker": getattr(best, "ticker", ""),
            "company_name": getattr(best, "company_name", ""),
            "score": getattr(best, "score", 0),
            "mos": getattr(best, "margin_of_safety", 0),
            "moat": getattr(best, "moat", ""),
            "summary": "",
        }

    # Fallback — never show score 0
    return None


# Debug endpoints — keep for now, remove before public launch
@router.get("/debug/parquet-status")
async def debug_parquet_status(user: dict = Depends(_require_admin)):
    """Diagnostic: check if Parquet files exist on this Railway instance."""
    import os
    from pathlib import Path

    # Check db_integration's PARQUET_DIR
    try:
        from data_pipeline.nse_prices.db_integration import PARQUET_DIR, _parquet_path
        pdir = str(PARQUET_DIR)
        exists = PARQUET_DIR.exists()
        files = sorted([f.name for f in PARQUET_DIR.glob("*.parquet")]) if exists else []
        hal_path = _parquet_path("HAL.NS")
    except Exception as exc:
        return {"error": f"import failed: {exc}"}

    # Check DB connectivity
    db_status = "unknown"
    try:
        from backend.services.analysis_service import _get_pipeline_session, _db_dead_until
        import time
        if time.time() < _db_dead_until:
            db_status = f"COOLDOWN (expires in {int(_db_dead_until - time.time())}s)"
        else:
            sess = _get_pipeline_session()
            db_status = "CONNECTED" if sess else "None (no DATABASE_URL)"
            if sess:
                try:
                    sess.close()
                except Exception:
                    pass
    except Exception as exc:
        db_status = f"error: {exc}"

    # Check local assembler
    local_status = "unknown"
    try:
        from backend.services.local_data_service import assemble_local
        local_status = "importable"
    except Exception as exc:
        local_status = f"import failed: {exc}"

    return {
        "parquet_dir": pdir,
        "parquet_dir_exists": exists,
        "file_count": len(files),
        "sample_files": files[:5],
        "hal_exists": hal_path.exists(),
        "hal_path": str(hal_path),
        "cipla_exists": _parquet_path("CIPLA.NS").exists(),
        "db_status": db_status,
        "local_assembler": local_status,
        "cwd": os.getcwd(),
        "database_url_set": bool(os.environ.get("DATABASE_URL")),
    }


@router.get("/debug/test-local/{ticker}")
async def debug_test_local(ticker: str, user: dict = Depends(_require_admin)):
    """Test local assembler directly — returns result or error."""
    ticker = ticker.upper().strip()
    import time as _t
    try:
        from backend.services.analysis_service import _get_pipeline_session
        t0 = _t.time()
        sess = _get_pipeline_session()
        db_time = _t.time() - t0
        if sess is None:
            return {"error": "session is None", "db_time_ms": round(db_time * 1000)}

        from backend.services.local_data_service import assemble_local
        t1 = _t.time()
        result = assemble_local(ticker, sess)
        asm_time = _t.time() - t1
        try:
            sess.close()
        except Exception:
            pass

        if result is None:
            return {"error": "assemble_local returned None", "db_time_ms": round(db_time * 1000), "asm_time_ms": round(asm_time * 1000)}

        return {
            "ok": True,
            "ticker": ticker,
            "price": result.get("price"),
            "source": result.get("_source"),
            "db_time_ms": round(db_time * 1000),
            "asm_time_ms": round(asm_time * 1000),
            "total_ms": round((db_time + asm_time) * 1000),
        }
    except Exception as exc:
        return {"error": str(exc), "type": type(exc).__name__}


@router.get("/search")
async def search_stocks(
    q: str = "",
    user: dict | None = Depends(get_current_user_optional),
):
    """
    Search Indian stocks by name, ticker, or keyword.
    No auth required — works for everyone.
    Examples: "reliance", "tcs", "hdfc", "airtel", "mankind"
    """
    results = search_tickers(q, limit=8)
    return {"query": q, "results": results}


# ── Chart data endpoint ──────────────────────────────────────
_PERIOD_MAP = {"1m": "1mo", "3m": "3mo", "6m": "6mo", "1y": "1y"}


@router.get("/analysis/{ticker}/chart-data")
async def get_chart_data(
    ticker: str,
    period: str = "1m",
    user: dict = Depends(get_current_user),
):
    """Get price history and financial data for charts."""
    ticker = ticker.upper().strip()
    yf_period = _PERIOD_MAP.get(period, "1mo")

    _cache_key = f"chart_data:{ticker}:{period}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    # --- Price history ---
    # Source priority:
    #   1. DuckDB Parquet  (fastest; local file, <50ms)
    #   2. `daily_prices` Postgres table (bhavcopy-sourced, daily refresh)
    #   3. yfinance live  (emergency fallback; Sentry-tagged so we can
    #      track how often bhavcopy coverage is missing)
    _PERIOD_DAYS = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
    _days = _PERIOD_DAYS.get(period, 30)
    prices: list[dict] = []
    _clean = ticker.replace(".NS", "").replace(".BO", "")

    # Helper to guard against NaN/inf leaking into JSON. `float(nan)`
    # round-trips fine in Python but FastAPI's JSONEncoder raises
    # "Out of range float values are not JSON compliant: nan" on
    # serialize. Sentry was catching ~36 events/week from this on
    # chart-data alone. Return None for non-finite values so the
    # frontend can render a gap in the line chart cleanly.
    import math as _math
    def _num(v):
        try:
            f = float(v)
            return round(f, 2) if _math.isfinite(f) else None
        except (TypeError, ValueError):
            return None

    # 1. Parquet (primary)
    try:
        from data_pipeline.nse_prices.db_integration import get_price_history
        df = get_price_history(_clean, _days)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                _p = _num(row["close"])
                if _p is None:
                    continue  # skip rows with NaN close
                prices.append({
                    "date": str(row["date"])[:10],
                    "price": _p,
                })
    except Exception:
        pass

    # 2. Postgres daily_prices (secondary — fed by NSE bhavcopy loader)
    if not prices:
        try:
            from data_pipeline.db import Session as _PipelineSession
            if _PipelineSession is not None:
                from sqlalchemy import text
                from datetime import date as _date, timedelta as _td
                _sess = _PipelineSession()
                try:
                    _start = _date.today() - _td(days=_days)
                    rows = _sess.execute(
                        text(
                            "SELECT trade_date, close_price "
                            "FROM daily_prices "
                            "WHERE ticker = :t AND trade_date >= :start "
                            "ORDER BY trade_date ASC"
                        ),
                        {"t": _clean, "start": _start},
                    ).mappings().all()
                    for r in rows:
                        _p = _num(r["close_price"])
                        if _p is None:
                            continue
                        prices.append({
                            "date": str(r["trade_date"])[:10],
                            "price": _p,
                        })
                finally:
                    try:
                        _sess.close()
                    except Exception:
                        pass
        except Exception:
            pass

    # 3. Fallback to yfinance only if neither parquet nor daily_prices had rows.
    # Warning log + Sentry tag so we can monitor how often this path fires.
    if not prices:
        try:
            import logging as _logging
            _logging.getLogger("yieldiq.analysis").warning(
                "chart-data fell back to yfinance for %s (parquet + daily_prices both empty)",
                ticker,
            )
            try:
                import sentry_sdk as _sentry_sdk
                _sentry_sdk.set_tag("data_source", "yfinance_fallback")
                _sentry_sdk.set_tag("endpoint", "chart-data")
            except Exception:
                pass

            import yfinance as yf
            hist = yf.Ticker(ticker).history(period=yf_period)
            if hist is not None and not hist.empty:
                hist = hist.reset_index()
                for _, row in hist.iterrows():
                    _p = _num(row["Close"])
                    if _p is None:
                        continue
                    prices.append({
                        "date": row["Date"].strftime("%Y-%m-%d"),
                        "price": _p,
                    })
        except Exception:
            pass  # prices stays empty → frontend falls back to mock

    # --- Financial data (revenue + FCF) from FinancialsService ---
    # Same canonical source as /analysis/{ticker}/financials so both
    # widgets on the page agree. The service returns values in Crores
    # (INR) or Millions (non-INR); we convert to raw units here because
    # the FinancialBars frontend formatter expects raw rupees / dollars.
    financials: dict = {}
    try:
        from backend.services.financials_service import FinancialsService

        svc = FinancialsService()
        fin = svc.get_financials(ticker, period="annual", years=5)

        # Currency unit determines the multiplier back to raw units.
        unit = (fin or {}).get("currency_unit", "Cr")
        scale = 1e7 if unit == "Cr" else 1e6  # Cr → ₹, M → $

        revenue_list: list[dict] = []
        fcf_list: list[dict] = []

        # income / cash_flow are the same merged year rows in the service
        # response. Iterate income for revenue, cash_flow for FCF; both
        # are sorted newest→oldest from the service. Reverse not needed —
        # the frontend sorts by year.localeCompare.
        for row in (fin or {}).get("income", []) or []:
            year_str: str | None = None
            pe = row.get("period_end")
            if pe:
                # period_end is ISO YYYY-MM-DD; chart-data is annual
                year_str = pe[:4]
            if not year_str:
                # fall back to formatted period (e.g. FY2025)
                year_str = str(row.get("year") or "")
            # Sector-aware revenue fall-back (2026-06-10). For banks
            # / NBFCs the generic `revenue` field is null — the
            # statement carries `interest_earned`, `net_interest_income`,
            # and `total_income` instead. Without this fall-back the
            # FinancialBars surface for bank tickers renders flat-zero
            # bars even though the data exists. The frontend
            # sectorFinancials helper also applies the same waterfall
            # when reading row-level FinancialYear values directly;
            # keeping the backend consistent means BOTH ingestion
            # paths agree about what "the revenue series" is for a
            # bank ticker.
            rev_v = _num(row.get("revenue"))
            if rev_v is None:
                rev_v = _num(row.get("interest_earned"))
            if rev_v is None:
                rev_v = _num(row.get("net_interest_income"))
            if rev_v is None:
                rev_v = _num(row.get("total_income"))
            if rev_v is not None and year_str:
                revenue_list.append({
                    "year": year_str,
                    "value": round(rev_v * scale),
                })

        for row in (fin or {}).get("cash_flow", []) or []:
            year_str = None
            pe = row.get("period_end")
            if pe:
                year_str = pe[:4]
            if not year_str:
                year_str = str(row.get("year") or "")
            fcf_v = _num(row.get("free_cash_flow"))
            if fcf_v is not None and year_str:
                fcf_list.append({
                    "year": year_str,
                    "value": round(fcf_v * scale),
                })

        if revenue_list or fcf_list:
            financials = {"revenue": revenue_list, "fcf": fcf_list}
    except Exception:
        pass  # financials stays empty → frontend shows empty state

    result = {"prices": prices, "period": period, "financials": financials}
    # PERF (egress): bumped 900s -> 21600s (6h). Chart data turns over
    # daily (bhavcopy refresh) and CACHE_VERSION bumps invalidate on real
    # analysis changes; 15 min was wastefully short and re-hit Neon for
    # daily_prices on every miss.
    cache.set(_cache_key, result, ttl=21600)
    return result


@router.get("/analysis/{ticker}/fv-history")
async def get_fv_history_endpoint(
    ticker: str,
    years: int = Query(default=3, ge=1, le=5),
    user: dict = Depends(get_current_user_optional),
):
    """
    Historical YieldIQ fair value vs market price.

    Tier limits:
      - free      → 1 year max
      - starter   → 3 years max
      - pro       → 5 years max
    """
    ticker = ticker.upper().strip()

    tier = (user or {}).get("tier", "free")
    tier_order = {"free": 0, "starter": 1, "pro": 2}
    tier_level = tier_order.get(tier, 0)
    if tier_level == 0:
        years = min(years, 1)
    elif tier_level == 1:
        years = min(years, 3)
    # pro: no clamp beyond the Query's le=5

    # Two-tier cache: tier 1 in-memory (per-worker, fast), tier 2
    # endpoint_cache DB table (shared, survives redeploys). Both keyed
    # by ticker + years since the response shape depends on years.
    # fv-history is safe to cache long (history only grows forward, and
    # the chart smooths over any 1-day staleness).
    _fvh_cache_key = f"fv-history:{ticker}:{years}"
    _mem_hit = cache.get(_fvh_cache_key)
    if _mem_hit is not None:
        _mem_hit_out = dict(_mem_hit)
        _mem_hit_out["tier"] = tier
        _mem_hit_out["tier_limited"] = tier_level == 0
        return _mem_hit_out

    from backend.services import endpoint_cache_service as _ecs
    _db_hit = _ecs.get(_fvh_cache_key)
    if _db_hit is not None:
        # Populate tier-1 so subsequent hits on this worker skip the DB
        cache.set(_fvh_cache_key, _db_hit, ttl=3600)
        _db_hit_out = dict(_db_hit)
        _db_hit_out["tier"] = tier
        _db_hit_out["tier_limited"] = tier_level == 0
        return _db_hit_out

    # Pipeline DB session — same pattern as analysis_service._get_pipeline_session
    try:
        from data_pipeline.db import Session as PipelineSession
    except Exception:
        PipelineSession = None

    if PipelineSession is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    db = PipelineSession()
    try:
        from data_pipeline.sources.fv_history import (
            get_fv_history,
            get_fv_history_summary,
        )
        data = get_fv_history(ticker, db, years)
        summary = get_fv_history_summary(ticker, db, years)

        if not data:
            _empty = {
                "ticker": ticker,
                "has_data": False,
                "years_returned": 0,
                "data": [],
                "summary": summary,
                "message": (
                    "Historical fair value data is building up. "
                    "Analyse this stock regularly to grow the chart."
                ),
            }
            # Cache the empty-state too — cheaper than re-running the query
            # every request. Shorter TTL (1h) so we recheck soon after a
            # seed.
            cache.set(_fvh_cache_key, _empty, ttl=3600)
            try:
                _ecs.set(_fvh_cache_key, _empty, ttl_hours=1)
            except Exception:
                pass
            return {**_empty, "tier": tier, "tier_limited": tier_level == 0}

        _full = {
            "ticker": ticker,
            "has_data": True,
            "years_returned": years,
            "data": data,
            "summary": summary,
        }
        cache.set(_fvh_cache_key, _full, ttl=3600)
        try:
            _ecs.set(_fvh_cache_key, _full, ttl_hours=6)
        except Exception:
            pass
        return {**_full, "tier": tier, "tier_limited": tier_level == 0}
    finally:
        db.close()


from pydantic import BaseModel as _BatchBaseModel


class FVHistoryBatchRequest(_BatchBaseModel):
    tickers: list[str]
    years: int = 1


@router.post("/analysis/fv-history/batch")
async def fv_history_batch(
    req: FVHistoryBatchRequest,
    user: dict = Depends(get_current_user_optional),
):
    """Batched fair-value vs price history for a list of tickers.

    One call per portfolio render is dramatically cheaper than N calls
    to ``/analysis/{ticker}/fv-history``: every result is served from
    the same two-tier cache the singular endpoint uses, and the DB
    session is opened once for the whole batch.

    Cap: 50 tickers per request. ``years`` is clamped to 1 here so the
    sparkline payload stays small — full multi-year history is still
    available via the per-ticker endpoint.

    Response shape:
        { "<TICKER>": { "has_data": bool, "data": [...], "summary": {...} }, ... }
    """
    if not req.tickers:
        return {}
    if len(req.tickers) > 50:
        raise HTTPException(
            status_code=400,
            detail="Batch size capped at 50 tickers per request",
        )

    # Sparklines only ever render 1y; force the clamp regardless of
    # what the caller asks for. Keeps payload + cache key narrow.
    years = 1
    out: dict[str, dict] = {}

    from backend.services import endpoint_cache_service as _ecs

    # Open a single pipeline session for cache-miss tickers.
    db = None
    PipelineSession = None
    try:
        from data_pipeline.db import Session as PipelineSession  # noqa: F401
    except Exception:
        PipelineSession = None

    for raw in req.tickers:
        ticker = (raw or "").upper().strip()
        if not ticker:
            continue

        _key = f"fv-history:{ticker}:{years}"

        # tier 1: in-memory
        hit = cache.get(_key)
        if hit is None:
            # tier 2: shared DB endpoint cache
            try:
                hit = _ecs.get(_key)
            except Exception:
                hit = None
            if hit is not None:
                cache.set(_key, hit, ttl=3600)

        if hit is not None:
            out[ticker] = {
                "has_data": bool(hit.get("has_data")),
                "data": hit.get("data", []) or [],
                "summary": hit.get("summary", {}),
            }
            continue

        # DB miss — pull from pipeline
        if PipelineSession is None:
            out[ticker] = {"has_data": False, "data": [], "summary": {}}
            continue
        if db is None:
            db = PipelineSession()
        try:
            from data_pipeline.sources.fv_history import (
                get_fv_history,
                get_fv_history_summary,
            )
            data = get_fv_history(ticker, db, years)
            summary = get_fv_history_summary(ticker, db, years)
            payload = {
                "ticker": ticker,
                "has_data": bool(data),
                "years_returned": years if data else 0,
                "data": data,
                "summary": summary,
            }
            cache.set(_key, payload, ttl=3600)
            try:
                _ecs.set(_key, payload, ttl_hours=1 if not data else 6)
            except Exception:
                pass
            out[ticker] = {
                "has_data": payload["has_data"],
                "data": payload["data"],
                "summary": payload["summary"],
            }
        except Exception as exc:
            # Never let one bad ticker poison the batch.
            out[ticker] = {"has_data": False, "data": [], "summary": {}, "error": str(exc)[:120]}

    if db is not None:
        try:
            db.close()
        except Exception:
            pass

    return out


@router.get("/analysis/{ticker}/financials")
async def get_financials_endpoint(
    ticker: str,
    period: str = Query(default="annual", pattern="^(annual|quarterly)$"),
    years: int = Query(default=5, ge=1, le=10),
    user: dict = Depends(get_current_user_optional),
):
    """
    Full financial statements (5y annual / 8q quarterly).

    Tier limits:
      - free       → 5 years max (annual); quarterly unaffected
      - starter+   → 5 years max

    Issue #205 (2026-06-07): raised the free-tier annual cap from
    3y → 5y. The 3y CAGR computation in ``_compute_summary`` needs
    4 data points (latest + 3 prior) to land a real 3-year CAGR;
    capping at 3 left anonymous users with a perpetually-null
    ``revenue_cagr_3y`` and broke the "Show 3Y CAGR" UI badge.
    Bumping to 5 leaves a paid-tier delta for the deeper history /
    quarterly slice while unblocking the free-tier surface.
    """
    ticker = ticker.upper().strip()

    tier = (user or {}).get("tier", "free")
    tier_order = {"free": 0, "starter": 1, "pro": 2}
    tier_level = tier_order.get(tier, 0)
    tier_limited = tier_level == 0
    # Issue #205: free tier annual cap raised 3y → 5y so CAGR populates.
    # Quarterly cap is untouched. Paid tiers continue to receive 5y.
    if period == "annual":
        years = min(years, 5)

    _cache_key = f"financials:{ticker}:{period}:{years}"

    # Tier 1: in-memory
    cached = cache.get(_cache_key)
    if cached:
        return cached

    # Tier 2: persistent endpoint_cache. Survives Railway redeploys.
    # Tier info varies by user so we re-stamp it per response; the
    # underlying statement rows are shared across tiers.
    from backend.services import endpoint_cache_service as _ecs
    _db_hit = _ecs.get(_cache_key)
    if _db_hit is not None:
        cache.set(_cache_key, _db_hit, ttl=86400)
        _out = dict(_db_hit)
        _out["tier"] = tier
        _out["tier_limited"] = tier_limited
        return _out

    from backend.services.financials_service import FinancialsService
    svc = FinancialsService()
    try:
        result = svc.get_financials(ticker, period=period, years=years)
    except Exception as exc:
        import logging
        logging.getLogger("yieldiq.financials").error(
            "Financials failed for %s: %s", ticker, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Financials unavailable")

    # Persist WITHOUT tier stamping so other users of the same ticker
    # can reuse the row. The tier annotation below is response-only.
    cache.set(_cache_key, result, ttl=86400)
    try:
        _ecs.set(_cache_key, result, ttl_hours=24)
    except Exception:
        pass

    result["tier"] = tier
    result["tier_limited"] = tier_limited
    return result


@router.get("/analysis/{ticker}/peers")
async def get_peers_endpoint(
    ticker: str,
    user: dict = Depends(get_current_user_optional),
):
    """
    Peer comparison table for ``ticker``.

    YieldIQ score/grade/FV/MoS are read off the in-process cache — a
    peer's score is only populated if it has been analysed recently.
    Valuation multiples and quality metrics come from the DB, with a
    yfinance live fallback for tickers missing from the DB snapshot.
    """
    ticker = ticker.upper().strip()

    _cache_key = f"peers:{ticker}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    try:
        from data_pipeline.db import Session as PipelineSession
    except Exception:
        PipelineSession = None

    db = PipelineSession() if PipelineSession is not None else None
    try:
        from backend.services.peers_service import PeersService
        svc = PeersService()
        result = svc.get_peer_comparison(ticker, db=db, cache=cache)
    except Exception as exc:
        import logging
        logging.getLogger("yieldiq.peers").error(
            "Peer comparison failed for %s: %s", ticker, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Peer comparison unavailable")
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

    if result.get("has_peers"):
        cache.set(_cache_key, result, ttl=86400)  # 30 min
    return result


@router.get("/analysis/{ticker}/dividends")
async def get_dividends_endpoint(
    ticker: str,
    user: dict = Depends(get_current_user_optional),
):
    """
    Live dividend data from yfinance (history + yield + payout).

    Coverage ratio is omitted here because the router has no
    access to the ``enriched`` dict. The same data is embedded in
    the main ``/analysis/{ticker}`` response under
    ``insights.dividend`` — use that when available.
    """
    ticker = ticker.upper().strip()

    _cache_key = f"dividends:{ticker}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    from backend.services.dividend_service import DividendService
    try:
        result = DividendService().get_dividends(ticker, enriched=None)
    except Exception as exc:
        import logging
        logging.getLogger("yieldiq.dividends").error(
            "Dividend endpoint failed for %s: %s", ticker, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Dividend data unavailable")

    cache.set(_cache_key, result, ttl=86400)  # 30 min
    return result


@router.get("/compare")
async def compare_stocks(
    ticker1: str,
    ticker2: str,
    user: dict = Depends(get_current_user),
):
    """Compare two stocks side by side."""
    ticker1 = ticker1.upper().strip()
    ticker2 = ticker2.upper().strip()

    # Tier-cap: enforce per-tier compare ticker limit. Today the endpoint
    # only takes 2 tickers, so this check is inert at the contractual
    # `cap >= 2` floor — but it keeps the cap centralised so the future
    # multi-ticker compare endpoint will inherit enforcement for free.
    # De-dup so comparing TICKER vs TICKER counts as 1, not 2.
    requested_tickers = {t for t in (ticker1, ticker2) if t}
    n = len(requested_tickers)
    cap = cap_for(user.get("tier", "free"), "compare_tickers")
    if n > cap:
        tier_name = user.get("tier", "free")
        raise HTTPException(
            status_code=403,
            detail={
                "error": "compare_ticker_cap_reached",
                "tier": tier_name,
                "cap": cap,
                "requested": n,
                "message": (
                    f"Your {tier_name.title()} plan allows comparing up to "
                    f"{cap} stocks. Upgrade to compare more."
                ),
                "upgrade_link": "/pricing",
            },
        )

    # Get both analyses (uses cache if available).
    # PERF: blocking sync call → thread pool, run concurrently. See PR #83.
    import asyncio as _asyncio
    a1, a2 = await _asyncio.gather(
        _asyncio.to_thread(service.get_full_analysis, ticker1),
        _asyncio.to_thread(service.get_full_analysis, ticker2),
    )

    return {
        "stock1": {
            "ticker": a1.ticker,
            "company_name": a1.company.company_name,
            "sector": a1.company.sector,
            "price": a1.valuation.current_price,
            "fair_value": a1.valuation.fair_value,
            "mos": a1.valuation.margin_of_safety,
            "verdict": a1.valuation.verdict,
            "score": a1.quality.yieldiq_score,
            "piotroski": a1.quality.piotroski_score,
            "moat": a1.quality.moat,
            "moat_score": a1.quality.moat_score,
            "wacc": a1.valuation.wacc,
            "fcf_growth": a1.valuation.fcf_growth_rate,
            "confidence": a1.valuation.confidence_score,
            "roe": a1.quality.roe,
            "de_ratio": a1.quality.de_ratio,
        },
        "stock2": {
            "ticker": a2.ticker,
            "company_name": a2.company.company_name,
            "sector": a2.company.sector,
            "price": a2.valuation.current_price,
            "fair_value": a2.valuation.fair_value,
            "mos": a2.valuation.margin_of_safety,
            "verdict": a2.valuation.verdict,
            "score": a2.quality.yieldiq_score,
            "piotroski": a2.quality.piotroski_score,
            "moat": a2.quality.moat,
            "moat_score": a2.quality.moat_score,
            "wacc": a2.valuation.wacc,
            "fcf_growth": a2.valuation.fcf_growth_rate,
            "confidence": a2.valuation.confidence_score,
            "roe": a2.quality.roe,
            "de_ratio": a2.quality.de_ratio,
        },
        "winner": {
            "score": ticker1 if a1.quality.yieldiq_score > a2.quality.yieldiq_score else ticker2,
            "value": ticker1 if a1.valuation.margin_of_safety > a2.valuation.margin_of_safety else ticker2,
            "quality": ticker1 if a1.quality.piotroski_score > a2.quality.piotroski_score else ticker2,
            "moat": ticker1 if a1.quality.moat_score > a2.quality.moat_score else ticker2,
        }
    }


@router.get("/analysis/{ticker}/reverse-dcf")
async def get_reverse_dcf_endpoint(
    ticker: str,
    wacc: float | None = Query(default=None, ge=0.05, le=0.25, description="Override WACC (5%-25%)"),
    terminal_g: float | None = Query(default=None, ge=0.0, le=0.06, description="Override terminal growth (0%-6%)"),
    years: int = Query(default=10, ge=5, le=15),
    user: dict = Depends(get_current_user_optional),
):
    """
    Reverse DCF — what FCF growth rate is the market implying?
    Optional WACC and terminal growth overrides for sensitivity analysis.
    Returns implied growth, verdict, scenarios, and plain-English summary.
    """
    ticker = ticker.upper().strip()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"

    # Resolve aliases
    ticker = TICKER_ALIASES.get(ticker, ticker)

    # Cache key includes overrides. version_keyed=True so a
    # CACHE_VERSION bump (which by definition changes FV / MoS /
    # implied-growth math) hard-retires the previous generation;
    # see cache_service.py.
    _cache_key = f"reverse_dcf:{ticker}:{wacc}:{terminal_g}:{years}"
    cached = cache.get(_cache_key, version_keyed=True)
    if cached:
        return cached

    try:
        result = service.get_reverse_dcf(
            ticker=ticker,
            wacc_override=wacc,
            terminal_g_override=terminal_g,
            years=years,
        )
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])

        # CONSISTENCY FIX (single price snapshot per ticker): the prism
        # endpoint already overrides its `price` via the canonical cascade
        # (live_quotes → daily_prices → yfinance). The reverse-dcf path
        # historically used the cached AnalysisResponse.valuation.current_price
        # which can drift up to a TTL behind the prism number. SBIN was the
        # canary — fair-value page showed ₹1,068, reverse-dcf ₹1,101 (3% gap).
        # Re-pin reverse-dcf's surfaced `current_price` to the same canonical
        # cascade and stamp `price_snapshot_at` so the UI can render
        # "captured Nh ago" prominently. Implied-growth math uses whatever
        # price was passed into the solver — we don't recompute it here
        # (that would require re-solving and changing user-visible numbers
        # mid-render); instead, we surface the snapshot timestamp so a stale
        # implied growth is honestly labelled.
        try:
            from datetime import datetime, timezone
            from backend.services.market_data_service import get_canonical_price
            _solver_px = result.get("current_price")
            _canonical_px = get_canonical_price(ticker, yf_fallback=_solver_px)
            if _canonical_px is not None and _canonical_px > 0:
                # Surface the canonical price for display, alongside the
                # solver's price (kept under `solver_price` for transparency).
                result["solver_price"] = _solver_px
                result["current_price"] = float(_canonical_px)
                result["price_source"] = "canonical_cascade"
            else:
                result["price_source"] = "solver_input"
            result["price_snapshot_at"] = datetime.now(timezone.utc).isoformat()
        except Exception as _exc:
            # Snapshot timestamp is additive — never fail the endpoint over it.
            import logging as _ll
            _ll.getLogger("yieldiq.reverse_dcf").warning(
                "reverse_dcf: price_snapshot_at stamping failed for %s: %s",
                ticker, _exc,
            )

        cache.set(_cache_key, result, ttl=3600, version_keyed=True)
        return result
    except TickerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.reverse_dcf").error(f"Reverse DCF failed for {ticker}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Reverse DCF computation failed")


@router.get("/analysis/{ticker}/report")
async def get_report(ticker: str, user: dict = Depends(get_current_user)):
    """Generate downloadable DCF report as text."""
    ticker = ticker.upper().strip()
    try:
        # PERF: blocking sync call → thread pool. See PR #83 note.
        import asyncio as _asyncio
        analysis = await _asyncio.to_thread(service.get_full_analysis, ticker)
        v = analysis.valuation
        q = analysis.quality
        s = analysis.scenarios

        lines = [
            "",
            "\u250c" + "\u2500" * 70 + "\u2510",
            "\u2502" + " Y I E L D I Q".center(70) + "\u2502",
            "\u2502" + " Quantitative Valuation Report".center(70) + "\u2502",
            "\u2502" + "".center(70) + "\u2502",
            "\u251c" + "\u2500" * 70 + "\u2524",
            "\u2502" + f"  Company: {analysis.company.company_name}".ljust(70) + "\u2502",
            "\u2502" + f"  Ticker:  {analysis.ticker}".ljust(70) + "\u2502",
            "\u251c" + "\u2500" * 70 + "\u2524",
            "\u2502" + "  VALUATION".ljust(70) + "\u2502",
            "\u2502" + f"  Fair Value:        \u20b9{v.fair_value:>12,.2f}".ljust(70) + "\u2502",
            "\u2502" + f"  Current Price:     \u20b9{v.current_price:>12,.2f}".ljust(70) + "\u2502",
            "\u2502" + f"  Margin of Safety:  {v.margin_of_safety:>+12.1f}%".ljust(70) + "\u2502",
            "\u2502" + f"  Verdict:           {v.verdict:>12s}".ljust(70) + "\u2502",
            "\u2502" + f"  WACC:              {v.wacc:>12.1f}%".ljust(70) + "\u2502",
            "\u2502" + f"  Confidence:        {v.confidence_score:>12d}/100".ljust(70) + "\u2502",
            "\u251c" + "\u2500" * 70 + "\u2524",
            "\u2502" + "  QUALITY".ljust(70) + "\u2502",
            "\u2502" + f"  YieldIQ Score:     {q.yieldiq_score:>12d}/100".ljust(70) + "\u2502",
            "\u2502" + f"  Piotroski:         {q.piotroski_score:>12d}/9".ljust(70) + "\u2502",
            "\u2502" + f"  Moat:              {q.moat:>12s}".ljust(70) + "\u2502",
            "\u251c" + "\u2500" * 70 + "\u2524",
            "\u2502" + "  SCENARIOS".ljust(70) + "\u2502",
            "\u2502" + f"  Bear Case:         \u20b9{s.bear.iv:>12,.2f}  (MoS {s.bear.mos_pct:+.1f}%)".ljust(70) + "\u2502",
            "\u2502" + f"  Base Case:         \u20b9{s.base.iv:>12,.2f}  (MoS {s.base.mos_pct:+.1f}%)".ljust(70) + "\u2502",
            "\u2502" + f"  Bull Case:         \u20b9{s.bull.iv:>12,.2f}  (MoS {s.bull.mos_pct:+.1f}%)".ljust(70) + "\u2502",
            "\u251c" + "\u2500" * 70 + "\u2524",
            "\u2502" + "  DISCLAIMER".ljust(70) + "\u2502",
            "\u2502" + "  Model output only. Not investment advice.".ljust(70) + "\u2502",
            "\u2502" + "  YieldIQ is not registered with SEBI.".ljust(70) + "\u2502",
            "\u2514" + "\u2500" * 70 + "\u2518",
            "",
            "  Generated by YieldIQ | yieldiq.in",
            "",
        ]
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content="\n".join(lines),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=YieldIQ_{ticker}.txt"},
        )
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.analysis").error(
            f"Report generation failed for {ticker}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Report generation failed: {type(e).__name__}")


# ── Excel export (Pro-tier) ──────────────────────────────────────
# Multi-sheet workbook: Inputs (editable WACC/g/years), DCF (formula-
# driven), Scenarios (Bear/Base/Bull snapshot), Source Data (raw
# inputs). Free-tier users get a 402 Payment Required so the frontend
# can render an upgrade CTA without leaking the workbook bytes.
@router.get("/analysis/{ticker}/export.xlsx")
async def export_analysis_xlsx(
    ticker: str,
    user: dict = Depends(get_current_user),
    _verified: dict = Depends(require_email_verified),
):
    """Download a formula-driven DCF workbook for ``ticker``.

    Pro-tier (or analyst / starter) only. Free-tier users receive
    HTTP 402 Payment Required with a JSON detail payload pointing at
    the upgrade page — frontend uses this to swap the button for an
    "Upgrade to Pro" CTA.

    Reuses the cached AnalysisResponse so the generated workbook
    matches what the user sees on the /analysis page.
    """
    tier = (user.get("tier") or "free").lower()
    # Superusers (effective tier set by check_analysis_limit) and any
    # paid tier may export. The analyst > pro > starter > free order
    # mirrors require_tier in middleware/auth.py.
    if tier not in ("pro", "starter", "analyst") and not user.get("is_superuser"):
        raise HTTPException(
            status_code=402,
            detail={
                "error": "upgrade_required",
                "message": (
                    "Excel export is a Pro-tier feature. Upgrade to "
                    "download a formula-driven DCF workbook."
                ),
                "upgrade_url": "/pricing",
            },
        )

    ticker = ticker.upper().strip()
    ticker = TICKER_ALIASES.get(ticker, ticker)

    # Reuse the analysis cache: tier-1 in-memory raw → tier-2 DB cache
    # → compute. Mirrors the pattern in /analysis/{ticker} above so a
    # warm-cache export costs ~10ms instead of a full recompute.
    analysis_obj = None
    try:
        _raw = cache.get(f"analysis:{ticker}:raw")
        if _raw:
            analysis_obj = _raw
        else:
            try:
                _db_cached = analysis_cache_service.get_cached(ticker)
            except Exception:
                _db_cached = None
            if _db_cached:
                analysis_obj = _db_cached
    except Exception:
        analysis_obj = None

    if analysis_obj is None:
        # Fall back to a fresh compute. Pushed onto the thread pool
        # because get_full_analysis is sync + does blocking I/O.
        import asyncio as _asyncio
        try:
            analysis_obj = await _asyncio.to_thread(
                service.get_full_analysis, ticker,
            )
        except TickerNotFoundError:
            raise HTTPException(
                status_code=404,
                detail={"error": "Ticker not found", "ticker": ticker},
            )
        except Exception as exc:
            import logging
            logging.getLogger("yieldiq.analysis").error(
                "xlsx export compute failed for %s: %s", ticker, exc,
                exc_info=True,
            )
            raise HTTPException(
                status_code=500, detail="Excel export unavailable",
            )

    try:
        from backend.services.excel_export_service import build_workbook
        # build_workbook is CPU-bound (openpyxl serialisation) — push
        # onto the threadpool so the event loop stays responsive when
        # multiple Pro users export concurrently.
        import asyncio as _asyncio
        xlsx_bytes = await _asyncio.to_thread(build_workbook, analysis_obj)
    except Exception as exc:
        import logging
        logging.getLogger("yieldiq.analysis").error(
            "xlsx export build failed for %s: %s", ticker, exc, exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Excel workbook generation failed",
        )

    safe_name = ticker.replace(".", "_")
    filename = f"YieldIQ_{safe_name}_DCF.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=300",
        },
    )


# ── Sensitivity recompute (interactive sliders) ──────────────────
# Powers SensitivityPanel on the analysis page. Paid tiers only —
# free users see the upgrade CTA in the frontend and never call
# this endpoint. Inputs are tight-bounded (matches frontend slider
# ranges) so a high-growth + low-WACC pathological combo can't
# blow up DCFEngine.
from pydantic import BaseModel, Field


class RecomputeRequest(BaseModel):
    wacc: float = Field(..., ge=0.05, le=0.20, description="Discount rate (5%-20%)")
    growth_5y_pct: float = Field(..., ge=-0.05, le=0.30, description="5y FCF growth (-5% .. 30%)")
    margin_pct: float = Field(..., ge=0.0, le=0.60, description="Operating margin (0% .. 60%)")
    terminal_growth: float = Field(default=0.03, ge=0.0, le=0.05)


@router.post("/analysis/{ticker}/recompute")
async def recompute_sensitivity(
    ticker: str,
    body: RecomputeRequest,
    user: dict = Depends(get_current_user),
):
    """Recompute the DCF with user-supplied WACC / growth / margin
    overrides. Tier-gated to paid plans (pro / analyst); free tier
    receives 403 so the frontend can render the upgrade CTA."""
    tier = (user.get("tier") or "free").lower()
    if tier not in ("pro", "starter", "analyst"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "tier_required",
                "required_tier": "pro",
                "message": "Interactive DCF sliders are a paid feature.",
                "upgrade_link": "/pricing",
            },
        )

    ticker = ticker.upper().strip()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"
    ticker = TICKER_ALIASES.get(ticker, ticker)

    # Cache key includes all overrides so identical slider positions
    # short-circuit; 5-minute TTL is plenty since the underlying
    # enriched data is stable on that horizon.
    _key = (
        f"recompute:{ticker}:{body.wacc:.4f}:{body.growth_5y_pct:.4f}:"
        f"{body.margin_pct:.4f}:{body.terminal_growth:.4f}"
    )
    cached = cache.get(_key)
    if cached:
        return cached

    try:
        from backend.services.analysis.recompute import recompute_dcf
        import asyncio as _asyncio
        result = await _asyncio.to_thread(
            recompute_dcf,
            ticker=ticker,
            wacc=body.wacc,
            growth_5y_pct=body.growth_5y_pct,
            margin_pct=body.margin_pct,
            terminal_growth=body.terminal_growth,
        )
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        cache.set(_key, result, ttl=300)
        return result
    except TickerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.recompute").error(
            f"Recompute failed for {ticker}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="DCF recompute failed")


# ── Reverse-DCF Playground (Week-2 manifesto: killer interactive) ──
# Five-slider DCF: WACC / Terminal Growth / Revenue CAGR (yrs 1-5) /
# Operating Margin / Tax Rate. Free tier unlocks only WACC; paid tier
# unlocks all five. The frontend renders a soft paywall (blur + CTA)
# on the locked sliders rather than blocking the whole page, so the
# 403 here only fires when a paid override is actually attempted —
# the base case (WACC-only, others at base) is reachable by anon /
# free callers via the same endpoint with default values for the
# locked inputs.
class DCFRecomputeRequest(BaseModel):
    wacc: float = Field(..., ge=0.06, le=0.15, description="Discount rate (6%-15%)")
    terminal_growth: float = Field(..., ge=0.0, le=0.07, description="Perpetuity growth (0%-7%)")
    revenue_cagr_yr1_5: float = Field(..., ge=-0.05, le=0.30, description="Revenue/FCF CAGR years 1-5 (-5% .. 30%)")
    operating_margin: float = Field(..., ge=0.0, le=0.50, description="Operating margin (0%-50%)")
    tax_rate: float = Field(default=0.25, ge=0.0, le=0.50, description="Tax rate (0%-50%)")


class DCFReverseEngineerRequest(BaseModel):
    market_price: float = Field(..., gt=0.0, description="Current market price to reverse-engineer")
    wacc: float = Field(..., ge=0.06, le=0.15)
    terminal_growth: float = Field(..., ge=0.0, le=0.07)
    revenue_cagr_yr1_5: float = Field(..., ge=-0.05, le=0.30)
    operating_margin: float = Field(..., ge=0.0, le=0.50)
    tax_rate: float = Field(default=0.25, ge=0.0, le=0.50)


def _is_paid_tier(user: dict | None) -> bool:
    if not user:
        return False
    tier = (user.get("tier") or "free").lower()
    return tier in ("pro", "starter", "analyst")


@router.post("/analysis/{ticker}/dcf-recompute")
async def dcf_playground_recompute(
    ticker: str,
    body: DCFRecomputeRequest,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    """Reverse-DCF playground recompute. Five-input live DCF with
    bear / base / bull fan-out band.

    Tier policy: free tier is allowed to call with all 5 inputs (the
    UI gates the locked sliders client-side and the soft paywall is
    a UX nudge, not a security boundary). If we ever need to enforce
    paid-only inputs server-side we can compare the body to the cached
    base inputs and 403 on a delta in a locked field — for now we
    keep the endpoint open so the manifesto's "free tier wide" rule
    (rule 7) is honoured at the API layer too.
    """
    ticker = ticker.upper().strip()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"
    ticker = TICKER_ALIASES.get(ticker, ticker)

    # Cache key includes every slider so identical positions reuse
    # the prior compute. 5-minute TTL — short enough to stay close to
    # the canonical pipeline, long enough to amortise debounced
    # slider drags by the same user in one session.
    _key = (
        f"dcf_playground:{ticker}:"
        f"{body.wacc:.4f}:{body.terminal_growth:.4f}:"
        f"{body.revenue_cagr_yr1_5:.4f}:{body.operating_margin:.4f}:"
        f"{body.tax_rate:.4f}"
    )
    cached = cache.get(_key)
    if cached:
        return cached

    try:
        from backend.services.analysis.dcf_playground import run_playground_with_band
        import asyncio as _asyncio
        from datetime import datetime, timezone
        result = await _asyncio.to_thread(
            run_playground_with_band,
            ticker=ticker,
            wacc=body.wacc,
            terminal_growth=body.terminal_growth,
            revenue_cagr_yr1_5=body.revenue_cagr_yr1_5,
            operating_margin=body.operating_margin,
            tax_rate=body.tax_rate,
        )
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])

        # Surface a `base_fv` field (the canonical cached FV) so the
        # frontend can show a "your slider position vs analyst base"
        # delta. Best-effort lookup from analysis_cache; the playground
        # FV still ships even if this fails.
        base_fv = None
        try:
            cached_analysis = analysis_cache_service.get_cached(ticker, fields_needed=["fair_value"])
            if isinstance(cached_analysis, dict):
                val = cached_analysis.get("valuation")
                if isinstance(val, dict):
                    base_fv = val.get("fair_value")
        except Exception:
            base_fv = None
        result["base_fv"] = float(base_fv) if base_fv else None
        result["as_of"] = datetime.now(timezone.utc).isoformat()
        result["ticker"] = ticker

        cache.set(_key, result, ttl=300)
        return result
    except TickerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.dcf_playground").error(
            f"DCF playground failed for {ticker}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="DCF playground compute failed")


@router.post("/analysis/{ticker}/dcf-reverse-engineer")
async def dcf_reverse_engineer(
    ticker: str,
    body: DCFReverseEngineerRequest,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    """Solve for the implied WACC / TG / Revenue CAGR (independently)
    that justify the supplied market_price, holding the other inputs
    at the supplied base. Capped at 50 bisection iterations per axis."""
    ticker = ticker.upper().strip()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"
    ticker = TICKER_ALIASES.get(ticker, ticker)

    _key = (
        f"dcf_reverse:{ticker}:{body.market_price:.2f}:"
        f"{body.wacc:.4f}:{body.terminal_growth:.4f}:"
        f"{body.revenue_cagr_yr1_5:.4f}:{body.operating_margin:.4f}:"
        f"{body.tax_rate:.4f}"
    )
    cached = cache.get(_key)
    if cached:
        return cached

    try:
        from backend.services.analysis.dcf_playground import reverse_engineer_inputs
        import asyncio as _asyncio
        from datetime import datetime, timezone
        result = await _asyncio.to_thread(
            reverse_engineer_inputs,
            ticker=ticker,
            market_price=body.market_price,
            base_wacc=body.wacc,
            base_terminal_growth=body.terminal_growth,
            base_revenue_cagr=body.revenue_cagr_yr1_5,
            base_operating_margin=body.operating_margin,
            base_tax_rate=body.tax_rate,
        )
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        result["as_of"] = datetime.now(timezone.utc).isoformat()
        result["ticker"] = ticker
        cache.set(_key, result, ttl=300)
        return result
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.dcf_playground").error(
            f"Reverse-engineer failed for {ticker}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Reverse-engineer compute failed")


# ── Sensitivity tornado ─────────────────────────────────────────
# Per-stock ranking of which model input moves FV the most. Re-runs
# the DCF 7-10× with each input perturbed ±X (200bps for rates,
# ±20% for relative inputs). Cached 24h per ticker — sensitivity is
# expensive but stable on a daily horizon (the underlying enriched
# data updates nightly via the data pipeline). Open to all auth'd
# users (no tier gate) since the value here is educational: it
# teaches users which assumption is worth the most scrutiny.
@router.get("/analysis/{ticker}/sensitivity")
async def analysis_sensitivity(
    ticker: str,
    user: dict = Depends(get_current_user_optional),
):
    """Return tornado-chart data: per-input FV sensitivity, sorted
    most-impactful first. See backend/services/analysis/sensitivity.py
    for the perturbation grid (DCF stocks vs financials)."""
    ticker = ticker.upper().strip()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"
    ticker = TICKER_ALIASES.get(ticker, ticker)

    cache_key = f"sensitivity:{ticker}:v1"
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Pull the canonical analysis once so we can seed the perturbation
    # grid from the model's actual WACC / growth / margin instead of
    # generic defaults — sensitivity around the wrong base value would
    # mis-rank inputs (e.g. a stock priced at 6% WACC ranks WACC much
    # higher than one priced at 14%).
    base_wacc: Optional[float] = None
    base_growth: Optional[float] = None
    base_margin: Optional[float] = None
    try:
        import asyncio as _asyncio_seed
        analysis = await _asyncio_seed.to_thread(service.get_full_analysis, ticker)
        # AnalysisResponse is a pydantic model; valuation is a sub-model
        v = getattr(analysis, "valuation", None)
        if v is not None:
            wacc_val = getattr(v, "wacc", 0) or 0
            if wacc_val:
                base_wacc = float(wacc_val) / 100.0
            g_val = getattr(v, "fcf_growth_rate", 0) or 0
            if g_val:
                base_growth = float(g_val) / 100.0
        # Operating margin isn't on AnalysisResponse yet; sensitivity
        # service falls back to 0.15 which matches SensitivityPanel's
        # default seed — keeps the two features in sync.
    except Exception:
        # Non-fatal — sensitivity will use built-in defaults.
        pass

    try:
        from backend.services.analysis.sensitivity import compute_sensitivity
        import asyncio as _asyncio
        result = await _asyncio.to_thread(
            compute_sensitivity,
            ticker=ticker,
            base_wacc=base_wacc,
            base_growth=base_growth,
            base_margin=base_margin,
        )
        if result.get("error"):
            # Surface as 200 with empty list + error key so the frontend
            # can show "sensitivity unavailable" without an error toast.
            return result
        # 24h cache — sensitivity ranking is stable day-to-day; only the
        # nightly data pipeline can shift the underlying inputs.
        cache.set(cache_key, result, ttl=86400)
        return result
    except TickerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.sensitivity").error(
            f"Sensitivity failed for {ticker}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Sensitivity computation failed")


# ── Coverage Tier (feat/coverage-tier-system) ───────────────────
# Public endpoint exposing the A/B/C tier rubric for a ticker. Used by
# the methodology page + the CoverageTierBadge tooltip. Labeling-only:
# returning C does NOT change anything about the underlying analysis.
@router.get("/coverage/{ticker}")
async def get_coverage_tier(ticker: str, refresh: int = 0):
    """Return the full coverage-tier breakdown for a ticker.

    Response shape::

        {
            "ticker": "RELIANCE.NS",
            "tier": "A" | "B" | "C",
            "criteria_met": "5/7",
            "criteria_passed": 5,
            "criteria_total": 7,
            "reasons": [...],
            "rubric": [
                {key, label, value, threshold, passed}, ...
            ]
        }

    Pass ``?refresh=1`` to bypass the 6h cache (used by the admin
    methodology explorer when verifying recent data-pipeline updates).
    """
    ticker = ticker.upper().strip()
    try:
        from backend.services import coverage_tier_service as _cts
        result = _cts.compute_coverage_tier(ticker, refresh=bool(refresh))
        result["ticker"] = ticker
        return result
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.coverage_tier").error(
            f"Coverage tier failed for {ticker}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Coverage tier computation failed")


# ─────────────────────────────────────────────────────────────────
# Time Slider — historical "as-of" analysis snapshot
# ─────────────────────────────────────────────────────────────────
#
# `GET /api/v1/analysis/{ticker}/as-of?date=YYYY-MM-DD`
#
# Reconstructs what YieldIQ thought about a ticker on a past date
# by joining three sources:
#
#   1. `fair_value_history`  → the stored FV / MoS / verdict for
#      the most recent row dated <= requested date.
#   2. `daily_prices`        → the close price at the requested
#      date (most-recent row dated <= requested date).
#   3. `cache_invalidation_manifest.MANIFEST` → the "version of
#      YieldIQ" in effect at the requested date — i.e. the
#      newest manifest entry with `applied_at` <= requested date.
#
# When the requested date predates the earliest FV-history row for
# this ticker, the endpoint returns `data_available=false` and a
# plain-English `limitations` string the frontend can render in a
# muted state. This is the dominant case at launch (fair_value_
# history began populating Feb 2026), but the feature gets more
# powerful with every passing day as history accumulates.
#
# Manifest entry: see `cache_invalidation_manifest.py` —
#   scope = ["time_slider", "as_of_analysis"]
#
# Tier note: tier-gating is enforced on the FRONTEND (free users
# can only slide back 1y; paid users get the full available
# range). The backend serves the requested date if data exists —
# we never want to render a 403 in the middle of a drag gesture.
# ─────────────────────────────────────────────────────────────────


@router.get("/analysis/{ticker}/as-of")
async def get_analysis_as_of(
    ticker: str,
    date: str = Query(..., description="YYYY-MM-DD"),
    user: Optional[dict] = Depends(get_current_user_optional),
):
    """Reconstruct the YieldIQ analysis as it stood on a past date.

    Returns a minimal payload — FV, price, MoS, verdict, model
    version, plus a `data_available` flag and optional
    `limitations` string when the requested date predates our
    fair-value coverage for this ticker.
    """
    from datetime import date as _date_cls, datetime as _dt

    ticker_norm = (ticker or "").upper().strip()
    if not ticker_norm:
        raise HTTPException(status_code=400, detail="Ticker required")

    # Parse the requested date strictly. The slider always emits
    # ISO-8601 YYYY-MM-DD, so anything else is a client bug worth
    # surfacing as a 400.
    try:
        requested = _date_cls.fromisoformat(date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="date must be in YYYY-MM-DD format",
        )

    today = _date_cls.today()
    if requested > today:
        raise HTTPException(status_code=400, detail="date cannot be in the future")

    # Two-tier cache: as-of payloads are immutable for any (ticker,
    # date) pair where date < today, so we can cache aggressively.
    # For date == today we still cache for 5 minutes so a slider
    # bounce doesn't hammer the DB.
    _cache_key = f"as-of:{ticker_norm}:{requested.isoformat()}"
    _mem_hit = cache.get(_cache_key)
    if _mem_hit is not None:
        return _mem_hit

    # Resolve the "model version in effect" on the requested date
    # from the manifest. Always available — the manifest is in-
    # process code, never a DB call.
    try:
        from backend.services.cache_invalidation_manifest import MANIFEST
        applied_before: list[dict] = []
        requested_dt = _dt.combine(requested, _dt.max.time())
        for entry in MANIFEST:
            ts = entry.get("applied_at")
            if ts is None:
                continue
            # Compare in naive UTC; manifest entries are tz-aware,
            # so strip tzinfo for the comparison after normalising.
            try:
                ts_naive = ts.replace(tzinfo=None) if getattr(ts, "tzinfo", None) else ts
            except Exception:
                continue
            if ts_naive <= requested_dt:
                applied_before.append(entry)
        applied_before.sort(
            key=lambda e: e.get("applied_at") or _dt.min,
            reverse=True,
        )
        model_version = (
            applied_before[0].get("version_id") if applied_before else None
        )
    except Exception:
        model_version = None

    # Open a pipeline session for the historical FV + price lookup.
    try:
        from data_pipeline.db import Session as PipelineSession
    except Exception:
        PipelineSession = None
    if PipelineSession is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    db = PipelineSession()
    try:
        from data_pipeline.models import FairValueHistory, DailyPrice

        # Earliest row gives us the "coverage start" we report when
        # the requested date is too far back.
        earliest = (
            db.query(FairValueHistory)
            .filter(FairValueHistory.ticker == ticker_norm)
            .order_by(FairValueHistory.date.asc())
            .first()
        )
        if earliest is None:
            _empty = {
                "ticker": ticker_norm,
                "as_of_date": requested.isoformat(),
                "fair_value": None,
                "current_price": None,
                "mos_pct": None,
                "verdict": None,
                "model_version": model_version,
                "data_available": False,
                "limitations": (
                    "We have not yet tracked a fair value for this ticker. "
                    "Time-machine history will appear here after the first analysis."
                ),
            }
            cache.set(_cache_key, _empty, ttl=300)
            return _empty

        if requested < earliest.date:
            _early = {
                "ticker": ticker_norm,
                "as_of_date": requested.isoformat(),
                "fair_value": None,
                "current_price": None,
                "mos_pct": None,
                "verdict": None,
                "model_version": model_version,
                "data_available": False,
                "limitations": (
                    f"We started tracking fair value for this ticker on "
                    f"{earliest.date.isoformat()}."
                ),
            }
            cache.set(_cache_key, _early, ttl=86400)
            return _early

        # Most-recent FV row dated <= requested.
        fv_row = (
            db.query(FairValueHistory)
            .filter(
                FairValueHistory.ticker == ticker_norm,
                FairValueHistory.date <= requested,
            )
            .order_by(FairValueHistory.date.desc())
            .first()
        )

        # Most-recent close on or before the requested date.
        price_row = (
            db.query(DailyPrice)
            .filter(
                DailyPrice.ticker == ticker_norm,
                DailyPrice.trade_date <= requested,
            )
            .order_by(DailyPrice.trade_date.desc())
            .first()
        )

        # Prefer the live close from daily_prices; fall back to the
        # price embedded in the FV row (which is what the engine saw
        # on the day the FV was computed).
        historical_price: Optional[float] = None
        if price_row is not None and price_row.close_price is not None:
            historical_price = float(price_row.close_price)
        elif fv_row is not None and fv_row.price is not None:
            historical_price = float(fv_row.price)

        fv_value: Optional[float] = (
            float(fv_row.fair_value)
            if (fv_row is not None and fv_row.fair_value is not None)
            else None
        )

        # Recompute MoS from the joined inputs so the displayed
        # number is always consistent with the (FV, price) pair on
        # screen. MoS = (FV - Price) / Price × 100 (matches the
        # convention used by `store_today_fair_value`).
        mos_pct: Optional[float] = None
        if fv_value is not None and historical_price and historical_price > 0:
            mos_pct = round((fv_value - historical_price) / historical_price * 100.0, 2)
        elif fv_row is not None and fv_row.mos_pct is not None:
            mos_pct = float(fv_row.mos_pct)

        # Derive the verdict bucket from MoS so the on-page label
        # always matches the chip the live analysis would render
        # for the same (FV, price). Mirrors the band thresholds in
        # frontend lib/utils.ts verdictFromMos.
        def _verdict_from_mos(m: Optional[float]) -> str:
            if m is None:
                return "under_review"
            if m >= 20:
                return "undervalued"
            if m >= -10:
                return "fairly_valued"
            return "overvalued"

        verdict = _verdict_from_mos(mos_pct)

        payload = {
            "ticker": ticker_norm,
            "as_of_date": requested.isoformat(),
            "fv_as_of_date": fv_row.date.isoformat() if fv_row else None,
            "price_as_of_date": (
                price_row.trade_date.isoformat() if price_row else None
            ),
            "fair_value": fv_value,
            "current_price": historical_price,
            "mos_pct": mos_pct,
            "verdict": verdict,
            "model_version": model_version,
            "data_available": fv_value is not None and historical_price is not None,
            "limitations": None,
        }

        # Cache: immutable past = long TTL; today = short TTL so a
        # mid-day recompute lands quickly.
        ttl = 300 if requested == today else 86400
        cache.set(_cache_key, payload, ttl=ttl)
        return payload
    finally:
        db.close()
