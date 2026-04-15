import axios from "axios"
import Cookies from "js-cookie"
import type { AnalysisResponse, TokenResponse, MarketPulseResponse, ScreenerResponse, PortfolioHealthResponse, HoldingResponse, SectorOverviewItem, WatchlistItemResponse, AlertResponse, SuccessResponse } from "@/types/api"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

const api = axios.create({ baseURL: API_BASE, timeout: 20000 })  // 20s timeout

api.interceptors.request.use((config) => {
  const token = Cookies.get("yieldiq_token")
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && typeof window !== "undefined") {
      Cookies.remove("yieldiq_token")
      window.location.href = "/auth/login"
    }
    if (err.response?.status === 429) {
      err.message = "Daily analysis limit reached. Upgrade for more."
    }
    if (!err.response) {
      err.message = "Network error — check your connection"
    }
    return Promise.reject(err)
  }
)

// Analysis
export const getAnalysis = (ticker: string): Promise<AnalysisResponse> =>
  api.get(`/api/v1/analysis/${ticker}`).then(r => r.data)

export const getAISummary = (ticker: string): Promise<{ summary: string }> =>
  api.get(`/api/v1/analysis/${ticker}/summary`).then(r => r.data)

export const getChartData = (ticker: string, period: string = "1m") =>
  api.get(`/api/v1/analysis/${ticker}/chart-data?period=${period}`).then(r => r.data)

export interface FVHistoryPoint {
  date: string
  fair_value: number
  price: number
  mos_pct: number
  verdict: string | null
}

export interface FVHistorySummary {
  has_data: boolean
  data_start_date: string | null
  total_points: number
  pct_undervalued: number | null
  pct_overvalued: number | null
}

export interface FVHistoryResponse {
  ticker: string
  has_data: boolean
  tier: string
  tier_limited: boolean
  years_returned: number
  data: FVHistoryPoint[]
  summary: FVHistorySummary
  message?: string
}

export const getFVHistory = (ticker: string, years: number = 3): Promise<FVHistoryResponse> =>
  api.get(`/api/v1/analysis/${ticker}/fv-history?years=${years}`).then(r => r.data)

export interface FinancialYear {
  year: string
  period_end: string | null
  // Income
  revenue: number | null
  revenue_growth_pct: number | null
  gross_profit: number | null
  gross_margin_pct: number | null
  ebitda: number | null
  operating_income: number | null
  operating_margin_pct: number | null
  net_income: number | null
  net_income_growth_pct: number | null
  net_margin_pct: number | null
  eps_diluted: number | null
  // Balance Sheet
  total_assets: number | null
  total_equity: number | null
  total_debt: number | null
  cash: number | null
  net_debt: number | null
  debt_to_equity: number | null
  book_value_per_share: number | null
  // Cash Flow
  operating_cash_flow: number | null
  capex: number | null
  free_cash_flow: number | null
  fcf_margin_pct: number | null
}

export interface FinancialsResponse {
  ticker: string
  currency: string
  currency_unit: string
  period: "annual" | "quarterly"
  years_available: number
  has_quarterly: boolean
  data_source: string
  tier: string
  tier_limited: boolean
  income: FinancialYear[]
  balance_sheet: FinancialYear[]
  cash_flow: FinancialYear[]
  summary: {
    revenue_cagr_3y: number | null
    avg_net_margin: number | null
    avg_fcf_margin: number | null
    latest_roe: number | null
  }
}

export const getFinancials = (
  ticker: string,
  period: "annual" | "quarterly" = "annual",
  years: number = 5,
): Promise<FinancialsResponse> =>
  api
    .get(`/api/v1/analysis/${ticker}/financials`, { params: { period, years } })
    .then(r => r.data)

export interface PeerRow {
  ticker: string
  is_main: boolean
  company_name: string
  yieldiq_score: number | null
  grade: string | null
  fair_value: number | null
  mos_pct: number | null
  verdict: string | null
  pe_ratio: number | null
  pb_ratio: number | null
  ev_ebitda: number | null
  market_cap_cr: number | null
  dividend_yield: number | null
  roe_pct: number | null
  net_margin_pct: number | null
  debt_to_equity: number | null
  fcf_yield_pct: number | null
}

