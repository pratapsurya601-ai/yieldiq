/**
 * Tests for the /admin/outliers page.
 *
 * Three behaviours pinned here:
 *   1. Table renders when the endpoint returns rows.
 *   2. Empty-state copy renders when count=0.
 *   3. The hydration guard suppresses the redirect on the very first
 *      paint — same fix as hotfix #360 for /admin/realty.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"

// ── Mocks ────────────────────────────────────────────────────────
const pushMock = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}))

const apiGetMock = vi.fn()
vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => apiGetMock(...args) },
}))

// Hydration state lives on `useAuthStore.persist`; we drive it from
// the tests by flipping `hasHydratedFlag` and (when needed) by invoking
// the listener registered through `onFinishHydration`.
let hasHydratedFlag = true
let pendingFinishCb: (() => void) | null = null
let storeState = {
  email: "pratapsurya601@gmail.com" as string | null,
}

vi.mock("@/store/authStore", () => {
  // The page calls `useAuthStore()` as a hook and reads `.persist` off
  // the store function. We expose both.
  const useAuthStore = Object.assign(
    () => storeState,
    {
      persist: {
        hasHydrated: () => hasHydratedFlag,
        onFinishHydration: (cb: () => void) => {
          pendingFinishCb = cb
          return () => {
            pendingFinishCb = null
          }
        },
      },
    },
  )
  return { useAuthStore }
})

// Import after mocks so the page picks them up.
import BenchmarkOutliersAdminPage from "@/app/(app)/admin/outliers/page"
import type { BenchmarkOutliersResponse } from "@/types/admin"

function makeResponse(
  overrides: Partial<BenchmarkOutliersResponse> = {},
): { data: BenchmarkOutliersResponse } {
  return {
    data: {
      generated_at: "2026-05-19T04:30:00Z",
      threshold_pct: 0.3,
      min_analysts: 3,
      direction: "both",
      count: overrides.rows?.length ?? 0,
      rows: [],
      ...overrides,
    },
  }
}

beforeEach(() => {
  pushMock.mockReset()
  apiGetMock.mockReset()
  hasHydratedFlag = true
  pendingFinishCb = null
  storeState = { email: "pratapsurya601@gmail.com" }
})

afterEach(() => {
  vi.clearAllMocks()
})

describe("BenchmarkOutliersAdminPage", () => {
  it("renders the outliers table when the API returns rows", async () => {
    apiGetMock.mockResolvedValueOnce(
      makeResponse({
        rows: [
          {
            ticker: "EXAMPLE.NS",
            sector: "IT",
            our_fv: 100.5,
            consensus_fv: 150.0,
            delta_pct: -0.33,
            direction: "under",
            analyst_count: 8,
            source: "yfinance",
            fetched_at: "2026-05-19T04:30:00Z",
            computed_at: null,
          },
          {
            ticker: "OTHER.NS",
            sector: null,
            our_fv: 600,
            consensus_fv: 300,
            delta_pct: 1.0,
            direction: "over",
            analyst_count: 5,
            source: "finnhub",
            fetched_at: "2026-05-19T04:30:00Z",
            computed_at: null,
          },
        ],
        count: 2,
      }),
    )

    render(<BenchmarkOutliersAdminPage />)

    await waitFor(() => {
      expect(screen.getByTestId("admin-outliers-table")).toBeInTheDocument()
    })
    expect(screen.getByTestId("outlier-row-EXAMPLE.NS")).toBeInTheDocument()
    expect(screen.getByTestId("outlier-row-OTHER.NS")).toBeInTheDocument()
    // High severity (|delta| > 0.5) attaches data-severity=high.
    expect(
      screen.getByTestId("outlier-row-OTHER.NS").getAttribute("data-severity"),
    ).toBe("high")
    // Medium severity (0.3 <= |delta| <= 0.5).
    expect(
      screen
        .getByTestId("outlier-row-EXAMPLE.NS")
        .getAttribute("data-severity"),
    ).toBe("med")

    expect(pushMock).not.toHaveBeenCalled()
    // Default request shape: limit=20, direction=both.
    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/admin/benchmark-outliers?limit=20&direction=both",
    )
  })

  it("shows the empty-state message when zero outliers", async () => {
    apiGetMock.mockResolvedValueOnce(makeResponse({ rows: [], count: 0 }))

    render(<BenchmarkOutliersAdminPage />)

    await waitFor(() => {
      expect(screen.getByTestId("admin-outliers-empty")).toBeInTheDocument()
    })
    expect(screen.getByTestId("admin-outliers-empty").textContent).toMatch(
      /No outliers found/i,
    )
    expect(screen.queryByTestId("admin-outliers-table")).toBeNull()
    expect(pushMock).not.toHaveBeenCalled()
  })

  it("hydration guard blocks redirect on first paint when store is empty", () => {
    // Pre-hydration: store reports no email and hasHydrated()=false.
    // This is exactly the failure mode hotfix #360 patched: without the
    // guard, the email-check effect runs immediately, sees email=null,
    // and bounces a real admin to /home.
    hasHydratedFlag = false
    storeState = { email: null }

    const { container } = render(<BenchmarkOutliersAdminPage />)

    // The guard returns `null` until persist hydration completes, so
    // the page renders nothing — and crucially, never calls router.push.
    expect(pushMock).not.toHaveBeenCalled()
    expect(apiGetMock).not.toHaveBeenCalled()
    expect(container.firstChild).toBeNull()
    // onFinishHydration must have been registered so that real
    // hydration completion will unblock the page.
    expect(pendingFinishCb).not.toBeNull()
  })
})
