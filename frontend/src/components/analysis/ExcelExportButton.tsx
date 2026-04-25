"use client"

import { useState } from "react"
import {
  getStockSummary,
  getHistoricalFinancials,
  getRatiosHistory,
  getPublicPeers,
} from "@/lib/api"
import { downloadWorkbook } from "@/lib/excel"

interface Props {
  ticker: string
  className?: string
}

/**
 * One-click "Download Excel" button for the fair-value page (Task C2).
 * Re-fetches the four public payloads on demand (so the user always
 * gets the latest cached numbers even if the SSR slice is stale) and
 * hands them to lib/excel.ts which builds the .xlsx in-browser.
 */
export default function ExcelExportButton({ ticker, className }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleClick = async () => {
    setBusy(true)
    setError(null)
    try {
      const [summary, financials, ratios, peers] = await Promise.all([
        getStockSummary(ticker),
        getHistoricalFinancials(ticker, 5, "annual"),
        getRatiosHistory(ticker, 5, "annual"),
        getPublicPeers(ticker, 10),
      ])
      if (!summary) {
        setError("Stock data is currently under review — try again shortly.")
        return
      }
      downloadWorkbook({ ticker, summary, financials, ratios, peers })
    } catch (e) {
      setError(e instanceof Error ? e.message : "Excel export failed")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={className}>
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-xl border bg-bg dark:bg-surface px-4 py-2 text-sm font-semibold transition hover:bg-surface dark:hover:bg-bg disabled:opacity-50"
        style={{
          borderColor: "var(--color-border, #E2E8F0)",
          color: "var(--color-ink, #0F172A)",
        }}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        {busy ? "Building Excel…" : "Download Excel"}
      </button>
      {error && (
        <p className="mt-2 text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
