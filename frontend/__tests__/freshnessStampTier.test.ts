/**
 * Task #197 (feat/as-of-plumbing, 2026-05-24).
 *
 * Pins the color-tier boundaries used by <FreshnessStamp tiered/> when
 * rendering the actual live_quotes.as_of age:
 *   - age <30m → green "Live ~Xm ago"
 *   - 30m–4h  → yellow "Delayed ~Xh ago"
 *   - >4h     → red "Stale — Xh ago"
 *
 * Boundaries matter — drifting the green window down to 5m would
 * silently turn most legitimate quote ages amber and look broken.
 */
import { describe, it, expect } from "vitest"
import { computeTier } from "@/components/common/FreshnessStamp"

describe("FreshnessStamp tier boundaries", () => {
  it("treats <30m as green Live", () => {
    const t1 = computeTier(60 * 1000) // 1m
    expect(t1.prefix).toBe("Live")
    expect(t1.colorCls).toMatch(/emerald/)

    const t29 = computeTier(29 * 60 * 1000) // 29m
    expect(t29.prefix).toBe("Live")
    expect(t29.colorCls).toMatch(/emerald/)
  })

  it("treats 30m as yellow Delayed (lower boundary)", () => {
    const t = computeTier(30 * 60 * 1000) // exactly 30m
    expect(t.prefix).toBe("Delayed")
    expect(t.colorCls).toMatch(/amber/)
  })

  it("treats 3h59m as yellow Delayed (upper boundary)", () => {
    const t = computeTier((3 * 60 + 59) * 60 * 1000)
    expect(t.prefix).toBe("Delayed")
    expect(t.colorCls).toMatch(/amber/)
  })

  it("treats 4h as red Stale (lower boundary)", () => {
    const t = computeTier(4 * 60 * 60 * 1000)
    expect(t.prefix).toBe("Stale —")
    expect(t.colorCls).toMatch(/rose/)
  })

  it("treats 5h (the recompute-time bug we are fixing) as red Stale", () => {
    // Pre-Task #197 the chip read the analysis recompute timestamp
    // which is commonly 5h+ old, so it ALWAYS rendered red even when
    // the underlying live_quote was fresh. Post-fix the input here
    // represents the actual quote age, so 5h is a genuine red and the
    // user-visible string is "Stale — 5h ago".
    const t = computeTier(5 * 60 * 60 * 1000)
    expect(t.prefix).toBe("Stale —")
    expect(t.phrase).toContain("5h")
  })
})
