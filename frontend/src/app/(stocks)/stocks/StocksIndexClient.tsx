"use client"

import { useMemo, useState } from "react"
import Link from "next/link"

interface TickerRow {
  ticker: string
  full_ticker?: string
  last_updated: string | null
}

const PAGE_SIZE = 50

export default function StocksIndexClient({
  tickers,
  initialPage,
  initialQuery,
}: {
  tickers: TickerRow[]
  initialPage: number
  initialQuery: string
}) {
  const [query, setQuery] = useState(initialQuery)
  const [page, setPage] = useState(initialPage)

  const filtered = useMemo(() => {
    const sorted = [...tickers].sort((a, b) =>
      a.ticker.localeCompare(b.ticker, "en")
    )
    if (!query) return sorted
    const q = query.toUpperCase()
    return sorted.filter(t => t.ticker.toUpperCase().includes(q))
  }, [tickers, query])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const start = (safePage - 1) * PAGE_SIZE
  const slice = filtered.slice(start, start + PAGE_SIZE)

  return (
    <div className="px-4 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full py-6">
      <header className="mb-6">
        <h1 className="text-2xl sm:text-3xl font-bold text-gray-900">All Stocks</h1>
        <p className="mt-1 text-sm text-gray-600">
          {tickers.length.toLocaleString("en-IN")} Indian stocks in the YieldIQ
          universe. Click a ticker to see its DCF fair value, reverse DCF, risk
          analysis and DuPont breakdown.
        </p>
      </header>

      <div className="mb-4 flex flex-col sm:flex-row gap-3 sm:items-center">
        <input
          type="search"
          inputMode="search"
          placeholder="Search by ticker (e.g. RELIANCE, ITC, HDFCBANK)"
          value={query}
          onChange={e => {
            setQuery(e.target.value)
            setPage(1)
          }}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <div className="text-xs text-gray-500">
          Showing {filtered.length === 0 ? 0 : start + 1}
          {"–"}
          {Math.min(start + PAGE_SIZE, filtered.length)} of{" "}
          {filtered.length.toLocaleString("en-IN")}
        </div>
      </div>

      {tickers.length === 0 ? (
        <div className="border border-gray-200 rounded-xl p-8 text-center text-gray-500 text-sm">
          Universe data is temporarily unavailable. Try refreshing in a moment,
          or jump to a popular stock:{" "}
          <Link href="/stocks/RELIANCE/fair-value" className="text-blue-600 hover:underline">
            RELIANCE
          </Link>
          ,{" "}
          <Link href="/stocks/TCS/fair-value" className="text-blue-600 hover:underline">
            TCS
          </Link>
          ,{" "}
          <Link href="/stocks/HDFCBANK/fair-value" className="text-blue-600 hover:underline">
            HDFCBANK
          </Link>
          .
        </div>
      ) : (
        <>
          <ul className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
            {slice.map(t => (
              <li key={t.ticker}>
                <Link
                  href={`/stocks/${encodeURIComponent(t.ticker)}/fair-value`}
                  className="block px-3 py-2 border border-gray-200 rounded-lg hover:border-blue-400 hover:bg-blue-50 transition text-sm font-medium text-gray-900"
                >
                  {t.ticker}
                </Link>
              </li>
            ))}
          </ul>

          {totalPages > 1 && (
            <nav className="mt-6 flex items-center justify-center gap-2" aria-label="Pagination">
              <button
                type="button"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={safePage <= 1}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-md disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                Previous
              </button>
              <span className="text-sm text-gray-600">
                Page {safePage} of {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={safePage >= totalPages}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-md disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                Next
              </button>
            </nav>
          )}
        </>
      )}
    </div>
  )
}
