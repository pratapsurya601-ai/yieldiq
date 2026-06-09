# backend/services/insurance_appraisal_service.py
# ═══════════════════════════════════════════════════════════════
# Appraisal-Value engine for Indian life insurers.
#
# Activated PR: feat/insurance-ev-admin-ui — ships the operator data-
# entry workflow and the engine plumbing. The engine only fires when
# the operator has loaded at least one row into ``insurance_appraisal_
# inputs`` (see migration 046). Until that happens the routing branch
# in ``backend/services/analysis/service.py`` falls through to the
# current P/BV path — so production output is byte-identical and no
# CACHE_VERSION bump is required at engine-land time.
#
# Why this exists:
#   docs/design/insurance-dcf-fix.md §3 (Approach A) — life insurers
#   are mis-valued by the P/BV cohort path because statutory book is
#   ~15–25% of Embedded Value. The industry-standard frame is
#
#       Appraisal Value  = EV + N × VNB
#       FV per share     = Appraisal Value / diluted shares
#
#   with the VNB multiplier N derived from Gordon-style logic on
#   sustainable VNB growth:
#
#       N = (1 + g) / (RDR − g)        clamped to [8, 25]
#
#   RDR (Risk Discount Rate) is disclosed in each insurer's EV report;
#   typical Indian range 8.5–11%. We use a per-ticker default that the
#   operator can override via the admin form when entering a row.
#
# Caller contract:
#   compute_appraisal_fair_value(
#       ticker, ev_per_share, vnb_per_share, growth,
#       rdr=None, shares=None
#   ) -> dict | None
#
#   Returns the same shape as compute_regulated_utility_fair_value /
#   compute_financial_fair_value so the wiring in analysis/service.py
#   can splice it into the existing `iv` / `bear_iv` / `bull_iv` /
#   `_val_method` / `_meta` plumbing without reshaping the surrounding
#   code.
#
# Routing helper:
#   load_latest_appraisal_inputs(ticker) -> dict | None
#   get_appraisal_fair_value_for_ticker(ticker, shares) -> dict | None
#
#   These read the most recent row from ``insurance_appraisal_inputs``
#   for the given ticker and assemble a FairValueResult-style dict.
#   Return None when no row exists; the caller falls through to the
#   existing P/BV path.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("yieldiq.insurance_appraisal")


# ── Insurer-type ticker classification (T3.3) ──────────────────
# Single source of truth for which Indian listed insurers are
# eligible for the EV + VNB appraisal framework. Mirrors the
# tickers already routed through ``_INSURANCE_TICKERS`` in
# backend/services/analysis/constants.py, narrowed to the LIFE
# subset (the only subset where annual EV + VNB disclosure makes
# the appraisal math applicable).
#
# General + health insurers (ICICI Lombard, Star Health, Niva
# Bupa, GIC Re, etc.) do NOT report EV / VNB. Their published
# valuation primitives are float-investment income, combined
# ratio (CoR = loss ratio + expense ratio) and underwriting
# margin — these belong in a separate float-PE / DDM cohort.
#
# Sources for the multiplier band:
#   - HDFC Life FY24 / FY25 investor decks (consensus VNB-mult ~22x)
#   - ICICI Pru Life FY24 disclosures (~20x consensus)
#   - SBI Life FY24 (~24x — distribution moat premium)
#   - LICI FY24 (lower ~12x — sovereign mix + lower growth)
#   - Damodaran "Valuation of Financial Service Firms" (2014):
#     life-insurance appraisal-value multiple of new-business
#     creation should sit in 15-30x absent franchise distortions.
LIFE_INSURERS: frozenset[str] = frozenset({
    "HDFCLIFE", "ICICIPRULI", "SBILIFE", "MAXFIN", "LICI",
})
GENERAL_HEALTH_INSURERS: frozenset[str] = frozenset({
    "ICICIGI", "STARHEALTH", "NIVABUPA",
    # Re-insurers + PSU general — float-income framework, not EV/VNB.
    "GICRE", "NIACL", "GODIGIT",
})


