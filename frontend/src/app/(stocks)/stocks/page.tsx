import type { Metadata } from "next"
import StocksIndexClient from "./StocksIndexClient"

// SSR'd index of every ticker in the YieldIQ universe.
// Why this file exists: prod was returning 404 on /stocks because the
// segment was a parent-only namespace (only /stocks/[ticker]/* existed).
// The bare /stocks URL is a primary nav target and was being cached as
// a 404 by Vercel (X-Vercel-Cache: HIT). Adding this leaf page resolves
// the route AND replaces the cached 404 once redeployed.
//
// dynamic="force-dynamic" + revalidate=0 force the edge to bypass the
// stale 404 it has cached for this path.

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export const dynamic = "force-dynamic"
export const revalidate = 0

export const metadata: Metadata = {
  title: "All Stocks — DCF Fair Value for Every Indian Stock | YieldIQ",
  description:
    "Browse every Indian stock in the YieldIQ universe. Search by ticker, jump to DCF fair value, reverse DCF, risk analysis, and DuPont breakdown. Free, no signup.",
  openGraph: {
    title: "All Stocks | YieldIQ",
    description:
      "Every Indian stock with DCF valuation. Search, filter, and analyze. Updated daily.",
    url: "https://yieldiq.in/stocks",
    siteName: "YieldIQ",
    type: "website",
    images: [{ url: "https://yieldiq.in/logo_icon.jpeg", width: 512, height: 512 }],
  },
  alternates: { canonical: "https://yieldiq.in/stocks" },
}

interface TickerRow {
  ticker: string
  full_ticker?: string
  last_updated: string | null
}

export default async function StocksIndexPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const sp = await searchParams
  const pageRaw = Array.isArray(sp.page) ? sp.page[0] : sp.page
  const qRaw = Array.isArray(sp.q) ? sp.q[0] : sp.q
  const page = Math.max(1, parseInt(pageRaw || "1", 10) || 1)
  const q = (qRaw || "").trim()

  let tickers: TickerRow[] = []
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/all-tickers`, {
      next: { revalidate: 86400 },
    })
    if (res.ok) {
      tickers = await res.json()
    }
  } catch {
    // Render empty state — page must never 500.
  }

  return <StocksIndexClient tickers={tickers} initialPage={page} initialQuery={q} />
}
