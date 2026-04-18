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
  try {
    const res = await fetch(
      `${base}/api/v1/prism/${encodeURIComponent(ticker)}`,
      { next: { revalidate: 300 } },
    )
    if (!res.ok) return null
    const d = (await res.json()) as PrismData
    return d
  } catch {
    // Backend down / DNS / etc — fall back to legacy hero without killing SSR.
    return null
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
