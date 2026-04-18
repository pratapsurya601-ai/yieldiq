"use client"
import { useState, useEffect, useRef, useCallback } from "react"
import { useRouter } from "next/navigation"
import api from "@/lib/api"
import { cn } from "@/lib/utils"

const POPULAR = [
  { ticker: "RELIANCE.NS", label: "RELIANCE", sector: "Oil & Gas" },
  { ticker: "TCS.NS", label: "TCS", sector: "IT" },
  { ticker: "INFY.NS", label: "INFOSYS", sector: "IT" },
  { ticker: "HDFCBANK.NS", label: "HDFC BANK", sector: "Banking" },
  { ticker: "ICICIBANK.NS", label: "ICICI BANK", sector: "Banking" },
  { ticker: "ITC.NS", label: "ITC", sector: "FMCG" },
  { ticker: "SBIN.NS", label: "SBI", sector: "Banking" },
  { ticker: "BHARTIARTL.NS", label: "AIRTEL", sector: "Telecom" },
  { ticker: "LT.NS", label: "L&T", sector: "Engineering" },
  { ticker: "SUNPHARMA.NS", label: "SUN PHARMA", sector: "Pharma" },
  { ticker: "TITAN.NS", label: "TITAN", sector: "Consumer" },
  { ticker: "BAJFINANCE.NS", label: "BAJAJ FIN", sector: "Finance" },
]

const SECTOR_LABELS: Record<string, string> = {
  "Oil & Gas": "Oil & Gas",
  IT: "IT",
  Banking: "Banking",
  FMCG: "FMCG",
  Telecom: "Telecom",
  Engineering: "Engg",
  Pharma: "Pharma",
  Consumer: "Consumer",
  Finance: "Finance",
}

interface SearchResult {
  ticker: string
  name: string
}

interface RecentItem {
  ticker: string
  label: string
  timestamp: number
}

function isValidTicker(t: string): boolean {
  return /^[A-Z0-9&\-]{1,20}(\.NS|\.BO)?$/.test(t)
}

function getRecentlyAnalysed(): RecentItem[] {
  try {
    const raw = localStorage.getItem("yieldiq_recent")
    if (!raw) return []
    const parsed = JSON.parse(raw) as RecentItem[]
    return parsed.slice(0, 5)
  } catch {
    return []
  }
}

function saveRecentlyAnalysed(ticker: string, label: string) {
  try {
    const existing = getRecentlyAnalysed()
    const filtered = existing.filter((r) => r.ticker !== ticker)
    const updated = [{ ticker, label, timestamp: Date.now() }, ...filtered].slice(0, 10)
    localStorage.setItem("yieldiq_recent", JSON.stringify(updated))
  } catch {
    // ignore
  }
}

