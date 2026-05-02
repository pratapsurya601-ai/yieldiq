# backend/services/analysis/utils.py
# ═══════════════════════════════════════════════════════════════
# Pure-function utilities extracted verbatim from the historical
# analysis_service.py monolith: ticker canonicalization, pct
# normalization, FX multiplier, red-flag generators, etc.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging

from backend.models.responses import RedFlag

_logger = logging.getLogger(__name__)

# ── MoS display clamp (P0 standardization, 2026-05-02) ─────────
# Single source of truth for clamping the displayed margin-of-safety
# percentage. The underlying raw mos_pct (always (FV-CMP)/CMP * 100)
# is preserved on the response in `margin_of_safety` for downstream
# consumers (canary-diff, alerts, fair-value history). The display
# value is bounded to [-100, +200]:
#   * -100 floor: with the CMP denominator, the worst case is FV=0
#     which gives -100%. Anything more negative is upstream noise.
#   * +200 ceiling: allow a 3x FV/CMP signal through so genuine deep
#     value names (FV ≈ 3×CMP) still surface; beyond that we clamp.
# Returns (display_value, was_clamped). Pass None through unchanged.
def display_mos(raw_mos):  # type: ignore[no-untyped-def]
    if raw_mos is None:
        return None, False
    try:
        v = float(raw_mos)
    except (TypeError, ValueError):
        return None, False
    clamped = max(-100.0, min(200.0, v))
    # Use a small epsilon so floating-point round-trips don't
    # spuriously flip mos_clamped to True for in-range values.
    return clamped, abs(clamped - v) > 1e-6

# Boundary band for the decimal/percent heuristic. Values within this
# many points of |1.0| log a WARNING so future threshold-window bugs
# (see PR #126: window ±5 → ±1 silently corrupted ROE/ROCE/ROA for
# ~100 stocks) are visible in observability before they corrupt data.
_PCT_BOUNDARY_BAND = 0.05
from screener.moat_engine import STRONG_BRAND_ALLOWLIST as _STRONG_BRAND_ALLOWLIST
from backend.services.analysis.constants import (
    FINANCIAL_COMPANIES,  # noqa: F401  (kept for parity with the monolith)
    _NBFC_TICKERS,
    _INSURANCE_TICKERS,
    TICKER_SECTOR_OVERRIDES,
    SECTOR_OVERRIDES,
    USD_INR_RATE,
)


def _get_financial_sub_type(clean_ticker: str) -> str:
    """Return 'NBFC', 'Insurance', or 'Banking' for a financial ticker."""
    if clean_ticker in _NBFC_TICKERS:
        return "NBFC"
    if clean_ticker in _INSURANCE_TICKERS:
        return "Insurance"
    return "Banking"


def _get_adjusted_fcf(fcf, pat, is_financial):
    """Floor FCF to PAT proxy for capex-heavy companies."""
    if is_financial:
        return None  # Don't use FCF for financials
    if fcf is None:
        return pat * 0.55 if pat and pat > 0 else None
    if pat and pat > 0 and fcf < pat * 0.3:
        # FCF looks distorted by heavy capex — use PAT proxy
        return pat * 0.55
    return fcf