# Default multipliers per life insurer — calibrated to the published
# multiplier each insurer trades at in the sell-side consensus VNB-
# valuation tables. Mid-point of the 15-30x Damodaran band.
_LIFE_INSURER_VNB_MULT_DEFAULTS: dict[str, float] = {
    "HDFCLIFE":   22.0,
    "ICICIPRULI": 20.0,
    "SBILIFE":    24.0,
    "MAXFIN":     18.0,
    "LICI":       12.0,
}

# Mid-point default when ticker is unknown but is_ev_vnb_applicable
# was overridden by the caller (rare — typically the caller will
# gate on the LIFE_INSURERS frozenset first).
_DEFAULT_VNB_MULT = 20.0
_VNB_MULT_FLOOR = 15.0
_VNB_MULT_CEILING = 30.0


# ── N multiplier clamp ──────────────────────────────────────────
# Per design doc §3 Approach A: floor 8, ceiling 25. Below 8 the model
# is implying VNB has no franchise value (LICI floor case); above 25
# the model is extrapolating high-growth indefinitely (sell-side
# generally caps at 25× for HDFCLIFE / SBILIFE / ICICIPRULI).
_N_FLOOR = 8.0
_N_CEILING = 25.0


# ── Default Risk Discount Rates (RDR) per ticker ────────────────
# Disclosed in each insurer's annual Indian Embedded Value Report
# footnotes. Operator can override per-entry via the admin form (the
# stored value, when present, takes precedence over this default).
_DEFAULT_RDR_BY_TICKER: dict[str, float] = {
    "HDFCLIFE":   0.0950,   # 9.50% — FY24 EV report
    "SBILIFE":    0.0950,
    "ICICIPRULI": 0.0950,
    "LICI":       0.0900,   # 9.00% — lower for sovereign-backed peers
}
_DEFAULT_RDR = 0.0950


# ── Growth clamps (sustainable VNB growth assumption) ───────────
# Cap at sector-implied ceiling (post-COVID base effects distort
# trailing-3Y CAGR upward) and floor at 4% (long-run nominal premium-
# penetration growth in India). See design doc §9.
_G_FLOOR = 0.04
_G_CEILING = 0.18


def _clean_ticker(t: Optional[str]) -> str:
    return (t or "").replace(".NS", "").replace(".BO", "").upper()


def _verdict_from_mos(mos_pct: float) -> str:
    if mos_pct >= 20.0:
        return "undervalued"
    if mos_pct >= -10.0:
        return "fairly_valued"
    return "overvalued"


def _derive_n_multiplier(growth: float, rdr: float) -> tuple[float, float, float]:
    """Compute the VNB multiplier N from Gordon-style growth/RDR inputs.

    Returns ``(n, g_used, rdr_used)`` — the clamped inputs are returned
    alongside so the caller can populate the ``_meta`` block with the
    actual values used (vs whatever the operator entered).
    """
    g = max(_G_FLOOR, min(_G_CEILING, float(growth)))
    r = float(rdr) if rdr and rdr > 0 else _DEFAULT_RDR
    # Defensive: if RDR ≤ g the Gordon formula blows up. Clamp r so
    # spread is at least 100 bps — corresponds to N ceiling case.
    if r - g < 0.01:
        r = g + 0.01
    n_raw = (1.0 + g) / (r - g)
    n = max(_N_FLOOR, min(_N_CEILING, n_raw))
    return n, g, r


