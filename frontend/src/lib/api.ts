import axios from "axios"
import Cookies from "js-cookie"
import type { AnalysisResponse, TokenResponse, MarketPulseResponse, ScreenerResponse, PortfolioHealthResponse, HoldingResponse, SectorOverviewItem, WatchlistItemResponse, AlertResponse, SuccessResponse, ProfileUpdateResponse, TodayMoversResponse } from "@/types/api"
// Static import — previously a dynamic import() was used here to avoid
// a theoretical circular with authStore, but there's no circular (authStore
// does not import api.ts) and the async path silently dropped counter
// updates in production: by the time the Promise resolved, the user was
// looking at a stale "2/5 today" and had to log out and back in to see
// the real count. Direct import runs synchronously per response.
import { useAuthStore } from "@/store/authStore"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// Per-deploy cache buster. Vercel injects VERCEL_GIT_COMMIT_SHA at build
// time; we expose it as NEXT_PUBLIC_BUILD_ID so it ends up in the client
// bundle. Used as:
//   1. queryKey suffix on every Discover/landing-page useQuery — each
//      deploy is a new key, so React Query never serves a stale empty
//      payload from a prior deploy's cache.
//   2. ?v=<sha> query param appended to every axios request below — busts
//      any HTTP-layer (browser/CDN) caches that key on full URL.
// In dev (no env var) we fall back to the literal "dev", which means the
// in-memory cache survives across HMR — desirable locally.
export const BUILD_ID: string =
  process.env.NEXT_PUBLIC_BUILD_ID ||
  process.env.VERCEL_GIT_COMMIT_SHA ||
  "dev"

const api = axios.create({ baseURL: API_BASE, timeout: 20000 })  // 20s timeout

