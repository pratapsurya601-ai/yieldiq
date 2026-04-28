# backend/models/responses.py
# Pydantic response models — the API contract for the Next.js frontend.
from __future__ import annotations
from pydantic import BaseModel, Field, field_serializer
from typing import Optional, Literal


# ── Shared serialization helpers ──────────────────────────────
# Lock the float precision of monetary / scenario fields at the JSON
# boundary. Without these, the authed `/api/v1/analysis/{ticker}`
# endpoint streams raw 64-bit floats (e.g. bear_case=1209.8671239771572)
# while the public `/api/v1/public/analysis/{ticker}` endpoint passes
# values through `_extract_analysis_summary` which `round(x, 2)`s every
# scalar. The mismatch produces canary "public-vs-authed precision
# drift" violations like the DRREDDY 0.017% delta flagged in PR #70.
# Fix: serialize the canonical model with explicit precision so both
# endpoints agree byte-for-byte.

def _round2(v: float | None) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return v


# ── Core analysis response ────────────────────────────────────

class CompanyInfo(BaseModel):
    ticker: str
    company_name: str
    exchange: str = ""
    sector: str = ""
    industry: str = ""
    country: str = ""
    currency: str = "INR"
    logo_url: Optional[str] = None
    description: Optional[str] = None
    market_cap: float = 0
    employees: Optional[int] = None


class PeerCapDetails(BaseModel):
    """Audit trail for the peer-multiple sanity ceiling.

    Populated only when `ValuationOutput.fair_value_source ==
    "peer_capped"`. `uncapped_fv` is the raw DCF (or P/B financial)
    FV the model would have surfaced; `ceiling_fv` is what the
    frontend displays — equal to 1.5 × `peer_fv`.

    `method` documents which peer multiple drove the ceiling:
      * "min(pe,ev_ebitda)" — both available, lower-of selected
      * "pe_only" / "ev_ebitda_only" — only one usable
      * "pb"                — bank / financial-services path
    """
    uncapped_fv: float
    peer_fv: float
    ceiling_fv: float
    method: Literal["min(pe,ev_ebitda)", "pe_only", "ev_ebitda_only", "pb"]
    n_peers: int
    median_pe: Optional[float] = None
    median_ev_ebitda: Optional[float] = None
    median_pb: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None


class ValuationOutput(BaseModel):
    fair_value: float
    current_price: float
    margin_of_safety: float
    verdict: Literal["undervalued", "fairly_valued", "overvalued", "avoid", "data_limited", "unavailable"]
    bear_case: float = 0
    base_case: float = 0
    bull_case: float = 0
    wacc: float = 0
    terminal_growth: float = 0
    fcf_growth_rate: float = 0
    confidence_score: int = 50
    wacc_industry_min: float = 0
    wacc_industry_max: float = 0
    fcf_growth_historical_avg: float = 0
    tv_pct_of_ev: float = 0
    dcf_reliable: bool = True
    reliability_score: int = 100
    pv_fcfs: float = 0
    pv_terminal: float = 0
    enterprise_value: float = 0
    equity_value: float = 0
    margin_of_safety_display: float = 0
    mos_is_extreme: bool = False
    mos_extreme_note: str | None = None
    fcf_data_source: str = ""  # "ttm", "annual", or "yfinance"
    valuation_model: str = "dcf"  # "dcf" or "pb_ratio" for financials
    # Set when the router clamps an out-of-bounds FV (FV outside
    # [0.1×price, 3×price] or |MoS| >= 95%). When True, the frontend
    # should render the FV with a "data quality" caveat rather than
    # treating it as a clean signal. Paired with an
    # AnalyticalNoteOutput(kind="data_quality") in `analytical_notes`.
    data_limited: bool = False
    # ── Freshness (feat/freshness-stamps, 2026-04-24) ─────────
    # ISO-8601 timestamp marking when the displayed price was pulled
    # from the upstream source. Null on legacy cached payloads /
    # degraded fallbacks. Frontend renders via
    # <FreshnessStamp prefix="Delayed" /> — never "Live" (SEBI).
    current_price_as_of: Optional[str] = None

    # ── Peer-multiple sanity ceiling (feat/peer-cap, 2026-04-27) ─
    # When the DCF FV exceeds 1.5× peer-median multiples, the
    # displayed `fair_value` is capped at 1.5× peer-implied and
    # `fair_value_source` flips from "dcf" to "peer_capped".
    # `peer_cap_details` carries the audit trail so the frontend
    # can render an explanatory tooltip without re-deriving any of
    # it. Both fields are purely additive — pre-PR clients ignore
    # unknown fields and continue to render `fair_value` as before.
    fair_value_source: Literal["dcf", "peer_capped"] = "dcf"
    peer_cap_details: Optional[PeerCapDetails] = None

    # ── JSON precision lock (DRREDDY drift fix, 2026-04-25) ────
    # Round monetary / scenario floats at serialization so the authed
    # endpoint (returns this Pydantic model directly) matches the
    # public endpoint (which already round(x, 2)s in
    # `_extract_analysis_summary`). Internal arithmetic still uses
    # full precision; only JSON output is rounded.
    @field_serializer(
        "fair_value",
        "current_price",
        "bear_case",
        "base_case",
        "bull_case",
        "pv_fcfs",
        "pv_terminal",
        "enterprise_value",
        "equity_value",
    )
    def _round_money(self, v: float) -> float:
        return _round2(v)

    @field_serializer("margin_of_safety", "margin_of_safety_display")
    def _round_pct(self, v: float) -> float:
        # MoS is rendered to 1 decimal everywhere on the frontend.
        if v is None:
            return v
        try:
            return round(float(v), 1)
        except (TypeError, ValueError):
            return v


