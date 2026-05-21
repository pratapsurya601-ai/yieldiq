/**
 * Day-77 (2026-05-22) — WatchlistButton smoke tests.
 *
 * Pins three behaviours of the Day-32 component:
 *   1. All three variants (default / compact / icon-only) render with
 *      the expected affordance and aria state.
 *   2. Click on an authenticated mount calls POST /api/v1/watchlist/
 *      with the bare ticker (the .NS suffix must be stripped before
 *      hitting the backend — the SQLite fallback path expects bare).
 *   3. Unauthenticated click routes to /auth/login with a return_to
 *      query param instead of firing the API.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"

// ── Mocks (must precede the import of the component under test) ──
const pushMock = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}))

const apiGetMock = vi.fn()
const apiPostMock = vi.fn()
const apiDeleteMock = vi.fn()
vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => apiGetMock(...a),
    post: (...a: unknown[]) => apiPostMock(...a),
    delete: (...a: unknown[]) => apiDeleteMock(...a),
  },
}))

let storeToken: string | null = "test-token"
vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (s: { token: string | null }) => unknown) =>
    selector({ token: storeToken }),
}))

// Imported after the mocks above so the component picks them up.
import WatchlistButton from "@/components/watchlist/WatchlistButton"

beforeEach(() => {
  pushMock.mockReset()
  apiGetMock.mockReset()
  apiPostMock.mockReset()
  apiDeleteMock.mockReset()
  storeToken = "test-token"
  apiGetMock.mockResolvedValue({ data: { in_watchlist: false } })
  apiPostMock.mockResolvedValue({ data: { ok: true } })
})

describe("WatchlistButton", () => {
  it("renders all three variants with the expected affordance", () => {
    const { unmount: u1 } = render(
      <WatchlistButton ticker="RELIANCE.NS" initialInWatchlist={false} />,
    )
    // compact (default variant) shows "Save" text.
    expect(screen.getByTestId("watchlist-button").textContent).toContain("Save")
    u1()

    const { unmount: u2 } = render(
      <WatchlistButton
        ticker="RELIANCE.NS"
        variant="default"
        initialInWatchlist={false}
      />,
    )
    expect(screen.getByTestId("watchlist-button").textContent).toContain(
      "Add to watchlist",
    )
    u2()

    render(
      <WatchlistButton
        ticker="RELIANCE.NS"
        variant="icon-only"
        initialInWatchlist={false}
      />,
    )
    const iconBtn = screen.getByTestId("watchlist-button")
    // icon-only has no visible text label; aria-label carries it.
    expect(iconBtn.textContent?.trim()).toBe("")
    expect(iconBtn.getAttribute("aria-label")).toBe("Add to watchlist")
  })

  it("strips the .NS suffix and POSTs the bare ticker on click", async () => {
    render(
      <WatchlistButton
        ticker="RELIANCE.NS"
        companyName="Reliance Industries"
        initialInWatchlist={false}
      />,
    )

    fireEvent.click(screen.getByTestId("watchlist-button"))

    await waitFor(() => {
      expect(apiPostMock).toHaveBeenCalledTimes(1)
    })
    expect(apiPostMock).toHaveBeenCalledWith("/api/v1/watchlist/", {
      ticker: "RELIANCE",
      company_name: "Reliance Industries",
    })
    // Optimistic flip — button should now report aria-pressed=true.
    expect(
      screen.getByTestId("watchlist-button").getAttribute("aria-pressed"),
    ).toBe("true")
  })

  it("routes unauthenticated users to /auth/login instead of firing the API", () => {
    storeToken = null
    // jsdom default location is http://localhost/ — pin a pathname so the
    // return_to encoding has something to bite on.
    window.history.replaceState({}, "", "/analysis/RELIANCE")

    render(
      <WatchlistButton ticker="RELIANCE.NS" initialInWatchlist={false} />,
    )
    fireEvent.click(screen.getByTestId("watchlist-button"))

    expect(apiPostMock).not.toHaveBeenCalled()
    expect(pushMock).toHaveBeenCalledTimes(1)
    const target = pushMock.mock.calls[0][0] as string
    expect(target.startsWith("/auth/login?return_to=")).toBe(true)
    expect(target).toContain(encodeURIComponent("/analysis/RELIANCE"))
  })
})
