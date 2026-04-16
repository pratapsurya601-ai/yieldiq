// types/api.ts — mirrors backend/models/responses.py exactly

export type Verdict = "undervalued" | "fairly_valued" | "overvalued" | "avoid" | "data_limited" | "unavailable"
export type Grade = "A" | "B" | "C" | "D" | "F"
export type Tier = "free" | "starter" | "pro" | "analyst"
export type Confidence = "high" | "medium" | "low" | "unusable"
export type MoatGrade = "Wide" | "Narrow" | "None"

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
  promoter_pct?: number | null
  promoter_pledge_pct?: number | null
  fii_pct?: number | null
  dii_pct?: number | null
  public_pct?: number | null
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

export interface AnalysisResponse {
  ticker: string
  company: CompanyInfo
  valuation: ValuationOutput
  quality: QualityOutput
  insights: InsightCards
  scenarios: ScenariosOutput
  price_levels: PriceLevels
  ai_summary: string | null
  data_confidence: Confidence
  data_issues: string[]
  cached: boolean
  timestamp: string
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
}

export interface UserResponse {
  user_id: string
  email: string
  tier: Tier
  analyses_today: number
  analysis_limit: number
  created_at: string
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
