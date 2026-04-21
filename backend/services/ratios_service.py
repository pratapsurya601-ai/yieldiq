# backend/services/ratios_service.py
# ═══════════════════════════════════════════════════════════════
# Canonical formulas for the quality-and-valuation ratios surfaced
# on the fair-value page. Each function returns `None` on bad input
# rather than raising — callers pipe None through to the frontend
# which renders "—".
#
# Units (matches ValuationOutput / QualityOutput):
#   ROCE, ROA, ROE         -> PERCENT (23.5 for 23.5%)
#   revenue CAGR           -> DECIMAL (0.124 for 12.4%)
#   EV/EBITDA, D/EBITDA,   -> RATIO
#   Current, Asset T/O     -> RATIO
#   Interest coverage      -> RATIO (times)
#
# NOTE: The existing in-flight ROCE computation in analysis_service.py
# uses `ebit / total_assets` (technically ROA). Changing that formula
# is a semantic change for every existing stock and would require a
# coordinated CACHE_VERSION bump per the discipline rules. The
# `compute_roce` in this module uses the textbook capital-employed
# denominator and is intentionally unwired until that rebaseline.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Sequence

log = logging.getLogger("yieldiq.ratios")


def _num(v):
    if v is None:
        return None
    try:
        x = float(v)
        if x != x:  # NaN
            return None
        return x
    except (TypeError, ValueError):
        return None


def compute_roce(ebit, total_assets, current_liabilities) -> float | None:
    """ROCE = EBIT / (Total Assets − Current Liabilities). Returns PERCENT.

    FIX2: explicitly returns None (NOT 0.0) for any missing/non-positive
    input so the frontend renders "—" rather than a misleading "0.0% Weak"
    chip. Inputs may be in any consistent monetary unit (raw INR, Cr,
    USD…) — the ratio is unit-free and ÷100 returns percent.

    Non-positive EBIT → None. A genuine loss-making company's negative
    ROCE is technically computable, but it's more useful to show "—"
    in the UI than a precise-looking red "-12.3% Weak" — users
    consistently misread the latter as 'healthy company losing money'
    rather than 'data unavailable / deep distress'. Callers that want
    the signed value can compute it themselves.
    """
    _ebit = _num(ebit)
    _ta = _num(total_assets)
    _cl = _num(current_liabilities)
    # Treat 0/None EBIT as "data not available" → None (NOT 0.0).
    if _ebit is None or _ebit <= 0:
        return None
    if _ta is None or _cl is None:
        return None
    cap_employed = _ta - _cl
    if cap_employed is None or cap_employed <= 0:
        return None
    return round(_ebit / cap_employed * 100.0, 1)


# Conversion: 1 Crore = 1e7 INR.
_CR = 1e7


def compute_ev_ebitda(
    market_cap_cr,
    total_debt_inr,
    total_cash_inr,
    ebitda_inr,
) -> float | None:
    """Enterprise-value multiple. Returns ratio (×).

    FIX2 — UNIT NORMALISATION:
        The pipeline carries `market_cap_cr` in Crores while
        `total_debt`, `total_cash`, and `ebitda` from local_data_service
        are in RAW INR (already multiplied by 1e7). Earlier versions of
        this helper assumed all four were in the same unit and produced
        absurd numbers (e.g. HCLTECH = 1376× instead of ~20×) when
        callers handed it the natural, mixed-unit fields off the
        enriched dict.

        We now convert everything to Crores internally so the ratio
        is correct regardless of caller convention — and so the same
        sanity check (1×–500×) holds in the validators chain.
    """
    # ── UNIT CONTRACT — DO NOT BREAK ─────────────────────────────
    # Numerator (EV) and denominator (EBITDA) MUST end up in the
    # SAME unit before the division. The historical bug class was
    # passing EV in raw INR and EBITDA in Cr (or vice versa), which
    # produced ratios off by a factor of 1e7 (HCLTECH=1376×, INFY=
    # 1217× in real payloads).
    #
    # Argument units accepted by this helper:
    #   market_cap_cr   -> CRORES         (e.g. 5_60_000 for ₹5.6L Cr)
    #   total_debt_inr  -> RAW INR        (e.g. 8.4e10 for ₹8,400 Cr)
    #   total_cash_inr  -> RAW INR
    #   ebitda_inr      -> RAW INR
    #
    # We normalise EVERYTHING to Crores below. Both `ev_cr` and
    # `ebitda_cr` are in CRORES at the point of division, so the
    # ratio is unit-free and dimensionally correct.
    # ────────────────────────────────────────────────────────────
    _mc_cr = _num(market_cap_cr)         # already Cr
    _td_inr = _num(total_debt_inr) or 0.0  # raw INR -> /1e7 -> Cr
    _tc_inr = _num(total_cash_inr) or 0.0  # raw INR -> /1e7 -> Cr
    _eb_inr = _num(ebitda_inr)             # raw INR -> /1e7 -> Cr
    if _mc_cr is None or _eb_inr is None or _eb_inr <= 0:
        return None  # don't fall back to 0 — return None for "data n/a"
    debt_cr = _td_inr / _CR    # raw INR -> Cr
    cash_cr = _tc_inr / _CR    # raw INR -> Cr
    ebitda_cr = _eb_inr / _CR  # raw INR -> Cr
    if ebitda_cr <= 0:
        return None
    ev_cr = _mc_cr + debt_cr - cash_cr   # Cr + Cr - Cr -> Cr
    ratio = round(ev_cr / ebitda_cr, 1)  # Cr / Cr -> unit-free ×

    # WARNING log when the SOURCE produces a ratio outside the
    # plausible band (0.5×, 200×). The response-layer
    # `_clamp_ev_ebitda` (analysis_service.py) and the
    # local_data_service.py:357 sanity guard both still clamp this
    # for the UI, but this log lets us monitor source-data quality
    # so unit mixups don't silently re-emerge.
    try:
        if not (0.5 < ratio < 200):
            log.warning(
                "RATIOS: EV/EBITDA raw=%.1f× outside (0.5, 200) "
                "(mcap_cr=%.2f debt_cr=%.2f cash_cr=%.2f "
                "ebitda_cr=%.2f) — likely source-data issue; will "
                "be clamped at response layer.",
                ratio, _mc_cr, debt_cr, cash_cr, ebitda_cr,
            )
    except Exception:
        pass

    return ratio


