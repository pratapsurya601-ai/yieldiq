"use client"
import { useState } from "react"
import { useRouter } from "next/navigation"

const POPULAR = [
  { ticker: "RELIANCE.NS", label: "RELIANCE" },
  { ticker: "TCS.NS", label: "TCS" },
  { ticker: "INFY.NS", label: "INFY" },
  { ticker: "HDFCBANK.NS", label: "HDFC BANK" },
  { ticker: "ICICIBANK.NS", label: "ICICI BANK" },
  { ticker: "ITC.NS", label: "ITC" },
  { ticker: "SBIN.NS", label: "SBI" },
  { ticker: "TATAMOTORS.NS", label: "TATA MOTORS" },
]

export default function SearchPage() {
  const [ticker, setTicker] = useState("")
  const router = useRouter()

  const handleAnalyse = () => {
    if (!ticker.trim()) return
    let t = ticker.trim().toUpperCase()
    if (!t.includes(".") && !t.match(/^[A-Z]{1,5}$/)) {
      t = t + ".NS"
    }
    router.push(`/analysis/${t}`)
  }

  return (
    <div className="max-w-md mx-auto px-4 py-12 space-y-8">
      <div className="text-center">
        <h1 className="text-xl font-bold text-gray-900 mb-1">Analyse a stock</h1>
        <p className="text-sm text-gray-500">Enter any NSE/BSE ticker to get a full DCF valuation</p>
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAnalyse()}
          placeholder="e.g. RELIANCE.NS, TCS.NS, AAPL"
          className="flex-1 px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
        <button
          onClick={handleAnalyse}
          className="px-6 py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition"
        >
          Analyse
        </button>
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
