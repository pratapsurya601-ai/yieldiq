/**
 * Premium-feel Round 1 — StickyAnalysisNav tests.
 *
 * Pins:
 *   1. Renders one pill per section, in the order passed.
 *   2. Default active section has data-active="true" on first paint.
 *   3. Clicking a pill fires onSelect(id), updates the active pill,
 *      and asks the browser to smooth-scroll the target section into
 *      view.
 *   4. Active-pill highlight follows scroll position — when the
 *      IntersectionObserver fires "valuation is most visible", the
 *      valuation pill takes over.
 *   5. Glass background ("stuck" treatment) only attaches after the
 *      hero scrolls off-screen.
 *   6. Mobile-friendly: pills live inside an overflow-x-auto strip so
 *      they remain reachable below 360px.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, act, fireEvent } from "@testing-library/react"
import StickyAnalysisNav from "@/components/analysis/StickyAnalysisNav"

// IntersectionObserver harness — we register every observer the
// component creates so tests can drive either the hero observer or
// the per-section observer independently.
type IOEntry = { isIntersecting: boolean; intersectionRatio: number; target: Element }
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
  { id: "valuation", label: "Valuation" },
  { id: "quality", label: "Quality" },
]

function setupSectionsInDOM() {
  // Each section needs to exist with an id so the component can call
  // scrollIntoView on the right node.
  for (const sec of sections) {
    const el = document.createElement("section")
    el.id = sec.id
    el.textContent = sec.label
    document.body.appendChild(el)
  }
}

beforeEach(() => {
  observers.length = 0
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver)
  // jsdom doesn't implement scrollIntoView — install a spy.
  Element.prototype.scrollIntoView = vi.fn()
  // requestAnimationFrame is jsdom-supported but mock it to run sync
  // so the click handler's deferred scroll lands within the test.
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    cb(performance.now())
    return 0
  })
  document.body.innerHTML = ""
  setupSectionsInDOM()
})

describe("StickyAnalysisNav", () => {
  it("renders one pill per section in the order provided", () => {
    render(<StickyAnalysisNav sections={sections} />)
    const pills = screen.getAllByRole("button")
    expect(pills.map((b) => b.textContent)).toEqual(["Summary", "Valuation", "Quality"])
  })

  it("marks the default-active pill on first paint", () => {
    render(<StickyAnalysisNav sections={sections} defaultActive="valuation" />)
    const valuation = screen.getByTestId("nav-pill-valuation")
    expect(valuation.getAttribute("data-active")).toBe("true")
    expect(valuation.getAttribute("aria-current")).toBe("true")
    const summary = screen.getByTestId("nav-pill-summary")
    expect(summary.getAttribute("data-active")).toBe("false")
  })

  it("falls back to the first section when no defaultActive is given", () => {
    render(<StickyAnalysisNav sections={sections} />)
    const summary = screen.getByTestId("nav-pill-summary")
    expect(summary.getAttribute("data-active")).toBe("true")
  })

  it("fires onSelect and scrolls the target section on click", () => {
    const onSelect = vi.fn()
    render(<StickyAnalysisNav sections={sections} onSelect={onSelect} />)
    const qualityPill = screen.getByTestId("nav-pill-quality")
    fireEvent.click(qualityPill)
    expect(onSelect).toHaveBeenCalledWith("quality")
    expect(qualityPill.getAttribute("data-active")).toBe("true")
    const qualitySection = document.getElementById("quality")!
    expect(qualitySection.scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    })
  })

  it("updates the active pill when scroll-driven intersection picks a new section", async () => {
    render(<StickyAnalysisNav sections={sections} />)
    // The second observer is the per-section tracker (the first is for
    // the hero — only attached when heroSelector is provided, so here
    // the per-section tracker is observers[0]).
    expect(observers.length).toBeGreaterThanOrEqual(1)
    const sectionObs = observers[0]
    const valuationEl = document.getElementById("valuation")!
    await act(async () => {
      sectionObs.cb([
        { isIntersecting: true, intersectionRatio: 0.8, target: valuationEl },
        {
          isIntersecting: true,
          intersectionRatio: 0.2,
          target: document.getElementById("summary")!,
        },
      ])
    })
    expect(
      screen.getByTestId("nav-pill-valuation").getAttribute("data-active"),
    ).toBe("true")
  })

  it("attaches the stuck glass treatment only after the hero leaves the viewport", async () => {
    // Place a hero element in the DOM so the heroSelector resolves.
    const hero = document.createElement("div")
    hero.setAttribute("data-hero", "true")
    document.body.appendChild(hero)
    render(
      <StickyAnalysisNav sections={sections} heroSelector="[data-hero=true]" />,
    )
    const nav = screen.getByTestId("sticky-analysis-nav")
    // First observer registered is the hero tracker.
    const heroObs = observers[0]
    // Pre-scroll: hero still on screen -> nav must NOT be stuck.
    await act(async () => {
      heroObs.cb([
        { isIntersecting: true, intersectionRatio: 1, target: hero },
      ])
    })
    expect(nav.getAttribute("data-stuck")).toBe("false")
    // After scroll past hero: hero off screen -> nav goes stuck.
    await act(async () => {
      heroObs.cb([
        { isIntersecting: false, intersectionRatio: 0, target: hero },
      ])
    })
    expect(nav.getAttribute("data-stuck")).toBe("true")
    expect(nav.className).toMatch(/backdrop-blur/)
  })

  it("starts stuck immediately when no hero selector is provided", () => {
    render(<StickyAnalysisNav sections={sections} />)
    const nav = screen.getByTestId("sticky-analysis-nav")
    expect(nav.getAttribute("data-stuck")).toBe("true")
  })

  it("keeps pills inside a horizontally-scrollable strip for mobile reachability", () => {
    const { container } = render(<StickyAnalysisNav sections={sections} />)
    const strip = container.querySelector("ul")!
    expect(strip.className).toMatch(/overflow-x-auto/)
  })
})