def compute_debt_to_ebitda(total_debt, ebitda) -> float | None:
    """Debt / EBITDA. Returns ratio (×).

    Both inputs must be in the same monetary unit; the ratio is
    unit-free so we don't normalise. Audited as part of FIX2 — the
    canonical caller (analysis_service) hands both fields straight
    from `enriched`, so they are always in raw INR together.
    """
    _td = _num(total_debt)
    _eb = _num(ebitda)
    if _td is None or _eb is None or _eb <= 0:
        return None
    return round(_td / _eb, 1)


def compute_interest_coverage(ebit, interest_expense) -> float | None:
    """EBIT / Interest Expense. Returns ratio (×).

    Both inputs must be in the same monetary unit; the ratio is
    unit-free so we don't normalise here.
    """
    _ebit = _num(ebit)
    _ie = _num(interest_expense)
    if _ebit is None or _ie is None or _ie <= 0:
        return None
    return round(_ebit / _ie, 1)


def compute_current_ratio(current_assets, current_liabilities) -> float | None:
    """Current Assets / Current Liabilities. Returns ratio (×)."""
    _ca = _num(current_assets)
    _cl = _num(current_liabilities)
    if _ca is None or _cl is None or _cl <= 0:
        return None
    return round(_ca / _cl, 2)


def compute_asset_turnover(revenue, total_assets) -> float | None:
    """Revenue / Total Assets. Returns ratio (×)."""
    _rev = _num(revenue)
    _ta = _num(total_assets)
    if _rev is None or _ta is None or _ta <= 0:
        return None
    return round(_rev / _ta, 2)


# ═══════════════════════════════════════════════════════════════
# Bank-native helpers (added 2026-04-21 for feat/bank-prism-metrics)
#
# Banks don't play well with the generic ROCE / Debt/EBITDA / Interest
# Coverage set — deposits aren't debt, capital employed ≠ total assets,
# and interest is revenue not a cost to cover. These helpers give us
# bank-appropriate primitives that feed the Prism axes.
#
# Data availability notes (see docs/bank_data_availability.md):
#   - ROA, ROE          → `financials` table (pre-computed)
#   - Cost-to-Income    → `company_financials.operating_expense / revenue`
#   - YoY growth        → derived from annual series
#   - NIM / CAR / NPA   → NOT in DB yet (source: NSE XBRL Sch A/B/XI/XVIII)
# ═══════════════════════════════════════════════════════════════


def compute_roa(net_income, total_assets) -> float | None:
    """Return On Assets = Net Income / Total Assets. Returns PERCENT.

    Both inputs must be in the same monetary unit; ratio is unit-free.
    Non-positive assets → None.
    """
    _ni = _num(net_income)
    _ta = _num(total_assets)
    if _ta is None or _ta <= 0:
        return None
    if _ni is None:
        return None
    return round(_ni / _ta * 100.0, 2)


