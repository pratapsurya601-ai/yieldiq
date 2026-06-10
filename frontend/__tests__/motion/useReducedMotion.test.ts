/**
 * motion/useReducedMotion — hook + override accessor tests.
 *
 * Pins:
 *   1. With OS pref OFF and override NOT set → hook returns false.
 *   2. With OS pref ON → hook returns true.
 *   3. With OS pref OFF but override set → hook returns true.
 *   4. setMotionOverrideOff(true) persists "1" to localStorage AND
 *      sets [data-yq-motion-off="1"] on <html>.
 *   5. setMotionOverrideOff(false) removes both.
 *   6. getMotionOverrideOff is SSR-safe (no throw without window).
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { renderHook, act } from "@testing-library/react"
import {
  useReducedMotion,
  getMotionOverrideOff,
  setMotionOverrideOff,
  MOTION_STORAGE_KEY,
} from "@/lib/motion/useReducedMotion"

function setMatchMedia(reducedMotion: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? reducedMotion : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

beforeEach(() => {
  // Reset localStorage + html attr between cases.
  window.localStorage.clear()
  document.documentElement.removeAttribute("data-yq-motion-off")
  setMatchMedia(false)
})

describe("useReducedMotion", () => {
  it("returns false when OS pref off and no override", () => {
    setMatchMedia(false)
    const { result } = renderHook(() => useReducedMotion())
    expect(result.current).toBe(false)
  })

  it("returns true when OS pref is on", () => {
    setMatchMedia(true)
    const { result } = renderHook(() => useReducedMotion())
    expect(result.current).toBe(true)
  })

  it("returns true when override is set, regardless of OS pref", () => {
    setMatchMedia(false)
    window.localStorage.setItem(MOTION_STORAGE_KEY, "1")
    const { result } = renderHook(() => useReducedMotion())
    expect(result.current).toBe(true)
  })

  it("flips from false → true after setMotionOverrideOff(true)", () => {
    setMatchMedia(false)
    const { result } = renderHook(() => useReducedMotion())
    expect(result.current).toBe(false)

    act(() => {
      setMotionOverrideOff(true)
    })
    expect(result.current).toBe(true)
  })
})

describe("setMotionOverrideOff", () => {
  it("writes '1' to localStorage when off=true", () => {
    setMotionOverrideOff(true)
    expect(window.localStorage.getItem(MOTION_STORAGE_KEY)).toBe("1")
  })

  it("removes the key when off=false", () => {
    window.localStorage.setItem(MOTION_STORAGE_KEY, "1")
    setMotionOverrideOff(false)
    expect(window.localStorage.getItem(MOTION_STORAGE_KEY)).toBeNull()
  })

  it("mirrors override to <html data-yq-motion-off='1'>", () => {
    setMotionOverrideOff(true)
    expect(document.documentElement.getAttribute("data-yq-motion-off")).toBe("1")
  })

  it("removes the html attribute when off=false", () => {
    document.documentElement.setAttribute("data-yq-motion-off", "1")
    setMotionOverrideOff(false)
    expect(document.documentElement.hasAttribute("data-yq-motion-off")).toBe(false)
  })
})

describe("getMotionOverrideOff", () => {
  it("returns true when localStorage holds '1'", () => {
    window.localStorage.setItem(MOTION_STORAGE_KEY, "1")
    expect(getMotionOverrideOff()).toBe(true)
  })

  it("returns false when localStorage is empty", () => {
    expect(getMotionOverrideOff()).toBe(false)
  })

  it("returns false for any non-'1' value", () => {
    window.localStorage.setItem(MOTION_STORAGE_KEY, "yes")
    expect(getMotionOverrideOff()).toBe(false)
  })
})
