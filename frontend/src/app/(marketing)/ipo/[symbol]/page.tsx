import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import MarketingTopNav from "@/components/marketing/MarketingTopNav"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export const revalidate = 3600

interface IPO {
  symbol: string
  company_name: string
  issue_size_cr: number | null
  price_band_min: number | null
  price_band_max: number | null
  ipo_open_date: string | null
  ipo_close_date: string | null
  listing_date: string | null
  status: "upcoming" | "recent"
  exchange: string
  sector: string | null
}

async function fetchIPO(symbol: string): Promise<IPO | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/ipos/${symbol}`, {
      next: { revalidate: 3600 },
    })
    if (!res.ok) return null
    return (await res.json()) as IPO
  } catch {
    return null
  }
}

function fmtDate(iso: string | null): string {
  if (!iso) return "\u2014"
  try {
    return new Date(iso).toLocaleDateString("en-IN", {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    })
  } catch {
    return iso
  }
}

function fmtBand(min: number | null, max: number | null): string {
  if (!min || !max) return "TBA"
  if (min === max) return `\u20B9${min}`
  return `\u20B9${min} \u2013 \u20B9${max}`
}

function fmtCr(n: number | null): string {
  if (n == null) return "\u2014"
  if (n >= 1000) return `\u20B9${(n / 1000).toFixed(1)}K Cr`
  return `\u20B9${n.toFixed(0)} Cr`
}

export async function generateMetadata(
  { params }: { params: Promise<{ symbol: string }> },
): Promise<Metadata> {
  const { symbol } = await params
  const ipo = await fetchIPO(symbol)
  if (!ipo) {
    return { title: `${symbol.toUpperCase()} IPO | YieldIQ` }
  }
  const verb = ipo.status === "upcoming" ? "Upcoming IPO" : "IPO"
  const band = fmtBand(ipo.price_band_min, ipo.price_band_max)
  return {
    title: `${ipo.company_name} (${ipo.symbol}) ${verb} \u2014 Price Band ${band} | YieldIQ`,
    description: `${ipo.company_name} IPO details: price band ${band}, issue size ${fmtCr(
      ipo.issue_size_cr,
    )}. Open ${fmtDate(ipo.ipo_open_date)} \u2013 Close ${fmtDate(ipo.ipo_close_date)}.`,
    openGraph: {
      title: `${ipo.company_name} IPO \u2014 ${band}`,
      description: `Issue size ${fmtCr(ipo.issue_size_cr)} \u00B7 ${ipo.exchange}`,
      url: `https://yieldiq.in/ipo/${ipo.symbol}`,
      siteName: "YieldIQ",
      type: "article",
    },
    alternates: { canonical: `https://yieldiq.in/ipo/${ipo.symbol}` },
  }
}

export default async function IPODetailPage(
  { params }: { params: Promise<{ symbol: string }> },
) {
  const { symbol } = await params
  const ipo = await fetchIPO(symbol)
  if (!ipo) notFound()

  const isListed = ipo.status === "recent" && ipo.listing_date

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Event",
    name: `${ipo.company_name} IPO`,
    startDate: ipo.ipo_open_date,
    endDate: ipo.ipo_close_date,
    eventStatus: "https://schema.org/EventScheduled",
    eventAttendanceMode: "https://schema.org/OnlineEventAttendanceMode",
    location: {
      "@type": "VirtualLocation",
      url: `https://yieldiq.in/ipo/${ipo.symbol}`,
    },
    description: `${ipo.company_name} initial public offering on ${ipo.exchange}.`,
  }

  return (
    <div className="min-h-screen bg-white">
      <MarketingTopNav />

      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <div className="max-w-3xl mx-auto px-4 py-8 sm:py-12">
        <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
          <Link href="/" className="hover:text-gray-600">Home</Link>
          <span>/</span>
          <Link href="/ipo" className="hover:text-gray-600">IPO Calendar</Link>
          <span>/</span>
          <span className="text-gray-600 font-medium">{ipo.symbol}</span>
        </nav>

        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 sm:p-8 mb-6">
          <div className="flex items-start justify-between gap-3 mb-4">
            <div className="flex-1 min-w-0">
              <h1 className="text-2xl sm:text-3xl font-black text-gray-900">
                {ipo.company_name}
              </h1>
              <p className="text-gray-500 text-sm mt-1">
                {ipo.symbol} &middot; {ipo.exchange}
                {ipo.sector ? ` \u00B7 ${ipo.sector}` : ""}
              </p>
            </div>
            <span
              className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full border ${
                ipo.status === "upcoming"
                  ? "bg-blue-50 text-blue-700 border-blue-200"
                  : "bg-gray-50 text-gray-600 border-gray-200"
              }`}
            >
              {ipo.status}
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mt-6">
            <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">
                Price Band
              </p>
              <p className="text-lg font-bold text-gray-900 font-mono">
                {fmtBand(ipo.price_band_min, ipo.price_band_max)}
              </p>
            </div>
            <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">
                Issue Size
              </p>
              <p className="text-lg font-bold text-gray-900 font-mono">
                {fmtCr(ipo.issue_size_cr)}
              </p>
            </div>
            <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">
                Exchange
              </p>
              <p className="text-lg font-bold text-gray-900">{ipo.exchange}</p>
            </div>
            <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">
                Open Date
              </p>
              <p className="text-sm font-semibold text-gray-900">
                {fmtDate(ipo.ipo_open_date)}
              </p>
            </div>
            <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">
                Close Date
              </p>
              <p className="text-sm font-semibold text-gray-900">
                {fmtDate(ipo.ipo_close_date)}
              </p>
            </div>
            <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">
                Listing Date
              </p>
              <p className="text-sm font-semibold text-gray-900">
                {fmtDate(ipo.listing_date)}
              </p>
            </div>
          </div>
        </div>

        {isListed && (
          <div className="bg-blue-50 border border-blue-100 rounded-2xl p-6 mb-6">
            <h2 className="text-sm font-bold text-blue-800 mb-2">
              Now trading on {ipo.exchange}
            </h2>
            <p className="text-sm text-blue-700 mb-4">
              {ipo.company_name} listed on {fmtDate(ipo.listing_date)}. Run a full DCF
              fair-value analysis using YieldIQ.
            </p>
            <Link
              href={`/stocks/${ipo.symbol}/fair-value`}
              className="inline-block bg-blue-600 text-white font-bold px-6 py-3 rounded-xl hover:bg-blue-700 transition"
            >
              View {ipo.symbol} Fair Value &rarr;
            </Link>
          </div>
        )}

        <p className="text-[10px] text-gray-400 text-center leading-relaxed">
          IPO information is currently a curated list and may not reflect the latest
          regulatory disclosures. Always check the official offer document and SEBI
          filings before investing. Not investment advice.
        </p>
      </div>
    </div>
  )
}
