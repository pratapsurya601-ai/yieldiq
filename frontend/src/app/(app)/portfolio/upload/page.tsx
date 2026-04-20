import type { Metadata } from "next"
import Link from "next/link"
import PortfolioUploader from "@/components/portfolio/PortfolioUploader"
import PortfolioSummary, { type ParsedHolding } from "@/components/portfolio/PortfolioSummary"

/**
 * Portfolio CSV upload page (Task C3).
 * --------------------------------------------------------------------------
 * Server component that hosts the client uploader and — once holdings have
 * been encoded into ?h=… by the uploader — renders the server-side
 * PortfolioSummary which fans out to /api/v1/public/stock-summary/{ticker}
 * for every holding in parallel.
 *
 * Auth: this route lives under the (app) route group whose layout is the
 * authed shell (DesktopNav / Navbar / ErrorBoundary). The route group is
 * the existing project's convention for "needs an account" pages — we do
 * not duplicate auth gating here. If you need a hard server-side gate,
 * add a redirect-to-/auth/login check on the cookie at the layout level.
 */

export const metadata: Metadata = {
  title: "Portfolio Tracker | YieldIQ",
  description:
    "Upload a CSV of your holdings and get an instant valuation summary: P&L, weighted fair value, sector exposure.",
  robots: { index: false, follow: false },
}

function parseHoldingsParam(raw: string | undefined): ParsedHolding[] {
  if (!raw) return []
  const out: ParsedHolding[] = []
  for (const chunk of raw.split("|")) {
    const [ticker, q, p, d] = chunk.split(":")
    const quantity = Number(q)
    const buy_price = Number(p)
    if (!ticker || !isFinite(quantity) || !isFinite(buy_price) || !d) continue
    out.push({
      ticker: ticker.toUpperCase(),
      quantity,
      buy_price,
      buy_date: d,
    })
  }
  return out
}

interface PageProps {
  searchParams: Promise<{ h?: string }>
}

export default async function PortfolioUploadPage({ searchParams }: PageProps) {
  const sp = await searchParams
  const holdings = parseHoldingsParam(sp.h)

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 sm:py-12">
      <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
        <Link href="/portfolio" className="hover:text-gray-600">Portfolio</Link>
        <span>/</span>
        <span className="text-gray-600 font-medium">Upload</span>
      </nav>

      <header className="mb-6">
        <h1 className="text-2xl sm:text-3xl font-black" style={{ color: "var(--color-ink, #0F172A)" }}>
          Portfolio tracker
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Upload a CSV of your holdings to see live P&amp;L, weighted fair value
          and sector exposure — entirely from public YieldIQ valuations.
        </p>
      </header>

      <div className="space-y-6">
        <PortfolioUploader />
        {holdings.length > 0 && <PortfolioSummary holdings={holdings} />}
      </div>
    </div>
  )
}
