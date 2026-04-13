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

const PRESETS: Preset[] = [
  {
    name: "Buffett Style",
    description: "Wide moat, strong earnings, fair price",
    borderColor: "border-l-blue-600",
    bgGradient: "bg-gradient-to-br from-blue-50/50 to-white",
    query: "buffett",
  },
  {
    name: "Deep Value",
    description: "High margin of safety, low P/E, high FCF yield",
    borderColor: "border-l-emerald-600",
    bgGradient: "bg-gradient-to-br from-emerald-50/50 to-white",
    query: "deep-value",
  },
  {
    name: "Growth Quality",
    description: "Strong growth with quality fundamentals",
    borderColor: "border-l-violet-600",
    bgGradient: "bg-gradient-to-br from-violet-50/50 to-white",
    query: "growth-quality",
  },
  {
    name: "Custom",
    description: "Set your own filters and criteria",
    borderColor: "border-l-amber-500",
    bgGradient: "bg-gradient-to-br from-amber-50/50 to-white",
    query: "custom",
  },
]

export default function ScreenerPresets() {
  return (
    <div className="grid grid-cols-2 gap-3">
      {PRESETS.map((preset) => (
        <div
          key={preset.name}
          className={cn(
            "rounded-xl border border-gray-100 shadow-sm",
            "border-l-4 p-3 flex flex-col justify-between",
            preset.borderColor,
            preset.bgGradient
          )}
        >
          <div className="mb-3">
            <h3 className="text-sm font-semibold text-gray-900">{preset.name}</h3>
            <p className="text-xs text-gray-500 mt-1 line-clamp-2">{preset.description}</p>
          </div>
          <Link
            href={`/discover/screener?preset=${preset.query}`}
            className={cn(
              "inline-flex items-center justify-center rounded-lg px-3 py-1.5",
              "text-xs font-medium bg-gray-100 text-gray-700",
              "hover:bg-gray-200 active:bg-gray-300 transition-colors"
            )}
          >
            Run
          </Link>
        </div>
      ))}
    </div>
  )
}
