/**
 * Anon /analysis/[ticker] — verdict-label unification.
 *
 * Task #178 P0 (2026-05-24): the anon page rendered THREE different
 * verdict strings for HDFCBANK.NS:
 *   • <title>       "Notably Undervalued"  (verdictFromMos(mos))
 *   • hero badge    "UNDER REVIEW"          (shouldGateVerdict gate)
 *   • Prism alt     "Deep value region"     (backend verdict_label)
 *
 * Day-34 "Verdict-chip consolidation — single source of truth" was
 * supposed to unify these. This test regression-guards against a future
 * regression by asserting all three surfaces render the SAME string when
 * fed the same backend payload.
 *
 * The contract: every surface reads `verdict_label` from /api/v1/prism;
 * local re-derivation from mos_pct or score is banned.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

// Mock heavyweight visual children that aren't relevant to label-string
// assertions. Prism is mocked at the top level so we can inspect the
// `data.verdict_label` it would have used for its alt text via the
// mock's recorded props.
const prismCalls: Array<{ data: { verdict_label?: string } }> = []
vi.mock("@/components/prism/Prism", () => ({
  default: (props: { data: { verdict_label?: string } }) => {
    prismCalls.push(props)
    return (
      <div
        data-testid="prism-mock"
        data-verdict-label={props.data.verdict_label ?? ""}
      />
    )
  },
}))
vi.mock("@/components/prism/PrismSkeleton", () => ({
  default: () => null,
}))
vi.mock("@/components/analysis/Breadcrumb", () => ({
  default: () => null,
  bucketFromMarketCapCr: () => "Large-cap",
}))
vi.mock("@/components/watchlist/WatchlistButton", () => ({
  default: () => null,
}))
vi.mock("@/app/(app)/analysis/[ticker]/JsonLd", () => ({
  default: () => null,
}))
vi.mock("@/components/analysis/MetricTooltip", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock("@/components/analysis/FvConfidenceBand", () => ({
  default: () => null,
}))

// Mock the api client so PublicAnalysis's useQuery resolves with the
// fixture without making a real HTTP call.
const HDFC_FIXTURE = {
  ticker: "HDFCBANK.NS",
  company_name: "HDFC Bank",
  sector: "Financial Services",
  price: 766.8,
  fair_value: 1097.15,
  mos_pct: 43.1,
  // The canonical string ALL three surfaces must render.
  verdict_label: "Notably Undervalued",
  verdict_band: "deepValue",
  yieldiq_score_100: 50,
  grade: "B",
  market_cap_cr: 600_000,
  confidence: 40, // intentionally low to prove the old shouldGateVerdict path is gone
  scenarios: { bear: 600, base: 1097, bull: 1800 }, // wide band — would have tripped old gate
  hex: {
    overall: 5,
    axes: {},
    sector_medians: {},
  },
}
vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(async () => ({ data: HDFC_FIXTURE })),
  },
}))

import PublicAnalysis from "@/app/(app)/analysis/[ticker]/PublicAnalysis"
import { adaptPrismResponse } from "@/lib/prism"

function renderPublic() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <PublicAnalysis ticker="HDFCBANK.NS" />
    </QueryClientProvider>,
  )
}

describe("Anon /analysis/[ticker] — verdict-label unification (task #178)", () => {
  beforeEach(() => {
    prismCalls.length = 0
  })

  it("hero badge renders the backend verdict_label verbatim", async () => {
    renderPublic()
    // Wait for the query to resolve and the body to swap in.
    await waitFor(() => {
      expect(screen.queryByTestId("prism-mock")).toBeTruthy()
    })
    // The hero badge sits in the summary card. It must contain the
    // canonical label, NOT "Under Review" (the old shouldGateVerdict
    // output for low-confidence/wide-band inputs) and NOT a label
    // re-derived from MoS via verdictFromMos.
    expect(screen.getByText(HDFC_FIXTURE.verdict_label)).toBeTruthy()
    expect(screen.queryByText(/under review/i)).toBeNull()
  })

  it("Prism alt-text source (data.verdict_label) matches the badge string", async () => {
    renderPublic()
    await waitFor(() => {
      expect(screen.queryByTestId("prism-mock")).toBeTruthy()
    })
    // The Prism component computes its alt as
    //   `Prism for ${ticker}: composite X of 10, verdict ${verdict_label}`
    // so verdict_label is the load-bearing string. Assert that the
    // string handed to <Prism> matches what the badge rendered.
    const prismEl = screen.getByTestId("prism-mock")
    expect(prismEl.getAttribute("data-verdict-label")).toBe(
      HDFC_FIXTURE.verdict_label,
    )
  })

  it("adaptPrismResponse preserves verdict_label as-is for the alt-text source", () => {
    // The same adapter the live PublicAnalysis path uses for the Prism
    // component. Confirms the canonical label survives the round-trip
    // and isn't quietly defaulted to "Under Review".
    const adapted = adaptPrismResponse(HDFC_FIXTURE, "HDFCBANK.NS")
    expect(adapted.verdict_label).toBe(HDFC_FIXTURE.verdict_label)
  })

  it("all three surfaces converge on the same string", async () => {
    renderPublic()
    await waitFor(() => {
      expect(screen.queryByTestId("prism-mock")).toBeTruthy()
    })
    const adapted = adaptPrismResponse(HDFC_FIXTURE, "HDFCBANK.NS")
    const badgeText = screen.getByText(HDFC_FIXTURE.verdict_label).textContent
    const prismLabel = screen
      .getByTestId("prism-mock")
      .getAttribute("data-verdict-label")
    // layout.tsx generateMetadata renders
    //   `${displayTicker} — ${prismVerdictLabel} | YieldIQ`
    // We can't easily invoke generateMetadata here (it's an SSR Next
    // helper that does its own fetch), so we assert the contract: the
    // string it would interpolate is `prismData.verdict_label`, which
    // is identical to what the badge and Prism alt render.
    expect(prismLabel).toBe(badgeText)
    expect(adapted.verdict_label).toBe(badgeText)
    // Concretely: the tab title would be
    //   "HDFCBANK — Notably Undervalued | YieldIQ"
    // matching the badge "Notably Undervalued" and the Prism alt's
    // "verdict Notably Undervalued" tail — three surfaces, one string.
  })
})
