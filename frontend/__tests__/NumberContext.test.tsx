import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import NumberContext from "@/components/common/NumberContext"

describe("NumberContext — muted context caption", () => {
  it("renders label and value together", () => {
    render(<NumberContext label="vs sector median" value="10.9%" />)
    const el = screen.getByTestId("number-context")
    expect(el.textContent).toBe("vs sector median 10.9%")
  })

  it("renders rupee references", () => {
    render(<NumberContext label="vs price" value="₹746" />)
    expect(screen.getByTestId("number-context").textContent).toBe(
      "vs price ₹746",
    )
  })

  it("self-hides when value is null", () => {
    render(<NumberContext label="5y avg" value={null} />)
    expect(screen.queryByTestId("number-context")).toBeNull()
  })

  it("self-hides when value is empty or the em-dash fallback", () => {
    render(<NumberContext label="5y avg" value="" />)
    expect(screen.queryByTestId("number-context")).toBeNull()
    render(<NumberContext label="5y avg" value={"—"} />)
    expect(screen.queryByTestId("number-context")).toBeNull()
  })
})
