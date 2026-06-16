"use client"
/**
 * RiskometerSpectrum — a descriptive six-band riskometer strip.
 *
 * Renders the SEBI Riskometer bands (Low → Very High) as a tone
 * spectrum with the count of sampled schemes in each band. This is
 * INFORMATIONAL, not a filter: the funds list endpoint has no `risk`
 * query param, so the bands are not links — they orient the user to
 * what the riskometer scale means and how the on-page sample spreads
 * across it.
 *
 * Self-hides when the sample carries no riskometer labels at all
 * (sum of counts === 0). Riskometer level is an operator-/AMC-curated
 * field that is sparse across the long tail, so hiding-on-empty keeps
 * the hub from ever showing a blank spectrum (no-empty guarantee, §8).
 *
 * SEBI: bands are AMC-published labels; tone colours are decorative.
 * Each segment shows its text label so colour is never the sole signal.
 */
import type { FundRiskometerLevel } from "@/types/api"
import { RISKOMETER_ORDER, RISKOMETER_TONE } from "@/lib/fund-riskometer"
import { Reveal } from "@/components/motion"

export interface RiskBucket {
  level: FundRiskometerLevel
  count: number
}

export default function RiskometerSpectrum({
  buckets,
}: {
  buckets: RiskBucket[]
}) {
  const byLevel = new Map(buckets.map((b) => [b.level, b.count]))
  const total = buckets.reduce((s, b) => s + b.count, 0)

  // Self-hide: no riskometer data in the sample → render nothing.
  if (total === 0) return null

  return (
    <Reveal direction="up" as="section" className="space-y-3">
      <div className="space-y-1">
        <p className="text-[11px] font-semibold uppercase leading-4 tracking-[0.06em] text-caption">
          Risk
        </p>
        <h2 className="text-[22px] font-semibold leading-7 tracking-tight text-ink">
          Browse by riskometer
        </h2>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {RISKOMETER_ORDER.map((level) => {
          const tone = RISKOMETER_TONE[level]
          const count = byLevel.get(level) ?? 0
          return (
            <div
              key={level}
              className={`flex flex-col gap-1 rounded-lg px-3 py-2.5 ${tone.cls} ${
                count === 0 ? "opacity-45" : ""
              }`}
            >
              <span className="text-[11px] font-semibold leading-tight">
                {tone.label}
              </span>
              <span className="text-sm font-semibold num">{count}</span>
            </div>
          )
        })}
      </div>

      <p className="text-[12px] leading-4 text-caption">
        Riskometer bands are disclosed by each AMC.
      </p>
    </Reveal>
  )
}