api.interceptors.request.use((config) => {
  const token = Cookies.get("yieldiq_token")
  if (token) config.headers.Authorization = `Bearer ${token}`
  // Append ?v=BUILD_ID to bust browser/CDN caches per deploy. Skip when
  // a `v` param is already present (caller-supplied) so we don't clobber.
  if (BUILD_ID && BUILD_ID !== "dev") {
    config.params = { v: BUILD_ID, ...(config.params || {}) }
  }
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
        // Clear stale auth state BEFORE any navigation so the next page
        // load (or post-redirect Zustand rehydration) doesn't reload the
        // bad token and re-fire the same 401 → reload loop.
        Cookies.remove("yieldiq_token")
        try { useAuthStore.getState().logout() } catch { /* best effort */ }
        // If we are already on the login page, do NOT hard-reload — that
        // is exactly what creates the refresh loop when a stale token
        // is rehydrated from localStorage on /auth/login.
        if (!window.location.pathname.startsWith("/auth/")) {
          window.location.href = "/auth/login"
        }
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

// ── ELI15 thesis ───────────────────────────────────────────────
// Plain-English 3-bullet explainer of the model's verdict, generated
// by Claude with mandatory SEBI post-filtering server-side and a
// deterministic template fallback when the LLM is unreachable or
// trips the filter. Cached per (ticker, day) in the backend; the
// frontend treats this as a 1-hour staleTime so a single page
// re-render doesn't re-fetch.
export interface ELI15ThesisResponse {
  ticker: string
  generated_at: string
  model_version: string
  // Wire-format enum, mirrors ValuationOutput.verdict.
  verdict: "undervalued" | "fairly_valued" | "overvalued" | "avoid" | "data_limited" | "unavailable"
  // SEBI-safe display label for direct rendering.
  verdict_display: string
  // Exactly 3 SEBI-filtered bullet strings on a successful response.
  // Empty/missing when the backend genuinely has nothing to return
  // (the panel hides itself in that case).
  bullets: string[]
  disclaimer: string
  cached: boolean
}

export const getELI15Thesis = (ticker: string): Promise<ELI15ThesisResponse> =>
  api.get(`/api/v1/analysis/${ticker}/eli15-thesis`).then(r => r.data)

// ── AI Explain (Premium Feel R4) ──────────────────────────────
// AlphaSpread-style preset cards. The presets list is fetched once;
// each card click hits POST /ai-explain with { ticker, preset_id }
// and returns the SEBI-filtered answer text. Server caches per
// (ticker, preset_id) for 30s so repeated clicks within a session
// reuse the answer for free. Free tier shares its 5/day cap with
// analyze().
export interface AIPresetCard {
  preset_id: string
  title: string
  preview: string
  icon: string
}

export interface AIPresetsResponse {
  presets: AIPresetCard[]
  disclaimer: string
}

export interface AIExplainResponse {
  ticker: string
  preset_id: string
  title: string
  answer: string
  disclaimer: string
  generated_at: string
  model_version: string
  source: "llm_first" | "llm_retry" | "template" | "template_no_llm"
  cached: boolean
}

export const getAIPresets = (): Promise<AIPresetsResponse> =>
  api.get(`/api/v1/public/ai-explain/presets`).then(r => r.data)

export const postAIExplain = (
  ticker: string,
  preset_id: string,
): Promise<AIExplainResponse> =>
  api
    .post(`/api/v1/public/ai-explain`, { ticker, preset_id })
    .then(r => r.data)

// Coverage Tier (feat/coverage-tier-system) — returns the full A/B/C
// rubric breakdown. Backed by a 6h server cache; pass refresh=true only
// for admin/methodology tooling.
import type { CoverageTier } from "@/types/api"
export const getCoverageTier = (ticker: string, refresh = false): Promise<CoverageTier> =>
  api.get(`/api/v1/coverage/${ticker}${refresh ? "?refresh=1" : ""}`).then(r => r.data)

// Sensitivity recompute — POST overrides, get a fresh DCF back.
// Powers the interactive sliders on /analysis/[ticker]; tier-gated
// to paid plans on the backend (free tier receives 403).
export interface RecomputeRequest {
  wacc: number             // decimal, 0.05 .. 0.20
  growth_5y_pct: number    // decimal, -0.05 .. 0.30
  margin_pct: number       // decimal, 0.0 .. 0.60
  terminal_growth?: number // decimal, default 0.03
}

export interface RecomputeScenarioCase {
  iv: number
  mos_pct: number
  growth: number
  wacc: number
  term_g: number
}

export interface RecomputeResponse {
  ticker: string
  fair_value: number
  current_price: number
  margin_of_safety: number
  verdict: string
  wacc: number
  fcf_growth_rate: number
  operating_margin: number
  terminal_growth: number
  bear_case?: number
  base_case?: number
  bull_case?: number
  scenarios?: {
    bear: RecomputeScenarioCase
    base: RecomputeScenarioCase
    bull: RecomputeScenarioCase
  }
  warnings?: string[]
}

export const recomputeDcf = (
  ticker: string,
  body: RecomputeRequest,
): Promise<RecomputeResponse> =>
  api.post(`/api/v1/analysis/${ticker}/recompute`, body).then(r => r.data)

// ── Reverse-DCF Playground (Week-2 manifesto) ──────────────────
// Five-slider interactive DCF. Free tier sees only the WACC slider
// unlocked; paid tier unlocks all 5. The endpoint accepts every
// input regardless of tier — gating is a UX nudge, not enforced
// server-side (see analysis.py docstring for rationale).
export interface DCFPlaygroundRequest {
  wacc: number                 // decimal, 0.06 .. 0.15
  terminal_growth: number      // decimal, 0.0  .. 0.07
  revenue_cagr_yr1_5: number   // decimal, -0.05 .. 0.30
  operating_margin: number     // decimal, 0.0  .. 0.50
  tax_rate?: number            // decimal, 0.0  .. 0.50, default 0.25
}

export interface DCFPlaygroundResponse {
  ticker: string
  fair_value: number
  bear_fv: number
  bull_fv: number
  base_fv: number | null      // canonical cached FV (the analyst base)
  current_price: number
  margin_of_safety: number
  verdict: string | null
  inputs_echo: DCFPlaygroundRequest
  as_of: string
  warnings?: string[]
}

export const recomputeDcfPlayground = (
  ticker: string,
  body: DCFPlaygroundRequest,
): Promise<DCFPlaygroundResponse> =>
  api.post(`/api/v1/analysis/${ticker}/dcf-recompute`, body).then(r => r.data)

export interface DCFReverseEngineerRequest {
  market_price: number
  wacc: number
  terminal_growth: number
  revenue_cagr_yr1_5: number
  operating_margin: number
  tax_rate?: number
}

export interface DCFReverseEngineerResponse {
  ticker: string
  market_price: number
  implied_wacc: number
  implied_terminal_growth: number
  implied_revenue_cagr: number
  iterations: {
    wacc_converged: boolean
    terminal_growth_converged: boolean
    revenue_cagr_converged: boolean
    max_iters: number
  }
  base_inputs: DCFPlaygroundRequest
  as_of: string
}

export const reverseEngineerDcf = (
  ticker: string,
  body: DCFReverseEngineerRequest,
): Promise<DCFReverseEngineerResponse> =>
  api.post(`/api/v1/analysis/${ticker}/dcf-reverse-engineer`, body).then(r => r.data)

// Saved scenarios (Phase-2 of editable-assumptions). Per-user named
// bundles of {assumptions, result} scoped to a ticker. Read is open
// to all auth'd users (free tier just sees an empty list); save is
// paid-only on the backend.
export interface SavedScenario {
  id: number
  ticker: string
  name: string
  assumptions: Record<string, number | string | null>
  result: Record<string, unknown>
  created_at?: string | null
  updated_at?: string | null
}

export interface ListScenariosResponse {
  scenarios: SavedScenario[]
  cap: number
}

export const listScenarios = (
  ticker?: string,
): Promise<ListScenariosResponse> =>
  api
    .get(`/api/v1/scenarios/`, { params: ticker ? { ticker } : undefined })
    .then(r => r.data)

export const saveScenario = (body: {
  ticker: string
  name: string
  assumptions: Record<string, number | string | null>
  result: Record<string, unknown>
}): Promise<SavedScenario> =>
  api.post(`/api/v1/scenarios/`, body).then(r => r.data)

export const deleteScenario = (id: number): Promise<{ ok: boolean }> =>
  api.delete(`/api/v1/scenarios/${id}`).then(r => r.data)

// Sensitivity tornado — per-input ranking of which assumption moves
// FV the most for THIS specific stock. Cached 24h server-side; the
// component should also let react-query cache for the page lifetime.
export interface SensitivityRow {
  input: string
  unit: "bps" | "pct"
  delta_low: number
  delta_high: number
  fv_low: number
  fv_high: number
  swing_pct: number
}

export interface SensitivityResponse {
  ticker: string
  base_fair_value: number
  is_financial: boolean
  sensitivities: SensitivityRow[]
  error?: string
}

export const getSensitivity = (ticker: string): Promise<SensitivityResponse> =>
  api.get(`/api/v1/analysis/${ticker}/sensitivity`).then(r => r.data)

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

/**
 * Time-machine snapshot for the per-analysis Time Slider (Phase 2,
 * 2026-05-25). Returns what YieldIQ thought about the ticker on the
 * requested date — FV / price / MoS / verdict / model version — or
 * `data_available: false` when the date predates fair-value
 * coverage for this ticker.
 */
export interface AsOfAnalysis {
  ticker: string
  as_of_date: string
  fv_as_of_date?: string | null
  price_as_of_date?: string | null
  fair_value: number | null
  current_price: number | null
  mos_pct: number | null
  verdict: string | null
  model_version: string | null
  data_available: boolean
  limitations: string | null
}

export const getAnalysisAsOf = (
  ticker: string,
  isoDate: string,
): Promise<AsOfAnalysis> =>
  api
    .get(`/api/v1/analysis/${ticker}/as-of?date=${isoDate}`)
    .then((r) => r.data)

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
  // Optional — present when the backend's income row carries it.
  // Used by RevenueSankey / EarningsWaterfall to break out the
  // Op Income → Interest leg. Older cached payloads omit it.
  interest_expense?: number | null
  // Bank Schedule III Div III fields (optional — present when the
  // financials_service reader surfaces bank-format columns; sibling
  // backend PR adds these to the response). Today they're undefined
  // for every ticker, which means FinancialStatements' all-null-row
  // filter hides the bank rows until the backend lands the data.
  // See redesign/followups/financial-statements-bugs-phase0.md Bug 3.
  interest_earned?: number | null
  interest_expended?: number | null
  net_interest_income?: number | null
  non_interest_income?: number | null
  total_income?: number | null
  operating_expenses?: number | null
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

// Today's Movers — top gainers / losers in a cohort (default NIFTY 500).
// Server-side cached 60s. Safe to refetchInterval at the same cadence.
export const getTodayMovers = (
  cohort: string = "nifty500",
  limit: number = 5,
): Promise<TodayMoversResponse> =>
  api
    .get("/api/v1/market/today-movers", { params: { cohort, limit } })
    .then(r => r.data)

// ── Landing trust strip — public coverage stats ──
// Real numbers for the 4-tile "stocks/logos/updates/sectors" strip
// on the logged-out landing page. Every field is OPTIONAL; the
// frontend hides any tile whose value is missing rather than render
// "0" (which would look broken). 1h router-side cache.
export interface CoverageStatsResponse {
  /** ISO-8601 — when this response was built (NOT when engine changed). */
  as_of: string
  /** Active stocks in the coverage universe. */
  stocks_covered?: number
  /** Percentage of NIFTY 500 constituents with a real PNG logo on disk. */
  nifty500_logo_coverage_pct?: number
  /** Total cached DCF analyses ever computed. */
  dcf_valuations_generated?: number
  /** Distinct active sectors. */
  sectors_covered?: number
  /** Distinct quarterly financials rows backfilled. */
  bank_quarters_backfilled?: number
  /** ISO-8601 — latest cache-invalidation manifest entry. */
  last_engine_update?: string
  /** Always-present list of upstream data sources. */
  data_sources: string[]
}

export const getCoverageStats = (): Promise<CoverageStatsResponse> =>
  api.get("/api/v1/public/coverage-stats").then(r => r.data)

// ── Sparklines (2026-06-09 — feat/home-sparklines-everywhere) ──
// Batched 7-/30-day close-price series per ticker, powering the inline
// SVG charts on the home-page panels. Server caps the list at 50; the
// frontend calls it once per panel on mount with whichever tickers
// the panel just rendered, never per-row.
export interface SparklineResponse {
  as_of: string | null
  period: "7d" | "30d"
  /** Series keyed by the SAME ticker string the caller asked for. */
  series: Record<string, number[]>
}

export const getSparklines = (
  tickers: string[],
  period: "7d" | "30d" = "7d",
): Promise<SparklineResponse> => {
  if (!tickers || tickers.length === 0) {
    // Cheap short-circuit — avoids a round-trip when the panel mounts
    // with an empty watchlist / portfolio. React Query still memoises
    // on the queryKey, so this is effectively free on subsequent
    // renders within staleTime.
    return Promise.resolve({ as_of: null, period, series: {} })
  }
  return api
    .get("/api/v1/sparklines", {
      params: { tickers: tickers.join(","), period },
    })
    .then(r => r.data)
}

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
  /** Today's change in rupees (per-holding, already × quantity). Null if no live_quote row. */
  day_change_abs: number | null
  /** Today's change in %. Null if no live_quote row. */
  day_change_pct: number | null
  fair_value: number | null
  mos_pct: number | null
  verdict: string
  score: number | null
  saved_at: string
  notes: string
  /**
   * Task #197 (feat/as-of-plumbing, 2026-05-24) — actual
   * live_quotes.as_of for the row that produced current_price. Lets
   * the per-holding freshness chip read genuine quote age (5-15m)
   * instead of the recompute time. Null when the canonical cascade
   * fell through to daily_prices / yfinance (frontend falls back to
   * a neutral "Updated recently" message).
   */
  as_of?: string | null
}

export interface SampleHolding {
  ticker: string
  display_ticker: string
  company_name: string
  sector: string
  quantity: number
  entry_price: number
  invested_value: number
  acquired_on: string
  is_sample: true
}

export interface SamplePortfolio {
  holdings: SampleHolding[]
  summary: { total_invested: number; count: number }
  label: string
  note: string
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
  /**
   * Task #197 (feat/as-of-plumbing) — batch-level freshness: the
   * freshest live_quotes.as_of across all holdings in this response.
   * Used by MoversRail to render one tiered FreshnessStamp for the
   * whole rail. Null when none of the holdings had a live_quotes row.
   */
  as_of?: string | null
  /** Day-97: present only on first-session signups with zero real holdings. */
  sample_portfolio?: SamplePortfolio
}

export const getHoldingsLive = (): Promise<HoldingsLiveResponse> =>
  api.get("/api/v1/portfolio/holdings-live").then(r => r.data)

// ── Morning Briefing (home hero, 2026-06-09) ────────────────────
// Personalized briefing block on /home — portfolio + NIFTY tiles
// plus a 2-4 sentence observational briefing line composed
// server-side from deterministic templates (no LLM). Cached 5 min
// per user_id. SEBI-clean prose: drag/lift/moved/reported only.
export interface MorningBriefingPortfolio {
  total_value: number
  day_change: number
  day_change_pct: number
  /** Last 7 daily basket totals. Empty array when history is cold. */
  sparkline_7d: number[]
}

export interface MorningBriefingMarket {
  nifty_value: number | null
  nifty_change_pct: number | null
  /** Last 7 daily closes for NIFTY 50. Empty when daily store is cold. */
  nifty_sparkline_7d: number[]
}

export interface MorningBriefingResponse {
  /** ISO 8601 IST timestamp the briefing was composed at. */
  as_of: string
  /** Display name — first token of the email local-part. The frontend
   *  prefers the user's saved displayName when set; falls back to this. */
  user_name: string
  /** Null when the user has zero holdings (frontend hides the tile). */
  portfolio: MorningBriefingPortfolio | null
  market: MorningBriefingMarket
  /** 2-4 observational sentences. Always non-empty. */
  briefing_text: string
}

export const getMorningBriefing = (): Promise<MorningBriefingResponse> =>
  api.get("/api/v1/home/morning-briefing").then(r => r.data)

// ── Portfolio Updates Feed (P0 #1) ──────────────────────────────
// Per-holding categorised event stream surfaced as the Portfolio >
// Updates tab. Rows are pre-built nightly by
// scripts/build_updates_feed.py; this endpoint joins them to the
// authenticated user's holdings and paginates reverse-chronologically.
export type PortfolioUpdateCategory =
  | "earnings"
  | "valuations"
  | "intrinsic_updates"
  | "dividends"
  | "insider_trading"
  | "risk_legal"
  | "other"

export interface PortfolioUpdateItem {
  id: number
  ticker: string
  event_at: string | null
  category: PortfolioUpdateCategory
  headline: string
  detail: string
  source_ref: unknown
  created_at: string | null
}

export interface PortfolioUpdatesResponse {
  items: PortfolioUpdateItem[]
  total: number
  limit?: number
  offset?: number
  category?: PortfolioUpdateCategory | null
  portfolio_id: string
}

export const getPortfolioUpdates = (
  opts: { category?: PortfolioUpdateCategory; limit?: number; offset?: number } = {},
): Promise<PortfolioUpdatesResponse> => {
  const params = new URLSearchParams()
  if (opts.category) params.set("category", opts.category)
  if (opts.limit != null) params.set("limit", String(opts.limit))
  if (opts.offset != null) params.set("offset", String(opts.offset))
  const qs = params.toString()
  const suffix = qs ? `?${qs}` : ""
  return api.get(`/api/v1/portfolio/me/updates${suffix}`).then(r => r.data)
}

// ── Portfolio Sum-of-Parts (P0 #2) ──────────────────────────────
// Read-only aggregation over cached DCF fair values. Backend never
// triggers a fresh analysis — holdings without cached FV are surfaced
// via `holdings_without_fv_count` so the card can render a
// LIMITED DATA chip.
export interface PortfolioSumOfPartsResponse {
  market_value: number
  intrinsic_value: number | null
  gap_pct: number | null
  verdict_label: "Overvalued" | "Undervalued" | "Fairly Valued" | null
  holdings_with_fv_count: number
  holdings_without_fv_count: number
  total_holdings: number
  as_of: string
}

export const getPortfolioSumOfParts = (): Promise<PortfolioSumOfPartsResponse> =>
  api.get("/api/v1/portfolio/sum-of-parts").then(r => r.data)

// ── FV-history batch (P0 #5) ────────────────────────────────────
// One round-trip for every ticker in the holdings table — backend
// caps at 50 tickers per request and returns 1y of (date, price,
// fair_value) per ticker for the mini-sparkline.
// Reuses the existing FVHistoryPoint shape above (same DB rows).
export interface FVHistoryBatchEntry {
  has_data: boolean
  data: FVHistoryPoint[]
  summary?: Record<string, unknown>
}

export type FVHistoryBatchResponse = Record<string, FVHistoryBatchEntry>

export const getFVHistoryBatch = (
  tickers: string[],
  years = 1,
): Promise<FVHistoryBatchResponse> =>
  api
    .post("/api/v1/analysis/fv-history/batch", { tickers, years })
    .then(r => r.data)

export const addHolding = (holding: Record<string, unknown>) =>
  api.post("/api/v1/portfolio/holdings", holding).then(r => r.data)

export const removeHolding = (ticker: string) =>
  api.delete(`/api/v1/portfolio/holdings/${ticker}`).then(r => r.data)

// Bulk-clear. DO NOT call without an in-UI confirm modal — this deletes
// every holding for the signed-in user and is not reversible from the
// client. Backend returns { message: "Cleared N holdings" } on success.
export const resetHoldings = () =>
  api.delete("/api/v1/portfolio/holdings").then(r => r.data)

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

// ── Band-shift alerts (sector-percentile USP) ───────────────
// Surfaced as a focused list separate from the generic notifications
// drawer. Each row is one sector-percentile band crossing on a
// watchlisted ticker.
export interface BandShiftAlert {
  id: number
  ticker: string
  from_band: string | null
  to_band: string | null
  from_label: string | null
  to_label: string | null
  fired_at: string | null
  delivered_email: boolean
  delivered_push: boolean
  user_dismissed: boolean
}

export const getBandShifts = (
  limit = 50,
): Promise<{ alerts: BandShiftAlert[] }> =>
  api.get(`/api/v1/alerts/band-shifts?limit=${limit}`).then(r => r.data)

export const dismissBandShift = (alertId: number): Promise<SuccessResponse> =>
  api.post(`/api/v1/alerts/band-shifts/${alertId}/dismiss`).then(r => r.data)

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
  // feat/transparency (2026-05-02) — per-row source badge from
  // `financials.data_source` ("BSE_XBRL", "yfinance", …). Optional
  // for back-compat with cached payloads pre-PR.
  data_source?: string | null
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
  // Canonical (added 2026-04-29 alongside has_peers) — falls back to
  // `peer_ticker` for older cached responses still in flight.
  ticker?: string
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
  // Day-86 (2026-05-22): ROCE surfaced alongside ROE so the cohort-outlier
  // detector has a second profitability axis. Optional — older cached
  // responses lack it.
  roce?: number | null
  pe_ratio: number | null
  // Day-86: cohort-outlier flag. Optional — older cached responses lack it.
  // `is_outlier=true` when the peer is > 2 sigma from the cohort median
  // on ROE, ROCE, or YieldIQ score; `deviates_on` lists the metric(s)
  // that triggered the flag with the cohort median + z-score.
  outlier_flag?: PeerOutlierFlag | null
}

