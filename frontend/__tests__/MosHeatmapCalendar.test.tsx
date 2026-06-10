/**
 * MosHeatmapCalendar smoke tests.
 *
 * Pins:
 *   1. Renders one gridcell per day in the selected range.
 *   2. Range selector toggles 1Y/2Y/3Y and shrinks/grows the grid.
 *   3. Empty-data state shows the right placeholder.
 *   4. Hover surfaces a tooltip with date + MoS + FV + price.
 *   5. Click on a data-bearing cell dispatches the
 *      `mos-heatmap-day-click` CustomEvent that ValuationTrajectoryChart
 *      will eventually listen for.
 *   6. SEBI vocab guard — fragments-built BANNED array
 *      (Pattern B per root CLAUDE.md rule #5) confirms none of the
 *      regulator-restricted verbs leak into the rendered DOM.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import MosHeatmapCalendar, {
  MOS_HEATMAP_DAY_EVENT,
} from "@/components/analysis/MosHeatmapCalendar"
import type { FVHistoryPoint } from "@/lib/api"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

/**
 * Synthesise daily fv_history points spanning `spanDays` ending today.
 * Roughly weekly cadence so a 3Y test stays fast but still produces a
 * representative grid.
 */
function makeHistory(spanDays: number, basePrice = 1000, baseFv = 1200): FVHistoryPoint[] {
  const out: FVHistoryPoint[] = []
  const oneDay = 24 * 3600 * 1000
  const now = Date.now()
  const stride = Math.max(1, Math.floor(spanDays / 80))
  for (let i = spanDays; i >= 0; i -= stride) {
    const d = new Date(now - i * oneDay)
    const t = (spanDays - i) / spanDays
    const fv = baseFv * (1 + t * 0.2)
    const price = basePrice * (1 + t * 0.15 + Math.sin(i / 9) * 0.04)
    out.push({
      date: d.toISOString().slice(0, 10),
      fair_value: Math.round(fv * 100) / 100,
      price: Math.round(price * 100) / 100,
      mos_pct: Math.round(((fv - price) / price) * 1000) / 10,
      verdict: "fair_value",
    } as FVHistoryPoint)
  }
  return out
}

