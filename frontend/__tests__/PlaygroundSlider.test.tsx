import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import PlaygroundSlider from "@/app/(app)/analysis/[ticker]/playground/PlaygroundSlider"
import type { SliderDef } from "@/app/(app)/analysis/[ticker]/playground/PlaygroundBody"

const DEF: SliderDef = {
  key: "wacc",
  label: "Discount Rate (WACC)",
  min: 0.06,
  max: 0.15,
  step: 0.001,
  defaultValue: 0.11,
  tooltip: "Higher WACC = more skeptical = lower fair value.",
  paidOnly: false,
}

describe("PlaygroundSlider", () => {
  it("renders the current value formatted as a percent", () => {
    render(<PlaygroundSlider def={DEF} value={0.11} onChange={() => {}} locked={false} />)
    expect(screen.getByText("11.0%")).toBeTruthy()
  })

  it("fires onChange when the user drags the slider", () => {
    const onChange = vi.fn()
    render(<PlaygroundSlider def={DEF} value={0.11} onChange={onChange} locked={false} />)
    const input = screen.getByRole("slider") as HTMLInputElement
    fireEvent.change(input, { target: { value: "0.13" } })
    expect(onChange).toHaveBeenCalledWith(0.13)
  })

  it("shows a reset button only when value differs from default", () => {
    const { rerender } = render(
      <PlaygroundSlider def={DEF} value={0.11} onChange={() => {}} locked={false} />,
    )
    expect(screen.queryByText("reset")).toBeNull()

    rerender(<PlaygroundSlider def={DEF} value={0.13} onChange={() => {}} locked={false} />)
    expect(screen.getByText("reset")).toBeTruthy()
  })

  it("reset button restores the default value", () => {
    const onChange = vi.fn()
    render(<PlaygroundSlider def={DEF} value={0.13} onChange={onChange} locked={false} />)
    fireEvent.click(screen.getByText("reset"))
    expect(onChange).toHaveBeenCalledWith(0.11)
  })

  it("disables the input when locked", () => {
    render(<PlaygroundSlider def={DEF} value={0.11} onChange={() => {}} locked={true} />)
    const input = screen.getByRole("slider") as HTMLInputElement
    expect(input.disabled).toBe(true)
    // Paywall hint is rendered
    expect(screen.getByText(/Paid feature/i)).toBeTruthy()
  })

  it("toggles the tooltip when the help button is clicked", () => {
    render(<PlaygroundSlider def={DEF} value={0.11} onChange={() => {}} locked={false} />)
    expect(screen.queryByText(DEF.tooltip)).toBeNull()
    const helpBtn = screen.getByRole("button", { name: /Explain Discount Rate/i })
    fireEvent.click(helpBtn)
    expect(screen.getByText(DEF.tooltip)).toBeTruthy()
  })
})
