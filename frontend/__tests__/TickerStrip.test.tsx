/**
 * TickerStrip — mobile scroll-snap + touch-target pins.
 *
 * Mobile audit Issue 8 (P2): the strip is a horizontal scroller that
 * lacked scroll-snap on phones, chips rendered under the 44px iOS
 * minimum touch target, and there was no edge-fade affordance to hint
 * "more content this way." This file pins:
 *
 *   1. Scroll container declares `scrollSnapType: x mandatory` so chip
 *      flicks settle on a chip boundary rather than mid-cell.
 *   2. Each chip has min-h-[44px] (Apple HIG / Material Design minimum).
 *   3. The strip renders two edge-fade overlays (left + right) with
 *      pointer-events-none + aria-hidden so they affordance scroll
 *      without intercepting taps or polluting the AT tree.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import TickerStrip from "@/components/analysis/TickerStrip"
import { useAuthStore } from "@/store/authStore"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  // Logged-out path is enough — we're testing layout invariants.
  useAuthStore.setState({
    token: null,
    userId: null,
    email: null,
    tier: "free",
  } as Partial<ReturnType<typeof useAuthStore.getState>> as never)
  // jsdom fetch stub — return empty indices so the strip renders the
  // em-dash skeleton. We're not asserting on data, just on layout.
  const fetchMock = vi.fn(
    async () => new Response(JSON.stringify({ indices: [] }), { status: 200 }),
  )
  // @ts-expect-error installing a jsdom fetch stub
  globalThis.fetch = fetchMock
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("TickerStrip — mobile scroll-snap + touch-target", () => {
  it("scroll container has scroll-snap-type: x mandatory", () => {
    const { container } = renderWithClient(<TickerStrip />)
    const scroller = container.querySelector("div.overflow-x-auto") as HTMLElement | null
    expect(scroller).not.toBeNull()
    // Inline style — Tailwind 4 doesn't ship a snap-type-x class out of
    // the box, so the strip declares the property inline. Asserting on
    // the camelCase style value matches what React writes to the DOM.
    expect(scroller?.style.scrollSnapType).toBe("x mandatory")
    expect(scroller?.style.scrollPaddingLeft).toBe("1rem")
  })

  it("each Cell chip has min-h-[44px] for iOS-minimum tap targets", () => {
    const { container } = renderWithClient(<TickerStrip />)
    const cells = container.querySelectorAll(".min-h-\\[44px\\]")
    // Three chips at minimum: NIFTY 50, SENSEX, BANK NIFTY.
    expect(cells.length).toBeGreaterThanOrEqual(3)
  })

  it("renders two edge-fade overlays (left + right) that are aria-hidden", () => {
    const { container } = renderWithClient(<TickerStrip />)
    const fades = container.querySelectorAll('[aria-hidden="true"].pointer-events-none')
    // Filter to only the gradient overlays — exclude separator dots.
    const gradients = Array.from(fades).filter((el) =>
      el.className.includes("bg-gradient"),
    )
    expect(gradients.length).toBe(2)
  })
})
