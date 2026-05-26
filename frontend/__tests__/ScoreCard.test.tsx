/**
 * ScoreCard — 12M trend visibility tests (task #190).
 *
 * The "12M trend" chip used to render its label and an empty sparkline
 * when fewer than 2 monthly score buckets were available, which on the
 * dark bg-ink card looked like an empty/broken chip. The fix hides the
 * whole row unless we have a usable series.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"

// Tooltip wrapper just passes children through in tests.
vi.mock("@/components/analysis/MetricTooltip", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import ScoreCard from "@/components/analysis/ScoreCard"

const baseProps = {
  score100: 58,
  grade: "B",
  refractionIndex: 2.3,
  marketCapCr: 12400,
}

describe("ScoreCard 12M trend chip", () => {
  it("omits the trend chip when trend12m is undefined", () => {
    render(<ScoreCard {...baseProps} />)
    expect(screen.queryByText("12M trend")).toBeNull()
    expect(screen.queryByLabelText("12-month score trend")).toBeNull()
  })

  it("omits the trend chip when trend12m is an empty array", () => {
    render(<ScoreCard {...baseProps} trend12m={[]} />)
    expect(screen.queryByText("12M trend")).toBeNull()
    expect(screen.queryByLabelText("12-month score trend")).toBeNull()
  })

  it("omits the trend chip when trend12m has a single point", () => {
    render(<ScoreCard {...baseProps} trend12m={[55]} />)
    expect(screen.queryByText("12M trend")).toBeNull()
    expect(screen.queryByLabelText("12-month score trend")).toBeNull()
  })

  it("renders the trend chip and sparkline when trend12m has ≥ 2 points", () => {
    render(<ScoreCard {...baseProps} trend12m={[50, 55, 58]} />)
    expect(screen.getByText("12M trend")).toBeInTheDocument()
    expect(screen.getByLabelText("12-month score trend")).toBeInTheDocument()
  })

  // P0 stubborn-render follow-up: a flat all-equal series (commonly all
  // zeros from a backfill cron that hasn't populated real scores yet)
  // cleared the prior length-only gate but the sparkline drew only a 1px
  // baseline that looked visually empty next to the "12M TREND" label on
  // the dark bg-ink card. The new variance gate must hide the row.
  it("omits the trend chip when trend12m is all zeros", () => {
    render(
      <ScoreCard {...baseProps} trend12m={[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]} />,
    )
    expect(screen.queryByText("12M trend")).toBeNull()
    expect(screen.queryByLabelText("12-month score trend")).toBeNull()
  })

  it("omits the trend chip when every point is identical", () => {
    render(<ScoreCard {...baseProps} trend12m={[50, 50, 50, 50]} />)
    expect(screen.queryByText("12M trend")).toBeNull()
    expect(screen.queryByLabelText("12-month score trend")).toBeNull()
  })

  // Defence-in-depth: if a caller bypasses lib/prism's adapter and hands
  // us a raw API array containing nulls/NaN/Infinity, we must still hide
  // the row rather than render an empty/broken sparkline.
  it("omits the trend chip when all points are non-finite", () => {
    // Simulates a raw-API payload that bypassed the adapter.
    const dirty = [NaN, Infinity, -Infinity] as unknown as number[]
    render(<ScoreCard {...baseProps} trend12m={dirty} />)
    expect(screen.queryByText("12M trend")).toBeNull()
    expect(screen.queryByLabelText("12-month score trend")).toBeNull()
  })

  it("renders the chip when ≥2 finite points survive filtering and vary", () => {
    const dirty = [NaN, 50, Infinity, 55] as unknown as number[]
    render(<ScoreCard {...baseProps} trend12m={dirty} />)
    expect(screen.getByText("12M trend")).toBeInTheDocument()
    expect(screen.getByLabelText("12-month score trend")).toBeInTheDocument()
  })
})