describe("MosHeatmapCalendar", () => {
  it("renders one button per day-cell with data + no-data classes", () => {
    const history = makeHistory(365)
    renderWithClient(
      <MosHeatmapCalendar
        ticker="HDFCBANK.NS"
        historyOverride={history}
      />,
    )
    const section = screen.getByTestId("mos-heatmap-calendar")
    expect(section).toHaveAttribute("data-state", "ready")
    const cells = within(section).getAllByTestId("mos-heatmap-cell")
    // 1Y default → at least 365 cells, usually a bit more after the
    // Sunday alignment offset.
    expect(cells.length).toBeGreaterThanOrEqual(365)
    // Mix of has-data + no-data cells (sparse weekly history).
    const dataCells = cells.filter(
      (c) => c.getAttribute("data-has-data") === "true",
    )
    const blankCells = cells.filter(
      (c) => c.getAttribute("data-has-data") === "false",
    )
    expect(dataCells.length).toBeGreaterThan(0)
    expect(blankCells.length).toBeGreaterThan(0)
  })

  it("range selector toggles 1Y/2Y/3Y and resizes the grid", () => {
    const history = makeHistory(365 * 3)
    renderWithClient(
      <MosHeatmapCalendar
        ticker="HDFCBANK.NS"
        historyOverride={history}
      />,
    )
    const oneY = screen.getByRole("radio", { name: /1Y range/i })
    const twoY = screen.getByRole("radio", { name: /2Y range/i })
    const threeY = screen.getByRole("radio", { name: /3Y range/i })

    // Default is 1Y.
    expect(oneY).toHaveAttribute("aria-checked", "true")
    const startCells = screen.getAllByTestId("mos-heatmap-cell").length

    fireEvent.click(threeY)
    expect(threeY).toHaveAttribute("aria-checked", "true")
    const wideCells = screen.getAllByTestId("mos-heatmap-cell").length
    expect(wideCells).toBeGreaterThan(startCells)

    fireEvent.click(twoY)
    expect(twoY).toHaveAttribute("aria-checked", "true")
    const midCells = screen.getAllByTestId("mos-heatmap-cell").length
    expect(midCells).toBeGreaterThan(startCells)
    expect(midCells).toBeLessThan(wideCells)
  })

  it("empty history renders the placeholder, not a grid", () => {
    renderWithClient(
      <MosHeatmapCalendar
        ticker="UNKNOWN.NS"
        historyOverride={[]}
      />,
    )
    const section = screen.getByTestId("mos-heatmap-calendar")
    expect(section).toHaveAttribute("data-state", "empty")
    expect(
      within(section).queryAllByTestId("mos-heatmap-cell").length,
    ).toBe(0)
  })

  it("hover on a data-bearing cell renders the tooltip", () => {
    const history = makeHistory(365)
    renderWithClient(
      <MosHeatmapCalendar
        ticker="HDFCBANK.NS"
        historyOverride={history}
      />,
    )
    const cells = screen.getAllByTestId("mos-heatmap-cell")
    const target = cells.find(
      (c) => c.getAttribute("data-has-data") === "true",
    )
    expect(target).toBeTruthy()
    if (!target) return
    fireEvent.mouseEnter(target)
    expect(screen.getByTestId("mos-heatmap-tooltip")).toBeInTheDocument()
    // Tooltip must include a numeric MoS row.
    expect(screen.getByTestId("mos-heatmap-tooltip").textContent).toMatch(
      /MoS/,
    )
  })

  it("click on a data cell dispatches the day-click custom event", () => {
    const history = makeHistory(365)
    const spy = vi.fn()
    window.addEventListener(MOS_HEATMAP_DAY_EVENT, spy as EventListener)
    try {
      renderWithClient(
        <MosHeatmapCalendar
          ticker="HDFCBANK.NS"
          historyOverride={history}
        />,
      )
      const cells = screen.getAllByTestId("mos-heatmap-cell")
      const target = cells.find(
        (c) => c.getAttribute("data-has-data") === "true",
      )
      expect(target).toBeTruthy()
      if (!target) return
      fireEvent.click(target)
      expect(spy).toHaveBeenCalledTimes(1)
      const evt = spy.mock.calls[0][0] as CustomEvent<{
        date: string
        point: FVHistoryPoint
      }>
      expect(evt.detail.date).toBe(target.getAttribute("data-iso"))
      expect(evt.detail.point).toBeTruthy()
    } finally {
      window.removeEventListener(MOS_HEATMAP_DAY_EVENT, spy as EventListener)
    }
  })

  it("does not dispatch the day-click event for no-data cells", () => {
    const history = makeHistory(365)
    const spy = vi.fn()
    window.addEventListener(MOS_HEATMAP_DAY_EVENT, spy as EventListener)
    try {
      renderWithClient(
        <MosHeatmapCalendar
          ticker="HDFCBANK.NS"
          historyOverride={history}
        />,
      )
      const cells = screen.getAllByTestId("mos-heatmap-cell")
      const blank = cells.find(
        (c) => c.getAttribute("data-has-data") === "false",
      )
      expect(blank).toBeTruthy()
      if (!blank) return
      // disabled <button> still triggers DOM click events in jsdom but
      // the component's onClick handler is gated by the disabled prop,
      // so no CustomEvent fires.
      fireEvent.click(blank)
      expect(spy).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener(MOS_HEATMAP_DAY_EVENT, spy as EventListener)
    }
  })

  it("rendered DOM does not leak SEBI-restricted vocabulary", () => {
    const history = makeHistory(365)
    const { container } = renderWithClient(
      <MosHeatmapCalendar
        ticker="HDFCBANK.NS"
        historyOverride={history}
      />,
    )
    // Pattern B from CLAUDE.md rule #5 — banned tokens built from
    // string fragments so the source file passes diff-only sebi-lint.
    const BANNED = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "stro" + "ng b" + "uy",
      "stro" + "ng se" + "ll",
      "underval" + "ued",
      "overval" + "ued",
    ]
    const text = (container.textContent || "").toLowerCase()
    for (const word of BANNED) {
      expect(text).not.toContain(word)
    }
  })
})
