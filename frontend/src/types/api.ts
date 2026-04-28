// types/api.ts — mirrors backend/models/responses.py exactly

export type Verdict = "undervalued" | "fairly_valued" | "overvalued" | "avoid" | "data_limited" | "unavailable"
export type Grade = "A" | "B" | "C" | "D" | "F"
export type Tier = "free" | "starter" | "pro" | "analyst"
export type Confidence = "high" | "medium" | "low" | "unusable"
// Mirrors backend QualityOutput.moat Literal at backend/models/responses.py:67.
// "Moderate" is emitted for allowlisted bellwethers floored by PR #36 / PR #41
// (score >=60). "N/A (Financial)" is emitted for banks/NBFCs where the moat
// engine returns a sector-specific sentinel. Drift between this union and the
// backend Literal silently breaks the Vercel build via InsightCards.tsx moat
// card comparisons — keep them synchronized.
export type MoatGrade = "Wide" | "Moderate" | "Narrow" | "None" | "N/A (Financial)"

export interface CompanyInfo {
  ticker: string
  company_name: string
  exchange: string
  sector: string
  industry: string
  country: string
  currency: string
  logo_url: string | null
  description: string | null
  market_cap: number
  employees: number | null
}

export interface ValuationOutput {
  fair_value: number
  current_price: number
  margin_of_safety: number
  verdict: Verdict
  bear_case: number
  base_case: number
  bull_case: number
  wacc: number
  terminal_growth: number
  fcf_growth_rate: number
  confidence_score: number
  wacc_industry_min: number
  wacc_industry_max: number
  fcf_growth_historical_avg: number
  tv_pct_of_ev: number
  dcf_reliable: boolean
  reliability_score: number
  pv_fcfs: number
  pv_terminal: number
  enterprise_value: number
  equity_value: number
  margin_of_safety_display: number
  mos_is_extreme: boolean
  mos_extreme_note: string | null
  fcf_data_source: string  // "ttm", "annual", or "yfinance"
  // feat/freshness-stamps — ISO timestamp of last price pull. Null on
  // legacy/degraded payloads. Render via <FreshnessStamp prefix="Delayed" />;
  // never "Live" (SEBI discipline, prices are always delayed).
  current_price_as_of?: string | null
}

export interface QualityOutput {
  yieldiq_score: number
  grade: string
  piotroski_score: number
  piotroski_grade: string
  earnings_quality_grade: string
  earnings_quality_score: number
  moat: MoatGrade
  moat_score: number
  momentum_score: number
  momentum_grade: string
  fundamental_score: number
  fundamental_grade: string
  roe: number | null
  de_ratio: number | null
  roce?: number | null
  debt_ebitda?: number | null
  debt_ebitda_label?: string | null
  interest_coverage?: number | null
  enterprise_value?: number | null
  // Phase 2.1 additions — backfilled by backend (see backend/models/responses.py
  // QualityOutput). Added to the frontend type on 2026-04-22 to wire up the
  // three ratio cards that were already coming down the wire but silently
  // dropped by the render list.
  current_ratio?: number | null     // ratio, current_assets / current_liabilities
  asset_turnover?: number | null    // ratio, revenue / total_assets
  revenue_cagr_3y?: number | null   // DECIMAL (0.124 = 12.4%) — multiply by 100 to display
  revenue_cagr_5y?: number | null   // DECIMAL
  promoter_pct?: number | null
  promoter_pledge_pct?: number | null
  fii_pct?: number | null
  dii_pct?: number | null
  public_pct?: number | null
  // Bank-native metrics — present for banks/NBFCs, null elsewhere.
  // See docs/bank_data_availability.md for the coverage matrix.
  is_bank?: boolean
  roa?: number | null              // percent
  cost_to_income?: number | null   // percent
  advances_yoy?: number | null     // percent, proxied via total_assets YoY
  deposits_yoy?: number | null     // percent, proxied via total_liab YoY
  revenue_yoy_bank?: number | null // percent
  pat_yoy_bank?: number | null     // percent
  nim?: number | null              // percent — null until NSE XBRL Sch A/B lands
  car?: number | null              // percent — null until NSE XBRL Sch XI lands
  nnpa?: number | null             // percent — null until NSE XBRL Sch XVIII lands
  casa?: number | null             // percent — null until NSE XBRL Sch V lands
  // feat/freshness-stamps — period_end (YYYY-MM-DD) of the latest
  // filing feeding these ratios. Null on yfinance-only paths.
  latest_filing_period_end?: string | null
}

