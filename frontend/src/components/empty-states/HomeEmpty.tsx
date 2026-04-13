"use client"

import Link from "next/link"
import { cn } from "@/lib/utils"

const POPULAR_TICKERS = [
  { ticker: "RELIANCE", label: "Reliance" },
  { ticker: "TCS", label: "TCS" },
  { ticker: "INFY", label: "Infy" },
  { ticker: "HDFCBANK", label: "HDFC Bank" },
]

export default function HomeEmpty() {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="h-16 w-16 rounded-full bg-blue-50 flex items-center justify-center mb-4">
        <svg className="h-8 w-8 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 01-2.25 2.25M16.5 7.5V18a2.25 2.25 0 002.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 002.25 2.25h13.5M6 7.5h3v3H6v-3z" />
        </svg>
      </div>

      <h2 className="text-lg font-semibold text-gray-900 mb-1">
        Your market briefing will live here
      </h2>
      <p className="text-sm text-gray-500 mb-6 max-w-xs">
        Start by analysing a stock to see personalised insights and your daily briefing.
      </p>

      <p className="text-xs text-gray-400 mb-3">Popular picks</p>
      <div className="flex flex-wrap justify-center gap-2">
        {POPULAR_TICKERS.map((item) => (
          <Link
            key={item.ticker}
            href={`/analysis/${item.ticker}`}
            className={cn(
              "inline-flex items-center rounded-full px-4 py-2",
              "bg-white border border-gray-200 text-sm font-medium text-gray-700",
              "hover:border-blue-300 hover:text-blue-700 active:bg-blue-50",
              "transition-colors shadow-sm"
            )}
          >
            {item.label}
          </Link>
        ))}
      </div>
    </div>
  )
}
