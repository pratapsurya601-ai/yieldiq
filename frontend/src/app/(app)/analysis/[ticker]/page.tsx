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
 *
 * 2026-06-04 — JSON-LD SSR relocation (acquisition PR-2). Previously
 * <JsonLd /> was mounted inside the "use client" PublicAnalysis body,
 * which meant (a) no JSON-LD shipped in the SSR HTML stream the
 * Googlebot crawler sees, and (b) the authed AnalysisBody path didn't
 * mount it at all. Phase-0 audit confirmed 0 / 32 analysis URLs
 * emitted JSON-LD in SSR HTML. Fix: SSR-fetch /api/v1/prism here
 * (same payload `generateMetadata` in layout.tsx already pulls — Next
 * dedupes the fetch when the URL + revalidate window match), then
 * render <JsonLd /> directly in the server tree above
 * AnalysisAuthGate. Schema CONTENT is unchanged; only the mount point
 * moved. Both anon and authed paths now ship the structured data in
 * the initial HTML response, regardless of cookie state.
 */

import { cookies } from "next/headers"
import AnalysisAuthGate from "./AnalysisAuthGate"
import JsonLd from "./JsonLd"
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

// Shape of the /api/v1/prism payload — narrowed to the fields the
// JSON-LD emitter needs. Mirrors the subset already consumed by
// layout.tsx::generateMetadata and PublicAnalysis (PrismRaw there).
interface PrismSsrPayload {
  ticker?: string
  company_name?: string
  sector?: string | null
  price?: number | null
  fair_value?: number | null
  mos_pct?: number | null
  verdict_label?: string | null
  yieldiq_score_100?: number | null
}

async function fetchPrismForJsonLd(
  ticker: string,
): Promise<PrismSsrPayload | null> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"
  try {
    // Same URL + revalidate as layout.tsx's generateMetadata fetch so
    // Next.js fetch-dedupe collapses both calls to one upstream request
    // per render window.
    const res = await fetch(`${apiUrl}/api/v1/prism/${ticker}`, {
      next: { revalidate: 60 },
    })
    if (!res.ok) return null
    return (await res.json()) as PrismSsrPayload
  } catch {
    // Never throw from a server component — degrade silently. JSON-LD
    // is a progressive enhancement; the page still renders without it.
    return null
  }
}

export default async function AnalysisPage({
  params,
}: {
  params: Promise<{ ticker: string }>
}) {
  const { ticker } = await params
  const cookieStore = await cookies()
  const ssrAuthenticated = Boolean(cookieStore.get("yieldiq_token")?.value)

  // SSR JSON-LD fetch (PR-2). Runs in parallel with the cookie read
  // above by virtue of being awaited on the same async boundary.
  const prism = await fetchPrismForJsonLd(ticker)
  const tickerUpper = ticker.toUpperCase()
  const displayTicker = tickerUpper.replace(/\.(NS|BO)$/i, "")
  const exchange: "NSE" | "BSE" = tickerUpper.endsWith(".BO") ? "BSE" : "NSE"

  return (
    // Mobile-PR-A (Issue 3, audit 2026-06-10): clear the fixed mobile
    // bottom nav (Navbar.tsx:118, ~64px + env(safe-area-inset-bottom))
    // so the final TrustFooter / SEBI disclaimer is not hidden behind
    // it. SEBI compliance copy partially covered is a regulatory
    // matter, not just an aesthetic one. md+ has no bottom nav.
    <div className="pb-[calc(env(safe-area-inset-bottom)+5rem)] md:pb-0">
      {prism && (
        <JsonLd
          ticker={tickerUpper}
          companyName={prism.company_name ?? displayTicker}
          sector={prism.sector}
          currentPrice={prism.price}
          fairValue={prism.fair_value}
          mosPct={prism.mos_pct}
          yieldiqScore={prism.yieldiq_score_100}
          verdict={prism.verdict_label ?? ""}
          exchange={exchange}
        />
      )}
      <TickerStrip />
      <AdrCohortBanner ticker={ticker} />
      <AnalysisAuthGate ticker={ticker} ssrAuthenticated={ssrAuthenticated} />
    </div>
  )
}
