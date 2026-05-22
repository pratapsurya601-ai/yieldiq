/**
 * Day-106 — TickerSuggestions ("Did you mean?") tests.
 *
 * Pins three behaviours:
 *   1. When /api/v1/search returns N hits for the typed ticker, all N
 *      render as cards linking to /analysis/<TICKER>.
 *   2. When the API returns zero hits, the component renders nothing
 *      (so the parent's "Search again" CTA remains the sole CTA).
 *   3. The query passed to the API has the .NS / .BO / .BSE suffix
 *      stripped and is lowercased — i.e. /analysis/HDFC.NS hits the
 *      backend as q=hdfc, matching what search_tickers expects.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

const apiGetMock = vi.fn()
vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => apiGetMock(...a),
  },
}))

// next/link is a thin wrapper in test land — just render an <a>.
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode } & Record<string, unknown>) => (
    <a href={href} {...rest}>{children}</a>
  ),
}))

import TickerSuggestions, { tickerToSuggestQuery } from "@/components/analysis/TickerSuggestions"

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  apiGetMock.mockReset()
})

describe("TickerSuggestions", () => {
  it("renders all returned suggestions as analysis links", async () => {
    apiGetMock.mockResolvedValueOnce({
      data: {
        query: "hdfc",
        results: [
          { ticker: "HDFCBANK.NS", name: "HDFC Bank", type: "stock" },
          { ticker: "HDFCLIFE.NS", name: "HDFC Life Insurance", type: "stock" },
          { ticker: "HDFCAMC.NS", name: "HDFC Asset Management", type: "stock" },
        ],
      },
    })

    renderWithClient(<TickerSuggestions ticker="HDFC" />)

    await waitFor(() =>
      expect(screen.getByTestId("ticker-suggestions")).toBeInTheDocument(),
    )

    const bank = screen.getByTestId("suggest-HDFCBANK.NS")
    const life = screen.getByTestId("suggest-HDFCLIFE.NS")
    const amc = screen.getByTestId("suggest-HDFCAMC.NS")

    expect(bank).toHaveAttribute("href", "/analysis/HDFCBANK.NS")
    expect(life).toHaveAttribute("href", "/analysis/HDFCLIFE.NS")
    expect(amc).toHaveAttribute("href", "/analysis/HDFCAMC.NS")

    // Display ticker drops the .NS suffix for legibility.
    expect(bank.textContent).toContain("HDFCBANK")
    expect(bank.textContent).toContain("HDFC Bank")
  })

  it("renders nothing when the API returns no matches", async () => {
    apiGetMock.mockResolvedValueOnce({
      data: { query: "rpower", results: [] },
    })

    const { container } = renderWithClient(<TickerSuggestions ticker="RPOWER.NS" />)

    // Give react-query a tick to settle.
    await new Promise((r) => setTimeout(r, 0))
    expect(container.firstChild).toBeNull()
    expect(screen.queryByTestId("ticker-suggestions")).toBeNull()
  })

  it("strips .NS/.BO/.BSE suffixes and lowercases before querying", async () => {
    apiGetMock.mockResolvedValue({ data: { query: "hdfc", results: [] } })

    renderWithClient(<TickerSuggestions ticker="HDFC.NS" />)

    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/search",
      expect.objectContaining({ params: { q: "hdfc", limit: 5 } }),
    )
  })

  it("tickerToSuggestQuery normalises the various suffix forms", () => {
    expect(tickerToSuggestQuery("HDFC")).toBe("hdfc")
    expect(tickerToSuggestQuery("HDFC.NS")).toBe("hdfc")
    expect(tickerToSuggestQuery("HDFC.BO")).toBe("hdfc")
    expect(tickerToSuggestQuery("HDFC.BSE")).toBe("hdfc")
    expect(tickerToSuggestQuery("  Asian Paints  ")).toBe("asian paints")
  })
})
