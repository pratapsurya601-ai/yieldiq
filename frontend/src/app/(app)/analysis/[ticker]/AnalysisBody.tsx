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
import AnnualReportsPanel from "@/components/analysis/AnnualReportsPanel"
import ARSignalsPanel from "@/components/annual-reports/ARSignalsPanel"
import BankKpiPanel from "@/components/banks/BankKpiPanel"
import { isPureBank } from "@/lib/bankTickers"
import InsiderTradingPanel from "@/components/analysis/InsiderTradingPanel"
import BulkBlockDealsPanel from "@/components/analysis/BulkBlockDealsPanel"
import DividendBarChart from "@/components/analysis/DividendBarChart"
import NewsWidget from "@/components/analysis/NewsWidget"
import EarningsCallsWidget from "@/components/analysis/EarningsCallsWidget"
import LoadingSteps from "@/components/ui/LoadingSteps"
import FinancialStatements from "@/components/analysis/FinancialStatements"
import { ChartDrawIn, RevealOnScroll } from "@/components/anim"
import ConcallsPanel from "@/components/analysis/ConcallsPanel"
import ConcallSignalsPanel from "@/components/concall/ConcallSignalsPanel"
import PeerComparison from "@/components/analysis/PeerComparison"
import EditorialHero from "@/components/analysis/EditorialHero"
import StockHeroImage from "@/components/analysis/StockHeroImage"
import {
  VERDICT_COLORS,
  verdictTierFromMos,
} from "@/lib/verdict-colors"
import { FormulasProvider } from "@/components/analysis/MetricTooltip"
import AnalyticalNotes from "@/components/analysis/AnalyticalNotes"
import ConfidenceIndicators from "@/components/analysis/ConfidenceIndicators"
import ScoreCard from "@/components/analysis/ScoreCard"
import StickyScorecard from "@/components/analysis/StickyScorecard"
import ScoreBreakdownPanel from "@/components/analysis/ScoreBreakdownPanel"
import ReverseDcfPanel from "@/components/analysis/ReverseDcfPanel"
import CompoundedGrowthPanel from "@/components/analysis/CompoundedGrowthPanel"
import CompoundedGrowthTrustStrip from "@/components/analysis/CompoundedGrowthTrustStrip"
import NumberedSectionHeader from "@/components/analysis/NumberedSectionHeader"
import TrustStrip, { type TrustStat } from "@/components/analysis/TrustStrip"
import CollapsibleSection from "@/components/personalization/CollapsibleSection"
import StylePickerModal from "@/components/personalization/StylePickerModal"
import PersonalizationBanner from "@/components/personalization/PersonalizationBanner"
import {
  type InvestingStyle,
  type SectionKey,
  CONFIGS,
  DEFAULT_SECTION_ORDER,
  SECTION_EXPLAINERS,
  getStyleFromStorage,
  hasUserSeenPicker,
} from "@/lib/personalization"
import FreshnessStamp from "@/components/common/FreshnessStamp"
import NarrativeSummary from "@/components/analysis/NarrativeSummary"
import WorryIndex from "@/components/analysis/WorryIndex"
import MetricWithContext from "@/components/analysis/MetricWithContext"
import MetricVsSectorChip from "@/components/analysis/MetricVsSectorChip"
import Breadcrumb, { bucketFromMarketCapCr } from "@/components/analysis/Breadcrumb"
import ShareReportCard from "@/components/analysis/ShareReportCard"
import ModelDisclaimer from "@/components/ModelDisclaimer"
import UnlockCTA from "@/components/payg/UnlockCTA"
import UnlockBadge from "@/components/payg/UnlockBadge"
import { usePaygStore } from "@/store/paygStore"
import SensitivityPanel from "@/components/analysis/SensitivityPanel"
import TickerSuggestions from "@/components/analysis/TickerSuggestions"
import AnalysisFAQ from "@/components/analysis/AnalysisFAQ"
import SeeAlsoPeers from "@/components/analysis/SeeAlsoPeers"
import InlinePeerComparison from "@/components/analysis/InlinePeerComparison"
import { useAuthStore } from "@/store/authStore"
import {
  formatCurrency,
  formatPct,
  formatCompanyName,
  verdictDisplayLabel,
  verdictFromMos,
  formatRelativeTime,
  shouldGateVerdict,
} from "@/lib/utils"
import { trackStockAnalysed } from "@/lib/analytics"
import Link from "next/link"
import dynamic from "next/dynamic"
import type { PrismData } from "@/components/prism/types"
import type { AnalysisResponse, Verdict } from "@/types/api"

// Code-split the Time Machine modal — ~12kb of scrubber + capture code that
// only loads when the user actually clicks the ⏱ button.
const PrismTimeMachine = dynamic(
  () => import("@/components/prism/PrismTimeMachine"),
  { ssr: false },
)

/* ------------------------------------------------------------------ */
/*  Code-split below-the-fold + non-Summary-tab panels.                */
/*  Each panel ships in its own chunk and only loads when the user     */
/*  scrolls to / clicks the tab that renders it. SSR is disabled       */
/*  because these are all client-only chart/widget components.         */
/* ------------------------------------------------------------------ */
const chartSkeleton = () => (
  <div className="h-64 animate-pulse rounded-lg bg-slate-100" />
)
const smallSkeleton = () => (
  <div className="h-32 animate-pulse rounded-lg bg-slate-100" />
)

const RevenueSankey = dynamic(() => import("@/components/analysis/RevenueSankey"), {
  ssr: false,
  loading: chartSkeleton,
})
const EarningsWaterfall = dynamic(() => import("@/components/analysis/EarningsWaterfall"), {
  ssr: false,
  loading: chartSkeleton,
})
const FinancialsKpiGrid = dynamic(() => import("@/components/analysis/FinancialsKpiGrid"), {
  ssr: false,
  loading: chartSkeleton,
})
const FairValueHistory = dynamic(() => import("@/components/analysis/FairValueHistory"), {
  ssr: false,
  loading: chartSkeleton,
})
const FinancialBars = dynamic(() => import("@/components/analysis/FinancialBars"), {
  ssr: false,
  loading: chartSkeleton,
})
const FinancialsChartPanel = dynamic(
  () => import("@/components/analysis/FinancialsChartPanel"),
  { ssr: false, loading: chartSkeleton },
)
const FVProjectionFan = dynamic(() => import("@/components/analysis/FVProjectionFan"), {
  ssr: false,
  loading: chartSkeleton,
})
const SensitivityTornado = dynamic(() => import("@/components/analysis/SensitivityTornado"), {
  ssr: false,
  loading: chartSkeleton,
})
const MemoryLane = dynamic(() => import("@/components/analysis/MemoryLane"), {
  ssr: false,
  loading: smallSkeleton,
})
const CommunitySentiment = dynamic(() => import("@/components/analysis/CommunitySentiment"), {
  ssr: false,
  loading: smallSkeleton,
})
const HonestCard = dynamic(() => import("@/components/analysis/HonestCard"), {
  ssr: false,
  loading: smallSkeleton,
})
const BullsBearsPanel = dynamic(() => import("@/components/analysis/BullsBearsPanel"), {
  ssr: false,
  loading: smallSkeleton,
})
const ManifestHistoryPanel = dynamic(() => import("@/components/analysis/ManifestHistoryPanel"), {
  ssr: false,
  loading: smallSkeleton,
})
const ProExcelExportButton = dynamic(() => import("@/components/analysis/ProExcelExportButton"), {
  ssr: false,
})
const PriceChart = dynamic(() => import("@/components/analysis/PriceChart"), {
  ssr: false,
  loading: chartSkeleton,
})

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
          {price > 0 ? formatCurrency(price, currency, ticker) : "—"}
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

