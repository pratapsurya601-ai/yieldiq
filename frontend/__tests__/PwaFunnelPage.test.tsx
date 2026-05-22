/**
 * Day-101c (2026-05-22) — PWA install funnel admin dashboard tests.
 *
 * Pins three behaviours of /admin/pwa-funnel:
 *   1. With admin email + mocked funnel data, the three big numbers
 *      (Prompted, Installed, Conversion) render with the right values.
 *   2. The chart container renders when daily_breakdown is non-empty.
 *   3. Non-admin users are redirected to /home and never see data.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"

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

// Recharts depends on ResizeObserver in jsdom; stub a minimal version
// and short-circuit ResponsiveContainer so the chart actually paints
// inside our test height-of-zero environment.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
  ResizeObserverStub

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts")
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="recharts-container" style={{ width: 600, height: 320 }}>
        {children}
      </div>
    ),
  }
})

// Module-level state read by the authStore mock. `vi.mock` hoists the
// factory above imports, so the mock factory itself must only
// reference values defined inside it; we expose a global the test can
// mutate between cases.
declare global {
  // eslint-disable-next-line no-var
  var __TEST_AUTH_EMAIL__: string | null
}
;(globalThis as unknown as { __TEST_AUTH_EMAIL__: string | null }).__TEST_AUTH_EMAIL__ =
  "pratapsurya601@gmail.com"

vi.mock("@/store/authStore", () => {
  const useAuthStore = (() => ({
    email: (globalThis as unknown as { __TEST_AUTH_EMAIL__: string | null })
      .__TEST_AUTH_EMAIL__,
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

import PwaFunnelPage from "@/app/(app)/admin/pwa-funnel/page"

beforeEach(() => {
  pushMock.mockReset()
  apiGetMock.mockReset()
  ;(globalThis as unknown as { __TEST_AUTH_EMAIL__: string | null }).__TEST_AUTH_EMAIL__ =
    "pratapsurya601@gmail.com"
})

const MOCK_DATA = {
  window_days: 7,
  totals: {
    prompted: 100,
    installed: 25,
    dismissed: 40,
    ios_hint_shown: 12,
  },
  conversion_rate: 0.25,
  dismissal_rate: 0.4,
  daily_breakdown: [
    { date: "2026-05-16", prompted: 20, installed: 5, dismissed: 8, ios_hint_shown: 2 },
    { date: "2026-05-17", prompted: 15, installed: 4, dismissed: 6, ios_hint_shown: 3 },
    { date: "2026-05-18", prompted: 18, installed: 6, dismissed: 5, ios_hint_shown: 1 },
  ],
}

describe("PwaFunnelPage", () => {
  it("renders the three big stats with conversion %", async () => {
    apiGetMock.mockResolvedValue({ data: MOCK_DATA })

    render(<PwaFunnelPage />)

    await waitFor(() => {
      expect(screen.getByTestId("pwa-funnel-stats")).toBeTruthy()
    })

    const stats = screen.getByTestId("pwa-funnel-stats")
    expect(stats.textContent).toContain("Prompted (7d)")
    expect(stats.textContent).toContain("100")
    expect(stats.textContent).toContain("Installed (7d)")
    expect(stats.textContent).toContain("25")
    expect(stats.textContent).toContain("Conversion")
    expect(stats.textContent).toContain("25.0%")
    // Dismissal sub-text uses the dismissal_rate value.
    expect(stats.textContent).toContain("40.0%")
  })

  it("renders the recharts chart when daily_breakdown has rows", async () => {
    apiGetMock.mockResolvedValue({ data: MOCK_DATA })

    render(<PwaFunnelPage />)

    await waitFor(() => {
      expect(screen.getByTestId("pwa-funnel-chart")).toBeTruthy()
    })

    const chartWrapper = screen.getByTestId("pwa-funnel-chart")
    // Recharts container stub renders inside our wrapper when data exists.
    expect(chartWrapper.querySelector('[data-testid="recharts-container"]')).toBeTruthy()
    // Table rows for all four event names are present.
    expect(screen.getByText("prompted")).toBeTruthy()
    expect(screen.getByText("installed")).toBeTruthy()
    expect(screen.getByText("dismissed")).toBeTruthy()
    expect(screen.getByText("ios_hint_shown")).toBeTruthy()
  })

  it("redirects non-admin users to /home and does not fetch", async () => {
    ;(globalThis as unknown as { __TEST_AUTH_EMAIL__: string | null }).__TEST_AUTH_EMAIL__ =
      "rando@example.com"
    apiGetMock.mockResolvedValue({ data: MOCK_DATA })

    render(<PwaFunnelPage />)

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/home")
    })
    expect(apiGetMock).not.toHaveBeenCalled()
  })
})
