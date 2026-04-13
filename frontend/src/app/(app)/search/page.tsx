"use client"
import { useState, useEffect, useRef } from "react"
import { useRouter } from "next/navigation"
import api from "@/lib/api"

const POPULAR = [
  { ticker: "RELIANCE.NS", label: "RELIANCE" },
  { ticker: "TCS.NS", label: "TCS" },
  { ticker: "INFY.NS", label: "INFOSYS" },
  { ticker: "HDFCBANK.NS", label: "HDFC BANK" },
  { ticker: "ICICIBANK.NS", label: "ICICI BANK" },
  { ticker: "ITC.NS", label: "ITC" },
  { ticker: "SBIN.NS", label: "SBI" },
  { ticker: "BHARTIARTL.NS", label: "AIRTEL" },
  { ticker: "LT.NS", label: "L&T" },
  { ticker: "SUNPHARMA.NS", label: "SUN PHARMA" },
  { ticker: "TITAN.NS", label: "TITAN" },
  { ticker: "BAJFINANCE.NS", label: "BAJAJ FIN" },
]

interface SearchResult {
  ticker: string
  name: string
}

export default function SearchPage() {
  const [query, setQuery] = useState("")
  const [suggestions, setSuggestions] = useState<SearchResult[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const debounceRef = useRef<NodeJS.Timeout | null>(null)
  const router = useRouter()

  // Debounced search
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
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query])

  const handleSelect = (ticker: string) => {
    setShowSuggestions(false)
    setQuery("")
    router.push(`/analysis/${ticker}`)
  }

  const handleAnalyse = () => {
    if (!query.trim()) return
    let t = query.trim().toUpperCase()
    if (!t.includes(".")) t = t + ".NS"
    setShowSuggestions(false)
    router.push(`/analysis/${t}`)
  }

  return (
    <div className="max-w-md mx-auto px-4 py-12 space-y-8">
      <div className="text-center">
        <h1 className="text-xl font-bold text-gray-900 mb-1">Analyse a stock</h1>
        <p className="text-sm text-gray-500">Search by company name or NSE ticker</p>
      </div>

      <div className="relative">
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAnalyse()}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            placeholder="Search... e.g. Reliance, TCS, Mankind"
            className="flex-1 px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          <button
            onClick={handleAnalyse}
            className="px-6 py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition"
          >
            Analyse
          </button>
        </div>

        {/* Autocomplete dropdown */}
        {showSuggestions && suggestions.length > 0 && (
          <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
            {suggestions.map((s) => (
              <button
                key={s.ticker}
                onClick={() => handleSelect(s.ticker)}
                className="w-full text-left px-4 py-3 hover:bg-blue-50 transition flex items-center justify-between border-b border-gray-50 last:border-0"
              >
                <div>
                  <span className="font-medium text-gray-900 text-sm">{s.name}</span>
                </div>
                <span className="text-xs text-gray-400 font-mono">{s.ticker.replace(".NS", "")}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div>
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-3">Popular stocks</p>
        <div className="flex flex-wrap gap-2">
          {POPULAR.map((s) => (
            <button
              key={s.ticker}
              onClick={() => router.push(`/analysis/${s.ticker}`)}
              className="px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-700 hover:border-blue-300 hover:text-blue-700 transition"
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
