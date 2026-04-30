"use client"

// BulkBlockDealsPanel — last 5 bulk + last 5 block deals for a ticker.
//
// Backend: GET /api/v1/public/bulk-deals/{ticker}?limit=5
//          GET /api/v1/public/block-deals/{ticker}?limit=5
//
// Self-archived from NSE's current-day snapshot via the daily cron
// (.github/workflows/nse_flows_daily.yml). Coverage builds up day-by-
// day from the cron's first run — empty state is the expected first
// rendering.
//
// Additive surface: no analysis-pipeline math is touched. The panel
// self-fetches in useEffect so it doesn't bloat the initial analysis
// payload, and renders nothing more than a quiet empty state when no
// deals exist for the ticker.

import { useEffect, useState } from "react"
import { getBulkDeals, getBlockDeals, type BulkBlockDeal } from "@/lib/api"

interface Props {
  ticker: string
}

function fmtQty(q: number | null): string {
  if (q === null || q === undefined) return "—"
  if (q >= 1e7) return `${(q / 1e7).toFixed(2)} Cr`
  if (q >= 1e5) return `${(q / 1e5).toFixed(2)} L`
  return q.toLocaleString("en-IN")
}

function fmtPrice(p: number | null): string {
  if (p === null || p === undefined) return "—"
  return `₹${p.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`
}

function shortName(s: string | null, n = 28): string {
  if (!s) return "—"
  return s.length > n ? s.slice(0, n - 1) + "…" : s
}

function DealsTable({ title, deals }: { title: string; deals: BulkBlockDeal[] }) {
  return (
    <div className="bg-surface border border-border rounded-xl overflow-hidden">
      <div className="px-4 py-2 border-b border-border bg-gray-50/50">
        <p className="text-xs font-semibold text-gray-700">{title}</p>
      </div>
      {deals.length === 0 ? (
        <div className="px-4 py-3">
          <p className="text-xs text-gray-500">No recent {title.toLowerCase()}.</p>
        </div>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-100 text-[10px] text-gray-400 uppercase">
              <th className="text-left px-3 py-1.5">Date</th>
              <th className="text-left px-3 py-1.5">Client</th>
              <th className="text-center px-3 py-1.5">Side</th>
              <th className="text-right px-3 py-1.5">Qty</th>
              <th className="text-right px-3 py-1.5">Price</th>
            </tr>
          </thead>
          <tbody>
            {deals.map((d, i) => (
              <tr key={`${d.deal_date}-${i}`} className={i % 2 === 1 ? "bg-gray-50/40" : ""}>
                <td className="px-3 py-1.5 font-mono text-gray-700">{d.deal_date}</td>
                <td className="px-3 py-1.5 text-gray-700">{shortName(d.client_name)}</td>
                <td className="px-3 py-1.5 text-center">
                  <span
                    className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                      d.buy_sell === "B"
                        ? "bg-blue-50 text-blue-700"
                        : "bg-red-50 text-red-700"
                    }`}
                  >
                    {d.buy_sell === "B" ? "Buy" : d.buy_sell === "S" ? "Sell" : d.buy_sell}
                  </span>
                </td>
                <td className="px-3 py-1.5 text-right font-mono">{fmtQty(d.quantity)}</td>
                <td className="px-3 py-1.5 text-right font-mono">{fmtPrice(d.price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function BulkBlockDealsPanel({ ticker }: Props) {
  const [bulk, setBulk] = useState<BulkBlockDeal[] | null>(null)
  const [block, setBlock] = useState<BulkBlockDeal[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([getBulkDeals(ticker, 5), getBlockDeals(ticker, 5)])
      .then(([b, k]) => {
        if (cancelled) return
        setBulk(b?.deals ?? [])
        setBlock(k?.deals ?? [])
      })
      .catch(() => {
        if (cancelled) return
        setBulk([])
        setBlock([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  if (loading) return null
  // Hide entirely when there's nothing for this ticker — keeps the
  // analysis page clean for the long tail. The InsightCards summary
  // card already shows the latest deal at-a-glance for stocks that do
  // have activity.
  if ((bulk?.length ?? 0) === 0 && (block?.length ?? 0) === 0) return null

  return (
    <div className="space-y-3">
      <p className="text-xs font-semibold text-gray-700 uppercase tracking-wider">
        Bulk &amp; Block Deals
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <DealsTable title="Bulk Deals" deals={bulk ?? []} />
        <DealsTable title="Block Deals" deals={block ?? []} />
      </div>
      <p className="text-[10px] text-gray-400">
        Source: NSE bulk/block deal reports, archived daily by YieldIQ.
      </p>
    </div>
  )
}
