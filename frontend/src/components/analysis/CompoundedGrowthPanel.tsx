"use client"

// CompoundedGrowthPanel — 3y/5y/10y CAGR panel for the analysis page.
//
// Day-103c (2026-05-22). Closes a competitive gap identified in the
// Day-102 audit: Screener.in's CAGR panel was its top-3 wedge against
// us, and we already had the underlying revenue/profit history in the
// financials table. This is a derived-metric ship.
//
// Data source: stock-summary's `compounded_growth` field (no new API
// call, no new endpoint). The component self-fetches with React Query
// so the surrounding AnalysisBody stays untouched apart from a single
// mount line.
//
// Rendering rules:
//   * 4 rows (Revenue / Profit / ROE / Stock) × 3 columns (3y/5y/10y)
//   * Each cell is the percentage with one decimal
//   * Color thresholds: green > 15%, neutral 5–15%, dim < 5%, red < 0
//   * Null → "—" (insufficient data or sanity-gate trip)
//   * Footer: "Computed from annual filings, as of FY{as_of_fy}"
//
// SEBI-safe copy: no advisory language. We describe what the numbers
// are, not what action they imply.

import { useQuery } from "@tanstack/react-query"
import { getStockSummary } from "@/lib/api"
import type { CompoundedGrowthPanel as PanelData } from "@/lib/api"
import CompoundedGrowthSparklines from "./CompoundedGrowthSparklines"

interface Props {
  ticker: string
}

type WindowKey = "3y" | "5y" | "10y"
type RowKey = "revenue" | "profit" | "roe_avg" | "stock"

const ROWS: { key: RowKey; label: string; hint: string }[] = [
  { key: "revenue", label: "Revenue", hint: "Annual revenue, compounded" },
  { key: "profit", label: "Profit", hint: "Net income, compounded" },
  { key: "roe_avg", label: "ROE (avg)", hint: "Simple average of annual ROE" },
  { key: "stock", label: "Stock price", hint: "Close-to-close, compounded" },
]

const WINDOWS: WindowKey[] = ["3y", "5y", "10y"]


function classify(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "text-caption"
  if (value < 0) return "text-danger"
  if (value > 15) return "text-success font-semibold"
  if (value >= 5) return "text-ink"
  return "text-caption"
}


function formatCell(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—"
  // One decimal, explicit sign for negatives, % suffix
  return `${value.toFixed(1)}%`
}


export default function CompoundedGrowthPanel({ ticker }: Props) {
  const query = useQuery({
    queryKey: ["stock-summary-cagr", ticker],
    queryFn: () => getStockSummary(ticker),
    staleTime: 5 * 60 * 1000,
  })

  const panel: PanelData | null = query.data?.compounded_growth ?? null

  // Hide entirely when we have nothing meaningful to show — keeps the
  // page from rendering a 12-cell wall of "—" for fresh listings or
  // when older cached payloads predate Day-103c.
  if (!panel) return null

  const allRowsEmpty = ROWS.every((row) => {
    const metric = panel[row.key]
    return WINDOWS.every((w) => metric?.[w] === null || metric?.[w] === undefined)
  })
  if (allRowsEmpty) return null

  // Use revenue.as_of_fy as the canonical "as of" — all 4 metrics
  // share the same source year by construction.
  const asOfFy = panel.revenue.as_of_fy ?? panel.profit.as_of_fy ?? panel.stock.as_of_fy

  return (
    <section
      className="bg-bg rounded-2xl border border-border p-4"
      aria-label={`Compounded growth for ${ticker}`}
    >
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-ink">Compounded growth</h2>
        <p className="text-xs text-caption mt-1">
          Annualised growth rates over the trailing 3, 5 and 10 years.
        </p>
      </div>

      {/* Visual Richness #3 (2026-05-27): sparkline tiles above the
          full table. Headline number is the longest available window
          (10y → 5y → 3y); curve is the implied trajectory back-cast
          from the CAGR values themselves — no extra fetch. */}
      <CompoundedGrowthSparklines panel={panel} />

      <details className="mt-4 group">
        <summary className="cursor-pointer text-xs text-caption hover:text-ink select-none">
          Show full 3y / 5y / 10y breakdown
        </summary>
        <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-caption">
              <th className="text-left font-normal pb-2 pr-2">Metric</th>
              {WINDOWS.map((w) => (
                <th key={w} className="text-right font-normal pb-2 px-2">
                  {w}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => {
              const metric = panel[row.key]
              return (
                <tr key={row.key} className="border-t border-border">
                  <td className="py-2 pr-2">
                    <div className="text-ink">{row.label}</div>
                    <div className="text-[11px] text-caption">{row.hint}</div>
                  </td>
                  {WINDOWS.map((w) => {
                    const v = metric?.[w] ?? null
                    return (
                      <td
                        key={w}
                        className={`py-2 px-2 text-right font-mono tabular-nums ${classify(v)}`}
                      >
                        {formatCell(v)}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
        </div>
      </details>

      <p className="text-[11px] text-caption mt-3">
        {asOfFy
          ? `Computed from annual filings, as of FY${asOfFy}. Stock CAGR uses daily close prices.`
          : "Computed from annual filings. Stock CAGR uses daily close prices."}
      </p>
    </section>
  )
}
