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
 */

import { cookies } from "next/headers"
import AnalysisBody from "./AnalysisBody"
import PublicAnalysis from "./PublicAnalysis"
import TickerStrip from "@/components/analysis/TickerStrip"

export default async function AnalysisPage({
  params,
}: {
  params: Promise<{ ticker: string }>
}) {
  const { ticker } = await params
  const cookieStore = await cookies()
  const isAuthenticated = Boolean(cookieStore.get("yieldiq_token")?.value)

  return (
    <>
      <TickerStrip />
      {isAuthenticated ? (
        <AnalysisBody ticker={ticker} prism={null} />
      ) : (
        <PublicAnalysis ticker={ticker} />
      )}
    </>
  )
}