def compute_appraisal_fair_value(
    ticker: str,
    ev_per_share: float,
    vnb_per_share: Optional[float],
    growth: float,
    rdr: Optional[float] = None,
    shares: Optional[float] = None,  # accepted for future per-share
                                     # rederivation; unused today.
) -> Optional[dict]:
    """Appraisal Value formula `FV = EV + N × VNB`, per share.

    Inputs are *per share* (the caller converts INR-Cr aggregates via
    ``shares_diluted``). Returns the standard FairValueResult dict, or
    None when EV_per_share is non-positive.
    """
    if ev_per_share is None or ev_per_share <= 0:
        return None
    ev_ps = float(ev_per_share)
    vnb_ps = float(vnb_per_share) if vnb_per_share and vnb_per_share > 0 else 0.0

    clean = _clean_ticker(ticker)
    rdr_used_input = rdr if rdr and rdr > 0 else _DEFAULT_RDR_BY_TICKER.get(clean, _DEFAULT_RDR)
    n, g_used, rdr_used = _derive_n_multiplier(growth, rdr_used_input)

    base = round(ev_ps + n * vnb_ps, 2)
    # Bear / bull ±20% around base — EV is already a present-value
    # model output (less noise than DCF FCF), so the band is narrower
    # than DCF's ±30% but slightly wider than regulated-utility's
    # ±25% to absorb the VNB-margin volatility quarter-to-quarter.
    bear = round(base * 0.80, 2)
    bull = round(base * 1.20, 2)

    return {
        "fair_value": base,
        "bear_case": bear,
        "base_case": base,
        "bull_case": bull,
        "method": "appraisal_value",
        "valuation_method": "appraisal_value",
        # Confidence: operator-curated inputs are higher-trust than
        # the P/BV peer-cohort fallback (which the design doc calls
        # "documented stub"). Floor at 75 to match the regulated-
        # utility engine that this mirrors.
        "confidence_score": 80,
        "_meta": {
            "ev_per_share":   round(ev_ps, 2),
            "vnb_per_share":  round(vnb_ps, 2),
            "n_multiplier":   round(n, 3),
            "growth_input":   round(float(growth), 4),
            "growth_used":    round(g_used, 4),
            "rdr_input":      round(float(rdr_used_input), 4),
            "rdr_used":       round(rdr_used, 4),
            "formula":        "FV = EV + N × VNB; N = (1+g)/(RDR-g) clamped [8,25]",
        },
    }


# ── Persistence-layer helpers ───────────────────────────────────
#
# These wrap the ``insurance_appraisal_inputs`` table (migration 046)
# and produce a ready-to-use dict for the analysis pipeline. Kept
# separate from the pure math above so the math is trivially testable
# without a database.


def load_latest_appraisal_inputs(ticker: str) -> Optional[dict]:
    """Return the most recent row from ``insurance_appraisal_inputs``
    for ``ticker`` (without .NS/.BO suffix), or None when:

      - no DB session is configured (local dev without Postgres),
      - the table does not exist (migration not applied yet),
      - no row exists for the ticker.

    The caller is expected to be tolerant of None and fall through to
    the existing P/BV path.
    """
    clean = _clean_ticker(ticker)
    if not clean:
        return None
    try:
        from data_pipeline.db import Session as _Sess
        from sqlalchemy import text as _t
    except Exception:
        return None
    if _Sess is None:
        return None
    db = _Sess()
    try:
        try:
            row = db.execute(
                _t(
                    "SELECT ticker, period_end, embedded_value_cr, "
                    "value_new_business_cr, vnb_margin_pct, "
                    "ev_growth_yoy_pct, source_url, entered_by, "
                    "entered_at, notes "
                    "FROM insurance_appraisal_inputs "
                    "WHERE ticker = :t "
                    "ORDER BY period_end DESC LIMIT 1"
                ),
                {"t": clean},
            ).fetchone()
        except Exception as exc:
            # Table missing in this environment, or transient DB error.
            # Either way: caller falls through to current P/BV path.
            logger.debug(
                "load_latest_appraisal_inputs(%s) failed: %s: %s",
                clean, type(exc).__name__, exc,
            )
            return None
        if not row:
            return None
        return {
            "ticker": row[0],
            "period_end": row[1],
            "embedded_value_cr": float(row[2]) if row[2] is not None else None,
            "value_new_business_cr": float(row[3]) if row[3] is not None else None,
            "vnb_margin_pct": float(row[4]) if row[4] is not None else None,
            "ev_growth_yoy_pct": float(row[5]) if row[5] is not None else None,
            "source_url": row[6],
            "entered_by": row[7],
            "entered_at": row[8],
            "notes": row[9],
        }
    finally:
        try:
            db.close()
        except Exception:
            pass


