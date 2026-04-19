"use client"

import { useState, useEffect } from "react"
import { cn } from "@/lib/utils"

interface AISummaryProps {
  summary: string | null
  ticker: string
  marginOfSafety?: number
  moat?: string
  confidence?: number
  fairValue?: number
  currentPrice?: number
}

function generateFallbackSummary(props: AISummaryProps): string {
  const {
    ticker,
    marginOfSafety = 0,
    moat = "None",
    confidence = 50,
    fairValue = 0,
    currentPrice = 0,
  } = props
  const cleanTicker = ticker.replace(".NS", "").replace(".BO", "")

  // marginOfSafety: positive = undervalued, negative = overvalued
  let direction = "near"
  let signal = "fairly valued"
  let pct = Math.abs(marginOfSafety)

  if (pct > 2) {
    if (marginOfSafety >= 0) {
      // Positive MoS = price is BELOW fair value = undervalued
      direction = "below"
      signal = "undervalued"
    } else {
      // Negative MoS = price is ABOVE fair value = overvalued
      direction = "above"
      signal = "overvalued"
    }
  }

  const moatLabel =
    moat === "Wide" ? "wide" : moat === "Narrow" ? "narrow" : moat === "N/A (Financial)" ? "N/A (financial sector)" : "no measurable"

  return `${cleanTicker} is currently trading ${pct.toFixed(0)}% ${direction} our fair value estimate, suggesting the stock may be ${signal}. The business has a ${moatLabel} competitive moat. Data quality: ${confidence}/100. This is a quantitative estimate — verify assumptions before acting.`
}

export default function AISummary(props: AISummaryProps) {
  const { summary, ticker } = props
  const [timedOut, setTimedOut] = useState(false)

  useEffect(() => {
    if (summary) {
      setTimedOut(false)
      return
    }
    const timer = setTimeout(() => setTimedOut(true), 4000)
    return () => clearTimeout(timer)
  }, [summary])

  if (!summary) {
    if (timedOut) {
      const fallback = generateFallbackSummary(props)
      return (
        <div className={cn("rounded-xl bg-surface p-4")}>
          <div className="flex items-center gap-2 mb-2">
            <svg className="h-4 w-4 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714a2.25 2.25 0 00.659 1.591L19 14.5M14.25 3.104c.251.023.501.05.75.082M19 14.5l-2.47 2.47a2.25 2.25 0 01-1.591.659H9.061a2.25 2.25 0 01-1.591-.659L5 14.5m14 0V17a2 2 0 01-2 2H7a2 2 0 01-2-2v-2.5" />
            </svg>
            <span className="text-sm font-medium text-body">AI Summary</span>
          </div>
          <p className="text-sm leading-relaxed text-body">{fallback}</p>
        </div>
      )
    }

    return (
      <div className={cn("rounded-xl bg-surface p-4")}>
        <div className="flex items-center gap-2 mb-2">
          <div className="h-2 w-2 rounded-full bg-blue-400 animate-pulse" />
          <span className="text-sm font-medium text-caption">AI Analysis</span>
        </div>
        <p className="text-sm text-caption">
          Generating analysis for {ticker}...
        </p>
      </div>
    )
  }

  return (
    <div className={cn("rounded-xl bg-surface p-4")}>
      <div className="flex items-center gap-2 mb-2">
        <svg className="h-4 w-4 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714a2.25 2.25 0 00.659 1.591L19 14.5M14.25 3.104c.251.023.501.05.75.082M19 14.5l-2.47 2.47a2.25 2.25 0 01-1.591.659H9.061a2.25 2.25 0 01-1.591-.659L5 14.5m14 0V17a2 2 0 01-2 2H7a2 2 0 01-2-2v-2.5" />
        </svg>
        <span className="text-sm font-medium text-body">AI Summary</span>
      </div>
      <p className="text-sm leading-relaxed text-body">{summary}</p>
    </div>
  )
}
