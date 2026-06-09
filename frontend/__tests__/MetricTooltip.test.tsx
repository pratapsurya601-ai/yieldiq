/**
 * MetricTooltip (Premium Feel R2) — primitive tests.
 *
 * Pins:
 *   1. Renders trigger with label + value inline.
 *   2. Opens the popover on hover (mouseEnter on the trigger button).
 *   3. Closes on Escape; closes on mouseLeave.
 *   4. Keyboard-accessible: Tab focuses the trigger, focus opens it.
 *   5. Renders content sourced from metric-explainers.ts when `metric`
 *      is set.
 *   6. SEBI vocabulary regression — the entire MetricTooltip + ALL
 *      explainer copy contains zero banned vocabulary. This is the
 *      runtime backstop to the lint script.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, act, fireEvent } from "@testing-library/react"
import MetricTooltip from "@/components/common/MetricTooltip"
import { METRIC_EXPLAINERS } from "@/lib/metric-explainers"

// Banned tokens mirror scripts/check_sebi_words.py. These constants
// only ever render INSIDE this test file (never to the DOM), so we
// per-line sebi-allow each entry. The runtime assertion below proves
// no rendered tooltip output ever contains any of these tokens.
const BANNED_WORDS = [
  "appears",        // sebi-allow: appears
  "concern",        // sebi-allow: concern
  "strength",       // sebi-allow: strength
  "weakness",       // sebi-allow: weakness
  "outperform",     // sebi-allow: outperform
  "underperform",   // sebi-allow: underperform
  "expensive",      // sebi-allow: expensive
  "attractive",     // sebi-allow: attractive
  "accumulate",     // sebi-allow: accumulate
  "recommend",      // sebi-allow: recommend
  "recommendation", // sebi-allow: recommendation
  "investable",     // sebi-allow: investable
  "investability",  // sebi-allow: investability
]

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

beforeEach(() => {
  setReducedMotion(false)
})

describe("MetricTooltip", () => {
  it("renders trigger with label and value inline", () => {
    render(<MetricTooltip label="ROE" value="18.3%" metric="roe" />)
    expect(screen.getByText("ROE")).toBeInTheDocument()
    expect(screen.getByText("18.3%")).toBeInTheDocument()
    // Trigger is a real <button>, identifiable by slugified test id.
    const wrapper = screen.getByTestId("metric-tooltip-roe")
    expect(wrapper).toBeTruthy()
    const trigger = wrapper.querySelector("button")
    expect(trigger).not.toBeNull()
    expect(trigger?.getAttribute("aria-expanded")).toBe("false")
  })

  it("opens the popover on hover (mouseEnter)", async () => {
    render(<MetricTooltip label="ROE" value="18.3%" metric="roe" />)
    const wrapper = screen.getByTestId("metric-tooltip-roe")
    const trigger = wrapper.querySelector("button") as HTMLButtonElement
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    const popover = screen.getByTestId("metric-tooltip-content")
    expect(popover).toBeInTheDocument()
    expect(popover.getAttribute("role")).toBe("tooltip")
  })

  it("closes the popover on Escape and on mouseLeave", async () => {
    render(<MetricTooltip label="ROE" value="18.3%" metric="roe" />)
    const wrapper = screen.getByTestId("metric-tooltip-roe")
    const trigger = wrapper.querySelector("button") as HTMLButtonElement
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })
    expect(screen.getByTestId("metric-tooltip-content")).toBeInTheDocument()
    await act(async () => {
      fireEvent.keyDown(document, { key: "Escape" })
    })
    expect(screen.queryByTestId("metric-tooltip-content")).toBeNull()
    // Re-open via hover, then leave to close.
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })
    expect(screen.getByTestId("metric-tooltip-content")).toBeInTheDocument()
    await act(async () => {
      fireEvent.mouseLeave(trigger, { relatedTarget: document.body })
    })
    expect(screen.queryByTestId("metric-tooltip-content")).toBeNull()
  })

  it("is keyboard-accessible: focus opens the popover", async () => {
    render(<MetricTooltip label="ROE" value="18.3%" metric="roe" />)
    const wrapper = screen.getByTestId("metric-tooltip-roe")
    const trigger = wrapper.querySelector("button") as HTMLButtonElement
    await act(async () => {
      trigger.focus()
      fireEvent.focus(trigger)
    })
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    expect(screen.getByTestId("metric-tooltip-content")).toBeInTheDocument()
    // The popover is linked to the trigger via aria-describedby for
    // screen readers — verify the relationship.
    const describedBy = trigger.getAttribute("aria-describedby")
    expect(describedBy).toBeTruthy()
    expect(document.getElementById(describedBy as string)).not.toBeNull()
  })

  it("renders title + description + formula sourced from metric-explainers.ts when `metric` is passed", async () => {
    render(<MetricTooltip label="ROE" value="18.3%" metric="roe" />)
    const wrapper = screen.getByTestId("metric-tooltip-roe")
    const trigger = wrapper.querySelector("button") as HTMLButtonElement
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })
    const popover = screen.getByTestId("metric-tooltip-content")
    const entry = METRIC_EXPLAINERS.roe
    expect(popover.textContent).toContain(entry.title)
    expect(popover.textContent).toContain(entry.description)
    if (entry.formula) {
      expect(popover.textContent).toContain(entry.formula)
    }
  })

  it("inline props override the metric-explainer copy", async () => {
    render(
      <MetricTooltip
        label="ROE"
        value="18.3%"
        metric="roe"
        title="Custom title"
        description="Custom description for this site only."
      />,
    )
    const wrapper = screen.getByTestId("metric-tooltip-roe")
    const trigger = wrapper.querySelector("button") as HTMLButtonElement
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })
    const popover = screen.getByTestId("metric-tooltip-content")
    expect(popover.textContent).toContain("Custom title")
    expect(popover.textContent).toContain("Custom description for this site only.")
    // The default ROE title from the library must NOT be rendered.
    expect(popover.textContent).not.toContain(
      METRIC_EXPLAINERS.roe.title,
    )
  })

  it("renders value-only fallback when no copy is resolvable", () => {
    // Unknown metric key + no inline overrides → component degrades to
    // an inline label + value with no trigger / no popover.
    const { container } = render(
      <MetricTooltip label="WEIRD" value="123" metric="this-key-does-not-exist" />,
    )
    expect(screen.getByText("WEIRD")).toBeInTheDocument()
    expect(screen.getByText("123")).toBeInTheDocument()
    // No button = no trigger = no popover wiring.
    expect(container.querySelector("button")).toBeNull()
  })

  it("SEBI vocabulary regression — no banned token surfaces in any rendered output across the entire explainer set", async () => { // sebi-allow: strength,strong,weak,weakness,buy,sell,hold,recommend,attractive,cheap,expensive,concern,investable,investability,accumulate,outperform,underperform,poor,appears,should,recommendation
    for (const [metric, entry] of Object.entries(METRIC_EXPLAINERS)) {
      const { unmount } = render(
        <MetricTooltip label={metric} value="—" metric={metric} />,
      )
      const wrapper = screen.getByTestId(`metric-tooltip-${metric.replace(/_/g, "-")}`)
      const trigger = wrapper.querySelector("button") as HTMLButtonElement
      await act(async () => {
        fireEvent.mouseEnter(trigger)
      })
      const popover = screen.getByTestId("metric-tooltip-content")
      const rendered = popover.textContent ?? ""
      for (const banned of BANNED_WORDS) {
        const pattern = new RegExp(`\\b${banned}\\b`, "i")
        expect(
          pattern.test(rendered),
          `entry "${metric}" contains banned word "${banned}": ${rendered}`,
        ).toBe(false)
      }
      // Cross-check: the title field on every entry must be non-empty.
      expect(entry.title.length).toBeGreaterThan(0)
      unmount()
    }
  })
})
