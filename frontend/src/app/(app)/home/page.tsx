"use client"
// Logged-in home — v2 dashboard.
// Bloomberg/Koyfin/Seeking-Alpha-inspired dense info layout.
// All API wiring uses existing endpoints (see backend audit notes in PR).
// Each panel fetches independently with its own ErrorBoundary so one
// flaky API never nukes the whole dashboard.

import dynamic from "next/dynamic"
import Link from "next/link"
import { useEffect, useState } from "react"
import { useAuthStore } from "@/store/authStore"
import { TIER_LIMITS } from "@/lib/constants"
import { priceLabel } from "@/config/pricing"
import PersonalHeader from "@/components/home/PersonalHeader"
import HomeSearchBar from "@/components/home/HomeSearchBar"
import ErrorBoundary from "@/components/ErrorBoundary"
import ModelDisclaimer from "@/components/ModelDisclaimer"
import MarketsStrip from "@/components/home/v2/MarketsStrip"
import PortfolioPanel from "@/components/home/v2/PortfolioPanel"
import WatchlistPanel from "@/components/home/v2/WatchlistPanel"
import DailyInsightCard from "@/components/home/v2/DailyInsightCard"

// Below-the-fold panels: lazy-load to keep the initial JS bundle small
// and prioritise LCP for the markets strip + hero columns.
// Anon-safe panels: SSR enabled so unauthenticated visitors see content,
// not empty containers (Phase 0 audit: placeholder-audit-phase0.md).
const QuantPicksGrid = dynamic(() => import("@/components/home/v2/QuantPicksGrid"))
const SectorHeatmap = dynamic(() => import("@/components/home/v2/SectorHeatmap"))
const EarningsWeekStrip = dynamic(() => import("@/components/home/v2/EarningsWeekStrip"))
// Today's Movers — daily-engagement widget, slotted between the
// MarketsStrip and the Portfolio/Watchlist hero grid. Lazy-loaded
// because it's a fresh API call distinct from /pulse — the user
// shouldn't wait on it for the LCP-critical markets strip.
const TodaysMovers = dynamic(() => import("@/components/home/v2/TodaysMovers"))
// User-specific: keep ssr:false (depends on client-only auth store).
const RecentAnalyses = dynamic(() => import("@/components/home/v2/RecentAnalyses"), { ssr: false })

function QuotaBanner({ remaining }: { remaining: number }) {
  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 flex items-start gap-3">
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-amber-100 flex items-center justify-center">
        <svg className="w-3.5 h-3.5 text-amber-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-amber-900">
          {remaining === 0 ? "You’ve used all 5 analyses today" : "1 analysis left today"}
        </p>
        <p className="text-[11px] text-amber-800 mt-0.5">
          {remaining === 0
            ? "Monthly quota resets on the 1st. Upgrade to Analyst for unlimited analyses."
            : `Make it count — or upgrade to Analyst for unlimited analyses (${priceLabel("analyst", "monthly")}/mo).`}
        </p>
      </div>
      <Link
        href="/pricing"
        className="flex-shrink-0 bg-amber-600 text-white text-xs font-semibold px-3 py-1.5 rounded-lg hover:bg-amber-700 transition"
      >
        Upgrade
      </Link>
    </div>
  )
}

