"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"

interface HealthScoreProps {
  score: number
  grade: string
  summary: string
  issues: string[]
  strengths: string[]
}

export default function HealthScore({ score, grade, summary, issues, strengths }: HealthScoreProps) {
  // Auto-expand if there are actionable issues — users shouldn't have to click to see them
  const [expanded, setExpanded] = useState(issues.length > 0)

  const scoreColor =
    score >= 70 ? "bg-blue-600" : score >= 50 ? "bg-amber-500" : "bg-red-500"

  const gradeColor =
    score >= 70 ? "text-blue-700" : score >= 50 ? "text-amber-700" : "text-red-700"

  return (
    <div className={cn("rounded-xl bg-surface border border-border shadow-sm p-4")}>
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-xs text-caption mb-0.5">Portfolio Health</p>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-ink">{score}</span>
            <span className={cn("text-lg font-semibold", gradeColor)}>
              {grade}
            </span>
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-2 w-full rounded-full bg-border overflow-hidden mb-3">
        <div
          className={cn("h-full rounded-full transition-all duration-700", scoreColor)}
          style={{ width: `${score}%` }}
        />
      </div>

      <p className="text-sm text-body mb-3">{summary}</p>

      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs font-medium text-brand hover:opacity-80 transition-colors"
      >
        {expanded ? "Show less" : "Show details"}
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          {strengths.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-body mb-1">Strengths</p>
              <ul className="space-y-1">
                {strengths.map((s, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs text-body">
                    <svg className="h-3.5 w-3.5 text-blue-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {issues.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-body mb-1">Observations</p>
              <ul className="space-y-1">
                {issues.map((issue, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs text-body">
                    <svg className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                    </svg>
                    {issue}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
