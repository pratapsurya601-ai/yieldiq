/**
 * Quick-wins batch (2026-06-10 competitor audit follow-up) — pin that
 * the `news` section is force-expanded by default regardless of its
 * personalization-derived slot. The brief: news sits at slot 9 under
 * the DEFAULT order and slots 2 / 7 / 8 under speculator / value /
 * growth — i.e. collapsed for the modal user even though recent
 * filings are one of the highest-signal sections on the page.
 *
 * Test mode: source-text. AnalysisBody is too heavy to mount in jsdom
 * (react-query, tanstack store, framer-motion, ~50 dynamic components),
 * so we pin the override expression literally. A regression that drops
 * the news override — leaving news collapsed for most users again —
 * trips this test before it ships.
 */

import { describe, it, expect } from "vitest"
import { readFileSync } from "node:fs"
import path from "node:path"

const BODY = path.resolve(
  __dirname,
  "../src/app/(app)/analysis/[ticker]/AnalysisBody.tsx",
)
const body = readFileSync(BODY, "utf-8")

describe("AnalysisBody — news section force-expanded (quick-wins batch)", () => {
  it("force-expands the news section regardless of its slot", () => {
    // The render loop must include `key === "news"` in the
    // defaultExpanded predicate so news is open on first paint even
    // when the active personalization style would normally collapse it.
    expect(body).toMatch(
      /const\s+defaultExpanded\s*=\s*idx\s*<\s*5\s*\|\|\s*key\s*===\s*"news"/,
    )
  })
})
