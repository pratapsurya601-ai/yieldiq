// Frontend types and helpers for the Strategy Builder UI.
// Mirrors the strategy_def schema documented in
// backend/services/strategy_service.py — keep them in sync.

export type RuleOperator =
  | ">="
  | "<="
  | ">"
  | "<"
  | "=="
  | "!="
  | "in"
  | "not_in"

export interface EntryRule {
  id: string
  metric: string
  op: RuleOperator
  value: number | string | string[]
}

export interface UniverseDef {
  kind: "all" | "nifty50" | "nifty500" | "watchlist" | "sector"
  sector?: string
  tickers?: string[]
}

export interface RebalanceDef {
  freq: "monthly" | "quarterly" | "yearly"
  sizing: "equal" | "score" | "top_n"
  top_n?: number
  max_position_pct?: number
}

export interface TestPeriodDef {
  start: string
  end: string
  benchmark: "nifty50" | "nifty500" | "sensex" | "custom"
}

export interface StrategyDef {
  name?: string
  universe: UniverseDef
  entry_rules: { logic: "AND" | "OR"; rules: Omit<EntryRule, "id">[] }
  rebalance: RebalanceDef
  test_period: TestPeriodDef
}

export interface MetricCatalogEntry {
  key: string
  label: string
  // numeric metrics use comparison operators; categorical use in/== ; enum
  // metrics expose a fixed set of choices.
  type: "number" | "string" | "enum"
  unit?: string
  options?: string[]
}

export const METRIC_CATALOG: MetricCatalogEntry[] = [
  { key: "yieldiq_score", label: "YieldIQ Score", type: "number", unit: "/100" },
  { key: "piotroski", label: "Piotroski F-Score", type: "number", unit: "/9" },
  {
    key: "moat",
    label: "Moat",
    type: "enum",
    options: ["Wide", "Moderate", "Narrow", "None"],
  },
  { key: "mos", label: "Margin of Safety", type: "number", unit: "%" },
  { key: "pe", label: "P/E (TTM)", type: "number" },
  { key: "pb", label: "P/B", type: "number" },
  { key: "roe", label: "ROE", type: "number", unit: "%" },
  { key: "roce", label: "ROCE", type: "number", unit: "%" },
  { key: "debt_equity", label: "Debt / Equity", type: "number" },
  { key: "revenue_cagr_3y", label: "Revenue CAGR (3y)", type: "number", unit: "%" },
  { key: "revenue_cagr_5y", label: "Revenue CAGR (5y)", type: "number", unit: "%" },
  { key: "div_yield", label: "Dividend Yield", type: "number", unit: "%" },
  { key: "sector", label: "Sector", type: "string" },
  {
    key: "market_cap_tier",
    label: "Market Cap Tier",
    type: "enum",
    options: ["Large", "Mid", "Small"],
  },
  {
    key: "sector_percentile_band",
    label: "Sector-percentile band",
    type: "enum",
    options: [
      "Notable discount",
      "Below peer range",
      "In peer range",
      "Above peer range",
      "Notable premium",
    ],
  },
]

export function defaultRebalance(): RebalanceDef {
  return { freq: "quarterly", sizing: "equal", top_n: 20, max_position_pct: 25 }
}

export function defaultTestPeriod(): TestPeriodDef {
  // Last 5 years, ending today (rough — backend will normalize)
  const end = new Date()
  const start = new Date()
  start.setFullYear(end.getFullYear() - 5)
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
    benchmark: "nifty50",
  }
}

export function emptyStrategy(): StrategyDef {
  return {
    universe: { kind: "nifty500" },
    entry_rules: { logic: "AND", rules: [] },
    rebalance: defaultRebalance(),
    test_period: defaultTestPeriod(),
  }
}

export interface BacktestMetrics {
  total_return_pct?: number
  cagr_pct?: number
  volatility_pct?: number
  sharpe_proxy?: number
  max_drawdown_pct?: number
  benchmark_cagr_pct?: number
  outperformance_pct?: number
  alpha_pct?: number
  beta?: number
  n_years?: number
}

export interface BacktestCurvePoint {
  date: string
  portfolio: number
  benchmark?: number
}

export interface MonthlyReturnRow {
  year: number
  month: number
  return_pct: number
}

export interface HoldingRow {
  ticker: string
  company_name?: string
  sector?: string
  score?: number
  mos?: number
  weight_pct: number
}

export interface BacktestResult {
  error?: string
  curve?: BacktestCurvePoint[]
  metrics?: BacktestMetrics
  holdings?: HoldingRow[]
  monthly_returns?: MonthlyReturnRow[]
  tickers_matched?: number
  tickers_backtested?: number
  tickers_dropped?: number
  benchmark?: string
  years?: number
  rebalance_days?: number
}

export interface SavedStrategyDTO {
  id: string
  name: string
  strategy_def: StrategyDef
  last_backtest_results?: BacktestResult | null
  last_backtested_at?: string | null
  is_public: boolean
  public_slug?: string | null
  created_at: string
  updated_at: string
}
