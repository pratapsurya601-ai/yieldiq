import axios from "axios"
import Cookies from "js-cookie"
import type { AnalysisResponse, TokenResponse, MarketPulseResponse, ScreenerResponse, PortfolioHealthResponse, HoldingResponse, SectorOverviewItem } from "@/types/api"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

const api = axios.create({ baseURL: API_BASE, timeout: 60000 })

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

export const getYieldIQ50 = (): Promise<ScreenerResponse> =>
  api.get("/api/v1/yieldiq50").then(r => r.data)

export const getTopPick = () =>
  api.get("/api/v1/top-pick").then(r => r.data)

// Screener
export const runScreener = (filters: Record<string, unknown>): Promise<ScreenerResponse> =>
  api.get("/api/v1/screener/run", { params: filters }).then(r => r.data)

export const runPreset = (preset: string): Promise<ScreenerResponse> =>
  api.get(`/api/v1/screener/preset/${preset}`).then(r => r.data)

// Market
export const getMarketPulse = (): Promise<MarketPulseResponse> =>
  api.get("/api/v1/market/pulse").then(r => r.data)

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
export const getWatchlist = () =>
  api.get("/api/v1/watchlist/").then(r => r.data)

export const addToWatchlist = (item: Record<string, unknown>) =>
  api.post("/api/v1/watchlist/", item).then(r => r.data)

export const removeFromWatchlist = (ticker: string) =>
  api.delete(`/api/v1/watchlist/${ticker}`).then(r => r.data)

// Auth
export const login = (email: string, password: string): Promise<TokenResponse> =>
  api.post("/api/v1/auth/login", { email, password }).then(r => r.data)

export const signup = (email: string, password: string): Promise<TokenResponse> =>
  api.post("/api/v1/auth/register", { email, password }).then(r => r.data)

export const getMe = () =>
  api.get("/api/v1/auth/me").then(r => r.data)

export default api