def get_appraisal_fair_value_for_ticker(
    ticker: str,
    shares: Optional[float],
) -> Optional[dict]:
    """Assemble a FairValueResult for ``ticker`` if appraisal inputs
    exist. Returns None when the row is absent or the inputs are
    insufficient (no EV, no shares).

    This is the function the analysis service should call from its
    routing branch.
    """
    if not shares or float(shares) <= 0:
        return None
    row = load_latest_appraisal_inputs(ticker)
    if not row:
        return None
    ev_cr = row.get("embedded_value_cr")
    if not ev_cr or ev_cr <= 0:
        return None
    vnb_cr = row.get("value_new_business_cr") or 0.0
    # 1 INR Crore = 1e7 INR. EV/VNB are in Crores; convert to absolute
    # INR before per-share division.
    ev_ps = (float(ev_cr) * 1e7) / float(shares)
    vnb_ps = (float(vnb_cr) * 1e7) / float(shares) if vnb_cr else 0.0

    # Growth: use ev_growth_yoy_pct (operator-entered) when present;
    # otherwise fall back to the floor. The Gordon clamp inside
    # compute_appraisal_fair_value will normalise either way.
    g_pct = row.get("ev_growth_yoy_pct")
    g = (float(g_pct) / 100.0) if g_pct is not None else _G_FLOOR

    out = compute_appraisal_fair_value(
        ticker=ticker,
        ev_per_share=ev_ps,
        vnb_per_share=vnb_ps,
        growth=g,
        shares=shares,
    )
    if not out:
        return None
    # Echo the data-provenance fields back so the analysis pipeline can
    # surface them in `data_issues` / model caveats.
    meta = out.setdefault("_meta", {})
    meta["period_end"] = (
        row["period_end"].isoformat()
        if hasattr(row.get("period_end"), "isoformat")
        else row.get("period_end")
    )
    meta["source_url"] = row.get("source_url")
    meta["entered_by"] = row.get("entered_by")
    meta["vnb_margin_pct"] = row.get("vnb_margin_pct")
    return out


# ═══════════════════════════════════════════════════════════════
# T3.3 — Embedded-Value + Value-of-New-Business appraisal math
#
# A pure-compute API (no DB, no I/O) that exposes the standard
# insurance valuation framework:
#
#     Appraisal Value = EV + VNB × N
#     FV per share    = Appraisal Value / shares_outstanding
#
# Two key differences from ``compute_appraisal_fair_value`` above:
#
#   1. It accepts ABSOLUTE Rs values (Crore-scale typical, but the
#      caller's units flow through unchanged). The pre-existing
#      ``compute_appraisal_fair_value`` accepts PER-SHARE inputs
#      derived from the admin-entry table at the persistence layer.
#
#   2. The N multiplier is selected from a published-multiplier
#      table (calibrated to each insurer's sell-side consensus
#      VNB-mult) rather than derived from a Gordon-style g/RDR
#      formula. Both approaches converge in the 15-25x band for
#      the Indian listed life cohort; this API exposes the
#      published-multiplier framing because that is how broker
#      research notes and investor decks state the math.
#
# Phase A delivery (T3.3): this extension is purely additive — no
# routing branch in backend/services/analysis/service.py is wired
# to call ``compute_ev_vnb_appraisal``. The existing
# ``get_appraisal_fair_value_for_ticker`` -> ``compute_appraisal_
# fair_value`` path remains the sole production caller. Phase B
# (separate PR, post canary-diff confirmation) will wire this API
# into the analysis route as an alternate framing alongside the
# operator-entry path.
# ═══════════════════════════════════════════════════════════════


