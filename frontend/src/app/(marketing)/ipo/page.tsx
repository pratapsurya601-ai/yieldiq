import type { Metadata } from "next"
import Link from "next/link"
import MarketingTopNav from "@/components/marketing/MarketingTopNav"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export const revalidate = 3600

export const metadata: Metadata = {
  title: "Upcoming & Recent IPOs in India \u2014 Price Band, Issue Size, Listing | YieldIQ",
  description:
    "Track upcoming and recent IPOs on NSE/BSE. Issue size, price band, open & close dates, listing dates. Free, updated regularly.",
  openGraph: {
    title: "Indian IPO Calendar \u2014 Upcoming & Recent | YieldIQ",
    description:
      "Upcoming IPOs in India with price band, issue size and listing dates.",
    url: "https://yieldiq.in/ipo",
    siteName: "YieldIQ",
    type: "website",
  },
  alternates: { canonical: "https://yieldiq.in/ipo" },
}

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

interface IPOListResponse {
  status_filter: string
  total: number
  ipos: IPO[]
  source: string
}

async function fetchIPOs(status: "upcoming" | "recent" | "all"): Promise<IPOListResponse | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/ipos?status=${status}`, {
      next: { revalidate: 3600 },
    })
    if (!res.ok) return null
    return (await res.json()) as IPOListResponse
  } catch {
    return null
  }
}

function fmtDate(iso: string | null): string {
  if (!iso) return "\u2014"
  try {
    return new Date(iso).toLocaleDateString("en-IN", {
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

function statusPill(status: string): string {
  if (status === "upcoming") return "bg-blue-50 text-blue-700 border-blue-200"
  return "bg-gray-50 text-gray-600 border-gray-200"
}

function IPOCard({ ipo }: { ipo: IPO }) {
  return (
    <Link
      href={`/ipo/${ipo.symbol}`}
      className="block bg-white border border-gray-200 hover:border-blue-300 rounded-2xl p-5 transition shadow-sm hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-bold text-gray-900 truncate">{ipo.company_name}</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {ipo.symbol} &middot; {ipo.exchange}
            {ipo.sector ? ` \u00B7 ${ipo.sector}` : ""}
          </p>
        </div>
        <span
          className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full border ${statusPill(
            ipo.status,
          )}`}
        >
          {ipo.status}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-[10px] text-gray-400 uppercase tracking-wider">Price Band</p>
          <p className="font-semibold text-gray-900 font-mono">
            {fmtBand(ipo.price_band_min, ipo.price_band_max)}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-gray-400 uppercase tracking-wider">Issue Size</p>
          <p className="font-semibold text-gray-900 font-mono">{fmtCr(ipo.issue_size_cr)}</p>
        </div>
        <div>
          <p className="text-[10px] text-gray-400 uppercase tracking-wider">Open</p>
          <p className="text-gray-700">{fmtDate(ipo.ipo_open_date)}</p>
        </div>
        <div>
          <p className="text-[10px] text-gray-400 uppercase tracking-wider">
            {ipo.status === "recent" ? "Listed" : "Close"}
          </p>
          <p className="text-gray-700">
            {ipo.status === "recent" ? fmtDate(ipo.listing_date) : fmtDate(ipo.ipo_close_date)}
          </p>
        </div>
      </div>
    </Link>
  )
}

export default async function IPOListPage() {
  const [upcoming, recent] = await Promise.all([fetchIPOs("upcoming"), fetchIPOs("recent")])

  const upcomingIpos = upcoming?.ipos ?? []
  const recentIpos = recent?.ipos ?? []

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "Upcoming IPOs in India",
    itemListElement: upcomingIpos.map((ipo, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: ipo.company_name,
      url: `https://yieldiq.in/ipo/${ipo.symbol}`,
    })),
  }

  return (
    <div className="min-h-screen bg-white">
      <MarketingTopNav />

      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-12 sm:py-16">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h1 className="text-3xl sm:text-4xl font-black text-white mb-3">
            IPO Calendar &mdash; Indian Stocks
          </h1>
          <p className="text-gray-400">
            Upcoming and recent IPOs on NSE / BSE &middot; Price band, issue size, listing dates
          </p>
        </div>
      </section>

      <section className="max-w-4xl mx-auto px-4 py-8">
        <h2 className="text-xl font-bold text-gray-900 mb-4">
          Upcoming IPOs
          <span className="ml-2 text-sm font-normal text-gray-400">
            ({upcomingIpos.length})
          </span>
        </h2>
        {upcomingIpos.length === 0 ? (
          <p className="text-sm text-gray-400 py-8 text-center">No upcoming IPOs listed.</p>
        ) : (
          <div className="grid sm:grid-cols-2 gap-4">
            {upcomingIpos.map(ipo => (
              <IPOCard key={ipo.symbol} ipo={ipo} />
            ))}
          </div>
        )}
      </section>

      <section className="max-w-4xl mx-auto px-4 py-8 border-t border-gray-100">
        <h2 className="text-xl font-bold text-gray-900 mb-4">
          Recently Listed
          <span className="ml-2 text-sm font-normal text-gray-400">
            ({recentIpos.length})
          </span>
        </h2>
        {recentIpos.length === 0 ? (
          <p className="text-sm text-gray-400 py-8 text-center">No recent IPOs.</p>
        ) : (
          <div className="grid sm:grid-cols-2 gap-4">
            {recentIpos.map(ipo => (
              <IPOCard key={ipo.symbol} ipo={ipo} />
            ))}
          </div>
        )}
      </section>

      <footer className="py-6 border-t border-gray-100">
        <p className="text-[10px] text-gray-400 text-center max-w-2xl mx-auto px-4">
          IPO data is currently a curated list maintained by YieldIQ; it will move
          to a live ingestion feed soon. Not investment advice. YieldIQ is not
          registered with SEBI as an investment adviser.
        </p>
      </footer>
    </div>
  )
}
