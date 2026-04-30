"use client"

// InsiderTradingPanel — SEBI PIT Reg 7 disclosures from NSE
// (corporates-pit). Renders the last 5 insider transactions for a ticker
// plus a "View all (N in last 5y)" affordance. Self-fetches; the data
// isn't on the StockSummary contract because we keep this surface
// additive and lazy.
//
// Data: GET /api/v1/public/insider-trading/{ticker}?limit=20
// (1h CDN cache, version_keyed=false — no CACHE_VERSION dependency).

import { useEffect, useState } from "react"

interface InsiderTxn {
  filing_date: string | null
  acquirer_name: string | null
  acquirer_category: string | null
  transaction_type: string | null
  buy_qty: number
  sell_qty: number
  transaction_value_cr: number | null
  holding_before_pct: number | null
  holding_after_pct: number | null
  annex_type: string | null
  pdf_url: string | null
}

interface InsiderResponse {
  ticker: string
  count: number
  count_5y: number
  transactions: InsiderTxn[]
}

const ROWS_TO_SHOW = 5

function fmtDate(s: string | null): string {
  if (!s) return "—"
  try {
    return new Date(s).toLocaleDateString("en-IN", {
      year: "numeric", month: "short", day: "numeric",
    })
  } catch {
    return s
  }
}

function fmtPct(v: number | null): string {
  if (v == null || isNaN(v)) return "—"
  return `${v.toFixed(2)}%`
}

function fmtQty(n: number): string {
  if (!n) return "—"
  if (Math.abs(n) >= 1e7) return `${(n / 1e7).toFixed(2)}Cr`
  if (Math.abs(n) >= 1e5) return `${(n / 1e5).toFixed(2)}L`
  return n.toLocaleString("en-IN")
}

function fmtValueCr(v: number | null): string {
  if (v == null) return "—"
  return `₹${v.toFixed(2)} Cr`
}

function txnSide(t: InsiderTxn): "BUY" | "SELL" | "—" {
  if ((t.buy_qty ?? 0) > 0) return "BUY"
  if ((t.sell_qty ?? 0) > 0) return "SELL"
  return "—"
}

export default function InsiderTradingPanel({ ticker }: { ticker: string }) {
  const [data, setData] = useState<InsiderResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    const symbol = (ticker || "").replace(".NS", "").replace(".BO", "")
    if (!symbol) { setLoading(false); return }
    fetch(`${base}/api/v1/public/insider-trading/${symbol}?limit=20`)
      .then(r => (r.ok ? r.json() : null))
      .then((j: InsiderResponse | null) => {
        if (cancelled) return
        setData(j)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Could not load insider data")
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [ticker])

  if (loading) {
    return (
      <section className="bg-bg dark:bg-surface rounded-2xl border border-border p-5">
        <h3 className="text-sm font-semibold text-ink mb-2">Insider Activity</h3>
        <div className="text-xs text-caption">Loading…</div>
      </section>
    )
  }

  const txns = data?.transactions ?? []

  if (!txns.length) {
    return (
      <section className="bg-bg dark:bg-surface rounded-2xl border border-border p-5">
        <h3 className="text-sm font-semibold text-ink mb-2">Insider Activity</h3>
        <div className="text-xs text-caption">
          No insider-trading disclosures on file
          {error ? ` (${error})` : "."}
        </div>
      </section>
    )
  }

  const recent = txns.slice(0, ROWS_TO_SHOW)
  const symbol = (ticker || "").replace(".NS", "").replace(".BO", "")

  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border p-5"
      aria-label={`Insider trading for ${ticker}`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Insider Activity</h3>
          <p className="text-xs text-caption mt-0.5">
            SEBI PIT Reg 7 disclosures (NSE). Promoter / KMP / designated-person
            buy &amp; sell filings.
          </p>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-caption">
              <th className="py-1 pr-3 font-medium">Date</th>
              <th className="py-1 pr-3 font-medium">Acquirer</th>
              <th className="py-1 pr-3 font-medium">Side</th>
              <th className="py-1 pr-3 font-medium tabular-nums">Qty</th>
              <th className="py-1 pr-3 font-medium tabular-nums">Value</th>
              <th className="py-1 pr-3 font-medium tabular-nums">Holding Before</th>
              <th className="py-1 pr-0 font-medium tabular-nums">Holding After</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((t, i) => {
              const side = txnSide(t)
              const qty = side === "BUY" ? t.buy_qty : side === "SELL" ? t.sell_qty : 0
              const sideColor =
                side === "BUY"
                  ? "text-emerald-600 dark:text-emerald-400"
                  : side === "SELL"
                  ? "text-red-600 dark:text-red-400"
                  : "text-caption"
              return (
                <tr key={i} className="border-t border-border/60">
                  <td className="py-1.5 pr-3 whitespace-nowrap text-ink">
                    {fmtDate(t.filing_date)}
                  </td>
                  <td className="py-1.5 pr-3 text-ink">
                    {t.pdf_url ? (
                      <a
                        href={t.pdf_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:underline"
                        title={t.acquirer_category ?? ""}
                      >
                        {t.acquirer_name ?? "—"}
                      </a>
                    ) : (
                      t.acquirer_name ?? "—"
                    )}
                  </td>
                  <td className={`py-1.5 pr-3 font-semibold ${sideColor}`}>{side}</td>
                  <td className="py-1.5 pr-3 tabular-nums text-ink">{fmtQty(qty)}</td>
                  <td className="py-1.5 pr-3 tabular-nums text-ink">
                    {fmtValueCr(t.transaction_value_cr)}
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums text-caption">
                    {fmtPct(t.holding_before_pct)}
                  </td>
                  <td className="py-1.5 pr-0 tabular-nums text-caption">
                    {fmtPct(t.holding_after_pct)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {data && data.count_5y > recent.length && (
        <div className="mt-3 text-xs">
          <a
            href={`/analysis/${symbol}/insider`}
            className="text-blue-600 hover:underline dark:text-blue-400"
          >
            View all ({data.count_5y} transactions in last 5y) →
          </a>
        </div>
      )}
    </section>
  )
}
