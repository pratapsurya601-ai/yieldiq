"use client"

// MutualFundHoldersPanel — top 5 mutual funds holding this stock,
// with QoQ AUM moves. Mirrors the Tickertape "Mutual Funds" panel.
//
// Data source: /api/v1/public/mf-holdings/{ticker} (additive,
// no auth, 6h CDN cache). The endpoint is stable across the
// "table populated" and "Phase 2 not landed" paths — the panel
// branches on the `available` flag rather than HTTP status.
//
// Empty state: shows a muted "MF holding data refreshes monthly.
// Check back after AMFI publishes next month's data." line. This
// is the path users currently see — MF Phase 2 of the pipeline
// (populates `mf_holdings_by_stock`) is not yet live.
//
// Trend insight line synthesises a single sentence from the net
// QoQ delta: e.g. "5 MFs added INR 500Cr last quarter" or "MFs
// reducing position — net -INR 300Cr". Kept short so it can sit
// above the table on mobile without wrapping aggressively.

import { useEffect, useState } from "react"

interface MfHolder {
  scheme_code: string
  scheme_name: string
  amc: string | null
  aum_in_stock_cr: number | null
  pct_of_aum: number | null
  qoq_change_cr: number | null
  qoq_change_label: "added" | "reduced" | "unchanged" | string
  as_of: string | null
}

interface MfHoldingsResponse {
  ticker: string
  top_mf_holders: MfHolder[]
  total_mf_holding_cr: number | null
  total_mf_holding_pct: number | null
  net_qoq_change_cr: number | null
  as_of: string | null
  available: boolean
}

function fmtCr(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—"
  if (Math.abs(v) >= 1000) return `INR ${(v / 1000).toFixed(1)}KCr`
  return `INR ${v.toFixed(0)}Cr`
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—"
  return `${v.toFixed(1)}%`
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—"
  try {
    return new Date(s).toLocaleDateString("en-IN", {
      year: "numeric", month: "short", day: "numeric",
    })
  } catch {
    return s
  }
}

function changeBadgeClasses(label: string): string {
  if (label === "added") {
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
  }
  if (label === "reduced") {
    return "bg-red-100 text-tone-bad-fg dark:bg-red-900/40 dark:text-red-300"
  }
  return "bg-slate-100 text-slate-600 dark:bg-slate-800/40 dark:text-slate-300"
}

function buildTrendLine(data: MfHoldingsResponse): string | null {
  if (!data.available) return null
  const n = data.top_mf_holders.length
  const net = data.net_qoq_change_cr
  if (n === 0 || net == null) return null
  const addedCount = data.top_mf_holders.filter(h => (h.qoq_change_cr ?? 0) > 1).length
  const reducedCount = data.top_mf_holders.filter(h => (h.qoq_change_cr ?? 0) < -1).length
  if (net > 1) {
    return `${addedCount || n} MFs added net ${fmtCr(net)} last quarter`
  }
  if (net < -1) {
    return `MFs reducing position — net ${fmtCr(net)}`
  }
  return `MF position steady — ${addedCount} added, ${reducedCount} reduced`
}

export default function MutualFundHoldersPanel({ ticker }: { ticker: string }) {
  const [data, setData] = useState<MfHoldingsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    const symbol = (ticker || "").replace(".NS", "").replace(".BO", "")
    if (!symbol) {
      setLoading(false)
      return
    }
    fetch(`${base}/api/v1/public/mf-holdings/${symbol}`)
      .then(r => (r.ok ? r.json() : null))
      .then((j: MfHoldingsResponse | null) => {
        if (cancelled) return
        setData(j)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Could not load MF holding data")
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [ticker])

  if (loading) {
    return (
      <section className="bg-bg dark:bg-surface rounded-2xl border border-border p-4">
        <h3 className="text-sm font-semibold text-ink mb-2">Mutual Fund Holders</h3>
        <div className="text-xs text-caption">Loading…</div>
      </section>
    )
  }

  const isEmpty =
    !data ||
    !data.available ||
    !Array.isArray(data.top_mf_holders) ||
    data.top_mf_holders.length === 0

  if (isEmpty) {
    return (
      <section
        className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
        aria-label={`Mutual fund holders for ${ticker}`}
      >
        <div className="flex items-start justify-between gap-3 mb-2">
          <div>
            <h3 className="text-sm font-semibold text-ink">Mutual Fund Holders</h3>
            <p className="text-xs text-caption mt-0.5">
              Which mutual funds own this stock + how their position moved last quarter.
            </p>
          </div>
        </div>
        <div className="text-xs text-caption italic">
          MF holding data refreshes monthly. Check back after AMFI publishes next month&apos;s data.
          {error ? ` (${error})` : ""}
        </div>
      </section>
    )
  }

  const trendLine = buildTrendLine(data)

  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
      aria-label={`Mutual fund holders for ${ticker}`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Mutual Fund Holders</h3>
          <p className="text-xs text-caption mt-0.5">
            Top 5 funds holding {ticker}. Source: AMC monthly factsheets via AMFI.
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs text-caption">Total MF AUM in stock</div>
          <div className="text-lg font-semibold text-ink tabular-nums">
            {fmtCr(data.total_mf_holding_cr)}
            {data.total_mf_holding_pct != null && (
              <span className="text-xs text-caption font-normal ml-1">
                ({fmtPct(data.total_mf_holding_pct)})
              </span>
            )}
          </div>
        </div>
      </div>

      {trendLine && (
        <div className="text-xs font-medium text-ink mb-3">
          {trendLine}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-caption border-b border-border">
              <th className="py-2 pr-2 font-medium">Scheme</th>
              <th className="py-2 px-2 font-medium text-right">AUM in stock</th>
              <th className="py-2 px-2 font-medium text-right">% of fund AUM</th>
              <th className="py-2 pl-2 font-medium text-right">QoQ change</th>
            </tr>
          </thead>
          <tbody>
            {data.top_mf_holders.map((h) => (
              <tr key={h.scheme_code} className="border-b border-border last:border-0">
                <td className="py-2 pr-2 align-top">
                  <div className="font-medium text-ink">{h.scheme_name}</div>
                  {h.amc && (
                    <div className="text-[10px] text-caption">{h.amc}</div>
                  )}
                </td>
                <td className="py-2 px-2 text-right tabular-nums text-ink">
                  {fmtCr(h.aum_in_stock_cr)}
                </td>
                <td className="py-2 px-2 text-right tabular-nums text-ink">
                  {fmtPct(h.pct_of_aum)}
                </td>
                <td className="py-2 pl-2 text-right">
                  <div className="flex items-center justify-end gap-1.5">
                    <span className="tabular-nums text-ink">
                      {h.qoq_change_cr != null && h.qoq_change_cr > 0 ? "+" : ""}
                      {h.qoq_change_cr != null ? fmtCr(h.qoq_change_cr).replace("INR ", "") : "—"}
                    </span>
                    <span
                      className={
                        "inline-flex items-center px-1.5 py-0.5 rounded-full text-[9px] " +
                        "font-semibold tracking-wide uppercase " +
                        changeBadgeClasses(h.qoq_change_label)
                      }
                    >
                      {h.qoq_change_label}
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-[10px] text-caption mt-3">
        <span>As of: {fmtDate(data.as_of)}</span>
        <span>AMFI factsheet — monthly refresh</span>
      </div>
    </section>
  )
}
