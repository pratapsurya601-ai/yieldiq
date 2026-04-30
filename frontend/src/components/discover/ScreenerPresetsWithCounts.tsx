"use client"

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import api from "@/lib/api"
import { cn } from "@/lib/utils"
import type { ScreenerResponse } from "@/types/api"

// Composed wrapper around the preset grid. Shows the match count on each
// card so users get a feel for the result size before running the
// screener. Counts are fetched with page_size=1 (cheap) and kept in React
// Query cache for an hour — presets don't change mid-session.

interface Preset {
  name: string
  description: string
  borderColor: string
  bgGradient: string
  query: string
  // "custom" has no canonical count; skip the fetch.
  countable: boolean
}

// 2026-04-25 dark-mode fix: the original gradients used Tailwind palette
// colors (blue-50 / emerald-50 / violet-50 / amber-50 -> white) that do
// NOT respond to the dark-mode class. In dark mode the cards rendered as
// near-black with the description text invisible. Each preset now carries
// both light AND dark gradient stops, and the description renders in
// `text-body` (one tier brighter than `text-caption`) for legible contrast
// on either background.
const PRESETS: Preset[] = [
  {
    name: "Buffett Style",
    description: "Wide moat, consistent earnings, fair price",
    borderColor: "border-l-blue-600",
    bgGradient:
      "bg-gradient-to-br from-blue-50/50 to-white dark:from-blue-950/30 dark:to-slate-900",
    query: "buffett",
    countable: true,
  },
  {
    name: "Deep Value",
    description: "High margin of safety, low P/E, high FCF yield",
    borderColor: "border-l-emerald-600",
    bgGradient:
      "bg-gradient-to-br from-emerald-50/50 to-white dark:from-emerald-950/30 dark:to-slate-900",
    query: "deep-value",
    countable: true,
  },
  {
    name: "Growth Quality",
    description: "High growth with quality fundamentals",
    borderColor: "border-l-violet-600",
    bgGradient:
      "bg-gradient-to-br from-violet-50/50 to-white dark:from-violet-950/30 dark:to-slate-900",
    query: "growth-quality",
    countable: true,
  },
  {
    name: "Custom",
    description: "Set your own filters and criteria",
    borderColor: "border-l-amber-500",
    bgGradient:
      "bg-gradient-to-br from-amber-50/50 to-white dark:from-amber-950/30 dark:to-slate-900",
    query: "custom",
    countable: false,
  },
]

async function fetchPresetCount(preset: string): Promise<number | null> {
  try {
    const res = await api.get<ScreenerResponse>(`/api/v1/screener/preset/${preset}`, { params: { page_size: 1 } })
    return res.data.total
  } catch {
    // Silent failure — the button still works, just without a count.
    return null
  }
}

function PresetCard({ preset }: { preset: Preset }) {
  const { data: count } = useQuery({
    queryKey: ["preset-count", preset.query],
    queryFn: () => fetchPresetCount(preset.query),
    enabled: preset.countable,
    staleTime: 3_600_000, // 1h
  })

  const label = !preset.countable
    ? "Run"
    : count == null
      ? "Run"
      : `Run \u2014 ${count} match${count === 1 ? "" : "es"}`

  return (
    <Link
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
        {/* `text-body` (one tier brighter than `text-caption`) is needed for
            legible contrast on the colored gradient backgrounds in BOTH
            light and dark mode. The 2026-04-25 dark-mode bug was caused by
            `text-caption` (#94A3B8 in dark) sitting too close in luminance
            to the dark-mode gradient stops. */}
        <p className="text-xs text-body mt-1 line-clamp-2">{preset.description}</p>
      </div>
      <span
        className={cn(
          "inline-flex items-center justify-center rounded-lg px-3 py-1.5 min-h-[36px]",
          "text-xs font-medium bg-bg text-body pointer-events-none"
        )}
      >
        {label}
      </span>
    </Link>
  )
}

export default function ScreenerPresetsWithCounts() {
  return (
    <div className="grid grid-cols-2 gap-3">
      {PRESETS.map((preset) => (
        <PresetCard key={preset.name} preset={preset} />
      ))}
    </div>
  )
}
