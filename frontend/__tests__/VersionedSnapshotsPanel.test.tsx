/**
 * T5.6 — VersionedSnapshotsPanel tests.
 *
 * Pins these behaviours:
 *   1. Renders entries when /manifest-history returns data.
 *   2. Date filter (from / to) reduces the visible set.
 *   3. Field filter chip reduces the visible set + flips active state.
 *   4. Diff button renders when fair_value_history covers the entry.
 *   5. Diff button absent when fv_history is sparse around the entry.
 *   6. Empty state when zero entries.
 *   7. Filter-no-match state ("No entries match the current filters").
 *   8. Loading state placeholder.
 *   9. "more" toggle on long rationales expands and collapses copy.
 *  10. Clear-filters button resets all three filters.
 *  11. SEBI guard — rendered DOM contains none of the banned verdict
 *      tokens. Per CLAUDE.md rule #5 the banned list is built from
 *      string fragments so the sebi-lint --diff-only scan never
 *      sees the literal tokens in the test source.
 */
import React from "react"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"

// Mock the api module so we can control getFVHistory return value
// without spinning up the real axios stack. The component imports
// `getFVHistory` and the `FVHistoryPoint` type from "@/lib/api".
const getFVHistoryMock = vi.fn()
vi.mock("@/lib/api", () => ({
  getFVHistory: (...a: unknown[]) => getFVHistoryMock(...a),
}))

import VersionedSnapshotsPanel from "@/components/analysis/VersionedSnapshotsPanel"

// Authed-shape fixture (version_id + rationale present). Five entries
// across a March -> May 2026 span so date-range filters have something
// to bite.
const FIXTURE = {
  ticker: "NTPC.NS",
  entries: [
    {
      version_id: "v_may_2026_cohort",
      applied_at: "2026-05-23T10:00:00+00:00",
      rationale: "Cohort-wide weighting refresh for the IT services group",
      fields_affected: ["*"],
    },
    {
      version_id: "v_apr_2026_growth",
      applied_at: "2026-04-15T09:00:00+00:00",
      rationale: "Added compounded growth metric to stock summary payload",
      fields_affected: ["compounded_growth"],
    },
    {
      version_id: "v_apr_2026_verdict",
      applied_at: "2026-04-01T16:00:00+00:00",
      rationale: "Tightened the overvalued band on the engine output",
      fields_affected: ["verdict"],
    },
    {
      version_id: "v_mar_2026_long",
      applied_at: "2026-03-20T11:00:00+00:00",
      rationale:
        // Long enough to trip the >140 char "more" affordance.
        "This entry is intentionally long so the panel renders the inline " +
        "more / less affordance for a single card. It is a synthetic rationale " +
        "written purely to exercise the truncation logic in the test environment.",
      fields_affected: ["composite_intrinsic_value", "fair_value"],
    },
    {
      version_id: "v_init_2026_02",
      applied_at: "2026-02-10T23:00:00+00:00",
      rationale: "Migration anchor entry for the granular cache rollout",
      fields_affected: ["*"],
    },
  ],
}

// fv-history rows that bracket the v_may_2026_cohort applied_at so the
// diff badge has both a before-row and an after-row to render.
const FV_HISTORY_RICH = {
  ticker: "NTPC.NS",
  has_data: true,
  tier: "free",
  tier_limited: false,
  years_returned: 3,
  data: [
    { date: "2026-05-20", fair_value: 100, price: 90, mos_pct: 11, verdict: null },
    { date: "2026-05-25", fair_value: 110, price: 92, mos_pct: 19, verdict: null },
    { date: "2026-04-10", fair_value: 95, price: 88, mos_pct: 8, verdict: null },
    { date: "2026-04-20", fair_value: 97, price: 89, mos_pct: 9, verdict: null },
  ],
  summary: {
    has_data: true,
    data_start_date: "2026-04-10",
    total_points: 4,
    pct_undervalued: null,
    pct_overvalued: null,
  },
}

const FV_HISTORY_EMPTY = {
  ticker: "NTPC.NS",
  has_data: false,
  tier: "free",
  tier_limited: false,
  years_returned: 3,
  data: [],
  summary: {
    has_data: false,
    data_start_date: null,
    total_points: 0,
    pct_undervalued: null,
    pct_overvalued: null,
  },
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  ;(global as unknown as { fetch: unknown }).fetch = fetchMock
  getFVHistoryMock.mockReset()
  // Default: no FV-history rows. Tests that need diffs override below.
  getFVHistoryMock.mockResolvedValue(FV_HISTORY_EMPTY)
})

afterEach(() => {
  vi.restoreAllMocks()
})

function mockManifestResponse(body: unknown) {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    json: async () => body,
  } as Response)
}

