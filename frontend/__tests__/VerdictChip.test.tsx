/**
 * Day-77 (2026-05-22) — VerdictChip smoke tests.
 *
 * Pins the rendered label and palette class for every Verdict value
 * defined in `@/types/api`, including the Day-61 `low_confidence`
 * variant. Catches the kind of regression the source-text greps in
 * `backend/tests/test_day*.py` cannot — e.g. a refactor that drops a
 * verdict case from the LABELS map, or a palette swap that removes
 * the slate hue introduced for the verdict-pill confidence gate.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import VerdictChip from "@/components/analysis/VerdictChip"
import type { Verdict } from "@/types/api"

const CASES: { verdict: Verdict; label: string; paletteHint: string }[] = [
  { verdict: "undervalued", label: "Below Fair Value", paletteHint: "blue" },
  { verdict: "fairly_valued", label: "Near Fair Value", paletteHint: "gray" },
  { verdict: "overvalued", label: "Above Fair Value", paletteHint: "amber" },
  { verdict: "avoid", label: "High Risk", paletteHint: "red" },
  { verdict: "data_limited", label: "Data Limited", paletteHint: "gray" },
  { verdict: "unavailable", label: "Unavailable", paletteHint: "gray" },
  // Day-61 verdict-pill confidence gate — slate, neutral.
  { verdict: "low_confidence", label: "Low Confidence", paletteHint: "slate" },
]

describe("VerdictChip", () => {
  for (const { verdict, label, paletteHint } of CASES) {
    it(`renders ${verdict} with label "${label}" and ${paletteHint} palette`, () => {
      const { container } = render(<VerdictChip verdict={verdict} />)
      expect(screen.getByText(label)).toBeInTheDocument()
      const chip = container.querySelector("span")
      expect(chip).not.toBeNull()
      // Class palette assertion — pinning the hue family (not the exact
      // shade) keeps the test stable across Tailwind opacity tweaks but
      // still catches a wholesale palette swap.
      expect(chip!.className).toMatch(new RegExp(paletteHint))
    })
  }

  it("respects the size prop (sm/md/lg)", () => {
    const { container, rerender } = render(
      <VerdictChip verdict="undervalued" size="sm" />,
    )
    expect(container.querySelector("span")!.className).toMatch(/text-xs/)
    rerender(<VerdictChip verdict="undervalued" size="lg" />)
    expect(container.querySelector("span")!.className).toMatch(/text-base/)
  })
})
