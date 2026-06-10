/**
 * motion/RevealStagger — children stagger tests.
 *
 * Pins:
 *   1. All children render to the DOM (no clipping).
 *   2. Each child carries its `data-stagger-index` in order.
 *   3. With reduced-motion ON, child transition is `none` and delays
 *      collapse to 0.
 *   4. With reduced-motion OFF, child delay increases by staggerMs
 *      per index.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import RevealStagger from "@/components/motion/RevealStagger"

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
  lastIOCallback = null
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver)
  setReducedMotion(false)
  window.localStorage.clear()
  document.documentElement.removeAttribute("data-yq-motion-off")
})

describe("RevealStagger", () => {
  it("renders every child", () => {
    render(
      <RevealStagger>
        <span data-testid="a">A</span>
        <span data-testid="b">B</span>
        <span data-testid="c">C</span>
      </RevealStagger>,
    )
    expect(screen.getByTestId("a")).toBeInTheDocument()
    expect(screen.getByTestId("b")).toBeInTheDocument()
    expect(screen.getByTestId("c")).toBeInTheDocument()
  })

  it("assigns sequential data-stagger-index", () => {
    render(
      <RevealStagger>
        <span>A</span>
        <span>B</span>
        <span>C</span>
      </RevealStagger>,
    )
    const wrappers = document.querySelectorAll("[data-stagger-index]")
    expect(wrappers).toHaveLength(3)
    expect(wrappers[0].getAttribute("data-stagger-index")).toBe("0")
    expect(wrappers[1].getAttribute("data-stagger-index")).toBe("1")
    expect(wrappers[2].getAttribute("data-stagger-index")).toBe("2")
  })

  it("stagger delay increases per index when motion enabled", () => {
    render(
      <RevealStagger staggerMs={120}>
        <span>A</span>
        <span>B</span>
        <span>C</span>
      </RevealStagger>,
    )
    const wrappers = Array.from(
      document.querySelectorAll<HTMLElement>("[data-stagger-index]"),
    )
    const t0 = wrappers[0].style.transition
    const t1 = wrappers[1].style.transition
    const t2 = wrappers[2].style.transition
    // The transition string carries the per-child delay.
    expect(t0).toContain("0ms")
    expect(t1).toContain("120ms")
    expect(t2).toContain("240ms")
  })

  it("collapses transitions to 'none' under reduced motion", () => {
    setReducedMotion(true)
    render(
      <RevealStagger>
        <span>A</span>
        <span>B</span>
      </RevealStagger>,
    )
    const wrappers = Array.from(
      document.querySelectorAll<HTMLElement>("[data-stagger-index]"),
    )
    for (const w of wrappers) {
      expect(w.style.transition).toBe("none")
    }
  })
})
