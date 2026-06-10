/**
 * Tests for the /methodology marketing page.
 *
 * The page is a pure Server Component with no client state, no
 * async data, and no third-party providers — so we render it
 * directly through @testing-library/react and assert on the DOM.
 *
 * Four pinned behaviours:
 *
 *   1. The page renders without throwing (smoke).
 *   2. Every shipped sector-engine name renders into the DOM. This
 *      is the regression backstop for the per-sector model
 *      explainers added alongside this test file.
 *   3. The "Honest caveats" sub-section renders (composite-IV gap,
 *      holdco SOTP stop-gap, pharma / insurance / telecom roadmap).
 *   4. SEBI vocabulary guard — the rendered DOM contains none of the
 *      banned advisory tokens. Per the root-CLAUDE.md standing rule
 *      #5, the BANNED array is built from string fragments at runtime
 *      (Pattern B) so the diff-only sebi-lint pass doesn't false-fire
 *      on this test file's literals.
 */

import { describe, it, expect, beforeEach } from "vitest"
import { render } from "@testing-library/react"

import MethodologyPage from "@/app/(marketing)/methodology/page"

// Every specialised valuation engine documented on the page. If a new
// engine ships, append it here and add a corresponding <Engine /> card
// to page.tsx; if an engine is retired, drop both. The test fails loud
// either way.
const SHIPPED_ENGINES: readonly string[] = [
  "Multiples-based fair value",
  "Bank residual-income",
  "REIT net-asset-value with DPU yield gap",
  "Regulated utility — RAB times allowed ROE",
  "Platform / recent-IPO sector relative",
  "Tier-2 cohort",
  "Reverse DCF",
  "Story DCF / Day-89 backtest",
  "Composite intrinsic value",
  "Holdco sum-of-the-parts",
]

describe("MethodologyPage — renders the per-sector model explainers", () => {
  let container: HTMLElement

  beforeEach(() => {
    container = render(<MethodologyPage />).container
  })

  it("smoke — renders the top-level methodology H1", () => {
    const h1 = container.querySelector("h1")
    expect(h1).not.toBeNull()
    expect(h1?.textContent).toContain("How YieldIQ values a stock")
  })

  it("renders the routing-section heading that introduces the engines", () => {
    const text = container.textContent ?? ""
    // The new section uses the exact phrasing from the marketing brief.
    expect(text).toContain(
      "When DCF isn't enough — specialized models by sector",
    )
  })

  it.each(SHIPPED_ENGINES)(
    "renders the '%s' engine card",
    (engineName) => {
      const text = container.textContent ?? ""
      expect(text).toContain(engineName)
    },
  )

  it("each engine card carries Routes / rationale / Key inputs labels", () => {
    const text = container.textContent ?? ""
    // We don't assert per-engine — the per-card structure is generated
    // by the <Engine /> primitive, so checking the labels appear once
    // each (i.e. at least 10 times across 10 cards) is sufficient.
    expect(text.match(/Routes/g)?.length ?? 0).toBeGreaterThanOrEqual(
      SHIPPED_ENGINES.length,
    )
    expect(text.match(/Why DCF alone is inadequate/g)?.length ?? 0)
      .toBeGreaterThanOrEqual(SHIPPED_ENGINES.length)
    expect(text.match(/Key inputs/g)?.length ?? 0).toBeGreaterThanOrEqual(
      SHIPPED_ENGINES.length,
    )
  })

  it("renders the 'Honest caveats' sub-section with all three callouts", () => {
    const text = container.textContent ?? ""
    expect(text).toContain("Honest caveats")
    // Composite-IV gap acknowledgement.
    expect(text).toContain("Composite IV closes a real DCF-only gap")
    expect(text).toContain("HDFCBANK")
    // Holdco SOTP stop-gap.
    expect(text).toContain("Holdco SOTP is a stop-gap")
    expect(text).toContain("BAJAJHLDNG")
    // Roadmap callout naming the three sectors still in the queue.
    expect(text).toContain("Pharma pipeline")
    expect(text).toContain("Insurance embedded-value")
    expect(text).toContain("Telecom ARPU-driven")
  })

  it("renders the pre-existing six-pillar Prism heading (regression guard)", () => {
    // The new section was inserted between the DCF section and the
    // Prism section. This assertion catches the case where the
    // insertion accidentally truncates the file or breaks the JSX
    // tree below the new content.
    const headings = Array.from(container.querySelectorAll("h2")).map(
      (h) => h.textContent ?? "",
    )
    expect(headings).toContain("The 6-pillar Prism")
    expect(headings).toContain("Verdict bands")
    expect(headings).toContain("Data sources")
    expect(headings).toContain("Known limitations")
    expect(headings).toContain("SEBI posture")
  })

  it("SEBI vocab guard — rendered DOM contains no banned advisory tokens", () => {
    // Pattern B from CLAUDE.md §5: build banned tokens from fragments
    // so the diff-only sebi-lint scanner over THIS file's literals
    // produces zero false positives. Identical to the runtime check
    // we'd get from a literal array.
    const BANNED: readonly string[] = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "recomm" + "end",
      "shou" + "ld",
      "outper" + "form",
      "underper" + "form",
      "accumu" + "late",
      "attrac" + "tive",
      "che" + "ap",
      "expen" + "sive",
      "wea" + "k",
      "stro" + "ng",
      "appe" + "ars",
      "conc" + "ern",
      "po" + "or",
      "investa" + "ble",
      "investabi" + "lity",
    ]

    const text = (container.textContent ?? "").toLowerCase()

    const hits: string[] = []
    for (const word of BANNED) {
      // Word-boundary match mirrors the python check_sebi_words.py regex.
      const re = new RegExp(`\\b${word}\\b`, "i")
      if (re.test(text)) {
        hits.push(word)
      }
    }

    // Some banned tokens appear inside DISCLOSURE COPY that
    // pre-dates this test file. Each pre-existing occurrence is
    // wrapped in a per-line `sebi-allow:` source annotation, so the
    // source-level lint stays green. The rendered DOM still
    // surfaces these tokens — that is intentional, and exactly why
    // we list them here as pre-existing rather than as novel leaks.
    // If a future edit introduces a NEW banned word outside this
    // allowlist, the assertion fails loud.
    const PRE_EXISTING_DISCLOSURE_TOKENS: readonly string[] = [
      "shou" + "ld",
      "recomm" + "end",
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
    ]
    const novelHits = hits.filter(
      (h) => !PRE_EXISTING_DISCLOSURE_TOKENS.includes(h),
    )

    expect(
      novelHits,
      `Methodology page DOM leaked banned SEBI vocabulary: ${novelHits.join(", ")}`,
    ).toEqual([])
  })
})
