# YieldIQ — Streamlit → Next.js + FastAPI Migration Spec
**Version:** 1.0
**Date:** 2026-03-25
**Status:** Planning
**Scope:** Full architecture migration maintaining feature parity with YieldIQ v6

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture Audit](#2-current-architecture-audit)
3. [Target Architecture](#3-target-architecture)
4. [FastAPI Backend — Endpoint Design](#4-fastapi-backend--endpoint-design)
5. [Python Modules — Reuse Assessment](#5-python-modules--reuse-assessment)
6. [React Component Hierarchy](#6-react-component-hierarchy)
7. [Authentication Flow — JWT](#7-authentication-flow--jwt)
8. [Infrastructure & Data Layer](#8-infrastructure--data-layer)
9. [Migration Effort Estimates](#9-migration-effort-estimates)
10. [Phased Migration Plan](#10-phased-migration-plan)
11. [Risk Register](#11-risk-register)
12. [Decision Log](#12-decision-log)

---

## 1. Executive Summary

YieldIQ v6 is a ~4,000-line Streamlit monolith. Streamlit's render model — full Python re-execution on every user interaction — creates hard ceilings on performance, concurrency, and UX polish. The goal of this migration is to decouple the analytical Python backend from the presentation layer, enabling:

- **Sub-100ms UI interactions** (React handles local state; API calls are async)
- **Concurrent multi-user scale** (stateless FastAPI workers behind a load balancer)
- **Mobile-ready frontend** (responsive Next.js, no Streamlit iframe constraints)
- **Independent deployment cycles** (frontend and backend deployed separately)
- **A public REST API** as a future revenue surface (developer tier)

The migration is designed to be **non-destructive and additive**: the Streamlit app stays live and serves all users during the transition. The new stack is built alongside it, traffic is cut over tab-by-tab, and the Streamlit app is only decommissioned after Phase 4 validation.

**Technology choices:**

| Layer | Technology | Rationale |
|---|---|---|
| Frontend | Next.js 15 (App Router) + TypeScript | SSR for SEO, React Server Components, Vercel deployment |
| UI Library | shadcn/ui + Tailwind CSS | Matches YieldIQ dark-blue branding, unstyled primitives |
| Charts | Recharts + Plotly React | Recharts for standard charts; Plotly for sensitivity heatmaps |
| Backend | FastAPI + Python 3.11 | Zero rewrite of analytical modules; async I/O; auto OpenAPI docs |
| Task Queue | Celery + Redis | Analysis jobs are 5–15s; must not block HTTP workers |
| Cache | Redis (+ existing diskcache for dev) | Session store, job results, market data TTL |
| Auth | JWT (access + refresh tokens) | Replaces SQLite session tokens; stateless, mobile-compatible |
| Database | PostgreSQL (prod) → SQLite (dev) | Replaces auth.db + portfolio.db; SQLAlchemy ORM |
| Deployment | Vercel (frontend) + Railway/Fly.io (backend) | Cheap, fast, zero-ops |

---

## 2. Current Architecture Audit

### 2.1 What Streamlit Gives Us (and its cost)

Every time a user clicks a button or changes a slider in Streamlit, the **entire Python script re-executes top to bottom**. YieldIQ's app.py is ~4,000 lines. This means:

- Every interaction re-imports modules, re-evaluates conditionals, re-renders HTML
- Session state is stored **per-server-process** — horizontal scaling is impossible without sticky sessions
- Analysis jobs (10–15 seconds) block the WebSocket thread for that user
- No way to push real-time updates to multiple users (alerts, price ticks)
- Mobile UX is constrained to Streamlit's iframe rendering model

### 2.2 Current Data Flow

```
Browser (WebSocket) ──► app.py (runs top-to-bottom on each interaction)
                           │
                           ├─► StockDataCollector.get_all()
                           │       ├─► Finnhub REST API
                           │       └─► yfinance (Yahoo Finance)
                           │
                           ├─► FCFForecaster.predict()      [ML: LR + RF blend]
                           ├─► DCFEngine.intrinsic_value_per_share()
                           ├─► assign_signal()
                           ├─► run_scenarios()
                           └─► Render 11 tabs of HTML/charts
```

### 2.3 Module Inventory

| Module | Lines | Category | Migration Path |
|---|---|---|---|
| `screener/dcf_engine.py` | ~600 | Pure math | Keep as-is, wrap in service class |
| `models/forecaster.py` | ~500 | ML + math | Keep as-is, pre-load model at startup |
| `data/collector.py` | ~800 | I/O (Finnhub + yfinance) | Keep as-is, add async wrapper |
| `data/processor.py` | ~300 | Pure math | Keep as-is |
| `screener/earnings_quality.py` | ~400 | Pure math | Keep as-is |
| `screener/piotroski.py` | ~250 | Pure math | Keep as-is |
| `screener/moat_engine.py` | ~350 | Rules + math | Keep as-is |
| `screener/investment_advisor.py` | ~300 | Rules | Keep as-is |
| `screener/scenarios.py` | ~200 | Pure math | Keep as-is |
| `screener/sector_relative.py` | ~200 | Rules + data | Keep as-is |
| `screener/stock_screener.py` | ~400 | Batch I/O | Keep, run as Celery task |
| `utils/config.py` | ~200 | Config + RF rate | Keep as-is |
| `dashboard/auth.py` | ~600 | SQLite auth | **Replace** with JWT + PostgreSQL |
| `dashboard/tier_gate.py` | ~500 | Feature flags | Extract LIMITS dict → config; replace render functions |
| `dashboard/portfolio.py` | ~800 | SQLite + Streamlit UI | Keep DB layer; rewrite UI layer |
| `dashboard/alerts.py` | ~400 | SQLite + UI | Keep DB layer; rewrite UI |
| `dashboard/ai_chat.py` | ~500 | Gemini API | Keep business logic; rewrite UI |
| `dashboard/pdf_report.py` | ~800 | ReportLab | Keep as-is, serve as file download |
| `dashboard/sheets_export.py` | ~500 | gspread + UI | Keep auth/export logic; rewrite UI |
| `dashboard/morning_brief.py` | ~400 | UI + yfinance | Rewrite in React; keep data fetch |
| `dashboard/onboarding.py` | ~650 | UI + SQLite | Rewrite in React; keep DB helpers |
| `dashboard/app.py` | ~4,000 | UI (all tabs) | **Full rewrite** in React |
| `dashboard/backtest.py` | ~600 | Computation + UI | Keep computation; rewrite charts |
| `dashboard/sector_dashboard.py` | ~700 | Data + UI | Keep data; rewrite charts |

---

## 3. Target Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERNET                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
          ┌────────────────┴────────────────┐
          │                                 │
          ▼                                 ▼
┌──────────────────┐              ┌──────────────────┐
│   Next.js 15     │              │  FastAPI          │
│   (Vercel)       │◄────REST────►│  (Railway/Fly)    │
│                  │              │                   │
│  App Router      │              │  /api/v1/*        │
│  React 19        │              │  Uvicorn (async)  │
│  Tailwind CSS    │              │  4 workers        │
│  shadcn/ui       │              └────────┬──────────┘
│  Recharts        │                       │
│  Plotly React    │              ┌─────────▼──────────┐
└──────────────────┘              │  Celery Workers    │
                                  │  (analysis jobs)   │
                                  └─────────┬──────────┘
                                            │
                    ┌───────────────────────┼───────────────────────┐
                    │                       │                       │
                    ▼                       ▼                       ▼
          ┌─────────────────┐    ┌──────────────────┐   ┌──────────────────┐
          │   PostgreSQL    │    │     Redis         │   │  External APIs   │
          │   (Supabase)    │    │   (Upstash)       │   │                  │
          │                 │    │                   │   │  Finnhub REST    │
          │  users          │    │  Job results      │   │  Yahoo Finance   │
          │  portfolio      │    │  Session cache    │   │  Google Gemini   │
          │  watchlist      │    │  Market data      │   │  Google Sheets   │
          │  alerts         │    │  Rate limits      │   └──────────────────┘
          │  onboarding     │    └───────────────────┘
          └─────────────────┘
```

### 3.1 Request Lifecycle for Stock Analysis

```
1.  User types "AAPL" + clicks Analyse
2.  POST /api/v1/analyze {ticker: "AAPL", wacc_override: null, ...}
    → FastAPI validates auth (JWT), checks tier limit
    → Returns {job_id: "uuid"} immediately (202 Accepted)

3.  Frontend polls GET /api/v1/analyze/{job_id}/status every 2s
    → Celery worker: StockDataCollector.get_all() + DCF pipeline
    → Returns {status: "running", progress: 40, stage: "Forecasting FCF"}

4.  Worker completes → stores result JSON in Redis (TTL 30 min)
    → Status endpoint returns {status: "done", result: {...}}

5.  Frontend renders result (all tabs hydrate from single result object)
    → No further API calls needed for tab switches
```

---

## 4. FastAPI Backend — Endpoint Design

All endpoints are prefixed `/api/v1/`. All protected endpoints require `Authorization: Bearer <access_token>`.

### 4.1 Auth — `/api/v1/auth`

```
POST   /auth/register
  Body:    {email, password, referral_code?}
  Returns: {access_token, refresh_token, user: {id, email, tier}}
  Errors:  409 (email exists), 422 (weak password)

POST   /auth/login
  Body:    {email, password}
  Returns: {access_token, refresh_token, user: {id, email, tier}}
  Errors:  401 (invalid), 429 (rate limited — 5 attempts / 15 min)

POST   /auth/refresh
  Body:    {refresh_token}
  Returns: {access_token, refresh_token}
  Errors:  401 (expired/invalid)

POST   /auth/logout
  Protected. Revokes refresh token (adds to Redis blocklist).

GET    /auth/me
  Protected.
  Returns: {id, email, tier, created_at, usage: {analyses_today, reports_month}}

PATCH  /auth/me
  Protected.
  Body:    {password?, notification_prefs?}
  Returns: Updated user object
```

### 4.2 Analysis — `/api/v1/analyze`

This is the core endpoint — wraps the full DCF pipeline as an async job.

```
POST   /analyze
  Protected. Tier check: analyses_per_day limit.
  Body:
    {
      ticker:          string,           // e.g. "AAPL", "TCS.NS"
      currency:        string,           // "USD" | "INR" | "GBP" | ...
      wacc_override:   float | null,     // null = auto-calculate
      terminal_g:      float,            // default 0.03
      forecast_years:  int,              // 5–15, default 10
      run_monte_carlo: bool              // Pro tier only
    }
  Returns: 202 {job_id: uuid, eta_seconds: 12}
  Errors:  402 (tier limit reached), 400 (invalid ticker)

GET    /analyze/{job_id}/status
  Protected (must be owner).
  Returns:
    {
      status:    "queued" | "running" | "done" | "error",
      progress:  0–100,
      stage:     "Fetching data" | "Forecasting FCF" | "Running DCF" | ...,
      result:    AnalysisResult | null,   // populated when done
      error:     string | null
    }

GET    /analyze/{ticker}/cached
  Protected. Returns last cached result for ticker (if within TTL).
  Returns: AnalysisResult | 404

GET    /analyze/{ticker}/sensitivity
  Protected. Tier check: sensitivity feature.
  Query: ?wacc_center=0.10&tg_center=0.03
  Returns: SensitivityMatrix (WACC × terminal_g grid of IV values)

GET    /analyze/{ticker}/scenarios
  Protected. Tier check: scenarios feature.
  Returns: {bear: ScenarioResult, base: ScenarioResult, bull: ScenarioResult}

GET    /analyze/{ticker}/reverse-dcf
  Protected.
  Query: ?current_price=150.0&wacc=0.10
  Returns: {implied_growth_rate, growth_at_fair_value, commentary}
```

**AnalysisResult schema (shared across endpoints):**
```typescript
interface AnalysisResult {
  ticker:          string
  company_name:    string
  sector:          string
  price:           number
  intrinsic_value: number
  mos_pct:         number        // Margin of Safety %
  signal:          "STRONG BUY" | "BUY" | "WATCH" | "HOLD" | "SELL" | "STRONG SELL"
  wacc:            number
  terminal_g:      number
  forecast_years:  number

  // DCF components
  projected_fcfs:  number[]
  terminal_value:  number
  enterprise_value: number

  // Quality scores
  piotroski_score: number        // 0–9
  earnings_quality: EQResult
  moat:            MoatResult
  confidence:      number        // 0–100

  // Market data
  pe_ratio:        number
  ev_ebitda:       number
  beta:            number
  roe:             number
  fcf_yield:       number

  // Smart money
  insider_sentiment:    string
  institutional_pct:    number
  earnings_track_record: ETRResult

  // Investment plan
  price_targets:   PriceTargets
  holding_period:  HoldingPeriod
  scenarios?:      ScenarioSet   // if tier allows

  // Metadata
  cached_at:       string        // ISO timestamp
  data_sources:    string[]      // ["finnhub", "yfinance"]
}
```

### 4.3 Portfolio — `/api/v1/portfolio`

```
GET    /portfolio
  Protected.
  Returns: {holdings: PortfolioHolding[], summary: PortfolioSummary}

POST   /portfolio
  Protected. Tier check: portfolio feature.
  Body:    {ticker, entry_price, shares, entry_date, notes?}
  Returns: PortfolioHolding (with live_price, pnl_pct fetched)

PATCH  /portfolio/{holding_id}
  Protected.
  Body:    {shares?, notes?, stop_loss?}
  Returns: Updated PortfolioHolding

DELETE /portfolio/{holding_id}
  Protected.
  Returns: 204

GET    /portfolio/summary
  Protected.
  Returns: {total_value, total_cost, total_pnl_pct, annualized_return,
            best_performer, worst_performer, sector_breakdown}

POST   /portfolio/sheets-sync
  Protected. Tier check: sheets_sync.
  Body:    {spreadsheet_url?}   // null = create new
  Returns: {spreadsheet_url, synced_at, rows_written}
```

### 4.4 Watchlist — `/api/v1/watchlist`

```
GET    /watchlist
  Protected.
  Returns: WatchlistItem[] (with live prices, current MoS vs saved IV)

POST   /watchlist
  Protected. Tier check: watchlist_stocks limit.
  Body:    {ticker, target_price?, notes?, iv_at_add, signal_at_add, mos_at_add}
  Returns: WatchlistItem

DELETE /watchlist/{ticker}
  Protected.
  Returns: 204

PATCH  /watchlist/{ticker}
  Protected.
  Body:    {target_price?, notes?}
  Returns: Updated WatchlistItem

GET    /watchlist/prices
  Protected. Bulk live-price refresh for all watchlist tickers.
  Returns: {ticker: live_price}[]  (cached 3 min in Redis)
```

### 4.5 Screener — `/api/v1/screener`

```
POST   /screener/run
  Protected. Tier check: screener_per_week limit.
  Body:
    {
      universe:    "sp500" | "sp1500" | "nse100" | "custom",
      custom_tickers?: string[],
      filters: {
        min_mos_pct?:       number,
        signals?:           string[],
        sectors?:           string[],
        min_piotroski?:     number,
        min_moat_score?:    number,
        max_pe?:            number,
        min_fcf_yield?:     number
      },
      sort_by: "mos_pct" | "signal" | "piotroski" | "moat",
      limit:   number   // max 100 for Premium, 500 for Pro
    }
  Returns: 202 {job_id: uuid, eta_seconds: 120}

GET    /screener/{job_id}/status
  Protected.
  Returns: {status, progress, result: ScreenerResult[] | null}

GET    /screener/last
  Protected. Returns the user's most recent completed screener run.
```

### 4.6 Alerts — `/api/v1/alerts`

```
GET    /alerts
  Protected.
  Returns: Alert[]

POST   /alerts
  Protected.
  Body:
    {
      ticker:        string,
      alert_type:    "price_above" | "price_below" | "signal_change" | "mos_crosses",
      threshold:     number,
      notify_email:  bool,
      notify_push:   bool
    }
  Returns: Alert

PATCH  /alerts/{alert_id}
  Protected.
  Body:    {threshold?, is_active?, notify_email?, notify_push?}
  Returns: Updated Alert

DELETE /alerts/{alert_id}
  Protected.
  Returns: 204

POST   /alerts/check
  Internal endpoint (called by Celery beat every 5 min).
  Returns: {triggered: Alert[]}
```

### 4.7 Market Data — `/api/v1/market`

```
GET    /market/snapshot
  Public (no auth required). Cached 5 min in Redis.
  Returns:
    {
      indices: {
        "S&P 500":  {price, change_pct, ytd_pct},
        "NASDAQ":   {price, change_pct, ytd_pct},
        "Dow":      {price, change_pct, ytd_pct},
        "VIX":      {price, level: "fear"|"neutral"|"greed"},
        "10Y UST":  {yield, change_bp}
      },
      sentiment: {label, vix_value, description},
      updated_at: string
    }

GET    /market/sectors
  Public. Cached 1 hr.
  Returns: SectorPerformance[] (name, ytd_pct, pe, fcf_yield, top_stocks)

GET    /market/price/{ticker}
  Protected. Cached 15 min per ticker.
  Returns: {price, change_pct, day_high, day_low, volume, market_cap}
```

### 4.8 User / Tier / Billing — `/api/v1/user`

```
GET    /user/usage
  Protected.
  Returns:
    {
      tier:              string,
      analyses_today:    int,
      analyses_limit:    int,
      reports_month:     int,
      reports_limit:     int,
      ai_questions_today: int,
      ai_questions_limit: int,
      features:          {[feature: string]: boolean}
    }

POST   /user/ai-question
  Protected. Tier check + daily question counter.
  Body:    {ticker, question, chat_history: Message[]}
  Returns: {answer: string, model: "gemini-2.0-flash"}

POST   /user/generate-pdf
  Protected. Tier check: pdf_reports_per_month.
  Body:    {ticker}   // must have cached analysis
  Returns: Binary PDF (Content-Type: application/pdf)

GET    /user/onboarding
  Protected.
  Returns: {completed: bool, current_step: int}

PATCH  /user/onboarding
  Protected.
  Body:    {step?, completed?}
  Returns: Updated onboarding state
```

### 4.9 Admin — `/api/v1/admin`

```
All endpoints require role: "admin" in JWT claims.

GET    /admin/users?page=1&limit=50&tier=free
POST   /admin/users/{user_id}/set-tier   Body: {tier}
POST   /admin/users/{user_id}/deactivate
DELETE /admin/users/{user_id}/sessions
GET    /admin/metrics   // active users, analyses today, error rate
```

### 4.10 WebSocket — Real-time Job Progress

```
WS     /ws/jobs/{job_id}
  Authenticated via ?token=<access_token> in query string.
  Server pushes:
    {type: "progress", data: {pct: 40, stage: "Forecasting FCF"}}
    {type: "done",     data: AnalysisResult}
    {type: "error",    data: {message: string}}
```

> **Implementation note:** WebSocket is a nice-to-have for Phase 2. Phase 1 polling (every 2s) is acceptable and simpler to implement.

---

## 5. Python Modules — Reuse Assessment

### 5.1 Use As-Is (Zero Changes)

These modules are pure Python with no Streamlit dependencies. They become FastAPI service functions or are called directly from Celery tasks.

| Module | What to do |
|---|---|
| `screener/dcf_engine.py` | Import directly in analysis service |
| `data/processor.py` | Import directly |
| `screener/earnings_quality.py` | Import directly |
| `screener/piotroski.py` | Import directly |
| `screener/moat_engine.py` | Import directly |
| `screener/scenarios.py` | Import directly |
| `screener/investment_advisor.py` | Import directly |
| `screener/reverse_dcf.py` | Import directly |
| `screener/ev_ebitda.py` | Import directly |
| `screener/ddm.py` | Import directly |
| `screener/fcf_yield.py` | Import directly |
| `screener/historical_iv.py` | Import directly |
| `screener/sector_relative.py` | Import directly |
| `screener/sector_guardrails.py` | Import directly |
| `screener/valuation_crosscheck.py` | Import directly |
| `utils/config.py` | Import directly; replace `st.cache_data` with `functools.lru_cache` or Redis |
| `models/industry_wacc.py` | Import directly |
| `dashboard/pdf_report.py` | Call from `/user/generate-pdf` endpoint; return bytes |

### 5.2 Needs Minor Surgery (Remove Streamlit calls only)

These modules contain business logic that's clean, but have scattered `st.*` calls (spinner, session_state, caching) that need to be removed or replaced.

| Module | Streamlit usages to remove | Estimated effort |
|---|---|---|
| `models/forecaster.py` | `@st.cache_data` on model loader | 30 min |
| `data/collector.py` | `@st.cache_data` throughout | 2 hr — replace with Redis/diskcache TTL |
| `dashboard/alerts.py` | DB layer is clean; `st.html`, `st.button` in render functions | 2 hr — split DB layer from render layer |
| `dashboard/portfolio.py` | DB functions are clean; rendering is interleaved | 3 hr — extract DB/compute functions to `services/portfolio.py` |
| `dashboard/morning_brief.py` | `@st.cache_data`, `st.spinner`, `st.html`, `st.form` | 1 hr — extract `_market_snapshot()`, `_live_prices()` as pure functions |
| `dashboard/ai_chat.py` | `st.chat_input`, `st.session_state["chat_history"]` | 1 hr — extract `get_gemini_response()` as pure function |
| `dashboard/sheets_export.py` | `st.spinner`, `st.error`, OAuth callback | 2 hr — extract `sync_to_sheets()` as pure function |

### 5.3 Full Rewrite Required (UI-Only Code)

These are Streamlit rendering functions with no extractable business logic.

| Module | Why | What replaces it |
|---|---|---|
| `dashboard/app.py` | Entire Streamlit app — tabs, layouts, HTML injection | Next.js pages + React components |
| `dashboard/tier_gate.py` (render fns) | `upgrade_prompt()`, `blur_and_lock()`, `tier_badge_html()` | React `<UpgradeGate>` component + middleware |
| `dashboard/auth.py` | SQLite sessions → JWT; bcrypt logic is reusable | FastAPI auth router + `python-jose` |
| `dashboard/onboarding.py` (UI layer) | `@st.dialog`, `st.html()`, `st.button()` | React multi-step modal component |
| `dashboard/tab_helpers.py` | `ccard()`, `ccard_end()`, `apply_koyfin()` | Tailwind CSS utility classes + shadcn Card |
| `dashboard/sector_heatmap.py` (render) | Plotly figures rendered via `st.plotly_chart` | Plotly React component |
| `dashboard/backtest.py` (render) | Mixed computation + Streamlit charts | Extract compute → `services/backtest.py` |
| `tabs/earnings_quality_tab.py` | Streamlit tab | React component |
| `tabs/moat_tab.py` | Streamlit tab | React component |
| `tabs/compare_tab.py` | Streamlit tab | React component |
| `tabs/financials.py` | Streamlit tab | React component |
| `tabs/reverse_dcf_tab.py` | Streamlit tab | React component |

### 5.4 Backend Service Layer Structure (FastAPI)

```
backend/
├── main.py                      # FastAPI app, CORS, middleware
├── routers/
│   ├── auth.py                  # POST /auth/*
│   ├── analyze.py               # POST /analyze, GET /analyze/*
│   ├── portfolio.py             # GET/POST/DELETE /portfolio
│   ├── watchlist.py             # GET/POST/DELETE /watchlist
│   ├── screener.py              # POST /screener/run
│   ├── alerts.py                # GET/POST/DELETE /alerts
│   ├── market.py                # GET /market/*
│   └── user.py                  # GET/PATCH /user/*
├── services/
│   ├── analysis_service.py      # Orchestrates the full DCF pipeline
│   ├── portfolio_service.py     # Portfolio DB operations (extracted from portfolio.py)
│   ├── alert_service.py         # Alert DB + checking logic
│   ├── ai_service.py            # Gemini API wrapper (extracted from ai_chat.py)
│   └── sheets_service.py        # Google Sheets sync (extracted from sheets_export.py)
├── tasks/
│   ├── analyze_task.py          # Celery task: full analysis pipeline
│   ├── screener_task.py         # Celery task: bulk screener run
│   └── alert_check_task.py      # Celery beat: periodic alert checking
├── core/
│   ├── auth.py                  # JWT creation, verification, OAuth2 scheme
│   ├── tier.py                  # Tier limits, feature gates (replaces tier_gate.py logic)
│   ├── database.py              # SQLAlchemy engine, session factory
│   ├── redis.py                 # Redis client, TTL helpers
│   └── config.py                # Settings from env vars (Pydantic BaseSettings)
├── models/                      # SQLAlchemy ORM models
│   ├── user.py
│   ├── portfolio.py
│   ├── watchlist.py
│   ├── alert.py
│   └── onboarding.py
├── schemas/                     # Pydantic request/response models
│   ├── analysis.py              # AnalysisResult, AnalysisRequest, etc.
│   ├── portfolio.py
│   ├── auth.py
│   └── user.py
└── yieldiq/                     # All existing Python modules, symlinked or copied
    ├── data/
    ├── screener/
    ├── models/
    └── utils/
```

---

## 6. React Component Hierarchy

### 6.1 Next.js App Router Structure

```
app/
├── (auth)/
│   ├── login/page.tsx
│   └── register/page.tsx
├── (app)/
│   ├── layout.tsx               # Main app shell: sidebar + header
│   ├── page.tsx                 # Morning Brief home page
│   ├── analyze/
│   │   ├── page.tsx             # Stock analysis entry point
│   │   └── [ticker]/page.tsx    # Analysis results (SSR-friendly)
│   ├── portfolio/page.tsx
│   ├── watchlist/page.tsx
│   ├── screener/page.tsx
│   ├── alerts/page.tsx
│   ├── markets/page.tsx
│   ├── sectors/page.tsx
│   ├── compare/page.tsx
│   └── guide/page.tsx
└── api/                         # Next.js API routes (thin proxies to FastAPI)
    └── [...path]/route.ts       # Proxy with auth header injection
```

### 6.2 Component Tree (Key Pages)

```
<AppShell>
├── <Sidebar>
│   ├── <BrandLogo />
│   ├── <NavLinks />            // Links to all pages
│   ├── <CurrencySelector />
│   ├── <ViewModeToggle />      // Simple / Pro
│   ├── <AdvancedSettings />    // WACC, terminal_g, forecast_yrs sliders
│   ├── <RecentTickers />       // Last 5 tickers (localStorage)
│   ├── <TierBadge />           // Free / Premium / Pro + usage bars
│   └── <ResumeTutorialButton /> // Shows if onboarding incomplete
│
├── <TopBar>
│   ├── <TickerSearchBar />     // Main ticker input
│   ├── <AnalyseButton />       // Triggers POST /analyze
│   └── <UserMenu />            // Avatar, settings, logout
│
└── <PageContent>  (varies by route)


─── Morning Brief Page ─────────────────────────────────
<MorningBriefPage>
├── <MarketSnapshot>
│   ├── <IndexCard ticker="^GSPC" />    // S&P 500
│   ├── <IndexCard ticker="^IXIC" />    // NASDAQ
│   ├── <IndexCard ticker="^DJI" />     // Dow
│   ├── <VixCard />
│   └── <TreasuryCard />
├── <OpportunitiesPanel>
│   └── <OpportunityRow × 5 />         // From analysis history
├── <WatchlistPanel>
│   └── <WatchlistQuickRow × n />
├── <SentimentMeter vix={18.5} />
└── <QuickAnalyzeForm />


─── Stock Analysis Page ────────────────────────────────
<StockAnalysisPage ticker="AAPL">
├── <AnalysisJobPoller jobId="..." />   // Polls status, updates state
├── <AnalysisHero>                      // Price, IV, MoS, Signal badge
│   ├── <LivePriceBadge />
│   ├── <IntrinsicValueBadge />
│   ├── <MarginOfSafetyBar />
│   └── <SignalBadge />
│
├── <AnalysisTabs>
│   ├── tab: "Overview"
│   │   ├── <KeyMetricsGrid />          // PE, beta, ROE, etc.
│   │   ├── <DCFAssumptionsBar />       // WACC, terminal_g, RF rate
│   │   ├── <InvestmentPlanCard />      // Buy/target/stop-loss
│   │   └── <ScenariosCard />           // Bear/base/bull IVs
│   │
│   ├── tab: "DCF Model"
│   │   ├── <FCFProjectionsChart />     // Bar chart: projected FCFs
│   │   ├── <DCFBreakdownTable />       // PV of each year
│   │   └── <SensitivityHeatmap />      // WACC × growth grid
│   │
│   ├── tab: "Quality"
│   │   ├── <MoatScoreCard />
│   │   ├── <PiotroskiCard />
│   │   └── <EarningsQualityCard />
│   │       └── <EarningsTrackRecord /> // Beat rate chart
│   │
│   ├── tab: "Smart Money"
│   │   ├── <InsiderActivityCard />
│   │   └── <InstitutionalOwnershipCard />
│   │
│   ├── tab: "Financials"
│   │   ├── <IncomeStatementTable />
│   │   ├── <CashFlowTable />
│   │   └── <BalanceSheetTable />
│   │
│   ├── tab: "Reverse DCF"
│   │   └── <ReverseDCFCard />
│   │
│   └── tab: "AI Analyst"
│       └── <AIChatPanel ticker="AAPL" />
│           ├── <ChatMessage × n />
│           ├── <ExampleQuestionChips />
│           └── <ChatInput />
│
├── <WatchlistAddPanel />               // Collapsed expander
└── <DownloadRow>
    ├── <DownloadTextReport />
    ├── <DownloadExcelButton />
    └── <DownloadPDFButton />           // Tier-gated


─── Screener Page ───────────────────────────────────────
<ScreenerPage>
├── <ScreenerFilters>
│   ├── <UniverseSelector />
│   ├── <SignalFilter />
│   ├── <SectorFilter />
│   ├── <NumericRangeFilter label="Min MoS%" />
│   └── <RunScreenerButton />
├── <ScreenerProgress />               // Shows during job run
└── <ScreenerResultsTable>
    └── <ScreenerRow × n />
        ├── Ticker, company, signal badge
        ├── MoS%, IV, price
        └── Quality score, Piotroski


─── Shared Components ─────────────────────────────────
components/
├── ui/
│   ├── SignalBadge.tsx         // STRONG BUY / BUY / WATCH / HOLD / SELL
│   ├── TierGate.tsx            // Blur + upgrade overlay
│   ├── UpgradeModal.tsx        // Tier upgrade CTA
│   ├── UsageBar.tsx            // Analyses today / reports this month
│   ├── MetricCard.tsx          // Dark card with title + value
│   ├── LoadingSpinner.tsx
│   └── TooltipHint.tsx         // Help icon + popover
├── charts/
│   ├── FCFBarChart.tsx
│   ├── SensitivityHeatmap.tsx  // Plotly heatmap
│   ├── ScenarioCompareChart.tsx
│   ├── EarningsTrackChart.tsx
│   ├── MonthlyInsiderChart.tsx
│   └── SectorHeatmap.tsx       // Plotly treemap
├── analysis/
│   ├── AnalysisJobPoller.tsx
│   ├── AnalysisHero.tsx
│   └── AnalysisTabs.tsx
└── onboarding/
    ├── OnboardingWizard.tsx    // 5-step modal
    └── OnboardingStep.tsx
```

### 6.3 State Management

| State type | Where it lives | Technology |
|---|---|---|
| Auth tokens | HTTP-only cookies (access) + localStorage (refresh metadata) | Next.js middleware |
| Current analysis result | React Query cache | `@tanstack/react-query` |
| Job polling state | React Query polling | `refetchInterval: 2000` |
| User tier + usage | React Query (revalidate on focus) | — |
| Sidebar settings (WACC, etc.) | Zustand store | Persisted to localStorage |
| Chat history | Zustand store (per ticker) | — |
| Analysis history | Zustand store | Persisted to localStorage (last 20) |
| Onboarding step | React Query + server state | Synced to `/user/onboarding` |

---

## 7. Authentication Flow — JWT

### 7.1 Token Design

```
Access Token:
  Algorithm:  HS256
  Payload:    {sub: user_id, email, tier, role, iat, exp}
  Lifetime:   15 minutes
  Storage:    Memory (React state) — never localStorage

Refresh Token:
  Algorithm:  HS256
  Payload:    {sub: user_id, jti: uuid, iat, exp}
  Lifetime:   30 days (Pro/Premium), 7 days (Free)
  Storage:    HTTP-only Secure cookie (SameSite=Strict)
  Rotation:   New refresh token issued on every use (invalidates old)
  Revocation: JTI added to Redis blocklist on logout
```

### 7.2 Login Flow

```
Client                                    Next.js (BFF)       FastAPI
  │                                            │                  │
  │── POST /auth/login {email, password} ─────►│                  │
  │                                            │── POST /api/v1/auth/login ──►│
  │                                            │                  │── bcrypt verify
  │                                            │                  │── Generate tokens
  │                                            │◄─ {access, refresh, user} ──│
  │                                            │── Set-Cookie: refresh (HTTP-only)
  │◄── {access_token, user} ──────────────────│
  │                                            │
  │   [Stores access_token in memory]          │
  │   [React Query: setQueryData("me", user)]  │
```

### 7.3 Token Refresh Flow (Silent Renewal)

```
Client                                    Next.js (BFF)       FastAPI
  │                                            │                  │
  │ [access_token expires in < 2 min]          │                  │
  │── POST /auth/refresh ──────────────────────►│                  │
  │   (refresh token sent via HTTP-only cookie) │                  │
  │                                            │── POST /api/v1/auth/refresh ─►│
  │                                            │                  │── Verify JTI not in blocklist
  │                                            │                  │── Generate new tokens
  │                                            │◄─ {new_access, new_refresh} ─│
  │                                            │── Update Set-Cookie (new refresh)
  │◄── {access_token} ────────────────────────│
  │                                            │
  │ [Updates in-memory access_token]           │
```

### 7.4 Migration from SQLite Sessions

The current auth.py issues `token = secrets.token_urlsafe(32)` stored in a `sessions` table. During migration:

1. **Phase 1**: Keep existing SQLite session auth running in Streamlit.
2. **Phase 2**: FastAPI implements JWT auth independently for the new frontend.
3. **Phase 3**: Add a migration endpoint: existing users can `POST /auth/migrate` with their Streamlit session token to receive JWT tokens (validates against the old SQLite sessions table before it's retired).
4. **Phase 4**: Streamlit app points to new auth system; SQLite sessions decommissioned.

### 7.5 Tier Enforcement in FastAPI

Replace Streamlit's `can()` function with a FastAPI dependency:

```python
# In each protected endpoint:
async def analyze(
    request: AnalyzeRequest,
    user: User = Depends(get_current_user),
    _: None  = Depends(require_feature("scenarios"))  # tier gate
)
```

The `require_feature` dependency reads from the same LIMITS dict, now stored in `core/tier.py`, and raises `HTTP 402 Payment Required` if the user's tier doesn't have access.

---

## 8. Infrastructure & Data Layer

### 8.1 Database Migration (SQLite → PostgreSQL)

Current SQLite tables and their PostgreSQL equivalents:

| SQLite file | Table(s) | Migration notes |
|---|---|---|
| `auth.db` | `users`, `sessions`, `login_attempts` | sessions → Redis; login_attempts → Redis sorted set |
| `portfolio.db` | `portfolio`, `watchlist` | Direct migration |
| `portfolio.db` | `price_alerts` | Direct migration |
| `portfolio.db` | `institutional_ownership_history` | Direct migration |
| `portfolio.db` | `user_onboarding` | Direct migration |
| `portfolio.db` | `backtest_results` | Direct migration |
| `portfolio.db` | `user_sheets_settings` | Direct migration |

Use Alembic for schema migrations. For the Streamlit→FastAPI transition period, both apps can share the same PostgreSQL database — Streamlit's SQLAlchemy models will be updated first.

### 8.2 Caching Strategy

```
Layer 1: Redis (shared across all workers)
  - Market snapshot data:  TTL 5 min
  - Live stock prices:     TTL 15 min
  - Full analysis results: TTL 30 min (keyed by ticker + wacc + tg + forecast_yrs)
  - Screener results:      TTL 24 hr
  - JWT refresh blocklist: TTL = token expiry
  - Rate limit counters:   TTL = window duration

Layer 2: Celery result backend (Redis)
  - Analysis job results:  TTL 1 hr (long enough for polling)
  - Screener job results:  TTL 24 hr

Layer 3: CDN (Vercel Edge)
  - /market/snapshot:      stale-while-revalidate 5 min
  - Static assets:         immutable (hash in filename)
```

### 8.3 Celery Task Queues

```
Queue: analysis         # Single-stock DCF jobs (5–15s each)
  Workers: 4            # Each handles 1 job at a time (CPU-bound)
  Priority: High

Queue: screener         # Bulk screener jobs (60–300s)
  Workers: 2            # Long-running, lower priority
  Priority: Normal

Queue: alerts           # Periodic alert checking (Celery beat, every 5 min)
  Workers: 1
  Schedule: */5 * * * *

Queue: reports          # PDF generation (ReportLab, ~2s)
  Workers: 2
```

---

## 9. Migration Effort Estimates

Effort is rated by engineer-days (1 ED = 1 senior engineer for 1 day).

### 9.1 Backend (FastAPI)

| Task | Effort | Notes |
|---|---|---|
| Project scaffold (FastAPI, SQLAlchemy, Alembic, Celery, Redis) | 3 ED | Standard setup, good templates exist |
| JWT auth system (login, refresh, logout, middleware) | 3 ED | Replacing SQLite sessions |
| Database migration (SQLite → PostgreSQL + Alembic) | 4 ED | Schema mapping + data migration script |
| Analysis service + Celery task (wrap existing pipeline) | 5 ED | Most Python modules reused as-is |
| WebSocket job progress | 2 ED | Can be deferred (polling works) |
| Portfolio endpoints | 3 ED | DB layer already clean in portfolio.py |
| Watchlist endpoints | 2 ED | Simple CRUD |
| Screener endpoints + Celery task | 4 ED | Long-running job management |
| Alerts endpoints + Celery beat | 3 ED | Logic extracted from alerts.py |
| Market data endpoints (Redis caching) | 2 ED | Extract from morning_brief.py |
| PDF generation endpoint | 1 ED | pdf_report.py needs no changes |
| AI chat endpoint | 1 ED | get_gemini_response() already isolated |
| Google Sheets sync endpoint | 2 ED | OAuth callback handling is complex |
| Tier/billing enforcement (middleware + dependencies) | 3 ED | Replaces tier_gate.py render logic |
| Admin endpoints | 2 ED | admin_cli.py logic → REST |
| Tests (unit + integration, 70% coverage) | 8 ED | Critical for analytical modules |
| Deployment pipeline (CI/CD, Fly.io, env management) | 3 ED | |
| **Backend Total** | **51 ED** | ~10 weeks for 1 engineer |

### 9.2 Frontend (Next.js)

| Task | Effort | Notes |
|---|---|---|
| Project scaffold (Next.js 15, Tailwind, shadcn/ui, React Query, Zustand) | 2 ED | |
| Auth pages (login, register, token management, middleware) | 4 ED | |
| App shell (sidebar, top bar, navigation, responsive) | 4 ED | Replicating sidebar from app.py |
| Morning Brief page (market snapshot, watchlist, sentiment) | 5 ED | |
| Stock Analysis page — hero + tabs scaffold | 4 ED | |
| DCF tab (FCF chart, assumptions, sensitivity heatmap) | 5 ED | Sensitivity heatmap is complex |
| Quality tab (Moat, Piotroski, Earnings Quality, Insider) | 4 ED | |
| Financials tab (3 tables with 5yr history) | 3 ED | |
| Investment plan card + price targets | 2 ED | |
| Scenario comparison chart | 2 ED | |
| AI Chat panel | 3 ED | Streaming responses add complexity |
| Portfolio page (P&L table, charts, position sizing) | 6 ED | |
| Watchlist page | 3 ED | |
| Screener page (filters + results table + job poller) | 5 ED | |
| Alerts page | 3 ED | |
| Compare Stocks page (side-by-side) | 4 ED | |
| Markets / Sector heatmap page (Plotly treemap) | 3 ED | |
| Onboarding wizard (5-step modal) | 3 ED | |
| Tier gating UI (blur overlay, upgrade modal, usage bars) | 3 ED | |
| PDF / Excel download buttons | 1 ED | |
| Responsive / mobile polish | 4 ED | |
| Tests (Vitest + Playwright E2E, key flows) | 6 ED | |
| Deployment (Vercel, env vars, CORS, preview deployments) | 2 ED | |
| **Frontend Total** | **81 ED** | ~16 weeks for 1 engineer |

### 9.3 Total Effort Summary

| Phase | Deliverable | Effort |
|---|---|---|
| Phase 0 | Prep + scaffolding | 10 ED |
| Phase 1 | Backend API (core) | 25 ED |
| Phase 2 | Frontend (analysis + auth) | 35 ED |
| Phase 3 | Frontend (secondary features) | 30 ED |
| Phase 4 | Tests, migration, cutover | 20 ED |
| **Grand total** | Full parity with v6 | **~120 ED** |

With a **2-engineer team** working in parallel on frontend and backend: approximately **4–5 months** to feature parity. With a **3-engineer team**: ~3 months.

> **Cost note:** This estimate assumes senior engineers familiar with both the Python data stack and React. Junior engineers add 30–50% overhead on the analytical modules.

---

## 10. Phased Migration Plan

The Streamlit app (`https://app.yieldiq.com`) stays live throughout. Users are not disrupted.

### Phase 0 — Foundation (Weeks 1–2)

**Goal:** Infrastructure ready, no user-visible changes.

**Tasks:**
- Set up PostgreSQL on Supabase; run SQLite → PostgreSQL migration script
- Set up Redis on Upstash
- Set up FastAPI project scaffold (routers, SQLAlchemy, Alembic, Pydantic schemas)
- Set up Celery + Redis broker (local dev with Docker Compose)
- Set up Next.js 15 project scaffold (App Router, Tailwind, shadcn/ui, React Query)
- Set up CI/CD pipelines (GitHub Actions → Fly.io for backend, Vercel for frontend)
- Configure CORS: FastAPI allows `*.yieldiq.com` origins
- Copy Python analytical modules (`screener/`, `models/`, `data/`, `utils/`) into backend monorepo; **do not modify them yet**

**Deliverable:** `https://api.yieldiq.com` returns `{status: "ok"}`. Database is live. Streamlit app unaffected (still uses its own SQLite files).

**Risk:** DB migration script must be tested on a production backup before going live.

---

### Phase 1 — Backend API (Weeks 3–7)

**Goal:** All API endpoints live and tested. FastAPI is the source of truth for new data.

**Tasks:**
- Implement JWT auth endpoints (`/auth/login`, `/register`, `/refresh`, `/logout`, `/me`)
- Implement analysis pipeline as a Celery task; expose `/analyze` POST + status polling
- Implement `/market/snapshot` (cached, public)
- Implement `/portfolio`, `/watchlist`, `/alerts` CRUD
- Implement `/screener/run` as a Celery task
- Implement `/user/generate-pdf`, `/user/ai-question`
- Write integration tests for all endpoints (pytest + httpx)
- Add API documentation at `https://api.yieldiq.com/docs` (FastAPI auto-generates this)

**Deliverable:** Postman collection + automated tests pass at 80%+ coverage. Backend ready for frontend consumption. **Streamlit still live.**

**Key decision at end of Phase 1:** Run both SQLite (Streamlit) and PostgreSQL (FastAPI) in parallel with a sync script, OR point Streamlit at PostgreSQL directly. Recommendation: **update Streamlit's DB connection to PostgreSQL** at end of Phase 1 so both apps share one database going forward.

---

### Phase 2 — Frontend Core (Weeks 8–14)

**Goal:** `https://next.yieldiq.com` (separate subdomain) is live with core analysis flow.

**Tasks:**
- App shell: sidebar, top bar, navigation, tier badge
- Auth pages: login, register; JWT storage + silent refresh
- Morning Brief landing page (consumes `/market/snapshot`, analysis history from localStorage)
- Stock analysis page: ticker input → job poller → hero → tabs (Overview + DCF + Quality)
- Onboarding wizard (5-step modal, persisted via `/user/onboarding`)
- Tier gate component (blur + upgrade modal)

**Deliverable:** A user can register, log in, analyse a stock, see their results, and add to watchlist on `https://next.yieldiq.com`. No screener, no portfolio, no alerts yet.

**Beta program:** Invite 20–50 power users to test `next.yieldiq.com`. Collect feedback. Keep Streamlit at `app.yieldiq.com` for everyone else.

---

### Phase 3 — Frontend Secondary Features (Weeks 15–20)

**Goal:** Full feature parity. `next.yieldiq.com` matches `app.yieldiq.com`.

**Tasks (can be parallelised):**
- Portfolio page (holdings, P&L, Google Sheets sync)
- Watchlist page (live prices, signal deltas, alerts)
- Alerts page (create, edit, delete)
- Screener page (filters, job poller, results table)
- Compare Stocks page (side-by-side analysis)
- Markets + Sector heatmap page
- Financials tab (income statement, cash flow, balance sheet)
- AI Chat panel (Gemini streaming)
- Excel + PDF downloads
- Mobile responsive polish
- Backtesting page

**Deliverable:** `next.yieldiq.com` is at full feature parity with the Streamlit app.

---

### Phase 4 — Cutover & Decommission (Weeks 21–22)

**Goal:** `app.yieldiq.com` → `next.yieldiq.com`. Streamlit retired.

**Tasks:**
- **Canary rollout:** Route 10% of `app.yieldiq.com` traffic to `next.yieldiq.com` via Cloudflare Workers
- Monitor: error rates, analysis completion time, user session length (should improve)
- If metrics healthy: increase to 50%, then 100% over one week
- Update DNS: `app.yieldiq.com` CNAME → Vercel
- Keep Streamlit running at `legacy.yieldiq.com` for 30 days (fallback for complaints)
- After 30 days with no critical issues: terminate Streamlit deployment

**Rollback plan:** Cloudflare traffic split can be reverted in < 60 seconds.

---

### Migration Timeline (2 engineers)

```
Week:  1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16  17  18  19  20  21  22
       ├───────────┤
       Phase 0: Infrastructure
                   ├───────────────────────┤
                   Phase 1: FastAPI Backend
                                           ├─────────────────────────────┤
                                           Phase 2: Next.js Core Frontend
                                                           ├─────────────────────────────┤
                                                           Phase 3: Full Feature Parity
                                                                                         ├────┤
                                                                                         Phase 4
```

Engineers:
- **Engineer A** (Python/backend): Phases 0–1 full ownership, supports Phase 2+
- **Engineer B** (React/frontend): Phases 2–3 full ownership, reviews Phase 1 API contracts

---

## 11. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| DCF pipeline produces different results in FastAPI vs Streamlit | Medium | Critical | Run 500-stock validation suite comparing outputs before Phase 2 cutover |
| Celery job latency > user expectation (>15s) | Medium | High | Add job queue depth monitoring; provision more workers before launch |
| yfinance/Finnhub rate limits under concurrent load | High | High | Redis-based rate limiter; upgrade Finnhub plan; cache aggressively |
| Google Sheets OAuth callback complexity | Medium | Medium | Defer to Phase 3; use service account where possible |
| User data migration (SQLite → PostgreSQL) loses records | Low | Critical | Full backup + row-count validation before migration |
| JWT refresh token theft (XSS) | Low | High | HTTP-only cookies for refresh token; CSP headers; short access token lifetime |
| Streamlit performance regresses for users during transition | Low | Medium | Streamlit stays on its current infra; no changes to it during Phase 1–2 |
| React component complexity grows beyond estimate | Medium | Medium | Use shadcn/ui + headless components; avoid custom chart components where Plotly works |
| Gemini API costs exceed budget (AI chat feature) | Medium | Medium | Daily hard limit per user enforced at API level; monitor usage in Phase 2 beta |

---

## 12. Decision Log

| # | Decision | Rationale | Alternative Considered |
|---|---|---|---|
| 1 | Next.js App Router (not Pages Router) | Server Components reduce bundle size; built-in SSR for SEO; Vercel-native | Pages Router (stable but being superseded) |
| 2 | FastAPI + Celery (not FastAPI + BackgroundTasks) | Analysis jobs are 5–15s — BackgroundTasks has no retry, no monitoring, no queue visibility | FastAPI BackgroundTasks (too simple for production) |
| 3 | JWT in HTTP-only cookies (not localStorage) | XSS cannot exfiltrate refresh token; CSRF mitigated by SameSite=Strict | localStorage (vulnerable to XSS) |
| 4 | Keep existing Python analytical modules as-is | Zero regression risk on core valuation math; only remove Streamlit imports | Rewrite in TypeScript (too risky; loses all accumulated IP) |
| 5 | PostgreSQL via Supabase (not remain on SQLite) | Multi-worker FastAPI needs shared database; SQLite is single-writer | PlanetScale (MySQL, less compatible with existing code) |
| 6 | React Query for server state (not Redux) | Co-located data fetching with auto-caching, background refetch, optimistic updates | Redux Toolkit (overkill for this data shape) |
| 7 | Zustand for client state (not Context API) | Lightweight; no boilerplate; localStorage persistence built-in | React Context (performance issues at scale; verbose) |
| 8 | Recharts for standard charts + Plotly for heatmaps | Recharts is lighter and more customisable for line/bar charts; Plotly only where interactivity (sensitivity heatmap, sector heatmap) justifies the bundle size | Only Plotly (heavy) or only Recharts (can't do heatmaps well) |
| 9 | Phased migration with separate subdomain | Zero disruption to existing users; allows beta testing; easy rollback | Big-bang rewrite (high risk; no rollback path) |
| 10 | Canary rollout via Cloudflare Workers in Phase 4 | Allows traffic split without application changes; instant rollback | Blue/green deploy (requires two identical infra setups) |

---

*End of spec. Next step: Phase 0 kickoff meeting — agree on team ownership, set up GitHub monorepo, provision cloud accounts.*