function PanelFallback({ label }: { label: string }) {
  // Day-29 (2026-05-20): closes Day-27 audit HIGH issue — fallback was
  // a generic "{label} temporarily unavailable" with no recovery path.
  // Now: shows the label, a brief explanation, and a Try again button
  // that reloads the page (panel-level refetch isn't possible from
  // inside the ErrorBoundary fallback since each panel owns its own
  // React Query state). Acceptable UX for a transient panel failure.
  return (
    <div
      className="bg-surface border border-border rounded-2xl p-4 space-y-2"
      data-testid={`panel-fallback-${label.toLowerCase().replace(/\s+/g, "-")}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-ink">{label} unavailable</p>
          <p className="text-[11px] text-caption mt-0.5">
            This panel failed to load. The rest of the page is unaffected.
          </p>
        </div>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="flex-shrink-0 text-[11px] font-semibold text-brand hover:underline focus:underline focus:outline-none"
        >
          Try again
        </button>
      </div>
    </div>
  )
}

export default function HomePage() {
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  const email = useAuthStore(s => s.email)
  const tier = useAuthStore(s => s.tier)
  const analysesToday = useAuthStore(s => s.analysesToday)
  const rawLimit = TIER_LIMITS[tier]
  const dailyLimit = typeof rawLimit === "number" ? rawLimit : null
  const remaining = dailyLimit !== null ? Math.max(0, dailyLimit - analysesToday) : null
  // Day-48 (2026-05-20): fire the quota warning at remaining<=3 (was <=1).
  // At <=1 the user is already one click from the wall — no runway to
  // consider upgrading. Three-left gives a soft nudge before the hard wall.
  const showQuotaWarning = tier === "free" && remaining !== null && remaining <= 3

  return (
    <div className="bg-bg pb-20">
      {/* Section 1 — Sticky markets strip (full-bleed) */}
      <ErrorBoundary label="MarketsStrip" fallback={null}>
        <MarketsStrip />
      </ErrorBoundary>

      {/* Task #193 — single spacing scale (space-y-8) across all sections.
          Prior layout mixed -mb-2, mb-3, gap-4 ad-hoc which made the dashboard
          feel uneven. Inner section headers still use mb-3 because they're
          intra-section spacing, not inter-section. */}
      <div className="max-w-7xl mx-auto px-4 pt-4 space-y-8">
        {showQuotaWarning && mounted && <QuotaBanner remaining={remaining ?? 0} />}

        {/* Greeting + always-visible search bar (Task #193) */}
        <div className="space-y-3">
          <PersonalHeader email={email} />
          <HomeSearchBar />
        </div>

        {/* Today's Movers — sits between MarketsStrip and the
            Portfolio/Watchlist hero so the first thing a logged-in user
            sees is market activity (not just their own positions).
            Wrapped in its own ErrorBoundary so the home page survives
            a today-movers API outage. */}
        <ErrorBoundary label="TodaysMovers" fallback={<PanelFallback label="Today's Movers" />}>
          <TodaysMovers />
        </ErrorBoundary>

        {/* Section 2 — 2-column hero: Portfolio + Watchlist.
            grid-cols-1 → lg:grid-cols-2 stacks cleanly on <lg viewports. */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ErrorBoundary label="PortfolioPanel" fallback={<PanelFallback label="Portfolio" />}>
            <PortfolioPanel />
          </ErrorBoundary>
          <ErrorBoundary label="WatchlistPanel" fallback={<PanelFallback label="Watchlist" />}>
            <WatchlistPanel />
          </ErrorBoundary>
        </div>

        {/* Section 3 — Quant picks (4 tiles) */}
        <section>
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-sm font-bold uppercase tracking-wider text-ink">
              Quant picks
            </h2>
            <Link href="/screener" className="text-xs font-semibold text-brand hover:underline">
              All screens →
            </Link>
          </div>
          <ErrorBoundary label="QuantPicksGrid" fallback={<PanelFallback label="Quant picks" />}>
            <QuantPicksGrid />
          </ErrorBoundary>
        </section>

        {/* Section 4 — Sector heatmap */}
        <ErrorBoundary label="SectorHeatmap" fallback={<PanelFallback label="Sector heatmap" />}>
          <SectorHeatmap />
        </ErrorBoundary>

        {/* Section 5 — Earnings this week */}
        <ErrorBoundary label="EarningsWeekStrip" fallback={<PanelFallback label="Earnings calendar" />}>
          <EarningsWeekStrip />
        </ErrorBoundary>

        {/* Section 6 + 7 — Recent + Daily insight (side-by-side on desktop) */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ErrorBoundary label="RecentAnalyses" fallback={<PanelFallback label="Recent analyses" />}>
            <RecentAnalyses />
          </ErrorBoundary>
          <div>
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-sm font-bold uppercase tracking-wider text-ink">
                For you
              </h2>
            </div>
            <DailyInsightCard />
          </div>
        </div>
      </div>

      <ModelDisclaimer compact className="text-center mt-6 px-4" />
    </div>
  )
}
