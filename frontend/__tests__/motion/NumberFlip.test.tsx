/**
 * motion/NumberFlip — value transition tests.
 *
 * Pins:
 *   1. Renders the initial value on mount (SSR-equivalent paint).
 *   2. When `value` prop changes, the displayed value flips to the
 *      new value within the flip duration (DURATION.fast = 200ms).
 *   3. Under reduced motion, the new value renders immediately
 *      without going through the flip transform.
 *   4. Carries `data-motion="number-flip"` for observability.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, act } from "@testing-library/react"
import NumberFlip from "@/components/motion/NumberFlip"

type IOCallback = (entries: { isIntersecting: boolean }[]) => void
let lastIOCallback: IOCallback | null = null

class MockIntersectionObserver {
  constructor(cb: IOCallback) {
    lastIOCallback = cb
  }
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}

function setReducedMotion(reduced: boolean) {
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
  vi.useFakeTimers()
  lastIOCallback = null
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver)
  setReducedMotion(false)
  window.localStorage.clear()
  document.documentElement.removeAttribute("data-yq-motion-off")
})

describe("NumberFlip", () => {
  it("renders the initial value on mount", () => {
    render(<NumberFlip value={42} />)
    expect(screen.getByText("42")).toBeInTheDocument()
  })

  it("respects decimals + prefix + suffix in the formatter", () => {
    render(<NumberFlip value={1234.5} decimals={2} prefix="₹" suffix=" cr" />)
    //   narrow space could appear from Intl.NumberFormat in some locales —
    // we look for the digits substring to stay locale-tolerant.
    const el = screen.getByText(/1,234\.50 cr/)
    expect(el).toBeInTheDocument()
  })

  it("flips to a new value when the prop changes", () => {
    const { rerender } = render(<NumberFlip value={10} />)
    expect(screen.getByText("10")).toBeInTheDocument()

    // Trigger the value change; the effect schedules two timers
    // (the value swap at half-duration, the flip-cleanup at full).
    rerender(<NumberFlip value={20} />)
    // Immediately after rerender the flipping data attribute is true
    // and the displayed value is still 10 — proves the flip kicked off
    // rather than snap-cutting.
    const flippingSpan = screen.getByText("10")
    expect(flippingSpan.getAttribute("data-motion-flipping")).toBe("true")

    // Advance past the halfway timer (100ms) so the value swap fires.
    act(() => {
      vi.advanceTimersByTime(120)
    })
    expect(screen.getByText("20")).toBeInTheDocument()

    // Advance past the full flip duration so the cleanup timer fires.
    act(() => {
      vi.advanceTimersByTime(200)
    })
    const settledSpan = screen.getByText("20")
    expect(settledSpan.getAttribute("data-motion-flipping")).toBe("false")
  })

  it("under reduced motion, new value renders without flip class", () => {
    setReducedMotion(true)
    const { rerender } = render(<NumberFlip value={5} />)
    act(() => {
      rerender(<NumberFlip value={9} />)
    })
    const span = screen.getByText("9")
    // No flipping transform applied — data attribute always "false".
    expect(span.getAttribute("data-motion-flipping")).toBe("false")
  })

  it("carries the data-motion observability tag", () => {
    render(<NumberFlip value={1} />)
    const span = screen.getByText("1")
    expect(span.getAttribute("data-motion")).toBe("number-flip")
  })
})
