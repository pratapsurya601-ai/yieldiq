/**
 * /analysis/[ticker] — server shell.
 *
 * PR1 SSR-cascade fix (Option C, 2026-04-19):
 *   The previous version did `await getPrismData(ticker)` on the server
 *   with a 4 s AbortController. On Vercel that produced a 9 s perceived
 *   regression for cold tickers:
 *
 *     1. SSR fires GET /api/v1/prism/{ticker} (cold = ~6.7 s).
 *     2. AbortController fires at 4 s → SSR returns the legacy-hero
 *        fallback HTML.
 *     3. Browser hydrates AnalysisBody, which then issues GET
 *        /api/v1/analysis/{ticker} client-side (also cold = ~5-9 s).
 *     4. User sees blank-then-hero-then-content over 9-13 s.
 *
 *   Net: SSR was paying 4 s of TTFB for a result the client immediately
 *   threw away. We now ship a thin server shell (TTFB <100 ms) and let
 *   AnalysisBody hydrate Prism client-side via react-query in parallel
 *   with the analysis fetch. AnalysisBody already gracefully falls back
 *   to <AnalysisHero/> while prism is null, so visitors see the legacy
 *   hero immediately and Prism upgrades when it lands.
 *
 *   Trade-off: above-the-fold LCP loses the SSR-painted Prism for the
 *   first cold visit. But (a) cold visits were already 9 s so LCP was
 *   not the win we thought; (b) CDN warming + prism's own server-side
 *   cache mean repeat visitors still get a fast paint.
 */

import AnalysisBody from "./AnalysisBody"
import TickerStrip from "@/components/analysis/TickerStrip"

export default async function AnalysisPage({
  params,
}: {
  // Next.js 16: dynamic route params arrive as a Promise.
  params: Promise<{ ticker: string }>
}) {
  const { ticker } = await params

  return (
    <>
      <TickerStrip />
      {/* prism={null} → AnalysisBody renders the legacy AnalysisHero
          immediately and hydrates Prism client-side. */}
      <AnalysisBody ticker={ticker} prism={null} />
    </>
  )
}
