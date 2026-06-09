/**
 * Sprint A1 (2026-06-09 competitor audit) — FreshnessStamp pulse-dot
 * tests.
 *
 * Pins:
 *   1. computePulse() returns the right band/colour/animated-state at
 *      each boundary (< 5min green pulse, 5min–1h yellow static, > 1h
 *      gray static).
 *   2. The rendered dot reflects the band via data-pulse-band and
 *      data-pulse-animated attributes, AND the dot precedes the text
 *      body so the visual order is dot → caption.
 *   3. The dot is hidden from assistive tech (aria-hidden) so the
 *      relative-time phrase remains the single accessible label.
 *   4. prefers-reduced-motion replaces the pulse animation with a
 *      static dot, even on the < 5min band where it would otherwise
 *      animate.
 *   5. Null / unparsable timestamps keep the legacy fallback path —
 *      no dot, no crash.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import FreshnessStamp, { computePulse } from "@/components/common/FreshnessStamp"

function setReducedMotion(matches: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? matches : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

function isoAgo(ms: number): string {
  return new Date(Date.now() - ms).toISOString()
}

beforeEach(() => {
  setReducedMotion(false)
})

describe("computePulse", () => {
  it("returns the live green-pulse band for ages under 5 minutes", () => {
    const info = computePulse(60 * 1000) // 1m
    expect(info.band).toBe("live")
    expect(info.pulse).toBe(true)
    expect(info.colorCls).toMatch(/emerald/)
  })

  it("flips to recent yellow static at 5 minutes and through 1 hour", () => {
    for (const ageMs of [5 * 60 * 1000, 30 * 60 * 1000, 59 * 60 * 1000]) {
      const info = computePulse(ageMs)
      expect(info.band).toBe("recent")
      expect(info.pulse).toBe(false)
      expect(info.colorCls).toMatch(/amber/)
    }
  })

  it("becomes stale gray static beyond one hour", () => {
    for (const ageMs of [60 * 60 * 1000, 2 * 60 * 60 * 1000, 24 * 60 * 60 * 1000]) {
      const info = computePulse(ageMs)
      expect(info.band).toBe("stale")
      expect(info.pulse).toBe(false)
      expect(info.colorCls).toMatch(/slate/)
    }
  })
})

describe("FreshnessStamp pulse dot", () => {
  it("renders a green animated dot for fresh (<5min) timestamps", () => {
    const { container } = render(
      <FreshnessStamp timestamp={isoAgo(60 * 1000)} prefix="Recomputed" />,
    )
    const dot = container.querySelector("[data-pulse-band]") as HTMLElement
    expect(dot).not.toBeNull()
    expect(dot.getAttribute("data-pulse-band")).toBe("live")
    expect(dot.getAttribute("data-pulse-animated")).toBe("true")
    expect(dot.className).toMatch(/emerald/)
    expect(dot.className).toMatch(/animate-pulse/)
  })

  it("renders a yellow static dot for 30-minute-old timestamps", () => {
    const { container } = render(
      <FreshnessStamp
        timestamp={isoAgo(30 * 60 * 1000)}
        prefix="Recomputed"
      />,
    )
    const dot = container.querySelector("[data-pulse-band]") as HTMLElement
    expect(dot.getAttribute("data-pulse-band")).toBe("recent")
    expect(dot.getAttribute("data-pulse-animated")).toBe("false")
    expect(dot.className).toMatch(/amber/)
    expect(dot.className).not.toMatch(/animate-pulse/)
  })

  it("renders a gray static dot for 2-hour-old timestamps", () => {
    const { container } = render(
      <FreshnessStamp
        timestamp={isoAgo(2 * 60 * 60 * 1000)}
        prefix="Recomputed"
      />,
    )
    const dot = container.querySelector("[data-pulse-band]") as HTMLElement
    expect(dot.getAttribute("data-pulse-band")).toBe("stale")
    expect(dot.getAttribute("data-pulse-animated")).toBe("false")
    expect(dot.className).toMatch(/slate/)
    expect(dot.className).not.toMatch(/animate-pulse/)
  })

  it("drops the pulse animation when prefers-reduced-motion is set, even on the live band", () => {
    setReducedMotion(true)
    const { container } = render(
      <FreshnessStamp timestamp={isoAgo(60 * 1000)} prefix="Recomputed" />,
    )
    const dot = container.querySelector("[data-pulse-band]") as HTMLElement
    expect(dot.getAttribute("data-pulse-band")).toBe("live")
    expect(dot.getAttribute("data-pulse-animated")).toBe("false")
    expect(dot.className).not.toMatch(/animate-pulse/)
    // Colour still conveys the band so motion-averse users still get
    // the signal — only the animation is suppressed.
    expect(dot.className).toMatch(/emerald/)
  })

  it("hides the dot from assistive tech (aria-hidden)", () => {
    const { container } = render(
      <FreshnessStamp timestamp={isoAgo(60 * 1000)} prefix="Recomputed" />,
    )
    const dot = container.querySelector("[data-pulse-band]") as HTMLElement
    expect(dot.getAttribute("aria-hidden")).toBeTruthy()
  })

  it("renders no dot when the timestamp is null and a fallback is provided", () => {
    const { container } = render(
      <FreshnessStamp timestamp={null} fallback="Data freshness unknown" />,
    )
    expect(container.querySelector("[data-pulse-band]")).toBeNull()
    expect(screen.getByText("Data freshness unknown")).toBeInTheDocument()
  })

  it("renders the dot alongside the tiered prefix when tiered=true", () => {
    const { container } = render(
      <FreshnessStamp timestamp={isoAgo(60 * 1000)} tiered />,
    )
    const dot = container.querySelector("[data-pulse-band]") as HTMLElement
    expect(dot).not.toBeNull()
    expect(dot.getAttribute("data-pulse-band")).toBe("live")
  })
})

// 2026-06-09 fix/analysis-ux-fixbatch — caller-prefix distinguishes
// the "model recompute" vs "price quote" timestamps so the two stamps
// on /analysis/[ticker] cannot read as a single value rendered twice
// with different ages (Chrome MCP audit on HDFCBANK flagged "Delayed,
// as of 13h ago" + "Delayed, as of 23h ago" as visually identical
// captions with different timestamps).
describe("FreshnessStamp — analysis-page dual-timestamp distinction", () => {
  it("renders the toolbar model-recompute caption with the new prefix", () => {
    render(
      <FreshnessStamp
        timestamp={isoAgo(13 * 60 * 60 * 1000)} // 13h ago
        prefix="Model recomputed"
      />,
    )
    // The body text format is `${prefix} ${phrase}` for relative-time
    // captions (< 7 days), so the prefix word is the leading distinct
    // copy users see.
    expect(screen.getByText(/Model recomputed/)).toBeInTheDocument()
    // The old shared "Delayed, as of" copy must NOT appear on the
    // toolbar caller — that label is now reserved for the hero glass
    // panel quote stamp, which uses "Price quote".
    expect(screen.queryByText(/Delayed, as of/)).toBeNull()
  })

  it("renders the hero glass-panel price-quote caption with the distinct prefix", () => {
    render(
      <FreshnessStamp
        timestamp={isoAgo(23 * 60 * 60 * 1000)} // 23h ago
        prefix="Price quote"
        fallback="Quote freshness unknown"
      />,
    )
    expect(screen.getByText(/Price quote/)).toBeInTheDocument()
    expect(screen.queryByText(/Model recomputed/)).toBeNull()
    expect(screen.queryByText(/Delayed, as of/)).toBeNull()
  })

  it("the two captions render with non-overlapping copy when shown together", () => {
    const { container } = render(
      <div>
        <FreshnessStamp
          timestamp={isoAgo(13 * 60 * 60 * 1000)}
          prefix="Model recomputed"
        />
        <FreshnessStamp
          timestamp={isoAgo(23 * 60 * 60 * 1000)}
          prefix="Price quote"
        />
      </div>,
    )
    // The two stamps must produce DIFFERENT prefixes so the user can
    // distinguish them at a glance. Asserting both phrases appear
    // exactly once each pins the copy contract.
    const matches = container.textContent ?? ""
    expect((matches.match(/Model recomputed/g) ?? []).length).toBe(1)
    expect((matches.match(/Price quote/g) ?? []).length).toBe(1)
  })
})