describe("VersionedSnapshotsPanel", () => {
  it("renders entries when the manifest endpoint returns data", async () => {
    mockManifestResponse(FIXTURE)
    render(<VersionedSnapshotsPanel ticker="NTPC.NS" currency="INR" />)
    await waitFor(() => {
      expect(
        screen.getByText(/Cohort-wide weighting refresh/),
      ).toBeInTheDocument()
    })
    expect(
      screen.getByText(/Added compounded growth metric/),
    ).toBeInTheDocument()
    // Counter reflects total entries.
    expect(screen.getByText(/5 of 5/)).toBeInTheDocument()
  })

  it("filters by from-date", async () => {
    mockManifestResponse(FIXTURE)
    render(<VersionedSnapshotsPanel ticker="NTPC.NS" currency="INR" />)
    await waitFor(() => screen.getByText(/Cohort-wide weighting refresh/))

    const fromInput = screen.getByLabelText(/Filter from date/i) as HTMLInputElement
    fireEvent.change(fromInput, { target: { value: "2026-05-01" } })

    // Only the May entry remains.
    await waitFor(() => {
      expect(
        screen.queryByText(/Migration anchor entry/),
      ).not.toBeInTheDocument()
    })
    expect(
      screen.getByText(/Cohort-wide weighting refresh/),
    ).toBeInTheDocument()
    expect(screen.getByText(/1 of 5/)).toBeInTheDocument()
  })

  it("filters by to-date inclusively", async () => {
    mockManifestResponse(FIXTURE)
    render(<VersionedSnapshotsPanel ticker="NTPC.NS" currency="INR" />)
    await waitFor(() => screen.getByText(/Cohort-wide weighting refresh/))

    const toInput = screen.getByLabelText(/Filter to date/i) as HTMLInputElement
    fireEvent.change(toInput, { target: { value: "2026-03-31" } })

    // Two pre-April entries remain.
    await waitFor(() => {
      expect(screen.getByText(/Migration anchor entry/)).toBeInTheDocument()
    })
    expect(screen.getByText(/2 of 5/)).toBeInTheDocument()
    expect(
      screen.queryByText(/Cohort-wide weighting refresh/),
    ).not.toBeInTheDocument()
  })

  it("filters by field chip and toggles active state", async () => {
    mockManifestResponse(FIXTURE)
    render(<VersionedSnapshotsPanel ticker="NTPC.NS" currency="INR" />)
    await waitFor(() => screen.getByText(/Cohort-wide weighting refresh/))

    // Click the "verdict" field chip in the filter row.
    const verdictChips = screen.getAllByRole("button", { name: "verdict" })
    fireEvent.click(verdictChips[0])

    await waitFor(() => {
      expect(screen.getByText(/Tightened the overvalued band/)).toBeInTheDocument()
    })
    expect(
      screen.queryByText(/Cohort-wide weighting refresh/),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/1 of 5/)).toBeInTheDocument()

    // Clicking the same chip again clears the filter.
    fireEvent.click(verdictChips[0])
    await waitFor(() => {
      expect(
        screen.getByText(/Cohort-wide weighting refresh/),
      ).toBeInTheDocument()
    })
    expect(screen.getByText(/5 of 5/)).toBeInTheDocument()
  })

  it("renders a Diff button when fv_history brackets the entry", async () => {
    mockManifestResponse(FIXTURE)
    // Reset so the rich fixture is the only resolver — the default
    // EMPTY resolver from beforeEach can race with mockResolvedValueOnce
    // depending on the vitest impl version.
    getFVHistoryMock.mockReset()
    getFVHistoryMock.mockResolvedValue(FV_HISTORY_RICH)
    render(<VersionedSnapshotsPanel ticker="NTPC.NS" currency="INR" />)

    await waitFor(() => {
      expect(
        screen.getByText(/Cohort-wide weighting refresh/),
      ).toBeInTheDocument()
    })
    // FV-history fetch resolves on a separate microtask — wait for at
    // least one Diff button to appear (multiple entries may pair).
    await waitFor(
      () => {
        expect(
          screen.getAllByRole("button", { name: /^Diff$/ }).length,
        ).toBeGreaterThan(0)
      },
      { timeout: 3000 },
    )
    const diffButtons = screen.getAllByRole("button", { name: /^Diff$/ })
    fireEvent.click(diffButtons[0])

    // The numeric before -> after FV pair renders.
    await waitFor(() => {
      expect(screen.getAllByText(/Fair value:/).length).toBeGreaterThan(0)
    })
    // Direction arrow + percent change shown for at least one entry.
    expect(screen.getAllByText(/%/).length).toBeGreaterThan(0)
  })

  it("does not render a Diff button when fv_history is empty", async () => {
    mockManifestResponse(FIXTURE)
    // getFVHistoryMock is already FV_HISTORY_EMPTY from beforeEach.
    render(<VersionedSnapshotsPanel ticker="NTPC.NS" currency="INR" />)
    await waitFor(() => {
      expect(
        screen.getByText(/Cohort-wide weighting refresh/),
      ).toBeInTheDocument()
    })
    // Give the FV-history promise a tick to resolve.
    await new Promise((r) => setTimeout(r, 0))
    expect(
      screen.queryByRole("button", { name: /^Diff$/ }),
    ).not.toBeInTheDocument()
  })

  it("shows empty state when the manifest is empty", async () => {
    mockManifestResponse({ ticker: "UNKNOWN.NS", entries: [] })
    render(<VersionedSnapshotsPanel ticker="UNKNOWN.NS" />)
    await waitFor(() => {
      expect(
        screen.getByText(/No model updates have applied to this ticker/),
      ).toBeInTheDocument()
    })
    // No filter row in the empty state.
    expect(screen.queryByLabelText(/Filter from date/i)).not.toBeInTheDocument()
  })

  it("shows a filter-no-match state when filters exclude everything", async () => {
    mockManifestResponse(FIXTURE)
    render(<VersionedSnapshotsPanel ticker="NTPC.NS" currency="INR" />)
    await waitFor(() => screen.getByText(/Cohort-wide weighting refresh/))

    const fromInput = screen.getByLabelText(/Filter from date/i) as HTMLInputElement
    fireEvent.change(fromInput, { target: { value: "2030-01-01" } })

    await waitFor(() => {
      expect(
        screen.getByText(/No entries match the current filters/),
      ).toBeInTheDocument()
    })
    expect(screen.getByText(/0 of 5/)).toBeInTheDocument()
  })

  it("renders a loading placeholder before the manifest resolves", () => {
    fetchMock.mockReturnValueOnce(new Promise(() => {}))
    render(<VersionedSnapshotsPanel ticker="NTPC.NS" />)
    expect(
      screen.getByText(/Loading model update history/i),
    ).toBeInTheDocument()
  })

  it("expands and collapses long rationales via the inline more/less toggle", async () => {
    mockManifestResponse(FIXTURE)
    render(<VersionedSnapshotsPanel ticker="NTPC.NS" currency="INR" />)
    await waitFor(() => screen.getByText(/Cohort-wide weighting refresh/))

    // Long copy is truncated initially.
    expect(screen.getByText(/This entry is intentionally long/)).toBeInTheDocument()
    // Toggle to "more".
    const moreBtn = screen.getByRole("button", { name: /^more$/ })
    fireEvent.click(moreBtn)
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /^less$/ }),
      ).toBeInTheDocument()
    })
    // Full text now visible.
    expect(
      screen.getByText(/exercise the truncation logic in the test environment/),
    ).toBeInTheDocument()
  })

  it("Clear button resets all filters", async () => {
    mockManifestResponse(FIXTURE)
    render(<VersionedSnapshotsPanel ticker="NTPC.NS" currency="INR" />)
    await waitFor(() => screen.getByText(/Cohort-wide weighting refresh/))

    const fromInput = screen.getByLabelText(/Filter from date/i) as HTMLInputElement
    fireEvent.change(fromInput, { target: { value: "2026-05-01" } })
    await waitFor(() => screen.getByText(/1 of 5/))

    const clearBtn = screen.getByRole("button", { name: /^Clear$/ })
    fireEvent.click(clearBtn)

    await waitFor(() => screen.getByText(/5 of 5/))
    expect(fromInput.value).toBe("")
  })

  it(
    "SEBI guard: rendered DOM contains none of the banned verdict tokens " +
      "(per CLAUDE.md rule #5, list built from fragments at runtime)",
    async () => {
      // Pattern B from CLAUDE.md: fragments concatenated at runtime so
      // the literal tokens never appear on a source line, keeping the
      // sebi-lint --diff-only scan clean. The assertion at runtime is
      // identical to a literal-array implementation.
      const BANNED = [
        "b" + "uy",
        "se" + "ll",
        "ho" + "ld",
        "stro" + "ng b" + "uy",
        "stro" + "ng se" + "ll",
        "rec" + "ommend",
        "tar" + "get pri" + "ce",
      ]
      mockManifestResponse(FIXTURE)
      const { container } = render(
        <VersionedSnapshotsPanel ticker="NTPC.NS" currency="INR" />,
      )
      await waitFor(() => screen.getByText(/Cohort-wide weighting refresh/))
      const text = (container.textContent || "").toLowerCase()
      for (const word of BANNED) {
        expect(text).not.toMatch(new RegExp(`\\b${word}\\b`))
      }
      // Sanity: panel header is what we asserted on.
      const panel = within(container).getByTestId("versioned-snapshots-panel")
      expect(panel).toBeTruthy()
    },
  )
})
