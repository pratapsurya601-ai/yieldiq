"use client"
import { useState, useEffect, useRef, useCallback, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { compareStocks } from "@/lib/api"
import api from "@/lib/api"
import { formatCurrency, formatPct, cn } from "@/lib/utils"
import { SCORE_COLOR, VERDICT_COLORS } from "@/lib/constants"
import type { Verdict } from "@/types/api"
import Link from "next/link"

interface SearchResult {
  ticker: string
  name: string
}

interface StockData {
  ticker: string
  company_name: string
  sector: string
  price: number
  fair_value: number
  mos: number
  verdict: Verdict
  score: number
  piotroski: number
  moat: string
  moat_score: number
  wacc: number
  fcf_growth: number
  confidence: number
  roe: number
  de_ratio: number
}

interface CompareResponse {
  stock1: StockData
  stock2: StockData
  winner: {
    score: string
    value: string
    quality: string
    moat: string
  }
}

function StockSearchInput({
  value,
  onSelect,
  placeholder,
}: {
  value: string
  onSelect: (ticker: string, name: string) => void
  placeholder: string
}) {
  const [query, setQuery] = useState("")
  const [suggestions, setSuggestions] = useState<SearchResult[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const debounceRef = useRef<NodeJS.Timeout | null>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.length < 2) {
      setSuggestions([])
      return
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.get(`/api/v1/search?q=${encodeURIComponent(query)}`)
        setSuggestions(res.data.results || [])
        setShowSuggestions(true)
      } catch {
        setSuggestions([])
      }
    }, 200)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query])

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [])

  return (
    <div ref={wrapperRef} className="relative flex-1">
      {value ? (
        <div className="flex items-center gap-2 px-3 py-2.5 bg-blue-50 border border-blue-200 rounded-xl">
          <span className="text-sm font-medium text-blue-800 flex-1 truncate">{value}</span>
          <button
            onClick={() => onSelect("", "")}
            className="text-blue-400 hover:text-blue-600 text-xs"
          >
            Change
          </button>
        </div>
      ) : (
        <>
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            placeholder={placeholder}
            className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          {showSuggestions && suggestions.length > 0 && (
            <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
              {suggestions.map((s) => (
                <button
                  key={s.ticker}
                  onClick={() => {
                    onSelect(s.ticker, s.name)
                    setQuery("")
                    setShowSuggestions(false)
                  }}
                  className="w-full text-left px-4 py-3 hover:bg-blue-50 transition flex items-center justify-between border-b border-gray-50 last:border-0"
                >
                  <span className="font-medium text-gray-900 text-sm">{s.name}</span>
                  <span className="text-xs text-gray-400 font-mono">{s.ticker.replace(".NS", "")}</span>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const colors = VERDICT_COLORS[verdict]
  const label = verdict.replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase())
  return (
    <span className={cn("inline-flex items-center rounded-full font-medium border px-2 py-0.5 text-xs", colors.bg, colors.text, colors.border)}>
      {label}
    </span>
  )
}

function CompareRow({
  label,
  val1,
  val2,
  winner,
  highlight,
}: {
  label: string
  val1: React.ReactNode
  val2: React.ReactNode
  winner?: 1 | 2 | null
  highlight?: boolean
}) {
  return (
    <div className={cn("grid grid-cols-3 items-center gap-2 px-3 py-2.5 rounded-lg text-sm", highlight ? "bg-gray-50" : "")}>
      <span className="text-gray-500 text-xs font-medium">{label}</span>
      <span className={cn("text-center font-medium", winner === 1 ? "text-blue-700 bg-blue-50 rounded-md px-2 py-0.5" : "text-gray-900")}>
        {val1}
      </span>
      <span className={cn("text-center font-medium", winner === 2 ? "text-blue-700 bg-blue-50 rounded-md px-2 py-0.5" : "text-gray-900")}>
        {val2}
      </span>
    </div>
  )
}

function CompareContent() {
  const searchParams = useSearchParams()
  const preselected1 = searchParams.get("stock1") || ""
  const preselected2 = searchParams.get("stock2") || ""

  const [ticker1, setTicker1] = useState(preselected1)
  const [name1, setName1] = useState(preselected1 ? preselected1.replace(".NS", "").replace(".BO", "") : "")
  const [ticker2, setTicker2] = useState(preselected2)
  const [name2, setName2] = useState(preselected2 ? preselected2.replace(".NS", "").replace(".BO", "") : "")

  const bothSelected = !!ticker1 && !!ticker2

  const { data, isLoading, error } = useQuery<CompareResponse>({
    queryKey: ["compare", ticker1, ticker2],
    queryFn: () => compareStocks(ticker1, ticker2),
    enabled: bothSelected,
    staleTime: 5 * 60 * 1000,
  })

  const handleSelect1 = useCallback((ticker: string, name: string) => {
    setTicker1(ticker)
    setName1(name)
  }, [])

  const handleSelect2 = useCallback((ticker: string, name: string) => {
    setTicker2(ticker)
    setName2(name)
  }, [])

  function getWinner(v1: number, v2: number, higherIsBetter = true): 1 | 2 | null {
    if (v1 === v2) return null
    if (higherIsBetter) return v1 > v2 ? 1 : 2
    return v1 < v2 ? 1 : 2
  }

  const s1 = data?.stock1
  const s2 = data?.stock2

  // Count overall wins
  let wins1 = 0
  let wins2 = 0
  if (data) {
    const w = data.winner
    if (w.score === ticker1) wins1++; else wins2++
    if (w.value === ticker1) wins1++; else wins2++
    if (w.quality === ticker1) wins1++; else wins2++
    if (w.moat === ticker1) wins1++; else wins2++
  }
  const overallWinner = wins1 > wins2 ? ticker1 : wins2 > wins1 ? ticker2 : null

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-5 pb-20">
      <div className="text-center">
        <h1 className="text-lg font-bold text-gray-900 mb-1">Compare Stocks</h1>
        <p className="text-xs text-gray-500">Pick two stocks to compare side by side</p>
      </div>

      {/* Stock pickers */}
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Stock 1</p>
          <StockSearchInput
            value={name1}
            onSelect={handleSelect1}
            placeholder="Search... e.g. Reliance"
          />
        </div>
        <button
          onClick={() => {
            const t1 = ticker1, n1 = name1
            setTicker1(ticker2); setName1(name2)
            setTicker2(t1); setName2(n1)
          }}
          className="mb-0.5 p-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition text-gray-400 hover:text-gray-600 shrink-0"
          title="Swap stocks"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
          </svg>
        </button>
        <div className="flex-1">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Stock 2</p>
          <StockSearchInput
            value={name2}
            onSelect={handleSelect2}
            placeholder="Search... e.g. TCS"
          />
        </div>
      </div>

      {/* Loading */}
      {bothSelected && isLoading && (
        <div className="text-center py-12">
          <div className="inline-block h-6 w-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mb-3" />
          <p className="text-sm text-gray-500">Crunching numbers...</p>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="text-center py-8">
          <p className="text-sm text-red-600">Failed to compare. Please try again.</p>
        </div>
      )}

      {/* Comparison table */}
      {s1 && s2 && (
        <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
          {/* Header */}
          <div className="grid grid-cols-3 items-center gap-2 px-3 py-3 border-b border-gray-100 bg-gray-50">
            <span className="text-xs font-bold text-gray-400 uppercase tracking-widest">Metric</span>
            <div className="text-center">
              <Link href={`/analysis/${s1.ticker}`} className="text-sm font-semibold text-gray-900 hover:text-blue-600 transition">
                {s1.company_name}
              </Link>
              <p className="text-[10px] text-gray-400">{s1.ticker.replace(".NS", "")} &middot; {s1.sector}</p>
            </div>
            <div className="text-center">
              <Link href={`/analysis/${s2.ticker}`} className="text-sm font-semibold text-gray-900 hover:text-blue-600 transition">
                {s2.company_name}
              </Link>
              <p className="text-[10px] text-gray-400">{s2.ticker.replace(".NS", "")} &middot; {s2.sector}</p>
            </div>
          </div>

          {/* Rows */}
          <div className="divide-y divide-gray-50">
            <CompareRow
              label="YieldIQ Score"
              val1={<span style={{ color: SCORE_COLOR(s1.score) }}>{s1.score}/100</span>}
              val2={<span style={{ color: SCORE_COLOR(s2.score) }}>{s2.score}/100</span>}
              winner={getWinner(s1.score, s2.score)}
              highlight
            />
            <CompareRow
              label="Verdict"
              val1={<VerdictBadge verdict={s1.verdict} />}
              val2={<VerdictBadge verdict={s2.verdict} />}
            />
            <CompareRow
              label="Fair Value"
              val1={formatCurrency(s1.fair_value)}
              val2={formatCurrency(s2.fair_value)}
              highlight
            />
            <CompareRow
              label="Current Price"
              val1={formatCurrency(s1.price)}
              val2={formatCurrency(s2.price)}
            />
            <CompareRow
              label="Margin of Safety"
              val1={<span className={s1.mos >= 0 ? "text-blue-600" : "text-amber-600"}>{formatPct(s1.mos)}</span>}
              val2={<span className={s2.mos >= 0 ? "text-blue-600" : "text-amber-600"}>{formatPct(s2.mos)}</span>}
              winner={getWinner(s1.mos, s2.mos)}
              highlight
            />
            <CompareRow
              label="Piotroski F-Score"
              val1={`${s1.piotroski}/9`}
              val2={`${s2.piotroski}/9`}
              winner={getWinner(s1.piotroski, s2.piotroski)}
            />
            <CompareRow
              label="Moat"
              val1={s1.moat}
              val2={s2.moat}
              winner={getWinner(s1.moat_score, s2.moat_score)}
              highlight
            />
            <CompareRow
              label="WACC"
              val1={`${s1.wacc.toFixed(1)}%`}
              val2={`${s2.wacc.toFixed(1)}%`}
              winner={getWinner(s1.wacc, s2.wacc, false)}
            />
            <CompareRow
              label="FCF Growth"
              val1={formatPct(s1.fcf_growth)}
              val2={formatPct(s2.fcf_growth)}
              winner={getWinner(s1.fcf_growth, s2.fcf_growth)}
              highlight
            />
            <CompareRow
              label="Confidence"
              val1={`${s1.confidence}/100`}
              val2={`${s2.confidence}/100`}
              winner={getWinner(s1.confidence, s2.confidence)}
            />
            <CompareRow
              label="ROE"
              val1={`${s1.roe.toFixed(1)}%`}
              val2={`${s2.roe.toFixed(1)}%`}
              winner={getWinner(s1.roe, s2.roe)}
              highlight
            />
            <CompareRow
              label="D/E Ratio"
              val1={s1.de_ratio.toFixed(2)}
              val2={s2.de_ratio.toFixed(2)}
              winner={getWinner(s1.de_ratio, s2.de_ratio, false)}
            />
          </div>
        </div>
      )}

      {/* Winner summary */}
      {data && s1 && s2 && (
        <div className="bg-gradient-to-br from-blue-50 to-white rounded-2xl border border-blue-100 p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">Overall Winner</h2>
          {overallWinner ? (
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-blue-600 flex items-center justify-center text-white text-lg font-bold">
                {overallWinner === ticker1 ? "1" : "2"}
              </div>
              <div>
                <p className="font-semibold text-gray-900">
                  {overallWinner === ticker1 ? s1.company_name : s2.company_name}
                </p>
                <p className="text-xs text-gray-500">
                  Wins {Math.max(wins1, wins2)} of 4 categories: Score, Value, Quality, Moat
                </p>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-600">It&apos;s a tie! Both stocks are evenly matched across key metrics.</p>
          )}
          <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            {(["score", "value", "quality", "moat"] as const).map((cat) => {
              const winTicker = data.winner[cat]
              const winName = winTicker === s1.ticker ? s1.company_name : s2.company_name
              return (
                <div key={cat} className="bg-white rounded-lg border border-gray-100 px-3 py-2 text-center">
                  <p className="text-gray-400 uppercase tracking-widest mb-1" style={{ fontSize: "9px" }}>
                    {cat}
                  </p>
                  <p className="font-medium text-gray-900 truncate">{winName.split(" ")[0]}</p>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!bothSelected && !isLoading && (
        <div className="text-center py-12">
          <p className="text-3xl mb-3">&#x2696;&#xFE0F;</p>
          <p className="text-sm text-gray-500">Select two stocks above to compare them</p>
        </div>
      )}

      <p className="text-[10px] text-gray-400 text-center leading-relaxed px-4">
        All outputs are model estimates using publicly available data. Not investment advice.
      </p>
    </div>
  )
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center py-20 text-gray-400">Loading comparison...</div>}>
      <CompareContent />
    </Suspense>
  )
}