export interface PeersResponse {
  ticker: string
  has_peers: boolean
  sector_label: string | null
  peers_count: number
  best_in_sector: Record<string, string>
  peers: PeerRow[]
  message?: string
}

export const getPeers = (ticker: string): Promise<PeersResponse> =>
  api.get(`/api/v1/analysis/${ticker}/peers`).then(r => r.data)

export const getYieldIQ50 = (): Promise<ScreenerResponse> =>
  api.get("/api/v1/yieldiq50").then(r => r.data)

export const getTopPick = () =>
  api.get("/api/v1/top-pick").then(r => r.data)

// Compare
export const compareStocks = (ticker1: string, ticker2: string) =>
  api.get(`/api/v1/compare?ticker1=${ticker1}&ticker2=${ticker2}`).then(r => r.data)

// Screener
export const runScreener = (filters: Record<string, unknown>): Promise<ScreenerResponse> =>
  api.get("/api/v1/screener/run", { params: filters }).then(r => r.data)

export const runPreset = (preset: string): Promise<ScreenerResponse> =>
  api.get(`/api/v1/screener/preset/${preset}`).then(r => r.data)

// Market
export const getMarketPulse = (
  includeMacro: boolean = false,
): Promise<MarketPulseResponse> =>
  api
    .get("/api/v1/market/pulse", {
      params: includeMacro ? { include_macro: true } : undefined,
    })
    .then(r => r.data)

export const getMacroSummary = (): Promise<{ summary: string | null }> =>
  api.get("/api/v1/market/macro-summary").then(r => r.data)

export const getSectorOverview = (): Promise<SectorOverviewItem[]> =>
  api.get("/api/v1/market/sectors").then(r => r.data)

// Portfolio
export const getPortfolioHealth = (): Promise<PortfolioHealthResponse> =>
  api.get("/api/v1/portfolio/health").then(r => r.data)

export const getHoldings = (): Promise<HoldingResponse[]> =>
  api.get("/api/v1/portfolio/holdings").then(r => r.data)

export const addHolding = (holding: Record<string, unknown>) =>
  api.post("/api/v1/portfolio/holdings", holding).then(r => r.data)

export const removeHolding = (ticker: string) =>
  api.delete(`/api/v1/portfolio/holdings/${ticker}`).then(r => r.data)

// Watchlist
export const getWatchlist = (): Promise<WatchlistItemResponse[]> =>
  api.get("/api/v1/watchlist/").then(r => r.data)

export const addToWatchlist = (item: Record<string, unknown>): Promise<SuccessResponse> =>
  api.post("/api/v1/watchlist/", item).then(r => r.data)

export const removeFromWatchlist = (ticker: string): Promise<SuccessResponse> =>
  api.delete(`/api/v1/watchlist/${ticker}`).then(r => r.data)

export const checkInWatchlist = (ticker: string): Promise<{ in_watchlist: boolean }> =>
  api.get(`/api/v1/watchlist/check/${ticker}`).then(r => r.data)

// Alerts
export const getAlerts = (): Promise<AlertResponse[]> =>
  api.get("/api/v1/alerts/").then(r => r.data)

export const createAlert = (data: { ticker: string; alert_type: string; target_price: number }): Promise<SuccessResponse> =>
  api.post("/api/v1/alerts/create", data).then(r => r.data)

export const deleteAlert = (alertId: number): Promise<SuccessResponse> =>
  api.delete(`/api/v1/alerts/${alertId}`).then(r => r.data)

// Auth
export const login = (email: string, password: string): Promise<TokenResponse> =>
  api.post("/api/v1/auth/login", { email, password }).then(r => r.data)

export const signup = (email: string, password: string, referralCode?: string | null): Promise<TokenResponse> =>
  api.post("/api/v1/auth/register", { email, password, ...(referralCode ? { referral_code: referralCode } : {}) }).then(r => r.data)

export const getMe = () =>
  api.get("/api/v1/auth/me").then(r => r.data)

export default api
