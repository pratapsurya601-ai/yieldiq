"use client"

// WorryIndex — circular gauge + tier copy + always-visible sub-component
// bars (Visual Richness #4, 2026-05-27).
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
// When the API doesn't include `contributors` (older cached payloads),
// the bars render with neutral 50/100 placeholders + a caption noting
// the breakdown is pending — never fake real numbers.

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
    text:  "text-tone-good-fg",
    chip:  "bg-tone-good-bg text-tone-good-fg border-tone-good-bd",
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
    text:  "text-tone-warn-fg",
    chip:  "bg-tone-warn-bg text-tone-warn-fg border-tone-warn-bd",
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

// Per-pillar state label — translates a 0-100 WORRY score into a
// word that reads in the correct direction without the user having
// to recall "high = bad here, opposite of usual".
//
// Bands chosen to mirror the OVERALL worry-tier cascade (sleep_well /
// normal / watch_closely / read_bears / significant_concerns) but
// collapsed into 4 buckets — per-pillar copy doesn't need 5-way
// granularity since the gauge headline already carries the nuance.
//
//   0-19    "Calm"      — pillar is dormant, not raising flags
//   20-39   "Normal"    — pillar shows ordinary noise
//   40-69   "Elevated"  — pillar is louder than normal
//   70-100  "Loud"      — pillar is shouting
//
// SEBI-safe by construction: "Calm" / "Normal" / "Elevated" / "Loud"
// are factual state descriptions, none on the banned-vocab list.
export type WorryState = "Calm" | "Normal" | "Elevated" | "Loud"

export function worryStateLabel(score: number): WorryState {
  const s = Math.max(0, Math.min(100, Math.round(score)))
  if (s < 20) return "Calm"
  if (s < 40) return "Normal"
  if (s < 70) return "Elevated"
  return "Loud"
}

// Tailwind classes paired with each state so the caption text mirrors
// the bar's gradient position — Calm leans green, Loud leans rose.
const STATE_TEXT_CLASS: Record<WorryState, string> = {
  Calm:     "text-emerald-700",
  Normal:   "text-lime-700",
  Elevated: "text-amber-700",
  Loud:     "text-rose-800",
}

// Fallback skeleton when the API payload predates the contributors
// field. We render 5 placeholder bars at 50/100 so the layout shape is
// preserved, and surface a caption so nobody mistakes them for real
// scores.
const PLACEHOLDER_CONTRIBUTORS: WorryContributor[] = [
  { component: "solvency",         label: "Solvency",          weight: 0, score: 50 },
  { component: "earnings_quality", label: "Earnings quality",  weight: 0, score: 50 },
  { component: "valuation",        label: "Valuation stretch", weight: 0, score: 50 },
  { component: "volatility",       label: "Market volatility", weight: 0, score: 50 },
  { component: "governance",       label: "Governance",        weight: 0, score: 50 },
]

