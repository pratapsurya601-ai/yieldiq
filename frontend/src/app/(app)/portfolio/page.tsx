"use client"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { getHoldingsLive, getPortfolioHealth, getWatchlist, removeFromWatchlist, getAlerts, deleteAlert, resetHoldings, getBandShifts, getFVHistoryBatch } from "@/lib/api"
import PortfolioSumOfPartsCard from "@/components/portfolio/PortfolioSumOfPartsCard"
import PortfolioReturnsStrip from "@/components/portfolio/PortfolioReturnsStrip"
import HoldingSparkline from "@/components/portfolio/HoldingSparkline"
import EmptyState from "@/components/common/EmptyState"
import HealthScore from "@/components/portfolio/HealthScore"
import PortfolioPrism from "@/components/portfolio/PortfolioPrism"
import SamplePortfolioView, { SAMPLE_DISMISSED_KEY } from "@/components/portfolio/SamplePortfolioView"
// PnLSparklinePlaceholder is intentionally not imported — the card is
// hidden until GET /portfolio/history exists. See HealthDashboard.tsx
// for restore instructions.
import { BelowFairValueBanner } from "@/components/portfolio/HealthDashboard"
import UpdatesFeed from "@/components/portfolio/UpdatesFeed"
import UnlockBadge from "@/components/payg/UnlockBadge"
import { formatCurrency } from "@/lib/utils"
import ModelDisclaimer from "@/components/ModelDisclaimer"
import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"

type PortfolioTab = "holdings" | "watchlist" | "alerts" | "updates"

function isTab(v: string | null): v is PortfolioTab {
  return v === "holdings" || v === "watchlist" || v === "alerts" || v === "updates"
}

function fmtRsCompact(n: number): string {
  const abs = Math.abs(n)
  const sign = n < 0 ? "-" : ""
  if (abs >= 10_000_000) return `${sign}\u20B9${(abs / 10_000_000).toFixed(2)}Cr`
  if (abs >= 100_000) return `${sign}\u20B9${(abs / 100_000).toFixed(2)}L`
  if (abs >= 1_000) return `${sign}\u20B9${(abs / 1_000).toFixed(1)}K`
  return `${sign}\u20B9${abs.toFixed(0)}`
}

function pctColor(n: number): string {
  if (n > 0) return "text-green-600"
  if (n < 0) return "text-red-600"
  return "text-caption"
}

// FIX portfolio-hotfix-#6: strip the trailing `-X` / `-x` / `_X`
// fallback marker that occasionally leaks from the backend ticker
// resolver into the holdings UI (e.g. "PREMCO-X"). Display-only —
// never mutate the underlying ticker used for routing / API keys.
function displayTicker(raw: string): string {
  return raw.replace(/[-_][Xx]$/, "")
}

// FIX portfolio-hotfix-#5: heuristic for "this holding is a
// commodity / non-equity instrument we never DCF-model". Used only
// for the user-facing copy under Fair Value when no FV is cached;
// we never *invent* a fair value for these.
function isLikelyCommodity(h: { ticker: string; sector?: string }): boolean {
  const t = (h.ticker || "").toUpperCase()
  const s = (h.sector || "").toLowerCase()
  if (s.includes("commod") || s.includes("etf") || s.includes("gold") || s.includes("silver")) {
    return true
  }
  return /(GOLD|SILVER|SILV|GOLDBEES|SILVERBEES|TATSILV|TATAGOLD)/.test(t)
}

export default function PortfolioPage() {
  return (
    <Suspense fallback={<div className="max-w-2xl md:max-w-4xl lg:max-w-5xl mx-auto px-4 py-6" />}>
      <PortfolioInner />
    </Suspense>
  )
}

function PortfolioInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const urlTab = searchParams.get("tab")
  const initialTab: PortfolioTab = isTab(urlTab) ? urlTab : "holdings"
  const [tab, setTabState] = useState<PortfolioTab>(initialTab)

  // Keep URL + state in sync when URL changes (e.g. back/forward, redirect arrival)
  useEffect(() => {
    if (isTab(urlTab) && urlTab !== tab) setTabState(urlTab)
  }, [urlTab, tab])

  const setTab = (next: PortfolioTab) => {
    setTabState(next)
    const params = new URLSearchParams(searchParams.toString())
    if (next === "holdings") params.delete("tab")
    else params.set("tab", next)
    const qs = params.toString()
    router.replace(qs ? `/portfolio?${qs}` : "/portfolio", { scroll: false })
  }

  const [toast, setToast] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { data: holdingsLive, isError: holdingsError, isLoading: holdingsLoading } = useQuery({ queryKey: ["holdings-live"], queryFn: getHoldingsLive, retry: 1 })
  const holdings = holdingsLive?.holdings || []
  const summary = holdingsLive?.summary

  // P0 #5 — batched 1y FV-history for every holding, fired once per
  // page load. The backend caps at 50 tickers per request and serves
  // every entry from the same two-tier cache the per-ticker endpoint
  // uses, so this is dramatically cheaper than N round-trips.
  // queryKey includes the sorted ticker list so the query stays stable
  // across re-renders that don't change the holdings set.
  const sparklineTickers = holdings.map(h => h.ticker).sort()
  const { data: sparklineBatch } = useQuery({
    queryKey: ["fv-history-batch", sparklineTickers.join(",")],
    queryFn: () => getFVHistoryBatch(sparklineTickers, 1),
    enabled: sparklineTickers.length > 0 && sparklineTickers.length <= 50,
    staleTime: 60 * 60 * 1000, // 1h — sparklines are very forgiving
    retry: 1,
  })

  // Day-97: backend attaches `sample_portfolio` on the FIRST session
  // after signup when the user has zero real holdings. Render the
  // SamplePortfolioView so the brand-new user sees the Portfolio Prism
  // + observation engine instantly instead of an empty state. One-way
  // dismissal via localStorage so we never re-show after import / close.
  const [sampleDismissed, setSampleDismissed] = useState(false)
  useEffect(() => {
    try {
      if (typeof window !== "undefined" && localStorage.getItem(SAMPLE_DISMISSED_KEY) === "1") {
        setSampleDismissed(true)
      }
    } catch { /* SSR / disabled storage — silently fall back to showing sample */ }
  }, [])
  const samplePortfolio = holdingsLive?.sample_portfolio
  const showSample = !sampleDismissed && !!samplePortfolio && holdings.length === 0
  // Map sample → Prism-compatible shape (ticker + invested_value is enough
  // for PortfolioPrism's weighting math). current_value isn't required by
  // the analyze endpoint, which only consumes ticker + shares.
  const prismHoldingsForSample = (samplePortfolio?.holdings || []).map((h) => ({
    ticker: h.ticker,
    quantity: h.quantity,
    invested_value: h.invested_value,
    current_value: h.invested_value,
  }))
  const dismissSample = () => {
    try { localStorage.setItem(SAMPLE_DISMISSED_KEY, "1") } catch { /* ignore */ }
    setSampleDismissed(true)
  }
  const { data: health } = useQuery({ queryKey: ["portfolio-health"], queryFn: getPortfolioHealth, retry: 1 })
  const { data: watchlist } = useQuery({ queryKey: ["watchlist"], queryFn: getWatchlist })
  const { data: alerts } = useQuery({ queryKey: ["alerts"], queryFn: getAlerts })

  // Band-shift alerts — show a small badge next to any watchlisted
  // ticker that has an undismissed band shift in the last 30 days.
  // Cheap query: returns at most 50 rows, polled lazily on tab focus.
  const { data: bandShifts } = useQuery({
    queryKey: ["band-shifts"],
    queryFn: () => getBandShifts(50),
    staleTime: 60_000,
  })
  const tickersWithBandShift = new Set(
    (bandShifts?.alerts ?? [])
      .filter((a) => !a.user_dismissed)
      .map((a) => a.ticker.toUpperCase()),
  )

  const removeWatchlistMut = useMutation({
    mutationFn: (ticker: string) => removeFromWatchlist(ticker),
    onSuccess: (_data, ticker) => {
      queryClient.invalidateQueries({ queryKey: ["watchlist"] })
      queryClient.invalidateQueries({ queryKey: ["watchlist-check", ticker] })
      showToast("Removed from watchlist")
    },
    onError: () => showToast("Failed to remove"),
  })

  const removeAlertMut = useMutation({
    mutationFn: (alertId: number) => deleteAlert(alertId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] })
      showToast("Alert removed")
    },
    onError: () => showToast("Failed to remove alert"),
  })

  // Reset-holdings flow. The confirm modal is gated by `resetConfirm`
  // so an accidental click on the button can't wipe the portfolio.
  // Health + prism queries are invalidated too because both derive from
  // holdings — without this the UI would still show the stale Prism
  // after the table goes empty.
  const [resetConfirm, setResetConfirm] = useState(false)
  const resetHoldingsMut = useMutation({
    mutationFn: () => resetHoldings(),
    onSuccess: (data: { message?: string }) => {
      queryClient.invalidateQueries({ queryKey: ["holdings-live"] })
      queryClient.invalidateQueries({ queryKey: ["portfolio-health"] })
      setResetConfirm(false)
      showToast(data?.message || "Holdings cleared")
    },
    onError: () => {
      setResetConfirm(false)
      showToast("Failed to reset holdings")
    },
  })

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  return (
    <div className="max-w-2xl md:max-w-4xl lg:max-w-5xl mx-auto px-4 py-6 space-y-5 pb-20">
      {/* Toast */}
      {toast && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-xs font-medium px-4 py-2 rounded-lg shadow-lg z-50 whitespace-nowrap">
          {toast}
        </div>
      )}

      {/* Portfolio Prism — weighted 6-pillar signature across all holdings */}
      {holdings && holdings.length >= 3 && <PortfolioPrism holdings={holdings} />}
      {/* Day-97: also fire the Prism for the sample fixture so the brand-new
          user sees the differentiator immediately. Backend's analyze endpoint
          is stateless + cached, so this costs at most 6 cache hits. */}
      {showSample && prismHoldingsForSample.length >= 3 && (
        <PortfolioPrism holdings={prismHoldingsForSample} />
      )}

      {/* Top-of-page health dashboard — ring + 30d P&L trend */}
      {health && health.score > 0 && (
        <HealthScore score={health.score} grade={health.grade} summary={health.summary} issues={health.issues} strengths={health.strengths} />
      )}
      {/* P&L sparkline card intentionally removed — the gradient Total-Value
          header above already surfaces current value, cumulative P&L abs/%,
          invested, winners/losers. A dashed "coming soon" tile here was pure
          noise. Restore once GET /portfolio/history exists — see
          PnLSparklinePlaceholder in components/portfolio/HealthDashboard.tsx. */}

      {/* P0 #2 — Portfolio Sum-of-Parts FV card. Placed ABOVE the tab
          strip because the SoP analysis applies to the whole portfolio,
          not just the holdings tab. Self-fetches via React Query and
          renders nothing when the user has zero holdings. */}
      <PortfolioSumOfPartsCard />

      {/* Tabs — iOS segmented control style */}
      <div className="flex bg-surface rounded-xl p-1">
        <button onClick={() => setTab("holdings")}
          className={`flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all ${tab === "holdings" ? "bg-bg dark:bg-surface text-ink shadow-sm ring-1 ring-black/5" : "text-caption hover:text-gray-700"}`}>
          Holdings
        </button>
        <button onClick={() => setTab("watchlist")}
          className={`flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all ${tab === "watchlist" ? "bg-bg dark:bg-surface text-ink shadow-sm ring-1 ring-black/5" : "text-caption hover:text-gray-700"}`}>
          Watchlist{watchlist && watchlist.length > 0 ? ` (${watchlist.length})` : ""}
        </button>
        <button onClick={() => setTab("alerts")}
          className={`flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all ${tab === "alerts" ? "bg-bg dark:bg-surface text-ink shadow-sm ring-1 ring-black/5" : "text-caption hover:text-gray-700"}`}>
          Alerts{alerts && alerts.length > 0 ? ` (${alerts.length})` : ""}
        </button>
        <button onClick={() => setTab("updates")}
          className={`flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all ${tab === "updates" ? "bg-bg dark:bg-surface text-ink shadow-sm ring-1 ring-black/5" : "text-caption hover:text-gray-700"}`}>
          Updates
        </button>
      </div>

      {/* Updates tab — P0 #1, per-holding categorised event stream. */}
      {tab === "updates" && <UpdatesFeed />}

      {/* Holdings tab */}
      {tab === "holdings" && holdingsError && (
        <div className="text-center py-12">
          <div className="w-16 h-16 mx-auto mb-4 text-gray-200">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 00.75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 00-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0112 15.75a23.978 23.978 0 01-7.577-1.22 2.016 2.016 0 01-.673-.38m0 0A2.18 2.18 0 013 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 013.413-.387m7.5 0V5.25A2.25 2.25 0 0013.5 3h-3a2.25 2.25 0 00-2.25 2.25v.894m7.5 0a48.667 48.667 0 00-7.5 0" />
            </svg>
          </div>
          <p className="text-base font-semibold text-ink mb-1">Couldn&rsquo;t load holdings</p>
          <p className="text-sm text-caption mb-4">We hit a snag fetching your portfolio. Check your connection and retry, or import fresh from your broker.</p>
          <div className="flex gap-2 justify-center flex-wrap">
            <Link href="/portfolio/import" className="inline-flex items-center justify-center min-h-[40px] bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-blue-700 active:scale-[0.98] transition">
              Import Zerodha / Groww CSV &rarr;
            </Link>
            <Link href="/search" className="inline-flex items-center justify-center min-h-[40px] bg-bg dark:bg-surface border border-border text-ink text-sm font-semibold px-4 py-2 rounded-lg hover:bg-gray-50 active:scale-[0.98] transition">
              Analyse a stock
            </Link>
          </div>
        </div>
      )}
      {tab === "holdings" && !holdingsError && holdingsLoading && (
        <div className="space-y-3" aria-busy="true" aria-label="Loading holdings">
          {/* Summary skeleton — matches the gradient header card */}
          <div className="skeleton rounded-2xl h-[148px]" />
          {/* Three holding-row skeletons — matches the real card layout */}
          {[0, 1, 2].map((i) => (
            <div key={i} className="bg-bg dark:bg-surface rounded-xl border border-gray-100 p-4 space-y-3">
              <div className="flex items-start justify-between">
                <div className="space-y-2">
                  <div className="skeleton h-4 w-24 rounded" />
                  <div className="skeleton h-3 w-32 rounded" />
                </div>
                <div className="space-y-2 text-right">
                  <div className="skeleton h-4 w-20 rounded ml-auto" />
                  <div className="skeleton h-3 w-8 rounded ml-auto" />
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div className="skeleton h-3 w-40 rounded" />
                <div className="skeleton h-3 w-24 rounded" />
              </div>
            </div>
          ))}
        </div>
      )}
      {tab === "holdings" && !holdingsError && !holdingsLoading && showSample && samplePortfolio && (
        <SamplePortfolioView sample={samplePortfolio} onDismiss={dismissSample} />
      )}
      {tab === "holdings" && !holdingsError && !holdingsLoading && !showSample && (
        holdings && holdings.length > 0 ? (
          <section aria-label="Holdings" data-testid="holdings-list" className="space-y-3">
            {/* Warn when any holding is trading >15% below our model fair value */}
            <BelowFairValueBanner holdings={holdings} />
            {/* Portfolio Summary */}
            {summary && summary.count > 0 && (() => {
              // FIX day2-#15: the backend's `winners`/`losers` counts use
              // `pnl > 0` and `pnl < 0` respectively, which drops
              // zero-gain holdings (e.g. TATAGOLD-E @ +0.00%) into
              // neither bucket — so Winners + Losers < count.
              // Recompute client-side with ties going to Winners
              // (0% ≥ 0%) so the two buckets always sum to count.
              const winners = holdings.filter((h) => h.pnl_pct >= 0).length
              const losers = holdings.filter((h) => h.pnl_pct < 0).length
              return (
              <div className="bg-gradient-to-br from-blue-600 to-cyan-500 rounded-2xl p-5 text-white">
                <p className="text-xs font-bold uppercase tracking-wider opacity-80 mb-1">Total Value</p>
                <p className="text-3xl font-black mb-1">{fmtRsCompact(summary.total_current_value)}</p>
                <div className="flex items-baseline gap-2">
                  <p className={`text-sm font-bold ${summary.total_pnl_abs >= 0 ? "text-green-200" : "text-red-200"}`}>
                    {summary.total_pnl_abs >= 0 ? "+" : ""}{fmtRsCompact(summary.total_pnl_abs)}
                  </p>
                  <p className={`text-sm font-semibold ${summary.total_pnl_abs >= 0 ? "text-green-200" : "text-red-200"}`}>
                    ({summary.total_pnl_pct >= 0 ? "+" : ""}{summary.total_pnl_pct.toFixed(2)}%)
                  </p>
                </div>
                {/* Day-30 (2026-05-20): added grid-cols-1 mobile
                    default. The old grid-cols-3 squashed Invested /
                    Current Value / P&L into ~110px columns on 375px
                    phones, truncating the larger rupee values. */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-4 pt-4 border-t border-white/20 text-xs">
                  <div>
                    <p className="opacity-80">Invested</p>
                    <p className="font-bold text-sm">{fmtRsCompact(summary.total_invested)}</p>
                  </div>
                  <div>
                    <p className="opacity-80">Winners</p>
                    <p className="font-bold text-sm">{winners}/{summary.count}</p>
                  </div>
                  <div>
                    <p className="opacity-80">Losers</p>
                    <p className="font-bold text-sm">{losers}/{summary.count}</p>
                  </div>
                </div>
              </div>
              )
            })()}

            {/* P0 #5 Feature C — return decomposition strip. Sits
                between the gradient summary and the holdings list so
                drivers of return are visible at a glance. Most cards
                show LIMITED DATA today; backend services land in
                follow-up PRs. */}
            <PortfolioReturnsStrip />

            {/* Holdings List — key includes account_label so two rows of
                the same ticker (e.g. SILVERBEES held in Zerodha AND ICICI)
                stay as separate cards instead of colliding on the React key
                and rendering as one merged/averaged position. */}
            {holdings.map((h) => (
              <Link key={`${h.ticker}:${h.account_label || "default"}`} href={`/analysis/${h.ticker}`}
                className="block bg-bg dark:bg-surface rounded-xl border border-gray-100 p-4 hover:border-blue-200 transition">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-bold text-ink">{displayTicker(h.display_ticker || h.ticker.replace(".NS", ""))}</p>
                      {h.account_label && h.account_label !== "default" && (
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-caption bg-surface px-1.5 py-0.5 rounded">
                          {h.account_label}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-caption truncate">{h.sector || h.company_name || "—"}</p>
                  </div>
                  <div className="text-right">
                    {/* TODO(PR-B, SEBI-compliance): render <PriceTimestamp
                         as_of={h.as_of ?? null} /> under CMP once the
                         portfolio holdings endpoint surfaces `as_of`
                         for each holding's current_price. */}
                    <p className="text-sm font-mono font-semibold text-ink">{formatCurrency(h.current_price, "INR")}</p>
                    <p className="text-[10px] text-caption uppercase tracking-wider">CMP</p>
                  </div>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <div className="text-caption">
                    {h.quantity} × {formatCurrency(h.entry_price, "INR")}
                    <span className="text-gray-300 mx-1">=</span>
                    <span className="text-ink">{fmtRsCompact(h.invested_value)}</span>
                  </div>
                  <div className="text-right">
                    <p className={`font-mono font-bold ${pctColor(h.pnl_pct)}`}>
                      {h.pnl_pct >= 0 ? "+" : ""}{fmtRsCompact(h.pnl_abs)} ({h.pnl_pct >= 0 ? "+" : ""}{h.pnl_pct.toFixed(2)}%)
                    </p>
                  </div>
                </div>
                {/* Fair value / MoS / sparkline row. FIX portfolio-
                    hotfix-#5: when a holding has no fair value (e.g.
                    commodity ETFs like TATSILV / GOLDBEES) render an
                    explicit "not modeled" line instead of leaving a
                    blank gap that reads as a broken row. */}
                {h.fair_value != null && h.mos_pct != null ? (
                  <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-50 text-[10px] gap-2">
                    <span className="text-caption shrink-0">
                      Fair Value: <span className="font-mono text-ink">{formatCurrency(h.fair_value, "INR")}</span>
                    </span>
                    {/* P0 #5 — 1Y price vs FV mini-sparkline. Fed from
                        the page-level batched query so we don't make
                        one network call per row. */}
                    <div onClick={(e) => e.preventDefault()} className="hidden sm:block">
                      <HoldingSparkline data={sparklineBatch?.[h.ticker]?.data} />
                    </div>
                    <span className={`font-semibold shrink-0 ${h.mos_pct >= 0 ? "text-green-600" : "text-amber-600"}`}>
                      MoS {h.mos_pct >= 0 ? "+" : ""}{h.mos_pct.toFixed(1)}%
                    </span>
                  </div>
                ) : (
                  <div className="mt-2 pt-2 border-t border-gray-50 text-[10px] text-caption">
                    Fair Value: not modeled{isLikelyCommodity(h) ? " (commodity)" : ""}
                  </div>
                )}
              </Link>
            ))}
          </section>
        ) : (
          // UX activation fix (2026-05): explicit section + label so the
          // Holdings empty state can never be mistaken for the Watchlist
          // empty state — both were rendering similar-looking generic
          // cards, which the May audit flagged as "Holdings tab shows
          // watchlist content".
          <section aria-label="Holdings (none yet)" data-testid="holdings-empty">
            <EmptyState
              illustration="/illustrations/empty-portfolio.svg"
              illustrationAlt="Illustration of a rising portfolio chart with a plus badge"
              title="No holdings yet"
              description="Holdings are the actual shares you own — track P&L, fair-value gap, and portfolio-level signals once added. Import your broker CSV or add a single position manually."
              actionLabel="Import broker CSV"
              actionHref="/portfolio/import"
              secondaryLabel="Add holding manually"
              secondaryHref="/portfolio/import"
            />
            <div className="mt-4 pt-4 text-center">
              <p className="text-[11px] text-caption uppercase tracking-wider mb-2 font-semibold">Want to see it first?</p>
              <Link
                href="/analysis/RELIANCE.NS"
                className="inline-flex items-center gap-1.5 text-sm font-semibold text-blue-600 hover:text-blue-700"
              >
                Explore a sample analysis (Reliance) &rarr;
              </Link>
            </div>
          </section>
        )
      )}
      {tab === "holdings" && !holdingsError && holdings && holdings.length > 0 && (
        <div className="flex flex-wrap justify-end items-center gap-4">
          <Link href="/concall" className="text-xs text-blue-600 font-semibold hover:underline">
            Concall AI &rarr;
          </Link>
          <Link href="/portfolio/tax-report" className="text-xs text-blue-600 font-semibold hover:underline">
            Tax Report &rarr;
          </Link>
          <Link href="/portfolio/import" className="text-xs text-blue-600 font-semibold hover:underline">
            + Import from broker CSV
          </Link>
          <button
            type="button"
            onClick={() => setResetConfirm(true)}
            className="text-xs text-red-600 font-semibold hover:underline disabled:opacity-50"
            disabled={resetHoldingsMut.isPending}
          >
            Reset holdings
          </button>
        </div>
      )}

      {/* Reset-holdings confirm modal.
          Shown only after the user clicks "Reset holdings" — never on
          first mount. The destructive button is red + requires a
          second click; the cancel button is the default-focused one so
          pressing Enter exits safely. */}
      {resetConfirm && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="reset-holdings-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4"
          onClick={() => !resetHoldingsMut.isPending && setResetConfirm(false)}
        >
          <div
            className="w-full max-w-sm bg-bg dark:bg-surface rounded-2xl shadow-xl p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div>
              <h3 id="reset-holdings-title" className="text-sm font-semibold text-ink">
                Delete all {holdings?.length ?? 0} holdings?
              </h3>
              <p className="text-xs text-caption mt-1">
                This permanently removes every holding from your portfolio.
                Your watchlist and alerts are not affected. You&apos;ll need
                to re-import from broker CSV or add them back manually.
              </p>
            </div>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                autoFocus
                onClick={() => setResetConfirm(false)}
                disabled={resetHoldingsMut.isPending}
                className="min-h-[36px] px-3 py-1.5 text-xs font-semibold text-ink bg-surface rounded-lg hover:bg-gray-200 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => resetHoldingsMut.mutate()}
                disabled={resetHoldingsMut.isPending}
                className="min-h-[36px] px-3 py-1.5 text-xs font-semibold text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {resetHoldingsMut.isPending ? "Clearing..." : "Yes, delete all"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Watchlist tab */}
      {tab === "watchlist" && (
        watchlist && watchlist.length > 0 ? (
          <section aria-label="Watchlist" data-testid="watchlist-list" className="space-y-2">
            {watchlist.map((w: { ticker: string; company_name: string; target_price: number; added_price: number }) => (
              <div key={w.ticker} className="flex items-center bg-bg dark:bg-surface rounded-xl border border-gray-100 hover:border-blue-200 transition">
                <Link href={`/analysis/${w.ticker}`} className="flex-1 flex items-center justify-between p-4">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="font-medium text-ink">{w.ticker.replace(".NS", "")}</p>
                      <UnlockBadge ticker={w.ticker} size="sm" />
                      {tickersWithBandShift.has(w.ticker.toUpperCase()) && (
                        <span
                          className="inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 ring-1 ring-amber-200"
                          title="Sector-percentile valuation band shifted recently"
                        >
                          New band shift
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-caption">{w.company_name}</p>
                  </div>
                  <div className="text-right">
                    {w.added_price > 0 && (
                      <p className="text-sm font-mono text-caption">{formatCurrency(w.added_price, "INR")}</p>
                    )}
                    {w.target_price > 0 && (
                      <p className="text-xs text-caption">Target: {formatCurrency(w.target_price, "INR")}</p>
                    )}
                  </div>
                </Link>
                <button
                  onClick={() => removeWatchlistMut.mutate(w.ticker)}
                  disabled={removeWatchlistMut.isPending}
                  aria-label={`Remove ${w.ticker.replace(".NS", "")} from watchlist`}
                  className="flex items-center justify-center min-w-[44px] min-h-[44px] text-caption hover:text-red-500 active:scale-90 transition shrink-0"
                  title="Remove from watchlist"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
          </section>
        ) : (
          <EmptyState
            illustration="/illustrations/empty-watchlist.svg"
            illustrationAlt="Illustration of a list with a star"
            title="Your watchlist will live here"
            description="Tap the star on any analysis page to save stocks and track valuation changes over time."
            actionLabel="Explore stocks"
            actionHref="/search"
          />
        )
      )}

      {/* Alerts tab */}
      {tab === "alerts" && (
        alerts && alerts.length > 0 ? (
          <div className="space-y-2">
            {alerts.map((a: { id: number; ticker: string; alert_type: string; target_price: number; created_at: string }) => (
              <div key={a.id} className="flex items-center bg-bg dark:bg-surface rounded-xl border border-gray-100 p-4">
                <Link href={`/analysis/${a.ticker}`} className="flex-1">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-ink">{a.ticker.replace(".NS", "")}</p>
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${a.alert_type === "above" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
                      {a.alert_type === "above" ? "ABOVE" : "BELOW"}
                    </span>
                  </div>
                  <p className="text-sm font-mono text-caption mt-0.5">
                    {"\u20b9"}{a.target_price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                  </p>
                </Link>
                <button
                  onClick={() => removeAlertMut.mutate(a.id)}
                  disabled={removeAlertMut.isPending}
                  aria-label={`Delete ${a.ticker.replace(".NS", "")} price alert`}
                  className="flex items-center justify-center min-w-[44px] min-h-[44px] text-caption hover:text-red-500 active:scale-90 transition shrink-0"
                  title="Delete alert"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-12">
            <div className="w-16 h-16 mx-auto mb-4 text-gray-200">
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
              </svg>
            </div>
            <p className="text-base font-semibold text-ink mb-1">No active alerts</p>
            <p className="text-sm text-caption mb-4">Set price alerts on any analysis page to get notified by email.</p>
            <Link href="/search" className="text-sm text-blue-600 font-medium hover:underline">Search stocks</Link>
          </div>
        )
      )}

      <ModelDisclaimer compact className="text-center pt-4" />
    </div>
  )
}
