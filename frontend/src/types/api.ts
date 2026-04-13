// types/api.ts — mirrors backend/models/responses.py exactly

export type Verdict = "undervalued" | "fairly_valued" | "overvalued" | "avoid"
export type Grade = "A" | "B" | "C" | "D" | "F"
export type Tier = "free" | "starter" | "pro"
export type Confidence = "high" | "medium" | "low"
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
}

export interface InsightCards {
  patience_months: number | null
  red_flag_count: number
  red_flags: string[]
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
