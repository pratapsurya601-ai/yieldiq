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
})