/**
 * Data Freshness widget — feat/transparency (2026-05-02),
 * simplified 2026-05-17 (fix/simplify-data-freshness).
 *
 * Default: one compact line — "Last updated 14 hours ago · Sources: …".
 * Power users can expand a <details> panel for per-number provenance.
 *
 * Design goals after user feedback ("WHY WE ARE TELLING THE WHOLE
 * DATA FRESHNESS?"): no ISO timestamps in default view, no internal
 * field names ("live_price_x_shares", "dcf"), humanise sources.
 * Underlying provenance is preserved — just hidden by default.
 */

// Humanise internal provenance tokens to user-facing labels.
function humaniseSource(raw: string | null | undefined): string | null {
  if (!raw) return null
  const s = String(raw).trim()
  if (!s) return null
  const lower = s.toLowerCase()
  if (lower === "live_price_x_shares") return "Derived (price × shares)"
  if (lower === "dcf") return "DCF model"
  if (lower === "nse" || lower === "nse_live") return "Live (NSE)"
  if (lower === "bse" || lower === "bse_live") return "Live (BSE)"
  if (lower === "nse_xbrl") return "NSE XBRL"
  if (lower === "yfinance") return "Live (yfinance)"
  // Day-64 (2026-05-21): audit caught internal "local_db_parquet" /
  // "local_db" / "supabase_cache" dev-name strings leaking into the
  // footer summary line. Humanise so the user never sees raw
  // implementation tokens. Anything else (truly novel source) falls
  // through to the original token --- still better than null but
  // worth filtering at the addSource() humanise step too.
  if (lower === "local_db_parquet" || lower === "local_db") return "YieldIQ database"
  if (lower === "supabase_cache" || lower === "analysis_cache") return "YieldIQ database"
  if (lower === "trusted_db" || lower === "pipeline_db") return "YieldIQ database"
  if (lower === "tier2_cohort" || lower === "story_dcf") return "YieldIQ model"
  return s
}

