"use client"

import { useState } from "react"
import { useSettingsStore } from "@/store/settingsStore"

interface LearnTipProps {
  tipKey: string
}

const TIPS: Record<string, string> = {
  wacc: "WACC (Weighted Average Cost of Capital) is the minimum return a company must earn to satisfy its investors. A higher WACC means the company is riskier.",
  mos: "Margin of Safety is the gap between the current price and our estimated fair value. A larger gap means more room for error in our estimates.",
  fcf: "Free Cash Flow is the cash a company generates after paying for operations and capital expenditures. It is what is actually available to shareholders.",
  score: "The YieldIQ Score combines valuation, quality, and momentum signals into a single 0-100 rating. Higher is better.",
  moat: "An economic moat is a durable competitive advantage that protects a company from competitors, like established brands, network effects, or switching costs.",
  piotroski: "The Piotroski F-Score (0-9) measures financial quality using 9 accounting signals. A score of 7+ suggests durable fundamentals.",
  dcf: "Discounted Cash Flow analysis estimates what a company is worth today by projecting future cash flows and discounting them back to present value.",
  confidence: "Confidence reflects how reliable our data inputs are. High confidence means consistent financials and good analyst coverage.",
}

export default function LearnTip({ tipKey }: LearnTipProps) {
  const learnMode = useSettingsStore((s) => s.learnMode)
  const [open, setOpen] = useState(false)

  if (!learnMode) return null

  const tip = TIPS[tipKey]
  if (!tip) return null

  // Compact: small info icon inline, expands on click
  return (
    <span className="inline-flex items-center">
      <button
        onClick={() => setOpen(!open)}
        className="ml-1 w-4 h-4 rounded-full bg-blue-100 text-blue-500 inline-flex items-center justify-center hover:bg-blue-200 transition-colors flex-shrink-0"
        aria-label="Learn more"
      >
        <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 001.5-.189m-1.5.189a6.01 6.01 0 01-1.5-.189m3.75 7.478a12.06 12.06 0 01-4.5 0m3.75 2.383a14.406 14.406 0 01-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 10-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" />
        </svg>
      </button>
      {open && (
        <span className="ml-1.5 text-[10px] text-blue-600 leading-tight">{tip}</span>
      )}
    </span>
  )
}
