import type { Metadata } from "next"
import Link from "next/link"
import MarketingTopNav from "@/components/marketing/MarketingTopNav"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export const metadata: Metadata = {
  title: "Indian Stock News & Corporate Filings Feed | YieldIQ",
  description: "Latest corporate filings, board meetings, and announcements from BSE/NSE. Updated every 30 minutes. Free, no signup required.",
  openGraph: {
    title: "Live Corporate Filings Feed | YieldIQ",
    description: "Real-time BSE/NSE corporate announcements for Indian stocks",
    url: "https://yieldiq.in/news",
  },
  alternates: { canonical: "https://yieldiq.in/news" },
}

interface NewsItem {
  headline: string
  summary: string
  source: string
  ticker?: string
  company_name?: string
  url: string
  published_at: string
  category: string
  importance: string
  importance_color: string
}

interface NewsFeedData {
  count: number
  items: NewsItem[]
}

function timeAgo(iso: string): string {
  if (!iso) return ""
  try {
    const d = new Date(iso)
    const diff = Date.now() - d.getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return "just now"
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    if (days < 7) return `${days}d ago`
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })
  } catch {
    return ""
  }
}

function importanceLabel(level: string) {
  if (level === "critical") return { text: "Critical", cls: "bg-red-50 text-red-700 border-red-200" }
  if (level === "high") return { text: "High", cls: "bg-amber-50 text-amber-700 border-amber-200" }
  if (level === "medium") return { text: "Medium", cls: "bg-blue-50 text-blue-700 border-blue-200" }
  return { text: "Low", cls: "bg-gray-50 text-gray-600 border-gray-200" }
}

export default async function NewsFeedPage() {
  let data: NewsFeedData = { count: 0, items: [] }
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/news?days=7&limit=80`, { next: { revalidate: 1800 } })
    if (res.ok) data = await res.json()
  } catch {}

  return (
    <div className="min-h-screen bg-white">
      <MarketingTopNav />

      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-12">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h1 className="text-3xl sm:text-4xl font-black text-white mb-2">Corporate Filings Feed</h1>
          <p className="text-gray-400">
            Latest BSE/NSE announcements &middot; {data.count} items in the last 7 days
          </p>
        </div>
      </section>

      <section className="max-w-4xl mx-auto px-4 py-6">
        {data.items.length === 0 && (
          <div className="text-center py-16 text-gray-400">
            <p className="text-lg font-semibold mb-1">Feed temporarily unavailable</p>
            <p className="text-sm">BSE/NSE feeds are rate-limited. Check back soon.</p>
          </div>
        )}

        <div className="space-y-2">
          {data.items.map((item, i) => {
            const il = importanceLabel(item.importance)
            return (
              <a
                key={i}
                href={item.url || undefined}
                target={item.url ? "_blank" : undefined}
                rel="noopener noreferrer"
                className={`block bg-white border rounded-xl p-4 transition hover:border-blue-300 ${item.url ? "cursor-pointer" : "cursor-default"}`}
                style={{ borderColor: item.importance === "critical" ? "#FCA5A5" : "#E5E7EB" }}
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2 flex-wrap min-w-0">
                    {item.ticker && (
                      <span className="text-xs font-bold text-gray-900">{item.company_name || item.ticker}</span>
                    )}
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${il.cls}`}>{il.text}</span>
                    <span className="text-[10px] text-gray-400 capitalize">{item.category}</span>
                  </div>
                  <span className="text-[10px] text-gray-400 flex-shrink-0">{timeAgo(item.published_at)}</span>
                </div>
                <p className="text-sm text-gray-900 font-medium leading-snug">{item.headline}</p>
                {item.summary && (
                  <p className="text-xs text-gray-500 mt-1 line-clamp-2">{item.summary}</p>
                )}
                <div className="mt-2 flex items-center gap-2 text-[10px] text-gray-400">
                  <span>{item.source}</span>
                  {item.url && <span>&middot; Click to open filing &rarr;</span>}
                </div>
              </a>
            )
          })}
        </div>
      </section>

      <footer className="py-6 border-t border-gray-100">
        <p className="text-[10px] text-gray-400 text-center max-w-2xl mx-auto px-4">
          Data sourced from BSE corporate announcements. Updated every 30 minutes.
          Not investment advice. YieldIQ is not registered with SEBI as an investment adviser.
        </p>
      </footer>
    </div>
  )
}
