/**
 * Sprint B.2 (2026-06-10) — StickyTableOfContents tests.
 *
 * Pins:
 *   1. Renders every section in the explicit `sections` prop, in
 *      order, inside the desktop rail.
 *   2. Falls back to scanning the DOM for `[data-toc-section]` when
 *      no prop is provided.
 *   3. Default-active = first section so the highlight always lands
 *      somewhere visible before any scroll happens.
 *   4. Click smooth-scrolls the target section (mock scrollIntoView)
 *      and updates the active highlight.
 *   5. IntersectionObserver-driven active tracking: when a different
 *      section enters the activation band, the highlight follows.
 *   6. Floating button + slide-in panel: button toggles the panel;
 *      clicking a panel item closes the panel and scrolls.
 *   7. Renders nothing when no sections are discovered.
 *   8. Honors the `toc-sections-changed` window event by re-scanning
 *      the DOM (covers tab-swap remounts).
 *   9. fix/sticky-toc-overlap-with-side-rail (2026-06-11): the
 *      desktop rail uses the `2xl:block` responsive prefix (was
 *      `xl:block`) so it stays hidden in the 1280-1535px range
 *      where the HonestHero side rail still occupies the right
 *      edge of the centered content container.
 *  10. fix/sticky-toc-overlap-with-side-rail (2026-06-11): the
 *      floating "Sections" button uses `2xl:hidden` (was
 *      `md:hidden`) so the navigator remains reachable at md/lg/xl
 *      viewports without overlap.
 *  11. fix/sticky-toc-overlap-with-side-rail (2026-06-11): the
 *      desktop rail is positioned via an inline `right: max(...)`
 *      style that pushes it OUTSIDE the 1152px content container's
 *      right edge — guarantees no overlap with the HonestHero
 *      sticky side rail at the 2xl breakpoint.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, act, fireEvent } from "@testing-library/react"
import StickyTableOfContents from "@/components/analysis/StickyTableOfContents"

type IOEntry = {
  isIntersecting: boolean
  intersectionRatio: number
  target: Element
}
type IOCallback = (entries: IOEntry[]) => void
const observers: { cb: IOCallback; targets: Element[] }[] = []

class MockIntersectionObserver {
  cb: IOCallback
  targets: Element[] = []
  constructor(cb: IOCallback) {
    this.cb = cb
    observers.push({ cb, targets: this.targets })
  }
  observe(el: Element) {
    this.targets.push(el)
  }
  unobserve(el: Element) {
    const i = this.targets.indexOf(el)
    if (i >= 0) this.targets.splice(i, 1)
  }
  disconnect() {
    this.targets.length = 0
  }
  takeRecords() {
    return []
  }
}

const sections = [
  { id: "summary", label: "Summary" },
  { id: "valuation", label: "Valuation Methods" },
  { id: "quality", label: "Quality Ratios" },
  { id: "peers", label: "Peer Comparison" },
]

function setupSectionsInDOM(seedDataAttrs = false) {
  for (const sec of sections) {
    const el = document.createElement("section")
    el.id = sec.id
    el.textContent = sec.label
    if (seedDataAttrs) el.setAttribute("data-toc-section", sec.label)
    document.body.appendChild(el)
  }
}

beforeEach(() => {
  observers.length = 0
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver)
  Element.prototype.scrollIntoView = vi.fn()
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    cb(performance.now())
    return 0
  })
  document.body.innerHTML = ""
})

describe("StickyTableOfContents", () => {
  it("renders one desktop item per explicit section in order", async () => {
    setupSectionsInDOM()
    render(<StickyTableOfContents sections={sections} />)
    await act(async () => {
      await Promise.resolve()
    })
    const desktop = screen.getByTestId("sticky-toc-desktop")
    const items = desktop.querySelectorAll<HTMLButtonElement>(
      "[data-testid^='toc-item-']",
    )
    expect(items.length).toBe(sections.length)
    expect(Array.from(items).map((el) => el.textContent?.trim())).toEqual([
      "Summary",
      "Valuation Methods",
      "Quality Ratios",
      "Peer Comparison",
    ])
  })

  it("falls back to discovering [data-toc-section] anchors from the DOM", async () => {
    setupSectionsInDOM(true)
    render(<StickyTableOfContents />)
    // Microtask scan -> next tick.
    await act(async () => {
      await Promise.resolve()
    })
    const desktop = screen.getByTestId("sticky-toc-desktop")
    const items = desktop.querySelectorAll<HTMLButtonElement>(
      "[data-testid^='toc-item-']",
    )
    expect(items.length).toBe(sections.length)
  })

  it("marks the first section as active on first paint", async () => {
    setupSectionsInDOM()
    render(<StickyTableOfContents sections={sections} />)
    await act(async () => {
      await Promise.resolve()
    })
    expect(
      screen.getByTestId("toc-item-summary").getAttribute("data-active"),
    ).toBe("true")
    expect(
      screen.getByTestId("toc-item-valuation").getAttribute("data-active"),
    ).toBe("false")
  })

  it("clicking an item scrolls the target section into view and marks it active", async () => {
    setupSectionsInDOM()
    render(<StickyTableOfContents sections={sections} />)
    await act(async () => {
      await Promise.resolve()
    })
    const qualityItem = screen.getByTestId("toc-item-quality")
    fireEvent.click(qualityItem)
    expect(qualityItem.getAttribute("data-active")).toBe("true")
    const qualitySection = document.getElementById("quality")!
    expect(qualitySection.scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    })
  })

  it("active item follows the intersection band as the user scrolls", async () => {
    setupSectionsInDOM()
    render(<StickyTableOfContents sections={sections} />)
    await act(async () => {
      await Promise.resolve()
    })
    const sectionObs = observers[0]
    expect(sectionObs).toBeDefined()
    // Valuation enters the band — highlight follows.
    await act(async () => {
      sectionObs.cb([
        {
          isIntersecting: false,
          intersectionRatio: 0,
          target: document.getElementById("summary")!,
        },
        {
          isIntersecting: true,
          intersectionRatio: 0,
          target: document.getElementById("valuation")!,
        },
      ])
    })
    expect(
      screen.getByTestId("toc-item-valuation").getAttribute("data-active"),
    ).toBe("true")
    // Quality enters, valuation leaves — highlight follows again.
    await act(async () => {
      sectionObs.cb([
        {
          isIntersecting: false,
          intersectionRatio: 0,
          target: document.getElementById("valuation")!,
        },
        {
          isIntersecting: true,
          intersectionRatio: 0,
          target: document.getElementById("quality")!,
        },
      ])
    })
    expect(
      screen.getByTestId("toc-item-quality").getAttribute("data-active"),
    ).toBe("true")
  })

  it("topmost section wins when multiple are in the band simultaneously", async () => {
    setupSectionsInDOM()
    render(<StickyTableOfContents sections={sections} />)
    await act(async () => {
      await Promise.resolve()
    })
    const sectionObs = observers[0]
    await act(async () => {
      sectionObs.cb([
        {
          isIntersecting: true,
          intersectionRatio: 0,
          target: document.getElementById("valuation")!,
        },
        {
          isIntersecting: true,
          intersectionRatio: 0,
          target: document.getElementById("quality")!,
        },
      ])
    })
    expect(
      screen.getByTestId("toc-item-valuation").getAttribute("data-active"),
    ).toBe("true")
  })

  it("toggles the mobile slide-in panel via the floating button", async () => {
    setupSectionsInDOM()
    render(<StickyTableOfContents sections={sections} />)
    await act(async () => {
      await Promise.resolve()
    })
    // Panel not in DOM on first paint.
    expect(
      screen.queryByTestId("sticky-toc-mobile-panel"),
    ).not.toBeInTheDocument()
    const fab = screen.getByTestId("sticky-toc-mobile-button")
    expect(fab.getAttribute("aria-expanded")).toBe("false")
    fireEvent.click(fab)
    expect(
      screen.getByTestId("sticky-toc-mobile-panel"),
    ).toBeInTheDocument()
    expect(fab.getAttribute("aria-expanded")).toBe("true")
  })

  it("clicking a mobile item closes the panel and scrolls", async () => {
    setupSectionsInDOM()
    render(<StickyTableOfContents sections={sections} />)
    await act(async () => {
      await Promise.resolve()
    })
    fireEvent.click(screen.getByTestId("sticky-toc-mobile-button"))
    const peersItem = screen.getByTestId("toc-mobile-item-peers")
    fireEvent.click(peersItem)
    expect(
      screen.queryByTestId("sticky-toc-mobile-panel"),
    ).not.toBeInTheDocument()
    const peersSection = document.getElementById("peers")!
    expect(peersSection.scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    })
  })

  it("renders nothing when no sections are discovered", () => {
    const { container } = render(<StickyTableOfContents />)
    expect(container.querySelector("[data-testid='sticky-toc-desktop']")).toBeNull()
    expect(
      container.querySelector("[data-testid='sticky-toc-mobile-button']"),
    ).toBeNull()
  })

  // ── fix/sticky-toc-overlap-with-side-rail (2026-06-11) ────────────
  //
  // Three responsive-behaviour pins covering the overlap fix. JSDOM
  // does not evaluate CSS media queries during render, so we assert
  // on the className the component emits — the same class names
  // Tailwind compiles into the actual breakpoint rules.

  it(
    "fix-toc-overlap: desktop rail is gated on `2xl:block`, not `xl:block`, " +
      "so it stays hidden at md/lg/xl viewports where the HonestHero " +
      "side rail still owns the right edge",
    async () => {
      setupSectionsInDOM()
      render(<StickyTableOfContents sections={sections} />)
      await act(async () => {
        await Promise.resolve()
      })
      const desktop = screen.getByTestId("sticky-toc-desktop")
      const cls = desktop.className
      expect(cls).toContain("2xl:block")
      // Hard-pin the negative: the previous `xl:block` (1280px) value
      // is what caused the overlap. Catch any regression that re-
      // introduces it.
      expect(cls).not.toMatch(/(^|\s)xl:block(\s|$)/)
      expect(cls).toContain("hidden")
    },
  )

  it(
    "fix-toc-overlap: floating button is gated on `2xl:hidden` so it " +
      "remains reachable at md/lg/xl viewports (1024-1535px) where " +
      "the desktop rail is suppressed",
    async () => {
      setupSectionsInDOM()
      render(<StickyTableOfContents sections={sections} />)
      await act(async () => {
        await Promise.resolve()
      })
      const fab = screen.getByTestId("sticky-toc-mobile-button")
      const cls = fab.className
      expect(cls).toContain("2xl:hidden")
      // Previous `md:hidden` (768px) hid the navigator entirely in
      // the 768-1535px range. Catch a regression that re-introduces it.
      expect(cls).not.toMatch(/(^|\s)md:hidden(\s|$)/)
    },
  )

  it(
    "fix-toc-overlap: desktop rail's `right` is computed via `max(...)` " +
      "so the rail sits OUTSIDE the centered max-w-6xl content " +
      "container — prevents overlap with the HonestHero sticky " +
      "side rail at 2xl",
    async () => {
      setupSectionsInDOM()
      render(<StickyTableOfContents sections={sections} />)
      await act(async () => {
        await Promise.resolve()
      })
      const desktop = screen.getByTestId("sticky-toc-desktop") as HTMLElement
      // React passes inline styles through to the DOM `style` attribute.
      // Read the raw attribute (not `.style.right`) so jsdom's CSSOM
      // limitations on unsupported value syntax do not swallow the test.
      const styleAttr = desktop.getAttribute("style") ?? ""
      expect(styleAttr).toMatch(/right:\s*max\(/)
      expect(styleAttr).toMatch(/50vw/)
      // The hard-coded Tailwind `right-6` of the original placement
      // would re-introduce the overlap. Catch any regression.
      expect(desktop.className).not.toMatch(/(^|\s)right-6(\s|$)/)
    },
  )

  it("re-scans the DOM on the toc-sections-changed window event", async () => {
    // Start with two sections, then add a third and dispatch the
    // change event; the new entry must show up in the desktop list.
    const initial = sections.slice(0, 2)
    for (const sec of initial) {
      const el = document.createElement("section")
      el.id = sec.id
      el.textContent = sec.label
      el.setAttribute("data-toc-section", sec.label)
      document.body.appendChild(el)
    }
    render(<StickyTableOfContents />)
    await act(async () => {
      await Promise.resolve()
    })
    let items = screen
      .getByTestId("sticky-toc-desktop")
      .querySelectorAll("[data-testid^='toc-item-']")
    expect(items.length).toBe(2)
    // Add a third section in the DOM and dispatch the event.
    const newSec = document.createElement("section")
    newSec.id = "peers"
    newSec.setAttribute("data-toc-section", "Peer Comparison")
    document.body.appendChild(newSec)
    await act(async () => {
      window.dispatchEvent(new CustomEvent("toc-sections-changed"))
    })
    items = screen
      .getByTestId("sticky-toc-desktop")
      .querySelectorAll("[data-testid^='toc-item-']")
    expect(items.length).toBe(3)
  })
})
