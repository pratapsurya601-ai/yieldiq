/**
 * PR-3 (acquisition four-hero retire, 2026-06-04) — render-path invariant
 * guards for AnalysisBody.tsx (authenticated /analysis/[ticker] surface).
 *
 * The bug being prevented: prior to this PR, AnalysisBody mounted FOUR
 * hero-class components (HonestHero, EditorialHero, ConfidenceIndicators,
 * AnalysisHero) and emitted CONTRADICTORY verdict labels within ~800px of
 * scroll (e.g. "Under Review" above "UNDERVALUED" on MUTHOOTFIN /
 * RELIANCE / TCS classes). This file pins the end-state invariant by
 * SOURCE-TEXT inspection so a future refactor that re-introduces any of
 * the retired imports fails CI before it ships.
 *
 * Test mode: source-text. AnalysisBody itself is too heavy to mount in
 * jsdom (it pulls react-query, tanstack store, framer-motion, ~50
 * dynamic components). The grep guards are intentionally STRICT so a
 * lazy `// import EditorialHero from ...` style re-introduction still
 * trips the test.
 */

import { describe, it, expect } from "vitest"
import { readFileSync } from "node:fs"
import path from "node:path"

const BODY = path.resolve(
  __dirname,
  "../src/app/(app)/analysis/[ticker]/AnalysisBody.tsx",
)
const body = readFileSync(BODY, "utf-8")

/** Strip /* ... *​/ block comments and // line comments so retire-
 * rationale text that happens to mention a forbidden tag name
 * doesn't trip the JSX-mount guards. Imperfect by design — we err
 * on the side of false negatives (test passes when it should fail)
 * for in-string mentions, but JSX angle-brackets inside strings are
 * vanishingly rare in this file. */
function stripBlockComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1")
}

describe("AnalysisBody — four-hero retire invariant (PR-3)", () => {
  it("imports HonestHero", () => {
    expect(body).toMatch(
      /import\s+HonestHero\s+from\s+["']@\/components\/analysis\/HonestHero["']/,
    )
  })

  it("mounts <HonestHero ...>", () => {
    expect(body).toMatch(/<HonestHero\b/)
  })

  it("does NOT import the full EditorialHero (only the demoted band)", () => {
    // The demoted band (EditorialHeroBand) is allowed. The full
    // 3-column EditorialHero is forbidden in this file.
    const importLines = body.match(
      /import[^;]*from\s+["']@\/components\/analysis\/EditorialHero["'][^;]*/g,
    )
    expect(importLines).toBeNull()
    // And it must not be mounted as a JSX element. Strip block
    // comments first so a "<EditorialHero ..." retire-rationale
    // inside a /* */ doesn't trip the guard.
    const codeOnly = stripBlockComments(body)
    expect(codeOnly).not.toMatch(/<EditorialHero[\s/>]/)
  })

  it("imports and mounts <EditorialHeroBand>", () => {
    expect(body).toMatch(
      /import\s+EditorialHeroBand\s+from\s+["']@\/components\/analysis\/EditorialHeroBand["']/,
    )
    expect(body).toMatch(/<EditorialHeroBand\b/)
  })

  it("does NOT import or mount the dead-code AnalysisHero", () => {
    expect(body).not.toMatch(
      /import[^;]*from\s+["']@\/components\/analysis\/AnalysisHero["']/,
    )
    expect(stripBlockComments(body)).not.toMatch(/<AnalysisHero[\s/>]/)
  })

  it("does NOT import or mount ConfidenceIndicators (absorbed inline)", () => {
    expect(body).not.toMatch(
      /import[^;]*from\s+["']@\/components\/analysis\/ConfidenceIndicators["']/,
    )
    expect(stripBlockComments(body)).not.toMatch(/<ConfidenceIndicators[\s/>]/)
  })

  it("still mounts MobileScoreStrip (spec §6 mobile carrier)", () => {
    expect(body).toMatch(/<MobileScoreStrip\b/)
  })

  it("retains the inline ConfidenceMethodologyBlock absorption", () => {
    // The three score chips + analyst-opinion banner survive the
    // retire as an in-file helper component — data is preserved,
    // the duplicate "fourth hero" surface is not.
    expect(body).toMatch(/function ConfidenceMethodologyBlock\b/)
    expect(body).toMatch(/<ConfidenceMethodologyBlock\b/)
  })
})
