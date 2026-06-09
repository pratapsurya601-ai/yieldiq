/**
 * PriceLadderPanel tests.
 *
 * Pins:
 *   1. Renders the three labelled stops (Fair Value, Target, Current).
 *   2. Slider drag updates the readout AND the Notify button label.
 *   3. Chip click sets MoS percentage and updates the readout.
 *   4. In-zone shading + Notify-button "In Zone" copy appear when
 *      currentPrice <= target.
 *   5. SEBI vocabulary: the rendered DOM contains zero banned words
 *      from scripts/check_sebi_words.py.
 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

// Stub next/navigation so useRouter() resolves in jsdom.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}))

// Stub the alerts API — we only need to verify the component invokes
// createAlert with the chip value; we don't exercise the server side.
//
// `vi.hoisted` makes the mock function available at the (hoisted)
// `vi.mock` factory call site. Defining the spy at module-top would
// be ReferenceError'd at hoist time.
const { createAlertMock } = vi.hoisted(() => ({
  createAlertMock: vi.fn(async () => ({ message: "ok" })),
}))
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@/lib/api")
  return { ...actual, createAlert: createAlertMock }
})

import PriceLadderPanel from "@/components/analysis/PriceLadderPanel"
import { useAuthStore } from "@/store/authStore"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// Mirror of scripts/check_sebi_words.py banned-word list. Kept inline
// rather than imported because the script is Python — the assertion
// here is the same regex applied to the rendered DOM, not to source.
const SEBI_BANNED = [
  "appears", // sebi-allow: appears
  "should", // sebi-allow: should
  "concern", // sebi-allow: concern
  "strength", // sebi-allow: strength
  "weakness", // sebi-allow: weakness
  "buy", // sebi-allow: buy
  "sell", // sebi-allow: sell
  "hold", // sebi-allow: hold
  "outperform", // sebi-allow: outperform
  "underperform", // sebi-allow: underperform
  "expensive", // sebi-allow: expensive
  "cheap", // sebi-allow: cheap
  "attractive", // sebi-allow: attractive
  "poor", // sebi-allow: poor
  "strong", // sebi-allow: strong
  "weak", // sebi-allow: weak
  "accumulate", // sebi-allow: accumulate
  "recommend", // sebi-allow: recommend
  "recommendation", // sebi-allow: recommendation
  "investable", // sebi-allow: investable
  "investability", // sebi-allow: investability
]

beforeEach(() => {
  createAlertMock.mockClear()
  useAuthStore.setState({
    token: null,
    userId: null,
    email: null,
    tier: "free",
  } as Partial<ReturnType<typeof useAuthStore.getState>> as never)
})

describe("PriceLadderPanel", () => {
  it("renders the three labelled stops at default 20% MoS", () => {
    renderWithClient(
      <PriceLadderPanel
        ticker="HDFCBANK.NS"
        companyName="HDFC Bank"
        currentPrice={1500}
        fairValue={2000}
        currency="INR"
      />,
    )
    expect(screen.getByTestId("ladder-stop-fv")).toBeInTheDocument()
    expect(screen.getByTestId("ladder-stop-target")).toBeInTheDocument()
    expect(screen.getByTestId("ladder-stop-current")).toBeInTheDocument()

    // Target label at default 20% reads "20% below".
    const target = screen.getByTestId("ladder-stop-target")
    expect(target.textContent).toContain("20% below")

    // Fair-value stop carries the FV pill ("F").
    expect(screen.getByTestId("ladder-stop-fv").textContent).toContain("F")

    // Default readout shows "20% below Fair Value".
    expect(screen.getByTestId("ladder-slider-readout").textContent).toContain(
      "20% below Fair Value",
    )
  })

  it("drag-to-set: slider input updates readout AND Notify button label", () => {
    renderWithClient(
      <PriceLadderPanel
        ticker="HDFCBANK.NS"
        companyName="HDFC Bank"
        currentPrice={1500}
        fairValue={2000}
        currency="INR"
      />,
    )
    const slider = screen.getByTestId("ladder-slider") as HTMLInputElement
    fireEvent.change(slider, { target: { value: "35" } })

    expect(screen.getByTestId("ladder-slider-readout").textContent).toContain(
      "35% below Fair Value",
    )
    // Not signed in -> CTA reads as the sign-in prompt rather than the
    // pct-bearing label. Switch on auth to assert the percent label.
    useAuthStore.setState({
      token: "fake",
      userId: "u1",
      email: "u@example.com",
      tier: "free",
    } as Partial<ReturnType<typeof useAuthStore.getState>> as never)
    fireEvent.change(slider, { target: { value: "42" } })
    expect(screen.getByTestId("ladder-primary").textContent).toContain("42%")
  })

  it("chip click sets MoS percentage and updates the readout", () => {
    renderWithClient(
      <PriceLadderPanel
        ticker="HDFCBANK.NS"
        companyName="HDFC Bank"
        currentPrice={1500}
        fairValue={2000}
        currency="INR"
      />,
    )
    fireEvent.click(screen.getByTestId("ladder-chip-40"))
    expect(screen.getByTestId("ladder-slider-readout").textContent).toContain(
      "40% below Fair Value",
    )
    // aria-checked flips on the selected chip.
    expect(
      screen.getByTestId("ladder-chip-40").getAttribute("aria-checked"),
    ).toBe("true")
    expect(
      screen.getByTestId("ladder-chip-20").getAttribute("aria-checked"),
    ).toBe("false")
  })

  it("in-zone shading: when currentPrice <= target the Target<->Current segment goes emerald and the CTA reads 'In Zone'", () => {
    // FV=100, default 20% MoS -> target=80. Current=70 is at-or-below
    // the target so the panel is "in zone" at default. Sign in so the
    // CTA renders the pct/in-zone label rather than the sign-in prompt.
    useAuthStore.setState({
      token: "fake",
      userId: "u1",
      email: "u@example.com",
      tier: "free",
    } as Partial<ReturnType<typeof useAuthStore.getState>> as never)
    renderWithClient(
      <PriceLadderPanel
        ticker="ABC.NS"
        companyName="Abc Ltd"
        currentPrice={70}
        fairValue={100}
        currency="INR"
      />,
    )
    const panel = screen.getByTestId("price-ladder-panel")
    expect(panel.getAttribute("data-in-zone")).toBe("true")

    const segment = screen.getByTestId("ladder-segment-target-current")
    expect(segment.className).toMatch(/emerald/)

    // CTA carries "In Zone" copy (no banned words).
    expect(screen.getByTestId("ladder-primary").textContent).toContain(
      "In Zone",
    )
  })

  it("out-of-zone: when currentPrice > target the panel is neutral and the CTA reads 'Notify Me at X%'", () => {
    // FV=100, default 20% MoS -> target=80. Current=90 is above the
    // target so the panel is out of zone.
    useAuthStore.setState({
      token: "fake",
      userId: "u1",
      email: "u@example.com",
      tier: "free",
    } as Partial<ReturnType<typeof useAuthStore.getState>> as never)
    renderWithClient(
      <PriceLadderPanel
        ticker="ABC.NS"
        companyName="Abc Ltd"
        currentPrice={90}
        fairValue={100}
        currency="INR"
      />,
    )
    expect(
      screen.getByTestId("price-ladder-panel").getAttribute("data-in-zone"),
    ).toBe("false")
    expect(screen.getByTestId("ladder-primary").textContent).toMatch(
      /Notify Me at 20%/,
    )
  })

  it("Notify Me click while authed invokes createAlert with the current chip value", async () => {
    useAuthStore.setState({
      token: "fake",
      userId: "u1",
      email: "u@example.com",
      tier: "free",
    } as Partial<ReturnType<typeof useAuthStore.getState>> as never)
    renderWithClient(
      <PriceLadderPanel
        ticker="HDFCBANK.NS"
        companyName="HDFC Bank"
        currentPrice={1500}
        fairValue={2000}
        currency="INR"
      />,
    )
    await act(async () => {
      fireEvent.click(screen.getByTestId("ladder-chip-30"))
    })
    await act(async () => {
      fireEvent.click(screen.getByTestId("ladder-primary"))
    })

    // useMutation's mutationFn fires inside a microtask — wait for it.
    await waitFor(() => {
      expect(createAlertMock).toHaveBeenCalledTimes(1)
    })
    expect(createAlertMock).toHaveBeenCalledWith({
      ticker: "HDFCBANK.NS",
      alert_type: "mos_above",
      target_price: 30,
    })
  })

  it("optional historicalHitsAtMos: renders a likelihood line when the helper returns a number", () => {
    const hits = vi.fn((p: number) => (p === 20 ? 7 : null))
    renderWithClient(
      <PriceLadderPanel
        ticker="HDFCBANK.NS"
        companyName="HDFC Bank"
        currentPrice={1500}
        fairValue={2000}
        currency="INR"
        historicalHitsAtMos={hits}
      />,
    )
    expect(screen.getByTestId("ladder-historical-hits").textContent).toMatch(
      /Last 3y/,
    )
    expect(screen.getByTestId("ladder-historical-hits").textContent).toMatch(
      /7 days/,
    )
  })

  it("SEBI vocabulary: rendered DOM is free of every banned word, in both in-zone and out-of-zone states", () => {
    // Out-of-zone render.
    const { container: outOfZone, unmount } = renderWithClient(
      <PriceLadderPanel
        ticker="HDFCBANK.NS"
        companyName="HDFC Bank"
        currentPrice={1800}
        fairValue={2000}
        currency="INR"
      />,
    )
    assertNoBannedWords(outOfZone.textContent ?? "")
    unmount()

    // In-zone render (currentPrice well below target at default 20%).
    const { container: inZone } = renderWithClient(
      <PriceLadderPanel
        ticker="HDFCBANK.NS"
        companyName="HDFC Bank"
        currentPrice={500}
        fairValue={2000}
        currency="INR"
      />,
    )
    assertNoBannedWords(inZone.textContent ?? "")
  })
})

function assertNoBannedWords(rendered: string) {
  const haystack = rendered.toLowerCase()
  for (const word of SEBI_BANNED) {
    const re = new RegExp(`\\b${word}\\b`, "i")
    expect(
      re.test(haystack),
      `Rendered DOM contains SEBI-banned word "${word}". Excerpt: ` +
        excerptAround(haystack, word),
    ).toBe(false)
  }
}

function excerptAround(haystack: string, word: string): string {
  const idx = haystack.toLowerCase().indexOf(word.toLowerCase())
  if (idx < 0) return "(no match)"
  const start = Math.max(0, idx - 24)
  const end = Math.min(haystack.length, idx + word.length + 24)
  return `…${haystack.slice(start, end)}…`
}