class QualityOutput(BaseModel):
    yieldiq_score: int = 0
    grade: str = "C"
    piotroski_score: int = 0
    piotroski_grade: str = ""
    earnings_quality_grade: str = ""
    earnings_quality_score: float = 0
    # "Moderate" added 2026-04-23: PR #36 introduced the
    # STRONG_BRAND_ALLOWLIST floor that lifts bellwether scores to ≥60
    # (the Narrow/Moderate band boundary in _moat_label_from_score),
    # but the Literal here wasn't updated. Every floored allowlist
    # ticker (TITAN/RELIANCE/HDFCBANK) then raised
    # "1 validation error for QualityOutput" → 503 on prod.
    # See Railway logs 2026-04-23 09:04 UTC.
    moat: Literal["Wide", "Moderate", "Narrow", "None", "N/A (Financial)"] = "None"
    moat_score: float = 0
    momentum_score: float = 0
    momentum_grade: str = ""
    fundamental_score: float = 0
    fundamental_grade: str = ""
    roe: Optional[float] = None
    de_ratio: Optional[float] = None
    # Extended ratios — all Optional; None renders as "—" in frontend
    roce: Optional[float] = None                    # ebit / total_assets × 100
    debt_ebitda: Optional[float] = None             # total_debt / ebitda
    debt_ebitda_label: Optional[str] = None         # Excellent / Healthy / Leveraged / High Risk
    interest_coverage: Optional[float] = None       # ebit / interest_expense
    enterprise_value: Optional[float] = None        # market_cap + debt − cash (in Cr)
    # Phase 2.1 additions — backfill when data available, None otherwise
    current_ratio: Optional[float] = None           # current_assets / current_liabilities
    asset_turnover: Optional[float] = None          # revenue / total_assets
    revenue_cagr_3y: Optional[float] = None         # DECIMAL (0.124 = 12.4%)
    revenue_cagr_5y: Optional[float] = None         # DECIMAL
    # Shareholding breakdown from ShareholdingPattern table
    promoter_pct: Optional[float] = None
    promoter_pledge_pct: Optional[float] = None
    fii_pct: Optional[float] = None
    dii_pct: Optional[float] = None
    public_pct: Optional[float] = None
    # ── Bank-native metrics (feat/bank-prism-metrics 2026-04-21) ──
    # All optional; set for bank/NBFC tickers, None everywhere else.
    # See docs/bank_data_availability.md for the data-coverage matrix.
    # Frontend can use `is_bank` as the render switch without
    # re-deriving sector.
    is_bank: bool = False
    roa: Optional[float] = None                   # percent, net_income / total_assets × 100
    cost_to_income: Optional[float] = None        # percent, opex / total_income × 100
    advances_yoy: Optional[float] = None          # percent, total_assets YoY (proxy)
    deposits_yoy: Optional[float] = None          # percent, total_liabilities YoY (proxy)
    revenue_yoy_bank: Optional[float] = None      # percent
    pat_yoy_bank: Optional[float] = None          # percent
    nim: Optional[float] = None                   # percent, TODO: XBRL Sch A/B
    car: Optional[float] = None                   # percent, TODO: XBRL Sch XI
    nnpa: Optional[float] = None                  # percent, TODO: XBRL Sch XVIII
    casa: Optional[float] = None                  # percent, TODO: XBRL Sch V
    # ── Freshness (feat/freshness-stamps, 2026-04-24) ─────────
    # period_end (ISO YYYY-MM-DD) of the most recent filing feeding
    # the ratios on this card. Null when the service couldn't derive
    # it (yfinance-only fallback). Surfaced as
    # "Latest filing: Mar 2024" via <FreshnessStamp />.
    latest_filing_period_end: Optional[str] = None


