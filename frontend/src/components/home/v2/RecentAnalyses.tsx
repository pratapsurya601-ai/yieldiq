"use client"
// Recent analyses — last 5 tickers user viewed.
//
// v2 (2026-06-07): identity-only localStorage + live re-fetch.
//
// Previously this tile rendered `price` and `mos` from values cached in
// localStorage at view-time. Two failure modes resulted:
//   1. The cached numbers never refreshed. A user who viewed ITC weeks
//      ago saw weeks-old price + MoS on /home forever.
//   2. The cached `mos` was the raw unclamped `valuation.margin_of_
//      safety` — bypassing the per-page displayMos() ±200 clamp. The
//      operator caught a "+200% ITC" tile on 2026-06-07.
//
// Additionally the tile did not honor the backend's `under_review`
// status (set by `validators.py` when data-quality checks fail). ITC
// was flagged under_review by the validators yet the tile happily
// rendered stale numbers next to it.
//
// Root-cause fix:
//   - localStorage stores identity only (ticker + viewedAt). The writer
//     side in AnalysisBody.tsx was simplified to match.
//   - On mount, the tile fetches `/api/v1/public/stock-summary/<ticker>`
//     per entry via getStockSummaryStatus (a new helper that preserves
//     the under_review signal — the existing getStockSummary drops it
//     silently which is correct for Excel-export callers but not here).
//   - Under_review entries render the "Under Review" verdict label
//     instead of stale numbers. The data is flagged for a reason; the
//     UI must respect that.
//   - MoS is clamped via the canonical displayMos() helper so the
//     ±200% hard-cap is enforced everywhere a MoS is rendered.
//   - Backward-compat: old localStorage entries with stale price/mos
//     keys are tolerated (read but ignored — the writer drops them).
//
// TODO (follow-up): backend `recent_views` table keyed by user, so the
// list persists across devices.

import Link from "next/link"
import { useEffect, useState } from "react"
import { History } from "lucide-react"
import { getStockSummaryStatus, type StockSummaryStatus } from "@/lib/api"
import { displayMos, computeTrueMos } from "@/lib/utils"
import TickerAvatar from "@/components/common/TickerAvatar"

const STORAGE_KEY = "yq:recent-views"

interface RecentEntry {
  ticker: string
  viewedAt: number
}

function readRecents(): RecentEntry[] {
  if (typeof window === "undefined") return []
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(e => e && typeof e.ticker === "string")
      .map(e => ({
        ticker: e.ticker as string,
        viewedAt:
          typeof e.viewedAt === "number" && Number.isFinite(e.viewedAt)
            ? e.viewedAt
            : 0,
      }))
      .slice(0, 5)
  } catch {
    return []
  }
}

interface RowData {
  ticker: string
  status: StockSummaryStatus
}

export default function RecentAnalyses() {
  const [items, setItems] = useState<RecentEntry[]>([])
  const [rows, setRows] = useState<RowData[]>([])
  const [mounted, setMounted] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setMounted(true)
    const recents = readRecents()
    setItems(recents)
    if (recents.length === 0) return
    setLoading(true)
    let cancelled = false
    Promise.all(
      recents.map(async r => ({
        ticker: r.ticker,
        status: await getStockSummaryStatus(r.ticker.replace(/\.(NS|BO)$/, "")),
      })),
    )
      .then(results => {
        if (cancelled) return
        setRows(results)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Reserve the section's vertical space BEFORE the client-only mount so
  // it doesn't pop in and shove the rest of the page down (this widget
  // reads localStorage, so it renders nothing on the server). A fixed
  // min-height skeleton keeps the cumulative layout shift near zero.
  if (!mounted) {
    return (
      <section>
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-ink inline-flex items-center gap-1.5">
            <History className="w-4 h-4" /> Recent analyses
          </h2>
        </div>
        <div className="bg-surface border border-border rounded-2xl divide-y divide-border min-h-[132px]">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="flex items-center justify-between px-4 py-2.5">
              <div className="h-4 w-20 bg-border/60 rounded animate-pulse" />
              <div className="h-3 w-12 bg-border/60 rounded animate-pulse" />
            </div>
          ))}
        </div>
      </section>
    )
  }

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-bold uppercase tracking-wider text-ink inline-flex items-center gap-1.5">
          <History className="w-4 h-4" /> Recent analyses
        </h2>
      </div>
      {items.length === 0 ? (
        <div className="bg-surface border border-border rounded-2xl p-4 min-h-[132px]">
          <p className="text-xs text-body">
            Tickers you analyse will appear here for quick recall.
          </p>
        </div>
      ) : (
        <div className="bg-surface border border-border rounded-2xl divide-y divide-border min-h-[132px]">
          {items.map(it => {
            const display = it.ticker.replace(/\.(NS|BO)$/, "")
            const row = rows.find(r => r.ticker === it.ticker)
            return (
              <Link
                key={it.ticker}
                href={`/analysis/${display}`}
                className="flex items-center justify-between px-4 py-2.5 hover:bg-bg/50 transition"
              >
                <span className="flex items-center gap-2 min-w-0">
                  <TickerAvatar ticker={it.ticker} size="sm" />
                  <span className="text-xs font-semibold text-ink font-mono truncate">{display}</span>
                </span>
                <div className="flex items-center gap-3 text-[11px] font-mono">
                  {renderStatus(row, loading)}
                  <span className="text-brand">View →</span>
                </div>
              </Link>
            )
          })}
        </div>
      )}
    </section>
  )
}

function renderStatus(row: RowData | undefined, loading: boolean) {
  if (!row) {
    // Still fetching this row, or the fetch hasn't resolved yet.
    return loading ? (
      <span className="text-caption">…</span>
    ) : (
      <span className="text-caption">—</span>
    )
  }
  if (row.status.kind === "under_review") {
    return (
      <span
        className="text-amber-700 dark:text-amber-400"
        title={row.status.message || "Data being recalibrated"}
      >
        Under Review
      </span>
    )
  }
  if (row.status.kind === "unavailable") {
    return <span className="text-caption">—</span>
  }
  // kind === "ok"
  const s = row.status.summary
  // Compute true (Buffett) MoS = (1 - price/FV)*100. Same sign as upside.
  const trueMos =
    (s as unknown as Record<string, unknown>).buffett_mos_pct != null &&
    typeof (s as unknown as Record<string, unknown>).buffett_mos_pct === "number"
      ? (s as unknown as Record<string, unknown>).buffett_mos_pct as number
      : computeTrueMos(s.fair_value, s.current_price)
  const mosLabel = trueMos != null ? (displayMos(trueMos, null, null) ?? null) : null
  return (
    <>
      {typeof s.current_price === "number" && (
        <span className="text-body">₹{s.current_price.toFixed(2)}</span>
      )}
      {mosLabel && trueMos != null ? (
        <span className="inline-flex flex-col items-end gap-0">
          <span className={trueMos >= 0 ? "text-green-600" : "text-red-600"}>
            {mosLabel}
          </span>
          {typeof s.mos === "number" && (
            <span className="text-[10px] text-caption font-mono">
              {s.mos >= 0 ? "+" : ""}{s.mos.toFixed(1)}% upside
            </span>
          )}
        </span>
      ) : null}
    </>
  )
}
