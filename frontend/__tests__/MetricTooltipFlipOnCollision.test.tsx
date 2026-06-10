/**
 * MetricTooltip + MetricWithContext — flip-on-collision regression.
 *
 * Pins the fix for tmp/mobile_audit_2026_06_10.md issue #7: when the
 * trigger sits near the bottom of the viewport (common in KPI grids
 * on mobile), opening the popover below would clip it off-screen.
 *
 * The fix runs a getBoundingClientRect()-based collision check inside
 * the open useEffect and renders `bottom-full mb-*` instead of
 * `top-full mt-*` when there isn't enough room below.
 *
 * jsdom doesn't lay out — getBoundingClientRect() returns zeros by
 * default — so we stub the rect to simulate "trigger near viewport
 * bottom" and assert on the resulting class.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { act, fireEvent, render, screen } from "@testing-library/react"

import MetricTooltip from "@/components/analysis/MetricTooltip"
import MetricWithContext from "@/components/analysis/MetricWithContext"

function stubViewport(width: number, height: number) {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    writable: true,
    value: width,
  })
  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    writable: true,
    value: height,
  })
}

function stubElementRect(rect: Partial<DOMRect>) {
  const filled: DOMRect = {
    x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0,
    width: 0, height: 0,
    toJSON: () => ({}),
    ...rect,
  } as DOMRect
  return vi
    .spyOn(Element.prototype, "getBoundingClientRect")
    .mockReturnValue(filled)
}

let _rectSpy: ReturnType<typeof vi.spyOn> | null = null

beforeEach(() => {
  _rectSpy = null
})

afterEach(() => {
  _rectSpy?.mockRestore()
  _rectSpy = null
})

describe("MetricTooltip — flip on bottom-of-viewport collision", () => {
  it("opens DOWN when there is plenty of room below", async () => {
    stubViewport(360, 800)
    // Trigger near the TOP of the viewport — plenty of room below.
    _rectSpy = stubElementRect({
      top: 40, bottom: 56, left: 20, right: 36, width: 16, height: 16,
    })
    render(<MetricTooltip metricKey="roce">ROCE</MetricTooltip>)
    const trigger = screen.getByRole("button", { name: /what is/i })
    await act(async () => { fireEvent.focus(trigger) })
    const popover = screen.getByRole("tooltip")
    expect(popover.getAttribute("data-flip")).toBe("down")
    expect(popover.className).toContain("top-full")
    expect(popover.className).toContain("mt-2")
    expect(popover.className).not.toContain("bottom-full")
  })

  it("flips UP when the trigger is near the bottom of the viewport (mobile audit issue #7)", async () => {
    stubViewport(360, 640)
    // Trigger 20px from the bottom of a 640px viewport — popover
    // estimated at 220px would clip badly below; lots of room above.
    _rectSpy = stubElementRect({
      top: 604, bottom: 620, left: 20, right: 36, width: 16, height: 16,
    })
    render(<MetricTooltip metricKey="roce">ROCE</MetricTooltip>)
    const trigger = screen.getByRole("button", { name: /what is/i })
    await act(async () => { fireEvent.focus(trigger) })
    const popover = screen.getByRole("tooltip")
    expect(popover.getAttribute("data-flip")).toBe("up")
    expect(popover.className).toContain("bottom-full")
    expect(popover.className).toContain("mb-2")
    expect(popover.className).not.toContain("top-full")
  })
})

describe("MetricWithContext — flip on bottom-of-viewport collision", () => {
  function renderWithContext() {
    return render(
      <MetricWithContext
        label="ROE"
        value={8.8}
        format={(n) => `${n.toFixed(1)}%`}
        peerMedian={12.4}
        peerP5={4.0}
        peerP95={22.0}
        direction="higher_is_better"
      />,
    )
  }

  it("opens DOWN by default", async () => {
    stubViewport(360, 800)
    _rectSpy = stubElementRect({
      top: 40, bottom: 80, left: 0, right: 200, width: 200, height: 40,
    })
    renderWithContext()
    // The whole row is focusable (tabIndex 0); focus triggers hover state.
    const row = screen.getByLabelText(/^ROE:/)
    await act(async () => { fireEvent.focus(row) })
    const tip = screen.getByRole("tooltip")
    expect(tip.getAttribute("data-flip")).toBe("down")
    expect(tip.className).toContain("top-full")
    expect(tip.className).not.toContain("bottom-full")
  })

  it("flips UP near the viewport bottom", async () => {
    stubViewport(360, 640)
    _rectSpy = stubElementRect({
      top: 600, bottom: 632, left: 0, right: 200, width: 200, height: 32,
    })
    renderWithContext()
    const row = screen.getByLabelText(/^ROE:/)
    await act(async () => { fireEvent.focus(row) })
    const tip = screen.getByRole("tooltip")
    expect(tip.getAttribute("data-flip")).toBe("up")
    expect(tip.className).toContain("bottom-full")
    expect(tip.className).not.toContain("top-full")
  })
})