class BulkDealItem(BaseModel):
    date: str = ""
    client: str = ""
    deal_type: str = ""  # BUY / SELL
    qty_lakh: float = 0
    price: float = 0
    category: str = ""  # bulk / block


class DividendFYItem(BaseModel):
    fy: str                          # e.g. "FY2025"
    total_per_share: float
    payment_count: int


class DividendData(BaseModel):
    has_dividends: bool = False
    ticker: str = ""
    message: str = ""
    current_yield_pct: Optional[float] = None
    payout_ratio_pct: Optional[float] = None
    five_yr_avg_yield: Optional[float] = None
    dividend_rate_per_share: Optional[float] = None
    last_dividend_value: Optional[float] = None
    next_ex_date: Optional[str] = None
    next_ex_days: Optional[int] = None
    consecutive_years: int = 0
    fy_history: list[DividendFYItem] = []
    coverage_ratio: Optional[float] = None
    sustainability: str = "moderate"
    sustainability_reason: str = ""
    # ── Freshness (feat/freshness-stamps, 2026-04-24) ─────────
    # ISO date (YYYY-MM-DD) of the most recent ex-dividend event in
    # corporate_actions. Surfaced as "Last dividend: Jan 16, 2025"
    # under the Dividend Tracker card. None when has_dividends is False.
    last_ex_date: Optional[str] = None


class RedFlag(BaseModel):
    """Structured risk/strength signal for the deep-dive UI."""
    flag: str                    # short machine key, e.g. "negative_equity"
    severity: str                # "critical" | "warning" | "info"
    title: str                   # display title, e.g. "Negative Equity"
    explanation: str             # 1-sentence plain English
    data_point: str              # actual number / value behind the flag
    why_it_matters: str          # impact on valuation / decision


class InsightCards(BaseModel):
    patience_months: Optional[int] = None
    red_flag_count: int = 0
    red_flags: list[str] = []
    red_flags_structured: list[RedFlag] = []
    dividend: Optional[DividendData] = None
    earnings_date: Optional[str] = None
    earnings_est_eps: Optional[float] = None
    earnings_days_until: Optional[int] = None
    wall_street_avg_target: Optional[float] = None
    wall_street_target_count: Optional[int] = None
    insider_net_sentiment: Optional[str] = None
    market_expectations_growth: Optional[float] = None
    fcf_yield: Optional[float] = None
    ev_ebitda: Optional[float] = None
    reverse_dcf_implied_growth: Optional[float] = None
    bulk_deals: list[BulkDealItem] = []
    # ── Freshness (feat/freshness-stamps, 2026-04-24) ─────────
    # ISO timestamp of analyst consensus last refresh. Free-tier
    # Finnhub/yfinance fallback don't surface it; analysis service
    # stamps with the compute time whenever target data is present.
    analyst_target_as_of: Optional[str] = None


# ── Reverse DCF detailed response ─────────────────────────────

class ReverseDCFScenario(BaseModel):
    growth_rate: float
    implied_iv: float
    mos: float


class ReverseDCFResponse(BaseModel):
    ticker: str
    current_price: float
    implied_growth: Optional[float] = None
    converged: bool = False
    iv_at_implied: float = 0.0
    historical_growth: Optional[float] = None
    long_run_gdp: float = 0.025
    wacc: float = 0.12
    terminal_g: float = 0.03
    verdict_level: str = ""  # conservative, reasonable, aggressive, very aggressive, unrealistic
    verdict_text: str = ""
    verdict_colour: str = ""  # green, amber, red
    summary: str = ""
    scenarios: dict = {}  # {label: ReverseDCFScenario}
    years_to_justify: Optional[int] = None
    payback_at_implied: Optional[int] = None
    fcf_yield: Optional[float] = None
    price_to_fcf: Optional[float] = None
    excess_growth: Optional[float] = None
    growth_premium: Optional[float] = None


