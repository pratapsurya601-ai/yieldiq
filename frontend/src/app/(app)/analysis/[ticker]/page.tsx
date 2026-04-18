/**
 * /analysis/[ticker] — server component.
 *
 * Fetches the Prism payload on the server so the editorial hero can
 * render SSR on first paint (protects LCP ≤ 1.3s). The rest of the
 * analysis page (tabs, queries, sticky header, share) lives in the
 * AnalysisBody client component which receives the Prism payload as
 * a prop — one server fetch covers the hero; zero client fetches are
 * needed to render above-the-fold content.
 */

import AnalysisBody from "./AnalysisBody"
import TickerStrip from "@/components/analysis/TickerStrip"
import type { PrismData } from "@/components/prism/types"

async function getPrismData(ticker: string): Promise<PrismData | null> {
  const base = process.env.NEXT_PUBLIC_API_URL || process.env.API_URL || ""
  if (!base) return null
  // Hard timeout: if Prism is cold (~15s compute) we fall back to the
  // legacy hero so Vercel's SSR doesn't hang and throw a 500. 4s is
  // generous for warm requests (typical <1s) and short enough to keep
  // LCP in budget when cold. The client-side body still renders fully.
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), 4000)
  try {
    const res = await fetch(
      `${base}/api/v1/prism/${encodeURIComponent(ticker)}`,
      { next: { revalidate: 300 }, signal: ctl.signal },
    )
    if (!res.ok) return null
    const d = (await res.json()) as PrismData
    return d
  } catch {
    // Abort / network error / DNS — fall back silently, body still renders.
    return null
  } finally {
    clearTimeout(timer)
  }
}

export default async function AnalysisPage({
  params,
}: {
  // Next.js 16: dynamic route params arrive as a Promise.
  params: Promise<{ ticker: string }>
}) {
  const { ticker } = await params
  const prism = await getPrismData(ticker)

  return (
    <>
      <TickerStrip />
      <AnalysisBody ticker={ticker} prism={prism} />
    </>
  )
}
