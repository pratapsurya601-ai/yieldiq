"use client"

// Strategy Builder + Backtest results page.
// Composes StrategyBuilder (form) + BacktestResults (dashboard) and
// drives the /api/v1/strategies/run + /save + /share endpoints.

import { useCallback, useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import api from "@/lib/api"
import StrategyBuilder from "@/components/backtest/StrategyBuilder"
import BacktestResults from "@/components/backtest/BacktestResults"
import {
  emptyStrategy,
  type BacktestResult,
  type SavedStrategyDTO,
  type StrategyDef,
} from "@/lib/strategyTypes"

export default function BacktestPage() {
  const [strategy, setStrategy] = useState<StrategyDef>(() => emptyStrategy())
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [savedId, setSavedId] = useState<string | null>(null)
  const [shareUrl, setShareUrl] = useState<string | null>(null)

  // Load list of user's saved strategies. Lightweight — no results blob.
  const { data: savedList, refetch: refetchSaved } = useQuery<{ strategies: SavedStrategyDTO[] }>({
    queryKey: ["saved-strategies"],
    queryFn: async () => {
      const res = await api.get("/api/v1/strategies/")
      return res.data
    },
    staleTime: 60 * 1000,
  })

  // axios instance has 20s default timeout; backtests can take 30-60s for
  // 5y on a 50-ticker universe. We bump the timeout per-call rather than
  // globally because the rest of the app benefits from snappy 20s timeouts.
  const runBacktest = useCallback(async () => {
    setIsRunning(true)
    setRunError(null)
    try {
      const res = await api.post(
        "/api/v1/strategies/run",
        { strategy_def: strategy },
        { timeout: 90_000 },
      )
      setResult(res.data as BacktestResult)
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string }
      setRunError(e?.response?.data?.detail || e?.message || "Backtest failed")
    } finally {
      setIsRunning(false)
    }
  }, [strategy])

  const saveStrategy = useCallback(async () => {
    const name = window.prompt("Name this strategy", strategy.name || `Strategy ${new Date().toLocaleDateString()}`)
    if (!name) return
    try {
      const res = await api.post(
        "/api/v1/strategies/save",
        { name, strategy_def: { ...strategy, name }, run_now: false },
        { timeout: 60_000 },
      )
      setSavedId(res.data?.id || null)
      refetchSaved()
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string }
      window.alert(e?.response?.data?.detail || e?.message || "Save failed")
    }
  }, [strategy, refetchSaved])

  const shareStrategy = useCallback(async () => {
    if (!savedId) {
      window.alert("Save the strategy first, then share it.")
      return
    }
    try {
      const res = await api.post(`/api/v1/strategies/${savedId}/share`)
      const slug = res.data?.public_slug
      if (slug) {
        const url = `${window.location.origin}/strategy/${slug}`
        setShareUrl(url)
        try {
          await navigator.clipboard.writeText(url)
        } catch {
          // clipboard might be blocked; URL is still rendered for copy-paste.
        }
      }
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string }
      window.alert(e?.response?.data?.detail || e?.message || "Share failed")
    }
  }, [savedId])

  // Derive list of saved strategies for the sidebar.
  const saved = savedList?.strategies || []

  return (
    <div className="px-4 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full pb-12 space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold text-ink">Strategy Backtest</h1>
        <p className="text-sm text-caption">
          Build a rule-based strategy and see how it would have performed historically vs the
          benchmark. Survivorship bias present — past performance does not guarantee future results.
        </p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-4">
        <div className="space-y-4">
          <StrategyBuilder
            value={strategy}
            onChange={setStrategy}
            onRun={runBacktest}
            isRunning={isRunning}
          />

          {isRunning && (
            <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
              Running backtest. Heavy universes can take 30–60 seconds.
            </div>
          )}
          {runError && !isRunning && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              {runError}
            </div>
          )}
          {result && !isRunning && (
            <BacktestResults
              result={result}
              onSave={saveStrategy}
              onShare={shareStrategy}
              shareUrl={shareUrl}
            />
          )}
        </div>

        {/* ── Saved strategies sidebar ────────────────────────────── */}
        <aside className="rounded-2xl border border-border bg-white p-4 h-fit">
          <h2 className="text-sm font-semibold text-ink mb-2">Saved strategies</h2>
          {saved.length === 0 ? (
            <p className="text-xs text-caption">No saved strategies yet. Run a backtest, then save it.</p>
          ) : (
            <ul className="space-y-1">
              {saved.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setStrategy(s.strategy_def)
                      setSavedId(s.id)
                      setShareUrl(s.public_slug ? `${window.location.origin}/strategy/${s.public_slug}` : null)
                    }}
                    className="w-full text-left text-xs text-ink hover:bg-gray-50 rounded px-2 py-1"
                  >
                    {s.name}
                    {s.is_public && <span className="ml-1 text-[10px] text-green-700">[public]</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  )
}
