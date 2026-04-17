"use client"

import { useState } from "react"
import type { ValidationResult } from "@/lib/validators"

/**
 * Banner shown when a stock's data fails sanity checks.
 * Critical issues hide all valuation fields.
 */
export default function DataQualityBanner({
  result,
  ticker,
}: {
  result: ValidationResult
  ticker: string
}) {
  const [expanded, setExpanded] = useState(false)

  if (result.ok) return null

  const critical = result.severity === "critical"
  const bg = critical ? "bg-red-50" : "bg-amber-50"
  const border = critical ? "border-red-200" : "border-amber-200"
  const text = critical ? "text-red-900" : "text-amber-900"
  const icon = critical ? "⚠" : "ⓘ"

  return (
    <div className={`${bg} ${border} ${text} border rounded-xl p-4 mb-4`}>
      <div className="flex items-start gap-3">
        <span className="text-lg" aria-hidden="true">{icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold">
            {critical ? "Data Under Review" : "Data Quality Notice"}
          </p>
          <p className="text-sm mt-1 leading-relaxed">{result.bannerMessage}</p>
          {result.issues.length > 0 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-xs underline mt-2 font-semibold"
            >
              {expanded ? "Hide details" : `Show ${result.issues.length} observation${result.issues.length === 1 ? "" : "s"}`}
            </button>
          )}
          {expanded && (
            <ul className="mt-2 space-y-1 text-xs opacity-80">
              {result.issues.map((iss, i) => (
                <li key={i}>• {iss}</li>
              ))}
            </ul>
          )}
          <p className="text-xs mt-3 opacity-70">
            Reported as ticker: <span className="font-mono">{ticker}</span> &middot;
            We&apos;re continuously improving data quality. <a href="/account" className="underline">Contact support</a> if this persists.
          </p>
        </div>
      </div>
    </div>
  )
}
