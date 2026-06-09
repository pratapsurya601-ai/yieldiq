/**
 * TrustStatsStrip — landing-page coverage tiles.
 *
 * Locks the contract that matters for a first-impression surface:
 *   1. Numbers are real (rendered from the API response, not
 *      placeholder constants).
 *   2. Missing fields → "—" placeholder, NEVER "0" (a 0-tile
 *      reads as broken to a first-time visitor).
 *   3. Tile labels + disclaimer copy are SEBI-safe (no buy/sell/
 *      recommend etc.) — duplicated here so a copy regression
 *      fails fast in the unit suite, not just on the GH lint.
 *   4. Each tile with an href renders an anchor pointing at the
 *      documented deeper-page route.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import React from "react"

vi.mock("@/lib/api", () => ({
  getCoverageStats: vi.fn(),
}))

// next/link → plain anchor for jsdom.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: { href: string; children: React.ReactNode } & Record<string, unknown>) => (
    <a href={href} {...rest}>{children}</a>
  ),
}))

import { getCoverageStats } from "@/lib/api"
import TrustStatsStrip from "@/components/landing/TrustStatsStrip"

const FULL_STATS = {
  as_of: "2026-06-09T08:00:00+05:30",
  stocks_covered: 5247,
  nifty500_logo_coverage_pct: 95,
  dcf_valuations_generated: 12483,
  sectors_covered: 18,
  bank_quarters_backfilled: 174,
  last_engine_update: "2026-06-07T12:00:00+00:00",
  data_sources: ["BSE XBRL", "NSE", "yfinance"],
}

describe("TrustStatsStrip", () => {
  it("renders all 4 tiles with real values from the API response", async () => {
    vi.mocked(getCoverageStats).mockResolvedValue(FULL_STATS as never)
    render(<TrustStatsStrip />)

    // Stocks tile — Indian comma formatting (5,247 not 5247).
    await waitFor(() => {
      expect(screen.getByTestId("trust-tile-stocks-value")).toHaveTextContent(
        "5,247",
      )
    })
    expect(screen.getByTestId("trust-tile-logo-value")).toHaveTextContent("95%")
    expect(screen.getByTestId("trust-tile-updates-value")).toHaveTextContent(
      "Daily",
    )
    expect(screen.getByTestId("trust-tile-sectors-value")).toHaveTextContent("18")

    // Captions render and match the SEBI-safe copy in the brief.
    expect(screen.getByText("Stocks Covered")).toBeInTheDocument()
    expect(screen.getByText("Real-logo Coverage")).toBeInTheDocument()
    expect(screen.getByText("Engine Updates")).toBeInTheDocument()
    expect(screen.getByText("NSE Sectors")).toBeInTheDocument()
  })

  it("shows '—' placeholder, NEVER '0', when API omits a field", async () => {
    // The backend deliberately omits missing counters rather than
    // emitting 0. The component must mirror that contract — a 0 on
    // a launch-page tile reads as a broken product.
    vi.mocked(getCoverageStats).mockResolvedValue({
      as_of: "2026-06-09T08:00:00+05:30",
      data_sources: ["BSE XBRL", "NSE", "yfinance"],
      // stocks_covered, nifty500_logo_coverage_pct, sectors_covered
      // all intentionally omitted.
    } as never)

    render(<TrustStatsStrip />)

    await waitFor(() => {
      // Updates tile renders "Daily" unconditionally — anchors the
      // first paint so the missing-tile assertions are meaningful.
      expect(screen.getByTestId("trust-tile-updates-value")).toHaveTextContent(
        "Daily",
      )
    })

    expect(screen.getByTestId("trust-tile-stocks-value")).toHaveTextContent("—")
    expect(screen.getByTestId("trust-tile-logo-value")).toHaveTextContent("—")
    expect(screen.getByTestId("trust-tile-sectors-value")).toHaveTextContent(
      "—",
    )

    // Absolutely no literal "0" on any tile value.
    const stocksVal = screen.getByTestId("trust-tile-stocks-value")
    expect(stocksVal.textContent).not.toBe("0")
    expect(stocksVal.textContent).not.toBe("0%")
  })

  it("each linked tile renders an anchor at the documented href", async () => {
    vi.mocked(getCoverageStats).mockResolvedValue(FULL_STATS as never)
    render(<TrustStatsStrip />)

    await waitFor(() => {
      expect(screen.getByTestId("trust-tile-stocks")).toBeInTheDocument()
    })

    const stocksLink = screen.getByTestId("trust-tile-stocks")
    expect(stocksLink.tagName.toLowerCase()).toBe("a")
    expect(stocksLink.getAttribute("href")).toBe("/discover")

    const logoLink = screen.getByTestId("trust-tile-logo")
    expect(logoLink.getAttribute("href")).toBe("/methodology")

    const updatesLink = screen.getByTestId("trust-tile-updates")
    expect(updatesLink.getAttribute("href")).toBe("/methodology")

    const sectorsLink = screen.getByTestId("trust-tile-sectors")
    expect(sectorsLink.getAttribute("href")).toBe("/sector")
  })

  it("renders the SEBI disclaimer with the required substrings", async () => {
    vi.mocked(getCoverageStats).mockResolvedValue(FULL_STATS as never)
    const { container } = render(<TrustStatsStrip />)

    await waitFor(() => {
      expect(screen.getByTestId("trust-stats-disclaimer")).toBeInTheDocument()
    })

    const disclaimer = screen.getByTestId("trust-stats-disclaimer")
    const text = (disclaimer.textContent || "").toLowerCase()
    expect(text).toContain("bse/nse")
    expect(text).toContain("yfinance")
    expect(text).toContain("not investment advice")
    expect(text).toContain("methodology")

    // Backstop the SEBI-vocabulary contract — none of these words
    // may appear anywhere in the rendered strip. (sebi-allow comments
    // only suppress the lint workflow; this assertion guards the
    // runtime DOM independently.)
    const dom = (container.textContent || "").toLowerCase()
    for (const word of [
      "buy", "sell", "recommend",
      "outperform", "underperform", "accumulate", "investable",
    ]) {
      expect(dom).not.toContain(word)
    }
  })

  it("survives a network failure by leaving missing tiles as '—'", async () => {
    vi.mocked(getCoverageStats).mockRejectedValue(new Error("offline"))
    render(<TrustStatsStrip />)

    await waitFor(() => {
      // Updates tile is the constant signal that the strip mounted
      // (it does not depend on the network response).
      expect(screen.getByTestId("trust-tile-updates-value")).toHaveTextContent(
        "Daily",
      )
    })
    expect(screen.getByTestId("trust-tile-stocks-value")).toHaveTextContent("—")
    expect(screen.getByTestId("trust-tile-logo-value")).toHaveTextContent("—")
    expect(screen.getByTestId("trust-tile-sectors-value")).toHaveTextContent(
      "—",
    )
  })
})
