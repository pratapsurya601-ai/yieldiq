"use client"
import { useEffect, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  getAnalysis,
  getChartData,
  getFVHistory,
  getPeers,
  getFinancials,
  getRatiosHistory,
} from "@/lib/api"
import { fetchPrism } from "@/lib/prism"
import AnalysisHero from "@/components/analysis/AnalysisHero"
import AnalysisTabs, { type AnalysisTabDef } from "@/components/analysis/AnalysisTabs"
import InsightCards from "@/components/analysis/InsightCards"
import RedFlagInsights from "@/components/analysis/RedFlagInsights"
import QualityRatios from "@/components/analysis/QualityRatios"
import PromoterPledgePanel from "@/components/analysis/PromoterPledgePanel"
import DividendTracker from "@/components/analysis/DividendTracker"
import NewsWidget from "@/components/analysis/NewsWidget"
import LoadingSteps from "@/components/ui/LoadingSteps"
import PriceChart from "@/components/analysis/PriceChart"
import FinancialBars from "@/components/analysis/FinancialBars"
import FairValueHistory from "@/components/analysis/FairValueHistory"
import FinancialStatements from "@/components/analysis/FinancialStatements"
import PeerComparison from "@/components/analysis/PeerComparison"
import EditorialHero from "@/components/analysis/EditorialHero"
import { FormulasProvider } from "@/components/analysis/MetricTooltip"
import AnalyticalNotes from "@/components/analysis/AnalyticalNotes"
import ReverseDcfPanel from "@/components/analysis/ReverseDcfPanel"
import FreshnessStamp from "@/components/common/FreshnessStamp"
import NarrativeSummary from "@/components/analysis/NarrativeSummary"
import Breadcrumb, { bucketFromMarketCapCr } from "@/components/analysis/Breadcrumb"
import ShareReportCard from "@/components/analysis/ShareReportCard"
import UnlockCTA from "@/components/payg/UnlockCTA"
import UnlockBadge from "@/components/payg/UnlockBadge"
import { usePaygStore } from "@/store/paygStore"
import SensitivityPanel from "@/components/analysis/SensitivityPanel"
import { useAuthStore } from "@/store/authStore"
import {
  formatCurrency,
  formatPct,
  formatCompanyName,
  verdictDisplayLabel,
} from "@/lib/utils"
import { trackStockAnalysed } from "@/lib/analytics"
import Link from "next/link"
import dynamic from "next/dynamic"
import type { PrismData } from "@/components/prism/types"

// Code-split the Time Machine modal — ~12kb of scrubber + capture code that
// only loads when the user actually clicks the ⏱ button.
const PrismTimeMachine = dynamic(
  () => import("@/components/prism/PrismTimeMachine"),
  { ssr: false },
)

/* ------------------------------------------------------------------ */
/*  Client body for /analysis/[ticker]. The parent (page.tsx, server   */
/*  component) fetches the Prism payload server-side and passes it in  */
/*  as `prism` so the editorial hero can render above-the-fold without */
/*  waiting for this component's useQuery data.                         */
/* ------------------------------------------------------------------ */

interface StickyHeaderProps {
  ticker: string
  price: number
  currency: string
  onSave?: () => void
  onAlert?: () => void
  onShare?: () => void
  onTimeMachine?: () => void
}

function StickyHeader({ ticker, price, currency, onSave, onAlert, onShare, onTimeMachine }: StickyHeaderProps) {
  const display = ticker.replace(".NS", "").replace(".BO", "")
  return (
    <div className="sticky top-0 z-20 -mx-4 px-4 h-12 flex items-center justify-between bg-bg/95 backdrop-blur border-b border-border">
      <div className="flex items-baseline gap-3 min-w-0">
        <span className="font-display text-base font-semibold text-ink tracking-tight">
          {display}
        </span>
        <span className="font-mono tabular-nums text-sm text-body truncate">
          {price > 0 ? formatCurrency(price, currency) : "—"}
        </span>
      </div>
      <div className="flex items-center gap-1">
        <IconButton label="Time Machine" onClick={onTimeMachine}>
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <circle cx="12" cy="12" r="9" strokeLinecap="round" strokeLinejoin="round" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 7v5l3 2" />
          </svg>
        </IconButton>
        <IconButton label="Save" onClick={onSave}>
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.322.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.322-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
          </svg>
        </IconButton>
        <IconButton label="Alert" onClick={onAlert}>
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
          </svg>
        </IconButton>
        <IconButton label="Share" onClick={onShare}>
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z" />
          </svg>
        </IconButton>
      </div>
    </div>
  )
}

