"use client"
// /portfolio/analyze — Portfolio Prism aggregator (Phase 1, 2026-05-03).
//
// Stateless one-shot analysis page. The user enters up to 25 holdings
// (ticker + share count), the page POSTs to
// /api/v1/portfolio/analyze, and we render four panels:
//
//   1. Per-pillar Prism bars (value / quality / growth / moat / safety / pulse)
//   2. Sector concentration pie
//   3. Valuation skew stacked bar
//   4. Piotroski distribution (3 cards: strong / moderate / weak)
//
// Phase 1 explicitly omits substitution suggestions and persistence —
// nothing is saved server-side. Phase 2 will add a Save button that
// writes to user_portfolios + tier-gate the endpoint.

import { useState, useEffect, useRef, useCallback } from "react"
import api from "@/lib/api"
import {
  PieChart, Pie, Cell, Tooltip as RTooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend,
} from "recharts"

const PILLARS = [
  { key: "value",   label: "Value",   color: "#2563eb" },
  { key: "quality", label: "Quality", color: "#0891b2" },
  { key: "growth",  label: "Growth",  color: "#16a34a" },
  { key: "moat",    label: "Moat",    color: "#a16207" },
  { key: "safety",  label: "Safety",  color: "#7c3aed" },
  { key: "pulse",   label: "Pulse",   color: "#db2777" },
] as const

const SECTOR_COLORS = [
  "#2563eb", "#16a34a", "#a16207", "#7c3aed", "#db2777",
  "#0891b2", "#ea580c", "#475569", "#ca8a04", "#9333ea",
]

const SKEW_COLORS: Record<string, string> = {
  undervalued: "#16a34a",
  fairly_valued: "#64748b",
  overvalued: "#dc2626",
  other: "#cbd5e1",
}

const MAX_HOLDINGS = 25

interface Row {
  id: string
  ticker: string
  shares: string  // string for input control; converted to number on submit
}

interface SearchResult {
  ticker: string
  name: string
}

interface AnalyzeResponse {
  summary: {
    holding_count: number
    total_value: number
    composite_score: number | null
    data_limited_count: number
    invalid_tickers: string[]
    data_limited_tickers: string[]
    elapsed_ms: number
  }
  prism_pillars: Record<string, number | null>
  sector_concentration: { sector: string; value: number; pct: number }[]
  valuation_skew: Record<string, number>
  piotroski_distribution: { strong: number; moderate: number; weak: number; unknown: number }
  holdings: {
    ticker: string
    shares: number
    current_price: number | null
    value: number
    weight_pct: number
    sector: string | null
    verdict_band: string | null
    piotroski_score: number | null
    composite_score: number | null
    data_limited: boolean
  }[]
  phase: number
}

function newRow(): Row {
  return { id: Math.random().toString(36).slice(2, 9), ticker: "", shares: "" }
}

