// paygStore.ts — tracks the user's active PAYG (₹99 / 24 h) unlocks.
//
// PAYG is additive to tier-based gating:
//   - Free tier gets 5 analyses / day.
//   - Analyst / Pro are unlimited.
//   - PAYG unlocks a single ticker for 24 h regardless of tier.
//
// The backend is the source of truth (`GET /api/v1/payments/payg-unlocks`
// returns only unlocks within the last 24 h). We hydrate the store once on
// app mount and after every successful verify so the UI can badge unlocked
// tickers and bypass the 429 gate without a round-trip.
//
// We deliberately do NOT persist this store. If the browser is offline we
// fall back to "locked" which is safer than showing a phantom unlock after
// the 24 h window has elapsed. The server will re-gate on the next analysis
// fetch anyway.

import { create } from "zustand"
import type { PaygUnlock } from "@/lib/api"

/** Milliseconds in a 24 h PAYG window. Kept here so badge countdown +
 *  unlock check use the exact same constant. */
export const PAYG_WINDOW_MS = 24 * 60 * 60 * 1000

interface PaygState {
  /** ticker (UPPERCASE, e.g. "TCS.NS") → ISO timestamp of unlock. */
  unlocks: Record<string, string>
  /** True once we've hydrated from the backend at least once. Used to
   *  avoid showing a phantom "locked" UI flash while the initial fetch
   *  is in-flight. */
  loaded: boolean

  setFromServer: (unlocks: PaygUnlock[]) => void
  addUnlock: (ticker: string, unlockedAt?: string) => void
  clear: () => void
  isUnlocked: (ticker: string) => boolean
  /** Whole-number hours remaining on an unlock; 0 if locked/expired. */
  hoursRemaining: (ticker: string) => number
}

/** Normalise ticker casing. Backend stores upper-case with `.NS` / `.BO`
 *  suffixes; some UI paths pass lowercase. Avoid missed matches. */
const norm = (t: string): string => t.trim().toUpperCase()

export const usePaygStore = create<PaygState>()((set, get) => ({
  unlocks: {},
  loaded: false,

  setFromServer: (list) => {
    const next: Record<string, string> = {}
    for (const u of list) {
      if (u?.ticker && u?.unlocked_at) next[norm(u.ticker)] = u.unlocked_at
    }
    set({ unlocks: next, loaded: true })
  },

  addUnlock: (ticker, unlockedAt) => {
    const key = norm(ticker)
    const iso = unlockedAt ?? new Date().toISOString()
    set((s) => ({ unlocks: { ...s.unlocks, [key]: iso } }))
  },

  clear: () => set({ unlocks: {}, loaded: false }),

  isUnlocked: (ticker) => {
    const iso = get().unlocks[norm(ticker)]
    if (!iso) return false
    const ts = Date.parse(iso)
    if (!Number.isFinite(ts)) return false
    return Date.now() - ts < PAYG_WINDOW_MS
  },

  hoursRemaining: (ticker) => {
    const iso = get().unlocks[norm(ticker)]
    if (!iso) return 0
    const ts = Date.parse(iso)
    if (!Number.isFinite(ts)) return 0
    const remainingMs = PAYG_WINDOW_MS - (Date.now() - ts)
    if (remainingMs <= 0) return 0
    return Math.ceil(remainingMs / (60 * 60 * 1000))
  },
}))