function IconButton({ label, onClick, children }: { label: string; onClick?: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="inline-flex items-center justify-center w-10 h-10 rounded-lg text-caption hover:text-ink hover:bg-surface active:scale-95 transition"
    >
      {children}
    </button>
  )
}

function EmptyFinancials({ onRefresh }: { onRefresh?: () => void }) {
  return (
    <div className="bg-bg rounded-2xl border border-border p-10 text-center">
      <div className="mx-auto w-12 h-12 rounded-full bg-surface flex items-center justify-center mb-3">
        <svg className="w-6 h-6 text-caption" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h12M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6" />
        </svg>
      </div>
      <p className="text-sm font-medium text-ink">Financials not yet available</p>
      <p className="text-xs text-caption max-w-xs mx-auto mt-1">
        We&rsquo;re still gathering statement data for this ticker.
      </p>
      <button
        type="button"
        onClick={onRefresh}
        className="mt-4 inline-flex items-center px-3 py-2 min-h-[40px] text-xs font-semibold text-brand bg-brand-50 rounded-lg hover:opacity-90 transition"
      >
        Request refresh
      </button>
    </div>
  )
}

interface Props {
  ticker: string
  /** Server-rendered Prism payload — null if fetch failed. */
  prism: PrismData | null
}

export default function AnalysisBody({ ticker, prism }: Props) {
  // Lazy-load pattern: only fetch data for tabs the user actually opens.
  // Previously all 5 queries fired in parallel on mount — peers alone was
  // 12s on cold cache, blocking perceived loading. Now only the critical
  // hero queries (analysis + chart) fire immediately. Tab-specific data
  // fires when the tab is opened, at which point the user expects a
  // fraction-of-a-second wait.
  const [openedTabs, setOpenedTabs] = useState<Set<string>>(() => new Set(["summary"]))

  // Toast for PAYG flow (reuses the styling pattern from account/page.tsx).
  // Lives here so the 429 gate and any inline unlock can share it.
  const [paygToast, setPaygToast] = useState<{ msg: string; tone: "ok" | "err" } | null>(null)
  const showPaygToast = (msg: string, tone: "ok" | "err" = "ok") => {
    setPaygToast({ msg, tone })
    setTimeout(() => setPaygToast(null), 4000)
  }
  const queryClient = useQueryClient()

  // PAYG unlock state — used to suppress the 429 gate flash after a
  // just-completed unlock. The server-side tier bump may lag the client
  // state by one tick, so a refetch can briefly return 429 even though
  // the user has an active unlock. Without this check the user sees
  // "Unlock for ₹99" reappear after they already paid.
  const isPaygUnlockedForTicker = usePaygStore((s) => s.isUnlocked(ticker))

  // Tier gate: paid plans (starter / pro / analyst) get the live
  // sensitivity sliders; free tier sees a static upgrade CTA. This hook
  // MUST stay above every early return below (loading / error / !data /
  // verdict-unavailable) — otherwise the first render bails before the
  // hook is called and the second render (after data lands) calls it,
  // which trips React's hook-order check (#310). See PR #133 (sliders)
  // + the fix in PR #fixme-react310 for the original regression.
  const userTier = useAuthStore((s) => s.tier)
  const canUseSliders =
    userTier === "starter" || userTier === "pro" || userTier === "analyst"

  const { data, isLoading, error } = useQuery({
    queryKey: ["analysis", ticker],
    queryFn: () => getAnalysis(ticker),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
    retry: (failureCount, err) => {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404 || status === 429) return false
      return failureCount < 1
    },
  })

  const { data: chartData } = useQuery({
    queryKey: ["chart-data", ticker, "1m"],
    queryFn: () => getChartData(ticker, "1m"),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
  })

  // PR1 SSR fix (Option C): Prism is now hydrated client-side instead of
  // SSR-fetched. The legacy <AnalysisHero/> renders immediately while this
  // query resolves; once it lands, <EditorialHero/> takes over. Long
  // staleTime + cacheTime so route-level navigations re-use the payload.
  const { data: prismLive } = useQuery({
    queryKey: ["prism", ticker],
    queryFn: () => fetchPrism(ticker),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
  // Prefer the freshest source: SSR-passed prop (legacy callers) → live
  // query result. `prism ?? prismLive` keeps any external caller that
  // still passes a server-rendered payload working.
  const prismResolved = prism ?? prismLive ?? null

  // ─── Deferred queries — fire only when their tab opens ────────────
  useQuery({
    queryKey: ["fv-history", ticker, 3],
    queryFn: () => getFVHistory(ticker, 3),
    enabled: !!ticker && openedTabs.has("history"),
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })
  useQuery({
    queryKey: ["peers", ticker],
    queryFn: () => getPeers(ticker),
    enabled: !!ticker && openedTabs.has("peers"),
    staleTime: 30 * 60 * 1000,
    retry: 1,
  })
  const financialsQuery = useQuery({
    queryKey: ["financials", ticker, "annual"],
    queryFn: () => getFinancials(ticker, "annual", 5),
    enabled: !!ticker && openedTabs.has("financials"),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
  // Lazy-load 10-year ratio history for sparklines on ratio cards. Only fires
  // once a tab that renders <QualityRatios /> opens (Valuation / Quality), so
  // the Overview tab stays lean. Endpoint has a 1-hour server cache + 15-min
  // edge SWR, and the response is ~3-5kB — negligible cost.
  const ratiosHistoryQuery = useQuery({
    queryKey: ["ratios-history", ticker, 10, "annual"],
    queryFn: () => getRatiosHistory(ticker, 10, "annual"),
    enabled:
      !!ticker && (openedTabs.has("valuation") || openedTabs.has("quality")),
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })

  useEffect(() => {
    if (data) {
      const displayTicker = data.ticker.replace(".NS", "").replace(".BO", "")
      const verdict = verdictDisplayLabel(data.valuation.verdict)
      document.title = `${displayTicker} — ${verdict} | YieldIQ`

      const desc = `${data.company.company_name} (${data.ticker}) fair value ₹${data.valuation.fair_value.toFixed(0)} vs price ₹${data.valuation.current_price.toFixed(0)}. YieldIQ Score: ${data.quality.yieldiq_score}/100. ${data.quality.moat} moat.`
      const metaDesc = document.querySelector('meta[name="description"]')
      if (metaDesc) {
        metaDesc.setAttribute("content", desc)
      } else {
        const meta = document.createElement("meta")
        meta.name = "description"
        meta.content = desc
        document.head.appendChild(meta)
      }
      trackStockAnalysed(
        data.ticker,
        data.valuation.verdict,
        data.quality.yieldiq_score
      )
    }
  }, [data])

  const [copiedShare, setCopiedShare] = useState(false)
  const [timeMachineOpen, setTimeMachineOpen] = useState(false)
  const onShare = async () => {
    if (typeof window === "undefined" || !data) return
    const url = window.location.href
    const title = `${data.ticker.replace(".NS", "").replace(".BO", "")} on YieldIQ`
    try {
      if (navigator.share) {
        await navigator.share({ title, url })
      } else {
        await navigator.clipboard.writeText(url)
        setCopiedShare(true)
        setTimeout(() => setCopiedShare(false), 2000)
      }
    } catch {
      /* user dismissed */
    }
  }

  if (isLoading) return <LoadingSteps />
  if (error) {
    const msg = (error as { message?: string })?.message ?? ""
    const is429 = msg.includes("Daily analysis limit reached")
    const is404 = msg.includes("Ticker not found")
    // Race-condition guard: if the user just completed a PAYG unlock,
    // paygStore may flip to unlocked before the next queryClient
    // invalidate completes. Render a skeleton instead of flashing the
    // "Unlock ₹99" CTA again. Once the refetch returns with the unlocked
    // payload, this whole branch unrenders naturally.
    if (is429 && isPaygUnlockedForTicker) {
      return <LoadingSteps />
    }
    const backendNote = (error as {
      response?: { data?: { detail?: { note?: string } | string } }
    })?.response?.data?.detail
    const note =
      typeof backendNote === "object" && backendNote !== null
        ? backendNote.note
        : undefined
    const displayTicker = ticker.replace(".NS", "").replace(".BO", "")
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center pb-20" role="alert" aria-live="polite">
        <div className="mx-auto w-16 h-16 rounded-full bg-[color:var(--color-warning)]/10 flex items-center justify-center mb-4">
          <svg className="w-8 h-8 text-warning" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
        </div>
        <p className="text-lg font-semibold text-ink mb-2">
          {is429 ? "Daily limit reached"
            : is404 ? "Ticker not found"
            : `Could not load ${ticker}`}
        </p>
        <p className="text-sm text-body mb-5 max-w-sm mx-auto">
          {is429
            ? "You've used all your free analyses for today. Upgrade to Pro for unlimited access."
            : is404
              ? (note ?? `We couldn\u2019t find \u201c${displayTicker}\u201d on any data provider. Please check the symbol and try again.`)
              : "Data provider may be temporarily unavailable. Try again in a moment."}
        </p>
        {is429 ? (
          <div className="space-y-4">
            <a href="/pricing" className="inline-flex items-center justify-center px-5 py-2.5 min-h-[44px] bg-brand text-white rounded-lg text-sm font-semibold hover:opacity-90 active:scale-[0.98] transition">
              Upgrade to Analyst
            </a>

            {/* PAYG alternative — one-off \u20B999 unlock for this ticker. */}
            <div className="flex items-center gap-3 max-w-xs mx-auto" role="separator" aria-hidden="true">
              <div className="flex-1 h-px bg-border" />
              <p className="text-[10px] font-semibold text-caption uppercase tracking-wider">or</p>
              <div className="flex-1 h-px bg-border" />
            </div>
            <UnlockCTA
              ticker={ticker}
              source="analysis_gate"
              onUnlocked={() => {
                showPaygToast(`Unlocked for 24h`, "ok")
                // Re-run the blocked queries so the page renders the
                // full analysis immediately without a hard reload.
                queryClient.invalidateQueries({ queryKey: ["analysis", ticker] })
                queryClient.invalidateQueries({ queryKey: ["prism", ticker] })
                queryClient.invalidateQueries({ queryKey: ["chart-data", ticker] })
              }}
              onError={(msg) => showPaygToast(msg, "err")}
            />
          </div>
        ) : is404 ? (
          <a href="/search" className="inline-flex items-center justify-center px-5 py-2.5 min-h-[44px] bg-brand text-white rounded-lg text-sm font-semibold hover:opacity-90 active:scale-[0.98] transition">Search again</a>
        ) : (
          <button onClick={() => window.location.reload()} className="inline-flex items-center justify-center px-5 py-2.5 min-h-[44px] bg-brand text-white rounded-lg text-sm font-semibold hover:opacity-90 active:scale-[0.98] transition">Try again</button>
        )}

        {paygToast && (
          <div
            className={`fixed bottom-20 md:top-20 md:bottom-auto left-1/2 -translate-x-1/2 text-white text-sm font-medium px-4 py-2.5 rounded-lg shadow-lg z-50 max-w-sm text-center ${
              paygToast.tone === "err" ? "bg-red-600" : "bg-gray-900"
            }`}
            role="status"
          >
            {paygToast.msg}
          </div>
        )}
      </div>
    )
  }
  if (!data) {
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center pb-20">
        <p className="text-4xl mb-4">&#9888;&#65039;</p>
        <p className="text-lg font-medium text-ink mb-2">
          Could not load {ticker}
        </p>
        <p className="text-sm text-caption mb-4">
          Analysis data was empty. This is usually a transient
          data-provider hiccup.
        </p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-brand text-white rounded-lg text-sm font-medium"
        >
          Retry
        </button>
      </div>
    )
  }

  const isDegenerate =
    (!data.valuation.current_price || data.valuation.current_price < 1) ||
    (data.valuation.fair_value === 0 &&
      data.valuation.bear_case === 0 &&
      data.valuation.bull_case === 0 &&
      data.quality.yieldiq_score === 0)

  if (data.valuation.verdict === "unavailable" || isDegenerate) {
    const displayTicker = data.ticker.replace(".NS", "").replace(".BO", "")
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center pb-20">
        <p className="text-4xl mb-4">&#9888;&#65039;</p>
        <p className="text-lg font-medium text-ink mb-2">
          Data unavailable for {displayTicker}
        </p>
        <p className="text-sm text-caption mb-4">
          {data.data_issues?.[0] ||
            "We couldn\u2019t fetch reliable financial data for this ticker. It may be delisted, renamed, or temporarily unavailable."}
        </p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-brand text-white rounded-lg text-sm font-medium"
        >
          Try again in a moment
        </button>
      </div>
    )
  }

  const { company, valuation, quality, insights } = data

  const dataLimited =
    (quality.yieldiq_score ?? 0) <= 0 || valuation.fair_value === 0

  const requestedTicker = ticker.toUpperCase()
  const canonicalTicker = data.ticker.toUpperCase()
  const wasAliased = requestedTicker !== canonicalTicker
  const requestedDisplay = requestedTicker.replace(".NS", "").replace(".BO", "")
  const canonicalDisplay = canonicalTicker.replace(".NS", "").replace(".BO", "")

  // FIX Day-3 #4 (2026-04-22): the prior guard looked for a nested
  // `statements.income_statement` shape that the backend has never emitted —
  // `/api/v1/analysis/{ticker}/financials` returns a flat object with
  // `income`, `balance_sheet`, `cash_flow` arrays at the top level (see
  // backend/services/financials_service.py + frontend/src/lib/api.ts
  // FinancialsResponse). The mismatch meant `hasAnyStatement` was always
  // false and every ticker — including TITAN and ADSL which have 3+ years
  // of statements — showed "Financials not yet available".
  const financialsPayload = financialsQuery.data as
    | { income?: unknown[]; balance_sheet?: unknown[]; cash_flow?: unknown[] }
    | undefined
  const hasAnyStatement =
    !!financialsPayload &&
    (((financialsPayload.income?.length ?? 0) > 0) ||
      ((financialsPayload.balance_sheet?.length ?? 0) > 0) ||
      ((financialsPayload.cash_flow?.length ?? 0) > 0))
  const financialsEmpty = financialsQuery.isFetched && !hasAnyStatement

  // Market cap on CompanyInfo is in absolute INR — convert to crores.
  const marketCapCr =
    company.market_cap && company.market_cap > 0
      ? company.market_cap / 1e7
      : null
  const marketCapBucket = bucketFromMarketCapCr(marketCapCr)

  // Operating margin isn't exposed on the analysis payload yet;
  // fall back to a sensible mid-cap default so the slider has a
  // starting point. The user can drag it freely; the backend scales
  // FCF off whatever current margin it derives from enriched data.
  const sensitivityBlock =
    valuation.dcf_reliable && valuation.fair_value > 0 ? (
      canUseSliders ? (
        <SensitivityPanel
          ticker={data.ticker}
          currency={company.currency}
          defaultWacc={valuation.wacc > 0 ? valuation.wacc / 100 : 0.12}
          defaultGrowth={
            valuation.fcf_growth_rate !== 0
              ? valuation.fcf_growth_rate / 100
              : 0.08
          }
          defaultMargin={0.15}
          baseFairValue={valuation.fair_value}
          baseMosPct={valuation.margin_of_safety}
        />
      ) : (
        <div className="bg-bg rounded-2xl border border-dashed border-border p-5 text-center">
          <h2 className="text-sm font-semibold text-ink mb-1">
            Play with the assumptions
          </h2>
          <p className="text-xs text-caption mb-4 max-w-md mx-auto">
            Drag WACC, growth and margin sliders to see how fair value moves
            with your assumptions. Available on Pro and Analyst plans.
          </p>
          <Link
            href="/account?upgrade=true"
            className="inline-flex items-center rounded-full px-5 py-2 text-sm font-medium bg-brand text-white hover:opacity-90 transition"
          >
            Upgrade to play with assumptions
          </Link>
        </div>
      )
    ) : null

  const scenarioBlock = data.scenarios ? (
    <div className="bg-bg rounded-2xl border border-border p-5">
      <h2 className="text-sm font-semibold text-ink mb-4">Scenario Analysis</h2>
      <div className="grid grid-cols-3 gap-3">
        {(["bear", "base", "bull"] as const).map((key) => {
          const sc = data.scenarios[key]
          const label = key === "bear" ? "Bear" : key === "base" ? "Base" : "Bull"
          const color = key === "bear" ? "text-danger" : key === "bull" ? "text-success" : "text-brand"
          return (
            <div key={key} className="text-center p-3 rounded-xl border border-border bg-surface">
              <p className="text-xs text-caption mb-1">{label} case</p>
              <p className={`text-lg font-bold font-mono tabular-nums ${color}`}>
                {formatCurrency(sc.iv, company.currency)}
              </p>
              <p className="text-xs text-caption">MoS: {formatPct(sc.mos_pct)}</p>
            </div>
          )
        })}
      </div>
    </div>
  ) : null

  const tabs: AnalysisTabDef[] = [
    {
      key: "summary",
      label: "Summary",
      content: (
        <div className="space-y-5">
          <InsightCards
            quality={quality}
            insights={insights}
            valuation={valuation}
            currency={company.currency}
            sector={company.sector}
            ticker={company.ticker}
          />
          <RedFlagInsights flags={insights?.red_flags_structured ?? []} />
          {scenarioBlock}
          <ReverseDcfPanel ticker={ticker} />
          <DividendTracker
            dividend={insights?.dividend ?? null}
            currency={company.currency}
            ticker={company.ticker}
          />
          <NewsWidget ticker={ticker} />
        </div>
      ),
    },
    {
      key: "valuation",
      label: "Valuation",
      content: (
        <div className="space-y-5">
          {scenarioBlock}
          {sensitivityBlock}
          <InsightCards
            quality={quality}
            insights={insights}
            valuation={valuation}
            currency={company.currency}
            sector={company.sector}
            ticker={company.ticker}
          />
          <QualityRatios
            quality={quality}
            insights={insights}
            ratioHistory={ratiosHistoryQuery.data ?? null}
          />
        </div>
      ),
    },
    {
      key: "quality",
      label: "Quality",
      content: (
        <div className="space-y-5">
          <InsightCards
            quality={quality}
            insights={insights}
            valuation={valuation}
            currency={company.currency}
            sector={company.sector}
            ticker={company.ticker}
          />
          <QualityRatios
            quality={quality}
            insights={insights}
            ratioHistory={ratiosHistoryQuery.data ?? null}
          />
          <PromoterPledgePanel ticker={ticker} />
          <RedFlagInsights flags={insights?.red_flags_structured ?? []} />
        </div>
      ),
    },
    {
      key: "financials",
      label: "Financials",
      content: financialsEmpty ? (
        <EmptyFinancials onRefresh={() => financialsQuery.refetch()} />
      ) : (
        <div className="space-y-5">
          <FinancialStatements ticker={ticker} currency={company.currency} />
          <div className="bg-bg rounded-2xl border border-border p-5">
            <h2 className="text-sm font-semibold text-ink mb-3">Financial Overview</h2>
            <FinancialBars
              ticker={ticker}
              currency={company.currency}
              revenue={chartData?.financials?.revenue}
              fcf={chartData?.financials?.fcf}
            />
          </div>
        </div>
      ),
    },
    {
      key: "history",
      label: "History",
      content: (
        <div className="space-y-5">
          <FairValueHistory
            ticker={ticker}
            companyName={formatCompanyName(company.company_name)}
            currency={company.currency}
          />
          <div className="bg-bg rounded-2xl border border-border p-5">
            <h2 className="text-sm font-semibold text-ink mb-3">Price History</h2>
            <PriceChart
              ticker={ticker}
              currentPrice={valuation.current_price}
              fairValue={valuation.fair_value}
              currency={company.currency}
            />
          </div>
        </div>
      ),
    },
    {
      key: "peers",
      label: "Peers",
      content: <PeerComparison ticker={ticker} currency={company.currency} />,
    },
  ]

  const exchange = (company.exchange || "NSE").toUpperCase() as "NSE" | "BSE"

  return (
    <FormulasProvider value={data.formulas}>
    <div className="max-w-2xl md:max-w-3xl lg:max-w-6xl mx-auto px-4 pb-20">
      {/* TODO(PR-B, SEBI-compliance): render <PriceTimestamp
           as_of={valuation.as_of ?? null} /> under the current
           price once the backend propagates `as_of` into the
           analysis response (ValuationOutput / StockSummary).
           See backend/services/market_data_service.py — the field
           exists on the market_quotes row but is NOT passed through
           backend/services/analysis/service.py at build time. */}
      <StickyHeader
        ticker={data.ticker}
        price={valuation.current_price}
        currency={company.currency}
        onShare={onShare}
        onTimeMachine={() => setTimeMachineOpen(true)}
      />
      {/* feat/freshness-stamps: price/compute freshness beneath the
          sticky header. Two stamps — one for the quote ("Delayed"),
          one for the overall analysis recompute time ("Recomputed") —
          give users immediate context on how stale the numbers are. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1">
        <FreshnessStamp
          timestamp={valuation.current_price_as_of}
          prefix="Delayed, as of"
        />
        <FreshnessStamp
          timestamp={data.timestamp}
          prefix="Recomputed"
        />
      </div>

      {copiedShare && (
        <div className="mt-2 text-xs text-brand bg-brand-50 border border-border rounded-lg px-3 py-2">
          Link copied to clipboard.
        </div>
      )}

      <div className="py-4 space-y-5">
        {wasAliased && (
          <div className="text-xs text-brand bg-brand-50 border border-border rounded-lg px-3 py-2">
            <span className="font-semibold">{requestedDisplay}</span> has been renamed to{" "}
            <span className="font-semibold">{canonicalDisplay}</span>. Showing {canonicalDisplay} data.
          </div>
        )}

        {dataLimited && (
          <div className="text-xs text-warning bg-[color:var(--color-warning)]/10 border border-border rounded-lg px-3 py-2">
            We&rsquo;re refreshing data for this ticker. Check back in 24 hours.
          </div>
        )}

        {!dataLimited && data.data_confidence !== "high" && (
          <div className={`text-xs font-medium px-3 py-1 rounded-full inline-block ${data.data_confidence === "medium" ? "bg-[color:var(--color-warning)]/10 text-warning" : "bg-[color:var(--color-danger)]/10 text-danger"}`}>
            Data: {data.data_confidence} confidence
          </div>
        )}

        {/* Company name + breadcrumb header */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1.5">
            <h1 className="font-editorial text-2xl md:text-3xl font-semibold text-ink truncate leading-tight">
              {formatCompanyName(company.company_name)}
            </h1>
            <p className="text-xs text-caption truncate flex items-center gap-2 flex-wrap">
              <span>{company.ticker}</span>
              <UnlockBadge ticker={company.ticker} size="sm" />
            </p>
            <Breadcrumb
              exchange={exchange}
              sector={company.sector}
              marketCapBucket={marketCapBucket}
              indices={[]}
            />
          </div>
          <div className="shrink-0 flex items-center gap-3">
            <ShareReportCard ticker={ticker} variant="compact" />
            <Link href={`/compare?stock1=${ticker}`} className="text-xs text-brand hover:underline whitespace-nowrap">
              Compare →
            </Link>
          </div>
        </div>

        {/* AI narrative summary — one-sentence conclusion rendered above
            the Prism hex so users can grasp the verdict in ~2 seconds
            without decoding the full card array. Component returns null
            when data.ai_summary is empty, so no reserved blank space. */}
        <NarrativeSummary summary={data.ai_summary} />

        {/* Editorial hero — Prism-driven. Uses server-rendered prism payload
            when available; falls back to the legacy AnalysisHero when the
            Prism endpoint is unreachable so users still see something.

            FV-clamp consistency fix (NOIDATOLL-class bug, 2026-04-27): when
            the backend router clamped fair_value to a plausible bound
            (FV/PX outside [0.1, 3.0] OR |MoS| ≥ 95% — see
            backend/routers/analysis.py FV bound-clamp block), it overwrites
            valuation.fair_value / margin_of_safety with the clamped numbers
            while leaving scenarios.base.iv / mos_pct untouched. The
            ScenarioGrid, AI summary, and AnalyticalNotes panel then all
            reference the unclamped base case (₹7.36 / +95.2% on NOIDATOLL),
            but the headline FAIR VALUE card showed the clamped derivative
            (₹11.31 / +200%). Three contradictory FVs on one screen.

            Resolution: when the clamp marker is present in data_issues
            (single source of truth — emitted by the same code path that
            does the clamp), promote the base-case scenario's iv/mos_pct
            to the headline so all four surfaces agree. The "Analytical
            notes" caution chip already explains *why* the headline differs
            from any naive (FV − P) / P arithmetic, so users aren't left
            with an unexplained jump. */}
        {(() => {
          const fvClamped = (data.data_issues ?? []).some((s) =>
            typeof s === "string" && s.includes("Fair value clamped"),
          )
          const baseScenario = data.scenarios?.base
          const headlineFairValue =
            fvClamped && baseScenario && baseScenario.iv > 0
              ? baseScenario.iv
              : valuation.fair_value
          const headlineMos =
            fvClamped && baseScenario && Number.isFinite(baseScenario.mos_pct)
              ? baseScenario.mos_pct
              : valuation.margin_of_safety

          return prismResolved ? (
            <EditorialHero
              data={prismResolved}
              fairValue={headlineFairValue}
              currentPrice={valuation.current_price}
              marginOfSafety={headlineMos}
              moat={quality.moat}
              currency={company.currency}
              score100={quality.yieldiq_score}
              grade={quality.grade}
              sectorRank={null}
              trend12m={prismResolved.score_history_12m ?? []}
              marketCapCr={marketCapCr}
              dataLimited={dataLimited}
              redFlags={insights?.red_flags_structured ?? []}
              valuationVerdict={valuation.verdict}
              confidence={valuation.confidence_score}
            />
          ) : (
            <AnalysisHero
              score={quality.yieldiq_score}
              grade={quality.grade}
              confidence={valuation.confidence_score}
              verdict={valuation.verdict}
              fairValue={headlineFairValue}
              currentPrice={valuation.current_price}
              marginOfSafety={headlineMos}
              moat={quality.moat}
              currency={company.currency}
              thesis={data.ai_summary}
              dataLimited={dataLimited}
              ticker={ticker}
            />
          )
        })()}

        {/* Analytical notes — backend-emitted contextual disclaimers
            (premium brand, conglomerate, regulated utility, etc.). Sits
            between the hero and the deep-dive tabs so the caveats land
            in the user's eye before they read the numbers. Renders
            nothing when the array is empty/undefined. */}
        <AnalyticalNotes notes={data.analytical_notes} />

        <AnalysisTabs
          tabs={tabs}
          initial="summary"
          onTabChange={(key) => setOpenedTabs((prev) => new Set(prev).add(key))}
        />

        <div className="bg-gradient-to-r from-[color:var(--color-brand-50)] to-surface border border-border rounded-xl p-4 flex items-center justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink">Share this analysis</p>
            <p className="text-xs text-caption">Prism card tuned for Instagram Story &amp; Twitter vertical</p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <ShareReportCard ticker={ticker} />
            <a
              href={`/report/${ticker}`}
              className="inline-flex items-center justify-center text-xs font-semibold text-brand hover:underline px-2 py-2 min-h-[40px]"
            >
              Text-only report →
            </a>
          </div>
        </div>

        <p className="text-xs text-caption text-center leading-relaxed px-4">
          Model estimates using publicly available data. Not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser.
        </p>
      </div>

      {timeMachineOpen && (
        <PrismTimeMachine
          ticker={data.ticker}
          isOpen={timeMachineOpen}
          onClose={() => setTimeMachineOpen(false)}
        />
      )}
    </div>
    </FormulasProvider>
  )
}
