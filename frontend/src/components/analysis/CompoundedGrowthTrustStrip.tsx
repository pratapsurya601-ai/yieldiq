"use client"

// CompoundedGrowthTrustStrip — TrustStrip variant that self-fetches
// stock-summary so it can render Revenue/Profit/ROE/Stock CAGR cards
// without forcing AnalysisBody to plumb the data through.
//
// Mirrors CompoundedGrowthPanel's fetch pattern (same queryKey, same
// staleTime) so the two share a single React-Query cache entry.
//
// Real-data-only policy: if all 4 cells are null, the component renders
// nothing (NOT a "LIMITED DATA" pill — silent omission keeps the page
// clean for fresh listings).

import { useQuery } from "@tanstack/react-query"
import { getStockSummary } from "@/lib/api"
import TrustStrip, { type TrustStat, type TrustAccent } from "./TrustStrip"

interface Props {
  ticker: string
}

function accentFor(value: number | null | undefined): TrustAccent {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "neutral"
  }
  if (value < 0) return "red"
  if (value >= 15) return "green"
  return "neutral"
}

function fmt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—"
  }
  return `${value.toFixed(1)}%`
}

export default function CompoundedGrowthTrustStrip({ ticker }: Props) {
  const query = useQuery({
    queryKey: ["stock-summary-cagr", ticker],
    queryFn: () => getStockSummary(ticker),
    staleTime: 5 * 60 * 1000,
  })

  const panel = query.data?.compounded_growth ?? null
  if (!panel) return null

  const rev3 = panel.revenue?.["3y"] ?? null
  const prof3 = panel.profit?.["3y"] ?? null
  const roe3 = panel.roe_avg?.["3y"] ?? null
  const stk10 = panel.stock?.["10y"] ?? null

  // Real-data-only: if every field is null, render nothing.
  if (
    rev3 === null &&
    prof3 === null &&
    roe3 === null &&
    stk10 === null
  ) {
    return null
  }

  const stats: TrustStat[] = [
    { label: "Revenue 3y CAGR", value: fmt(rev3), accent: accentFor(rev3) },
    { label: "Profit 3y CAGR", value: fmt(prof3), accent: accentFor(prof3) },
    { label: "ROE avg 3y", value: fmt(roe3), accent: accentFor(roe3) },
    { label: "Stock 10y CAGR", value: fmt(stk10), accent: accentFor(stk10) },
  ]

  return <TrustStrip stats={stats} ariaLabel="Compounded growth highlights" />
}