export default function SearchPage() {
  const [query, setQuery] = useState("")
  const [suggestions, setSuggestions] = useState<SearchResult[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [recent, setRecent] = useState<RecentItem[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [highlightIdx, setHighlightIdx] = useState(-1)
  const debounceRef = useRef<NodeJS.Timeout | null>(null)
  const router = useRouter()

  useEffect(() => {
    setRecent(getRecentlyAnalysed())
  }, [])

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.length < 2) {
      setSuggestions([])
      setIsSearching(false)
      setSearchError(null)
      return
    }
    setIsSearching(true)
    setSearchError(null)
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.get(`/api/v1/search?q=${encodeURIComponent(query)}`)
        setSuggestions(res.data.results || [])
        setShowSuggestions(true)
        setHighlightIdx(-1)
      } catch {
        setSuggestions([])
        setSearchError("Search is temporarily unavailable. Try again.")
      } finally {
        setIsSearching(false)
      }
    }, 200)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query])

  const handleSelect = useCallback((ticker: string, name?: string) => {
    setShowSuggestions(false)
    setQuery("")
    saveRecentlyAnalysed(ticker, name || ticker.replace(".NS", "").replace(".BO", ""))
    router.push(`/analysis/${ticker}`)
  }, [router])

  const handleAnalyse = () => {
    if (!query.trim()) return
    let t = query.trim().toUpperCase()
    if (!t.includes(".")) t = t + ".NS"
    if (!isValidTicker(t)) {
      setValidationError("Invalid ticker format. Use letters, numbers, e.g. RELIANCE or TCS.NS")
      return
    }
    setValidationError(null)
    setShowSuggestions(false)
    saveRecentlyAnalysed(t, t.replace(".NS", "").replace(".BO", ""))
    router.push(`/analysis/${t}`)
  }

  return (
    <div className="max-w-md md:max-w-xl mx-auto px-4 py-12 space-y-8 pb-20">
      <div className="text-center">
        <h1 className="text-xl font-bold text-gray-900 mb-1">Analyse a stock</h1>
        <p className="text-sm text-gray-500">Search by company name or NSE ticker</p>
      </div>

      <div className="relative">
        <div className="flex gap-2">
          <div className="relative flex-1">
            {/* Search icon inside input */}
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <input
              type="text"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                if (validationError) setValidationError(null)
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown" && suggestions.length > 0) {
                  e.preventDefault()
                  setShowSuggestions(true)
                  setHighlightIdx((i) => Math.min(i + 1, suggestions.length - 1))
                } else if (e.key === "ArrowUp" && suggestions.length > 0) {
                  e.preventDefault()
                  setHighlightIdx((i) => Math.max(i - 1, 0))
                } else if (e.key === "Enter") {
                  if (highlightIdx >= 0 && suggestions[highlightIdx]) {
                    handleSelect(suggestions[highlightIdx].ticker, suggestions[highlightIdx].name)
                  } else {
                    handleAnalyse()
                  }
                } else if (e.key === "Escape") {
                  setShowSuggestions(false)
                  setHighlightIdx(-1)
                }
              }}
              onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
              placeholder="Search NSE/BSE ticker or company, e.g. RELIANCE, TCS, SBIN.BO"
              className="w-full pl-10 pr-10 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            {isSearching && (
              <svg className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity="0.25" />
                <path d="M22 12a10 10 0 00-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
              </svg>
            )}
          </div>
          <button
            onClick={handleAnalyse}
            className="px-6 py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition"
          >
            Analyse
          </button>
        </div>

        {validationError && (
          <p className="text-xs text-red-600 mt-1 px-1">{validationError}</p>
        )}
        {searchError && (
          <p className="text-xs text-red-600 mt-1 px-1">{searchError}</p>
        )}

        {/* Autocomplete dropdown */}
        {showSuggestions && suggestions.length > 0 && (
          <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
            {suggestions.map((s, i) => (
              <button
                key={s.ticker}
                onMouseEnter={() => { router.prefetch(`/analysis/${s.ticker}`); setHighlightIdx(i) }}
                onMouseDown={(e) => {
                  e.preventDefault()  // Prevent input blur from hiding dropdown
                  handleSelect(s.ticker, s.name)
                }}
                className={cn(
                  "w-full text-left px-4 py-3 transition flex items-center justify-between border-b border-gray-50 last:border-0",
                  i === highlightIdx ? "bg-blue-50" : "hover:bg-blue-50",
                )}
              >
                <div>
                  <span className="font-medium text-gray-900 text-sm">{s.name}</span>
                </div>
                <span className="text-xs text-gray-400 font-mono">{s.ticker.replace(".NS", "")}</span>
              </button>
            ))}
          </div>
        )}

        {/* No-results state */}
        {showSuggestions && !isSearching && !searchError && query.length >= 2 && suggestions.length === 0 && (
          <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg p-4 text-center">
            <p className="text-sm text-gray-600">No stocks found for &ldquo;{query}&rdquo;</p>
            <p className="text-xs text-gray-400 mt-1">Try the NSE ticker (e.g. RELIANCE) or full company name</p>
          </div>
        )}
      </div>

      {/* Recently analysed */}
      {recent.length > 0 && (
        <div>
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-3">Recently analysed</p>
          <div className="flex flex-wrap gap-2">
            {recent.map((r) => (
              <button
                key={r.ticker}
                onMouseEnter={() => router.prefetch(`/analysis/${r.ticker}`)}
                onClick={() => handleSelect(r.ticker, r.label)}
                className="px-3 py-1.5 bg-blue-50 border border-blue-100 rounded-lg text-sm font-medium text-blue-700 hover:bg-blue-100 transition"
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div>
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-3">Popular stocks</p>
        <div className="flex flex-wrap gap-2">
          {POPULAR.map((s) => (
            <button
              key={s.ticker}
              onMouseEnter={() => router.prefetch(`/analysis/${s.ticker}`)}
              onClick={() => handleSelect(s.ticker, s.label)}
              className="px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-700 hover:border-blue-300 hover:text-blue-700 transition inline-flex items-center gap-1.5"
            >
              <span className="text-[10px] text-gray-400 font-normal">{SECTOR_LABELS[s.sector] || ""}</span>
              {s.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
