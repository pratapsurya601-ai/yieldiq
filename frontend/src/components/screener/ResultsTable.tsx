"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { cn } from "@/lib/utils"
import type { ScreenerQueryRow } from "@/lib/screenerFilters"

interface ResultsTableProps {
  rows: ScreenerQueryRow[]
  total: number
  isLoading: boolean
  pageSize?: number
  // When the upstream query failed, callers should pass the error
  // through so we DON'T render the "No stocks match" empty state —
  // that would falsely tell users no stocks meet their filters when
  // the truth is the API returned 4xx/5xx. The caller renders a
  // dedicated error banner; we just bail out of our own render.
  // Fixes P0-#1 frontend surfacing regression (see
  // extractScreenerError in app/(app)/screener/page.tsx).
  error?: unknown
}

type SortDir = "asc" | "desc"

// Derive columns from the keys present on the first row. Ticker always
// comes first; everything else is ordered alphabetically so the header is
// stable across runs (object key order would otherwise follow insertion).
function deriveColumns(rows: ScreenerQueryRow[]): string[] {
  if (rows.length === 0) return []
  const keys = new Set<string>()
  rows.forEach((r) => Object.keys(r).forEach((k) => keys.add(k)))
  const out = Array.from(keys).filter((k) => k !== "ticker").sort()
  return ["ticker", ...out]
}

function formatCell(v: unknown): string {
  if (v == null) return "\u2014"
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "\u2014"
    if (Math.abs(v) >= 1000) return v.toLocaleString("en-IN", { maximumFractionDigits: 1 })
    return v.toFixed(2)
  }
  return String(v)
}

// TODO(PR-B, SEBI-compliance): when a screener row contains a price
// column (current_price / cmp / price), render <PriceTimestamp
// as_of={...} /> at the top of the table once the screener response
// returns a batch-level `as_of` (or per-row `as_of`). Presently the
// screener runs over the cached analysis tape so no freshness stamp
// is passed through; blocked on backend plumbing.
export default function ResultsTable({ rows, total, isLoading, pageSize = 50, error = null }: ResultsTableProps) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  const [page, setPage] = useState(0)

  const columns = useMemo(() => deriveColumns(rows), [rows])

  const sorted = useMemo(() => {
    if (!sortKey) return rows
    const copy = rows.slice()
    copy.sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      // Numeric comparison when both sides coerce to a finite number;
      // otherwise string compare. Nulls always sort last regardless of dir.
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      const an = typeof av === "number" ? av : Number(av)
      const bn = typeof bv === "number" ? bv : Number(bv)
      if (Number.isFinite(an) && Number.isFinite(bn)) {
        return sortDir === "asc" ? an - bn : bn - an
      }
      return sortDir === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av))
    })
    return copy
  }, [rows, sortKey, sortDir])

  const paged = useMemo(() => {
    const start = page * pageSize
    return sorted.slice(start, start + pageSize)
  }, [sorted, page, pageSize])

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize))

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
    setPage(0)
  }

  if (isLoading) {
    return (
      <div className="rounded-2xl border border-border bg-white overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <div className="h-4 w-32 animate-pulse rounded bg-border/60" />
        </div>
        <div className="divide-y divide-border">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="px-4 py-3 flex items-center gap-4">
              <div className="h-4 w-16 animate-pulse rounded bg-border/60" />
              <div className="h-4 flex-1 animate-pulse rounded bg-border/40" />
              <div className="h-4 w-20 animate-pulse rounded bg-border/60" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  // Never render the "No stocks match" empty state when the upstream
  // query errored. A 400 from a malformed DSL, a 429 rate-limit, or a
  // 500 would otherwise be indistinguishable from a truly empty result
  // set — which was the original P0-#1 regression that made users
  // think no cheap-and-quality stocks exist. When there's an error we
  // render nothing and let the parent show its dedicated error banner.
  if (error != null) {
    return null
  }

  if (rows.length === 0) {
    return (
      <div className="rounded-2xl border border-border bg-bg p-8 text-center">
        <p className="text-sm text-caption">No stocks match these filters.</p>
        <p className="text-xs text-caption mt-1">Try relaxing a threshold or removing a filter.</p>
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-border bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <span className="text-sm font-semibold text-ink">{total.toLocaleString()} results</span>
        {pageCount > 1 && (
          <div className="flex items-center gap-2 text-xs text-caption">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-2 py-1 rounded border border-border hover:bg-bg disabled:opacity-40"
            >
              Prev
            </button>
            <span>
              {page + 1} / {pageCount}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              disabled={page >= pageCount - 1}
              className="px-2 py-1 rounded border border-border hover:bg-bg disabled:opacity-40"
            >
              Next
            </button>
          </div>
        )}
      </div>

      <div className="overflow-x-auto max-h-[70vh]">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-bg border-b border-border z-10">
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  scope="col"
                  className={cn(
                    "text-left px-3 py-2 font-medium text-caption whitespace-nowrap",
                    "cursor-pointer select-none hover:text-ink"
                  )}
                  onClick={() => toggleSort(col)}
                >
                  <span className="inline-flex items-center gap-1">
                    {col}
                    {sortKey === col && <span aria-hidden>{sortDir === "asc" ? "\u2191" : "\u2193"}</span>}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paged.map((row, i) => {
              const tickerRaw = String(row.ticker ?? "")
              const tickerClean = tickerRaw.replace(".NS", "").replace(".BO", "")
              const href = `/analysis/${tickerRaw.includes(".") ? tickerRaw : tickerRaw + ".NS"}`
              return (
                <tr key={`${tickerRaw}-${i}`} className="border-b border-border/60 hover:bg-bg">
                  {columns.map((col) => (
                    <td key={col} className="px-3 py-2 whitespace-nowrap">
                      {col === "ticker" ? (
                        <Link href={href} className="font-semibold text-blue-700 hover:underline">
                          {tickerClean}
                        </Link>
                      ) : (
                        <span className="text-body">{formatCell(row[col])}</span>
                      )}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
