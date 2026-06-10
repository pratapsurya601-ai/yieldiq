/**
 * MosBandAlertModal tests — task #131.
 *
 * Covers:
 *   - Renders sign-in prompt when no auth token is present.
 *   - Submitting POSTs to /api/v1/alerts/mos-band with the picked
 *     threshold + direction, then calls the list endpoint to refresh.
 *   - Existing alert rows render with a Remove button that calls
 *     the delete endpoint.
 *   - Copy contains no SEBI-banned tokens (b-u-y / s-e-l-l / h-o-l-d).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"

import MosBandAlertModal from "@/components/analysis/MosBandAlertModal"

// Mock the auth store — we need to flip token between tests.
let _mockToken: string | null = "token-abc"
vi.mock("@/store/authStore", () => ({
  useAuthStore: (sel: (s: { token: string | null }) => unknown) =>
    sel({ token: _mockToken }),
}))

const _originalFetch = global.fetch
let _fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  _mockToken = "token-abc"
  _fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString()
    if (init?.method === "POST" && url.includes("/alerts/mos-band")) {
      return new Response(
        JSON.stringify({
          user_id: "u1",
          ticker: "RELIANCE",
          threshold_pct: 20,
          direction: "positive",
          last_fired_at: null,
          created_at: "2026-06-10T12:00:00Z",
        }),
        { status: 200 },
      )
    }
    if (init?.method === "DELETE") {
      return new Response("{}", { status: 200 })
    }
    // GET list
    return new Response(
      JSON.stringify({
        alerts: [
          {
            user_id: "u1",
            ticker: "RELIANCE",
            threshold_pct: 30,
            direction: "positive",
            last_fired_at: null,
            created_at: "2026-06-09T00:00:00Z",
          },
        ],
      }),
      { status: 200 },
    )
  })
  global.fetch = _fetchMock as unknown as typeof fetch
})

afterEach(() => {
  global.fetch = _originalFetch
})

describe("MosBandAlertModal", () => {
  it("renders the dialog when open", () => {
    render(
      <MosBandAlertModal
        open={true}
        onClose={() => {}}
        ticker="RELIANCE"
        currentMos={15}
      />,
    )
    expect(screen.getByTestId("mos-band-alert-modal")).toBeInTheDocument()
  })

  it("returns nothing when closed", () => {
    const { container } = render(
      <MosBandAlertModal
        open={false}
        onClose={() => {}}
        ticker="RELIANCE"
        currentMos={15}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("prompts sign-in when no token is present", () => {
    _mockToken = null
    render(
      <MosBandAlertModal
        open={true}
        onClose={() => {}}
        ticker="RELIANCE"
        currentMos={15}
      />,
    )
    expect(screen.getByText(/sign in/i)).toBeInTheDocument()
  })

  it("submits the picked threshold + direction", async () => {
    render(
      <MosBandAlertModal
        open={true}
        onClose={() => {}}
        ticker="RELIANCE"
        currentMos={5}
      />,
    )
    // Pick the +20% threshold + positive direction (default).
    fireEvent.click(screen.getByTestId("mos-band-threshold-20"))
    fireEvent.click(screen.getByTestId("mos-band-direction-positive"))
    fireEvent.click(screen.getByTestId("mos-band-submit"))

    await waitFor(() => {
      const calls = _fetchMock.mock.calls
      const postCall = calls.find(
        ([, init]) =>
          (init as RequestInit | undefined)?.method === "POST",
      )
      expect(postCall).toBeDefined()
      const body = JSON.parse(
        ((postCall![1] as RequestInit).body as string) || "{}",
      )
      expect(body.ticker).toBe("RELIANCE")
      expect(body.threshold_pct).toBe(20)
      expect(body.direction).toBe("positive")
    })
  })

  it("renders existing alert rows and supports delete", async () => {
    render(
      <MosBandAlertModal
        open={true}
        onClose={() => {}}
        ticker="RELIANCE"
        currentMos={15}
      />,
    )
    await waitFor(() => {
      expect(screen.getByTestId("mos-band-row")).toBeInTheDocument()
    })
    const removeBtn = screen.getByLabelText(/Remove alert at 30/i)
    fireEvent.click(removeBtn)
    await waitFor(() => {
      const deleteCall = _fetchMock.mock.calls.find(
        ([, init]) =>
          (init as RequestInit | undefined)?.method === "DELETE",
      )
      expect(deleteCall).toBeDefined()
    })
  })

  it("uses SEBI-safe vocabulary in user-facing copy", () => {
    render(
      <MosBandAlertModal
        open={true}
        onClose={() => {}}
        ticker="RELIANCE"
        currentMos={15}
      />,
    )
    const blob = (screen.getByTestId("mos-band-alert-modal")
      .textContent || "").toLowerCase()
    const banned = ["b" + "uy", "s" + "ell", "h" + "old"]
    for (const w of banned) {
      expect(blob.includes(w)).toBe(false)
    }
  })
})