export interface BulkDealItem {
  date: string
  client: string
  deal_type: string
  qty_lakh: number
  price: number
  category: string
}

export interface RedFlag {
  flag: string
  severity: "critical" | "warning" | "info"
  title: string
  explanation: string
  data_point: string
  why_it_matters: string
}

export interface DividendFYItem {
  fy: string
  total_per_share: number
  payment_count: number
}

export interface DividendData {
  has_dividends: boolean
  ticker: string
  message: string
  current_yield_pct: number | null
  payout_ratio_pct: number | null
  five_yr_avg_yield: number | null
  dividend_rate_per_share: number | null
  last_dividend_value: number | null
  next_ex_date: string | null
  next_ex_days: number | null
  consecutive_years: number
  fy_history: DividendFYItem[]
  coverage_ratio: number | null
  sustainability: "strong" | "moderate" | "at_risk"
  sustainability_reason: string
  // feat/freshness-stamps — ISO date (YYYY-MM-DD) of the last ex-dividend event.
  last_ex_date?: string | null
}

export interface InsightCards {
  patience_months: number | null
  red_flag_count: number
  red_flags: string[]
  red_flags_structured: RedFlag[]
  dividend?: DividendData | null
  earnings_date: string | null
  earnings_est_eps: number | null
  earnings_days_until: number | null
  wall_street_avg_target: number | null
  wall_street_target_count: number | null
  insider_net_sentiment: string | null
  market_expectations_growth: number | null
  fcf_yield: number | null
  ev_ebitda: number | null
  reverse_dcf_implied_growth: number | null
  bulk_deals: BulkDealItem[]
  // feat/freshness-stamps — ISO timestamp of the analyst consensus refresh.
  // Null when unavailable; backend falls back to compute time when any
  // target data is present.
  analyst_target_as_of?: string | null
}

export interface ScenarioCase {
  iv: number
  mos_pct: number
  growth: number
  wacc: number
  term_g: number
}

export interface ScenariosOutput {
  bear: ScenarioCase
  base: ScenarioCase
  bull: ScenarioCase
}

export interface PriceLevels {
  entry_signal: string
  discount_zone: number | null
  model_estimate: number | null
  downside_range: number | null
  risk_reward_ratio: number | null
  holding_period: string | null
}

// Mirrors backend AnalyticalNoteOutput at backend/models/responses.py
// (PR #69). Backend emits 0-5 contextual disclaimers per analysis flagging
// structural DCF limitations for specific stock archetypes (premium brand,
// conglomerate, regulated utility, cyclical trough, post-merger, high-P/E
// growth, ADR / USD reporting).
export type AnalyticalNoteKind =
  | "data_quality"
  | "premium_brand"
  | "conglomerate"
  | "regulated_utility"
  | "cyclical_trough"
  | "post_merger"
  | "high_pe_growth"
  | "adr_usd_reporting"
export type AnalyticalNoteSeverity = "info" | "caution"
export interface AnalyticalNoteOutput {
  kind: AnalyticalNoteKind
  severity: AnalyticalNoteSeverity
  title: string
  body: string
}

export interface AnalysisResponse {
  ticker: string
  company: CompanyInfo
  valuation: ValuationOutput
  quality: QualityOutput
  insights: InsightCards
  scenarios: ScenariosOutput
  price_levels: PriceLevels
  ai_summary: string | null
  /**
   * Multilingual AI summary translations (Phase 0 — review-gated,
   * dark-launched). Mirrors the backend's
   * `AnalysisResponse.ai_summary_translations`. Keyed by ISO 639-1
   * code: "hi" (Hindi), "ta" (Tamil), "mr" (Marathi). The English
   * summary in `ai_summary` is the authoritative source; translations
   * carry an in-string disclaimer noting this. Stays `null` until
   * the `MULTILINGUAL_SUMMARIES_ENABLED` backend flag is flipped
   * (post native-speaker review). UI toggle ships in a later PR.
   */
  ai_summary_translations?: Record<string, string> | null
  data_confidence: Confidence
  data_issues: string[]
  analytical_notes?: AnalyticalNoteOutput[]
  cached: boolean
  timestamp: string
  /**
   * Backend-authored formula metadata, keyed by metric id (e.g.
   * "margin_of_safety", "roce"). Populated from
   * backend/services/analysis/formulas.py — the single source of
   * truth introduced after the 2026-04-25 MoS-tooltip drift bug.
   *
   * The MetricTooltip component prefers `formulas[key].formula` over
   * the hard-coded mirror in `lib/metric_explanations.ts`. Optional
   * because pre-PR cached payloads do not carry it.
   */
  formulas?: Record<string, FormulaInfo>
}

