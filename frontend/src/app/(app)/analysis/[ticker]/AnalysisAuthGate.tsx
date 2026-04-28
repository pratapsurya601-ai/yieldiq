"use client"

/**
 * AnalysisAuthGate — client-side auth-handoff for /analysis/[ticker].
 *
 * Why this exists (CRITICAL bug, paid users locked out):
 *
 * The server shell (`page.tsx`) branches on the SSR-readable
 * `yieldiq_token` cookie. That cookie was set with a fixed 7-day expiry
 * at login while the persisted Zustand auth store has no expiry — so
 * the cookie can disappear out from under an actively-using paid user.
 * When that happens the server returns the anonymous `PublicAnalysis`
 * signup wall to a fully-paid ANALYST user.
 *
 * This gate trusts the SSR result for the first paint (so SEO + initial
 * render still match the cookie state and we don't flash a private body
 * to anonymous visitors) but, on the client, upgrades to the authed
 * body the moment we detect a Zustand token in localStorage. The
 * companion `CookieAuthSync` then re-issues the cookie so subsequent
 * SSRs are correct.
 *
 * Order of operations on first load for an affected user:
 *
 *   1. SSR sees no cookie → server renders `<PublicAnalysis />`.
 *   2. React hydrates. Zustand reads localStorage and surfaces the
 *      persisted token.
 *   3. This gate sees token !== null and swaps to `<AnalysisBody />`.
 *   4. `CookieAuthSync` (mounted in Providers) writes a fresh cookie.
 *   5. Next navigation has a valid cookie → SSR is correct again.
 *
 * For genuinely anonymous visitors: token stays null, `PublicAnalysis`
 * stays mounted, and the public marketing CTA is exactly what they see.
 */

import { useSyncExternalStore } from "react"
import { useAuthStore } from "@/store/authStore"
import AnalysisBody from "./AnalysisBody"
import PublicAnalysis from "./PublicAnalysis"

interface Props {
  ticker: string
  /** SSR-resolved auth signal from the cookie. Used for the initial
   *  render so SEO crawlers and genuinely-anonymous visitors get the
   *  same body the server rendered. */
  ssrAuthenticated: boolean
}

/**
 * Subscribe to whether the Zustand auth store currently holds a token.
 *
 * `useSyncExternalStore` is the React-blessed escape hatch for reading
 * client-only state without causing a hydration mismatch: the
 * `getServerSnapshot` callback returns `false` during SSR so the
 * server-rendered tree matches `ssrAuthenticated`, then on the client
 * the real value flows in on the first commit. No extra `useEffect`
 * + `setState` round-trip needed.
 */
function useStoreHasToken(): boolean {
  return useSyncExternalStore(
    (cb) => useAuthStore.subscribe(cb),
    () => Boolean(useAuthStore.getState().token),
    () => false,
  )
}

export default function AnalysisAuthGate({ ticker, ssrAuthenticated }: Props) {
  const storeHasToken = useStoreHasToken()
  const showAuthed = ssrAuthenticated || storeHasToken

  return showAuthed ? (
    <AnalysisBody ticker={ticker} prism={null} />
  ) : (
    <PublicAnalysis ticker={ticker} />
  )
}