export default function WorryIndex({ worry }: Props) {
  if (!worry || typeof worry.score !== "number") return null

  const score = Math.max(0, Math.min(100, Math.round(worry.score)))
  const style = TIER_STYLES[worry.tier] ?? TIER_STYLES.watch_closely
  // Stroke-dashoffset to render `score`% of the circle filled.
  const dashOffset = CIRC * (1 - score / 100)

  return (
    <section
      aria-labelledby="worry-index-heading"
      className="bg-surface rounded-2xl border border-border p-4 sm:p-6"
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

      <div className="flex flex-col sm:flex-row items-center gap-4">
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

      {/* Sub-component breakdown — always visible as horizontal bars
          so the "why" sits next to the headline number. The dial stays
          the centerpiece; bars act as decomposition.

          When the API payload predates the contributors field, we fall
          back to neutral 50/100 placeholder bars + a caption — never
          fake real numbers (project discipline). */}
      {(() => {
        const hasRealData =
          Array.isArray(worry.contributors) && worry.contributors.length > 0
        const rows = hasRealData ? worry.contributors : PLACEHOLDER_CONTRIBUTORS

        return (
          <div className="mt-4 border-t border-border pt-4">
            <div className="flex items-baseline justify-between mb-3">
              <h3 className="text-[11px] font-semibold text-caption uppercase tracking-wide">
                What drives this score
              </h3>
              {!hasRealData && (
                <span className="text-[10px] text-caption/80 italic">
                  Component breakdown coming soon
                </span>
              )}
            </div>
            <FadeStagger as="div" className="space-y-2.5" staggerMs={60}>
              {rows.map((c) => {
                const clamped = Math.max(0, Math.min(100, c.score))
                // Bug 5 (P2, 2026-06-09): per-pillar labels were
                // semantically inverted — "Solvency: 0 out of 100" on
                // a healthy bank read as "zero solvency" not "zero
                // worry on solvency". Pivot to state-language labels
                // (Calm / Normal / Elevated / Loud) that read in the
                // correct direction without scale-recall. Raw 0-100
                // score moves to a small secondary caption for power
                // users who want the underlying number.
                const state = hasRealData ? worryStateLabel(clamped) : null
                const stateClass = state ? STATE_TEXT_CLASS[state] : ""
                const ariaLabel = hasRealData && state
                  ? c.detail
                    ? `${c.label}: ${state} — ${c.detail}`
                    : `${c.label}: ${state} (${clamped} of 100 worry signal)`
                  : `${c.label}: breakdown pending`
                return (
                  <div
                    key={c.component}
                    className="grid grid-cols-[110px_1fr_56px] sm:grid-cols-[150px_1fr_72px] items-center gap-3 text-xs"
                  >
                    <span className="text-caption truncate" title={c.label}>
                      {c.label}
                      {hasRealData && c.weight > 0 && (
                        <span className="ml-1 text-[10px] text-caption/70">
                          ({c.weight}%)
                        </span>
                      )}
                    </span>
                    {/* Track uses a static green→amber→red gradient so
                        the colour position itself tells you whether the
                        score is calm or loud. The filled portion is
                        opaque; the unfilled tail is dimmed via overlay. */}
                    <div
                      className="relative h-2 rounded-full overflow-hidden bg-gradient-to-r from-emerald-500 via-amber-400 to-rose-600"
                      role="img"
                      aria-label={ariaLabel}
                      title={c.detail || undefined}
                    >
                      <div
                        aria-hidden
                        className={cn(
                          "absolute inset-y-0 right-0 bg-surface/85 transition-[width] duration-[900ms] ease-out",
                          !hasRealData && "bg-surface/70",
                        )}
                        style={{ width: `${100 - clamped}%` }}
                      />
                      <div
                        aria-hidden
                        className="absolute top-0 bottom-0 w-px bg-ink/70"
                        style={{ left: `calc(${clamped}% - 0.5px)` }}
                      />
                    </div>
                    <span
                      className={cn(
                        "text-right font-semibold leading-tight flex flex-col items-end",
                        hasRealData ? stateClass : "text-caption/70",
                      )}
                    >
                      <span data-testid={`worry-state-${c.component}`}>
                        {hasRealData && state ? state : "—"}
                      </span>
                      {hasRealData && (
                        <span className="text-[10px] tabular-nums font-normal text-caption/70">
                          {c.score}/100
                        </span>
                      )}
                    </span>
                    {hasRealData && c.detail && (
                      <span className="col-span-3 text-[11px] text-caption leading-snug -mt-1">
                        {c.detail}
                      </span>
                    )}
                  </div>
                )
              })}
            </FadeStagger>
            <p className="mt-3 text-[10px] text-caption/70">
              State labels: Calm (0-19) · Normal (20-39) · Elevated
              (40-69) · Loud (70-100). Lower means quieter risk signal.
            </p>
          </div>
        )
      })()}
    </section>
  )
}
