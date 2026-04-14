"use client"

import { useState, useEffect } from "react"
import { cn } from "@/lib/utils"

interface AISummaryProps {
  summary: string | null
  ticker: string
}

export default function AISummary({ summary, ticker }: AISummaryProps) {
  const [timedOut, setTimedOut] = useState(false)

  useEffect(() => {
    if (summary) {
      setTimedOut(false)
      return
    }
    const timer = setTimeout(() => setTimedOut(true), 8000)
    return () => clearTimeout(timer)
  }, [summary])

  if (!summary) {
    if (timedOut) {
      return (
        <div className={cn("rounded-xl bg-gray-50 p-4")}>
          <div className="flex items-center gap-2 mb-2">
            <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
            </svg>
            <span className="text-sm font-medium text-gray-500">AI Summary</span>
          </div>
          <p className="text-sm text-gray-500">
            AI summary is temporarily unavailable. Review the valuation data and quality scores above to form your own assessment of {ticker.replace(".NS", "").replace(".BO", "")}.
          </p>
        </div>
      )
    }

    return (
      <div className={cn("rounded-xl bg-gray-50 p-4")}>
        <div className="flex items-center gap-2 mb-2">
          <div className="h-2 w-2 rounded-full bg-blue-400 animate-pulse" />
          <span className="text-sm font-medium text-gray-500">AI Analysis</span>
        </div>
        <p className="text-sm text-gray-400">
          Generating analysis for {ticker}...
        </p>
      </div>
    )
  }

  return (
    <div className={cn("rounded-xl bg-gray-50 p-4")}>
      <div className="flex items-center gap-2 mb-2">
        <svg className="h-4 w-4 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714a2.25 2.25 0 00.659 1.591L19 14.5M14.25 3.104c.251.023.501.05.75.082M19 14.5l-2.47 2.47a2.25 2.25 0 01-1.591.659H9.061a2.25 2.25 0 01-1.591-.659L5 14.5m14 0V17a2 2 0 01-2 2H7a2 2 0 01-2-2v-2.5" />
        </svg>
        <span className="text-sm font-medium text-gray-700">AI Summary</span>
      </div>
      <p className="text-sm leading-relaxed text-gray-700">{summary}</p>
    </div>
  )
}
