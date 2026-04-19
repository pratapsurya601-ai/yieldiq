"use client"

import { useMemo, useState } from "react"
import { cn } from "@/lib/utils"
import type { RedFlag } from "@/types/api"

interface Props {
  flags: RedFlag[]
}

const SEVERITY_ORDER: Record<RedFlag["severity"], number> = {
  critical: 0,
  warning: 1,
  info: 2,
}

const SEVERITY_LABEL: Record<RedFlag["severity"], string> = {
  critical: "🔴 CRITICAL",
  warning: "🟡 WARNING",
  info: "✅ STRENGTH",
}

const SEVERITY_CARD: Record<RedFlag["severity"], string> = {
  critical: "border-l-4 border-red-500 bg-red-50",
  warning: "border-l-4 border-yellow-500 bg-yellow-50",
  info: "border-l-4 border-green-500 bg-green-50",
}

const SEVERITY_BADGE: Record<RedFlag["severity"], string> = {
  critical: "text-red-700",
  warning: "text-yellow-700",
  info: "text-green-700",
}

export default function RedFlagInsights({ flags }: Props) {
  const [expanded, setExpanded] = useState(false)

  const sorted = useMemo(() => {
    return [...flags].sort(
      (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]
    )
  }, [flags])

  const counts = useMemo(() => {
    let risks = 0
    let strengths = 0
    for (const f of flags) {
      if (f.severity === "info") strengths += 1
      else risks += 1
    }
    return { risks, strengths }
  }, [flags])

  // Nothing to show — render null so the layout collapses
  if (!flags || flags.length === 0) return null

  const summaryLine = (() => {
    const risks =
      counts.risks === 0
        ? "No risks"
        : `${counts.risks} ${counts.risks === 1 ? "risk" : "risks"}`
    const strengths =
      counts.strengths === 0
        ? "No strengths"
        : `${counts.strengths} ${counts.strengths === 1 ? "strength" : "strengths"}`
    return `${risks} · ${strengths} found`
  })()

  // Index of the first "info" flag — used to insert the divider
  const firstInfoIdx = sorted.findIndex(f => f.severity === "info")
  const hasBoth = firstInfoIdx > 0 && counts.risks > 0

  return (
    <div className="bg-surface rounded-2xl border border-border overflow-hidden">
      {/* Collapsed header — always shown */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between p-4 hover:bg-bg transition-colors text-left"
        aria-expanded={expanded}
      >
        <div>
          <p className="text-sm font-semibold text-ink">
            🔍 Risk &amp; Quality Deep Dive
          </p>
          <p className="text-xs text-caption mt-0.5">{summaryLine}</p>
        </div>
        <span
          className={cn(
            "text-caption text-sm transition-transform duration-200",
            expanded && "rotate-180"
          )}
          aria-hidden="true"
        >
          ▼
        </span>
      </button>

      {/* Expanded panel */}
      {expanded && (
        <div className="px-4 pb-4 pt-1 space-y-3 border-t border-border">
          {sorted.map((f, i) => (
            <div key={`${f.flag}-${i}`}>
              {/* Divider before first positive card */}
              {hasBoth && i === firstInfoIdx && (
                <div className="flex items-center gap-2 py-2">
                  <div className="flex-1 h-px bg-border" />
                  <span className="text-[11px] text-caption uppercase tracking-wider">
                    Positive signals
                  </span>
                  <div className="flex-1 h-px bg-border" />
                </div>
              )}

              <article className={cn("rounded-xl p-4 space-y-2", SEVERITY_CARD[f.severity])}>
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={cn(
                      "text-[11px] font-bold uppercase tracking-wider",
                      SEVERITY_BADGE[f.severity]
                    )}
                  >
                    {SEVERITY_LABEL[f.severity]}
                  </span>
                </div>
                <h3 className="text-sm font-semibold text-ink">{f.title}</h3>
                <p className="text-xs text-body font-mono tabular-nums">
                  {f.data_point}
                </p>
                <p className="text-xs text-body leading-relaxed">
                  {f.explanation}
                </p>
                <div className="pt-1">
                  <p className="text-[11px] font-semibold text-caption uppercase tracking-wide mb-0.5">
                    Why it matters
                  </p>
                  <p className="text-xs text-body leading-relaxed">
                    {f.why_it_matters}
                  </p>
                </div>
              </article>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
