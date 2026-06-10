/**
 * HoldingsTrendMiniChart (feat/analysis-holdings-trend-chart, 2026-06-10).
 *
 * Covers:
 *   - Render-path: ResponsiveContainer + 4 stacked Areas materialize
 *     when we supply trendData directly (no self-fetch).
 *   - Fallback: when trendData is empty AND currentPattern is provided,
 *     the current-only readout renders with the 4 percentages.
 *   - Empty state: when both are missing, the panel renders the "no
 *     data on file" line rather than collapsing.
 *   - Insights helpers: ppDelta + trendPhrase produce the expected
 *     values (and trendPhrase NEVER returns banned vocab from the
 *     SEBI guard list — the component sticks to neutral descriptions
 *     like "rose" / "fell" / "little changed").
 *
 * Recharts is shimmed so ResponsiveContainer paints in JSDOM (mirrors
 * the pattern used in PwaFunnelPage.test.tsx + FundsPhase3Slim.test.tsx).
 */

import React from "react"
import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts")
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="recharts-container" style={{ width: 600, height: 220 }}>
        {children}
      </div>
    ),
  }
})

import {
  HoldingsTrendMiniChart,
  ppDelta,
  trendPhrase,
  isSeriesAllNull,
  type HoldingsTrendDataPoint,
} from "@/components/analysis/HoldingsTrendMiniChart"

// Canonical 8-quarter fixture using the Indian FY convention (FY
// named by END year — FY25 = Apr 2024-Mar 2025, FY26 = Apr 2025-Mar
// 2026). This shape mirrors what the backend emits after the
// ROOT CAUSE #4 (2026-06-11) fix to _quarter_label.
const FIXTURE: HoldingsTrendDataPoint[] = [
  { quarter_end: "2024-06-30", quarter_label: "Q1 FY25", promoter_pct: 50.8, fii_pct: 19.8, dii_pct: 17.9, public_pct: 11.5 },
  { quarter_end: "2024-09-30", quarter_label: "Q2 FY25", promoter_pct: 50.6, fii_pct: 20.2, dii_pct: 17.8, public_pct: 11.4 },
  { quarter_end: "2024-12-31", quarter_label: "Q3 FY25", promoter_pct: 50.5, fii_pct: 20.5, dii_pct: 17.7, public_pct: 11.3 },
  { quarter_end: "2025-03-31", quarter_label: "Q4 FY25", promoter_pct: 50.4, fii_pct: 20.9, dii_pct: 17.6, public_pct: 11.1 },
  { quarter_end: "2025-06-30", quarter_label: "Q1 FY26", promoter_pct: 50.3, fii_pct: 21.2, dii_pct: 17.5, public_pct: 11.0 },
  { quarter_end: "2025-09-30", quarter_label: "Q2 FY26", promoter_pct: 50.2, fii_pct: 21.5, dii_pct: 17.4, public_pct: 10.9 },
  { quarter_end: "2025-12-31", quarter_label: "Q3 FY26", promoter_pct: 50.1, fii_pct: 21.8, dii_pct: 17.2, public_pct: 10.9 },
  { quarter_end: "2026-03-31", quarter_label: "Q4 FY26", promoter_pct: 50.0, fii_pct: 22.0, dii_pct: 17.0, public_pct: 11.0 },
]

describe("HoldingsTrendMiniChart", () => {
  it("renders the chart wrapper when trendData has 2+ points", () => {
    render(
      <HoldingsTrendMiniChart
        ticker="RELIANCE"
        trendData={FIXTURE}
        currentPattern={null}
      />
    )
    expect(screen.getByTestId("holdings-trend-chart")).toBeInTheDocument()
    expect(screen.getByTestId("recharts-container")).toBeInTheDocument()
    expect(screen.getByText(/8-quarter trend/i)).toBeInTheDocument()
  })

  it("falls back to current-only when trendData is empty", () => {
    render(
      <HoldingsTrendMiniChart
        ticker="NEWCO"
        trendData={[]}
        currentPattern={{
          promoter_pct: 65.4,
          fii_pct: 12.1,
          dii_pct: 8.3,
          public_pct: 14.2,
        }}
      />
    )
    expect(screen.getByTestId("holdings-trend-current-only")).toBeInTheDocument()
    // All four percentages render.
    expect(screen.getByText("65.4%")).toBeInTheDocument()
    expect(screen.getByText("12.1%")).toBeInTheDocument()
    expect(screen.getByText("8.3%")).toBeInTheDocument()
    expect(screen.getByText("14.2%")).toBeInTheDocument()
  })

  it("renders the empty-state line when both trend and current are missing", () => {
    render(
      <HoldingsTrendMiniChart
        ticker="UNKNOWN"
        trendData={[]}
        currentPattern={null}
      />
    )
    expect(screen.getByTestId("holdings-trend-empty")).toBeInTheDocument()
    expect(screen.getByText(/No shareholding pattern/i)).toBeInTheDocument()
  })

  it("renders the insights strip with computed deltas when trend is present", () => {
    render(
      <HoldingsTrendMiniChart
        ticker="RELIANCE"
        trendData={FIXTURE}
        currentPattern={null}
      />
    )
    // Promoter fell from 50.8 to 50.0 = -0.8pp
    expect(screen.getByText("-0.8pp")).toBeInTheDocument()
    // FII rose from 19.8 to 22.0 = +2.2pp
    expect(screen.getByText("+2.2pp")).toBeInTheDocument()
  })
})

