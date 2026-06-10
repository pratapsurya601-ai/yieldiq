/**
 * Mobile-PR-A (audit `tmp/mobile_audit_2026_06_10.md`) regression guards
 * for the three CSS-only fixes that ship in this PR:
 *
 *   Issue 1 (P0): ValuationGrid scenario row must stack on mobile so the
 *                 ₹ currency strings do not wrap mid-number at 360px.
 *   Issue 3 (P1): /analysis/[ticker] page root must carry a bottom
 *                 padding that clears the fixed mobile bottom nav so the
 *                 SEBI disclaimer in TrustFooter is fully visible. The
 *                 file already exists at the path checked here — if a
 *                 future refactor moves it, this guard fails loudly.
 *   Issue 4 (P1): InsightCards sentiment-segment row must NOT use a flat
 *                 grid-cols-5 — it must widen progressively from 2 cols
 *                 on the smallest viewports up to 5 cols on sm+.
 *
 * These are static-content assertions (read the source file off disk,
 * assert the responsive class names are present) rather than DOM
 * snapshots because InsightCards is a heavy default-export with many
 * required props and grid-cols-5 lives inside a conditional analyst-
 * consensus branch — rendering it would require a deep API-shape fake
 * and would couple the test to unrelated render logic.
 *
 * ValuationGrid IS rendered through the DOM to assert the rendered
 * class string, because it has a clean public prop shape.
 */

import { describe, it, expect } from "vitest"
import { render } from "@testing-library/react"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import ValuationGrid from "@/components/analysis/ValuationGrid"

const repoFrontend = join(__dirname, "..")

describe("Mobile-PR-A — Issue 1: ValuationGrid stacks on mobile", () => {
  it("renders the scenario row with grid-cols-1 md:grid-cols-3 (no flat grid-cols-3)", () => {
    const { container } = render(
      <ValuationGrid
        bear={{ fair_value: 142500, mos_pct: -12.3 }}
        base={{ fair_value: 165000, mos_pct: 5.4 }}
        bull={{ fair_value: 198000, mos_pct: 22.1 }}
        currentPrice={156000}
        currency="INR"
        ticker="HDFCBANK.NS"
      />,
    )
    // Find the inner grid that holds the three scenario cards.
    const grid = container.querySelector('div[class*="grid-cols-"]')
    expect(grid).not.toBeNull()
    const cls = grid?.getAttribute("class") ?? ""
    // P0 invariant: mobile must stack (1 col). Then 3 cols at md+.
    expect(cls).toContain("grid-cols-1")
    expect(cls).toContain("md:grid-cols-3")
    // The pre-fix flat literal would have been plain "grid-cols-3" with
    // no responsive prefix — assert that pattern is gone.
    expect(cls).not.toMatch(/(^|\s)grid-cols-3(\s|$)/)
  })
})

describe("Mobile-PR-A — Issue 3: analysis page clears mobile bottom nav", () => {
  it("page.tsx root carries pb-[…] safe-area padding with md:pb-0", () => {
    const pagePath = join(
      repoFrontend,
      "src/app/(app)/analysis/[ticker]/page.tsx",
    )
    const source = readFileSync(pagePath, "utf8")
    // The safe-area calc is the canonical pattern (Navbar.tsx uses the
    // same env(safe-area-inset-bottom) primitive). Asserting on the
    // calc lets us tolerate spacing rem tweaks (4rem vs 5rem) while
    // still failing if the safe-area-aware wrapper is dropped entirely.
    expect(source).toMatch(
      /pb-\[calc\(env\(safe-area-inset-bottom\)\+\d+(\.\d+)?rem\)\]/,
    )
    expect(source).toContain("md:pb-0")
  })
})

describe("Mobile-PR-A — Issue 4: InsightCards sentiment row widens progressively", () => {
  it("sentiment grid uses grid-cols-2 sm:grid-cols-3 md:grid-cols-5 (not flat grid-cols-5)", () => {
    const insightPath = join(
      repoFrontend,
      "src/components/analysis/InsightCards.tsx",
    )
    const source = readFileSync(insightPath, "utf8")
    // The mobile-friendly class string must be present verbatim — this
    // is exactly the literal Tailwind has to see to JIT all five
    // breakpoint variants.
    expect(source).toContain(
      "grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-1 mt-2 text-[11px]",
    )
    // And the pre-fix flat literal must be gone. Match only the exact
    // pre-fix opener so other (legitimate) grid-cols-5 usages on
    // larger card grids elsewhere in the file are not false-positives.
    expect(source).not.toContain(
      'className="grid grid-cols-5 gap-1 mt-2 text-[11px]',
    )
  })
})