@dataclass
class EVVNBInputs:
    """Aggregate-Rs (NOT per-share) appraisal-value inputs.

    All Rs amounts are in the caller's chosen unit (typically
    Indian Crores; 1 Cr = 1e7 INR). The formula is unit-agnostic
    — what comes in flows out. If shares_outstanding is also
    passed in matching units (i.e. count of shares), the per-share
    output divides cleanly.

    Attributes:
        embedded_value: Latest reported EV (most recent annual
            EV / IEV / TEV report). Aggregate Rs, not per-share.
        new_business_value: VNB for the latest reporting year
            (TTM or FY, caller's choice). Aggregate Rs.
        vnb_multiple: N — the capitalisation multiple applied to
            VNB. Default 20x = mid-point of the Damodaran [15, 30]
            band; callers should typically obtain this via
            ``select_vnb_multiple`` so the per-insurer default
            (HDFCLIFE 22x, LICI 12x, etc.) is picked up.
        new_business_growth: Optional forward growth used for
            projected-VNB sanity checks. Not used in the headline
            ``appraisal_value`` calculation — that is one-period.
        forward_years: How many years of forward VNB projection
            the caller intends to use downstream (informational
            only at this layer).
    """
    embedded_value: float
    new_business_value: float
    vnb_multiple: float = 20.0
    new_business_growth: Optional[float] = None
    forward_years: int = 5


@dataclass
class EVVNBResult:
    """Structured appraisal-value output."""
    appraisal_value: Optional[float]
    appraisal_per_share: Optional[float]
    components: dict
    method: str
    sanity_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "appraisal_value": self.appraisal_value,
            "appraisal_per_share": self.appraisal_per_share,
            "components": dict(self.components),
            "method": self.method,
            "sanity_warnings": list(self.sanity_warnings),
        }