class ScenarioCase(BaseModel):
    iv: float = 0
    mos_pct: float = 0
    growth: float = 0
    wacc: float = 0
    term_g: float = 0


class ScenariosOutput(BaseModel):
    bear: ScenarioCase = ScenarioCase()
    base: ScenarioCase = ScenarioCase()
    bull: ScenarioCase = ScenarioCase()


class PriceLevels(BaseModel):
    entry_signal: str = ""
    discount_zone: Optional[float] = None
    model_estimate: Optional[float] = None
    downside_range: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    holding_period: Optional[str] = None


class AnalyticalNoteOutput(BaseModel):
    """Contextual note emitted by backend/services/analytical_notes.py.

    1–5 of these are attached to every AnalysisResponse as
    `analytical_notes`. They flag structural DCF limitations for
    specific stock archetypes (premium brand, conglomerate,
    regulated utility, cyclical trough, post-merger, high-P/E
    growth, ADR) via pattern-matched rules — no hardcoded ticker
    maintenance beyond the tiny conglomerate allowlist.
    """
    kind: Literal[
        "premium_brand", "conglomerate", "cyclical_trough",
        "post_merger", "regulated_utility", "adr_usd_report",
        "high_pe_growth", "data_quality",
    ]
    severity: Literal["info", "caution"] = "info"
    title: str
    body: str


class AnalysisResponse(BaseModel):
    ticker: str
    company: CompanyInfo
    valuation: ValuationOutput
    quality: QualityOutput
    insights: InsightCards
    scenarios: ScenariosOutput = ScenariosOutput()
    price_levels: PriceLevels = PriceLevels()
    ai_summary: Optional[str] = None
    # Multilingual AI summary translations (Phase 0 — review-gated).
    # Populated only when the MULTILINGUAL_SUMMARIES_ENABLED feature
    # flag is on AND a native-speaker review has signed off on the
    # prompt set. Keyed by ISO 639-1 code: "hi", "ta", "mr". The
    # English summary remains the authoritative source in
    # ``ai_summary``. Stays ``None`` for backward compatibility with
    # clients that have not adopted the multilingual UI.
    ai_summary_translations: Optional[dict[str, str]] = None
    data_confidence: Literal["high", "medium", "low", "unusable"] = "medium"
    data_issues: list[str] = []
    # Contextual disclaimers emitted by
    # backend/services/analytical_notes.py (PR #69). Always
    # present; empty list when no rule fires. Purely additive —
    # does NOT influence scoring or fair value.
    analytical_notes: list[AnalyticalNoteOutput] = []
    cached: bool = False
    timestamp: str = ""
    # Snapshot of the exact inputs that produced `valuation.fair_value`
    # at compute time. Persisted into analysis_cache.payload so warm
    # cache hits can be reproduced/audited deterministically. Optional
    # because pre-v35 cached payloads may not have it (back-compat).
    # See backend/services/validators/stability.py for the structural
    # check that fires when this is missing on a fresh compute.
    computation_inputs: Optional[dict] = None


# ── Screener response ─────────────────────────────────────────

class ScreenerStock(BaseModel):
    ticker: str
    company_name: str = ""
    score: int = 0
    fair_value: float = 0
    current_price: float = 0
    margin_of_safety: float = 0
    verdict: str = ""
    moat: str = ""
    confidence: str = ""
    sector: str = ""


class ScreenerResponse(BaseModel):
    results: list[ScreenerStock] = []
    total: int = 0
    page: int = 1
    page_size: int = 20
    filter_applied: dict = {}


# ── Portfolio health response ─────────────────────────────────

class PortfolioHealthResponse(BaseModel):
    score: int = 0
    grade: str = "F"
    summary: str = ""
    issues: list[str] = []
    strengths: list[str] = []
    overvalued_count: int = 0
    undervalued_count: int = 0
    danger_positions: list[str] = []
    concentration_warning: Optional[str] = None


class HoldingResponse(BaseModel):
    ticker: str
    company_name: str = ""
    entry_price: float = 0
    current_price: float = 0
    iv: float = 0
    mos_pct: float = 0
    signal: str = ""
    sector: str = ""
    notes: str = ""
    saved_at: str = ""
    account_label: str = "default"
    quantity: float = 0


class WatchlistItemResponse(BaseModel):
    ticker: str
    company_name: str = ""
    added_price: float = 0
    target_price: float = 0
    alert_mos_threshold: float = 0
    notes: str = ""
    added_at: str = ""


