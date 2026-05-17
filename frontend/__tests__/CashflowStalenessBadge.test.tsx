/**
 * Tests for CashflowStalenessBadge.
 *
 * Verifies the badge correctly surfaces the backend's `fcf_ttm_basis`
 * (and the compound `fcf_data_source` string carrying it) so users
 * see when TTM cashflow data is stale per SEBI's H1/Q4-only CFS rule.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import CashflowStalenessBadge, {
  parseCashflowBasis,
  resolveBadgeSpec,
} from "@/components/analysis/CashflowStalenessBadge"

describe("CashflowStalenessBadge", () => {
  it("renders amber badge when basis is fy_q4_stale", () => {
    render(<CashflowStalenessBadge basis="fy_q4_stale" />)
    const badge = screen.getByTestId("cashflow-staleness-badge")
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveAttribute("data-tone", "amber")
    expect(badge.textContent).toContain("Cashflow data from FY-end (Mar)")
  })

  it("renders amber badge when basis is older_than_6mo", () => {
    render(<CashflowStalenessBadge basis="older_than_6mo" />)
    const badge = screen.getByTestId("cashflow-staleness-badge")
    expect(badge).toHaveAttribute("data-tone", "amber")
    expect(badge.textContent).toContain(">6 months old")
  })

  it("renders neutral badge for h1_stitched / h1_plus_prev_h2", () => {
    render(<CashflowStalenessBadge basis="h1_stitched" />)
    const badge = screen.getByTestId("cashflow-staleness-badge")
    expect(badge).toHaveAttribute("data-tone", "neutral")
    expect(badge.getAttribute("title")).toMatch(/stitched from latest H1 \+ Q4/)
  })

  it("does NOT render when basis is 'fresh'", () => {
    render(<CashflowStalenessBadge basis="fresh" />)
    expect(screen.queryByTestId("cashflow-staleness-badge")).toBeNull()
  })

  it("does NOT render when basis is 'latest_q_cfs'", () => {
    render(<CashflowStalenessBadge basis="latest_q_cfs" />)
    expect(screen.queryByTestId("cashflow-staleness-badge")).toBeNull()
  })

  it("does NOT render when basis is 'fy_q4' (full FY, current)", () => {
    render(<CashflowStalenessBadge basis="fy_q4" />)
    expect(screen.queryByTestId("cashflow-staleness-badge")).toBeNull()
  })

  it("does NOT render when basis is absent / null / unknown", () => {
    const { rerender } = render(<CashflowStalenessBadge />)
    expect(screen.queryByTestId("cashflow-staleness-badge")).toBeNull()
    rerender(<CashflowStalenessBadge basis={null} />)
    expect(screen.queryByTestId("cashflow-staleness-badge")).toBeNull()
    rerender(<CashflowStalenessBadge basis="some_unknown_token" />)
    expect(screen.queryByTestId("cashflow-staleness-badge")).toBeNull()
  })

  it("parses basis from fcf_data_source compound string", () => {
    render(
      <CashflowStalenessBadge dataSource="ttm+nse_xbrl_cf_fy_q4_stale" />,
    )
    const badge = screen.getByTestId("cashflow-staleness-badge")
    expect(badge).toHaveAttribute("data-tone", "amber")
    expect(badge).toHaveAttribute("data-basis", "fy_q4_stale")
  })

  it("explicit basis prop wins over dataSource", () => {
    render(
      <CashflowStalenessBadge
        basis="h1_plus_prev_h2"
        dataSource="ttm+nse_xbrl_cf_fy_q4_stale"
      />,
    )
    const badge = screen.getByTestId("cashflow-staleness-badge")
    expect(badge).toHaveAttribute("data-tone", "neutral")
    expect(badge).toHaveAttribute("data-basis", "h1_plus_prev_h2")
  })

  it("amber tooltip mentions the SEBI rule", () => {
    render(<CashflowStalenessBadge basis="fy_q4_stale" />)
    const badge = screen.getByTestId("cashflow-staleness-badge")
    const title = badge.getAttribute("title") ?? ""
    expect(title).toMatch(/SEBI/)
    expect(title).toMatch(/H1.*Sep.*Q4.*Mar|Sep.*Mar/i)
  })
})

describe("parseCashflowBasis", () => {
  it("returns null on empty input", () => {
    expect(parseCashflowBasis()).toBeNull()
    expect(parseCashflowBasis(null, null)).toBeNull()
    expect(parseCashflowBasis("", "")).toBeNull()
  })

  it("returns basis when provided directly", () => {
    expect(parseCashflowBasis("fy_q4_stale")).toBe("fy_q4_stale")
  })

  it("extracts basis from ttm+nse_xbrl_cf_{basis} form", () => {
    expect(parseCashflowBasis(null, "ttm+nse_xbrl_cf_h1_plus_prev_h2")).toBe(
      "h1_plus_prev_h2",
    )
    expect(parseCashflowBasis(null, "ttm+nse_xbrl_cf_fy_q4_stale")).toBe(
      "fy_q4_stale",
    )
  })

  it("returns null when dataSource has no recognizable marker", () => {
    expect(parseCashflowBasis(null, "yfinance")).toBeNull()
    expect(parseCashflowBasis(null, "normalized_3y")).toBeNull()
  })
})

describe("resolveBadgeSpec", () => {
  it("returns null for fresh / latest_q_cfs / fy_q4 / unknown", () => {
    expect(resolveBadgeSpec("fresh")).toBeNull()
    expect(resolveBadgeSpec("latest_q_cfs")).toBeNull()
    expect(resolveBadgeSpec("fy_q4")).toBeNull()
    expect(resolveBadgeSpec("garbage")).toBeNull()
    expect(resolveBadgeSpec(null)).toBeNull()
  })

  it("returns amber spec for fy_q4_stale", () => {
    const spec = resolveBadgeSpec("fy_q4_stale")
    expect(spec).not.toBeNull()
    expect(spec!.tone).toBe("amber")
    expect(spec!.label).toMatch(/FY-end/)
  })

  it("returns neutral spec for h1_stitched and h1_plus_prev_h2", () => {
    expect(resolveBadgeSpec("h1_stitched")!.tone).toBe("neutral")
    expect(resolveBadgeSpec("h1_plus_prev_h2")!.tone).toBe("neutral")
  })
})
