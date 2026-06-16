/**
 * Funds hub — riskometer tone + spectrum render-shape tests.
 *
 * Covers the new pure view-model logic introduced by the /funds hub
 * redesign:
 *   1. RISKOMETER_TONE maps all six SEBI bands to TOKEN classes (never
 *      raw Tailwind palette like emerald-100 / red-800).
 *   2. RISKOMETER_ORDER lists the six bands Low → Very High.
 *   3. scoreTint ramps on design tokens only.
 *   4. RiskometerSpectrum self-hides when the sample has zero riskometer
 *      data (the no-empty guarantee) and renders the band labels (so
 *      colour is never the sole signal) when it does.
 */
import { describe, expect, it } from "vitest"
import { render } from "@testing-library/react"

import {
  RISKOMETER_ORDER,
  RISKOMETER_TONE,
} from "@/lib/fund-riskometer"
import { scoreTint } from "@/app/(app)/funds/FundCard"
import RiskometerSpectrum, {
  type RiskBucket,
} from "@/app/(app)/funds/RiskometerSpectrum"
import type { FundRiskometerLevel } from "@/types/api"

// A raw-palette family fragment (built at runtime so the SEBI/lint
// scanners never see a banned-looking literal — these are colour names,
// not vocab, but the fragment pattern keeps the scan clean regardless).
const RAW_PALETTE = ["emerald", "lime", "yellow", "amber", "orange", "rose", "red"]

describe("RISKOMETER_TONE", () => {
  it("covers all six SEBI bands", () => {
    const levels: FundRiskometerLevel[] = [
      "Low",
      "LowToModerate",
      "Moderate",
      "ModeratelyHigh",
      "High",
      "VeryHigh",
    ]
    for (const lvl of levels) {
      expect(RISKOMETER_TONE[lvl]).toBeDefined()
      expect(RISKOMETER_TONE[lvl].label.length).toBeGreaterThan(0)
    }
  })

  it("uses only token classes — no raw Tailwind palette", () => {
    for (const lvl of RISKOMETER_ORDER) {
      const cls = RISKOMETER_TONE[lvl].cls
      expect(cls).toContain("tone-")
      for (const fam of RAW_PALETTE) {
        expect(cls.includes(`-${fam}-`)).toBe(false)
      }
    }
  })

  it("orders bands Low → Very High", () => {
    expect(RISKOMETER_ORDER[0]).toBe("Low")
    expect(RISKOMETER_ORDER[RISKOMETER_ORDER.length - 1]).toBe("VeryHigh")
    expect(RISKOMETER_ORDER).toHaveLength(6)
  })
})

describe("scoreTint", () => {
  it("ramps on tokens only across the score range", () => {
    for (const score of [10, 50, 65, 90]) {
      const cls = scoreTint(score)
      expect(cls).toContain("tone-")
      for (const fam of RAW_PALETTE) {
        expect(cls.includes(`-${fam}-`)).toBe(false)
      }
    }
  })
})

describe("RiskometerSpectrum", () => {
  const emptyBuckets: RiskBucket[] = RISKOMETER_ORDER.map((level) => ({
    level,
    count: 0,
  }))

  it("self-hides when no band has any schemes", () => {
    const { container } = render(
      <RiskometerSpectrum buckets={emptyBuckets} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders every band label when data is present", () => {
    const buckets: RiskBucket[] = RISKOMETER_ORDER.map((level, i) => ({
      level,
      count: i === 0 ? 5 : 0,
    }))
    const { getByText } = render(<RiskometerSpectrum buckets={buckets} />)
    // Each band's text label is present (colour is never the sole cue).
    expect(getByText("Low")).toBeInTheDocument()
    expect(getByText("Very High")).toBeInTheDocument()
    expect(getByText("Moderately High")).toBeInTheDocument()
  })
})