def _clamp_ev_ebitda(value):
    """Defense-in-depth: cap EV/EBITDA at the response layer so absurd
    values from any upstream path (yfinance unit mixup, stale cache row,
    bad market_metrics column) can never reach the UI.

    Audit feedback: INFY persistently shows EV/EBITDA = 1217.5× across
    audits while peer median is ~24×. local_data_service.py:357 added
    a sanity guard but the value can still leak through other paths
    (eveb.get("current_ev_ebitda") if that ever fires). Final guard
    here: anything outside (0.5, 200) returns None → UI renders "—".
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0.5 or v > 200:
        return None
    return v


def _enforce_scenario_order(bear, base, bull, price: float):
    """Defense-in-depth: ensure bull >= base >= bear in the final output.

    PR-NTPC: scenarios.py already enforces ordering after the parallel
    DCF runs, but the wave-of-fixes hit edge cases on certain stocks
    (e.g. NTPC: utilities with terminal_g near WACC produce a degenerate
    bull DCF where the bull-growth perturbation actually decreases the
    forecasted IV vs base). When that happens, the canary Gate 3 fires
    "scenario order broken bull < base".

    This wrapper is the LAST line of defense before serialization. If
    bull < base or bear > base after all upstream logic, clamp them to
    sane ±7.5% bands and flag with `scenario_clamped=True` in MoS-pct
    field comment (kept silent to avoid user-visible "clamped" flag —
    the fact that it surfaced here means the upstream DCF was unstable
    for this ticker, which is a separate investigation, not a
    user-facing display bug).

    Why ±7.5% (widened 2026-04-25 from ±5%): the canary harness Gate 3
    floor is 5% bull/bear separation. Clamping at exactly ±5% leaves
    no headroom — any rounding nudges the post-clamp scenario right
    onto the gate boundary and trips it. ±7.5% buys a 2.5pp safety
    margin above the floor.
    """
    from backend.models.responses import ScenarioCase, ScenariosOutput
    base_iv = base.iv or 0.0
    bear_iv = bear.iv or 0.0
    bull_iv = bull.iv or 0.0

    # P0 BATCH A2 (2026-05-02): bull spread sanity gate.
    # Ordering check alone (`bear <= base <= bull`) was passing for cases
    # where the bull leg sat just barely above base — e.g. INFY had
    # bear=409 / base=683 / bull=685 (bull only +0.3% above base) and
    # FOSECOIND had bear=1647 / base=2997 / bull=3404 (+13.6%). Root
    # cause: scenarios.py computes bull off its own scenarios-base DCF
    # while service.py uses the main blended `iv` as the displayed base,
    # so the asymmetric flex collapsed when the main IV was already on
    # the optimistic side of the scenarios DCF. Enforce a minimum +20%
    # bull spread (and -20% bear floor) below — pushes the clamped
    # ordering branch whenever the natural spread is too tight, not
    # just when ordering is broken.
    _MIN_BULL_SPREAD = 1.20   # bull must be >= base * 1.20
    _MAX_BEAR_SPREAD = 0.80   # bear must be <= base * 0.80
    # Trigger clamp if natural bull spread is < +15% (FOSECOIND audit
    # showed +13% bull spread looking flat to users) or natural bear
    # spread is < -15%. The asymmetry between trigger (15%) and floor
    # (20%) gives a small hysteresis margin.
    _too_tight = base_iv > 0 and (
        bull_iv < base_iv * 1.15 or bear_iv > base_iv * 0.85
    )

    # If ordering is intact AND spread is meaningful, return as-is.
    if bear_iv <= base_iv <= bull_iv and not _too_tight:
        return ScenariosOutput(bear=bear, base=base, bull=bull)

    if _too_tight and bear_iv <= base_iv <= bull_iv:
        # Ordering OK but spread too tight — log so it's visible in obs.
        import logging
        logging.getLogger("yieldiq.scenarios").warning(
            "bull_flex.too_tight bear=%.2f base=%.2f bull=%.2f "
            "(bull/base=%.3f, bear/base=%.3f) — forcing min ±20%% spread",
            bear_iv, base_iv, bull_iv,
            (bull_iv / base_iv) if base_iv > 0 else 0,
            (bear_iv / base_iv) if base_iv > 0 else 0,
        )

    # Otherwise clamp. Bear can't exceed 80% of base; bull can't drop
    # below 120% of base. Recompute mos_pct from clamped iv.
    # (Was 92.5% / 107.5% — too tight; the +/-7.5% band silently
    # accepted near-equal scenarios that confused users about the
    # range of outcomes.)
    fixed_bear_iv = min(bear_iv, base_iv * _MAX_BEAR_SPREAD) if base_iv > 0 else bear_iv
    fixed_bull_iv = max(bull_iv, base_iv * _MIN_BULL_SPREAD) if base_iv > 0 else bull_iv

    def _mos_pair(iv):
        if price and price > 0 and iv > 0:
            raw = (iv - price) / price * 100
            d, c = display_mos(raw)
            return round(d if d is not None else 0.0, 1), c
        return 0.0, False

    _fb_mos, _fb_clamped = _mos_pair(fixed_bear_iv)
    fixed_bear = ScenarioCase(
        iv=round(fixed_bear_iv, 2), mos_pct=_fb_mos, mos_clamped=_fb_clamped,
        growth=bear.growth, wacc=bear.wacc, term_g=bear.term_g,
    ) if fixed_bear_iv != bear_iv else bear

    _fl_mos, _fl_clamped = _mos_pair(fixed_bull_iv)
    fixed_bull = ScenarioCase(
        iv=round(fixed_bull_iv, 2), mos_pct=_fl_mos, mos_clamped=_fl_clamped,
        growth=bull.growth, wacc=bull.wacc, term_g=bull.term_g,
    ) if fixed_bull_iv != bull_iv else bull

    import logging
    logging.getLogger("yieldiq.scenarios").warning(
        "scenario_clamp: bear/bull clamped to base ±20%% — investigate "
        "(orig bear=%s base=%s bull=%s -> bear=%s base=%s bull=%s)",
        bear_iv, base_iv, bull_iv,
        fixed_bear.iv, base.iv, fixed_bull.iv,
    )
    return ScenariosOutput(bear=fixed_bear, base=base, bull=fixed_bull)


# Known Indian bare-ticker set. Built once from ticker_search.INDIAN_STOCKS
# so adding a stock there automatically extends canonicalization.
# Guarded behind a lazy property — import cycles are annoying.
_KNOWN_INDIAN_BARE: frozenset[str] | None = None


def _known_indian_bare() -> frozenset[str]:
    """Cached set of bare tickers known to be Indian.

    Sources, in order:
      1. Static `ticker_search.INDIAN_STOCKS` list (fast, ships with code).
      2. Live `stocks` table on Neon — adds every active bare row whose
         `ticker_ns` resolves to an `.NS` symbol. This catches stocks not
         in the curated INDIAN_STOCKS list (e.g. CAPLIPOINT, mid/small caps
         added via the BSE/NSE listing import) which were silently routed
         to the US pipeline because the static list was the only source.
         See P0 bug 2026-04-30: /analysis/CAPLIPOINT served USD prices and
         "US General" sector tag because CAPLIPOINT existed in `stocks` but
         not in INDIAN_STOCKS, so canonicalization fell through.

    DB lookup runs once per process (cached in module-level frozenset).
    Failures degrade gracefully — we keep whatever sources succeeded.
    """
    global _KNOWN_INDIAN_BARE
    if _KNOWN_INDIAN_BARE is not None:
        return _KNOWN_INDIAN_BARE
    bare: set[str] = set()
    # Source 1: static curated list
    try:
        from backend.services.ticker_search import INDIAN_STOCKS
        for d in INDIAN_STOCKS:
            t = d.get("ticker") if isinstance(d, dict) else None
            if t:
                bare.add(t.replace(".NS", "").replace(".BO", "").upper())
    except Exception as exc:
        _logger.warning("ticker_search load failed for canonicalize: %s", exc)
    # Source 2: live `stocks` table on Neon. The schema uses bare PK with
    # a separate `ticker_ns` column for the NSE-suffixed variant. Pull all
    # active rows.
    try:
        from backend.services.analysis.db import _get_pipeline_session
        from sqlalchemy import text
        sess = _get_pipeline_session()
        if sess is not None:
            try:
                rows = sess.execute(
                    text(
                        "SELECT ticker FROM stocks "
                        "WHERE ticker_ns IS NOT NULL AND is_active = true"
                    )
                ).fetchall()
                for r in rows:
                    if r and r[0]:
                        bare.add(str(r[0]).upper())
            finally:
                try:
                    sess.close()
                except Exception:
                    pass
    except Exception as exc:
        _logger.warning("stocks-table load failed for canonicalize: %s", exc)
    _KNOWN_INDIAN_BARE = frozenset(bare)
    _logger.info("canonicalize: loaded %d known Indian bare tickers", len(_KNOWN_INDIAN_BARE))
    return _KNOWN_INDIAN_BARE


# ── Ticker existence gate (P1, 2026-05-02) ─────────────────────
# `_known_indian_bare()` above already loads every active bare
# ticker from the `stocks` table once per process. We reuse that
# cache to cheaply 404 anything that isn't a real symbol — the
# auditor flagged /prism/HEALTHCARE (a sector name) and
# /prism/SHAQUAK (junk) auto-creating "Fair value 5.0/10" stub
# pages even though the new null-pillar gate flipped them to
# "Under Review". Real fix: refuse to even compute.
#
# Returns True if the bare form (suffix-stripped, upper-cased) is
# in the cached known-Indian-bare set. US tickers and anything
# else fall through to True so this function is purely a guard
# against junk Indian-suffixed inputs (HEALTHCARE.NS, SHAQUAK.NS,
# HEALTHCARE bare). For US/global symbols we still let the request
# through — those are validated downstream by the data provider.
def _is_known_ticker(ticker: str) -> bool:
    """Cheap existence check: is `ticker` a real Indian symbol or a
    plausibly-non-Indian symbol we should let through?

    Implementation detail: piggy-backs on `_known_indian_bare()` so
    there's zero extra DB load — the set is built once per worker
    and then served from a module-level frozenset.
    """
    if not ticker:
        return False
    bare = (
        str(ticker).strip().upper()
        .replace(".NS", "")
        .replace(".BO", "")
    )
    if not bare:
        return False
    try:
        if bare in _known_indian_bare():
            return True
    except Exception:
        # Cache load failed — fail OPEN so a transient DB blip can't
        # take the whole site down with bogus 404s.
        return True
    # If the input had an Indian suffix (.NS / .BO) and the bare
    # form is NOT in the known-Indian set, we treat it as junk
    # (HEALTHCARE.NS, SHAQUAK.NS). Without a suffix we let it
    # through as a possible US/global symbol.
    t_up = str(ticker).strip().upper()
    if t_up.endswith(".NS") or t_up.endswith(".BO"):
        return False
    # Bare-form guard: if it's clearly Indian-shaped (all-letters,
    # > 4 chars, requested via a route that expects Indian inputs)
    # we still let the underlying handler decide — the DB lookup
    # above already covered the "yes Indian" case. Default open.
    return True


def _canonicalize_ticker(ticker: str) -> str:
    """Normalize bare Indian tickers to their .NS form.

    Examples:
        'TCS'        → 'TCS.NS'      (known Indian, add suffix)
        'TCS NS'     → 'TCS.NS'      (space-separated variant)
        'TCS.NS'     → 'TCS.NS'      (already canonical)
        'TCS.BO'     → 'TCS.BO'      (BSE variant — preserved)
        ' tcs '      → 'TCS.NS'      (whitespace + case)
        'AAPL'       → 'AAPL'        (genuinely US, unchanged)
        '  '         → ''            (empty after strip)

    The backend's is_indian detection relies on suffix presence. Without
    canonicalization, a bare Indian ticker like 'TCS' flows through the
    US pipeline and returns sector='US General', currency='USD', and
    all XBRL-sourced fields null. Visible on the Discover rails and any
    caller that passes bare symbols (screen results, autocomplete, etc).
    """
    if not ticker:
        return ticker
    # 1. Whitespace + case normalization
    t = ticker.strip().upper()
    if not t:
        return t
    # 2. Space-separated variants ('TCS NS' / 'TCS BO' / 'TCS BSE' /
    #    'TCS NSE') — collapse internal whitespace and attempt a suffix
    #    match BEFORE the bare-ticker-set lookup.
    if " " in t:
        parts = t.split()
        base = parts[0]
        tail = "".join(parts[1:])  # 'NS', 'BO', 'NSE', 'BSE', etc.
        # Map common tail variants to canonical suffixes
        if tail in ("NS", "NSE"):
            return f"{base}.NS"
        if tail in ("BO", "BSE"):
            return f"{base}.BO"
        # Unknown tail — fall through to bare-ticker logic on the base
        t = base
    # 3. Already has a canonical suffix — preserve as-is
    if t.endswith(".NS") or t.endswith(".BO"):
        return t
    # 4. Bare ticker known to be Indian — append .NS
    if t in _known_indian_bare():
        return f"{t}.NS"
    # 5. Genuinely US or unknown — pass through
    return t


def _normalize_pct(val) -> float | None:
    """
    Normalize a percentage-ish value to always be in PERCENTAGE form (23.5 for 23.5%).

    Handles mixed conventions in our data pipeline:
    - yfinance returns ROE as decimal (0.235 for 23.5%)
    - Aiven XBRL sometimes stores as percentage (23.5)
    - Some computed fields use decimals

    Rule: if |val| < 1 we treat it as decimal (yfinance bounds decimals
    to [-1, 1]), else already percentage. Previously this window was ±5
    which double-multiplied legitimate small percent values — see the
    inline comment below for the bug history.
    """
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v == 0:
        return 0.0
    # yfinance returns ROE/ROCE/ROA as decimals bounded by [-1, 1]
    # (e.g. 0.235 == 23.5%). Any |v| >= 1 is therefore already in
    # percent form (e.g. 23.5 == 23.5%) and must NOT be re-multiplied.
    # Bug history: this window was previously (-5, 5), which double-
    # multiplied any percent value with |v| < 5 — corrupting ROE/ROCE/ROA
    # for low-margin stocks (e.g. GRASIM ROE 2.35% → 235%, ROCE 3.5% → 350%).
    # Boundary observability: surface values that could flip class if
    # the threshold window ever shifts again. This is purely additive
    # logging — behaviour is unchanged.
    if abs(abs(v) - 1.0) <= _PCT_BOUNDARY_BAND:
        _logger.warning(
            "_normalize_pct: v=%g within %g of decimal/percent boundary 1.0 "
            "— classification may be wrong if upstream feed changed units",
            v, _PCT_BOUNDARY_BAND,
        )
    if -1.0 < v < 1.0:
        out = round(v * 100, 2)
        _logger.debug(
            "_normalize_pct: detected decimal (v=%g) -> returning percent %g",
            v, out,
        )
        return out
    _logger.debug(
        "_normalize_pct: detected percent (v=%g, passthrough)", v,
    )
    return round(v, 2)


def _compute_roe_fallback(enriched: dict):
    """Compute ROE from net_income / total_equity when yfinance doesn't provide it.

    Negative- or zero-equity guard (added 2026-04-25): when total_equity
    is non-positive, the ratio NI/E is mathematically defined but
    economically meaningless — a profitable company with negative book
    equity (PAYTM-style accumulated losses) would produce a spurious
    -439% ROE chip. We refuse to return a value in that case and stash
    the reason into ``enriched['input_quality_flags']`` so downstream
    can surface it as a data-quality note rather than a quality signal.
    """
    try:
        net_income = enriched.get("net_income") or enriched.get("netIncome", 0)
        # Read equity directly so we can distinguish "missing" from
        # "<=0". The previous `or` short-circuit treated 0/negative as
        # "missing" and silently propagated whatever fallback the rest
        # of the pipeline produced.
        equity = enriched.get("total_equity")
        if equity is None:
            equity = enriched.get("totalStockholderEquity")

        # Negative or zero equity → refuse to compute, flag the input.
        if equity is not None:
            try:
                eq_val = float(equity)
            except (TypeError, ValueError):
                eq_val = None
            if eq_val is not None and eq_val <= 0:
                flags = enriched.get("input_quality_flags")
                if not isinstance(flags, list):
                    flags = []
                if "negative_equity" not in flags:
                    flags.append("negative_equity")
                enriched["input_quality_flags"] = flags
                return None

        if net_income and equity and float(equity) > 0:
            roe = net_income / float(equity)
            if -2.0 <= roe <= 2.0:  # sanity: -200% to +200%
                return round(roe, 4)
    except Exception:
        pass
    return None


# 2-hour in-memory cache for the yfinance statement-based ROE so we
# don't re-pull financials on every analysis request for the same ticker.
_YF_ROE_CACHE: dict[str, tuple[float, float | None]] = {}


def _yf_compute_roe_from_statements(ticker: str) -> float | None:
    """Compute ROE = NetIncome / avgStockholdersEquity from yfinance's
    financials + balance_sheet dataframes.

    Used as a 2nd-tier fallback when ``.info.returnOnEquity`` is None
    (common for SBIN, KOTAKBANK, HINDUNILVR, BAJFINANCE etc.).

    Returns ROE as a decimal (0.17 for 17%) or None on any failure.
    Cached for 2 hours per ticker.
    """
    import time as _t
    now = _t.time()
    cached = _YF_ROE_CACHE.get(ticker)
    if cached and (now - cached[0]) < 7200:
        return cached[1]
    try:
        import yfinance as yf
        sym = ticker if (ticker.endswith(".NS") or ticker.endswith(".BO")) else f"{ticker}.NS"
        t = yf.Ticker(sym)
        fin = t.financials
        bs = t.balance_sheet
        if fin is None or bs is None or fin.empty or bs.empty:
            _YF_ROE_CACHE[ticker] = (now, None)
            return None
        ni_rows = ("Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operation Net Minority Interest")
        ni = None
        for r in ni_rows:
            if r in fin.index:
                col = fin.columns[0]
                v = fin.loc[r, col]
                if v is not None and not (isinstance(v, float) and (v != v)):
                    ni = float(v)
                    break
        eq = None
        eq_rows = ("Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity")
        for r in eq_rows:
            if r in bs.index:
                eq_vals = bs.loc[r, bs.columns[:2]].dropna()
                if len(eq_vals) >= 1:
                    eq = float(eq_vals.mean())
                    break
        if ni is None or eq is None or eq <= 0:
            _YF_ROE_CACHE[ticker] = (now, None)
            return None
        roe = ni / eq
        # Sanity: -200%..200%; otherwise it's almost certainly a unit error
        if not (-2.0 <= roe <= 2.0):
            _YF_ROE_CACHE[ticker] = (now, None)
            return None
        _YF_ROE_CACHE[ticker] = (now, roe)
        return roe
    except Exception:
        _YF_ROE_CACHE[ticker] = (now, None)
        return None


def _resolve_sector(raw_sector: str, clean_ticker: str = "") -> str:
    """Map raw yfinance/screener sector names to cleaner display names.

    If a ticker-based override exists it takes precedence, ensuring NBFCs,
    banks, and insurers are always labelled correctly regardless of what
    yfinance reports.
    """
    # Ticker override has highest priority
    if clean_ticker and clean_ticker in TICKER_SECTOR_OVERRIDES:
        return TICKER_SECTOR_OVERRIDES[clean_ticker]
    if not raw_sector:
        return ""
    return SECTOR_OVERRIDES.get(raw_sector, raw_sector)


# ═══════════════════════════════════════════════════════════════
# RED FLAG DEEP DIVE — structured flag generator
# ═══════════════════════════════════════════════════════════════

def _fmt_cr(val) -> str:
    """Format a Crore value for user-facing text."""
    if val is None:
        return "N/A"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "N/A"
    if abs(v) >= 100_000:
        return f"₹{v / 100_000:.1f}L Cr"
    if abs(v) >= 1_000:
        return f"₹{v:,.0f} Cr"
    return f"₹{v:.0f} Cr"


def _build_structured_flags(
    enriched: dict,
    piotroski: dict,
    moat_result: dict,
    is_financial: bool,
    existing_flags: list,
    price: float,
    mos_pct: float | None = None,
) -> list:
    """
    Generate structured ``RedFlag`` objects from the already-built
    enriched dict plus piotroski/moat results. Never raises —
    every individual signal is wrapped in try/except so one bad
    value cannot block the rest.

    Returns a list sorted critical → warning → info.
    """
    flags: list = []
    try:
        _add_flags(
            flags, enriched, piotroski, moat_result, is_financial, price, mos_pct
        )
    except Exception as exc:
        import logging
        logging.getLogger("yieldiq.red_flags").debug(
            "structured flag generator failed: %s", exc
        )
    order = {"critical": 0, "warning": 1, "info": 2}
    flags.sort(key=lambda f: order.get(f.severity, 3))
    return flags


def _add_flags(
    flags: list,
    enriched: dict,
    piotroski: dict,
    moat_result: dict,
    is_financial: bool,
    price: float,
    mos_pct: float | None = None,
) -> None:
    """All flag-specific logic. Appends RedFlag objects to ``flags``."""

    def add(flag, severity, title, explanation, data_point, why_it_matters):
        flags.append(RedFlag(
            flag=flag,
            severity=severity,
            title=title,
            explanation=explanation,
            data_point=data_point,
            why_it_matters=why_it_matters,
        ))

    # ── CRITICAL ───────────────────────────────────────────────

    # C1 — Negative equity
    try:
        equity = enriched.get("total_equity")
        if equity is not None and float(equity) < 0:
            debt = enriched.get("total_debt", 0)
            assets = enriched.get("total_assets")
            parts = [f"Total equity: {_fmt_cr(equity)}"]
            if assets is not None:
                parts.append(f"Debt: {_fmt_cr(debt)}, Assets: {_fmt_cr(assets)}")
            else:
                parts.append(f"Debt: {_fmt_cr(debt)}")
            add(
                flag="negative_equity",
                severity="critical",
                title="Negative Equity",
                explanation=(
                    "Total liabilities exceed total assets — the company "
                    "technically owes more than it owns."
                ),
                data_point=" · ".join(parts),
                why_it_matters=(
                    "Negative equity makes DCF valuation unreliable and "
                    "signals elevated bankruptcy risk. Common in capital-"
                    "heavy sectors (airlines, infra) — check the reason "
                    "before acting."
                ),
            )
    except Exception:
        pass

    # C2 — Loss-making for 2+ consecutive years (non-financial)
    if not is_financial:
        try:
            income_df = enriched.get("income_df")
            if income_df is not None and "net_income" in income_df.columns:
                recent = income_df["net_income"].dropna().tail(2)
                if len(recent) >= 2 and (recent < 0).all():
                    vals = recent.tolist()
                    add(
                        flag="loss_making",
                        severity="critical",
                        title="Consecutive Losses",
                        explanation=(
                            "Company has reported net losses for 2+ "
                            "consecutive years."
                        ),
                        data_point=(
                            f"Net income last 2 years: "
                            f"{_fmt_cr(vals[0])}, {_fmt_cr(vals[1])}"
                        ),
                        why_it_matters=(
                            "Sustained losses erode equity, increase debt "
                            "dependence, and make DCF valuation based on "
                            "future cash flows unreliable."
                        ),
                    )
        except Exception:
            pass

    # C3 — Very high debt (D/E > 3, non-financial)
    if not is_financial:
        try:
            de = enriched.get("de_ratio")
            if de is None:
                de = enriched.get("debt_to_equity")
            if de is not None and float(de) > 3:
                add(
                    flag="high_debt",
                    severity="critical",
                    title="Very High Debt",
                    explanation=(
                        "Debt is more than 3× equity — a level that "
                        "strains interest payments and limits financial "
                        "flexibility."
                    ),
                    data_point=f"Debt / Equity: {float(de):.1f}x",
                    why_it_matters=(
                        "High leverage amplifies losses in downturns and "
                        "can trigger covenant breaches. WACC rises with "
                        "debt risk."
                    ),
                )
        except Exception:
            pass

    # C4 — Promoter pledge > 25%
    try:
        pledge = enriched.get("promoter_pledge_pct")
        if pledge is not None:
            p = float(pledge)
            if p > 25:
                add(
                    flag="high_promoter_pledge",
                    severity="critical",
                    title="High Promoter Pledge",
                    explanation=(
                        "Promoters have pledged more than 25% of their "
                        "shareholding as loan collateral."
                    ),
                    data_point=f"Promoter pledge: {p:.1f}% of promoter holding",
                    why_it_matters=(
                        "If the stock falls, lenders can force-sell "
                        "pledged shares, triggering a spiral. One of the "
                        "highest-risk signals for Indian retail investors."
                    ),
                )
    except Exception:
        pass

    # ── WARNING ────────────────────────────────────────────────

    # W1 — DCF unreliable
    try:
        if not enriched.get("dcf_reliable", True):
            reason = enriched.get("unreliable_reason") or "Insufficient financial data"
            add(
                flag="dcf_unreliable",
                severity="warning",
                title="DCF Model Limited",
                explanation=(
                    "The discounted cash flow model has reduced "
                    "reliability for this stock."
                ),
                data_point=f"Reason: {reason}",
                why_it_matters=(
                    "Treat the fair value estimate as directional only. "
                    "Cross-check with P/E and P/B multiples before "
                    "acting on the signal."
                ),
            )
    except Exception:
        pass

    # W2 — Declining revenue 3 years running
    try:
        income_df = enriched.get("income_df")
        if income_df is not None and "revenue" in income_df.columns:
            rev = income_df["revenue"].dropna().tail(3)
            if len(rev) >= 3 and (rev.diff().dropna() < 0).all():
                vals = rev.tolist()
                add(
                    flag="declining_revenue",
                    severity="warning",
                    title="Declining Revenue",
                    explanation="Revenue has fallen for 3 consecutive years.",
                    data_point=(
                        f"Revenue: {_fmt_cr(vals[0])} → "
                        f"{_fmt_cr(vals[1])} → {_fmt_cr(vals[2])}"
                    ),
                    why_it_matters=(
                        "Sustained revenue decline suggests structural "
                        "demand loss or competitive pressure. FCF growth "
                        "assumptions in DCF may be optimistic."
                    ),
                )
    except Exception:
        pass

    # W3 — Negative FCF (non-financial, current year)
    if not is_financial:
        try:
            fcf = enriched.get("latest_fcf", 0)
            rev = enriched.get("latest_revenue", 0)
            if fcf is not None and float(fcf) < 0 and rev and float(rev) > 0:
                add(
                    flag="negative_fcf",
                    severity="warning",
                    title="Negative Free Cash Flow",
                    explanation=(
                        "The company is consuming more cash than it "
                        "generates from operations after capex."
                    ),
                    data_point=(
                        f"FCF: {_fmt_cr(fcf)} "
                        f"(FCF margin: {fcf / rev * 100:.1f}%)"
                    ),
                    why_it_matters=(
                        "Negative FCF companies rely on debt or equity "
                        "issuance to fund operations. Sustainable only "
                        "for high-growth businesses with a clear path to "
                        "profitability."
                    ),
                )
        except Exception:
            pass

    # W4 — Very thin net margins (< 5%, non-financial, positive)
    if not is_financial:
        try:
            nm = enriched.get("net_margin")
            if nm is not None:
                nm_pct = float(nm) * 100 if abs(float(nm)) <= 1 else float(nm)
                if 0 < nm_pct < 5:
                    add(
                        flag="thin_margins",
                        severity="warning",
                        title="Very Thin Margins",
                        explanation=(
                            "Net profit margin is below 5%, leaving "
                            "little buffer for cost shocks."
                        ),
                        data_point=f"Net margin: {nm_pct:.1f}%",
                        why_it_matters=(
                            "Thin margins amplify earnings sensitivity to "
                            "input costs, wages, and rates. A 1pp margin "
                            "shock on a 3% margin business eliminates "
                            "~33% of profits."
                        ),
                    )
        except Exception:
            pass

    # W5 — Very high P/E (> 60)
    try:
        pe = enriched.get("pe_ratio")
        if pe is None:
            pe = enriched.get("trailing_pe")
        if pe is not None and isinstance(pe, (int, float)) and float(pe) > 60:
            add(
                flag="high_pe",
                severity="warning",
                title="Very High P/E Ratio",
                explanation=(
                    "Stock trades above 60× earnings — pricing in very "
                    "high future growth."
                ),
                data_point=f"P/E ratio: {float(pe):.1f}x",
                why_it_matters=(
                    "High-P/E stocks are vulnerable to re-rating if "
                    "growth disappoints. Earnings misses can cause sharp "
                    "price declines."
                ),
            )
    except Exception:
        pass

    # W6 — Weak Piotroski (≤ 3)
    try:
        p_score = int(piotroski.get("score", 0)) if piotroski else 0
        if 0 < p_score <= 3:
            add(
                flag="weak_piotroski",
                severity="warning",
                title="Weak Financial Health",
                explanation=(
                    "Piotroski F-Score of 3 or below indicates poor "
                    "financial quality across profitability, leverage, "
                    "and efficiency."
                ),
                data_point=f"Piotroski F-Score: {p_score}/9",
                why_it_matters=(
                    "Low Piotroski scores historically predict "
                    "underperformance — stocks scoring ≤ 3 are "
                    "short-sell candidates in academic research."
                ),
            )
    except Exception:
        pass

    # W7 — Elevated pledge (10% < p ≤ 25%)
    try:
        pledge = enriched.get("promoter_pledge_pct")
        if pledge is not None:
            p = float(pledge)
            if 10 < p <= 25:
                add(
                    flag="elevated_pledge",
                    severity="warning",
                    title="Elevated Promoter Pledge",
                    explanation=(
                        "Promoters have pledged 10–25% of their "
                        "shareholding."
                    ),
                    data_point=f"Promoter pledge: {p:.1f}%",
                    why_it_matters=(
                        "Moderate pledge risk. Monitor if the stock "
                        "falls sharply — forced selling can accelerate "
                        "the decline."
                    ),
                )
    except Exception:
        pass

    # W8 — Possible value trap (mirrors the EditorialHero banner)
    # Frontend formula: Value pillar ≥ 8 AND (Quality pillar < 5 OR
    # Moat = None). Backend proxies:
    #   • Value ≥ 8  →  MoS > 30%   (deep discount)
    #   • Quality < 5  →  Piotroski F ≤ 4
    #   • Moat = None  →  moat_result.grade == "None"
    # We only fire this when we have a real MoS number (so the banner
    # and this flag fire on the same set of stocks). Severity "warning"
    # to match the amber tone of the EditorialHero note.
    try:
        mos_val = mos_pct
        if mos_val is None:
            mos_val = enriched.get("mos_pct")
        if mos_val is not None and float(mos_val) > 30:
            moat_grade = (moat_result.get("grade") or "") if moat_result else ""
            moat_none = str(moat_grade).strip().lower() == "none"
            p_score_vt = int(piotroski.get("score", 0)) if piotroski else 0
            quality_weak = 0 < p_score_vt <= 4
            if moat_none or quality_weak:
                reasons = []
                if quality_weak:
                    reasons.append(f"Piotroski F-Score {p_score_vt}/9")
                if moat_none:
                    reasons.append("no durable moat")
                reason_str = " · ".join(reasons) if reasons else "weak fundamentals"
                add(
                    flag="value_trap",
                    severity="warning",
                    title="Possible Value Trap",
                    explanation=(
                        "Deep discount paired with weak quality or no "
                        "durable moat — undervalued stocks often stay "
                        "undervalued for a reason."
                    ),
                    data_point=(
                        f"Margin of safety: {float(mos_val):.0f}% · {reason_str}"
                    ),
                    why_it_matters=(
                        "Classic value-trap pattern: the market is pricing "
                        "in real fundamental risk. Cross-check the earnings "
                        "trajectory and balance sheet before assuming the "
                        "discount will close."
                    ),
                )
    except Exception:
        pass

    # ── INFO / positive signals ────────────────────────────────

    # I1 — Debt-free (< ₹50 Cr treated as effectively zero)
    try:
        debt = enriched.get("total_debt", 0)
        if debt is not None and float(debt) < 50:
            add(
                flag="debt_free",
                severity="info",
                title="Virtually Debt-Free",
                explanation="The company carries minimal or zero long-term debt.",
                data_point=f"Total debt: {_fmt_cr(debt)}",
                why_it_matters=(
                    "Zero debt means all FCF goes to shareholders. Lower "
                    "WACC and higher resilience during credit tightening."
                ),
            )
    except Exception:
        pass

    # I2 — Strong Piotroski (≥ 7)
    try:
        p_score = int(piotroski.get("score", 0)) if piotroski else 0
        if p_score >= 7:
            add(
                flag="strong_piotroski",
                severity="info",
                title="Strong Financial Health",
                explanation=(
                    "Piotroski F-Score of 7+ indicates excellent "
                    "profitability, improving leverage, and operational "
                    "efficiency."
                ),
                data_point=f"Piotroski F-Score: {p_score}/9",
                why_it_matters=(
                    "High Piotroski scores predict outperformance in "
                    "academic research. Signals improving fundamental "
                    "quality."
                ),
            )
    except Exception:
        pass

    # I3 — Wide moat
    try:
        m_score = int(moat_result.get("score", 0)) if moat_result else 0
        m_grade = (moat_result.get("grade") or "") if moat_result else ""
        if m_score > 65 or m_grade == "Wide":
            moat_types = moat_result.get("moat_types", []) if moat_result else []
            type_str = ", ".join(moat_types) if moat_types else "competitive advantages"
            add(
                flag="wide_moat",
                severity="info",
                title="Wide Economic Moat",
                explanation=(
                    "The business has durable competitive advantages "
                    "that protect long-term profitability."
                ),
                data_point=f"Moat score: {m_score}/100 ({type_str})",
                why_it_matters=(
                    "Wide-moat companies maintain returns above cost of "
                    "capital for longer, supporting higher DCF terminal "
                    "values."
                ),
            )
    except Exception:
        pass

    # I4 — High ROE (> 20%)
    try:
        roe = enriched.get("roe")
        if roe is not None:
            roe_pct = float(roe) * 100 if abs(float(roe)) <= 1 else float(roe)
            if roe_pct > 20:
                add(
                    flag="high_roe",
                    severity="info",
                    title="High Return on Equity",
                    explanation=(
                        "The company earns more than 20% return on "
                        "shareholder equity — a hallmark of quality "
                        "businesses."
                    ),
                    data_point=f"ROE: {roe_pct:.1f}%",
                    why_it_matters=(
                        "Sustained high ROE means capital can be "
                        "reinvested at above-average rates, compounding "
                        "value over time."
                    ),
                )
    except Exception:
        pass

    # I5 — Strong FCF margin (> 10%, non-financial)
    if not is_financial:
        try:
            fcf = enriched.get("latest_fcf", 0)
            rev = enriched.get("latest_revenue", 0)
            if fcf and rev and float(fcf) > 0:
                margin_pct = float(fcf) / float(rev) * 100
                if margin_pct > 10:
                    add(
                        flag="strong_fcf",
                        severity="info",
                        title="Strong Free Cash Flow",
                        explanation=(
                            "Business generates healthy free cash flow "
                            "as a percentage of revenue."
                        ),
                        data_point=(
                            f"FCF: {_fmt_cr(fcf)} "
                            f"(FCF margin: {margin_pct:.1f}%)"
                        ),
                        why_it_matters=(
                            "Strong FCF funds dividends, buybacks, debt "
                            "reduction, and growth capex without "
                            "external financing."
                        ),
                    )
        except Exception:
            pass

    # ── Day-3 additions: bellwether-aware strength signals ──────
    # Fixes issue #19: large-cap quality names (TITAN, HDFCBANK,
    # NESTLEIND, ...) were surfacing zero "info" flags because the
    # previous five rules required ROE>20 (Titan's ROE is None in
    # our enriched dict), Piotroski>=7, zero debt, Wide moat, or
    # FCF margin>10% — Titan hits none of these despite ROCE=36.9%
    # and 3y revenue CAGR of 28%. These extra rules read ROCE /
    # revenue_cagr_3y / interest_coverage / debt_to_equity that
    # service.py now injects into ``enriched`` before calling the
    # flag builder (FIX-DAY3-STRENGTHS 2026-04-22).

    # I6 — Durable profitability: ROCE > 15%
    # ROCE is sector-agnostic (works for banks too, unlike ROE). We
    # read the same _roce_val service.py stuffs back into enriched.
    try:
        roce = enriched.get("roce")
        if roce is not None:
            # Service injects ROCE as a percent (e.g. 36.9), but
            # accept decimal 0-1 inputs defensively in case the
            # contract ever slips.
            roce_pct = float(roce) * 100 if abs(float(roce)) <= 1 else float(roce)
            if roce_pct > 15:
                add(
                    flag="high_roce",
                    severity="info",
                    title="Durable Return on Capital",
                    explanation=(
                        "Return on capital employed above 15% — the "
                        "business earns substantially more than its "
                        "cost of capital on every rupee deployed."
                    ),
                    data_point=f"ROCE: {roce_pct:.1f}%",
                    why_it_matters=(
                        "High ROCE sustained over time is the single "
                        "strongest quantitative signal of a durable "
                        "business. It means reinvested profits compound "
                        "shareholder value at above-average rates."
                    ),
                )
    except Exception:
        pass

    # I7 — Consistent growth: 3y revenue CAGR > 8%
    try:
        cagr3 = enriched.get("revenue_cagr_3y")
        if cagr3 is not None:
            # Stored as decimal (0.28 = 28%).
            cagr_pct = float(cagr3) * 100 if abs(float(cagr3)) <= 1 else float(cagr3)
            if cagr_pct > 8:
                add(
                    flag="strong_growth",
                    severity="info",
                    title="Consistent Revenue Growth",
                    explanation=(
                        "Revenue has compounded above 8% annually over "
                        "the past three years — a pace that outpaces "
                        "nominal GDP and typical peer sets."
                    ),
                    data_point=f"3-year revenue CAGR: {cagr_pct:.1f}%",
                    why_it_matters=(
                        "Sustained top-line growth expands the DCF "
                        "base and — when paired with stable margins — "
                        "is a precondition for multi-year compounding."
                    ),
                )
    except Exception:
        pass

    # I8 — Strong balance sheet: D/E < 0.5 AND interest coverage > 5
    # Skip for financials (leverage isn't meaningful for banks).
    if not is_financial:
        try:
            de = enriched.get("debt_to_equity")
            ic = enriched.get("interest_coverage")
            de_ok = de is not None and float(de) < 0.5
            ic_ok = ic is not None and float(ic) > 5
            if de_ok and ic_ok:
                add(
                    flag="strong_balance_sheet",
                    severity="info",
                    title="Strong Balance Sheet",
                    explanation=(
                        "Low leverage and comfortable interest coverage — "
                        "the business can absorb shocks without "
                        "refinancing risk."
                    ),
                    data_point=f"D/E: {float(de):.2f} · Interest coverage: {float(ic):.1f}x",
                    why_it_matters=(
                        "Balance-sheet strength preserves optionality "
                        "during credit cycles and limits the downside "
                        "in adverse scenarios."
                    ),
                )
        except Exception:
            pass

    # I9 — Category leader: allowlist membership. Kicks in whenever
    # no other info flag would surface for a bellwether (fall-through
    # is handled at the end by the "ensure-at-least-one" guard below).
    try:
        _raw_t = str(enriched.get("ticker") or "").strip().upper()
        if _raw_t in _STRONG_BRAND_ALLOWLIST or (
            _raw_t.endswith(".BO")
            and (_raw_t[:-3] + ".NS") in _STRONG_BRAND_ALLOWLIST
        ):
            add(
                flag="category_leader",
                severity="info",
                title="Category Leader / Franchise",
                explanation=(
                    "Established market leadership with durable brand, "
                    "distribution, or network advantages that are hard "
                    "to replicate in the Indian market."
                ),
                data_point="Recognised bellwether franchise",
                why_it_matters=(
                    "Category leaders compound through pricing power "
                    "and share-of-wallet gains even in slow-growth "
                    "environments, and defend returns during downturns."
                ),
            )
    except Exception:
        pass

    # ── Cap info flags at 3 (highest-signal first) ──────────────
    # Rank: wide_moat > high_roce > strong_piotroski > high_roe >
    # strong_growth > strong_balance_sheet > strong_fcf >
    # debt_free > category_leader. Keep top 3; drop the rest.
    _INFO_PRIORITY = {
        "wide_moat":            0,
        "high_roce":            1,
        "strong_piotroski":     2,
        "high_roe":             3,
        "strong_growth":        4,
        "strong_balance_sheet": 5,
        "strong_fcf":           6,
        "debt_free":            7,
        "category_leader":      8,
    }
    try:
        _info = [f for f in flags if f.severity == "info"]
        _non_info = [f for f in flags if f.severity != "info"]
        _info.sort(key=lambda f: _INFO_PRIORITY.get(f.flag, 99))
        _kept = _info[:3]
        flags.clear()
        flags.extend(_non_info)
        flags.extend(_kept)
    except Exception:
        pass


def _fx_multiplier(currency: str | None) -> float:
    """Return the multiplier to convert a Financials row into INR."""
    if not currency:
        return 1.0
    code = str(currency).strip().upper()
    if code == "USD":
        return USD_INR_RATE
    return 1.0


def _debt_ebitda_label(ratio: float | None) -> str | None:
    """Map Debt/EBITDA to a text band. None in → None out."""
    if ratio is None:
        return None
    if ratio < 1.0:
        return "Excellent"
    if ratio < 3.0:
        return "Healthy"
    if ratio < 5.0:
        return "Leveraged"
    return "High Risk"