/**
 * Per-metric metadata block emitted by the backend on every
 * AnalysisResponse. Mirrors `backend/models/responses.py::FormulaInfo`.
 */
export interface FormulaInfo {
  key: string
  label: string
  formula: string
  explanation: string
  units?: string
  sector_note?: string | null
}

export interface ScreenerStock {
  ticker: string
  company_name: string
  score: number
  fair_value: number
  current_price: number
  margin_of_safety: number
  verdict: string
  moat: string
  confidence: string
  sector: string
}

export interface ScreenerResponse {
  results: ScreenerStock[]
  total: number
  page: number
  page_size: number
  filter_applied: Record<string, unknown>
}

export interface MarketIndex {
  name: string
  price: number
  change_pct: number
}

export interface MarketPulseResponse {
  indices: MarketIndex[]
  fear_greed_index: number | null
  fear_greed_label: string | null
  timestamp: string
  // Macro extension — populated only with ?include_macro=true
  fii_net_cr?: number | null
  dii_net_cr?: number | null
  fii_date?: string | null
  fii_stale?: boolean
  usd_inr?: number | null
  gold_usd?: number | null
  silver_usd?: number | null
  crude_usd?: number | null
  risk_free_pct?: number | null
  nifty_midcap_price?: number | null
  nifty_midcap_change_pct?: number | null
  ai_summary?: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user_id: string
  email: string
  tier: Tier
  analyses_today: number
  analysis_limit: number
  // Editable display name (PR #72) — null when never set;
  // frontend falls back to nameFromEmail() in PersonalHeader.
  display_name: string | null
  display_name_edits_remaining: number
  // Feature flags resolved server-side for this user. Optional because
  // pre-PR backends omit the field; useFeatureFlag() treats absence as
  // all-disabled.
  feature_flags?: Record<string, boolean>
}

export interface UserResponse {
  user_id: string
  email: string
  tier: Tier
  analyses_today: number
  analysis_limit: number
  created_at: string
  display_name: string | null
  display_name_edits_remaining: number
  // See TokenResponse.feature_flags above.
  feature_flags?: Record<string, boolean>
}

// PATCH /api/v1/account/profile response shape.
export interface ProfileUpdateResponse {
  display_name: string
  edits_used: number
  edits_remaining: number
}

export interface HoldingResponse {
  ticker: string
  company_name: string
  entry_price: number
  current_price: number
  iv: number
  mos_pct: number
  signal: string
  sector: string
  notes: string
  saved_at: string
}

export interface PortfolioHealthResponse {
  score: number
  grade: string
  summary: string
  issues: string[]
  strengths: string[]
  overvalued_count: number
  undervalued_count: number
  danger_positions: string[]
  concentration_warning: string | null
}

export interface SectorOverviewItem {
  name: string
  avg_score: number
  pct_undervalued: number
  trend: string
}

export interface WatchlistItemResponse {
  ticker: string
  company_name: string
  added_price: number
  target_price: number
  alert_mos_threshold: number
  notes: string
  added_at: string
}

export interface AlertResponse {
  id: number
  ticker: string
  alert_type: string
  target_price: number
  created_at: string
  is_active: boolean
}

export interface SuccessResponse {
  ok: boolean
  message: string
}

// ── Notifications (in-app bell + drawer) ─────────────────────
// Mirrors backend/services/notifications_service.py NotificationType
// and the row shape returned by the /api/v1/notifications/* routes.
export type NotificationType =
  | "alert_fired"
  | "portfolio_event"
  | "earnings_reminder"
  | "market_event"
  | "model_update"
  | "system"

export interface Notification {
  id: number
  type: NotificationType
  title: string
  body: string | null
  link: string | null
  metadata: Record<string, unknown>
  created_at: string  // ISO8601
  read_at: string | null
}

export interface NotificationsUnreadResponse {
  items: Notification[]
  count: number
}

export interface NotificationsRecentResponse {
  items: Notification[]
}

export interface NotificationsUnreadCountResponse {
  count: number
}
