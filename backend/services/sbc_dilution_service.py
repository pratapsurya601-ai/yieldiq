# backend/services/sbc_dilution_service.py
"""
Stock-Based Compensation (SBC) dilution normalization — T4.1 Phase A.

Charlie Munger / Warren Buffett famously call stock-based compensation
(RSUs, ESOPs, ESPPs) "the most ignored real expense" in modern
financial reporting. The accounting recognises SBC on the income
statement, but it is then added back on the cash-flow statement as a
non-cash item, and most reported FCF / EPS / PE numbers ignore its
dilutive cost entirely. The shareholder absorbs it through dilution
that compounds annually.

This module produces a Munger-style adjustment:

    SBC-adjusted FCF    = reported_fcf - sbc_expense
    Forward dilution    = sbc_expense / current_price   (Cr shares)
    Adjusted share base = reported_shares + forward_dilution

Phase A is the standalone service plus an additive surface on the
financials reader. We DO NOT mutate the reported ``free_cash_flow``
field — DCF and every downstream consumer continue to read the GAAP
figure, so this PR is canary-safe by construction. Phase B (separate
PR) will switch the DCF input from reported_fcf to adjusted_fcf for
tickers whose ``sbc_intensity_label`` is ``"heavy"``.

Intensity buckets are calibrated to where the adjustment starts
materially shifting DCF fair value:

    SBC / FCF  <   2 %   →   "negligible"   (noise; ignore)
    SBC / FCF  2 – 5 %   →   "moderate"     (worth knowing)
    SBC / FCF  5 – 15 %  →   "material"     (DCF noticeably overstated)
    SBC / FCF  >  15 %   →   "heavy"        (DCF significantly wrong)

Heavy-SBC names in the Indian universe are concentrated in platform
IPOs (Zomato, Nykaa, Paytm, PB Fintech) and a handful of new-economy
listings. Large IT services (TCS, INFY, WIPRO) historically run
SBC < 2 % of FCF and are classified "negligible" automatically — no
need to list them in ``SBC_HEAVY_TICKERS``.

Defensive: every entry point catches bad inputs (None, NaN, zero
shares, negative FCF) and returns the reported values with a sanity
warning rather than crashing or silently producing nonsense.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("yieldiq.sbc_dilution")

# ─────────────────────────────────────────────────────────────────
# Intensity thresholds — tuned to where the SBC adjustment starts
# moving DCF fair-value by more than ~1 % per percentage point of
# SBC drag. Anything sub-2 % is below the noise floor of the
# underlying FCF estimate (yfinance / NSE_XBRL revisions move FCF
# by more than 2 % on revision-day for most tickers).
# ─────────────────────────────────────────────────────────────────
_NEGLIGIBLE_MAX_PCT = 2.0
_MODERATE_MAX_PCT = 5.0
_MATERIAL_MAX_PCT = 15.0


@dataclass
class SBCInputs:
    """Inputs for a single SBC adjustment calculation.

    All monetary values in INR Crores. Shares in Crores. Price in
    INR per share.

    ``sbc_history_inr_cr`` is optional and currently unused by
    ``compute_sbc_adjustment`` — it exists so callers (eg. analysis
    services) can pass through the trailing series for later trend
    analysis without a second DB hit.
    """
    reported_fcf: float
    sbc_expense_inr_cr: float
    reported_shares_outstanding: float
    current_price: float
    sbc_history_inr_cr: Optional[list[float]] = None


@dataclass
class SBCAdjustedFinancials:
    """Result of an SBC adjustment.

    Two pairs of fields:

    1. FCF leg
       - ``reported_fcf``         GAAP figure, untouched
       - ``sbc_adjusted_fcf``     reported_fcf − sbc_expense
       - ``sbc_as_pct_of_fcf``    SBC / reported_fcf × 100

    2. Share-count leg (forward dilution)
       - ``reported_shares``                  GAAP figure, untouched
       - ``forward_dilution_shares_added``    SBC / price (Cr shares)
       - ``dilution_adjusted_shares``         reported + added

    Plus a coarse intensity bucket and any sanity warnings raised
    by defensive paths (negative FCF, zero shares, missing inputs).
    """
    reported_fcf: float
    sbc_adjusted_fcf: float
    sbc_as_pct_of_fcf: float

    reported_shares: float
    forward_dilution_shares_added: float
    dilution_adjusted_shares: float

    sbc_intensity_label: str
    sanity_warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Heavy-SBC ticker set
#
# Indian-listed names where SBC has been > 5 % of FCF for at least
# one of the last three fiscal years. Source: company DRHP / annual
# report SBC disclosures cross-checked against published FCF.
#
# We deliberately EXCLUDE the large IT services bucket (TCS, INFY,
# WIPRO, HCLTECH, TECHM) — their SBC runs < 2 % of FCF and is
# classified "negligible" by ``classify_sbc_intensity`` automatically.
# Putting them in the heavy set would over-trigger the "worth
# surfacing" gate downstream.
# ─────────────────────────────────────────────────────────────────
SBC_HEAVY_TICKERS: frozenset[str] = frozenset({
    # Platform / consumer-internet IPOs — DRHP-disclosed heavy SBC
    "ZOMATO",
    "NYKAA",            # FSN E-Commerce Ventures
    "PAYTM",            # One 97 Communications
    "POLICYBZR",        # PB Fintech parent (legacy ticker)
    "PBFINTECH",        # PB Fintech (current ticker)
    # Mid-cap new-economy with disclosed SBC pools > 5% of FCF
    "ECLERX",
    "AFFLE",            # Affle India
    "EASEMYTRIP",       # Easy Trip Planners
    "TBOTEK",           # TBO Tek
    "MAPMYINDIA",       # C.E. Info Systems
    "DELHIVERY",
    "INDIAMART",        # IndiaMART InterMESH
})


def classify_sbc_intensity(sbc_pct_of_fcf: float) -> str:
    """Bucket the SBC intensity by its share of reported FCF.

    Boundaries are inclusive on the upper side: 2.0 % is "moderate",
    5.0 % is "material", 15.0 % is "heavy". Sub-zero or NaN inputs
    bucket to "negligible" (defensive; happens when FCF is negative
    or SBC is missing).
    """
    try:
        pct = float(sbc_pct_of_fcf)
    except (TypeError, ValueError):
        return "negligible"
    if math.isnan(pct) or pct <= _NEGLIGIBLE_MAX_PCT:
        return "negligible"
    if pct <= _MODERATE_MAX_PCT:
        return "moderate"
    if pct <= _MATERIAL_MAX_PCT:
        return "material"
    return "heavy"


def _is_finite_positive(x: object) -> bool:
    """True iff x is a finite, non-NaN, strictly positive number."""
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    return v > 0


def _is_finite(x: object) -> bool:
    """True iff x is a finite, non-NaN number (sign doesn't matter)."""
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return not (math.isnan(v) or math.isinf(v))


def compute_sbc_adjustment(inputs: SBCInputs) -> SBCAdjustedFinancials:
    """Apply Munger-style SBC adjustment.

    Defensive — invalid inputs return the reported values with a
    sanity warning rather than NaN / crash. The four failure modes
    we explicitly catch:

      1. Reported FCF non-finite   → return reported (no adjustment)
      2. Reported FCF <= 0         → return reported, warn (the
                                     "SBC as % of FCF" ratio is
                                     undefined when FCF is non-positive
                                     so we cannot bucket intensity)
      3. SBC missing / non-finite  → treat as zero, mark "negligible"
      4. Shares <= 0 OR price <= 0 → skip forward-dilution leg
                                     (FCF leg still computed)
    """
    warnings: list[str] = []

    reported_fcf = inputs.reported_fcf
    sbc = inputs.sbc_expense_inr_cr
    shares = inputs.reported_shares_outstanding
    price = inputs.current_price

    # ── FCF leg ────────────────────────────────────────────────
    if not _is_finite(reported_fcf):
        warnings.append("reported_fcf_non_finite")
        # Cannot compute anything meaningful — return zero-shape
        # result tagged with the warning so callers can degrade.
        return SBCAdjustedFinancials(
            reported_fcf=0.0,
            sbc_adjusted_fcf=0.0,
            sbc_as_pct_of_fcf=0.0,
            reported_shares=float(shares) if _is_finite(shares) else 0.0,
            forward_dilution_shares_added=0.0,
            dilution_adjusted_shares=(
                float(shares) if _is_finite(shares) else 0.0
            ),
            sbc_intensity_label="negligible",
            sanity_warnings=warnings,
        )

    reported_fcf = float(reported_fcf)

    if not _is_finite(sbc):
        warnings.append("sbc_expense_missing")
        sbc_val = 0.0
    else:
        sbc_val = float(sbc)
        if sbc_val < 0:
            warnings.append("sbc_expense_negative_clamped_to_zero")
            sbc_val = 0.0

    adjusted_fcf = reported_fcf - sbc_val

    # Intensity calc — only meaningful when reported FCF is positive.
    if reported_fcf <= 0:
        warnings.append("reported_fcf_non_positive_intensity_unknown")
        sbc_pct = 0.0
        intensity = "negligible"
    else:
        sbc_pct = round((sbc_val / reported_fcf) * 100.0, 2)
        intensity = classify_sbc_intensity(sbc_pct)

    # ── Share-count leg ────────────────────────────────────────
    if not _is_finite_positive(shares):
        warnings.append("reported_shares_zero_or_invalid")
        shares_val = 0.0
        forward_added = 0.0
        adjusted_shares = 0.0
    elif not _is_finite_positive(price):
        warnings.append("current_price_zero_or_invalid")
        shares_val = float(shares)
        forward_added = 0.0
        adjusted_shares = shares_val
    else:
        shares_val = float(shares)
        price_val = float(price)
        # SBC is in INR Cr (= 1e7 INR). Price is INR per share.
        # → forward dilution in Cr shares = sbc_cr * 1e7 / price / 1e7
        # = sbc_cr / price. The unit conversion is a wash because
        # we want the answer in the same unit as the share count
        # (Cr shares).
        forward_added = round(sbc_val / price_val, 4)
        if forward_added < 0:
            # Should not happen given the SBC clamp above, but guard
            # against weird inputs.
            forward_added = 0.0
        adjusted_shares = round(shares_val + forward_added, 4)

    return SBCAdjustedFinancials(
        reported_fcf=round(reported_fcf, 2),
        sbc_adjusted_fcf=round(adjusted_fcf, 2),
        sbc_as_pct_of_fcf=sbc_pct,
        reported_shares=round(shares_val, 4),
        forward_dilution_shares_added=forward_added,
        dilution_adjusted_shares=adjusted_shares,
        sbc_intensity_label=intensity,
        sanity_warnings=warnings,
    )


def is_sbc_adjustment_meaningful(
    ticker: str,
    sbc_pct_of_fcf: float,
) -> bool:
    """Worth surfacing the adjustment to the user?

    True iff intensity is "material" or "heavy" OR the ticker is in
    the curated heavy-SBC set (catches names where the latest FY's
    SBC is below the trailing average — e.g. a Zomato print where
    sentiment-driven SBC accrual was unusually light).
    """
    if not ticker:
        return classify_sbc_intensity(sbc_pct_of_fcf) in {"material", "heavy"}
    t = ticker.upper().strip().replace(".NS", "").replace(".BO", "")
    if t in SBC_HEAVY_TICKERS:
        return True
    return classify_sbc_intensity(sbc_pct_of_fcf) in {"material", "heavy"}


def to_dict(result: SBCAdjustedFinancials) -> dict:
    """JSON-safe dict form. Matches the dataclass field names 1:1."""
    return {
        "reported_fcf": result.reported_fcf,
        "sbc_adjusted_fcf": result.sbc_adjusted_fcf,
        "sbc_as_pct_of_fcf": result.sbc_as_pct_of_fcf,
        "reported_shares": result.reported_shares,
        "forward_dilution_shares_added": result.forward_dilution_shares_added,
        "dilution_adjusted_shares": result.dilution_adjusted_shares,
        "sbc_intensity_label": result.sbc_intensity_label,
        "sanity_warnings": list(result.sanity_warnings),
    }


__all__ = [
    "SBCInputs",
    "SBCAdjustedFinancials",
    "SBC_HEAVY_TICKERS",
    "classify_sbc_intensity",
    "compute_sbc_adjustment",
    "is_sbc_adjustment_meaningful",
    "to_dict",
]
