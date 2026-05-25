import { describe, it, expect } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import MetricWithContext from "@/components/analysis/MetricWithContext"

describe("MetricWithContext", () => {
  it("renders an em-dash row when both value and median are absent", () => {
    render(
      <MetricWithContext
        label="ROE"
        value={null}
        format={(n) => `${n.toFixed(1)}%`}
        peerMedian={null}
      />
    )
    expect(screen.getByText("ROE")).toBeInTheDocument()
    expect(screen.getByText("—")).toBeInTheDocument()
  })

  it("renders naked value when peer median is missing but value present", () => {
    render(
      <MetricWithContext
        label="ROE"
        value={12.4}
        format={(n) => `${n.toFixed(1)}%`}
        peerMedian={null}
      />
    )
    expect(screen.getByText("12.4%")).toBeInTheDocument()
    // No slider svg
    expect(document.querySelector("svg")).toBeNull()
  })

  it("renders slider with value marker + median tick when peer context present", () => {
    render(
      <MetricWithContext
        label="ROE"
        value={8.8}
        format={(n) => `${n.toFixed(1)}%`}
        peerMedian={12.4}
        peerP5={4.0}
        peerP95={22.0}
        direction="higher_is_better"
      />
    )
    expect(screen.getByText("8.8%")).toBeInTheDocument()
    expect(screen.getByText(/sector median 12\.4%/i)).toBeInTheDocument()
    const svg = document.querySelector("svg")
    expect(svg).not.toBeNull()
    // 1 track + 1 filled bar + 1 median line + 1 value marker (circle)
    expect(svg!.querySelector("circle")).not.toBeNull()
    expect(svg!.querySelectorAll("line").length).toBeGreaterThanOrEqual(1)
  })

  it("includes 5y avg tick when historicalAvg is supplied", () => {
    render(
      <MetricWithContext
        label="ROE"
        value={8.8}
        format={(n) => `${n.toFixed(1)}%`}
        peerMedian={12.4}
        peerP5={4.0}
        peerP95={22.0}
        historicalAvg={11.2}
        direction="higher_is_better"
      />
    )
    const lines = document.querySelectorAll("svg line")
    // median line + historical tick line
    expect(lines.length).toBeGreaterThanOrEqual(2)
  })

  it("tooltip shows on focus with all three values", () => {
    render(
      <MetricWithContext
        label="PE"
        value={22.2}
        format={(n) => `${n.toFixed(1)}x`}
        peerMedian={18.6}
        peerP5={10}
        peerP95={40}
        historicalAvg={20}
        direction="lower_is_better"
      />
    )
    const wrapper = screen.getByLabelText(/PE:/i)
    fireEvent.focus(wrapper)
    const tooltip = screen.getByRole("tooltip")
    expect(tooltip.textContent).toContain("22.2x")
    expect(tooltip.textContent).toContain("18.6x")
    expect(tooltip.textContent).toContain("20.0x")
  })
})
