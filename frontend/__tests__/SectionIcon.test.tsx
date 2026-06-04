/**
 * SectionIcon smoke tests.
 *
 * Asserts every name in the union renders a non-null icon and the
 * className override propagates to the underlying SVG.
 */
import { describe, it, expect } from "vitest"
import { render } from "@testing-library/react"

import SectionIcon, {
  type SectionIconName,
} from "@/components/common/SectionIcon"

const ALL_NAMES: SectionIconName[] = [
  "moat",
  "valuation",
  "risk-flag",
  "strengths",
  "dividends",
  "analyst",
  "insider",
  "promoter",
  "quality",
  "growth",
]

describe("SectionIcon", () => {
  it("renders a non-null icon for every name in the union", () => {
    for (const name of ALL_NAMES) {
      const { container, unmount } = render(<SectionIcon name={name} />)
      const svg = container.querySelector("svg")
      expect(svg, `expected svg for "${name}"`).not.toBeNull()
      unmount()
    }
  })

  it("accepts a className override that propagates to the svg", () => {
    const { container } = render(
      <SectionIcon name="moat" className="h-8 w-8 text-success" />,
    )
    const svg = container.querySelector("svg")
    expect(svg).not.toBeNull()
    expect(svg?.getAttribute("class")).toContain("h-8")
    expect(svg?.getAttribute("class")).toContain("text-success")
  })

  it("defaults to h-4 w-4 when className is omitted", () => {
    const { container } = render(<SectionIcon name="valuation" />)
    const svg = container.querySelector("svg")
    expect(svg?.getAttribute("class")).toContain("h-4")
    expect(svg?.getAttribute("class")).toContain("w-4")
  })
})
