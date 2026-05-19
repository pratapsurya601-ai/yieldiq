/**
 * Tests for StoryDcfBadge.
 *
 * Verifies the badge fires for the two backend story-DCF engine
 * strings and stays out of the way for every other engine. The badge
 * is the frontend's visible signal that the displayed fair value is
 * a narrative model whose confidence is hard-capped at 50.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import StoryDcfBadge, {
  isStoryDcfEngine,
} from "@/components/analysis/StoryDcfBadge"

describe("StoryDcfBadge", () => {
  it("renders for engine == 'story_dcf'", () => {
    render(<StoryDcfBadge valuationEngineUsed="story_dcf" />)
    const badge = screen.getByTestId("story-dcf-badge")
    expect(badge).toBeInTheDocument()
    expect(badge.textContent).toMatch(/Story-DCF/)
    expect(badge.textContent).toMatch(/confidence cap 50/)
  })

  it("renders for engine == 'story_dcf_after_dcf_collapse'", () => {
    render(
      <StoryDcfBadge valuationEngineUsed="story_dcf_after_dcf_collapse" />,
    )
    const badge = screen.getByTestId("story-dcf-badge")
    expect(badge).toBeInTheDocument()
    expect(badge.getAttribute("data-engine")).toBe(
      "story_dcf_after_dcf_collapse",
    )
  })

  it("does NOT render for the default DCF engine", () => {
    render(<StoryDcfBadge valuationEngineUsed="dcf" />)
    expect(screen.queryByTestId("story-dcf-badge")).toBeNull()
  })

  it("does NOT render for sector-relative recent-IPO engine", () => {
    render(
      <StoryDcfBadge valuationEngineUsed="sector_relative_recent_ipo" />,
    )
    expect(screen.queryByTestId("story-dcf-badge")).toBeNull()
  })

  it("does NOT render for the Tier-2 cohort engine", () => {
    render(<StoryDcfBadge valuationEngineUsed="tier2_cohort_pe_peer" />)
    expect(screen.queryByTestId("story-dcf-badge")).toBeNull()
  })

  it("does NOT render when engine is null or undefined", () => {
    const { rerender } = render(<StoryDcfBadge />)
    expect(screen.queryByTestId("story-dcf-badge")).toBeNull()
    rerender(<StoryDcfBadge valuationEngineUsed={null} />)
    expect(screen.queryByTestId("story-dcf-badge")).toBeNull()
    rerender(<StoryDcfBadge valuationEngineUsed="" />)
    expect(screen.queryByTestId("story-dcf-badge")).toBeNull()
  })

  it("tooltip mentions the operator-curated config path", () => {
    render(<StoryDcfBadge valuationEngineUsed="story_dcf" />)
    const badge = screen.getByTestId("story-dcf-badge")
    const title = badge.getAttribute("title") ?? ""
    expect(title).toMatch(/story_dcf_overrides\.json/)
    expect(title).toMatch(/cap.*50/i)
  })

  it("tooltip includes the confidence score when provided", () => {
    render(
      <StoryDcfBadge
        valuationEngineUsed="story_dcf"
        confidenceScore={42}
      />,
    )
    const badge = screen.getByTestId("story-dcf-badge")
    expect(badge.getAttribute("title")).toMatch(/42\/100/)
  })

  it("tooltip omits the confidence line when not provided", () => {
    render(<StoryDcfBadge valuationEngineUsed="story_dcf" />)
    const badge = screen.getByTestId("story-dcf-badge")
    expect(badge.getAttribute("title")).not.toMatch(/Current confidence/)
  })
})

describe("isStoryDcfEngine", () => {
  it("accepts the two known story-DCF engine strings", () => {
    expect(isStoryDcfEngine("story_dcf")).toBe(true)
    expect(isStoryDcfEngine("story_dcf_after_dcf_collapse")).toBe(true)
  })

  it("rejects all other engine strings", () => {
    expect(isStoryDcfEngine("dcf")).toBe(false)
    expect(isStoryDcfEngine("tier2_cohort_pe_peer")).toBe(false)
    expect(isStoryDcfEngine("platform_ps_peer")).toBe(false)
    expect(isStoryDcfEngine("rate_base")).toBe(false)
    expect(isStoryDcfEngine("appraisal_value")).toBe(false)
    expect(isStoryDcfEngine("pb_plus_land_bank")).toBe(false)
    expect(isStoryDcfEngine("sector_relative_recent_ipo")).toBe(false)
  })

  it("rejects null / undefined / empty string", () => {
    expect(isStoryDcfEngine(null)).toBe(false)
    expect(isStoryDcfEngine(undefined)).toBe(false)
    expect(isStoryDcfEngine("")).toBe(false)
  })

  it("rejects near-misses (substring match must be exact)", () => {
    expect(isStoryDcfEngine("story_dcf_v2")).toBe(false)
    expect(isStoryDcfEngine("not_story_dcf")).toBe(false)
    expect(isStoryDcfEngine("STORY_DCF")).toBe(false) // case-sensitive
  })
})
