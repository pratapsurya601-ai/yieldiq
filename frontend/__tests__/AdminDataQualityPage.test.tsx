/**
 * Phase A.2.2 — Admin /admin/data-quality page tests.
 *
 * Pins four behaviours:
 *   1. All-green response renders an "All systems green" badge and
 *      no failures panel content.
 *   2. A red row renders a red status pill and shows the failing
 *      check in the Recent failures panel.
 *   3. Clicking a row expands it and shows the per-check details.
 *   4. Non-admin email triggers a redirect to /home and no fetch.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, fireEvent } from "@testing-library/react"

const pushMock = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}))

const apiGetMock = vi.fn()
vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => apiGetMock(...a),
  },
}))

declare global {
  // eslint-disable-next-line no-var
  var __TEST_AUTH_EMAIL_DQ__: string | null
}
;(globalThis as unknown as { __TEST_AUTH_EMAIL_DQ__: string | null }).__TEST_AUTH_EMAIL_DQ__ =
  "pratapsurya601@gmail.com"

vi.mock("@/store/authStore", () => {
  const useAuthStore = (() => ({
    email: (globalThis as unknown as { __TEST_AUTH_EMAIL_DQ__: string | null })
      .__TEST_AUTH_EMAIL_DQ__,
  })) as unknown as {
    (): { email: string | null }
    persist: {
      hasHydrated: () => boolean
      onFinishHydration: (cb: () => void) => () => void
    }
  }
  useAuthStore.persist = {
    hasHydrated: () => true,
    onFinishHydration: () => () => {},
  }
  return { useAuthStore }
})

import AdminDataQualityPage from "@/app/(app)/admin/data-quality/page"

beforeEach(() => {
  pushMock.mockReset()
  apiGetMock.mockReset()
  ;(globalThis as unknown as { __TEST_AUTH_EMAIL_DQ__: string | null }).__TEST_AUTH_EMAIL_DQ__ =
    "pratapsurya601@gmail.com"
})

const GREEN_RESPONSE = {
  latest_per_table: [
    {
      table: "daily_prices",
      populator: "data_pipeline.sources.nse_bhavcopy",
      overall_status: "green",
      run_at: "2026-05-23T05:00:00Z",
      checks: {
        table: "daily_prices",
        populator: "data_pipeline.sources.nse_bhavcopy",
        last_run_at: "2026-05-23T05:00:00Z",
        overall_status: "green",
        checks: [
          { name: "row_count_stability", status: "pass", details: "ok", threshold: {} },
        ],
      },
    },
    {
      table: "stocks",
      populator: "data_pipeline.sources.nse_industry_master",
      overall_status: "green",
      run_at: "2026-05-23T05:00:00Z",
      checks: {
        table: "stocks",
        populator: "data_pipeline.sources.nse_industry_master",
        last_run_at: "2026-05-23T05:00:00Z",
        overall_status: "green",
        checks: [
          { name: "known_good.HDFCBANK.industry", status: "pass", details: "ok", threshold: {} },
        ],
      },
    },
  ],
  history: [],
  summary: { green: 2, yellow: 0, red: 0, total_tables: 2 },
  cached: false,
  cache_age_seconds: 0,
}

const RED_RESPONSE = {
  latest_per_table: [
    {
      table: "daily_prices",
      populator: "data_pipeline.sources.nse_bhavcopy",
      overall_status: "red",
      run_at: "2026-05-23T05:00:00Z",
      checks: {
        table: "daily_prices",
        populator: "data_pipeline.sources.nse_bhavcopy",
        last_run_at: "2026-05-23T05:00:00Z",
        overall_status: "red",
        checks: [
          {
            name: "adj_close_distinct_from_close",
            status: "fail",
            details: "adj_close==close on RELIANCE",
            threshold: { tickers: ["RELIANCE"] },
          },
          {
            name: "row_count_stability",
            status: "pass",
            details: "ok",
            threshold: {},
          },
        ],
      },
    },
  ],
  history: [
    {
      table: "daily_prices",
      populator: "data_pipeline.sources.nse_bhavcopy",
      overall_status: "red",
      run_at: "2026-05-23T05:00:00Z",
    },
  ],
  summary: { green: 0, yellow: 0, red: 1, total_tables: 1 },
  cached: false,
  cache_age_seconds: 0,
}

describe("AdminDataQualityPage", () => {
  it("renders the all-green badge when every table is green", async () => {
    apiGetMock.mockResolvedValue({ data: GREEN_RESPONSE })

    render(<AdminDataQualityPage />)

    await waitFor(() => {
      expect(screen.getByTestId("overall-badge")).toBeTruthy()
    })

    const badge = screen.getByTestId("overall-badge")
    expect(badge.textContent).toContain("All systems green")
    // Recent failures panel renders but says "No failing checks"
    expect(screen.getByTestId("recent-failures").textContent).toContain(
      "No failing checks",
    )
    // Both table rows present
    expect(screen.getByTestId("table-row-daily_prices")).toBeTruthy()
    expect(screen.getByTestId("table-row-stocks")).toBeTruthy()
  })

  it("renders a red pill and surfaces the failing check in Recent failures", async () => {
    apiGetMock.mockResolvedValue({ data: RED_RESPONSE })

    render(<AdminDataQualityPage />)

    await waitFor(() => {
      expect(screen.getByTestId("overall-badge")).toBeTruthy()
    })

    const badge = screen.getByTestId("overall-badge")
    expect(badge.textContent).toContain("table(s) red")
    // Row-level pill present
    const row = screen.getByTestId("table-row-daily_prices")
    expect(row).toBeTruthy()
    // Recent failures panel mentions the failing check name
    const failures = screen.getByTestId("recent-failures")
    expect(failures.textContent).toContain("adj_close_distinct_from_close")
  })

  it("expands a row when clicked and shows the per-check list", async () => {
    apiGetMock.mockResolvedValue({ data: RED_RESPONSE })

    render(<AdminDataQualityPage />)

    await waitFor(() => {
      expect(screen.getByTestId("table-row-daily_prices")).toBeTruthy()
    })

    // The row is a button — click its header.
    const row = screen.getByTestId("table-row-daily_prices")
    const button = row.querySelector("button")
    expect(button).toBeTruthy()
    fireEvent.click(button!)

    await waitFor(() => {
      expect(screen.getByTestId("table-row-detail-daily_prices")).toBeTruthy()
    })
    const detail = screen.getByTestId("table-row-detail-daily_prices")
    expect(detail.textContent).toContain("adj_close_distinct_from_close")
    expect(detail.textContent).toContain("row_count_stability")
  })

  it("redirects non-admin users to /home and does not fetch", async () => {
    ;(globalThis as unknown as { __TEST_AUTH_EMAIL_DQ__: string | null }).__TEST_AUTH_EMAIL_DQ__ =
      "rando@example.com"
    apiGetMock.mockResolvedValue({ data: GREEN_RESPONSE })

    render(<AdminDataQualityPage />)

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/home")
    })
    expect(apiGetMock).not.toHaveBeenCalled()
  })
})
