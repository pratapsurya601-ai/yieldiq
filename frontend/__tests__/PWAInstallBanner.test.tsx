/**
 * Day-100a (2026-05-22) — PWAInstallBanner gating + iOS fallback tests.
 *
 * Pins five behaviours:
 *   1. Already-installed (matchMedia standalone) renders null.
 *   2. Dismissed within the 30-day TTL renders null.
 *   3. Dismissed > 30 days ago re-renders the banner.
 *   4. iOS UA with no beforeinstallprompt within 3s falls back to the
 *      "Share → Add to Home Screen" hint variant.
 *   5. Android happy path: beforeinstallprompt fires → install variant.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, act } from "@testing-library/react"

// Mock the analytics helper so we don't fire real sendBeacon in jsdom.
vi.mock("@/lib/pwaAnalytics", () => ({
  trackPwaEvent: vi.fn(),
}))

import PWAInstallBanner from "@/components/PWAInstallBanner"

const ANDROID_UA =
  "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
const IOS_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"

function setUserAgent(ua: string) {
  Object.defineProperty(window.navigator, "userAgent", {
    value: ua,
    configurable: true,
  })
}

function setStandalone(value: boolean | undefined) {
  Object.defineProperty(window.navigator, "standalone", {
    value,
    configurable: true,
  })
}

function setMatchMediaStandalone(isStandalone: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: isStandalone && query.includes("standalone"),
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

function primeViews(count = 3) {
  localStorage.setItem("yieldiq_pwa_views", String(count - 1))
  // Banner increments before the gate, so seeding `count - 1` lands us
  // at exactly `count` on first render.
}

beforeEach(() => {
  localStorage.clear()
  setMatchMediaStandalone(false)
  setStandalone(false)
})

afterEach(() => {
  vi.useRealTimers()
})

describe("PWAInstallBanner", () => {
  it("renders nothing when running standalone (already installed)", () => {
    setUserAgent(ANDROID_UA)
    setMatchMediaStandalone(true)
    primeViews()

    const { container } = render(<PWAInstallBanner />)
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when dismissed within the 30-day TTL", () => {
    setUserAgent(ANDROID_UA)
    primeViews()
    // Dismissed five minutes ago.
    localStorage.setItem(
      "yieldiq_pwa_dismiss",
      String(Date.now() - 5 * 60 * 1000),
    )

    const { container } = render(<PWAInstallBanner />)
    expect(container).toBeEmptyDOMElement()
  })

  it("re-renders the banner when dismissal is older than 30 days", () => {
    vi.useFakeTimers()
    setUserAgent(IOS_UA)
    primeViews()
    // Dismissed 31 days ago.
    localStorage.setItem(
      "yieldiq_pwa_dismiss",
      String(Date.now() - 31 * 864e5),
    )

    render(<PWAInstallBanner />)
    // iOS path: advance past the 3s fallback timer.
    act(() => {
      vi.advanceTimersByTime(3100)
    })
    expect(
      screen.getByText(/Add YieldIQ to Home Screen/i),
    ).toBeInTheDocument()
  })

  it("shows the iOS hint variant when beforeinstallprompt never fires", () => {
    vi.useFakeTimers()
    setUserAgent(IOS_UA)
    primeViews()

    render(<PWAInstallBanner />)
    // Before the 3s timer, nothing renders.
    expect(screen.queryByText(/Add to Home Screen/i)).not.toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(3100)
    })

    // iOS variant uses the Share-icon copy "Tap ... then Add to Home Screen".
    expect(screen.getByText(/then Add to Home Screen/i)).toBeInTheDocument()
    // The install button only exists on the Chromium variant.
    expect(screen.queryByRole("button", { name: /^Install$/ })).toBeNull()
  })

  it("shows the install variant on Android when beforeinstallprompt fires", () => {
    setUserAgent(ANDROID_UA)
    primeViews()

    render(<PWAInstallBanner />)

    act(() => {
      const evt = new Event("beforeinstallprompt") as Event & {
        prompt: () => Promise<void>
        userChoice: Promise<{ outcome: "accepted" | "dismissed" }>
      }
      evt.prompt = () => Promise.resolve()
      evt.userChoice = Promise.resolve({ outcome: "accepted" as const })
      window.dispatchEvent(evt)
    })

    expect(
      screen.getByRole("button", { name: /^Install$/ }),
    ).toBeInTheDocument()
  })
})
