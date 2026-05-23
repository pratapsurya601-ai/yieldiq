/**
 * Day-127 (2026-05-23) — industry-percentile caption helpers.
 *
 * Pins the SEBI-safe bucket caption + the new peer-count caption
 * (vs. {N} peers in {industry}) used under the YieldIQ Score on
 * AnalysisHero. The peer count makes the "Top quartile" framing
 * meaningful — small cohorts (3 peers) shouldn't read the same
 * as large ones (40+ peers).
 */

import { describe, it, expect } from "vitest"
import { peerCountCaption, percentileCaption } from "@/lib/industryPercentile"

describe("percentileCaption", () => {
  it("returns null when percentile or industry missing", () => {
    expect(percentileCaption(null, "Banks")).toBeNull()
    expect(percentileCaption(undefined, "Banks")).toBeNull()
    expect(percentileCaption(80, null)).toBeNull()
    expect(percentileCaption(80, "")).toBeNull()
    expect(percentileCaption(80, "   ")).toBeNull()
  })

  it("buckets at quartile boundaries", () => {
    expect(percentileCaption(99, "IT Services")).toBe("Top quartile in IT Services")
    expect(percentileCaption(75, "IT Services")).toBe("Top quartile in IT Services")
    expect(percentileCaption(74, "IT Services")).toBe("Above IT Services median")
    expect(percentileCaption(50, "IT Services")).toBe("Above IT Services median")
    expect(percentileCaption(49, "IT Services")).toBe("Below IT Services median")
    expect(percentileCaption(25, "IT Services")).toBe("Below IT Services median")
    expect(percentileCaption(10, "IT Services")).toBe("Bottom quartile in IT Services")
  })
})

describe("peerCountCaption", () => {
  it("renders the 'vs. {N} peers in {industry}' line for normal cohorts", () => {
    expect(peerCountCaption(42, "Banks - Private Sector")).toBe(
      "vs. 42 peers in Banks - Private Sector",
    )
  })

  it("singularises 'peer' for cohort size 1", () => {
    expect(peerCountCaption(1, "IT Services")).toBe("vs. 1 peer in IT Services")
  })

  it("returns null when cohort_size is missing, zero, or non-finite", () => {
    expect(peerCountCaption(null, "Banks")).toBeNull()
    expect(peerCountCaption(undefined, "Banks")).toBeNull()
    expect(peerCountCaption(0, "Banks")).toBeNull()
    expect(peerCountCaption(Number.NaN, "Banks")).toBeNull()
    expect(peerCountCaption(Number.POSITIVE_INFINITY, "Banks")).toBeNull()
  })

  it("returns null when industry is missing or blank", () => {
    expect(peerCountCaption(20, null)).toBeNull()
    expect(peerCountCaption(20, undefined)).toBeNull()
    expect(peerCountCaption(20, "")).toBeNull()
    expect(peerCountCaption(20, "   ")).toBeNull()
  })

  it("trims whitespace around the industry label", () => {
    expect(peerCountCaption(8, "  Pharma  ")).toBe("vs. 8 peers in Pharma")
  })
})
