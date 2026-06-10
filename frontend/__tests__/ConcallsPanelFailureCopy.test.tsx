/**
 * ROOT CAUSE #10 (2026-06-11) — ConcallsPanel must distinguish the
 * three placeholder strings the backend emits:
 *   - "(summary unavailable)" — populate hasn't fired yet (or fired
 *     and ran out of retries below the threshold). Renders the soft
 *     "Summary not generated yet" line.
 *   - "(summary generation failed — see transcript)" — row has
 *     escalated to the dead-letter table. Renders a louder failure
 *     copy + carries the data-testid="concall-summary-failed" so the
 *     operator can grep prod for it.
 *   - "(summary withheld pending review)" — Groq output tripped the
 *     SEBI vocab guard; renders a withheld notice.
 *
 * Real summary text (bullet lines) is rendered as a normal list.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type React from "react"

import ConcallsPanel from "@/components/analysis/ConcallsPanel"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

interface ConcallItem {
  period: string
  date: string
  source_url: string
  ai_summary: string
  has_full_transcript: boolean
}

function mockFetch(items: ConcallItem[]) {
  const stub = vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () =>
        Promise.resolve({
          ticker: "HDFCBANK",
          count: items.length,
          concalls: items,
        }),
    }),
  )
  vi.stubGlobal("fetch", stub)
  return stub
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe("ConcallsPanel — placeholder differentiation (ROOT CAUSE #10)", () => {
  it("renders the failure copy + testid when ai_summary is the failed sentinel", async () => {
    mockFetch([
      {
        period: "Q1-FY26",
        date: "2025-07-19",
        source_url: "https://example.com/concall.pdf",
        ai_summary: "(summary generation failed — see transcript)",
        has_full_transcript: true,
      },
    ])

    renderWithClient(<ConcallsPanel ticker="HDFCBANK" />)
    await waitFor(() => {
      expect(
        screen.getByTestId("concall-summary-failed"),
      ).toBeInTheDocument()
    })
    expect(
      screen.getByTestId("concall-summary-failed").textContent,
    ).toMatch(/Summary generation failed/i)
  })

  it("renders the soft 'not generated yet' line for the unavailable sentinel", async () => {
    mockFetch([
      {
        period: "Q1-FY26",
        date: "2025-07-19",
        source_url: "https://example.com/concall.pdf",
        ai_summary: "(summary unavailable)",
        has_full_transcript: true,
      },
    ])

    renderWithClient(<ConcallsPanel ticker="HDFCBANK" />)
    await waitFor(() => {
      expect(
        screen.getByText(/Summary not generated yet/i),
      ).toBeInTheDocument()
    })
    // And the failure-copy testid is NOT present — we don't want to
    // alarm the user when the populate path may still succeed on its
    // next attempt.
    expect(screen.queryByTestId("concall-summary-failed")).toBeNull()
  })

  it("renders normal bullet text when the summary is real content", async () => {
    mockFetch([
      {
        period: "Q1-FY26",
        date: "2025-07-19",
        source_url: "https://example.com/concall.pdf",
        ai_summary:
          "- Revenue grew 12% YoY\n- NIM expanded by 20 bps\n- Capex guidance maintained",
        has_full_transcript: true,
      },
    ])

    renderWithClient(<ConcallsPanel ticker="HDFCBANK" />)
    await waitFor(() => {
      expect(screen.getByText(/Revenue grew 12% YoY/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/NIM expanded by 20 bps/i)).toBeInTheDocument()
    expect(screen.queryByTestId("concall-summary-failed")).toBeNull()
  })
})