def compute_ev_vnb_appraisal(
    inputs: EVVNBInputs,
    shares_outstanding: Optional[float] = None,
) -> EVVNBResult:
    """Insurance appraisal value via EV + (VNB × Multiple).

    Two return modes:

      * ``method = "ev_plus_vnb_capitalized"`` — the standard case:
        EV > 0, VNB > 0, multiple > 0. Returns
        ``appraisal_value = ev + vnb * multiple``.

      * ``method = "ev_only"`` — when VNB <= 0 (loss-making new
        business or zero disclosure). Returns ``appraisal_value =
        ev`` and adds a sanity warning. This is the right fallback
        when an insurer has paused growth or written off a cohort
        of new business — EV captures the run-off value.

      * ``method = "unavailable"`` — when EV is missing / <= 0.
        No appraisal is possible. ``appraisal_value`` is None.

    When ``shares_outstanding`` is supplied and positive, also
    populates ``appraisal_per_share``. Otherwise that field is
    None and the caller can read ``appraisal_value`` as an
    aggregate.

    Args:
        inputs: Aggregate-Rs EV/VNB inputs (see EVVNBInputs).
        shares_outstanding: Optional diluted-share count. When
            absent, only the aggregate value is returned.

    Returns:
        ``EVVNBResult`` with method-tagged components dict so the
        caller can render a transparency panel ("EV ₹50,000 Cr +
        VNB ₹3,500 Cr × 22 = ₹127,000 Cr appraisal value").

    Notes:
        - Negative EV is rejected (returns ``unavailable``). A real
          insurer with negative EV is technically insolvent —
          appraisal-value math is meaningless.
        - Multiplier outside [15, 30] generates a sanity warning
          but does NOT override the caller's choice. The clamp is
          documented at the broker-research level; specific
          insurer overrides (e.g. LICI 12x) intentionally sit
          below the floor and the caller (``select_vnb_multiple``)
          is the right place to make that judgement.
    """
    warnings: list[str] = []

    ev = float(inputs.embedded_value or 0)
    vnb = float(inputs.new_business_value or 0)
    mult = float(inputs.vnb_multiple or 0)

    if ev <= 0:
        return EVVNBResult(
            appraisal_value=None,
            appraisal_per_share=None,
            components={"ev": ev, "vnb_capitalized": 0.0, "vnb_multiple": mult},
            method="unavailable",
            sanity_warnings=[
                "Embedded Value missing or non-positive — appraisal value "
                "cannot be computed.",
            ],
        )

    # Multiplier band check — surface a warning but honour the caller's
    # choice. The 15-30x band is the Damodaran / sell-side consensus
    # range; LICI-like sovereign-mix names legitimately trade below 15x.
    if mult and mult < _VNB_MULT_FLOOR:
        warnings.append(
            f"VNB multiple {mult:.1f}x is below the typical [15, 30] band "
            f"— acceptable for sovereign-mix or low-growth insurers but "
            f"verify the calibration source."
        )
    elif mult > _VNB_MULT_CEILING:
        warnings.append(
            f"VNB multiple {mult:.1f}x exceeds the typical [15, 30] band "
            f"— sell-side research caps at 30x even for top-tier growth."
        )

    if vnb <= 0 or mult <= 0:
        # EV-only fallback. Most common reason: TTM VNB turned negative
        # (rare — happens during product-mix transitions) or the caller
        # did not pass a multiple.
        if vnb <= 0:
            warnings.append(
                "Value of New Business is non-positive — appraisal value "
                "defaults to Embedded Value alone (no VNB capitalisation)."
            )
        if mult <= 0 and vnb > 0:
            warnings.append(
                "VNB multiple is non-positive — appraisal value defaults "
                "to Embedded Value alone."
            )
        appraisal = ev
        components = {
            "ev": ev,
            "vnb_capitalized": 0.0,
            "vnb_multiple": mult,
            "vnb_input": vnb,
        }
        method = "ev_only"
    else:
        vnb_capitalized = vnb * mult
        appraisal = ev + vnb_capitalized
        components = {
            "ev": ev,
            "vnb_capitalized": vnb_capitalized,
            "vnb_multiple": mult,
            "vnb_input": vnb,
        }
        method = "ev_plus_vnb_capitalized"

    per_share: Optional[float] = None
    if shares_outstanding and float(shares_outstanding) > 0:
        per_share = appraisal / float(shares_outstanding)

    # Forward-projection sanity check — purely informational.
    if inputs.new_business_growth is not None and inputs.forward_years > 0:
        g = float(inputs.new_business_growth)
        components["forward_growth"] = g
        components["forward_years"] = int(inputs.forward_years)
        if g > 0.30:
            warnings.append(
                f"New business growth {g * 100:.1f}% is unusually high — "
                f"sustained >25% VNB growth is rare even for India life."
            )
        elif g < -0.10:
            warnings.append(
                f"New business growth {g * 100:.1f}% is sharply negative — "
                f"appraisal value will deteriorate quickly absent recovery."
            )

    return EVVNBResult(
        appraisal_value=appraisal,
        appraisal_per_share=per_share,
        components=components,
        method=method,
        sanity_warnings=warnings,
    )


