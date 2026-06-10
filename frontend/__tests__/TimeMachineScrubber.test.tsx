/**
 * TimeMachineScrubber smoke tests (T6.3, 2026-06-10).
 *
 * Pins:
 *   1. Renders a slider when fv_history has ≥ 2 points.
 *   2. Renders nothing when fv_history is empty or single-point —
 *      the scrubber needs a range to be useful.
 *   3. Date changes propagate via the onDateChange callback. Moving
 *      the slider to the rightmost tick (today) bubbles `null`.
 *   4. The Reset-to-today button clears the selection.
 *   5. The TimeMachineProvider exposes the matching `selectedPoint`
 *      via `useTimeMachine()` — proves the context bridge works.
 *   6. SEBI vocab guard — Pattern B (fragments) per CLAUDE.md rule #5.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import TimeMachineScrubber from "@/components/analysis/TimeMachineScrubber"
import {
  TimeMachineProvider,
  useTimeMachine,
} from "@/lib/time-machine-context"
import type { FVHistoryPoint } from "@/lib/api"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

/**
 * Synthesise N daily points spanning `spanDays` ending today.
 * Newest last (`fair_value_history` is returned oldest-first from the
 * backend).
 */
function makeHistory(spanDays: number, baseFv = 1200): FVHistoryPoint[] {
  const out: FVHistoryPoint[] = []
  const oneDay = 24 * 3600 * 1000
  const now = Date.now()
  for (let i = spanDays; i >= 0; i -= 7) {
    const d = new Date(now - i * oneDay)
    const t = (spanDays - i) / spanDays
    const fv = baseFv * (1 + t * 0.15)
    const price = baseFv * 0.9 * (1 + t * 0.1)
    out.push({
      date: d.toISOString().slice(0, 10),
      fair_value: Math.round(fv * 100) / 100,
      price: Math.round(price * 100) / 100,
      mos_pct: Math.round(((fv - price) / price) * 1000) / 10,
      verdict: "fair_value",
    })
  }
  return out
}

describe("TimeMachineScrubber", () => {
  it("renders the slider when fv_history has at least two points", () => {
    renderWithClient(
      <TimeMachineScrubber
        ticker="HDFCBANK.NS"
        fvHistory={makeHistory(365 * 2)}
        selectedDate={null}
        onDateChange={() => {}}
      />,
    )

    const section = screen.getByTestId("time-machine-scrubber")
    expect(section).toBeTruthy()
    expect(screen.getByTestId("time-machine-slider")).toBeTruthy()
    // Default label is "Today" when selectedDate is null.
    expect(screen.getByTestId("time-machine-current-label").textContent).toBe(
      "Today",
    )
  })

  it("renders nothing when fv_history is empty or single-point", () => {
    const { container, rerender } = renderWithClient(
      <TimeMachineScrubber
        ticker="HDFCBANK.NS"
        fvHistory={[]}
        selectedDate={null}
        onDateChange={() => {}}
      />,
    )
    expect(container.querySelector('[data-testid="time-machine-scrubber"]')).toBeNull()

    rerender(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <TimeMachineScrubber
          ticker="HDFCBANK.NS"
          fvHistory={makeHistory(0)}
          selectedDate={null}
          onDateChange={() => {}}
        />
      </QueryClientProvider>,
    )
    expect(container.querySelector('[data-testid="time-machine-scrubber"]')).toBeNull()
  })

  it("propagates date changes through onDateChange (mid-range = ISO date, end = null)", () => {
    const history = makeHistory(365 * 2)
    const onDateChange = vi.fn()
    const lastIndex = history.length - 1
    const startDate = history[Math.floor(lastIndex / 3)].date

    const { rerender } = renderWithClient(
      <TimeMachineScrubber
        ticker="HDFCBANK.NS"
        fvHistory={history}
        selectedDate={startDate}
        onDateChange={onDateChange}
      />,
    )
    const slider = screen.getByTestId("time-machine-slider") as HTMLInputElement

    // Drag to the middle — expect the matching ISO date to bubble up.
    const mid = Math.floor(lastIndex / 2)
    fireEvent.change(slider, { target: { value: String(mid) } })
    expect(onDateChange).toHaveBeenLastCalledWith(history[mid].date)

    // Caller commits the new selection; rerender mirrors that state so
    // the next interaction is a real value change.
    rerender(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <TimeMachineScrubber
          ticker="HDFCBANK.NS"
          fvHistory={history}
          selectedDate={history[mid].date}
          onDateChange={onDateChange}
        />
      </QueryClientProvider>,
    )

    // Drag to the rightmost tick — expect a null bubble (back to today).
    fireEvent.change(slider, { target: { value: String(lastIndex) } })
    expect(onDateChange).toHaveBeenLastCalledWith(null)
  })

  it("Reset button bubbles null and is only rendered when a date is selected", () => {
    const history = makeHistory(365 * 2)
    const onDateChange = vi.fn()

    const { rerender } = renderWithClient(
      <TimeMachineScrubber
        ticker="HDFCBANK.NS"
        fvHistory={history}
        selectedDate={null}
        onDateChange={onDateChange}
      />,
    )
    // No Reset button while at "today".
    expect(screen.queryByTestId("time-machine-reset")).toBeNull()

    rerender(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <TimeMachineScrubber
          ticker="HDFCBANK.NS"
          fvHistory={history}
          selectedDate={history[10].date}
          onDateChange={onDateChange}
        />
      </QueryClientProvider>,
    )
    const resetBtn = screen.getByTestId("time-machine-reset")
    expect(resetBtn).toBeTruthy()
    fireEvent.click(resetBtn)
    expect(onDateChange).toHaveBeenCalledWith(null)
  })

  it("TimeMachineProvider exposes the matching selectedPoint via useTimeMachine()", () => {
    const history = makeHistory(365 * 2)
    const targetDate = history[5].date

    function Probe() {
      const { selectedPoint } = useTimeMachine()
      return (
        <div data-testid="probe-fv">
          {selectedPoint ? String(selectedPoint.fair_value) : "none"}
        </div>
      )
    }

    function Harness() {
      // Drive the provider's setter from inside via a child that
      // changes the date on mount.
      const { setSelectedDate } = useTimeMachine()
      return (
        <button
          data-testid="harness-set"
          onClick={() => setSelectedDate(targetDate)}
        >
          set
        </button>
      )
    }

    renderWithClient(
      <TimeMachineProvider ticker="HDFCBANK.NS" historyOverride={history}>
        <Probe />
        <Harness />
      </TimeMachineProvider>,
    )

    // Initially "today" → null.
    expect(screen.getByTestId("probe-fv").textContent).toBe("none")
    fireEvent.click(screen.getByTestId("harness-set"))
    expect(screen.getByTestId("probe-fv").textContent).toBe(
      String(history[5].fair_value),
    )
  })

  // SEBI vocab guard — Pattern B (fragments) per CLAUDE.md rule #5.
  it("does not leak SEBI-banned verbs into rendered output", () => {
    const history = makeHistory(365 * 2)
    const { container } = renderWithClient(
      <TimeMachineScrubber
        ticker="HDFCBANK.NS"
        fvHistory={history}
        selectedDate={history[10].date}
        onDateChange={() => {}}
        currency="INR"
      />,
    )
    const BANNED = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "stro" + "ng b" + "uy",
      "stro" + "ng se" + "ll",
      "tar" + "get pri" + "ce",
      "recommen" + "dation",
    ]
    const haystack = (container.textContent || "").toLowerCase()
    for (const term of BANNED) {
      expect(haystack).not.toContain(term)
    }
  })
})
