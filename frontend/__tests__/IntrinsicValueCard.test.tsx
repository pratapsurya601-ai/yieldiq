/**
 * IntrinsicValueCard — badge polarity + bar visibility guards
 * (feat/alphaspread-style-opening).
 *
 *   1. price < IV → "Discount X%" badge (data-direction="discount")
 *   2. price > IV → "Premium X%" badge (data-direction="premium")
 *   3. data-limited → no badge, no bars, em-dash figure
 *
 * framer-motion + NumberFlip read matchMedia for reduced-motion; jsdom
 * needs the standard stub.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"

import IntrinsicValueCard from "@/components/analysis/IntrinsicValueCard"

function stubMatchMedia(reduced: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? reduced : false,
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
  stubMatchMedia(false)
})

const BASE = {
  ticker: "TEST.NS",
  displayTicker: "TEST",
  currency: "INR",
}

describe("IntrinsicValueCard — Discount/Premium badge", () => {
  it("flips to DISCOUNT when the price sits below the IV", () => {
    render(
      <IntrinsicValueCard {...BASE} intrinsicValue={1200} currentPrice={1000} />,
    )
    const badge = screen.getByTestId("iv-card-badge")
    expect(badge.getAttribute("data-direction")).toBe("discount")
    // pct = (1200 − 1000) / 1000 = 20.0%
    expect(badge.textContent).toMatch(/Discount 20\.0%/i)
  })

  it("flips to PREMIUM when the price sits above the IV", () => {
    render(
      <IntrinsicValueCard {...BASE} intrinsicValue={900} currentPrice={1000} />,
    )
    const badge = screen.getByTestId("iv-card-badge")
    expect(badge.getAttribute("data-direction")).toBe("premium")
    // pct = |900 − 1000| / 1000 = 10.0%
    expect(badge.textContent).toMatch(/Premium 10\.0%/i)
  })
})

describe("IntrinsicValueCard — IV vs Price bars", () => {
  it("renders both labeled bars when IV and price are usable", () => {
    render(
      <IntrinsicValueCard {...BASE} intrinsicValue={1200} currentPrice={1000} />,
    )
    expect(screen.getByTestId("iv-card-bars")).toBeInTheDocument()
    expect(screen.getByTestId("iv-bar-iv").textContent).toMatch(
      /Intrinsic Value/,
    )
    expect(screen.getByTestId("iv-bar-price").textContent).toMatch(/Price/)
  })
})

describe("IntrinsicValueCard — data-limited", () => {
  it("suppresses badge + bars and renders an em dash", () => {
    render(
      <IntrinsicValueCard
        {...BASE}
        intrinsicValue={null}
        currentPrice={1000}
        dataLimited
      />,
    )
    expect(screen.queryByTestId("iv-card-badge")).toBeNull()
    expect(screen.queryByTestId("iv-card-bars")).toBeNull()
    expect(screen.getByTestId("iv-card").textContent).toContain("—")
  })

  it("suppresses badge + bars even when a stale IV number is passed alongside dataLimited", () => {
    render(
      <IntrinsicValueCard
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dataLimited
      />,
    )
    expect(screen.queryByTestId("iv-card-badge")).toBeNull()
    expect(screen.queryByTestId("iv-card-bars")).toBeNull()
  })
})
