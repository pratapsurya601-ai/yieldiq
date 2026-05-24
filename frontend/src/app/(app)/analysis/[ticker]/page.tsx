/**
 * /analysis/[ticker] — server shell.
 *
 * Branches on the presence of the `yieldiq_token` cookie:
 *
 *   - Authenticated users get the full `AnalysisBody` — DCF, AI narrative,
 *     10-year financials, peer comparison, FV history, and all other
 *     gated surfaces.
 *
 *   - Anonymous users get `PublicAnalysis` — the Prism 6-pillar view + a
 *     summary card + inline upsell CTAs in place of each gated section.
 *     The landing page markets "analyse any stock free" and the CTA sends
 *     users to /analysis/:ticker; if we return the authed body to an
 *     anon visitor, the axios interceptor in `lib/api.ts` bounces them
 *     to /auth/login the moment `getAnalysis()` returns 401 and the
 *     entire public promise collapses. Routing to /prism/:ticker would
 *     work for the happy path but would leave social shares of
 *     /analysis/:ticker URLs broken for the logged-out majority of
 *     visitors. Keeping one URL with a dual-mode body is the long-term
 *     shape — one source of truth, one shareable link.
 *
 * PR1 SSR-cascade fix (Option C, 2026-04-19) is preserved: we still ship
 * a thin server shell and let the body hydrate Prism + analysis data
 * client-side so TTFB stays under ~100 ms.
 *
 * 2026-04-27 — paid-user lockout fix: we still read the cookie SSR-side
 * to seed the initial render (preserves SEO + the anon promise), but
 * the actual Body/Public swap is delegated to `AnalysisAuthGate`, a
 * client component that can ALSO consult the persisted Zustand auth
 * store. This is the safety net for the case where the 7-day cookie
 * expired but the user's session in localStorage is still active —
 * before this fix, those users (including paying ANALYST subscribers)
 * were being shown the anon signup wall on every analysis page. See
 * `components/CookieAuthSync.tsx` for the long-term cookie-refresh fix.
 */

import { cookies } from "next/headers"
import AnalysisAuthGate from "./AnalysisAuthGate"
import TickerStrip from "@/components/analysis/TickerStrip"
import AdrCohortBanner from "@/components/analysis/AdrCohortBanner"

// Task #179 (2026-05-24) — ISR cap on the anon analysis page.
//
// Repro: operator opened https://www.yieldiq.in/analysis/HDFCBANK.NS in
// incognito and saw score=64 / "Notably Undervalued" while both
// /api/v1/public/stock-summary/HDFCBANK.NS and
// /api/v1/analysis/HDFCBANK.NS/og-data returned score=50 / "undervalued"
// identically. The wire-format payload was clean, but the rendered HTML
// was carrying a pre-recompute score. The only durable cause that fits
// both surfaces (body score AND tab title verdict are derived in
// different layers) is a stale Next.js / Vercel CDN render of this
// segment from before the recompute.
//
// This page already opts into dynamic rendering implicitly because we
// read `cookies()` to seed the SSR auth gate — Next 16 marks the
// segment as request-time the moment a dynamic API is touched, so the
// SSR shell itself cannot be CDN-cached. The explicit `revalidate = 60`
// belt-and-braces this: if a refactor ever drops the `cookies()` call,
// the page is still capped at one minute of staleness rather than
// silently flipping to indefinitely-cached static HTML. Combined with
// `revalidate: 60` on the layout's og-data fetch (which feeds the tab
// title and og:image), the worst-case end-to-end staleness window any
// anon visitor can observe is bounded at ~60 s after a backend score
// recompute. See task #179 for the full investigation trail.
export const revalidate = 60

export default async function AnalysisPage({
  params,
}: {
  params: Promise<{ ticker: string }>
}) {
  const { ticker } = await params
  const cookieStore = await cookies()
  const ssrAuthenticated = Boolean(cookieStore.get("yieldiq_token")?.value)

  return (
    <>
      <TickerStrip />
      <AdrCohortBanner ticker={ticker} />
      <AnalysisAuthGate ticker={ticker} ssrAuthenticated={ssrAuthenticated} />
    </>
  )
}
