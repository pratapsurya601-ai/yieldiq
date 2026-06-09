/**
 * MarketsStrip — locks in the post-2026-06-09 layout that adds three
 * commodity tiles (GOLD / SILVER / CRUDE) after the existing five
 * indices + FX + 10Y cells.
 *
 * The strip is the LCP candidate on /home, so structural drift here has
 * outsized perf implications. The snapshot diff catches both visual
 * regressions and accidental tile removal.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

vi.mock("@/lib/api", () => ({
  getMarketPulse: vi.fn(),
}))

import { getMarketPulse } from "@/lib/api"
import MarketsStrip from "@/components/home/v2/MarketsStrip"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const FULL_PULSE = {
  indices: [
    { name: "NIFTY 50",   price: 25_400, change_pct:  0.42, sparkline_7d: [25200, 25250, 25300, 25320, 25340, 25380, 25400] },
    { name: "NIFTY BANK", price: 53_100, change_pct: -0.18, sparkline_7d: [53200, 53180, 53150, 53140, 53130, 53110, 53100] },
    // 2026-06-09 — SENSEX now ships a sparkline via macro_sparklines
    // (yfinance ^BSESN, since the BSE composite is not in
    // nse_index_history). The backend promotes the series onto
    // idx.sparkline_7d before sending; this fixture mirrors that.
    { name: "SENSEX",     price: 83_550, change_pct:  0.30, sparkline_7d: [83000, 83100, 83200, 83300, 83400, 83500, 83550] },
  ],
  fear_greed_index: null,
  fear_greed_label: null,
  timestamp: "2026-06-08T15:30:00+05:30",
  usd_inr: 83.5,
  // 2026-06-09 — pct fields added so USD/INR + India 10Y tiles render
  // a delta badge instead of "—" hardcoded pre-fix. Values chosen
  // distinct from every other tile's change_pct in this fixture so
  // the regex assertions below have exactly one DOM match each.
  usd_inr_change_pct: 0.71,   // → "+0.7%" — distinct from indices/commodities
  risk_free_pct: 7.05,
  risk_free_change_pct: -1.62, // → "-1.6%" — distinct from indices/commodities
  // Commodity payload added by the same PR as this test.
  gold_usd: 2350.0,
  silver_usd: 30.5,
  crude_usd: 78.2,
  gold_usd_change_pct: 0.8,
  silver_usd_change_pct: -0.5,
  crude_usd_change_pct: 1.2,
  gold_inr_per_10g: 63_080,
  silver_inr_per_10g: 818,
  // 2026-06-09 — backend populates 7d closes for the 5 macro tiles +
  // SENSEX via yfinance. The Cell renders the sparkline iff the series
  // has ≥ 2 points. Five usable keys here (SENSEX already lives on the
  // index tile via sparkline_7d) means five inline sparklines after
  // the three index sparklines = eight total svg.recharts-like nodes.
  macro_sparklines: {
    USDINR:   [83.30, 83.35, 83.40, 83.45, 83.42, 83.48, 83.50],
    INDIA10Y: [7.10, 7.09, 7.07, 7.06, 7.06, 7.04, 7.05],
    GOLD:     [2300, 2310, 2320, 2330, 2335, 2345, 2350],
    SILVER:   [30.0, 30.1, 30.2, 30.3, 30.4, 30.45, 30.5],
    CRUDE:    [77.0, 77.5, 77.8, 78.0, 78.1, 78.15, 78.2],
  },
}

describe("MarketsStrip — commodity tiles", () => {
  it("renders GOLD, SILVER, and CRUDE tiles after the index + FX cells", async () => {
    vi.mocked(getMarketPulse).mockResolvedValue(FULL_PULSE as never)
    const { container } = renderWithClient(<MarketsStrip />)
    await waitFor(() => {
      expect(screen.getByText("GOLD")).toBeInTheDocument()
    })
    expect(screen.getByText("SILVER")).toBeInTheDocument()
    expect(screen.getByText("CRUDE")).toBeInTheDocument()
    // Spot-check formatting: gold/silver in ₹/10g, crude in $/bbl.
    expect(screen.getByText(/₹63,080\/10g/)).toBeInTheDocument()
    expect(screen.getByText(/\$78\.2\/bbl/)).toBeInTheDocument()
    // SEBI watch — neutral labels only.
    const text = container.textContent || ""
    expect(text.toLowerCase()).not.toContain("buy")
    expect(text.toLowerCase()).not.toContain("recommend") // sebi-allow: recommend
    expect(container).toMatchSnapshot()
  })

  it("renders sparklines for all 6 macro tiles + SENSEX when backend populates them", async () => {
    // 2026-06-09 — regression guard for the macro_sparklines fix.
    // Pre-fix the strip showed sparklines only on NIFTY 50 + NIFTY BANK
    // (the two indices `nse_index_history` carried). After fix:
    //   - 3 index tiles render sparklines (NIFTY 50, NIFTY BANK, SENSEX)
    //   - 5 macro tiles render sparklines (USD/INR, India 10Y, GOLD,
    //     SILVER, CRUDE) backed by yfinance-cached series.
    // Total = 8 sparkline SVGs in the strip.
    vi.mocked(getMarketPulse).mockResolvedValue(FULL_PULSE as never)
    const { container } = renderWithClient(<MarketsStrip />)
    await waitFor(() => {
      expect(screen.getByText("GOLD")).toBeInTheDocument()
    })
    const sparklines = container.querySelectorAll("[data-testid='sparkline-svg']")
    expect(sparklines.length).toBe(8)
  })

  it("renders change % for USD/INR and India 10Y when backend supplies the deltas", async () => {
    // 2026-06-09 — pre-fix MarketsStrip.tsx hardcoded `pct={null}` for
    // these two tiles even when the backend had the data. After fix
    // the cells read `pulse.usd_inr_change_pct` and
    // `pulse.risk_free_change_pct`, so the formatted pct string
    // ("+0.12%" / "-0.04%") renders next to the tile value.
    vi.mocked(getMarketPulse).mockResolvedValue(FULL_PULSE as never)
    renderWithClient(<MarketsStrip />)
    await waitFor(() => {
      expect(screen.getByText("USD/INR")).toBeInTheDocument()
    })
    // formatPct rounds to 1 decimal place ("+0.7%" / "-1.6%"). Match
    // loosely so future formatPct precision tweaks don't break the
    // test — we care that SOME pct ≠ "—" is rendered.
    expect(screen.getByText(/\+0\.7\s*%/)).toBeInTheDocument()
    expect(screen.getByText(/-1\.6\s*%/)).toBeInTheDocument()
  })

  it("falls back to '—' for USD/INR and India 10Y when backend pct fields are null", async () => {
    // Degraded path: yfinance was rate-limited so the backend served
    // the cached USD/INR + 10Y values but the change_pct derivation
    // returned None. The tile still renders the value; only the badge
    // collapses to "—". Sparklines for those tiles are also missing
    // (the cache miss is correlated — same yfinance call powered both).
    vi.mocked(getMarketPulse).mockResolvedValue({
      ...FULL_PULSE,
      usd_inr_change_pct: null,
      risk_free_change_pct: null,
      macro_sparklines: {
        ...FULL_PULSE.macro_sparklines,
        USDINR: undefined,
        INDIA10Y: undefined,
      },
    } as never)
    const { container } = renderWithClient(<MarketsStrip />)
    await waitFor(() => {
      expect(screen.getByText("USD/INR")).toBeInTheDocument()
    })
    // Both tile values still show. The pct text collapses to "—".
    expect(screen.getByText(/₹83\.50/)).toBeInTheDocument()
    expect(screen.getByText(/7\.05%/)).toBeInTheDocument()
    // Sparkline SVG count drops by 2 (USDINR + INDIA10Y absent).
    const sparklines = container.querySelectorAll("[data-testid='sparkline-svg']")
    expect(sparklines.length).toBe(6)
  })

  it("renders '—' for commodity tiles when upstream data is missing", async () => {
    // yfinance rate-limit / outage path: gold_inr_per_10g and crude_usd
    // both null. The tile must degrade to "—" rather than crash.
    vi.mocked(getMarketPulse).mockResolvedValue({
      ...FULL_PULSE,
      gold_usd: null,
      silver_usd: null,
      crude_usd: null,
      gold_usd_change_pct: null,
      silver_usd_change_pct: null,
      crude_usd_change_pct: null,
      gold_inr_per_10g: null,
      silver_inr_per_10g: null,
    } as never)
    const { container } = renderWithClient(<MarketsStrip />)
    await waitFor(() => {
      expect(screen.getByText("GOLD")).toBeInTheDocument()
    })
    // All three commodity tiles render the em-dash placeholder.
    const dashes = container.querySelectorAll("span")
    const dashCount = Array.from(dashes).filter(
      (el) => el.textContent === "—",
    ).length
    // Strip already had USD/INR + India 10Y emit a "—" for the pct
    // column even in the populated case (pct=null). With three more
    // missing tiles we expect AT LEAST 3 additional dashes for the
    // commodity values themselves.
    expect(dashCount).toBeGreaterThanOrEqual(3)
  })
})

describe("MarketsStrip — showHubLink prop (Bug 1, 2026-06-09)", () => {
  // The /markets hub itself renders the strip; before the fix the
  // tail-end "Markets →" link pointed at the page the user was on.
  // The prop defaults to true so /home stays byte-identical.
  it("renders the 'Markets →' link by default", async () => {
    vi.mocked(getMarketPulse).mockResolvedValue(FULL_PULSE as never)
    renderWithClient(<MarketsStrip />)
    await waitFor(() => {
      expect(screen.getByText("GOLD")).toBeInTheDocument()
    })
    const links = screen.getAllByRole("link")
    const hubLink = links.find(
      (a) => a.getAttribute("href") === "/markets",
    )
    expect(hubLink).toBeDefined()
  })

  it("omits the 'Markets →' link when showHubLink={false}", async () => {
    vi.mocked(getMarketPulse).mockResolvedValue(FULL_PULSE as never)
    renderWithClient(<MarketsStrip showHubLink={false} />)
    await waitFor(() => {
      expect(screen.getByText("GOLD")).toBeInTheDocument()
    })
    const links = screen.getAllByRole("link")
    const hubLink = links.find(
      (a) => a.getAttribute("href") === "/markets",
    )
    expect(hubLink).toBeUndefined()
  })

  it("links the SENSEX tile to /sensex (Bug 3)", async () => {
    // Pre-fix the SENSEX tile rendered as a non-clickable div because
    // INDEX_ROUTES had no entry for it. After Bug 3 the new /sensex
    // page is wired into INDEX_ROUTES and the tile becomes a real link.
    vi.mocked(getMarketPulse).mockResolvedValue(FULL_PULSE as never)
    renderWithClient(<MarketsStrip />)
    await waitFor(() => {
      expect(screen.getByText("SENSEX")).toBeInTheDocument()
    })
    const links = screen.getAllByRole("link")
    const sensexLink = links.find(
      (a) => a.getAttribute("href") === "/sensex",
    )
    expect(sensexLink).toBeDefined()
  })
})
