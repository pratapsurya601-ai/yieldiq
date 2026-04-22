import axios from "axios"
import Cookies from "js-cookie"
import type { AnalysisResponse, TokenResponse, MarketPulseResponse, ScreenerResponse, PortfolioHealthResponse, HoldingResponse, SectorOverviewItem, WatchlistItemResponse, AlertResponse, SuccessResponse } from "@/types/api"
// Static import — previously a dynamic import() was used here to avoid
// a theoretical circular with authStore, but there's no circular (authStore
// does not import api.ts) and the async path silently dropped counter
// updates in production: by the time the Promise resolved, the user was
// looking at a stale "2/5 today" and had to log out and back in to see
// the real count. Direct import runs synchronously per response.
import { useAuthStore } from "@/store/authStore"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

const api = axios.create({ baseURL: API_BASE, timeout: 20000 })  // 20s timeout

api.interceptors.request.use((config) => {
  const token = Cookies.get("yieldiq_token")
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Case-insensitive header getter. Axios normalizes to lowercase in most
// versions, but preserves Camel-Case in a few older/middleware setups.
// Belt-and-braces: check both common shapes.
function _readHeader(headers: unknown, name: string): string | undefined {
  if (!headers || typeof headers !== "object") return undefined
  const h = headers as Record<string, unknown>
  const lc = name.toLowerCase()
  if (h[lc] !== undefined) return String(h[lc])
  // Try Camel-Case (X-Analyses-Today)
  const cc = name
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join("-")
  if (h[cc] !== undefined) return String(h[cc])
  // Axios occasionally exposes headers via a Headers-like object with get()
  const g = (h as { get?: (k: string) => string | null }).get
  if (typeof g === "function") {
    const v = g.call(h, lc) ?? g.call(h, cc)
    if (v !== null && v !== undefined) return String(v)
  }
  return undefined
}

api.interceptors.response.use(
  (res) => {
    // Backend's check_analysis_limit dependency surfaces the free-tier
    // counter on every gated endpoint via X-Analyses-Today / -Limit
    // response headers (see backend/middleware/auth.py + CORS
    // expose_headers in backend/main.py). Mirror them into the auth
    // store so the nav widget, home page, and account page all reflect
    // the real backend state immediately — no /auth/me round-trip
    // needed.
    if (typeof window !== "undefined") {
      try {
        const today = _readHeader(res.headers, "x-analyses-today")
        const limit = _readHeader(res.headers, "x-analyses-limit")
        if (today !== undefined || limit !== undefined) {
          const s = useAuthStore.getState()
          const nextToday = today !== undefined ? Number(today) : s.analysesToday
          const nextLimit = limit !== undefined ? Number(limit) : s.analysisLimit
          if (Number.isFinite(nextToday) && Number.isFinite(nextLimit)) {
            useAuthStore.setState({
              analysesToday: nextToday,
              analysisLimit: nextLimit,
            })
          }
        }
      } catch (e) {
        // Don't let a counter-sync error block the response, but log so
        // a broken auth store is visible in prod devtools, not silent.
        // eslint-disable-next-line no-console
        console.warn("[api] X-Analyses header sync failed:", e)
      }
    }
    return res
  },
  (err) => {
    // Mirror X-Analyses-* headers on ERROR responses too (primarily 429).
    // When the rate limiter blocks the 6th call of the day, the backend
    // raises HTTPException with X-Analyses-Today/Limit in the headers
    // dict. Without this block, the nav counter stays at its previous
    // value (or at 0 if the user refreshed before hitting the cap) —
    // confusingly showing 0/5 on the Daily-limit-reached screen.
    if (typeof window !== "undefined" && err.response?.headers) {
      try {
        const today = _readHeader(err.response.headers, "x-analyses-today")
        const limit = _readHeader(err.response.headers, "x-analyses-limit")
        if (today !== undefined || limit !== undefined) {
          const s = useAuthStore.getState()
          const nextToday = today !== undefined ? Number(today) : s.analysesToday
          const nextLimit = limit !== undefined ? Number(limit) : s.analysisLimit
          if (Number.isFinite(nextToday) && Number.isFinite(nextLimit)) {
            useAuthStore.setState({
              analysesToday: nextToday,
              analysisLimit: nextLimit,
            })
          }
        }
      } catch {
        // swallow — counter sync is best-effort, never block error flow
      }
    }
    if (err.response?.status === 401 && typeof window !== "undefined") {
      // Only treat 401 as "session expired" when a token was actually
      // present. For anonymous visitors (e.g. hitting /analysis/:ticker
      // without signing up — the landing page advertises this as free),
      // a 401 from a gated backend endpoint is expected; bubble it up to
      // the caller and let the page show its public fallback or upsell
      // rather than hard-redirecting the whole browser to /auth/login.
      const hadToken = Cookies.get("yieldiq_token")
      if (hadToken) {
        Cookies.remove("yieldiq_token")
        window.location.href = "/auth/login"
      }
    }
    if (err.response?.status === 429) {
      err.message = "Daily analysis limit reached. Upgrade for more."
    }
    if (err.response?.status === 404) {
      // Backend raises 404 specifically when the data provider has no
      // record of the requested ticker (invalid / misspelled symbol).
      err.message = "Ticker not found"
    }
    if (!err.response) {
      err.message = "Network error — check your connection"
    }
    return Promise.reject(err)
  }
)

// Analysis
// feat/ai-narrative-summary (2026-04-21): the narrative summary is now
// baked into AnalysisResponse.ai_summary during the cold-compute path
// and persisted in the analysis_cache tiers, so warm reads include it
// at zero extra latency. The legacy ?include_summary=false escape hatch
// existed because the OLD summary flow routed through a separate
// synchronous endpoint that added 5-15s to every request; that is no
// longer true. We now request the summary by default and render it
// above the Prism hex when present, hide the component when null.
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

export interface LiveHolding {
  ticker: string
  display_ticker: string
  company_name: string
  sector: string
  entry_price: number
  quantity: number
  account_label: string
  current_price: number
  invested_value: number
  current_value: number
  pnl_abs: number
  pnl_pct: number
  fair_value: number | null
  mos_pct: number | null
  verdict: string
  score: number | null
  saved_at: string
  notes: string
}

export interface HoldingsLiveResponse {
  holdings: LiveHolding[]
  summary: {
    total_invested: number
    total_current_value: number
    total_pnl_abs: number
    total_pnl_pct: number
    winners: number
    losers: number
    count: number
  }
}

export const getHoldingsLive = (): Promise<HoldingsLiveResponse> =>
  api.get("/api/v1/portfolio/holdings-live").then(r => r.data)

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

// ---------------------------------------------------------------------------
// Public SEO-page fetch helpers
// ---------------------------------------------------------------------------
// These hit the unauthenticated /api/v1/public/* endpoints used by the
// server-rendered fair-value page. They return null on 503 (under_review)
// and on network errors so the SEO page can render placeholder cards
// without blocking the rest of the layout.

export interface HistoricalFinancialsPeriod {
  period_end: string
  period_type: string
  revenue: number | null
  ebitda: number | null
  ebit: number | null
  pat: number | null
  eps_diluted: number | null
  cfo: number | null
  capex: number | null
  free_cash_flow: number | null
  total_assets: number | null
  total_equity: number | null
  total_debt: number | null
  cash_and_equivalents: number | null
  shares_outstanding: number | null
  roe: number | null
  roa: number | null
  debt_to_equity: number | null
  gross_margin: number | null
  operating_margin: number | null
  net_margin: number | null
  fcf_margin: number | null
  revenue_growth_yoy: number | null
  pat_growth_yoy: number | null
}

export interface HistoricalFinancialsResponse {
  ticker: string
  currency: string
  periods: HistoricalFinancialsPeriod[]
}

export interface RatioHistoryPeriod {
  period_end: string
  period_type: string
  roe: number | null
  roce: number | null
  roa: number | null
  de_ratio: number | null
  debt_ebitda: number | null
  interest_cov: number | null
  gross_margin: number | null
  operating_margin: number | null
  net_margin: number | null
  fcf_margin: number | null
  revenue_yoy: number | null
  ebitda_yoy: number | null
  pat_yoy: number | null
  fcf_yoy: number | null
  pe_ratio: number | null
  pb_ratio: number | null
  ev_ebitda: number | null
  dividend_yield: number | null
  market_cap_cr: number | null
  current_ratio: number | null
  asset_turnover: number | null
}

export interface RatioHistoryResponse {
  ticker: string
  periods: RatioHistoryPeriod[]
}

export interface PublicPeerRow {
  peer_ticker: string
  rank: number
  sector: string | null
  sub_sector: string | null
  mcap_ratio: number | null
  company_name: string | null
  fair_value: number | null
  current_price: number | null
  margin_of_safety: number | null
  verdict: string | null
  score: number | null
  moat: string | null
  roe: number | null
  pe_ratio: number | null
}

export interface PublicPeersResponse {
  ticker: string
  peers: PublicPeerRow[]
}

// Server-side fetch — uses bare fetch() (not axios) because these helpers
// are called from React Server Components and rely on Next.js's fetch
// caching / `next: { revalidate }` extension.
async function publicGet<T>(path: string, revalidateSec: number): Promise<T | null> {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  try {
    const res = await fetch(`${base}${path}`, { next: { revalidate: revalidateSec } })
    if (res.status === 503) return null  // under_review sentinel
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

export const getHistoricalFinancials = (
  ticker: string,
  years: number = 10,
  period: "annual" | "quarterly" = "annual",
): Promise<HistoricalFinancialsResponse | null> =>
  publicGet<HistoricalFinancialsResponse>(
    `/api/v1/public/financials/${ticker}?period=${period}&years=${years}`,
    3600,
  )

export const getRatiosHistory = (
  ticker: string,
  years: number = 10,
  period: "annual" | "quarterly" = "annual",
): Promise<RatioHistoryResponse | null> =>
  publicGet<RatioHistoryResponse>(
    `/api/v1/public/ratios-history/${ticker}?years=${years}&period=${period}`,
    3600,
  )

export const getPublicPeers = (
  ticker: string,
  limit: number = 5,
): Promise<PublicPeersResponse | null> =>
  publicGet<PublicPeersResponse>(
    `/api/v1/public/peers/${ticker}?limit=${limit}`,
    3600,
  )

// ── Dividend history ─────────────────────────────────────────
export interface DividendEvent {
  ex_date: string                        // ISO YYYY-MM-DD
  amount: number | null                  // ₹ per share, null when un-parseable
}

export interface DividendHistoryResponse {
  ticker: string
  count: number
  total_paid_5y: number | null
  dividends: DividendEvent[]
}

export const getDividendHistory = (
  ticker: string,
  years: number = 10,
): Promise<DividendHistoryResponse | null> =>
  publicGet<DividendHistoryResponse>(
    `/api/v1/public/dividends/${ticker}?years=${years}`,
    21600,                               // 6h — matches backend edge cache
  )

// ---------------------------------------------------------------------------
// Stock summary (used by sensitivity heatmap, Excel export, portfolio tracker)
// ---------------------------------------------------------------------------
// Mirrors the StockSummary shape rendered on the fair-value page. Returns
// null on under_review (503) or any error so callers can degrade gracefully.

export interface StockSummary {
  ticker: string
  company_name: string
  sector: string
  industry: string
  exchange: string
  currency: string
  fair_value: number
  current_price: number
  mos: number
  verdict: string
  score: number
  grade: string
  moat: string
  piotroski: number
  bear_case: number
  base_case: number
  bull_case: number
  wacc: number
  confidence: number
  roe: number | null
  de_ratio: number | null
  roce: number | null
  debt_ebitda: number | null
  interest_coverage: number | null
  current_ratio: number | null
  asset_turnover: number | null
  revenue_cagr_3y: number | null
  revenue_cagr_5y: number | null
  ev_ebitda: number | null
  market_cap: number
  ai_summary_snippet: string | null
  last_updated: string | null
}

export const getStockSummary = async (
  ticker: string,
): Promise<StockSummary | null> => {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  try {
    const res = await fetch(`${base}/api/v1/public/stock-summary/${ticker}`, {
      next: { revalidate: 300 },
    })
    if (!res.ok) return null
    const data = await res.json()
    if (data && data.status === "under_review") return null
    return data as StockSummary
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// PAYG (Pay-as-you-go) — ₹99 for 24h access to a single analysis.
// Backend: POST /create-order → Razorpay modal → POST /verify → ticker unlocked.
// Unlock state lives in Postgres; /payg-unlocks returns only unlocks within
// the last 24h (backend filters).
// ---------------------------------------------------------------------------

export interface PaygCreateOrderResponse {
  order_id: string
  amount: number          // paise — 9900 = ₹99
  currency: string        // "INR"
  key_id: string          // Razorpay public key
  plan: string            // "single_analysis"
  ticker: string
  name: string
  description: string
}

export interface PaygVerifyResponse {
  ok: boolean
  unlock: { ticker: string; hours: number }
  message: string
}

export interface PaygUnlock {
  ticker: string
  unlocked_at: string     // ISO timestamp
  razorpay_payment_id: string
}

export interface PaygUnlocksResponse {
  unlocks: PaygUnlock[]
}

export const createPaygOrder = (
  ticker: string,
  planId: string = "single_analysis",
): Promise<PaygCreateOrderResponse> =>
  api
    .post("/api/v1/payments/create-order", null, {
      params: { plan_id: planId, ticker },
    })
    .then((r) => r.data)

export const verifyPaygPayment = (args: {
  razorpay_order_id: string
  razorpay_payment_id: string
  razorpay_signature: string
  ticker: string
  planId?: string
}): Promise<PaygVerifyResponse> =>
  api
    .post("/api/v1/payments/verify", null, {
      params: {
        razorpay_order_id: args.razorpay_order_id,
        razorpay_payment_id: args.razorpay_payment_id,
        razorpay_signature: args.razorpay_signature,
        plan_id: args.planId ?? "single_analysis",
        ticker: args.ticker,
      },
    })
    .then((r) => r.data)

export const listPaygUnlocks = (): Promise<PaygUnlocksResponse> =>
  api.get("/api/v1/payments/payg-unlocks").then((r) => r.data)

// Auth
export const login = (email: string, password: string): Promise<TokenResponse> =>
  api.post("/api/v1/auth/login", { email, password }).then(r => r.data)

export const signup = (email: string, password: string, referralCode?: string | null): Promise<TokenResponse> =>
  api.post("/api/v1/auth/register", { email, password, ...(referralCode ? { referral_code: referralCode } : {}) }).then(r => r.data)

export const getMe = () =>
  api.get("/api/v1/auth/me").then(r => r.data)

// Onboarding state — backend is source of truth, localStorage is fast-path cache.
// Added 2026-04-21 to fix: users who completed onboarding on device A would see
// the wizard again when logging in on device B/incognito because the completion
// flag lived only in localStorage (yieldiq-settings).
export interface OnboardingStatusResponse {
  completed: boolean
  last_step: number
  completed_at: string | null
  source: "db" | "default"
}

export const getOnboardingStatus = (): Promise<OnboardingStatusResponse> =>
  api.get("/api/v1/auth/onboarding-status", { timeout: 4000 }).then(r => r.data)

export const completeOnboardingRemote = (body?: {
  last_step?: number
  interests?: string[]
  firstStock?: string | null
}): Promise<{ completed: boolean; completed_at: string }> =>
  api.post("/api/v1/auth/complete-onboarding", body ?? {}, { timeout: 4000 }).then(r => r.data)

export default api
