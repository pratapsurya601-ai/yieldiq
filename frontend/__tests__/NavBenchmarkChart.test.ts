import { describe, it, expect } from "vitest"

import {
  buildChartData,
  isoYearsBefore,
} from "@/app/(app)/funds/[scheme_code]/NavBenchmarkChart"
import type { FundBenchmarkPoint, FundNavPoint } from "@/types/api"

// ── Fixtures ──────────────────────────────────────────────────────────
//
// Mirror the live API shape for scheme 147946: ~daily NAV points (every
// ~3 days here for compactness) spanning 5 years 2021-05-18 → 2026-06-15.
// The bug under test: a window filter that took the last N *rows* instead
// of the last N *years* rendered only ~6 months for the 5Y toggle.

function buildNavSeries(
  startIso: string,
  endIso: string,
  stepDays: number,
  startNav: number,
): FundNavPoint[] {
  const out: FundNavPoint[] = []
  const end = new Date(`${endIso}T00:00:00Z`)
  let cur = new Date(`${startIso}T00:00:00Z`)
  let nav = startNav
  while (cur.getTime() <= end.getTime()) {
    out.push({
      nav_date: cur.toISOString().slice(0, 10),
      nav: Number(nav.toFixed(3)),
      aum_cr: null,
    })
    nav *= 1.0015 // gentle uptrend
    cur = new Date(cur.getTime() + stepDays * 24 * 3600 * 1000)
  }
  return out
}

const NAV = buildNavSeries("2021-05-18", "2026-06-15", 3, 18.08)
const LAST_DATE = NAV[NAV.length - 1].nav_date

describe("isoYearsBefore", () => {
  it("subtracts whole calendar years", () => {
    expect(isoYearsBefore("2026-06-15", 5)).toBe("2021-06-15")
    expect(isoYearsBefore("2026-06-15", 1)).toBe("2025-06-15")
    expect(isoYearsBefore("2026-06-15", 10)).toBe("2016-06-15")
  })
})

describe("buildChartData — window selection", () => {
  it("5Y selects a ~5-year window, not the last few rows (regression)", () => {
    const { data, spanYears, truncatedToInception } = buildChartData(NAV, [], 5)
    expect(data.length).toBeGreaterThan(0)
    // First visible date must be ~5y before the last date, NOT a recent
    // few-month slice. The old slice(-60) bug started at ~2025-12.
    expect(data[0].date >= "2021-05-18").toBe(true)
    expect(data[0].date <= "2021-07-01").toBe(true)
    expect(data[data.length - 1].date).toBe(LAST_DATE)
    expect(spanYears).toBeGreaterThanOrEqual(4.5)
    // 5y of held data is exactly available, so not "since inception".
    expect(truncatedToInception).toBe(false)
  })

  it("1Y selects only the trailing year", () => {
    const { data, spanYears } = buildChartData(NAV, [], 1)
    expect(data[0].date >= "2025-06-15").toBe(true)
    expect(data[data.length - 1].date).toBe(LAST_DATE)
    expect(spanYears).toBeGreaterThanOrEqual(0.9)
    expect(spanYears).toBeLessThanOrEqual(1.1)
  })

  it("3Y selects roughly three trailing years", () => {
    const { data, spanYears } = buildChartData(NAV, [], 3)
    expect(data[0].date >= "2023-06-15").toBe(true)
    expect(data[0].date <= "2023-07-15").toBe(true)
    expect(spanYears).toBeGreaterThanOrEqual(2.8)
    expect(spanYears).toBeLessThanOrEqual(3.1)
  })

  it("10Y on a 5-year history degrades to since-inception (capped)", () => {
    const { data, spanYears, truncatedToInception } = buildChartData(
      NAV,
      [],
      10,
    )
    expect(truncatedToInception).toBe(true)
    // Capped to held data — does NOT render an empty/padded 10Y.
    expect(data[0].date).toBe("2021-05-18")
    expect(data[data.length - 1].date).toBe(LAST_DATE)
    expect(spanYears).toBeGreaterThanOrEqual(4.5)
    expect(spanYears).toBeLessThanOrEqual(5.2)
  })
})

describe("buildChartData — indexing / rebasing", () => {
  it("rebases the scheme series to 100 at the first point of the window", () => {
    const { data } = buildChartData(NAV, [], 5)
    expect(data[0].scheme).toBeCloseTo(100, 6)
    // Uptrend ⇒ later index value exceeds 100.
    expect(data[data.length - 1].scheme).toBeGreaterThan(100)
  })

  it("re-anchors per window: 1Y starts at 100 at the 1Y start, not 5Y start", () => {
    const five = buildChartData(NAV, [], 5)
    const one = buildChartData(NAV, [], 1)
    expect(one.data[0].scheme).toBeCloseTo(100, 6)
    // The 1Y window starts later, so its first raw NAV differs from 5Y's,
    // yet both are indexed to exactly 100 at their own first point.
    expect(one.data[0].date).not.toBe(five.data[0].date)
  })
})

describe("buildChartData — benchmark alignment + gaps", () => {
  // Benchmark with a deliberate 99-day hole (2026-01-06 → 2026-04-15),
  // mirroring the live backfill gap for scheme 147946.
  const BENCH: FundBenchmarkPoint[] = NAV.filter(
    (p) => !(p.nav_date > "2026-01-06" && p.nav_date < "2026-04-15"),
  ).map((p, i) => ({
    benchmark_index_code: "NIFTY_SMALLCAP_250_TRI",
    nav_date: p.nav_date,
    tri_value: 8000 + i * 5,
  }))

  it("aligns benchmark to scheme dates and rebases benchmark to 100", () => {
    const { data, hasBenchmark } = buildChartData(NAV, BENCH, 5)
    expect(hasBenchmark).toBe(true)
    const firstWithBench = data.find((d) => d.benchmark != null)
    expect(firstWithBench?.benchmark).toBeCloseTo(100, 6)
  })

  it("renders the benchmark gap as null rows (no interpolation)", () => {
    const { data } = buildChartData(NAV, BENCH, 1)
    const inGap = data.filter(
      (d) => d.date > "2026-01-06" && d.date < "2026-04-15",
    )
    // Scheme spine still has points across the gap...
    expect(inGap.length).toBeGreaterThan(0)
    // ...but every benchmark value inside the gap is null (a break in the
    // line, not a straight-line interpolation across 99 days).
    expect(inGap.every((d) => d.benchmark === null)).toBe(true)
  })

  it("returns hasBenchmark=false when no benchmark rows fall in window", () => {
    const { hasBenchmark } = buildChartData(NAV, [], 5)
    expect(hasBenchmark).toBe(false)
  })
})

describe("buildChartData — edge cases", () => {
  it("returns empty data for empty nav history", () => {
    const r = buildChartData([], [], 5)
    expect(r.data).toEqual([])
    expect(r.hasBenchmark).toBe(false)
    expect(r.spanYears).toBe(0)
  })

  it("sorts unsorted nav history before windowing", () => {
    const shuffled = [...NAV].reverse()
    const { data } = buildChartData(shuffled, [], 5)
    for (let i = 1; i < data.length; i++) {
      expect(data[i].date >= data[i - 1].date).toBe(true)
    }
  })
})
