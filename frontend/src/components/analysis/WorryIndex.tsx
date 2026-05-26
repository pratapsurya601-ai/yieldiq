"use client"

// WorryIndex — circular gauge + tier copy + expandable contributors.
// Phase-3 (2026-05-25) — Design Manifesto rule 2 ("every number has
// context") expressed as a single 0-100 emotional risk score.
//
// Data shape: AnalysisResponse.worry_index
//   {
//     score: 0-100,
//     tier: "sleep_well" | "normal" | "watch_closely" | "read_bears" | "significant_concerns",
//     headline: string,
//     contributors: [{component, label, weight, score, detail}, ...]
//   }
//
// Renders nothing when the field is absent (pre-PR cached payloads).

import { useState } from "react"
import { CountUp, FadeStagger } from "@/components/anim"
import { cn } from "@/lib/utils"

export interface WorryContributor {
  component: string
  label: string
  weight: number
  score: number
  detail?: string
}

export interface WorryIndexData {
  score: number
  tier:
    | "sleep_well"
    | "normal"
    | "watch_closely"
    | "read_bears"
    | "significant_concerns"
  headline: string
  contributors: WorryContributor[]
}

interface Props {
  worry: WorryIndexData | null | undefined
}

// Verdict-style cascade so the gauge reads at a glance even if the
// user only ever looks at the colour.
const TIER_STYLES: Record<
  WorryIndexData["tier"],
  { ring: string; track: string; text: string; chip: string }
> = {
  sleep_well: {
    ring:  "stroke-emerald-600",
    track: "stroke-emerald-100",
    text:  "text-emerald-700",
    chip:  "bg-emerald-50 text-emerald-700 border-emerald-200",
  },
  normal: {
    ring:  "stroke-lime-600",
    track: "stroke-lime-100",
    text:  "text-lime-700",
    chip:  "bg-lime-50 text-lime-700 border-lime-200",
  },
  watch_closely: {
    ring:  "stroke-amber-500",
    track: "stroke-amber-100",
    text:  "text-amber-700",
    chip:  "bg-amber-50 text-amber-700 border-amber-200",
  },
  read_bears: {
    ring:  "stroke-orange-600",
    track: "stroke-orange-100",
    text:  "text-orange-700",
    chip:  "bg-orange-50 text-orange-700 border-orange-200",
  },
  significant_concerns: {
    ring:  "stroke-rose-700",
    track: "stroke-rose-100",
    text:  "text-rose-800",
    chip:  "bg-rose-50 text-rose-800 border-rose-200",
  },
}

const SIZE = 160          // px — outer SVG dimension
const STROKE = 14         // px — ring thickness
const RADIUS = (SIZE - STROKE) / 2
const CIRC = 2 * Math.PI * RADIUS

export default function WorryIndex({ worry }: Props) {
  const [open, setOpen] = useState(false)

  if (!worry || typeof worry.score !== "number") return null

  const score = Math.max(0, Math.min(100, Math.round(worry.score)))
  const style = TIER_STYLES[worry.tier] ?? TIER_STYLES.watch_closely
  // Stroke-dashoffset to render `score`% of the circle filled.
  const dashOffset = CIRC * (1 - score / 100)

  return (
    <section
      aria-labelledby="worry-index-heading"
      className="bg-surface rounded-2xl border border-border p-5 sm:p-6"
    >
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h2
            id="worry-index-heading"
            className="text-[11px] font-semibold text-caption uppercase tracking-wide"
          >
            The Worry Index
          </h2>
          <p className="text-xs text-caption mt-0.5">
            One number that says how loud the risk signals are right now.
          </p>
        </div>
        <span
          className={cn(
            "text-[10px] font-semibold uppercase tracking-wide rounded-full px-2 py-0.5 border",
            style.chip,
          )}
        >
          {worry.tier.replace(/_/g, " ")}
        </span>
      </div>

      <div className="flex flex-col sm:flex-row items-center gap-5">
        {/* Circular gauge */}
        <div className="relative shrink-0" style={{ width: SIZE, height: SIZE }}>
          <svg
            width={SIZE}
            height={SIZE}
            viewBox={`0 0 ${SIZE} ${SIZE}`}
            className="-rotate-90"
            aria-hidden
          >
            <circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              strokeWidth={STROKE}
              className={style.track}
              strokeLinecap="round"
            />
            <circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              strokeWidth={STROKE}
              strokeDasharray={CIRC}
              strokeDashoffset={dashOffset}
              className={cn(style.ring, "transition-[stroke-dashoffset] duration-[1200ms] ease-out")}
              strokeLinecap="round"
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <CountUp
              to={score}
              duration={1.2}
              className={cn("text-4xl font-bold tabular-nums", style.text)}
            />
            <span className="text-[10px] text-caption uppercase tracking-wide mt-0.5">
              out of 100
            </span>
          </div>
        </div>

        {/* Tier headline */}
        <div className="flex-1 text-center sm:text-left">
          <p className={cn("text-xl sm:text-2xl font-semibold leading-snug", style.text)}>
            {worry.headline}
          </p>
          <p className="text-xs text-caption mt-2 max-w-prose mx-auto sm:mx-0">
            Composite of solvency, earnings quality, valuation stretch, market
            volatility and governance signals. Lower is calmer.
          </p>
        </div>
      </div>

      {/* Expandable contributors */}
      {worry.contributors && worry.contributors.length > 0 && (
        <div className="mt-5 border-t border-border pt-4">
          <button
            type="button"
            onClick={() => setOpen(v => !v)}
            aria-expanded={open}
            className="text-xs font-medium text-ink hover:text-ink/80 flex items-center gap-1.5"
          >
            <span>{open ? "Hide" : "What drives this score?"}</span>
            <span aria-hidden className={cn("transition-transform", open && "rotate-90")}>›</span>
          </button>

          {open && (
            <FadeStagger as="div" className="mt-3 space-y-2" staggerMs={70}>
              {worry.contributors.map((c) => (
                <div
                  key={c.component}
                  className="grid grid-cols-[110px_1fr_44px] sm:grid-cols-[140px_1fr_48px] items-center gap-3 text-xs"
                >
                  <span className="text-caption">
                    {c.label}
                    <span className="ml-1 text-[10px] text-caption/70">
                      ({c.weight}%)
                    </span>
                  </span>
                  <div className="h-1.5 rounded-full bg-bg overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full",
                        c.score < 20 ? "bg-emerald-600" :
                        c.score < 40 ? "bg-lime-600" :
                        c.score < 60 ? "bg-amber-500" :
                        c.score < 80 ? "bg-orange-600" : "bg-rose-700",
                      )}
                      style={{ width: `${Math.max(0, Math.min(100, c.score))}%` }}
                      title={c.detail || undefined}
                    />
                  </div>
                  <span className="text-right tabular-nums font-medium text-ink">
                    {c.score}
                  </span>
                  {c.detail && (
                    <span className="col-span-3 text-[11px] text-caption leading-snug -mt-1">
                      {c.detail}
                    </span>
                  )}
                </div>
              ))}
            </FadeStagger>
          )}
        </div>
      )}
    </section>
  )
}
