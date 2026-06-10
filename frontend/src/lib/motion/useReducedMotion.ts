"use client"
/**
 * motion/useReducedMotion.ts — single source of truth for "do we
 * animate at all?".
 *
 * Returns `true` (skip motion) when EITHER:
 *   - the user has OS-level prefers-reduced-motion: reduce, OR
 *   - the user has flipped the in-app "Reduce motion" toggle, which
 *     writes `"1"` to localStorage key `yq:motion-off`.
 *
 * Why both? OS-level is the right default for accessibility but the
 * user can't always change it (kiosk, school laptop). The in-app
 * override lets anyone opt out without leaving the page.
 *
 * Implementation uses `useSyncExternalStore` for two reasons:
 *   1. Avoid the extra render-on-mount that a useEffect+useState pair
 *      would cost (the screen would flash with-motion then snap to
 *      no-motion).
 *   2. Satisfy `react-hooks/set-state-in-effect` cleanly — the
 *      subscriber pattern is the lint-blessed shape for this.
 *
 * SSR-safe: server snapshot returns `false` (= animate) which matches
 * the first client paint pre-hydration. After hydration the real
 * value takes over.
 */
import { useSyncExternalStore } from "react"

const MEDIA_QUERY = "(prefers-reduced-motion: reduce)"
const STORAGE_KEY = "yq:motion-off"

// ── Override accessors (exported for the settings page) ─────────────

/**
 * Read the current override value from localStorage. Returns `true`
 * iff the user has explicitly flipped the in-app toggle off.
 *
 * Safe to call during SSR — returns `false` when window is missing.
 */
export function getMotionOverrideOff(): boolean {
  if (typeof window === "undefined") return false
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1"
  } catch {
    // localStorage can throw in private-browsing on iOS Safari.
    return false
  }
}

/**
 * Write the override and broadcast a synthetic `storage` event so
 * every mounted `useReducedMotion()` subscriber re-reads. (Native
 * `storage` events only fire across tabs, not within the same tab —
 * we need the same-tab notification too.)
 */
export function setMotionOverrideOff(off: boolean): void {
  if (typeof window === "undefined") return
  try {
    if (off) {
      window.localStorage.setItem(STORAGE_KEY, "1")
    } else {
      window.localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    return
  }
  // Mirror the override to <html data-yq-motion-off> so CSS
  // utilities (.hover-lift, .shimmer, etc.) flip in lockstep
  // with the React hook. The anti-FOUC script in layout.tsx
  // sets this on first paint; the toggle handler keeps it in
  // sync for the live page.
  try {
    if (off) {
      document.documentElement.setAttribute("data-yq-motion-off", "1")
    } else {
      document.documentElement.removeAttribute("data-yq-motion-off")
    }
  } catch {
    // Some test envs lack documentElement — ignore.
  }
  // Notify same-tab subscribers — see comment above.
  try {
    window.dispatchEvent(
      new StorageEvent("storage", { key: STORAGE_KEY }),
    )
  } catch {
    // Older browsers reject the StorageEvent constructor; fall back
    // to a simple CustomEvent the subscriber also listens for.
    window.dispatchEvent(new CustomEvent("yq:motion-changed"))
  }
}

// ── useSyncExternalStore plumbing ───────────────────────────────────

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) {
    return () => {}
  }
  const mq = window.matchMedia(MEDIA_QUERY)
  // Safari < 14 lacks addEventListener on MediaQueryList.
  if (mq.addEventListener) {
    mq.addEventListener("change", onChange)
  } else {
    mq.addListener(onChange)
  }
  // localStorage changes from other tabs.
  window.addEventListener("storage", onChange)
  // Same-tab localStorage changes (see setMotionOverrideOff).
  window.addEventListener("yq:motion-changed", onChange as EventListener)

  return () => {
    if (mq.removeEventListener) {
      mq.removeEventListener("change", onChange)
    } else {
      mq.removeListener(onChange)
    }
    window.removeEventListener("storage", onChange)
    window.removeEventListener(
      "yq:motion-changed",
      onChange as EventListener,
    )
  }
}

function getSnapshot(): boolean {
  if (typeof window === "undefined") return false
  if (getMotionOverrideOff()) return true
  if (!window.matchMedia) return false
  return window.matchMedia(MEDIA_QUERY).matches
}

function getServerSnapshot(): boolean {
  // SSR default is "animate" — matches the first client paint before
  // hydration, avoids a flash.
  return false
}

/**
 * `useReducedMotion()` — returns `true` when motion must be SKIPPED
 * (either OS-level pref OR in-app override). Components consult this
 * and either render the reduced-motion variant or skip the animation
 * entirely.
 */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}

// Re-export the constants in case consumers (settings page) want to
// build their own UI without importing the helpers above.
export const MOTION_STORAGE_KEY = STORAGE_KEY
export const MOTION_MEDIA_QUERY = MEDIA_QUERY
