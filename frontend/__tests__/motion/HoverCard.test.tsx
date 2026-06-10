/**
 * motion/HoverCard — hover transform tests.
 *
 * Pins:
 *   1. Renders children.
 *   2. Carries hover Tailwind classes (-translate-y-0.5, hover:shadow-md,
 *      hover:scale-[1.02]) under standard motion.
 *   3. Drops the scale class under reduced-motion (lift via shadow only).
 *   4. Disabled card carries neither hover class.
 *   5. data-motion-reduced reflects the resolved state.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import HoverCard from "@/components/motion/HoverCard"

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
  setReducedMotion(false)
  window.localStorage.clear()
  document.documentElement.removeAttribute("data-yq-motion-off")
})

describe("HoverCard", () => {
  it("renders children", () => {
    render(
      <HoverCard>
        <p>contents</p>
      </HoverCard>,
    )
    expect(screen.getByText("contents")).toBeInTheDocument()
  })

  it("carries lift + scale hover classes under standard motion", () => {
    render(
      <HoverCard>
        <p>contents</p>
      </HoverCard>,
    )
    const card = screen.getByText("contents").parentElement as HTMLElement
    const cls = card.className
    expect(cls).toContain("hover:-translate-y-0.5")
    expect(cls).toContain("hover:shadow-md")
    expect(cls).toContain("hover:scale-[1.02]")
    expect(card.getAttribute("data-motion-reduced")).toBe("false")
  })

  it("drops the scale class under reduced motion", () => {
    setReducedMotion(true)
    render(
      <HoverCard>
        <p>contents</p>
      </HoverCard>,
    )
    const card = screen.getByText("contents").parentElement as HTMLElement
    const cls = card.className
    expect(cls).not.toContain("hover:scale-[1.02]")
    // Shadow class still applied — state feedback survives reduced motion.
    expect(cls).toContain("hover:shadow-md")
    expect(card.getAttribute("data-motion-reduced")).toBe("true")
  })

  it("carries no hover classes when disabled", () => {
    render(
      <HoverCard disabled>
        <p>contents</p>
      </HoverCard>,
    )
    const card = screen.getByText("contents").parentElement as HTMLElement
    expect(card.className).not.toContain("hover:")
  })

  it("collapses transition to 'none' under reduced motion", () => {
    setReducedMotion(true)
    render(
      <HoverCard>
        <p>contents</p>
      </HoverCard>,
    )
    const card = screen.getByText("contents").parentElement as HTMLElement
    expect(card.style.transition).toBe("none")
  })
})
