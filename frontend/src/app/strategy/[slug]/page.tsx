"use client"

// Public read-only strategy view. No auth required.
// Renders the saved strategy_def + last_backtest_results returned by
// GET /api/v1/strategies/public/{slug}.

import { use } from "react"
import { useQuery } from "@tanstack/react-query"
import api from "@/lib/api"
import BacktestResults from "@/components/backtest/BacktestResults"
import type { BacktestResult, SavedStrategyDTO } from "@/lib/strategyTypes"

interface PageProps {
  params: Promise<{ slug: string }>
}

export default function PublicStrategyPage({ params }: PageProps) {
  // Next 15: params is a Promise. The `use()` hook unwraps it.
  const { slug } = use(params)

  const { data, isLoading, error } = useQuery<SavedStrategyDTO>({
    queryKey: ["public-strategy", slug],
    queryFn: async () => {
      const res = await api.get(`/api/v1/strategies/public/${slug}`)
      return res.data
    },
  })

  if (isLoading) {
    return <div className="p-8 text-sm text-caption">Loading strategy…</div>
  }
  if (error || !data) {
    return (
      <div className="p-8 text-sm text-red-700">
        This strategy could not be loaded. It may have been unshared.
      </div>
    )
  }

  const result = (data.last_backtest_results || {}) as BacktestResult
  const def = data.strategy_def

  return (
    <div className="px-4 sm:px-6 lg:px-8 max-w-5xl mx-auto w-full py-8 space-y-4">
      <header className="space-y-1">
        <p className="text-[11px] uppercase tracking-wide text-caption">Public strategy</p>
        <h1 className="text-2xl font-bold text-ink">{data.name}</h1>
        <p className="text-xs text-caption">
          Last backtested:{" "}
          {data.last_backtested_at
            ? new Date(data.last_backtested_at).toLocaleString()
            : "never"}
          {" · "}
          Universe: {def.universe.kind}
          {" · "}
          {def.entry_rules.rules.length} rule{def.entry_rules.rules.length === 1 ? "" : "s"}
          {" · "}
          Rebalance: {def.rebalance.freq}
        </p>
      </header>

      {result && (result.curve || result.error) ? (
        <BacktestResults result={result} isReadOnly />
      ) : (
        <div className="rounded-2xl border border-border bg-white p-4 text-sm text-caption">
          The owner of this strategy has not run a backtest yet.
        </div>
      )}

      <div className="rounded-2xl border border-border bg-gray-50 p-4">
        <h2 className="text-sm font-semibold text-ink mb-2">Strategy rules</h2>
        <ul className="text-xs text-ink space-y-1">
          {def.entry_rules.rules.length === 0 && (
            <li className="text-caption">No rules — universe is the only filter.</li>
          )}
          {def.entry_rules.rules.map((r, i) => (
            <li key={i} className="font-mono">
              {r.metric} {r.op}{" "}
              {Array.isArray(r.value) ? r.value.join(", ") : String(r.value)}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[11px] text-caption">
          Combined with logic: <strong>{def.entry_rules.logic}</strong>.
          Sizing: {def.rebalance.sizing}, top {def.rebalance.top_n ?? "—"}.
        </p>
      </div>
    </div>
  )
}