// ── Ticker autocomplete (mirrors compare/page.tsx pattern) ──
function TickerInput({
  value,
  onChange,
}: {
  value: string
  onChange: (v: string) => void
}) {
  const [query, setQuery] = useState(value)
  const [suggestions, setSuggestions] = useState<SearchResult[]>([])
  const [open, setOpen] = useState(false)
  const debounceRef = useRef<NodeJS.Timeout | null>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => { setQuery(value) }, [value])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!query || query.length < 2) {
      setSuggestions([])
      return
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.get(`/api/v1/search?q=${encodeURIComponent(query)}`)
        setSuggestions(res.data.results || [])
        setOpen(true)
      } catch {
        setSuggestions([])
      }
    }, 200)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query])

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", onClickOutside)
    return () => document.removeEventListener("mousedown", onClickOutside)
  }, [])

  return (
    <div ref={wrapperRef} className="relative">
      <input
        type="text"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value.toUpperCase())
          onChange(e.target.value.toUpperCase())
        }}
        onFocus={() => suggestions.length > 0 && setOpen(true)}
        placeholder="Ticker (e.g. INFY)"
        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {open && suggestions.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden max-h-56 overflow-y-auto">
          {suggestions.map((s) => (
            <button
              key={s.ticker}
              type="button"
              onClick={() => {
                onChange(s.ticker.toUpperCase())
                setQuery(s.ticker.toUpperCase())
                setOpen(false)
              }}
              className="w-full text-left px-3 py-2 hover:bg-blue-50 text-sm border-b border-gray-50 last:border-0"
            >
              <span className="font-medium text-gray-900">{s.name}</span>
              <span className="ml-2 text-gray-500 text-xs">{s.ticker}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function PortfolioAnalyzePage() {
  const [rows, setRows] = useState<Row[]>([newRow(), newRow()])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AnalyzeResponse | null>(null)

  const updateRow = useCallback((id: string, patch: Partial<Row>) => {
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  }, [])
  const removeRow = useCallback((id: string) => {
    setRows((rs) => (rs.length > 1 ? rs.filter((r) => r.id !== id) : rs))
  }, [])
  const addRow = useCallback(() => {
    setRows((rs) => (rs.length < MAX_HOLDINGS ? [...rs, newRow()] : rs))
  }, [])

  async function onAnalyze() {
    setError(null)
    setResult(null)
    const payload = rows
      .map((r) => ({ ticker: r.ticker.trim().toUpperCase(), shares: Number(r.shares) }))
      .filter((r) => r.ticker && Number.isFinite(r.shares) && r.shares > 0)

    if (payload.length === 0) {
      setError("Add at least one ticker with a share count > 0.")
      return
    }
    if (payload.length > MAX_HOLDINGS) {
      setError(`Maximum ${MAX_HOLDINGS} holdings per analysis.`)
      return
    }

    setLoading(true)
    try {
      const res = await api.post("/api/v1/portfolio/analyze", { holdings: payload })
      setResult(res.data as AnalyzeResponse)
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      setError(typeof detail === "string" ? detail : "Analysis failed. Try again.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Portfolio Prism</h1>
        <p className="text-sm text-gray-600 mt-1">
          Aggregate Prism scores, sector concentration, valuation skew,
          and Piotroski distribution across up to {MAX_HOLDINGS} holdings.
          Stateless — nothing is saved.
        </p>
      </div>

      {/* Holdings input table */}
      <section className="border border-gray-200 rounded-xl p-4 bg-white">
        <div className="grid grid-cols-12 gap-3 text-xs font-medium text-gray-500 mb-2 px-1">
          <div className="col-span-7">Ticker</div>
          <div className="col-span-4">Shares</div>
          <div className="col-span-1"></div>
        </div>
        <div className="space-y-2">
          {rows.map((row) => (
            <div key={row.id} className="grid grid-cols-12 gap-3 items-center">
              <div className="col-span-7">
                <TickerInput
                  value={row.ticker}
                  onChange={(v) => updateRow(row.id, { ticker: v })}
                />
              </div>
              <div className="col-span-4">
                <input
                  type="number"
                  min="0"
                  step="any"
                  value={row.shares}
                  onChange={(e) => updateRow(row.id, { shares: e.target.value })}
                  placeholder="0"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div className="col-span-1">
                <button
                  type="button"
                  onClick={() => removeRow(row.id)}
                  disabled={rows.length === 1}
                  className="text-gray-400 hover:text-red-600 disabled:opacity-30 disabled:cursor-not-allowed text-lg"
                  aria-label="Remove row"
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between mt-4">
          <button
            type="button"
            onClick={addRow}
            disabled={rows.length >= MAX_HOLDINGS}
            className="text-sm text-blue-600 hover:text-blue-800 disabled:text-gray-400 disabled:cursor-not-allowed"
          >
            + Add holding ({rows.length}/{MAX_HOLDINGS})
          </button>
          <button
            type="button"
            onClick={onAnalyze}
            disabled={loading}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white text-sm font-medium rounded-lg"
          >
            {loading ? "Analyzing…" : "Analyze"}
          </button>
        </div>
        {error && (
          <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 px-3 py-2 rounded-lg">
            {error}
          </div>
        )}
      </section>

      {result && <Results data={result} />}
    </div>
  )
}

// ── Results panels ─────────────────────────────────────────────
function Results({ data }: { data: AnalyzeResponse }) {
  const sectors = (data.sector_concentration || []).map((s, i) => ({
    name: s.sector || "Unknown",
    value: s.pct,
    fill: SECTOR_COLORS[i % SECTOR_COLORS.length],
  }))
  const skew = data.valuation_skew || {}
  const skewData = [{
    name: "Portfolio",
    undervalued: skew.undervalued || 0,
    fairly_valued: skew.fairly_valued || 0,
    overvalued: skew.overvalued || 0,
    other: skew.other || 0,
  }]
  const piotroski = data.piotroski_distribution || { strong: 0, moderate: 0, weak: 0, unknown: 0 }

  return (
    <div className="space-y-6">
      {/* Summary strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SummaryStat label="Holdings" value={String(data.summary.holding_count)} />
        <SummaryStat
          label="Total value"
          value={`₹${data.summary.total_value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
        />
        <SummaryStat
          label="Composite Prism"
          value={data.summary.composite_score != null ? `${data.summary.composite_score}/100` : "—"}
        />
        <SummaryStat
          label="Data-limited"
          value={String(data.summary.data_limited_count)}
        />
      </div>
      {data.summary.data_limited_tickers?.length > 0 && (
        <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          Cached data unavailable for: {data.summary.data_limited_tickers.join(", ")}.
          These holdings are excluded from weighted aggregates. Open each ticker
          page once to warm the cache, then retry.
        </div>
      )}

      {/* Per-pillar Prism bars */}
      <Panel title="Prism scores by pillar (value-weighted, 0–100)">
        <div className="space-y-3">
          {PILLARS.map((p) => {
            const v = data.prism_pillars[p.key]
            const pct = typeof v === "number" ? Math.max(0, Math.min(100, v)) : 0
            return (
              <div key={p.key} className="flex items-center gap-3">
                <div className="w-20 text-sm text-gray-700">{p.label}</div>
                <div className="flex-1 h-6 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${pct}%`, backgroundColor: p.color }}
                  />
                </div>
                <div className="w-14 text-right text-sm font-medium text-gray-900">
                  {typeof v === "number" ? v.toFixed(1) : "—"}
                </div>
              </div>
            )
          })}
        </div>
      </Panel>

      {/* Sector pie */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Panel title="Sector concentration">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={sectors}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  label={(e: any) => `${e.name} (${e.value.toFixed(0)}%)`}
                >
                  {sectors.map((s, i) => (
                    <Cell key={i} fill={s.fill} />
                  ))}
                </Pie>
                <RTooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        {/* Valuation skew stacked bar */}
        <Panel title="Valuation skew">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={skewData} layout="vertical" margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
                <YAxis type="category" dataKey="name" hide />
                <RTooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
                <Legend />
                <Bar dataKey="undervalued" stackId="a" fill={SKEW_COLORS.undervalued} />
                <Bar dataKey="fairly_valued" stackId="a" fill={SKEW_COLORS.fairly_valued} />
                <Bar dataKey="overvalued" stackId="a" fill={SKEW_COLORS.overvalued} />
                <Bar dataKey="other" stackId="a" fill={SKEW_COLORS.other} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      {/* Piotroski distribution */}
      <Panel title="Piotroski F-score distribution">
        <div className="grid grid-cols-3 gap-3">
          <PiotroskiCard
            label="High (≥7)"
            count={piotroski.strong}
            color="bg-green-50 text-green-800 border-green-200"
          />
          <PiotroskiCard
            label="Moderate (4–6)"
            count={piotroski.moderate}
            color="bg-amber-50 text-amber-800 border-amber-200"
          />
          <PiotroskiCard
            label="Low (<4)"
            count={piotroski.weak}
            color="bg-red-50 text-red-800 border-red-200"
          />
        </div>
        {piotroski.unknown > 0 && (
          <p className="mt-2 text-xs text-gray-500">
            {piotroski.unknown} holding{piotroski.unknown === 1 ? "" : "s"} without
            a Piotroski score (not yet cached).
          </p>
        )}
      </Panel>

      {/* Per-holding detail table */}
      <Panel title="Holdings">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-500 border-b border-gray-200">
              <tr>
                <th className="text-left py-2 px-2">Ticker</th>
                <th className="text-right py-2 px-2">Shares</th>
                <th className="text-right py-2 px-2">Price</th>
                <th className="text-right py-2 px-2">Value</th>
                <th className="text-right py-2 px-2">Weight</th>
                <th className="text-left py-2 px-2">Sector</th>
                <th className="text-left py-2 px-2">Verdict</th>
                <th className="text-right py-2 px-2">Piotroski</th>
                <th className="text-right py-2 px-2">Score</th>
              </tr>
            </thead>
            <tbody>
              {data.holdings.map((h) => (
                <tr key={h.ticker} className="border-b border-gray-100">
                  <td className="py-2 px-2 font-medium text-gray-900">
                    {h.ticker.replace(/\.NS$/, "")}
                    {h.data_limited && (
                      <span className="ml-1 text-xs text-amber-600">⚠</span>
                    )}
                  </td>
                  <td className="text-right py-2 px-2">{h.shares}</td>
                  <td className="text-right py-2 px-2">
                    {h.current_price != null ? `₹${h.current_price.toFixed(2)}` : "—"}
                  </td>
                  <td className="text-right py-2 px-2">
                    {h.value > 0 ? `₹${h.value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—"}
                  </td>
                  <td className="text-right py-2 px-2">{h.weight_pct.toFixed(1)}%</td>
                  <td className="py-2 px-2 text-gray-700">{h.sector || "—"}</td>
                  <td className="py-2 px-2 text-gray-700">{h.verdict_band || "—"}</td>
                  <td className="text-right py-2 px-2">{h.piotroski_score ?? "—"}</td>
                  <td className="text-right py-2 px-2">{h.composite_score ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <p className="text-xs text-gray-500 text-center pt-2">
        Phase 1 — analysis only. Persistence, tier-aware caps, and substitution
        suggestions ship in the next release.
      </p>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border border-gray-200 rounded-xl p-4 bg-white">
      <h2 className="text-sm font-semibold text-gray-900 mb-3">{title}</h2>
      {children}
    </section>
  )
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-gray-200 rounded-xl p-3 bg-white">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-lg font-semibold text-gray-900 mt-1">{value}</div>
    </div>
  )
}

function PiotroskiCard({
  label, count, color,
}: { label: string; count: number; color: string }) {
  return (
    <div className={`border rounded-lg p-3 ${color}`}>
      <div className="text-xs">{label}</div>
      <div className="text-2xl font-semibold mt-1">{count}</div>
    </div>
  )
}
