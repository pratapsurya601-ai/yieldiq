/**
 * Phase J — useSessionTrace hook.
 *
 * Pins the load-bearing invariants:
 *   1. Anonymous (no token / no userId): hook is a no-op. No fetch
 *      goes out even when trackPageView / trackSearch / trackClick
 *      are called.
 *   2. Auth'd: events are buffered and flushed on the 30s interval.
 *   3. classifyLength bucketing is stable (search queries log only
 *      the length class, never the raw text).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { renderHook, act } from "@testing-library/react"

import { useAuthStore } from "@/store/authStore"
import { useSessionTrace, __INTERNAL } from "@/lib/useSessionTrace"

function resetAuth() {
  useAuthStore.setState({
    token: null,
    userId: null,
    email: null,
    tier: "free",
    analysesToday: 0,
    analysisLimit: 5,
    displayName: null,
    displayNameEditsRemaining: 3,
    featureFlags: {},
    emailVerified: true,
  })
}

describe("useSessionTrace — anonymous users", () => {
  beforeEach(() => {
    resetAuth()
    vi.useFakeTimers()
    vi.stubGlobal("fetch", vi.fn())
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it("does not fire fetch when no token / userId", () => {
    const { result } = renderHook(() => useSessionTrace())

    act(() => {
      result.current.trackPageView("/analysis/RELIANCE.NS")
      result.current.trackSearch("RELIANCE")
      result.current.trackClick("expand_dcf")
    })

    // Advance well past the flush interval.
    act(() => {
      vi.advanceTimersByTime(__INTERNAL.FLUSH_INTERVAL_MS * 2)
    })

    expect((fetch as unknown as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled()
  })
})

describe("useSessionTrace — auth'd users", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}")))
    useAuthStore.setState({
      token: "jwt-test-token",
      userId: "u-test",
      email: "u@example.com",
      tier: "free",
      analysesToday: 0,
      analysisLimit: 5,
      displayName: null,
      displayNameEditsRemaining: 3,
      featureFlags: {},
      emailVerified: true,
    })
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    resetAuth()
  })

  it("flushes buffered events on the periodic interval", () => {
    const { result } = renderHook(() => useSessionTrace())
    act(() => {
      result.current.trackPageView("/analysis/RELIANCE.NS")
    })
    // No fetch yet — buffer hasn't flushed.
    expect(fetch).not.toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(__INTERNAL.FLUSH_INTERVAL_MS + 100)
    })

    expect(fetch).toHaveBeenCalledTimes(1)
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe(__INTERNAL.ENDPOINT)
    expect((init as RequestInit).method).toBe("POST")
    const headers = (init as RequestInit).headers as Record<string, string>
    expect(headers.Authorization).toBe("Bearer jwt-test-token")
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body.session_id).toBeTruthy()
    expect(body.events).toHaveLength(1)
    expect(body.events[0].event_type).toBe("page_view")
  })
})

describe("classifyLength bucketing", () => {
  const { classifyLength } = __INTERNAL
  it("buckets correctly", () => {
    expect(classifyLength("")).toBe("empty")
    expect(classifyLength("   ")).toBe("empty")
    expect(classifyLength("AB")).toBe("short")
    expect(classifyLength("RELI")).toBe("medium")
    expect(classifyLength("RELIANCE")).toBe("medium")
    expect(classifyLength("RELIANCE INDUSTRIES")).toBe("long")
  })
})