# ── Market data response ──────────────────────────────────────

class MarketIndex(BaseModel):
    name: str
    price: float = 0
    change_pct: float = 0


class MarketPulseResponse(BaseModel):
    indices: list[MarketIndex] = []
    fear_greed_index: Optional[int] = None
    fear_greed_label: Optional[str] = None
    timestamp: str = ""

    # Macro extension — all optional, populated only when
    # ?include_macro=true is passed.
    fii_net_cr: Optional[float] = None
    dii_net_cr: Optional[float] = None
    fii_date: Optional[str] = None
    fii_stale: bool = False
    usd_inr: Optional[float] = None
    gold_usd: Optional[float] = None
    silver_usd: Optional[float] = None
    crude_usd: Optional[float] = None  # Deprecated — superseded by silver_usd
    risk_free_pct: Optional[float] = None
    nifty_midcap_price: Optional[float] = None
    nifty_midcap_change_pct: Optional[float] = None
    ai_summary: Optional[str] = None


class SectorOverviewItem(BaseModel):
    name: str
    avg_score: float = 0
    pct_undervalued: float = 0
    trend: str = ""


# ── Alert response ────────────────────────────────────────────

class AlertResponse(BaseModel):
    id: int = 0
    ticker: str = ""
    alert_type: str = ""
    target_price: float = 0
    created_at: str = ""
    is_active: bool = True


# ── Auth responses ────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str = ""
    email: str = ""
    tier: Literal["free", "starter", "pro", "analyst"] = "free"
    analyses_today: int = 0
    analysis_limit: int = 5
    # Editable display name (PR #72) — sourced from Supabase
    # auth.users.raw_user_meta_data. Null when user has never set one
    # (frontend falls back to nameFromEmail() for the greeting).
    display_name: Optional[str] = None
    # Remaining edits in the lifetime cap (default 3 for new users).
    display_name_edits_remaining: int = 3
    # Feature flags resolved server-side for this user (see
    # backend/services/feature_flags.py). Purely additive — pre-PR
    # frontend clients ignore unknown fields; post-PR clients gain the
    # ability to branch on staged-rollout / Pro-only beta features
    # without a separate round-trip per flag.
    feature_flags: dict[str, bool] = Field(default_factory=dict)


class UserResponse(BaseModel):
    user_id: str = ""
    email: str = ""
    tier: Literal["free", "starter", "pro", "analyst"] = "free"
    analyses_today: int = 0
    analysis_limit: int = 5
    created_at: str = ""
    display_name: Optional[str] = None
    display_name_edits_remaining: int = 3
    # See TokenResponse.feature_flags above.
    feature_flags: dict[str, bool] = Field(default_factory=dict)


# ── Generic responses ─────────────────────────────────────────

class SuccessResponse(BaseModel):
    ok: bool = True
    message: str = ""


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str = ""


# ── Historical financials (public endpoint) ───────────────────

class HistoricalFinancialPeriod(BaseModel):
    period_end: str
    period_type: str
    revenue: Optional[float] = None
    ebitda: Optional[float] = None
    ebit: Optional[float] = None
    pat: Optional[float] = None
    eps_diluted: Optional[float] = None
    cfo: Optional[float] = None
    capex: Optional[float] = None
    free_cash_flow: Optional[float] = None
    total_assets: Optional[float] = None
    total_equity: Optional[float] = None
    total_debt: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    shares_outstanding: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    debt_to_equity: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    fcf_margin: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    pat_growth_yoy: Optional[float] = None


class HistoricalFinancialsResponse(BaseModel):
    ticker: str
    currency: str = "INR"
    periods: list[HistoricalFinancialPeriod] = []


# ── Ratio history (public endpoint) ───────────────────────────

class RatioHistoryPeriod(BaseModel):
    period_end: str
    period_type: str
    roe: Optional[float] = None
    roce: Optional[float] = None
    roa: Optional[float] = None
    de_ratio: Optional[float] = None
    debt_ebitda: Optional[float] = None
    interest_cov: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    fcf_margin: Optional[float] = None
    revenue_yoy: Optional[float] = None
    ebitda_yoy: Optional[float] = None
    pat_yoy: Optional[float] = None
    fcf_yoy: Optional[float] = None
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None
    dividend_yield: Optional[float] = None
    market_cap_cr: Optional[float] = None
    current_ratio: Optional[float] = None
    asset_turnover: Optional[float] = None


class RatioHistoryResponse(BaseModel):
    ticker: str
    periods: list[RatioHistoryPeriod] = []


