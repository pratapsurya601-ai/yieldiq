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
from typing import Optional

logger = logging.getLogger("yieldiq.insurance_appraisal")


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
