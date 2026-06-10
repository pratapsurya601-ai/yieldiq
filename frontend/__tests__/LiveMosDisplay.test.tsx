/**
 * LiveMosDisplay tests — task #131 live FV recompute chip.
 *
 * Covers:
 *   - Renders the cached fallback price → MoS immediately (no flash of 0).
 *   - Polls /api/v1/public/quote/{ticker}, updates the displayed MoS
 *     when the live endpoint returns a new price, and flips the data-
 *     is-live attribute.
 *   - Returns nothing when fair_value is not finite (no half-rendered chip).
 *   - Clamps insane MoS values so a unit-bug ticker can't show +999%.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"

import LiveMosDisplay from "@/components/analysis/LiveMosDisplay"

const _originalFetch = global.fetch

beforeEach(() => {
  // Default mock: a successful quote response.
  global.fetch = vi.fn(async () => {
    return new Response(
      JSON.stringify({
        ticker: "RELIANCE",
        price: 1200,
        as_of: "2026-06-10T12:00:00Z",
        source: "live_quotes",
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    )
  }) as unknown as typeof fetch
})

afterEach(() => {
  global.fetch = _originalFetch
  vi.useRealTimers()
})

describe("LiveMosDisplay", () => {
  it("renders the cached MoS immediately using the fallback price", () => {
    // fv=1500, fallback=1000 → cached MoS = +33.3%
    render(
      <LiveMosDisplay
        ticker="RELIANCE"
        fairValue={1500}
        fallbackPrice={1000}
      />,
    )
    const chip = screen.getByTestId("live-mos-display")
    expect(chip).toBeInTheDocument()
    // Initial render uses the fallback (no live yet).
    expect(chip.getAttribute("data-is-live")).toBe("0")
    expect(screen.getByTestId("live-mos-value").textContent).toMatch(
      /\+33\.3%/,
    )
  })

  it("updates the MoS when the live endpoint returns a fresh price", async () => {
    // fv=1500, live=1200 → live MoS = +20.0%
    render(
      <LiveMosDisplay
        ticker="RELIANCE"
        fairValue={1500}
        fallbackPrice={1000}
      />,
    )
    await waitFor(() => {
      expect(screen.getByTestId("live-mos-value").textContent).toMatch(
        /\+20\.0%/,
      )
    })
    expect(
      screen.getByTestId("live-mos-display").getAttribute("data-is-live"),
    ).toBe("1")
  })

  it("returns null when fair value is missing", () => {
    const { container } = render(
      <LiveMosDisplay
        ticker="RELIANCE"
        fairValue={0}
        fallbackPrice={1000}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("clamps extreme MoS values (audit #232 anti-regression)", async () => {
    // fv=1, fallback=0.0001 → raw MoS ~ +9999%; clamp to +200%.
    global.fetch = vi.fn(async () => {
      return new Response(JSON.stringify({ price: 0.0001 }), { status: 200 })
    }) as unknown as typeof fetch
    render(
      <LiveMosDisplay ticker="X" fairValue={1} fallbackPrice={0.5} />,
    )
    await waitFor(() => {
      const txt = screen.getByTestId("live-mos-value").textContent || ""
      // Must show +200.0% (clamp), not +999% or similar.
      expect(txt).toMatch(/\+200\.0%/)
    })
  })
})
