"use client"
import { useSyncExternalStore } from "react"

/**
 * Returns `true` when the user has requested reduced motion via the
 * OS-level `prefers-reduced-motion: reduce` setting.
 *
 * Implemented with `useSyncExternalStore` (rather than useEffect +
 * useState) so we satisfy the `react-hooks/set-state-in-effect` lint
 * rule and avoid an extra render on mount.
 *
 * SSR-safe: the server snapshot returns `false`, matching the first
 * client paint before hydration replaces it with the real value.
 */
const QUERY = "(prefers-reduced-motion: reduce)"

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) {
    return () => {}
  }
  const mq = window.matchMedia(QUERY)
  // Safari < 14 lacks addEventListener on MediaQueryList.
  if (mq.addEventListener) {
    mq.addEventListener("change", onChange)
    return () => mq.removeEventListener("change", onChange)
  }
  mq.addListener(onChange)
  return () => mq.removeListener(onChange)
}

function getSnapshot(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false
  return window.matchMedia(QUERY).matches
}

function getServerSnapshot(): boolean {
  return false
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