def select_vnb_multiple(
    insurer_type: str,
    new_business_growth: Optional[float] = None,
    market_share_trend: Optional[str] = None,
    ticker: Optional[str] = None,
) -> float:
    """Pick a VNB multiple based on insurer characteristics.

    Life insurers: 18-25x typical. Per-ticker defaults reflect
    sell-side consensus VNB-multiples:

      * HDFCLIFE  22x (brand + bancassurance premium)
      * ICICIPRULI 20x (mixed channel)
      * SBILIFE    24x (distribution moat via SBI branches)
      * MAXFIN     18x (smaller distribution footprint)
      * LICI       12x (sovereign mix, lower secular growth —
                        legitimately below the 15x floor)

    General + health insurers: returns a sentinel ``0.0`` — the EV/VNB
    framework does NOT apply (they don't publish EV or VNB). The
    correct framing is float-investment-income PE or DDM.

    Adjustments:
      * Market-share gainers: +2x to +3x
      * Market-share losers:  -3x to -5x
      * New-business-growth above 25%: +2x boost
      * New-business-growth below 5%:  -2x penalty

    Args:
        insurer_type: One of {"life", "general", "health"}. The
            caller is expected to derive this from
            ``LIFE_INSURERS`` / ``GENERAL_HEALTH_INSURERS``.
        new_business_growth: Optional fractional growth (0.15 for
            15%) — pulls the multiplier up for growth-tilted names.
        market_share_trend: One of {"gaining", "stable", "losing",
            None}. Optional qualitative input.
        ticker: Optional bare ticker. When provided AND a
            per-insurer default exists, that default is used as
            the base before growth / market-share adjustments.

    Returns:
        Multiple as a float. Returns 0.0 for general / health
        insurers (sentinel — caller must check before use).
    """
    itype = (insurer_type or "").strip().lower()
    if itype in ("general", "health", "general_insurance", "health_insurance",
                 "reinsurance", "non_life"):
        # Sentinel — caller must NOT apply this to compute_ev_vnb_appraisal.
        return 0.0
    if itype not in ("life", "life_insurance"):
        # Unknown insurer type — return mid-point default but log so the
        # caller can investigate.
        logger.debug(
            "select_vnb_multiple: unknown insurer_type=%r; defaulting to "
            "mid-point %.1fx", insurer_type, _DEFAULT_VNB_MULT,
        )
        return _DEFAULT_VNB_MULT

    # Per-ticker default if known. Otherwise mid-point.
    clean = _clean_ticker(ticker or "")
    base = _LIFE_INSURER_VNB_MULT_DEFAULTS.get(clean, _DEFAULT_VNB_MULT)

    # Market-share adjustment.
    if market_share_trend:
        trend = market_share_trend.strip().lower()
        if trend in ("gaining", "gain", "+"):
            base += 2.5
        elif trend in ("losing", "lose", "-"):
            base -= 4.0
        # "stable" → no adjustment.

    # Growth adjustment — symmetric ±2x at the 25%/5% thresholds.
    if new_business_growth is not None:
        g = float(new_business_growth)
        if g >= 0.25:
            base += 2.0
        elif g <= 0.05:
            base -= 2.0

    # Honour LICI / similar sovereign-mix legitimate-low overrides:
    # if the per-ticker default is already below the [15, 30] band
    # (only LICI today at 12x), keep the under-band value rather
    # than clamping. For everyone else, enforce the band.
    per_ticker_default = _LIFE_INSURER_VNB_MULT_DEFAULTS.get(clean)
    if per_ticker_default is not None and per_ticker_default < _VNB_MULT_FLOOR:
        # Allow the result to drift downward but cap upside at the
        # ceiling so an adjustment can't push a sovereign-mix name
        # above 30x.
        return max(0.0, min(_VNB_MULT_CEILING, base))
    return max(_VNB_MULT_FLOOR, min(_VNB_MULT_CEILING, base))


def is_ev_vnb_applicable(ticker: str, sector: Optional[str] = None) -> bool:
    """True iff the EV + VNB appraisal framework is appropriate.

    Returns True for the five listed Indian life insurers
    (``LIFE_INSURERS`` frozenset). Returns False for general /
    health insurers (they don't disclose EV / VNB), banks, and
    everything else.

    The ``sector`` argument is accepted for API symmetry with
    other cohort-classifier helpers in the analysis pipeline but
    is currently unused — ticker membership is the authoritative
    signal, because yfinance / NSE sector strings for insurers
    ("Insurance — Life", "Insurance — General", "Financial
    Services") are too coarse to distinguish the two cohorts.

    Args:
        ticker: Either bare ("HDFCLIFE") or canonical
            ("HDFCLIFE.NS") form.
        sector: Currently ignored — see note above. Accepted for
            future-proofing when sector taxonomy stabilises.

    Returns:
        True for life insurers, False otherwise.
    """
    clean = _clean_ticker(ticker)
    if not clean:
        return False
    if clean in LIFE_INSURERS:
        return True
    if clean in GENERAL_HEALTH_INSURERS:
        return False
    return False