# ── Peer groups (public endpoint) ─────────────────────────────

class PeerInfo(BaseModel):
    peer_ticker: str
    rank: int
    sector: Optional[str] = None
    sub_sector: Optional[str] = None
    mcap_ratio: Optional[float] = None
    # Selected fields from peer's latest analysis cache / ratio history
    company_name: Optional[str] = None
    fair_value: Optional[float] = None
    current_price: Optional[float] = None
    margin_of_safety: Optional[float] = None
    verdict: Optional[str] = None
    score: Optional[float] = None
    moat: Optional[str] = None
    roe: Optional[float] = None
    pe_ratio: Optional[float] = None


class PeersResponse(BaseModel):
    ticker: str
    peers: list[PeerInfo] = []


# ── IPO calendar (public endpoint, curated stub for now) ──────

class IPOEntry(BaseModel):
    symbol: str
    company_name: str
    issue_size_cr: Optional[float] = None
    price_band_min: Optional[float] = None
    price_band_max: Optional[float] = None
    ipo_open_date: Optional[str] = None      # ISO date
    ipo_close_date: Optional[str] = None     # ISO date
    listing_date: Optional[str] = None       # ISO date, None if not yet listed
    status: Literal["upcoming", "recent"] = "upcoming"
    exchange: str = "NSE"
    sector: Optional[str] = None


class IPOListResponse(BaseModel):
    status_filter: Literal["upcoming", "recent", "all"] = "upcoming"
    total: int = 0
    ipos: list[IPOEntry] = []
    source: str = "curated_stub"  # placeholder marker until ingestion job exists


# ── Segment revenue (public endpoint) ─────────────────────────

class SegmentPoint(BaseModel):
    period_end: Optional[str] = None         # ISO date
    revenue_cr: float = 0


class SegmentSeries(BaseModel):
    name: str
    points: list[SegmentPoint] = []


class SegmentRevenueResponse(BaseModel):
    ticker: str
    display_ticker: str
    years: int = 5
    segments: list[SegmentSeries] = []


# ── Dividend history (public endpoint) ────────────────────────


class DividendEvent(BaseModel):
    """One ex-dividend event from the corporate_actions feed."""
    ex_date: str                       # ISO YYYY-MM-DD
    amount: Optional[float] = None     # ₹ per share, parsed from action text


class DividendHistoryResponse(BaseModel):
    ticker: str
    count: int = 0
    total_paid_5y: Optional[float] = None    # sum of `amount` within last 5Y
    dividends: list[DividendEvent] = []


# ── Reverse-DCF (public endpoint, additive) ───────────────────
# This is the NEW response shape backing
# /api/v1/public/reverse-dcf/{ticker}. It is intentionally distinct
# from the existing `ReverseDCFResponse` (used by the authed
# /api/v1/analysis/{ticker}/reverse-dcf path) — that older shape
# captures growth-only verdicts; this one carries both the
# implied-growth and implied-margin axes plus the iso-FV curve.

class IsoFvPoint(BaseModel):
    """One (growth, margin) point on the iso-fair-value curve."""
    growth: float                       # FCF growth, decimal (0.18 = 18%)
    margin: float                       # FCF margin, decimal


class ReverseDcfInputs(BaseModel):
    """Snapshot of the exact inputs used to solve the reverse DCF."""
    current_price: float
    wacc: float
    terminal_g: float
    current_fcf: float
    current_margin: float
    current_revenue: float
    consensus_growth: float
    total_debt: float = 0.0
    total_cash: float = 0.0
    shares: float = 0.0
    years: int = 10


class ReverseDcfResponse(BaseModel):
    """Public reverse-DCF response — what the market is pricing in.

    Fields:
      - implied_growth_pct: solve for FCF growth that makes DCF == price
      - implied_margin_pct: solve for FCF margin at consensus growth
      - iso_fv_curve: 3 (growth, margin) points along the iso-FV curve
      - current_market_implied_summary: plain-English narration
      - sanity_check_lines: optional comparisons vs trailing actuals
      - converged: True iff both binary searches hit tolerance
      - inputs: ReverseDcfInputs snapshot
    """
    ticker: str
    implied_growth_pct: float
    implied_margin_pct: float
    iso_fv_curve: list[IsoFvPoint] = []
    current_market_implied_summary: str = ""
    sanity_check_lines: list[str] = []
    converged: bool = False
    inputs: ReverseDcfInputs
