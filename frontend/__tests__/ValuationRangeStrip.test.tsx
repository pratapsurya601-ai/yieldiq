/**
 * ValuationRangeStrip — pure marker math + render guards
 * (feat/intrinsic-value-thesis-redesign).
 *
 * Pins:
 *   1. `rangeStripLayout` places bear/bull/IV/price proportionally,
 *      including the price-outside-band case, without a DOM.
 *   2. Non-finite / non-positive inputs return null (the strip
 *      self-hides rather than fabricating zeros).
 *   3. The component renders the band, both markers, the bear/bull
 *      labels, and the "outside bear–bull range" chip when the price
 *      sits outside the band.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"

import ValuationRangeStrip, {
  rangeStripLayout,
} from "@/components/analysis/intrinsic/ValuationRangeStrip"

function stubMatchMedia() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

beforeEach(() => {
  stubMatchMedia()
})

describe("rangeStripLayout — pure marker math", () => {
  it("places every marker inside the strip for an in-band price", () => {
    const l = rangeStripLayout({
      bear: 80,
      bull: 120,
      intrinsicValue: 100,
      price: 95,
    })
    expect(l).not.toBeNull()
    expect(l!.priceOutside).toBeNull()
    const bandRight = l!.bandLeftPct + l!.bandWidthPct
    expect(l!.bandLeftPct).toBeLessThan(l!.ivPct)
    expect(l!.ivPct).toBeLessThan(bandRight)
    expect(l!.pricePct).toBeGreaterThan(l!.bandLeftPct)
    expect(l!.pricePct).toBeLessThan(bandRight)
    // 6% domain padding keeps the band off the strip edges.
    expect(l!.bandLeftPct).toBeGreaterThanOrEqual(2)
    expect(bandRight).toBeLessThanOrEqual(98)
    // price < IV → price marker sits left of the IV marker.
    expect(l!.pricePct).toBeLessThan(l!.ivPct)
  })

  it("flags priceOutside='under' and keeps the marker in view when price < bear", () => {
    const l = rangeStripLayout({
      bear: 100,
      bull: 150,
      intrinsicValue: 120,
      price: 60,
    })
    expect(l).not.toBeNull()
    expect(l!.priceOutside).toBe("under")
    expect(l!.pricePct).toBeLessThan(l!.bandLeftPct)
    expect(l!.pricePct).toBeGreaterThanOrEqual(2)
  })

  it("flags priceOutside='over' when price > bull", () => {
    const l = rangeStripLayout({
      bear: 100,
      bull: 150,
      intrinsicValue: 120,
      price: 180,
    })
    expect(l).not.toBeNull()
    expect(l!.priceOutside).toBe("over")
    expect(l!.pricePct).toBeGreaterThan(l!.bandLeftPct + l!.bandWidthPct)
    expect(l!.pricePct).toBeLessThanOrEqual(98)
  })

  it("normalizes swapped bear/bull inputs to the same layout", () => {
    const swapped = rangeStripLayout({
      bear: 120,
      bull: 80,
      intrinsicValue: 100,
      price: 95,
    })
    const ordered = rangeStripLayout({
      bear: 80,
      bull: 120,
      intrinsicValue: 100,
      price: 95,
    })
    expect(swapped).toEqual(ordered)
  })

  it("clamps an extreme outlier price to the edge pad instead of overflowing", () => {
    const l = rangeStripLayout({
      bear: 90,
      bull: 110,
      intrinsicValue: 100,
      price: 1000,
    })
    expect(l).not.toBeNull()
    expect(l!.priceOutside).toBe("over")
    expect(l!.pricePct).toBeLessThanOrEqual(98)
  })

  it("returns null on non-finite or non-positive inputs", () => {
    const base = { bear: 80, bull: 120, intrinsicValue: 100, price: 95 }
    expect(rangeStripLayout({ ...base, bear: 0 })).toBeNull()
    expect(rangeStripLayout({ ...base, bull: -5 })).toBeNull()
    expect(rangeStripLayout({ ...base, intrinsicValue: NaN })).toBeNull()
    expect(rangeStripLayout({ ...base, price: Infinity })).toBeNull()
  })
})

const BASE_PROPS = {
  ticker: "TEST.NS",
  currency: "INR",
}

describe("ValuationRangeStrip — render", () => {
  it("renders the band, IV + price markers, and bear/bull end labels", () => {
    render(
      <ValuationRangeStrip
        {...BASE_PROPS}
        bear={800}
        bull={1200}
        intrinsicValue={1000}
        currentPrice={950}
      />,
    )
    expect(screen.getByTestId("iv-range-strip")).toBeInTheDocument()
    expect(screen.getByTestId("iv-range-band")).toBeInTheDocument()
    expect(screen.getByTestId("iv-range-marker-iv").textContent).toContain(
      "1,000",
    )
    expect(screen.getByTestId("iv-range-marker-price").textContent).toContain(
      "950",
    )
    expect(screen.getByTestId("iv-range-label-bear").textContent).toContain(
      "800",
    )
    expect(screen.getByTestId("iv-range-label-bull").textContent).toContain(
      "1,200",
    )
    // In-band price → no outside chip.
    expect(screen.queryByTestId("iv-range-price-outside")).toBeNull()
  })

  it("renders the outside chip when the price sits under the bear bound", () => {
    render(
      <ValuationRangeStrip
        {...BASE_PROPS}
        bear={800}
        bull={1200}
        intrinsicValue={1000}
        currentPrice={700}
      />,
    )
    expect(
      screen.getByTestId("iv-range-price-outside").textContent,
    ).toContain("outside bear–bull range")
  })

  it("self-hides entirely when the scenario bounds are unavailable", () => {
    const { container } = render(
      <ValuationRangeStrip
        {...BASE_PROPS}
        bear={null}
        bull={null}
        intrinsicValue={1000}
        currentPrice={950}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
