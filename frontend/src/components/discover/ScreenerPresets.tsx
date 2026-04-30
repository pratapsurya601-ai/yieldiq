"use client"

import Link from "next/link"
import { cn } from "@/lib/utils"

interface Preset {
  name: string
  description: string
  borderColor: string
  bgGradient: string
  query: string
}

// 2026-04-25 dark-mode fix: kept in lock-step with the sibling
// `ScreenerPresetsWithCounts` PRESETS list. Any preset name/description/
// border/gradient change must be applied in BOTH files.
const PRESETS: Preset[] = [
  {
    name: "Buffett Style",
    description: "Wide moat, consistent earnings, fair price",
    borderColor: "border-l-blue-600",
    bgGradient:
      "bg-gradient-to-br from-blue-50/50 to-white dark:from-blue-950/30 dark:to-slate-900",
    query: "buffett",
  },
  {
    name: "Deep Value",
    description: "High margin of safety, low P/E, high FCF yield",
    borderColor: "border-l-emerald-600",
    bgGradient:
      "bg-gradient-to-br from-emerald-50/50 to-white dark:from-emerald-950/30 dark:to-slate-900",
    query: "deep-value",
  },
  {
    name: "Growth Quality",
    description: "High growth with quality fundamentals",
    borderColor: "border-l-violet-600",
    bgGradient:
      "bg-gradient-to-br from-violet-50/50 to-white dark:from-violet-950/30 dark:to-slate-900",
    query: "growth-quality",
  },
  {
    name: "Custom",
    description: "Set your own filters and criteria",
    borderColor: "border-l-amber-500",
    bgGradient:
      "bg-gradient-to-br from-amber-50/50 to-white dark:from-amber-950/30 dark:to-slate-900",
    query: "custom",
  },
]

export default function ScreenerPresets() {
  return (
    <div className="grid grid-cols-2 gap-3">
      {PRESETS.map((preset) => (
        <Link
          key={preset.name}
          href={`/discover/screener?preset=${preset.query}`}
          className={cn(
            "rounded-xl border border-border shadow-sm",
            "border-l-4 p-3 flex flex-col justify-between",
            "cursor-pointer hover:shadow-md hover:border-l-[6px] active:scale-[0.99] transition",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            preset.borderColor,
            preset.bgGradient
          )}
        >
          <div className="mb-3">
            <h3 className="text-sm font-semibold text-ink">{preset.name}</h3>
            {/* `text-body` (one tier brighter than `text-caption`) is needed
                for legible contrast on the colored gradient backgrounds in
                BOTH light and dark mode. See sibling component comment. */}
            <p className="text-xs text-body mt-1 line-clamp-2">{preset.description}</p>
          </div>
          <span
            className={cn(
              "inline-flex items-center justify-center rounded-lg px-3 py-1.5",
              "text-xs font-medium bg-bg text-body pointer-events-none"
            )}
          >
            Run
          </span>
        </Link>
      ))}
    </div>
  )
}