def compute_cost_to_income(operating_expense, total_income) -> float | None:
    """Cost-to-Income = Operating Expense / Total Income. Returns PERCENT.

    For banks, `total_income` is (interest earned + non-interest income).
    When that split isn't available we pass `revenue` (the
    `company_financials.revenue` column already aggregates them for the
    XBRL ingest). Lower is better; top Indian private banks run ~40-45%,
    PSU banks ~50-55%.

    Non-positive denominator → None.
    """
    _opex = _num(operating_expense)
    _rev = _num(total_income)
    if _rev is None or _rev <= 0:
        return None
    if _opex is None or _opex < 0:
        return None
    return round(_opex / _rev * 100.0, 2)


def compute_yoy_growth(current, previous) -> float | None:
    """Year-over-year growth as PERCENT.

    Returns None when the prior value is <= 0 (growth formula undefined)
    or either value is missing. Use this for Advances YoY / Deposits YoY
    / Revenue YoY / PAT YoY.
    """
    _curr = _num(current)
    _prev = _num(previous)
    if _curr is None or _prev is None:
        return None
    if _prev <= 0:
        return None
    return round((_curr - _prev) / _prev * 100.0, 2)


def compute_nim(interest_earned, interest_expended, total_assets) -> float | None:
    """Net Interest Margin = (Int Earned − Int Expended) / Total Assets.

    Returns PERCENT. Input fields are typically NULL in our current
    `company_financials` rows — this function is here for the day the
    NSE XBRL Schedule A/B extractor lands. Until then callers will feed
    all-None and get None back (correctly).
    """
    _ie = _num(interest_earned)
    _iex = _num(interest_expended)
    _ta = _num(total_assets)
    if _ta is None or _ta <= 0:
        return None
    if _ie is None or _iex is None:
        return None
    return round((_ie - _iex) / _ta * 100.0, 2)


def compute_revenue_cagr(revenues: Sequence[float], years: int) -> float | None:
    """
    revenues: iterable with the LATEST value LAST (chronological).
    Returns DECIMAL CAGR (0.124 = 12.4%) or None when insufficient data.

    PR-DATA-2 source-side hardening:
      1. Year-ordering: caller MUST pass oldest→newest. We do NOT
         re-sort here because we have no reliable timestamp on the
         scalars; if upstream reverses, every CAGR will be wrong with
         the inverse sign — that is the sole shape this function
         expects, and it is now asserted by the |cagr| > 50% WARNING
         log below (a -75% read on a stable IT services name is the
         classic reversed-series signature).
      2. NaN filtering: previously only `None` was stripped, so NaN
         floats survived the comprehension and produced NaN CAGR. Now
         filtered alongside None.
      3. Index-shift bug: the previous filter dropped Nones silently,
         which shifted `series[-years-1]` away from "true 3y ago" when
         a middle year was missing. We now require the FULL window of
         consecutive non-None, non-NaN values; if the last `years+1`
         positions in the input contain any holes we return None
         rather than silently mis-aligning the base year.
      4. Non-positive base year: explicit guard — CAGR is undefined
         when the base revenue is <= 0 (loss-to-profit swings, JV
         carve-outs, fresh listings, accounting restatements).
    """
    if revenues is None:
        return None

    def _clean(x):
        if x is None:
            return None
        try:
            f = float(x)
            if f != f:  # NaN
                return None
            return f
        except (TypeError, ValueError):
            return None

    raw = list(revenues)
    if len(raw) < years + 1:
        return None

    # Take the last `years + 1` positions and require ALL of them to
    # be valid — preserves correct year alignment.
    window = [_clean(v) for v in raw[-(years + 1):]]
    if any(v is None for v in window):
        return None

    start = window[0]
    end = window[-1]

    # Guard: cannot CAGR off a non-positive base. A negative or zero
    # base year (loss year, demerger, restated to zero) makes the
    # power formula meaningless or sign-flipped.
    if start is None or start <= 0:
        return None
    if end is None or end <= 0:
        return None

    cagr = round((end / start) ** (1.0 / years) - 1.0, 4)

    # WARNING log when the SOURCE produces an absurd CAGR. The
    # response-layer `_sanitize_cagr` (analysis_service.py) still
    # clamps |CAGR| > 50% to None for the UI, but this log lets us
    # measure how often the upstream series itself is dirty (FX
    # mixup, year-order flip, special situation) so we can chase
    # the root cause rather than just the symptom.
    try:
        if abs(cagr) > 0.50:
            log.warning(
                "RATIOS: revenue CAGR %dy raw=%.4f outside ±50%% "
                "(start=%.2f end=%.2f window_len=%d) — likely "
                "source-data issue; will be clamped to None at "
                "response layer.",
                years, cagr, start, end, len(window),
            )
    except Exception:
        pass

    return cagr
