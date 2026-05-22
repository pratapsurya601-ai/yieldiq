/**
 * Day-108a — ManifestHistoryPanel tests.
 *
 * Pins three behaviours:
 *   1. Happy path: when /api/v1/public/manifest-history returns N
 *      entries, the first 3 render with rationale + version_id badge;
 *      remaining N-3 are hidden behind a "Show all (N)" toggle.
 *   2. Empty state: when the API returns zero entries, the panel
 *      renders a stable "No model updates" message (no timeline,
 *      no Show-all button).
 *   3. "Show all" toggle expands the rest of the entries and flips
 *      label to "Show fewer".
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import ManifestHistoryPanel from "@/components/analysis/ManifestHistoryPanel"

const FIXTURE_5 = {
  ticker: "NTPC.NS",
  entries: [
    {
      version_id: "v_day107a_it_services_2026_05_23",
      applied_at: "2026-05-23T10:00:00+00:00",
      rationale: "Day-107a: IT services cohort WACC tighten",
      fields_affected: ["*"],
    },
    {
      version_id: "v_day103c_cagr_panel_2026_05_22",
      applied_at: "2026-05-22T19:00:00+00:00",
      rationale: "Day-103c: new compounded_growth field",
      fields_affected: ["compounded_growth"],
    },
    {
      version_id: "v_audit7_p0_2026_05_22",
      applied_at: "2026-05-22T16:30:00+00:00",
      rationale: "Audit#7 P0: ASIANPAINT recompute clamp",
      fields_affected: ["*"],
    },
    {
      version_id: "v_audit6_overvalued_2026_05_22",
      applied_at: "2026-05-22T16:00:00+00:00",
      rationale: "Audit#6: backend mirror of overvalued gate",
      fields_affected: ["verdict"],
    },
    {
      version_id: "v_init_2026_05_22",
      applied_at: "2026-05-22T23:00:00+00:00",
      rationale: "Day-94 migration anchor",
      fields_affected: ["*"],
    },
  ],
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  // @ts-expect-error — stubbing global fetch in jsdom.
  global.fetch = fetchMock
})

afterEach(() => {
  vi.restoreAllMocks()
})

function mockResponse(body: unknown) {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    json: async () => body,
  } as Response)
}

describe("ManifestHistoryPanel", () => {
  it("renders the first 3 entries and hides the rest behind Show all", async () => {
    mockResponse(FIXTURE_5)
    render(<ManifestHistoryPanel ticker="NTPC.NS" />)

    // First three rationales appear.
    await waitFor(() => {
      expect(
        screen.getByText(/Day-107a: IT services cohort WACC tighten/),
      ).toBeInTheDocument()
    })
    expect(
      screen.getByText(/Day-103c: new compounded_growth field/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Audit#7 P0: ASIANPAINT recompute clamp/),
    ).toBeInTheDocument()

    // Hidden ones are not in the DOM yet.
    expect(
      screen.queryByText(/Audit#6: backend mirror of overvalued gate/),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText(/Day-94 migration anchor/),
    ).not.toBeInTheDocument()

    // Toggle visible with the right count.
    expect(screen.getByRole("button", { name: /Show all \(5\)/ })).toBeInTheDocument()
  })

  it("renders the empty-state message when the API returns zero entries", async () => {
    mockResponse({ ticker: "UNKNOWN.NS", entries: [] })
    render(<ManifestHistoryPanel ticker="UNKNOWN.NS" />)
    await waitFor(() => {
      expect(
        screen.getByText(/No model updates have applied to this ticker/),
      ).toBeInTheDocument()
    })
    // No Show-all button in the empty state.
    expect(
      screen.queryByRole("button", { name: /Show all/ }),
    ).not.toBeInTheDocument()
  })

  it("Show all toggle expands the remaining entries and flips label", async () => {
    mockResponse(FIXTURE_5)
    render(<ManifestHistoryPanel ticker="NTPC.NS" />)

    const toggle = await screen.findByRole("button", { name: /Show all \(5\)/ })
    fireEvent.click(toggle)

    // Previously hidden entries now appear.
    await waitFor(() => {
      expect(
        screen.getByText(/Audit#6: backend mirror of overvalued gate/),
      ).toBeInTheDocument()
    })
    expect(screen.getByText(/Day-94 migration anchor/)).toBeInTheDocument()
    // Toggle label flips.
    expect(
      screen.getByRole("button", { name: /Show fewer/ }),
    ).toBeInTheDocument()
  })
})