export interface PeerOutlierDeviation {
  metric: "roe" | "roce" | "score" | string
  value: number
  cohort_median: number
  z: number
}

export interface PeerOutlierFlag {
  is_outlier: boolean
  deviates_on: PeerOutlierDeviation[]
}

// Day-80 (2026-05-22): peer-cohort transparency. The public /peers
// endpoint now returns a structured cohort-criteria object alongside
// the raw peer rows so the compare page (and SEO peer card) can
// surface WHY each peer is in the cohort — Tickertape just says
// "industry peers" without ever explaining the rationale.
export interface PeerCohortCriteria {
  sub_sector: string | null
  sector: string | null
  // Inclusive [min%, max%] mcap band, expressed as percent of subject
  // mcap. Example: [11.8, 81.4] = peers range from 12% to 81% of HDFCBANK.
  mcap_band_pct: [number, number] | null
  peer_count: number
  // Plain-English caption, ready to render. Null if neither sub-sector
  // nor mcap band could be synthesised.
  caption: string | null
  // True when the cohort has more than one sub-sector — UI displays
  // a "mixed cohort" disclaimer instead of asserting a single sub-sector.
  mixed_sub_sector: boolean
  // Day-96 (2026-05-22): True when the peer-builder had to fall back
  // past the subject's sub-sector (e.g. Airlines → Industrials because
  // INDIGO has effectively no listed peers). UI renders a warning so
  // the user knows the peers aren't true sub-sector matches.
  cohort_broadened?: boolean
  // Subject's true sub-sector — distinguishes "what we filtered for"
  // from "what we got". Useful for the broadened-cohort disclaimer.
  subject_sub_sector?: string | null
  // Count of returned peers actually sharing subject's sub-sector.
  same_sub_sector_peer_count?: number
}