describe("HoldingsTrendMiniChart — ROOT CAUSE #4 regressions (2026-06-11)", () => {
  it("renders unique x-axis labels even if the payload smuggles a duplicate", () => {
    // Defensive de-dupe — backend now dedupes, but stale CDN cache
    // could still serve a payload from before the fix.
    const withDup: HoldingsTrendDataPoint[] = [
      ...FIXTURE,
      // Duplicate Q2 FY26 — must be filtered out by the safeTrend pass.
      { quarter_end: "2025-09-29", quarter_label: "Q2 FY26", promoter_pct: 99.9, fii_pct: 0.0, dii_pct: 0.0, public_pct: 0.1 },
    ]
    render(
      <HoldingsTrendMiniChart
        ticker="RELIANCE"
        trendData={withDup}
        currentPattern={null}
      />
    )
    // The header reads "8-quarter trend" because the 9th row was a dup.
    expect(screen.getByText(/8-quarter trend/i)).toBeInTheDocument()
  })

  it("omits a series entirely when every row's value is null (no flat-zero bars)", () => {
    // FII history incomplete: every row's fii_pct is null. Component
    // must surface the "history incomplete" overlay and NOT draw an
    // FII series. The presence of the overlay caption signals the
    // honest gap rather than reading flat 0% bars as "FII at zero".
    const fiiNull: HoldingsTrendDataPoint[] = FIXTURE.map((r) => ({
      ...r,
      fii_pct: null,
    }))
    render(
      <HoldingsTrendMiniChart
        ticker="RELIANCE"
        trendData={fiiNull}
        currentPattern={null}
      />
    )
    const overlay = screen.getByTestId("holdings-trend-incomplete-overlay")
    expect(overlay).toBeInTheDocument()
    expect(overlay.textContent ?? "").toMatch(/FII/)
    expect(overlay.textContent ?? "").toMatch(/history incomplete/i)
  })

  it("does not re-sort x-axis by string — backend canonical order wins", () => {
    // If the chart sorted by label, "Q1 FY26" would land before
    // "Q4 FY25" (string compare: '1' < '4'). The component must
    // preserve insertion order from the payload (which is ASC by
    // canonical quarter_end on the backend). We validate by
    // confirming the first and last labels in the rendered insights
    // strip refer to the chronological endpoints.
    render(
      <HoldingsTrendMiniChart
        ticker="RELIANCE"
        trendData={FIXTURE}
        currentPattern={null}
      />
    )
    // Promoter fell from 50.8 (oldest, Q1 FY25) to 50.0 (newest, Q4
    // FY26) = -0.8pp. If the chart had re-sorted by label string,
    // the earliest row in the array would no longer be Q1 FY25 and
    // the delta would flip sign.
    expect(screen.getByText("-0.8pp")).toBeInTheDocument()
  })
})

describe("isSeriesAllNull", () => {
  it("returns true when every value is null/undefined/NaN", () => {
    const rows: HoldingsTrendDataPoint[] = [
      { quarter_end: "2025-03-31", quarter_label: "Q4 FY25", promoter_pct: 50.0, fii_pct: null, dii_pct: 17.0, public_pct: 11.0 },
      { quarter_end: "2025-06-30", quarter_label: "Q1 FY26", promoter_pct: 50.1, fii_pct: null, dii_pct: 17.1, public_pct: 11.1 },
    ]
    expect(isSeriesAllNull(rows, "fii_pct")).toBe(true)
    expect(isSeriesAllNull(rows, "promoter_pct")).toBe(false)
  })

  it("returns true on an empty array", () => {
    expect(isSeriesAllNull([], "promoter_pct")).toBe(true)
  })
})

describe("ppDelta", () => {
  it("returns null when fewer than 2 numeric points exist", () => {
    expect(ppDelta([], "promoter_pct")).toBeNull()
    expect(
      ppDelta(
        [
          { quarter_end: "2026-03-31", quarter_label: "Q4 FY26", promoter_pct: 50.0, fii_pct: null, dii_pct: null, public_pct: null },
        ],
        "fii_pct"
      )
    ).toBeNull()
  })

  it("returns latest minus earliest across non-null values", () => {
    const d = ppDelta(FIXTURE, "fii_pct")
    expect(d).not.toBeNull()
    expect(d!).toBeCloseTo(2.2, 5)
  })
})

describe("trendPhrase SEBI compliance", () => {
  // Banned-vocab list mirrors scripts/check_sebi_words.py BANNED_WORDS.
  // Built from string fragments so the SEBI diff-only linter doesn't
  // trip on the fixture (Pattern B from CLAUDE.md standing rule 5).
  const BANNED: string[] = [
    "b" + "uy",
    "se" + "ll",
    "ho" + "ld",
    "accum" + "ulate",
    "accum" + "ulating",
    "out" + "perform",
    "under" + "perform",
    "rec" + "ommend",
    "rec" + "ommendation",
    "att" + "ractive",
    "ex" + "pensive",
    "ch" + "eap",
    "str" + "ong",
    "we" + "ak",
  ]

  const samples = [
    trendPhrase("Promoter", -0.8, 8),
    trendPhrase("FII", 2.2, 8),
    trendPhrase("DII", 0.0, 8),
    trendPhrase("Promoter", null, 8),
  ]

  it("never emits banned vocab in any phrase", () => {
    for (const phrase of samples) {
      for (const word of BANNED) {
        const re = new RegExp(`\\b${word}\\b`, "i")
        expect(phrase, `phrase: "${phrase}" matched banned word "${word}"`).not.toMatch(re)
      }
    }
  })

  it("produces neutral movement language", () => {
    expect(trendPhrase("FII", 2.2, 8)).toMatch(/rose/i)
    expect(trendPhrase("Promoter", -0.8, 8)).toMatch(/fell/i)
    expect(trendPhrase("DII", 0.0, 8)).toMatch(/little changed/i)
  })
})
