/**
 * Phase 4 personalization — CollapsibleSection wrapper tests.
 *
 * Pins:
 *   1. Respects defaultExpanded=true (children visible on mount).
 *   2. Respects defaultExpanded=false (children hidden on mount).
 *   3. Click on the header toggles open/closed.
 *   4. Explainer button + body only shown when an explainer string is
 *      passed and the section is open.
 *   5. Children are kept mounted while collapsed (so heavy components
 *      don't lose react-query cache state).
 */
import { describe, expect, it } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"

import CollapsibleSection from "@/components/personalization/CollapsibleSection"

describe("CollapsibleSection", () => {
  it("renders expanded when defaultExpanded=true", () => {
    render(
      <CollapsibleSection
        sectionKey="scenarios"
        number={1}
        defaultExpanded={true}
      >
        <p>scenario body</p>
      </CollapsibleSection>,
    )
    const body = screen.getByText("scenario body").parentElement
    expect(body).toBeTruthy()
    expect(body?.hasAttribute("hidden")).toBe(false)
  })

  it("renders collapsed when defaultExpanded=false but still mounts children", () => {
    render(
      <CollapsibleSection
        sectionKey="scenarios"
        number={1}
        defaultExpanded={false}
      >
        <p>scenario body</p>
      </CollapsibleSection>,
    )
    // Children remain in the DOM — that's important for query cache —
    // but the wrapper is `hidden`.
    const body = screen.getByText("scenario body").parentElement
    expect(body?.hasAttribute("hidden")).toBe(true)
  })

  it("toggles open/closed when the header is clicked", () => {
    render(
      <CollapsibleSection
        sectionKey="scenarios"
        number={2}
        defaultExpanded={false}
      >
        <p>tap to expand</p>
      </CollapsibleSection>,
    )
    const header = screen.getByRole("button", { name: /valuation scenarios/i })
    fireEvent.click(header)
    expect(screen.getByText("tap to expand").parentElement?.hasAttribute("hidden")).toBe(false)
    fireEvent.click(header)
    expect(screen.getByText("tap to expand").parentElement?.hasAttribute("hidden")).toBe(true)
  })

  it("renders the explainer toggle when explainer is provided and open", () => {
    render(
      <CollapsibleSection
        sectionKey="compounded_growth"
        number={3}
        defaultExpanded={true}
        explainer="A plain-English note about CAGR."
      >
        <p>growth body</p>
      </CollapsibleSection>,
    )
    const explainBtn = screen.getByRole("button", { name: /what this means/i })
    fireEvent.click(explainBtn)
    expect(
      screen.getByText(/plain-english note about cagr/i),
    ).toBeTruthy()
  })

  it("does NOT render the explainer toggle when explainer is null", () => {
    render(
      <CollapsibleSection
        sectionKey="compounded_growth"
        number={3}
        defaultExpanded={true}
        explainer={null}
      >
        <p>growth body</p>
      </CollapsibleSection>,
    )
    expect(screen.queryByRole("button", { name: /what this means/i })).toBeNull()
  })

  it("prefixes the heading with its dynamic number", () => {
    render(
      <CollapsibleSection
        sectionKey="dividends"
        number={5}
        defaultExpanded={true}
      >
        <p>dividends body</p>
      </CollapsibleSection>,
    )
    const heading = screen.getByRole("heading", { level: 2 })
    expect(heading.textContent).toMatch(/^5\./)
    expect(heading.textContent).toMatch(/DIVIDENDS/)
  })
})
