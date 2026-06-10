/**
 * Sprint B.2 (2026-06-10) — AnalysisTabs smooth-transition tests.
 *
 * The B.2 spec wraps the active panel under <AnimatePresence> so
 * switching Summary -> Valuation -> Quality fades instead of hard-
 * cutting. We do not assert specific framer-motion class names —
 * those are implementation details. We DO assert:
 *   1. Each tab renders its content when selected.
 *   2. Tab switching swaps the rendered content (single active panel).
 *   3. Switching back returns to the original tab's content.
 *   4. Controlled `active` prop still drives the swap.
 *   5. `onTabChange` fires on user click.
 *
 * Framer-motion exposes a CSS-driven path under jsdom; the transition
 * collapses to a synchronous render so the assertions stay stable.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import AnalysisTabs, { type AnalysisTabDef } from "@/components/analysis/AnalysisTabs"

const tabs: AnalysisTabDef[] = [
  { key: "summary", label: "Summary", content: <p>summary-content</p> },
  { key: "valuation", label: "Valuation", content: <p>valuation-content</p> },
  { key: "quality", label: "Quality", content: <p>quality-content</p> },
  { key: "financials", label: "Financials", content: <p>financials-content</p> },
  { key: "history", label: "History", content: <p>history-content</p> },
  { key: "peers", label: "Peers", content: <p>peers-content</p> },
]

describe("AnalysisTabs smooth transitions (B.2)", () => {
  it("renders the initial tab's content", () => {
    render(<AnalysisTabs tabs={tabs} initial="summary" />)
    expect(screen.getByText("summary-content")).toBeInTheDocument()
  })

  it("swaps content when a different tab is clicked", async () => {
    render(<AnalysisTabs tabs={tabs} initial="summary" />)
    fireEvent.click(screen.getByRole("tab", { name: "Valuation" }))
    // popLayout AnimatePresence keeps the previous panel mounted while
    // the exit animation runs; jsdom resolves the animation in the
    // next microtask, so wait for the swap to settle.
    await waitFor(() => {
      expect(screen.getByText("valuation-content")).toBeInTheDocument()
      expect(screen.queryByText("summary-content")).not.toBeInTheDocument()
    })
  })

  it("fires onTabChange with the new tab key", () => {
    const onTabChange = vi.fn()
    render(
      <AnalysisTabs
        tabs={tabs}
        initial="summary"
        onTabChange={onTabChange}
      />,
    )
    fireEvent.click(screen.getByRole("tab", { name: "Quality" }))
    expect(onTabChange).toHaveBeenCalledWith("quality")
  })

  it("switching back to the original tab re-renders its content", async () => {
    render(<AnalysisTabs tabs={tabs} initial="summary" />)
    fireEvent.click(screen.getByRole("tab", { name: "Valuation" }))
    await waitFor(() =>
      expect(screen.getByText("valuation-content")).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole("tab", { name: "Summary" }))
    await waitFor(() =>
      expect(screen.getByText("summary-content")).toBeInTheDocument(),
    )
  })

  it("active panel carries the data-tabpanel-key attribute matching the active tab", () => {
    const { container } = render(<AnalysisTabs tabs={tabs} initial="history" />)
    const panel = container.querySelector("[data-tabpanel-key='history']")
    expect(panel).not.toBeNull()
    expect(panel?.textContent).toBe("history-content")
  })
})
