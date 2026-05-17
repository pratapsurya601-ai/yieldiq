"use client"
// Recent analyses — last 5 tickers user viewed.
// v1: localStorage-backed. Each ticker analysis page is expected to push
// its symbol into "yq:recent-views" via a tiny effect — that wiring lives
// on the analysis page and is OUT OF SCOPE for this PR. This component
// gracefully renders empty until that list is populated.
// TODO (follow-up): backend `recent_views` table keyed by user, so the
// list persists across devices.

import Link from "next/link"
import { useEffect, useState } from "react"
import { History } from "lucide-react"

const STORAGE_KEY = "yq:recent-views"

interface RecentEntry {
  ticker: string
  viewedAt: number
  price?: number | null
  mos?: number | null
}

function readRecents(): RecentEntry[] {
  if (typeof window === "undefined") return []
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(e => e && typeof e.ticker === "string").slice(0, 5)
  } catch {
    return []
  }
}

export default function RecentAnalyses() {
  const [items, setItems] = useState<RecentEntry[]>([])
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    setMounted(true)
    setItems(readRecents())
  }, [])

  if (!mounted) return null

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-bold uppercase tracking-wider text-ink inline-flex items-center gap-1.5">
          <History className="w-4 h-4" /> Recent analyses
        </h2>
      </div>
      {items.length === 0 ? (
        <div className="bg-surface border border-border rounded-2xl p-4">
          <p className="text-xs text-body">
            Tickers you analyse will appear here for quick recall.
          </p>
        </div>
      ) : (
        <div className="bg-surface border border-border rounded-2xl divide-y divide-border">
          {items.map(it => {
            const display = it.ticker.replace(/\.(NS|BO)$/, "")
            return (
              <Link
                key={it.ticker}
                href={`/analysis/${display}`}
                className="flex items-center justify-between px-4 py-2.5 hover:bg-bg/50 transition"
              >
                <span className="text-xs font-semibold text-ink font-mono">{display}</span>
                <div className="flex items-center gap-3 text-[11px] font-mono">
                  {typeof it.price === "number" && (
                    <span className="text-body">₹{it.price.toFixed(2)}</span>
                  )}
                  {typeof it.mos === "number" && (
                    <span className={it.mos >= 0 ? "text-green-600" : "text-red-600"}>
                      {it.mos >= 0 ? "+" : ""}{it.mos.toFixed(0)}%
                    </span>
                  )}
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
