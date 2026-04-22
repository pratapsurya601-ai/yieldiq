"use client"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { getHoldingsLive, getPortfolioHealth, getWatchlist, removeFromWatchlist, getAlerts, deleteAlert } from "@/lib/api"
import HealthScore from "@/components/portfolio/HealthScore"
import PortfolioPrism from "@/components/portfolio/PortfolioPrism"
// PnLSparklinePlaceholder is intentionally not imported — the card is
// hidden until GET /portfolio/history exists. See HealthDashboard.tsx
// for restore instructions.
import { BelowFairValueBanner } from "@/components/portfolio/HealthDashboard"
import UnlockBadge from "@/components/payg/UnlockBadge"
import { formatCurrency } from "@/lib/utils"
import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"

type PortfolioTab = "holdings" | "watchlist" | "alerts"

function isTab(v: string | null): v is PortfolioTab {
  return v === "holdings" || v === "watchlist" || v === "alerts"
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
  return "text-gray-600"
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
  const { data: health } = useQuery({ queryKey: ["portfolio-health"], queryFn: getPortfolioHealth, retry: 1 })
  const { data: watchlist } = useQuery({ queryKey: ["watchlist"], queryFn: getWatchlist })
  const { data: alerts } = useQuery({ queryKey: ["alerts"], queryFn: getAlerts })

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

      {/* Top-of-page health dashboard — ring + 30d P&L trend */}
      {health && health.score > 0 && (
        <HealthScore score={health.score} grade={health.grade} summary={health.summary} issues={health.issues} strengths={health.strengths} />
      )}
      {/* P&L sparkline card intentionally removed — the gradient Total-Value
          header above already surfaces current value, cumulative P&L abs/%,
          invested, winners/losers. A dashed "coming soon" tile here was pure
          noise. Restore once GET /portfolio/history exists — see
          PnLSparklinePlaceholder in components/portfolio/HealthDashboard.tsx. */}

      {/* Tabs — iOS segmented control style */}
      <div className="flex bg-gray-100 rounded-xl p-1">
        <button onClick={() => setTab("holdings")}
          className={`flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all ${tab === "holdings" ? "bg-white text-gray-900 shadow-sm ring-1 ring-black/5" : "text-gray-500 hover:text-gray-700"}`}>
          Holdings
        </button>
        <button onClick={() => setTab("watchlist")}
          className={`flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all ${tab === "watchlist" ? "bg-white text-gray-900 shadow-sm ring-1 ring-black/5" : "text-gray-500 hover:text-gray-700"}`}>
          Watchlist{watchlist && watchlist.length > 0 ? ` (${watchlist.length})` : ""}
        </button>
        <button onClick={() => setTab("alerts")}
          className={`flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all ${tab === "alerts" ? "bg-white text-gray-900 shadow-sm ring-1 ring-black/5" : "text-gray-500 hover:text-gray-700"}`}>
          Alerts{alerts && alerts.length > 0 ? ` (${alerts.length})` : ""}
        </button>
      </div>

      {/* Holdings tab */}
      {tab === "holdings" && holdingsError && (
        <div className="text-center py-12">
          <div className="w-16 h-16 mx-auto mb-4 text-gray-200">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 00.75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 00-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0112 15.75a23.978 23.978 0 01-7.577-1.22 2.016 2.016 0 01-.673-.38m0 0A2.18 2.18 0 013 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 013.413-.387m7.5 0V5.25A2.25 2.25 0 0013.5 3h-3a2.25 2.25 0 00-2.25 2.25v.894m7.5 0a48.667 48.667 0 00-7.5 0" />
            </svg>
          </div>
          <p className="text-base font-semibold text-gray-700 mb-1">Couldn&rsquo;t load holdings</p>
          <p className="text-sm text-gray-500 mb-4">We hit a snag fetching your portfolio. Check your connection and retry, or import fresh from your broker.</p>
          <div className="flex gap-2 justify-center flex-wrap">
            <Link href="/portfolio/import" className="inline-flex items-center justify-center min-h-[40px] bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-blue-700 active:scale-[0.98] transition">
              Import Zerodha / Groww CSV &rarr;
            </Link>
            <Link href="/search" className="inline-flex items-center justify-center min-h-[40px] bg-white border border-gray-200 text-gray-700 text-sm font-semibold px-4 py-2 rounded-lg hover:bg-gray-50 active:scale-[0.98] transition">
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
            <div key={i} className="bg-white rounded-xl border border-gray-100 p-4 space-y-3">
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
      {tab === "holdings" && !holdingsError && !holdingsLoading && (
        holdings && holdings.length > 0 ? (
          <div className="space-y-3">
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
                <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-white/20 text-xs">
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

            {/* Holdings List — key includes account_label so two rows of
                the same ticker (e.g. SILVERBEES held in Zerodha AND ICICI)
                stay as separate cards instead of colliding on the React key
                and rendering as one merged/averaged position. */}
            {holdings.map((h) => (
              <Link key={`${h.ticker}:${h.account_label || "default"}`} href={`/analysis/${h.ticker}`}
                className="block bg-white rounded-xl border border-gray-100 p-4 hover:border-blue-200 transition">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-bold text-gray-900">{h.display_ticker || h.ticker.replace(".NS", "")}</p>
                      {h.account_label && h.account_label !== "default" && (
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">
                          {h.account_label}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 truncate">{h.sector || h.company_name || "—"}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-mono font-semibold text-gray-900">{formatCurrency(h.current_price, "INR")}</p>
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider">CMP</p>
                  </div>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <div className="text-gray-500">
                    {h.quantity} × {formatCurrency(h.entry_price, "INR")}
                    <span className="text-gray-300 mx-1">=</span>
                    <span className="text-gray-700">{fmtRsCompact(h.invested_value)}</span>
                  </div>
                  <div className="text-right">
                    <p className={`font-mono font-bold ${pctColor(h.pnl_pct)}`}>
                      {h.pnl_pct >= 0 ? "+" : ""}{fmtRsCompact(h.pnl_abs)} ({h.pnl_pct >= 0 ? "+" : ""}{h.pnl_pct.toFixed(2)}%)
                    </p>
                  </div>
                </div>
                {/* Optional: show fair value & verdict if available */}
                {h.fair_value != null && h.mos_pct != null && (
                  <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-50 text-[10px]">
                    <span className="text-gray-400">
                      Fair Value: <span className="font-mono text-gray-700">{formatCurrency(h.fair_value, "INR")}</span>
                    </span>
                    <span className={`font-semibold ${h.mos_pct >= 0 ? "text-green-600" : "text-amber-600"}`}>
                      MoS {h.mos_pct >= 0 ? "+" : ""}{h.mos_pct.toFixed(1)}%
                    </span>
                  </div>
                )}
              </Link>
            ))}
          </div>
        ) : (
          <div className="text-center py-12">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-blue-50 flex items-center justify-center text-blue-500">
              <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 00.75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 00-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0112 15.75a23.978 23.978 0 01-7.577-1.22 2.016 2.016 0 01-.673-.38m0 0A2.18 2.18 0 013 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 013.413-.387m7.5 0V5.25A2.25 2.25 0 0013.5 3h-3a2.25 2.25 0 00-2.25 2.25v.894m7.5 0a48.667 48.667 0 00-7.5 0" />
              </svg>
            </div>
            <p className="text-base font-semibold text-gray-900 mb-1">No holdings yet</p>
            <p className="text-sm text-gray-500 mb-4 max-w-sm mx-auto">Your portfolio is empty. Import your Zerodha/Groww holdings in seconds, or analyse stocks one by one.</p>
            <div className="flex gap-2 justify-center flex-wrap">
              <Link href="/portfolio/import" className="inline-flex items-center justify-center min-h-[40px] bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-blue-700 active:scale-[0.98] transition">
                Import CSV &rarr;
              </Link>
              <Link href="/search" className="inline-flex items-center justify-center min-h-[40px] bg-white border border-gray-200 text-gray-700 text-sm font-semibold px-4 py-2 rounded-lg hover:bg-gray-50 active:scale-[0.98] transition">
                Analyse a stock
              </Link>
            </div>
            <div className="mt-6 pt-5 border-t border-gray-100 max-w-sm mx-auto">
              <p className="text-[11px] text-gray-400 uppercase tracking-wider mb-2 font-semibold">Want to see it first?</p>
              <Link
                href="/analysis/RELIANCE.NS"
                className="inline-flex items-center gap-1.5 text-sm font-semibold text-blue-600 hover:text-blue-700"
              >
                Explore a sample analysis (Reliance) &rarr;
              </Link>
            </div>
          </div>
        )
      )}
      {tab === "holdings" && !holdingsError && holdings && holdings.length > 0 && (
        <div className="flex flex-wrap justify-end gap-4">
          <Link href="/concall" className="text-xs text-blue-600 font-semibold hover:underline">
            Concall AI &rarr;
          </Link>
          <Link href="/portfolio/tax-report" className="text-xs text-blue-600 font-semibold hover:underline">
            Tax Report &rarr;
          </Link>
          <Link href="/portfolio/import" className="text-xs text-blue-600 font-semibold hover:underline">
            + Import from broker CSV
          </Link>
        </div>
      )}

      {/* Watchlist tab */}
      {tab === "watchlist" && (
        watchlist && watchlist.length > 0 ? (
          <div className="space-y-2">
            {watchlist.map((w: { ticker: string; company_name: string; target_price: number; added_price: number }) => (
              <div key={w.ticker} className="flex items-center bg-white rounded-xl border border-gray-100 hover:border-blue-200 transition">
                <Link href={`/analysis/${w.ticker}`} className="flex-1 flex items-center justify-between p-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-gray-900">{w.ticker.replace(".NS", "")}</p>
                      <UnlockBadge ticker={w.ticker} size="sm" />
                    </div>
                    <p className="text-xs text-gray-400">{w.company_name}</p>
                  </div>
                  <div className="text-right">
                    {w.added_price > 0 && (
                      <p className="text-sm font-mono text-gray-600">{formatCurrency(w.added_price, "INR")}</p>
                    )}
                    {w.target_price > 0 && (
                      <p className="text-xs text-gray-400">Target: {formatCurrency(w.target_price, "INR")}</p>
                    )}
                  </div>
                </Link>
                <button
                  onClick={() => removeWatchlistMut.mutate(w.ticker)}
                  disabled={removeWatchlistMut.isPending}
                  aria-label={`Remove ${w.ticker.replace(".NS", "")} from watchlist`}
                  className="flex items-center justify-center min-w-[44px] min-h-[44px] text-gray-400 hover:text-red-500 active:scale-90 transition shrink-0"
                  title="Remove from watchlist"
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
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.562.562 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.562.562 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
              </svg>
            </div>
            <p className="text-base font-semibold text-gray-700 mb-1">Watchlist empty</p>
            <p className="text-sm text-gray-400 mb-4">Tap the star on any analysis page to save stocks here.</p>
            <Link href="/search" className="text-sm text-blue-600 font-medium hover:underline">Search stocks</Link>
          </div>
        )
      )}

      {/* Alerts tab */}
      {tab === "alerts" && (
        alerts && alerts.length > 0 ? (
          <div className="space-y-2">
            {alerts.map((a: { id: number; ticker: string; alert_type: string; target_price: number; created_at: string }) => (
              <div key={a.id} className="flex items-center bg-white rounded-xl border border-gray-100 p-4">
                <Link href={`/analysis/${a.ticker}`} className="flex-1">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-gray-900">{a.ticker.replace(".NS", "")}</p>
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${a.alert_type === "above" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
                      {a.alert_type === "above" ? "ABOVE" : "BELOW"}
                    </span>
                  </div>
                  <p className="text-sm font-mono text-gray-600 mt-0.5">
                    {"\u20b9"}{a.target_price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                  </p>
                </Link>
                <button
                  onClick={() => removeAlertMut.mutate(a.id)}
                  disabled={removeAlertMut.isPending}
                  aria-label={`Delete ${a.ticker.replace(".NS", "")} price alert`}
                  className="flex items-center justify-center min-w-[44px] min-h-[44px] text-gray-400 hover:text-red-500 active:scale-90 transition shrink-0"
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
            <p className="text-base font-semibold text-gray-700 mb-1">No active alerts</p>
            <p className="text-sm text-gray-400 mb-4">Set price alerts on any analysis page to get notified by email.</p>
            <Link href="/search" className="text-sm text-blue-600 font-medium hover:underline">Search stocks</Link>
          </div>
        )
      )}
    </div>
  )
}
