"use client"

import { useSearchParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { Suspense, useCallback } from "react"
import api from "@/lib/api"
import Link from "next/link"
import { useAuthStore } from "@/store/authStore"

interface ScreenerStock {
  ticker: string
  score: number
  margin_of_safety: number
}

interface ScreenerResponse {
  results: ScreenerStock[]
  total: number
  page: number
  page_size: number
  filter_applied: Record<string, unknown>
}

const PRESET_CONFIG: Record<string, { title: string; description: string; color: string }> = {
  buffett: {
    title: "Buffett Style",
    description: "Wide moat, consistent earnings, fair price. Score 60+ with 20%+ margin of safety.",
    color: "text-blue-600",
  },
  "deep-value": {
    title: "Deep Value",
    description: "High margin of safety, low P/E, high FCF yield. Score 60+ with 30%+ MoS.",
    color: "text-emerald-600",
  },
  "growth-quality": {
    title: "Growth Quality",
    description: "High growth with quality fundamentals. Score 80+ with positive MoS.",
    color: "text-violet-600",
  },
  custom: {
    title: "Custom Screener",
    description: "All stocks ranked by YieldIQ Score.",
    color: "text-amber-600",
  },
}

function ScreenerContent() {
  const params = useSearchParams()
  const preset = params.get("preset") || "custom"
  const { tier } = useAuthStore()

  // Map URL preset names to API preset names
  const apiPreset = preset.replace("-", "_")
  const config = PRESET_CONFIG[preset] || PRESET_CONFIG.custom

  const handleExportCSV = useCallback(async () => {
    try {
      const res = await api.get(`/api/v1/screener/export?preset=${apiPreset}`)
      const stocks = res.data.results as ScreenerStock[]
      if (!stocks.length) return

      const headers = ["Ticker", "Score", "Margin of Safety (%)"]
      const rows = stocks.map((s: ScreenerStock) => [
        s.ticker,
        s.score,
        s.margin_of_safety.toFixed(1),
      ])
      const csv = [headers.join(","), ...rows.map((r: (string | number)[]) => r.join(","))].join("\n")

      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `yieldiq_screener_${preset}_${new Date().toISOString().split("T")[0]}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert("CSV export requires Starter plan or above.")
    }
  }, [apiPreset, preset])

  const { data, isLoading, error } = useQuery<ScreenerResponse>({
    queryKey: ["screener", preset],
    queryFn: async () => {
      if (preset === "custom") {
        const res = await api.get("/api/v1/screener/run?min_score=0&page_size=50")
        return res.data
      }
      const res = await api.get(`/api/v1/screener/preset/${apiPreset}`)
      return res.data
    },
    staleTime: 5 * 60 * 1000,
  })

  return (
    <div className="max-w-2xl md:max-w-3xl lg:max-w-5xl mx-auto px-4 py-6 pb-20 space-y-5">
      {/* Header */}
      <div>
        <Link href="/discover" className="text-xs text-blue-600 hover:underline mb-2 inline-block">
          &larr; Back to Discover
        </Link>
        <h1 className={`text-xl font-bold ${config.color}`}>{config.title}</h1>
        <p className="text-sm text-gray-500 mt-1">{config.description}</p>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center py-16">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          <span className="ml-3 text-sm text-gray-500">Running screener...</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-center">
          <p className="text-sm text-amber-800 font-medium mb-1">Screener requires Starter plan</p>
          <p className="text-xs text-amber-700">Upgrade to access stock screening with custom filters.</p>
          <Link href="/account" className="inline-block mt-3 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg font-medium hover:bg-blue-700">
            Upgrade
          </Link>
        </div>
      )}

      {/* Results */}
      {data && data.results && data.results.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-900">{data.total} stocks found</span>
            <div className="flex items-center gap-3">
              {tier !== "free" && (
                <button
                  onClick={handleExportCSV}
                  className="text-xs font-medium text-blue-600 hover:text-blue-700 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-lg transition"
                >
                  Download CSV
                </button>
              )}
              <span className="text-xs text-gray-400">Page {data.page}</span>
            </div>
          </div>
          <div className="divide-y divide-gray-50">
            {data.results.map((stock, i) => {
              const cleanTicker = stock.ticker.replace(".NS", "").replace(".BO", "")
              const mosColor = stock.margin_of_safety >= 15
                ? "text-green-600"
                : stock.margin_of_safety >= 0
                  ? "text-blue-600"
                  : stock.margin_of_safety >= -15
                    ? "text-amber-600"
                    : "text-red-600"

              return (
                <Link
                  key={stock.ticker}
                  href={`/analysis/${stock.ticker.includes(".") ? stock.ticker : stock.ticker + ".NS"}`}
                  className="flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-400 w-6 text-right">{i + 1}</span>
                    <span className="text-sm font-semibold text-blue-700">{cleanTicker}</span>
                  </div>
                  <div className="flex items-center gap-6">
                    <div className="text-right">
                      <span className="text-sm font-bold text-gray-900">{stock.score}</span>
                      <span className="text-xs text-gray-400 ml-1">score</span>
                    </div>
                    <div className="text-right w-16">
                      <span className={`text-sm font-semibold ${mosColor}`}>
                        {stock.margin_of_safety >= 0 ? "+" : ""}{stock.margin_of_safety.toFixed(0)}%
                      </span>
                    </div>
                  </div>
                </Link>
              )
            })}
          </div>
        </div>
      )}

      {/* Empty */}
      {data && (!data.results || data.results.length === 0) && (
        <div className="bg-gray-50 border border-gray-100 rounded-xl p-8 text-center">
          <p className="text-sm text-gray-500">No stocks match this criteria.</p>
          <p className="text-xs text-gray-400 mt-1">Try a different preset or lower the filters.</p>
        </div>
      )}
    </div>
  )
}

export default function ScreenerPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center py-20">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
      </div>
    }>
      <ScreenerContent />
    </Suspense>
  )
}