export interface PublicPeersResponse {
  ticker: string
  // Both fields optional — older cached responses (pre-2026-04-29) lack
  // them. Consumers must default `has_peers` to `peers.length > 0`.
  has_peers?: boolean
  sector_label?: string | null
  // Optional — added 2026-05-22 (Day-80). Older cached responses lack it.
  cohort_criteria?: PeerCohortCriteria | null
  peers: PublicPeerRow[]
}

// Server-side fetch — uses bare fetch() (not axios) because these helpers
// are called from React Server Components and rely on Next.js's fetch
// caching / `next: { revalidate }` extension.
async function publicGet<T>(path: string, revalidateSec: number): Promise<T | null> {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  // Per-deploy cache buster — same rationale as the axios interceptor above.
  // Without this, the Next.js fetch cache at /discover/market-flows could
  // hold an empty `{flows: []}` for the full revalidate window across deploys.
  const sep = path.includes("?") ? "&" : "?"
  const bustedPath =
    BUILD_ID && BUILD_ID !== "dev" ? `${path}${sep}v=${BUILD_ID}` : path
  try {
    const res = await fetch(`${base}${bustedPath}`, { next: { revalidate: revalidateSec } })
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
  source_format?: "rupee_amount" | "pct_of_fv"
}

export interface DividendHistoryResponse {
  ticker: string
  count: number
  total_paid_5y: number | null
  // Counts of how amounts were derived — populated since the
  // %-of-face-value parser landed (2026-05-02). Optional for
  // backwards compatibility with cached responses pre-cutover.
  pct_fv_parsed_count?: number
  unparsed_count?: number
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

// ── NSE bulk/block deals + FII/DII flows (feat/flows) ────────
// All three feed off self-archived NSE snapshots ingested daily by
// .github/workflows/nse_flows_daily.yml. NSE has no historical
// endpoint for these, so coverage extends only as far back as the
// cron has been running.
export interface BulkBlockDeal {
  ticker: string
  deal_date: string                      // ISO YYYY-MM-DD
  deal_type: "bulk" | "block" | string
  client_name: string | null
  buy_sell: "B" | "S" | string
  quantity: number | null
  price: number | null
  exchange: string
}

export interface BulkBlockDealsResponse {
  ticker: string
  count: number
  deals: BulkBlockDeal[]
}

export const getBulkDeals = (
  ticker: string,
  limit: number = 10,
): Promise<BulkBlockDealsResponse | null> =>
  publicGet<BulkBlockDealsResponse>(
    `/api/v1/public/bulk-deals/${ticker}?limit=${limit}`,
    3600,
  )

export const getBlockDeals = (
  ticker: string,
  limit: number = 10,
): Promise<BulkBlockDealsResponse | null> =>
  publicGet<BulkBlockDealsResponse>(
    `/api/v1/public/block-deals/${ticker}?limit=${limit}`,
    3600,
  )

export interface MarketFlowRow {
  trade_date: string                     // ISO YYYY-MM-DD
  category: "FII" | "DII" | string
  buy_value_cr: number | null
  sell_value_cr: number | null
  net_value_cr: number | null
}

export interface MarketFlowsResponse {
  days: number
  count: number
  flows: MarketFlowRow[]
}

export const getMarketFlows = (
  days: number = 30,
): Promise<MarketFlowsResponse | null> =>
  publicGet<MarketFlowsResponse>(
    `/api/v1/public/market-flows?days=${days}`,
    1800,                                // 30 min, matches backend
  )

// ---------------------------------------------------------------------------
// Public indices (NIFTY 50, SENSEX, NIFTY Bank, ...)
// ---------------------------------------------------------------------------
// Mirrors /api/v1/public/indices. Used by the logged-out TickerStrip so the
// indices row populates without an auth token. The auth-gated /market/pulse
// remains the source for logged-in users (richer payload, fear/greed, etc).

export interface PublicIndexRow {
  name: string
  symbol: string | null
  price: number
  change_pct: number | null
  as_of: string | null
}

export interface PublicIndicesResponse {
  indices: PublicIndexRow[]
  count: number
}

export const getPublicIndices = (): Promise<PublicIndicesResponse | null> =>
  publicGet<PublicIndicesResponse>(
    `/api/v1/public/indices`,
    300,                                // 5 min, matches backend
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
  // Day-103c: compounded-growth panel (3y/5y/10y CAGR) — additive,
  // nullable across the board so older cached payloads degrade safely.
  compounded_growth: CompoundedGrowthPanel | null
  last_updated: string | null
}

export interface CompoundedGrowthMetric {
  "3y": number | null
  "5y": number | null
  "10y": number | null
  as_of_fy: number | null
}

/**
 * Stock-CAGR variant: carries a `status` field emitted by the backend
 * (`backend/services/cagr_service.py::_stock_cagr_panel`). Possible
 * values:
 *   - "ok"               — adj_close present and all windows computed
 *   - "partial"          — at least one window resolved
 *   - "rebuild_pending"  — adj_close not yet populated for this ticker
 *   - "db_unavailable"   — DATABASE_URL unset / connect failed
 *
 * 2026-06-09 fix/analysis-ux-fixbatch: HDFCBANK on prod returned
 * `{3y: null, 5y: null, 10y: null, status: "rebuild_pending"}` because
 * the daily_prices.adj_close column hasn't been backfilled for the
 * banking universe yet. The frontend was rendering "Insufficient
 * history" — misleading copy for a 30-year-listed name. Optional
 * `status` lets the sparkline tile distinguish "we genuinely don't
 * have enough years" (a young listing) from "the backfill hasn't run
 * yet" (data-pipeline state, not a stock fact).
 */
export interface CompoundedGrowthStockMetric extends CompoundedGrowthMetric {
  status?: "ok" | "partial" | "rebuild_pending" | "db_unavailable" | null
}

export interface CompoundedGrowthPanel {
  revenue: CompoundedGrowthMetric
  profit: CompoundedGrowthMetric
  roe_avg: CompoundedGrowthMetric
  stock: CompoundedGrowthStockMetric
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
// Stock summary with status — preserves the under_review signal so callers
// (e.g. RecentAnalyses home tile) can render "Under Review" instead of
// dropping the entry. The plain getStockSummary above drops under_review
// silently which is correct for Excel-export / heatmap callers, but the
// home tile needs to honor the recalibration status visibly.
//
// Root-cause discipline (2026-06-07): RecentAnalyses previously rendered
// price + MoS from a localStorage cache written at view-time. That cache
// never invalidated, never honored under_review, and froze unclamped raw
// MoS values (the +200% ITC bug operator caught on /home). The fix is to
// stop caching display data — localStorage holds identity only, and the
// tile re-fetches fresh status per ticker on mount.
// ---------------------------------------------------------------------------

export type StockSummaryStatus =
  | { kind: "ok"; summary: StockSummary }
  | { kind: "under_review"; ticker: string; message?: string }
  | { kind: "unavailable"; ticker: string }

export const getStockSummaryStatus = async (
  ticker: string,
): Promise<StockSummaryStatus> => {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  try {
    const res = await fetch(`${base}/api/v1/public/stock-summary/${ticker}`, {
      next: { revalidate: 300 },
    })
    if (!res.ok) return { kind: "unavailable", ticker }
    const data = await res.json()
    if (data && data.status === "under_review") {
      return {
        kind: "under_review",
        ticker,
        message:
          typeof data.message === "string" ? data.message : undefined,
      }
    }
    if (data && typeof data.current_price === "number") {
      return { kind: "ok", summary: data as StockSummary }
    }
    return { kind: "unavailable", ticker }
  } catch {
    return { kind: "unavailable", ticker }
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

// Google OAuth (feat/google-oauth-signup)
// Flow: button → GET /auth/google/url → browser redirect to Supabase →
// Google consent → Supabase callback to /auth/callback with #access_token=…
// & #id_token=… in the URL hash → callback page POSTs id_token back here.
export interface GoogleAuthResponse extends TokenResponse {
  is_new_user: boolean
}

export const getGoogleOAuthUrl = (redirectTo?: string): Promise<{ url: string }> =>
  api
    .get("/api/v1/auth/google/url", { params: redirectTo ? { redirect_to: redirectTo } : {} })
    .then((r) => r.data)

export const exchangeGoogleIdToken = (
  idToken: string,
  referralCode?: string | null,
): Promise<GoogleAuthResponse> =>
  api
    .post("/api/v1/auth/google", {
      id_token: idToken,
      ...(referralCode ? { referral_code: referralCode } : {}),
    })
    .then((r) => r.data)

// Modern OAuth path — POSTs the Supabase session JWT (not Google's id_token).
// Backend validates it via admin.auth.get_user(jwt). See
// backend.middleware.auth.verify_supabase_session_token for why this
// replaces exchangeGoogleIdToken.
export const loginWithSupabaseSession = (
  accessToken: string,
  referralCode?: string | null,
): Promise<GoogleAuthResponse> =>
  api
    .post("/api/v1/auth/supabase", {
      access_token: accessToken,
      ...(referralCode ? { referral_code: referralCode } : {}),
    })
    .then((r) => r.data)

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

// Account profile (PR #72) — editable display name with 3-edit lifetime cap.
export const updateProfileDisplayName = (
  displayName: string,
): Promise<ProfileUpdateResponse> =>
  api
    .patch("/api/v1/account/profile", { display_name: displayName })
    .then((r) => r.data)

export const completeOnboardingRemote = (body?: {
  last_step?: number
  interests?: string[]
  firstStock?: string | null
}): Promise<{ completed: boolean; completed_at: string }> =>
  api.post("/api/v1/auth/complete-onboarding", body ?? {}, { timeout: 4000 }).then(r => r.data)

// ── Mutual Funds (Phase 3-slim) ──────────────────────────────────────
// Read-only fund detail + landing helpers. SSR-friendly (used inside
// server components in app/(app)/funds), so we use plain fetch on the
// SSR path and the axios client on the client path. Both surfaces hit
// the same backend prefix.

import type {
  FundDetailResponse,
  FundListResponse,
} from "@/types/api"

export const getFund = (scheme_code: string): Promise<FundDetailResponse> =>
  api.get(`/api/v1/funds/${encodeURIComponent(scheme_code)}`).then((r) => r.data)

export const listFunds = (limit = 20): Promise<FundListResponse> =>
  api.get(`/api/v1/funds`, { params: { limit } }).then((r) => r.data)

// SSR-side fetch helpers — bypass the axios client (which depends on
// document cookies) and the BUILD_ID query param. Server components in
// app/(app)/funds use these directly.
export async function fetchFundSSR(
  scheme_code: string,
): Promise<FundDetailResponse | null> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/funds/${encodeURIComponent(scheme_code)}`,
      { next: { revalidate: 300 } },
    )
    if (!res.ok) return null
    return (await res.json()) as FundDetailResponse
  } catch {
    return null
  }
}

export async function fetchFundListSSR(
  limit = 20,
): Promise<FundListResponse> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/funds?limit=${limit}`, {
      next: { revalidate: 300 },
    })
    if (!res.ok) return { funds: [], total: 0 }
    return (await res.json()) as FundListResponse
  } catch {
    return { funds: [], total: 0 }
  }
}

// ── Phase 1 — Fair-Value History contract (Agent B) ──────────────
// Mirrors the existing getAnalysis pattern. Backend stub returns the
// empty shape until Agent A wires the query off fair_value_history.
import type { FairValueHistoryResponse } from "@/types/api"

export const getValuationHistory = (ticker: string): Promise<FairValueHistoryResponse> =>
  api.get(`/api/valuation-history/${ticker}`).then(r => r.data)

export default api
