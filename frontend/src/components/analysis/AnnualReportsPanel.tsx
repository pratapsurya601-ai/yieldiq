"use client"

// AnnualReportsPanel — per-ticker list of annual report PDF links.
//
// Closes the Screener.in parity gap flagged in the Day-102 competitive
// audit: they ship FY12+ AR links going back ~13 years. We start
// smaller (the BSE filing-index scraper lands in a follow-up task)
// but the contract + UI are stable from day one.
//
// Data source: /api/v1/public/annual-reports/{ticker} (additive, no
// auth, 6h CDN cache). Self-fetches because the AR link list isn't on
// the StockSummary contract — we keep this surface lazy.
//
// SEBI-safe: no opinion, no commentary — just verified filing
// links with the source-of-truth date.

import { useEffect, useMemo, useState } from "react"

interface AnnualReportRow {
  fiscal_year: number
  filed_date: string | null
  source_url: string
}

interface AnnualReportsResponse {
  ticker: string
  annual_reports: AnnualReportRow[]
}

const VISIBLE_DEFAULT = 5

function fmtDate(s: string | null): string {
  if (!s) return "—"
  try {
    return new Date(s).toLocaleDateString("en-IN", {
      year: "numeric",
      month: "short",
      day: "numeric",
    })
  } catch {
    return s
  }
}

// "FY24" badge from a fiscal year ending March.
function fyLabel(fy: number): string {
  const yy = fy % 100
  return `FY${String(yy).padStart(2, "0")}`
}

export default function AnnualReportsPanel({ ticker }: { ticker: string }) {
  const [data, setData] = useState<AnnualReportsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    const symbol = (ticker || "").trim()
    if (!symbol) {
      setLoading(false)
      return
    }
    fetch(`${base}/api/v1/public/annual-reports/${symbol}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: AnnualReportsResponse | null) => {
        if (cancelled) return
        setData(j)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Could not load annual reports")
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  const rows = data?.annual_reports ?? []
  const visible = useMemo(
    () => (expanded ? rows : rows.slice(0, VISIBLE_DEFAULT)),
    [rows, expanded],
  )
  const hiddenCount = Math.max(0, rows.length - VISIBLE_DEFAULT)

  if (loading) {
    return (
      <section className="bg-bg dark:bg-surface rounded-2xl border border-border p-4">
        <h3 className="text-sm font-semibold text-ink mb-2">Annual Reports</h3>
        <div className="text-xs text-caption">Loading…</div>
      </section>
    )
  }

  if (rows.length === 0) {
    return (
      <section className="bg-bg dark:bg-surface rounded-2xl border border-border p-4">
        <h3 className="text-sm font-semibold text-ink mb-2">Annual Reports</h3>
        <div className="text-xs text-caption">
          Annual reports coming soon for this ticker
          {error ? ` (${error})` : "."}
        </div>
      </section>
    )
  }

  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
      aria-label={`Annual reports for ${ticker}`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Annual Reports</h3>
          <p className="text-xs text-caption mt-0.5">
            Official annual report filings (BSE/NSE). Source links open in a new tab.
          </p>
        </div>
      </div>

      <ul className="divide-y divide-border">
        {visible.map((row) => (
          <li
            key={`${row.fiscal_year}-${row.source_url}`}
            className="flex items-center justify-between gap-3 py-2 text-sm"
          >
            <div className="flex items-center gap-3 min-w-0">
              <span
                className="inline-flex items-center justify-center px-2 py-0.5 rounded-full
                           text-[10px] font-semibold tracking-wide uppercase
                           bg-tone-info-bg text-tone-info-fg dark:bg-blue-900/40 dark:text-blue-300
                           tabular-nums"
                aria-label={`Fiscal year ${row.fiscal_year}`}
              >
                {fyLabel(row.fiscal_year)}
              </span>
              <span className="text-xs text-caption tabular-nums">
                {fmtDate(row.filed_date)}
              </span>
            </div>
            <a
              href={row.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400 whitespace-nowrap"
              aria-label={`Download annual report for fiscal year ${row.fiscal_year}`}
            >
              Download ↗
            </a>
          </li>
        ))}
      </ul>

      {hiddenCount > 0 && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            {expanded ? "Show fewer" : `Show all (${rows.length})`}
          </button>
        </div>
      )}
    </section>
  )
}