function DataFreshnessWidget({ data }: { data: AnalysisResponse }) {
  const v = data.valuation
  const c = data.company
  const q = data.quality

  // Collect unique humanised sources for the compact summary line.
  const sourceSet = new Set<string>()
  const addSource = (raw: string | null | undefined) => {
    const h = humaniseSource(raw)
    if (h && !/^derived/i.test(h) && !/model$/i.test(h)) sourceSet.add(h)
  }
  addSource(v.current_price_source)
  addSource(c.market_cap_source)
  addSource(c.shares_outstanding_source)
  addSource(q.revenue_source)
  const sources = Array.from(sourceSet)

  // Build the expandable rows (humanised, relative time, no ISO in body).
  type Row = { label: string; value: string; title?: string }
  const rows: Row[] = []
  const pushRow = (
    label: string,
    sourceRaw: string | null | undefined,
    when: string | null | undefined,
  ) => {
    const src = humaniseSource(sourceRaw)
    const rel = when ? formatRelativeTime(when) : null
    const parts = [src, rel].filter(Boolean) as string[]
    if (parts.length === 0) return
    rows.push({ label, value: parts.join(" · "), title: when ?? undefined })
  }

  if (data.timestamp) {
    rows.push({
      label: "Recomputed",
      value: formatRelativeTime(data.timestamp),
      title: data.timestamp,
    })
  }
  pushRow("Current price", v.current_price_source, v.current_price_as_of)
  pushRow("Fair value", v.valuation_engine_used, v.fair_value_computed_at)
  pushRow("Market cap", c.market_cap_source, c.market_cap_as_of)
  pushRow("Shares", c.shares_outstanding_source, null)
  if (q.latest_filing_period_end) {
    rows.push({ label: "Latest filing", value: q.latest_filing_period_end })
  }
  pushRow("Revenue history", q.revenue_source, null)

  if (rows.length === 0 && !data.timestamp) return null

  const summaryTime = data.timestamp ? formatRelativeTime(data.timestamp) : null
  const summaryBits: string[] = []
  if (summaryTime) summaryBits.push(`Last updated ${summaryTime}`)
  if (sources.length > 0) summaryBits.push(`Sources: ${sources.join(", ")}`)

  return (
    <section
      className="rounded-2xl border border-border bg-bg dark:bg-surface p-4"
      aria-label="Data freshness summary"
    >
      <details className="group">
        <summary
          className="flex items-center justify-between gap-3 cursor-pointer list-none text-[12px] text-caption leading-snug [&::-webkit-details-marker]:hidden"
          title={data.timestamp ?? undefined}
        >
          <span className="truncate">
            {summaryBits.join(" · ")}
          </span>
          <span className="shrink-0 text-[11px] text-caption underline decoration-dotted underline-offset-2 group-open:hidden">
            View details
          </span>
          <span className="shrink-0 text-[11px] text-caption underline decoration-dotted underline-offset-2 hidden group-open:inline">
            Hide details
          </span>
        </summary>
        {rows.length > 0 && (
          <dl className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
            {rows.map((r) => (
              <div
                key={r.label}
                className="flex justify-between gap-3 border-b border-border last:border-0 py-1"
              >
                <dt className="text-caption shrink-0">{r.label}</dt>
                <dd
                  className="text-ink text-right truncate"
                  title={r.title}
                >
                  {r.value}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </details>
    </section>
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
  const authToken = useAuthStore((s) => s.token)
  const authUserId = useAuthStore((s) => s.userId)
  const canUseSliders =
    userTier === "starter" || userTier === "pro" || userTier === "analyst"

  // Phase 4 manifesto (Paradigm 11): record a Memory Lane visit for the
  // signed-in user. Fire-and-forget — never blocks render, never surfaces
  // errors to the user. Re-fires on ticker change so HDFCBANK → INFY
  // navigation counts as two visits, not one.
  useEffect(() => {
    if (!authToken || !authUserId || !ticker) return
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    const clean = ticker
      .toUpperCase()
      .replace(".NS", "")
      .replace(".BO", "")
      .replace(".BSE", "")
      .replace(".NSE", "")
    fetch(`${base}/api/v1/me/ticker-visit/${clean}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
    }).catch(() => {
      // Silent — Memory Lane is additive; a missed beacon just delays
      // the first-visit snapshot by one page load.
    })
  }, [ticker, authToken, authUserId])


  // P0 (2026-04-30): analysis cache + chart + prism all surface live price.
  // Stale prices are the worst UX on this page — drop to 60s so a page that
  // sits open through a price tick re-fetches on the next interaction.
  const { data, isLoading, error } = useQuery({
    queryKey: ["analysis", ticker],
    queryFn: () => getAnalysis(ticker),
    enabled: !!ticker,
    staleTime: 60_000,
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
    staleTime: 60_000,
  })

  // PR1 SSR fix (Option C): Prism is now hydrated client-side instead of
  // SSR-fetched. The legacy <AnalysisHero/> renders immediately while this
  // query resolves; once it lands, <EditorialHero/> takes over. Long
  // staleTime + cacheTime so route-level navigations re-use the payload.
  const { data: prismLive } = useQuery({
    queryKey: ["prism", ticker],
    queryFn: () => fetchPrism(ticker),
    enabled: !!ticker,
    staleTime: 60_000,
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
      // Tab title verdict is derived from MoS (the same number rendered
      // in the hero) via verdictFromMos() so tab and body can never
      // disagree. Falls back to the verdict-string label if MoS is
      // missing/non-finite (e.g. data_limited / unavailable states).
      const mos = data.valuation.margin_of_safety
      // Day-91 (2026-05-22): route the tab title through the same
      // verdict-pill gate the hero uses. Before this, TCS at 67%
      // confidence + Data Limited banner rendered "TCS — Notably
      // Undervalued | YieldIQ" in the browser tab — directly
      // contradicting the page's own data-limited banner. RELIANCE /
      // INDIGO at 41-45% confidence rendered confident verdicts in
      // the tab too. The gate collapses both to "Under Review" /
      // "Low Confidence" using the shared lib/utils helper.
      const gated = shouldGateVerdict({
        dataLimited:
          (data.valuation.verdict || "").toString().toLowerCase() === "data_limited",
        confidence: data.valuation.confidence_score,
        currentPrice: data.valuation.current_price,
        bullCase: data.valuation.bull_case,
        bearCase: data.valuation.bear_case,
        marginOfSafety: mos,
      })
      // Fallback chain: gate > MoS-derived verdict > backend verdict
      // label > neutral "Stock Analysis". The neutral form catches
      // tickers where price / FV / verdict are all null (e.g. data
      // outage on INFY 2026-04-30) so we never render "INFY —  | YieldIQ".
      const mosVerdict =
        mos != null && Number.isFinite(mos) ? verdictFromMos(mos) : ""
      const fallbackVerdict = verdictDisplayLabel(data.valuation.verdict)
      const verdict = gated
        ? "Under Review"
        : mosVerdict || fallbackVerdict || "Stock Analysis"
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
      // Task #181 — wire up the writer side of the home page's
      // "Recent analyses" card. The reader (components/home/v2/
      // RecentAnalyses.tsx) has always pulled from this localStorage
      // key, but nothing ever wrote to it, so the card was empty for
      // every user no matter how many tickers they analysed. We push
      // the freshly-loaded ticker + price + MoS here (deduped on
      // symbol, capped at 5) so the next home-page render has real
      // entries to show. v1 is intentionally localStorage-only — the
      // backend `recent_views` table TODO in the reader still stands.
      try {
        const STORAGE_KEY = "yq:recent-views"
        const raw = window.localStorage.getItem(STORAGE_KEY)
        const existing = raw ? JSON.parse(raw) : []
        const filtered = Array.isArray(existing)
          ? existing.filter(
              (e: { ticker?: unknown }) =>
                e && typeof e.ticker === "string" && e.ticker !== data.ticker,
            )
          : []
        const entry = {
          ticker: data.ticker,
          viewedAt: Date.now(),
          price:
            typeof data.valuation.current_price === "number"
              ? data.valuation.current_price
              : null,
          mos: mos != null && Number.isFinite(mos) ? mos : null,
        }
        const next = [entry, ...filtered].slice(0, 5)
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      } catch {
        // localStorage unavailable (Safari private mode, quota, etc.) —
        // recent-analyses is a nice-to-have, never a hard failure.
      }
    }
  }, [data])

  const [copiedShare, setCopiedShare] = useState(false)
  const [timeMachineOpen, setTimeMachineOpen] = useState(false)

  // ─── Phase 4: investing-style personalization ────────────────────
  // Read once on mount, then react to changes from the picker modal or
  // a same-tab preferences-page write. We keep this in component state
  // (not Zustand) because the surface is narrow — only the Summary tab
  // re-renders when style changes, and SSR must not crash.
  const [activeStyle, setActiveStyle] = useState<InvestingStyle | null>(null)
  const [stylePickerOpen, setStylePickerOpen] = useState(false)
  useEffect(() => {
    // localStorage is a non-React external system — schedule the read
    // through a microtask so the eslint rule `set-state-in-effect`
    // (cascading-render warning) is happy. Same pattern as RAF / IO
    // subscribers used elsewhere in this file (CountUp, etc.).
    queueMicrotask(() => {
      setActiveStyle(getStyleFromStorage())
      // First-paint modal gate (chassis 2026-05-26) — see
      // .audit/competitor-walk-hdfcbank-2026-05-26.md gap #1.
      // The picker previously opened on the very first analysis visit
      // for every visitor (signed-in or anon), covering the verdict
      // cascade and hero photo. Three conditions must all be true
      // before we auto-open it now:
      //   1. The user is signed in (anon visitors never see it — the
      //      preference is meaningless without an account anyway).
      //   2. They have actually browsed the product — at least three
      //      tickers in the local "recent views" log (the same writer
      //      this component already maintains for the home page card).
      //   3. They have not already seen or skipped the picker on this
      //      device.
      // Users can still open the picker via /account/preferences any
      // time. This swaps an unconditional first-paint modal for a
      // delayed nudge to engaged users only.
      if (!hasUserSeenPicker() && authToken) {
        try {
          const raw = window.localStorage.getItem("yq:recent-views")
          const entries = raw ? JSON.parse(raw) : []
          const visitCount = Array.isArray(entries) ? entries.length : 0
          if (visitCount > 2) {
            setStylePickerOpen(true)
          }
        } catch {
          // localStorage unavailable (Safari private mode, quota) — fall
          // through. Better to never show the modal than to show it on
          // first paint by accident.
        }
      }
    })
  }, [authToken])
  // task-#218 (2026-05-26): the Phase-2 wide TimeSlider was replaced by
  // the compact Time Machine chip (PR-B chassis), and the `asOfData`
  // state was left in place with a renamed setter (`_setAsOfData`) +
  // eslint-disable as a placeholder for a future re-wire. The state
  // was never re-wired and stayed dead, so the snapshot-replay
  // branches in the hero JSX have been removed. When the Time Machine
  // chip needs to drive a snapshot view, re-introduce the state via
  // `PrismTimeMachine`'s onSelect callback at that point.
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
        <p className="text-sm text-body mb-4 max-w-sm mx-auto">
          {is429
            ? "You've used all your free analyses for today. Upgrade to Pro for unlimited access."
            : is404
              ? (note ?? `We couldn\u2019t find \u201c${displayTicker}\u201d on any data provider. Please check the symbol and try again.`)
              : "Data provider may be temporarily unavailable. Try again in a moment."}
        </p>
        {is429 ? (
          <div className="space-y-4">
            <a href="/pricing" className="inline-flex items-center justify-center px-4 py-2.5 min-h-[44px] bg-brand text-white rounded-lg text-sm font-semibold hover:opacity-90 active:scale-[0.98] transition">
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
          <>
            {/* Day-106: surface "Did you mean?" hits from the static
                ticker index before the dead-end "Search again" CTA.
                Renders nothing if the backend returns zero matches,
                so the Search button remains the visible fallback. */}
            <TickerSuggestions ticker={ticker} />
            <a href="/search" className="inline-flex items-center justify-center px-4 py-2.5 min-h-[44px] bg-brand text-white rounded-lg text-sm font-semibold hover:opacity-90 active:scale-[0.98] transition">Search again</a>
          </>
        ) : (
          <button onClick={() => window.location.reload()} className="inline-flex items-center justify-center px-4 py-2.5 min-h-[44px] bg-brand text-white rounded-lg text-sm font-semibold hover:opacity-90 active:scale-[0.98] transition">Try again</button>
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

  // P0 frontend gate (2026-05-02): broaden the dataLimited trigger to
  // include the canonical verdict enum. Previously dataLimited fired only
  // when score==0 OR fv==0, so a ticker like ONGC (verdict=data_limited
  // but with stale non-zero FV/score still in the cache) rendered the
  // headline FV ₹X next to a tiny "Data Limited" chip — read as a real
  // FV by users. Now any verdict in {data_limited, under_review,
  // unavailable} suppresses every FV/MoS/score-derived UI element.
  const verdictLower = (valuation.verdict || "").toString().toLowerCase()
  const verdictDataLimited =
    verdictLower === "data_limited" ||
    verdictLower === "under_review" ||
    verdictLower === "under review" ||
    verdictLower === "unavailable"
  const dataLimited =
    verdictDataLimited ||
    (quality.yieldiq_score ?? 0) <= 0 ||
    valuation.fair_value === 0

  const requestedTicker = ticker.toUpperCase()
  const canonicalTicker = data.ticker.toUpperCase()
  const requestedDisplay = requestedTicker.replace(".NS", "").replace(".BO", "")
  const canonicalDisplay = canonicalTicker.replace(".NS", "").replace(".BO", "")
  // Only show the rename banner when the user-visible symbols actually differ.
  // Previously compared raw tickers ("INFY" vs "INFY.NS"), which fired on
  // every page with a suffix mismatch even though the displayed names matched.
  const wasAliased =
    requestedDisplay.toUpperCase() !== canonicalDisplay.toUpperCase()

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
        <div className="bg-bg rounded-2xl border border-dashed border-border p-4 text-center">
          <h2 className="text-sm font-semibold text-ink mb-1">
            Play with the assumptions
          </h2>
          <p className="text-xs text-caption mb-4 max-w-md mx-auto">
            Drag WACC, growth and margin sliders to see how fair value moves
            with your assumptions. Available on Pro and Analyst plans.
          </p>
          <Link
            href="/account?upgrade=true"
            className="inline-flex items-center rounded-full px-4 py-2 text-sm font-medium bg-brand text-white hover:opacity-90 transition"
          >
            Upgrade to play with assumptions
          </Link>
        </div>
      )
    ) : null

  // Alpha-Spread restyle (2026-05-25): the 3 bear/base/bull cards are
  // replaced by a single fan-out projection chart. Same data, denser
  // visualization, with a "Show numbers" toggle baked into the chart for
  // users who want the legacy table view.
  const scenarioBlock = data.scenarios && !dataLimited ? (
    <FVProjectionFan
      ticker={ticker}
      currency={company.currency}
      currentPrice={valuation.current_price}
      scenarios={data.scenarios}
    />
  ) : null

  // #ASD-restyle (2026-05-25): TrustStrip data for the Summary tab's
  // numbered sections. Real fields from the analysis payload only —
  // no mock values, no fake stars. If a field is null, value renders as
  // "—" (neutral); if every stat is null upstream, the strip omits itself.
  const scenarioAccent = (m: number | null | undefined) => {
    if (m === null || m === undefined || !Number.isFinite(m)) return "neutral" as const
    return m >= 0 ? ("green" as const) : ("red" as const)
  }
  const scenariosTrustStats: TrustStat[] | null = data.scenarios && !dataLimited
    ? [
        {
          label: "Bear Discount",
          value: Number.isFinite(data.scenarios.bear?.mos_pct)
            ? formatPct(data.scenarios.bear.mos_pct)
            : "—",
          accent: scenarioAccent(data.scenarios.bear?.mos_pct),
        },
        {
          label: "Base Discount",
          value: Number.isFinite(data.scenarios.base?.mos_pct)
            ? formatPct(data.scenarios.base.mos_pct)
            : "—",
          accent: scenarioAccent(data.scenarios.base?.mos_pct),
        },
        {
          label: "Bull Discount",
          value: Number.isFinite(data.scenarios.bull?.mos_pct)
            ? formatPct(data.scenarios.bull.mos_pct)
            : "—",
          accent: scenarioAccent(data.scenarios.bull?.mos_pct),
        },
        ...(Number.isFinite(valuation.confidence_score)
          ? [{
              label: "Model Confidence",
              value: `${Math.round(valuation.confidence_score)}/100`,
              accent: "neutral" as const,
            }]
          : []),
      ]
    : null

  const dividendData = insights?.dividend ?? null
  const dividendTrustStats: TrustStat[] | null = (() => {
    if (!dividendData || !dividendData.has_dividends) return null
    const cards: TrustStat[] = []
    if (dividendData.current_yield_pct !== null && Number.isFinite(dividendData.current_yield_pct)) {
      cards.push({
        label: "Yield",
        value: `${dividendData.current_yield_pct.toFixed(2)}%`,
        accent: "neutral",
      })
    }
    if (dividendData.payout_ratio_pct !== null && Number.isFinite(dividendData.payout_ratio_pct)) {
      cards.push({
        label: "Payout",
        value: `${dividendData.payout_ratio_pct.toFixed(0)}%`,
        accent: "neutral",
      })
    }
    if (dividendData.consecutive_years > 0) {
      cards.push({
        label: "Consecutive Years",
        value: String(dividendData.consecutive_years),
        accent: "green",
      })
    }
    return cards.length >= 2 ? cards : null
  })()

  // ─── Phase 4 personalization: build the Summary-tab section map ────
  // Each entry is a fully-rendered ReactNode. Sections that don't apply
  // (e.g. honest_card on legacy cached payloads, scenarios when
  // dataLimited) resolve to null and get filtered before render.
  const config = activeStyle ? CONFIGS[activeStyle] : null
  const sectionOrder: SectionKey[] = config?.sectionOrder ?? DEFAULT_SECTION_ORDER

  const summarySectionMap: Record<SectionKey, React.ReactNode> = {
    // chassis(PR-A) 2026-05-26: InsightCards + RedFlagInsights are
    // intentionally not rendered on the Summary tab. They appear on
    // the Valuation and Quality tabs respectively; surfacing them
    // here again was the root cause of the "reads as 4 different
    // products stacked vertically" feedback. The map keys remain
    // (and the personalization configs still reference them) so the
    // picker keeps its full vocabulary, but the renderableSections
    // filter strips null entries before mapping.
    insight_cards: null,
    red_flags: null,
    scenarios: scenarioBlock ? (
      <>
        {scenariosTrustStats ? (
          <TrustStrip stats={scenariosTrustStats} ariaLabel="Scenario highlights" />
        ) : null}
        {scenarioBlock}
      </>
    ) : null,
    bulls_bears: (
      <BullsBearsPanel
        bulls={data.bulls_say}
        bears={data.bears_say}
        updated={data.thesis_updated}
      />
    ),
    honest_card: data.honest_card ? <HonestCard card={data.honest_card} /> : null,
    // Competitor-walk gap #3 (2026-05-26): inline cohort table so users
    // don't have to leave the page to see peer context. Self-empties to
    // a neutral notice when the cohort is unavailable.
    peers: (
      <InlinePeerComparison ticker={ticker} currency={company.currency} />
    ),
    compounded_growth: (
      <>
        <CompoundedGrowthTrustStrip ticker={ticker} />
        {/* Tickertape density trick #2 (2026-05-27): inline sector
            context next to the headline ROE so the user gets
            "vs sector" framing without leaving the page. The chip
            self-hides when either side is null. */}
        {data.sector_medians?.roe != null && quality.roe != null && (
          <div className="mt-2">
            <MetricVsSectorChip
              label="ROE"
              value={quality.roe}
              unit="%"
              sectorMedian={data.sector_medians.roe}
              format="better-higher"
            />
          </div>
        )}
        <CompoundedGrowthPanel ticker={ticker} />
      </>
    ),
    financials_chart: (
      <FinancialsChartPanel ticker={ticker} currency={company.currency} />
    ),
    reverse_dcf: !dataLimited ? <ReverseDcfPanel ticker={ticker} /> : null,
    dividends: (
      <>
        {dividendTrustStats ? (
          <TrustStrip stats={dividendTrustStats} ariaLabel="Dividend highlights" />
        ) : null}
        {/* Tickertape density trick #2 (2026-05-27): inline sector
            context for dividend yield (and payout when available).
            Each chip self-hides when its sector median is null —
            sectors with no cohort-level payout signal (banks,
            cyclical metals) collapse to nothing rather than render
            "vs sector —". */}
        {(dividendData?.has_dividends &&
          ((data.sector_medians?.div_yield != null &&
            dividendData.current_yield_pct != null))) && (
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
            <MetricVsSectorChip
              label="Yield"
              value={dividendData.current_yield_pct}
              unit="%"
              sectorMedian={data.sector_medians?.div_yield ?? null}
              format="better-higher"
            />
          </div>
        )}
        {/* Visual Richness #2: replaced the collapsed DividendTracker
            details panel with a 10-year DPS bar chart + payout overlay.
            The 3 KPI tiles (Yield / Payout / Consecutive Years) above
            are unchanged. */}
        <DividendBarChart
          dividend={insights?.dividend ?? null}
          currency={company.currency}
          ticker={company.ticker}
        />
      </>
    ),
    news: <NewsWidget ticker={ticker} />,
    earnings_calls: <EarningsCallsWidget ticker={ticker} />,
    community: (
      <CommunitySentiment ticker={ticker} companyName={company.company_name} />
    ),
  }

  // Filter sections that have no content for this ticker, then renumber
  // so the visible numerals are always 1..N (no gaps).
  const renderableSections = sectionOrder.filter(
    (k) => summarySectionMap[k] != null,
  )

  const tabs: AnalysisTabDef[] = [
    {
      key: "summary",
      label: "Summary",
      content: (
        // PR-D chassis: outer container uses editorial whitespace
        // (space-y-16 md:space-y-20) so each numbered section reads as
        // its own beat rather than another row in a stack. Each
        // CollapsibleSection child is wrapped in the canonical
        // rounded-2xl card surface below.
        //
        // chassis(PR-A) 2026-05-26: InsightCards + RedFlagInsights are
        // intentionally excluded from the Summary tab (they appear on
        // Valuation / Quality respectively). The summarySectionMap
        // returns null for those keys, so the personalization picker's
        // vocabulary stays whole but the duplicate render is gone.
        <div className="space-y-16 md:space-y-20">
          {/* Phase-3 (2026-05-25) — The Worry Index sits between the
              hero / confidence indicators and the numbered sections so
              the user gets one emotional read before the rest of the
              page elaborates. Self-hides when worry_index is absent. */}
          <WorryIndex worry={data.worry_index ?? null} />

          {/* Phase 4 personalization: persisted style controls section
              order, default-expanded set, and Beginner-mode explainers.
              Verdict colour cascade still owns the hero — accent only
              applies to numbered headers and dividers inside this map.
              When activeStyle is null, defaultExpanded is forced true
              for every section, preserving the legacy UX exactly.
              Each item is wrapped in the PR-D canonical card surface
              (rounded-2xl border border-border bg-bg p-6). */}
          {renderableSections.map((key, idx) => {
            const number = idx + 1
            const defaultExpanded = config
              ? config.defaultExpanded.includes(key)
              : true
            const explainer =
              config?.showSectionExplainers ? SECTION_EXPLAINERS[key] : null
            return (
              <div key={key} className="rounded-2xl border border-border bg-bg p-6">
                <CollapsibleSection
                  sectionKey={key}
                  number={number}
                  defaultExpanded={defaultExpanded}
                  accentHue={config?.accentHue}
                  explainer={explainer}
                >
                  {summarySectionMap[key]}
                </CollapsibleSection>
              </div>
            )
          })}

          {/* PR-B (chassis): Phase 4 manifesto (Paradigm 11) personal
              Memory Lane. Relocated from just-under-hero to AFTER the
              last numbered section so the top-half no longer reads as
              4 stacked products. Component returns null for anon users,
              first-time visitors, or when no prior visit exists. */}
          <MemoryLane ticker={ticker} companyName={company.company_name} />
        </div>
      ),
    },
    {
      key: "valuation",
      label: "Valuation",
      content: (
        <div className="space-y-4">
          {scenarioBlock}
          {sensitivityBlock}
          {valuation.dcf_reliable && valuation.fair_value > 0 ? (
            <SensitivityTornado
              ticker={data.ticker}
              currency={company.currency}
            />
          ) : null}
          <InsightCards
            quality={quality}
            insights={insights}
            valuation={valuation}
            currency={company.currency}
            sector={company.sector}
            ticker={company.ticker}
            analystConsensus={data.analyst_consensus ?? null}
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
        <div className="space-y-4">
          <InsightCards
            quality={quality}
            insights={insights}
            valuation={valuation}
            currency={company.currency}
            sector={company.sector}
            ticker={company.ticker}
            analystConsensus={data.analyst_consensus ?? null}
          />
          {/* Phase-3 (2026-05-25) — Inline comparison sliders. Every
              key metric shows where it sits vs peer median (and own
              5y avg where ratiosHistory is loaded). Reads from
              AnalysisResponse.peer_context; self-hides per-metric
              when peer sample is < 3 tickers. */}
          {data.peer_context && Object.keys(data.peer_context).length > 0 && (
            <div className="bg-surface rounded-2xl border border-border p-4 space-y-2.5">
              <h3 className="text-sm font-semibold text-ink">
                Where you stand vs peers
              </h3>
              <p className="text-[11px] text-caption mb-2">
                Slider runs from 5th to 95th peer percentile. Tick = peer
                median. Dot = this company.
              </p>
              {data.peer_context.roe_pct && (
                <MetricWithContext
                  label="ROE"
                  value={data.peer_context.roe_pct.value}
                  format={(n) => `${n.toFixed(1)}%`}
                  peerMedian={data.peer_context.roe_pct.median}
                  peerP5={data.peer_context.roe_pct.p5}
                  peerP95={data.peer_context.roe_pct.p95}
                  direction="higher_is_better"
                />
              )}
              {data.peer_context.pe_ratio && (
                <MetricWithContext
                  label="PE"
                  value={data.peer_context.pe_ratio.value}
                  format={(n) => `${n.toFixed(1)}x`}
                  peerMedian={data.peer_context.pe_ratio.median}
                  peerP5={data.peer_context.pe_ratio.p5}
                  peerP95={data.peer_context.pe_ratio.p95}
                  direction="lower_is_better"
                />
              )}
              {data.peer_context.debt_to_equity && (
                <MetricWithContext
                  label="D/E"
                  value={data.peer_context.debt_to_equity.value}
                  format={(n) => n.toFixed(2)}
                  peerMedian={data.peer_context.debt_to_equity.median}
                  peerP5={data.peer_context.debt_to_equity.p5}
                  peerP95={data.peer_context.debt_to_equity.p95}
                  direction="lower_is_better"
                />
              )}
              {data.peer_context.net_margin_pct && (
                <MetricWithContext
                  label="Net margin"
                  value={data.peer_context.net_margin_pct.value}
                  format={(n) => `${n.toFixed(1)}%`}
                  peerMedian={data.peer_context.net_margin_pct.median}
                  peerP5={data.peer_context.net_margin_pct.p5}
                  peerP95={data.peer_context.net_margin_pct.p95}
                  direction="higher_is_better"
                />
              )}
            </div>
          )}
          <QualityRatios
            quality={quality}
            insights={insights}
            ratioHistory={ratiosHistoryQuery.data ?? null}
          />
          <PromoterPledgePanel ticker={ticker} />
          {/* Phase I-frontend (Block II): per-bank operational + asset-
              quality KPIs. Only renders for tickers in
              PURE_BANK_TICKERS_FOR_DE; non-banks skip the fetch entirely
              via the isPureBank() guard. The panel itself also self-
              hides if the backend returns is_bank=false. */}
          {isPureBank(ticker) && <BankKpiPanel ticker={ticker} />}
          <InsiderTradingPanel ticker={ticker} />
          <BulkBlockDealsPanel ticker={ticker} />
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
        <div className="space-y-4">
          {/* Section 1 — Financials tab numbered headers
              (manifesto rule: numbered sections established on
              Summary tab; propagated here Phase-2). */}
          <section aria-labelledby="fin-section-kpi">
            <NumberedSectionHeader
              number={1}
              title="KPI OVERVIEW"
              caption="Headline revenue, profit and cash-flow metrics with growth context."
            />
            <FinancialsKpiGrid
              ticker={ticker}
              annual={financialsQuery.data}
              currency={company.currency}
            />
          </section>

          {/* Section 2 — Revenue Sankey (feat/sankey-waterfall-phase2). */}
          <RevealOnScroll>
            <section aria-labelledby="fin-section-sankey">
              <NumberedSectionHeader
                number={2}
                title="WHERE DOES THE MONEY GO?"
                caption="A flow view of every rupee of revenue — split between costs, taxes and profit."
              />
              <ChartDrawIn cssReveal>
                <RevenueSankey
                  ticker={ticker}
                  annual={financialsQuery.data}
                  currency={company.currency}
                />
              </ChartDrawIn>
            </section>
          </RevealOnScroll>

          {/* Section 3 — Earnings Waterfall. */}
          <RevealOnScroll>
            <section aria-labelledby="fin-section-waterfall">
              <NumberedSectionHeader
                number={3}
                title="EARNINGS WATERFALL"
                caption="Step-by-step walk from revenue to net income, with the size of each subtraction visible."
              />
              <ChartDrawIn>
                <EarningsWaterfall
                  ticker={ticker}
                  annual={financialsQuery.data}
                  currency={company.currency}
                />
              </ChartDrawIn>
            </section>
          </RevealOnScroll>

          {/* Section 4 — detailed statements. */}
          <section aria-labelledby="fin-section-statements">
            <NumberedSectionHeader
              number={4}
              title="DETAILED STATEMENTS"
              caption="Income statement, balance sheet and cash flow as reported."
            />
            <FinancialStatements ticker={ticker} currency={company.currency} />
          </section>
          <div className="bg-bg rounded-2xl border border-border p-4">
            <h2 className="text-sm font-semibold text-ink mb-3">Financial Overview</h2>
            <FinancialBars
              ticker={ticker}
              currency={company.currency}
              revenue={chartData?.financials?.revenue}
              fcf={chartData?.financials?.fcf}
              fcfDataSource={valuation.fcf_data_source}
            />
          </div>
          {/* Phase G-intel-phase1 (c): structured signals extracted via
              Anthropic from the latest transcript. Renders ABOVE the
              free-text ConcallsPanel; renders nothing when no signals
              exist yet (additive surface — never blocks the page). */}
          <ConcallSignalsPanel ticker={ticker} />
          {/* Day-103a: concall library with AI-summarised quarterly
              earnings calls. Renders empty state until ingestion lands. */}
          <ConcallsPanel ticker={ticker} />
          {/* Phase H-frontend (Block II): structured AR signals extracted
              via Anthropic. Renders ABOVE the AnnualReportsPanel link
              list; renders nothing when no extraction exists yet. */}
          <ARSignalsPanel ticker={ticker} />
          {/* Day-103b: per-ticker annual report PDF links (Screener.in parity). */}
          <AnnualReportsPanel ticker={ticker} />
        </div>
      ),
    },
    {
      key: "history",
      label: "History",
      content: (
        <div className="space-y-4">
          <FairValueHistory
            ticker={ticker}
            companyName={formatCompanyName(company.company_name)}
            currency={company.currency}
          />
          <div className="bg-bg rounded-2xl border border-border p-4">
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

  // Manifesto Rule 9 — verdict-driven color cascade. Computed once so the
  // sticky 4px page-top bar and the StockHeroImage agree on tier.
  const heroVerdictTier = verdictTierFromMos(
    valuation.margin_of_safety,
    valuation.verdict,
  )
  const heroVerdictPalette = VERDICT_COLORS[heroVerdictTier]

  return (
    <FormulasProvider value={data.formulas}>
    {/* #ASD-restyle (2026-05-25): deep-navy gradient backdrop on the
        analysis page so the Summary-tab section dividers feel like
        Alpha Spread's linear scroll. Outer div paints the gradient
        edge-to-edge; the existing max-w wrapper sits inside it so
        card surfaces (bg-bg / bg-surface) are unaffected. */}
    <div className="bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-950 dark:via-slate-900 dark:to-slate-950 min-h-screen">
    {/* Manifesto Rule 9 — sticky 4px verdict-color indicator. Visible
        from any scroll position so users always have a "what's this
        stock's status" anchor in their peripheral vision. */}
    <div
      data-testid="hero-verdict-bar"
      aria-hidden
      className={`sticky top-0 z-30 h-1 w-full ${heroVerdictPalette.bar}`}
    />
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

      {/* Tickertape-parity 2-column shell (audit:
          .audit/tickertape-deep-walk-2026-05-27.md, gap #1). At lg: and
          up the StickyScorecard rail anchors on the left at 336px,
          sticky top-20, while the existing tab/section content flows in
          the flex-1 right column. Below lg: the rail self-collapses to
          a horizontal sticky strip rendered inside the StickyScorecard
          component itself, so the surrounding markup stays single-
          column on mobile and the layout never reflows mid-render. */}
      <div className="lg:flex lg:items-start lg:gap-6 lg:pt-4">
        <StickyScorecard
          ticker={data.ticker}
          displayTicker={canonicalDisplay}
          companyName={formatCompanyName(company.company_name)}
          currency={company.currency}
          currentPrice={valuation.current_price}
          fairValue={valuation.fair_value}
          confidence={valuation.confidence_score}
          marginOfSafety={valuation.margin_of_safety}
          verdict={valuation.verdict}
          dataLimited={dataLimited}
          worryScore={data.worry_index?.score ?? null}
          worryTier={data.worry_index?.tier ?? null}
          yieldiqScore={quality.yieldiq_score}
          grade={quality.grade}
          moat={quality.moat}
          redFlagCount={insights?.red_flags_structured?.length ?? null}
        />

      <div className="py-4 space-y-4 lg:flex-1 lg:min-w-0 lg:py-0">
        {/* Phase 4 personalization: one-time confirmation banner shown
            after the user picks a style. Self-hides for users without
            a style and after dismissal. */}
        <PersonalizationBanner style={activeStyle} />

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

        {/* Company name + breadcrumb header.
            Mobile fix: stack vertically so the H1 gets full width and
            doesn't truncate to "Relian..." when the action row competes
            for space. From sm: revert to side-by-side layout. */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div className="min-w-0 space-y-1.5">
            <h1 className="font-editorial text-2xl md:text-3xl font-semibold text-ink leading-tight">
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
          <div className="shrink-0 flex items-center gap-3 sm:self-start">
            <ShareReportCard ticker={ticker} variant="compact" />
            <Link href={`/compare?stock1=${ticker}`} className="text-sm sm:text-xs text-brand hover:underline whitespace-nowrap py-2 sm:py-0">
              Compare →
            </Link>
          </div>
        </div>

        {/* Per-ticker model caveat banner — surfaced for conglomerates,
            holdcos, turnarounds, and pre-profit names where the generic
            DCF doesn't apply. Backend tags these with a "[model_caveat]"
            prefix in data_issues (see backend/services/analysis/
            ticker_overrides.py). Amber, rendered ABOVE the FV display so
            users see the limitation before the number. */}
        {(() => {
          const caveatPrefix = "[model_caveat] "
          const caveat = (data.data_issues ?? []).find(
            (s) => typeof s === "string" && s.startsWith(caveatPrefix),
          )
          if (!caveat) return null
          const message = caveat.slice(caveatPrefix.length)
          return (
            <div
              role="note"
              className="text-xs md:text-sm text-warning bg-[color:var(--color-warning)]/10 border border-[color:var(--color-warning)]/40 rounded-lg px-3 py-2"
            >
              <p className="font-semibold mb-0.5">Model caveat</p>
              <p className="text-ink/80 leading-snug">{message}</p>
            </div>
          )
        })()}

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
          // fix/mos-clamp-enforce (2026-05-26): NEVER let a raw
          // base-scenario MoS (which is uncapped — `base_unclamped`-class
          // numbers like WIPRO 321% / KALYANI 829%) reach the hero.
          // Prefer the backend's already-clamped valuation.margin_of_safety
          // and hard-cap to ±200% as defense in depth. When fv_clamped is
          // true and the unclamped base scenario MoS would overflow,
          // collapse to the clamped headline rather than promote an
          // implausible value to the hero.
          const HARD_MOS_CAP = 200
          const candidateHeadlineMos =
            fvClamped && baseScenario && Number.isFinite(baseScenario.mos_pct)
              ? baseScenario.mos_pct
              : valuation.margin_of_safety
          const headlineMos = Number.isFinite(candidateHeadlineMos)
            ? Math.max(-HARD_MOS_CAP, Math.min(HARD_MOS_CAP, candidateHeadlineMos))
            : valuation.margin_of_safety

          // Step B (2026-05-17): pass through the new buffett_mos_pct
          // field so the hero can render the "Margin of Safety (Buffett)"
          // chip alongside the legacy upside-% chip. Pre-PR cached
          // payloads lack the field; EditorialHero skips the chip then.
          const headlineBuffettMos =
            valuation.buffett_mos_pct ?? null

          // task-#218 (2026-05-26): removed dead asOfData snapshot-
          // replay overrides. The hero now renders the live headline
          // values directly. See the state declaration near the top of
          // this component for re-wire notes when the Time Machine
          // chip needs to drive a historical view.
          const displayFairValue = headlineFairValue
          const displayMos = headlineMos
          const displayPrice = valuation.current_price
          const displayVerdict: Verdict = valuation.verdict

          return prismResolved ? (
            <>
              {/* PR-B (chassis): compact Time Machine chip aligned
                  right, near the hero price card. Chip opens the
                  PrismTimeMachine popover (unchanged). */}
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => setTimeMachineOpen(true)}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border bg-bg px-3 py-1 text-xs text-body hover:text-ink hover:bg-surface transition"
                  aria-label="Open Time Machine"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                    <circle cx="12" cy="12" r="9" strokeLinecap="round" strokeLinejoin="round" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 7v5l3 2" />
                  </svg>
                  Time Machine
                </button>
              </div>
              {/* Manifesto Rule 9 — verdict-colored full-bleed hero. Sits
                  ABOVE the EditorialHero 3-column grid, doesn't touch it.
                  Reuses headlineMos/headlineFairValue so the verdict tier
                  agrees with the headline number even under FV clamp. */}
              <StockHeroImage
                ticker={data.ticker}
                displayTicker={company.ticker}
                companyName={formatCompanyName(company.company_name)}
                currentPrice={displayPrice}
                currency={company.currency}
                marginOfSafetyPct={displayMos}
                verdict={displayVerdict}
                marketCapCr={marketCapCr}
                asOf={
                  data.as_of ??
                  valuation.as_of ??
                  valuation.current_price_as_of ??
                  null
                }
              />
            <EditorialHero
              data={prismResolved}
              fairValue={displayFairValue}
              currentPrice={displayPrice}
              marginOfSafety={displayMos}
              buffettMosPct={headlineBuffettMos}
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
              // MUTHOOTFIN P0 (2026-05-17): plumb through the reliability
              // signals so the hero can collapse to "Under Review" instead
              // of rendering "Notably Below Fair Value" above the yellow
              // caution banner. See EditorialHero `isUnreliable` guard.
              fvClamped={fvClamped}
              dcfReliable={valuation.dcf_reliable}
              dataConfidence={data.data_confidence}
              bullCase={valuation.bull_case}
              bearCase={valuation.bear_case}
              // chassis 2026-05-26: single-primary-signal hero. ScoreCard,
              // Buffett MoS chip and Moat stat move into the disclosure
              // below. See .audit/competitor-walk-hdfcbank-2026-05-26.md.
              compactSummary
            />
            </>
          ) : (
            <>
            {/* PR-B (chassis): compact Time Machine chip that opens the
                PrismTimeMachine popover. */}
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setTimeMachineOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-bg px-3 py-1 text-xs text-body hover:text-ink hover:bg-surface transition"
                aria-label="Open Time Machine"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <circle cx="12" cy="12" r="9" strokeLinecap="round" strokeLinejoin="round" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 7v5l3 2" />
                </svg>
                Time Machine
              </button>
            </div>
            <AnalysisHero
              score={quality.yieldiq_score}
              grade={quality.grade}
              confidence={valuation.confidence_score}
              verdict={displayVerdict}
              fairValue={displayFairValue}
              currentPrice={displayPrice}
              marginOfSafety={displayMos}
              moat={quality.moat}
              currency={company.currency}
              thesis={data.ai_summary}
              dataLimited={dataLimited}
              ticker={ticker}
              fairValueComputedAt={valuation.fair_value_computed_at ?? data.timestamp}
              valuationEngineUsed={valuation.valuation_engine_used}
              currentPriceAsOf={valuation.current_price_as_of}
              currentPriceSource={valuation.current_price_source}
              bullCase={valuation.bull_case}
              bearCase={valuation.bear_case}
              // Task #197 (feat/as-of-plumbing): prefer top-level
              // `data.as_of` (added in the same PR), fall back to the
              // valuation-nested copy. Null on legacy cached payloads
              // — the hero degrades to "Updated recently".
              liveQuoteAsOf={data.as_of ?? valuation.as_of ?? null}
            />
            </>
          )
        })()}

        {/* Confidence and methodology disclosure (chassis 2026-05-26).
            Collapsed by default per .audit/competitor-walk-hdfcbank-
            2026-05-26.md gap #2 — the above-the-fold view stays at the
            primary triad (Verdict + Fair Value + Discount-to-FV).
            Methodology details — the composite score, grade, sector
            rank, refraction index, data-quality and model-confidence
            chips, and valuation-stability band — live in here for
            readers who want them. Components are unchanged; only the
            visibility wrapper is new. */}
        <details className="rounded-2xl border border-border bg-bg dark:bg-surface group">
          <summary className="cursor-pointer list-none flex items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-ink [&::-webkit-details-marker]:hidden">
            <span className="flex items-center gap-2">
              <span aria-hidden className="text-caption transition-transform group-open:rotate-90">&#9656;</span>
              Confidence and methodology
            </span>
            <span className="text-[11px] text-caption">
              Composite score, sector rank, data-quality breakdown
            </span>
          </summary>
          <div className="px-4 pb-4 pt-1 space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
              <ScoreCard
                score100={quality.yieldiq_score}
                grade={quality.grade}
                trend12m={prismResolved?.score_history_12m ?? []}
                sectorRank={null}
                refractionIndex={prismResolved?.refraction_index ?? 0}
                marketCapCr={marketCapCr ?? null}
                redFlags={insights?.red_flags_structured ?? []}
              />
              <div className="lg:col-span-2">
                <ScoreBreakdownPanel
                  breakdown={prismResolved?.quality?.score_breakdown}
                />
              </div>
            </div>
            <ConfidenceIndicators
              dataQualityScore={valuation.data_quality_score}
              modelConfidenceScore={valuation.model_confidence_score}
              valuationStabilityScore={valuation.valuation_stability_score}
              analystOpinionRequired={valuation.analyst_opinion_required}
              dataIssues={data.data_issues}
            />
          </div>
        </details>

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
            {/* Pro-tier formula-driven DCF workbook. The component
                returns null for free / unauthenticated users so the
                button is invisible to them — matches PR_LADDER spec. */}
            <ProExcelExportButton ticker={ticker} />
          </div>
        </div>

        {/* feat/transparency (2026-05-02): "Data Freshness" widget.
            Summarises every per-number provenance / freshness field
            surfaced elsewhere on the page in one place so users can
            audit data lineage without hunting through tooltips. Purely
            additive — renders any non-null subset, hides itself when
            nothing is available (legacy cached payloads). */}
        <DataFreshnessWidget data={data} />

        {/* Alpha-Spread restyle (2026-05-25): See Also peer mini-cards.
            Reuses the existing /peers endpoint — no extra backend work.
            Lives between the deep-dive content and the manifest audit so
            users have a continuation path before the page tapers off. */}
        <SeeAlsoPeers ticker={ticker} currency={company.currency} />

        {/* chassis(PR-A) 2026-05-26: thin strip of at-a-glance signal
            chips (Analyst Consensus / Insider Activity / Promoter
            Holding, plus the rest of the InsightCards row). Relocated
            here from the standalone Summary-tab block. Sits directly
            above the FAQ so the page tapers from deep-dive content into
            quick-reference chips and then auto-generated Q&A. Visible
            on every tab by design — these are page-level signals, not
            tab-scoped. */}
        <InsightCards
          quality={quality}
          insights={insights}
          valuation={valuation}
          currency={company.currency}
          sector={company.sector}
          ticker={company.ticker}
          analystConsensus={data.analyst_consensus ?? null}
        />

        {/* Alpha-Spread restyle (2026-05-25): auto-generated FAQ with
            schema.org FAQPage JSON-LD. Template-driven, NO LLM. Highest-
            leverage SEO move in the spec — Google promotes FAQPage in
            search results as rich snippets. */}
        <AnalysisFAQ data={data} />

        {/* Day-108a manifest history — collapsed by default per user
            feedback 2026-05-25 ("dont need this"). Kept accessible
            via <details> so power users can still open the model-change
            audit log. No prominent numbered section header. */}
        <details className="mx-4 mt-12 group">
          <summary className="cursor-pointer text-xs uppercase tracking-wide text-muted-foreground hover:text-foreground transition-colors py-2 select-none">
            ▸ Model change log
            <span className="ml-2 text-muted-foreground/60 group-open:hidden">
              (read-only audit of every update)
            </span>
          </summary>
          <div className="mt-4">
            <ManifestHistoryPanel ticker={ticker} />
          </div>
        </details>

        <ModelDisclaimer className="mx-4" />
      </div>
      </div>

      {timeMachineOpen && (
        <PrismTimeMachine
          ticker={data.ticker}
          isOpen={timeMachineOpen}
          onClose={() => setTimeMachineOpen(false)}
        />
      )}

      {/* Phase 4 personalization: first-visit picker modal. Auto-opens
          once per device on the first analysis page load; subsequent
          opens are user-triggered (future Preferences entry point). */}
      <StylePickerModal
        open={stylePickerOpen}
        onClose={(picked) => {
          setStylePickerOpen(false)
          setActiveStyle(picked)
        }}
      />
    </div>
    </div>
    </FormulasProvider>
  )
}
