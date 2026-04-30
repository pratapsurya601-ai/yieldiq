"use client"

import Link from "next/link"
import { cn } from "@/lib/utils"

// 2026-04-30 P0 fix: preset cards used to point at
// `/discover/screener?preset=<key>`, which calls the auth-gated
// `/api/v1/screener/preset/<key>` endpoint. For free-tier (and logged-out)
// users that endpoint 401s, so the destination page rendered the
// "Screener requires Starter plan" upsell instead of results — making the
// preset cards feel completely broken on the public landing surface.
//
// The DSL screener at `/screener?filters=...` is public (uses
// `/api/v1/public/screener/query`) and renders for everyone. We rewrite
// each preset card's href to the equivalent DSL filter set so a click
// from /discover always lands on a real results table.
//
// The legacy `/discover/screener` route still exists for the Starter+
// preset experience (linked from elsewhere), so we don't remove it.

interface Preset {
  name: string
  description: string
  borderColor: string
  bgGradient: string
  // /screener?filters=... target — public, unauth-friendly.
  href: string
}

const PRESETS: Preset[] = [
  {
    name: "Buffett Style",
    description: "High return on equity, low leverage",
    borderColor: "border-l-blue-600",
    bgGradient:
      "bg-gradient-to-br from-blue-50/50 to-white dark:from-blue-950/30 dark:to-slate-900",
    // High Quality DSL preset: ROE > 18, D/E < 1, sort by ROE.
    href: "/screener?filters=roe%3E18%2Cde_ratio%3C1&sort=roe",
  },
  {
    name: "Deep Value",
    description: "High margin of safety with low P/E",
    borderColor: "border-l-emerald-600",
    bgGradient:
      "bg-gradient-to-br from-emerald-50/50 to-white dark:from-emerald-950/30 dark:to-slate-900",
    // Deep Value DSL preset: MoS > 30, P/E < 15, sort by MoS.
    href: "/screener?filters=mos%3E30%2Cpe_ratio%3C15&sort=mos",
  },
  {
    name: "Growth Quality",
    description: "Reasonable P/E with high return on capital",
    borderColor: "border-l-violet-600",
    bgGradient:
      "bg-gradient-to-br from-violet-50/50 to-white dark:from-violet-950/30 dark:to-slate-900",
    // Value + Quality DSL preset: P/E < 20, ROCE > 15, sort by MoS.
    href: "/screener?filters=pe_ratio%3C20%2Croce%3E15&sort=mos",
  },
  {
    name: "Custom",
    description: "Build your own filters and criteria",
    borderColor: "border-l-amber-500",
    bgGradient:
      "bg-gradient-to-br from-amber-50/50 to-white dark:from-amber-950/30 dark:to-slate-900",
    href: "/screener",
  },
]

function PresetCard({ preset }: { preset: Preset }) {
  return (
    <Link
      href={preset.href}
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
        Run
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
