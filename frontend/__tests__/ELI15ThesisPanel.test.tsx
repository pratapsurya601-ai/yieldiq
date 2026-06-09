/**
 * ELI15ThesisPanel smoke tests.
 *
 * Pins these behaviours:
 *   1. Populated path: renders 3 bullets, the disclaimer, and the
 *      "Adjust assumptions" link pointing at the playground.
 *   2. Empty path: bullets array empty -> render nothing.
 *   3. Loading path: no initialData and the underlying useQuery is
 *      in-flight -> render the skeleton (3 shimmer rows).
 *   4. Error path: api call throws -> render nothing (never show
 *      an "AI failed" message — looks bad on a research page).
 *
 * The component uses @tanstack/react-query; tests inject a fresh
 * QueryClient per case so suites are isolated.
 */
import React from "react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

// Mock the API helper so the component's useQuery never hits the
// network. We control loading / error / data on a per-test basis
// by re-assigning the mock implementation before each render.
const getELI15ThesisMock = vi.fn()
vi.mock("@/lib/api", () => ({
  getELI15Thesis: (...a: unknown[]) => getELI15ThesisMock(...a),
}))

import ELI15ThesisPanel from "@/components/analysis/ELI15ThesisPanel"
import type { ELI15ThesisResponse } from "@/lib/api"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  )
}

const FULL_PAYLOAD: ELI15ThesisResponse = {
  ticker: "HDFCBANK.NS",
  generated_at: "2026-06-09T07:30:00+05:30",
  model_version: "eli15-thesis-v1-anthropic-2026-06-09",
  verdict: "undervalued",
  verdict_display: "below model fair value",
  bullets: [
    "HDFC Bank trades at Rs 747; the model's base-case fair value is Rs 1,146, a 53% gap.",
    "The wide moat label sits at 72 and the DCF uses WACC 9.8% with terminal growth 3.0%.",
    "Confidence is 90% with data quality as the top driver, and the bear case Rs 955 still sits above the current price.",
  ],
  disclaimer:
    "Generated 2026-06-09. Not advice; for educational use. Adjust your own assumptions on the Reverse-DCF Playground.",
  cached: false,
}

beforeEach(() => {
  getELI15ThesisMock.mockReset()
})

describe("ELI15ThesisPanel", () => {
  it("renders all 3 bullets, disclaimer, and playground link", async () => {
    renderWithClient(
      <ELI15ThesisPanel ticker="HDFCBANK.NS" initialData={FULL_PAYLOAD} />,
    )

    // Header text.
    expect(
      screen.getByText(/Why the model sees it this way/i),
    ).toBeInTheDocument()

    // Each bullet rendered verbatim.
    for (const b of FULL_PAYLOAD.bullets) {
      expect(screen.getByText(b)).toBeInTheDocument()
    }

    // Disclaimer present (matches the date stamp).
    expect(
      screen.getByText(/Generated 2026-06-09/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Not advice; for educational use/),
    ).toBeInTheDocument()

    // "Adjust assumptions" link points at the playground.
    const link = screen.getByRole("link", { name: /Adjust assumptions/i })
    expect(link).toHaveAttribute(
      "href",
      "/analysis/HDFCBANK.NS/playground",
    )

    // Panel exposes a stable testid for downstream selectors.
    expect(screen.getByTestId("eli15-thesis-panel")).toBeInTheDocument()
  })

  it("renders the skeleton while loading", () => {
    // Pending promise -> useQuery stays in the loading state.
    getELI15ThesisMock.mockReturnValue(new Promise(() => { /* never resolves */ }))

    renderWithClient(<ELI15ThesisPanel ticker="TCS.NS" />)

    // Skeleton is rendered with the right testid + aria-busy.
    const skel = screen.getByTestId("eli15-thesis-skeleton")
    expect(skel).toBeInTheDocument()
    expect(skel).toHaveAttribute("aria-busy", "true")

    // The populated panel is NOT rendered.
    expect(screen.queryByTestId("eli15-thesis-panel")).toBeNull()
  })

  it("renders nothing when the api throws", async () => {
    // Reject the query so React Query goes to error state. The
    // component sets ``retry: 1`` so the rejection happens twice
    // before isError flips to true — allow a generous timeout.
    getELI15ThesisMock.mockRejectedValue(new Error("network down"))

    const { container } = renderWithClient(
      <ELI15ThesisPanel ticker="INFY.NS" />,
    )

    await waitFor(
      () => {
        expect(container.firstChild).toBeNull()
      },
      { timeout: 5000 },
    )
    // Mock was called at least once.
    expect(getELI15ThesisMock).toHaveBeenCalled()
  })

  it("renders nothing when bullets array is empty", () => {
    const emptyPayload: ELI15ThesisResponse = {
      ...FULL_PAYLOAD,
      bullets: [],
    }
    const { container } = renderWithClient(
      <ELI15ThesisPanel ticker="HDFCBANK.NS" initialData={emptyPayload} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("clamps to 3 bullets even if the backend returns more", () => {
    const overlong: ELI15ThesisResponse = {
      ...FULL_PAYLOAD,
      bullets: [
        ...FULL_PAYLOAD.bullets,
        "An extra fourth bullet that should never render.",
        "And a fifth one for good measure.",
      ],
    }
    renderWithClient(
      <ELI15ThesisPanel ticker="HDFCBANK.NS" initialData={overlong} />,
    )
    expect(
      screen.queryByText(/An extra fourth bullet/i),
    ).toBeNull()
    expect(
      screen.queryByText(/fifth one for good measure/i),
    ).toBeNull()
    // First 3 still render.
    for (const b of FULL_PAYLOAD.bullets) {
      expect(screen.getByText(b)).toBeInTheDocument()
    }
  })
})
