import type { Metadata } from "next"
import { notFound } from "next/navigation"
import Link from "next/link"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

interface NewsItem {
  headline: string
  summary: string
  source: string
  url: string
  published_at: string
  category: string
  importance: string
}

interface TickerNews {
  ticker: string
  display_ticker: string
  count: number
  items: NewsItem[]
  ai_summary: string | null
}

async function getNews(ticker: string): Promise<TickerNews | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/news/${ticker}?days=14`, {
      next: { revalidate: 3600 },
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export async function generateMetadata(
  { params }: { params: Promise<{ ticker: string }> }
): Promise<Metadata> {
  const { ticker } = await params
  const display = ticker.toUpperCase().replace(".NS", "").replace(".BO", "")
  const data = await getNews(ticker)
  return {
    title: `${display} News & Filings \u2014 ${data?.count || 0} Recent Items | YieldIQ`,
    description: `Latest news, BSE corporate filings, and announcements for ${display}. Updated hourly.`,
    alternates: { canonical: `https://yieldiq.in/stocks/${display}/news` },
  }
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

function importanceBadge(level: string) {
  if (level === "critical") return { text: "Critical", cls: "bg-red-50 text-red-700 border-red-200", dot: "bg-red-500" }
  if (level === "high") return { text: "High", cls: "bg-amber-50 text-amber-700 border-amber-200", dot: "bg-amber-500" }
  if (level === "medium") return { text: "Medium", cls: "bg-blue-50 text-blue-700 border-blue-200", dot: "bg-blue-500" }
  return { text: "Low", cls: "bg-gray-50 text-gray-600 border-gray-200", dot: "bg-gray-400" }
}

export default async function StockNewsPage(
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params
  const data = await getNews(ticker)
  if (!data) notFound()

  const display = data.display_ticker

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Breadcrumb */}
      <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
        <Link href="/" className="hover:text-gray-600">Home</Link>
        <span>/</span>
        <Link href={`/stocks/${display}/fair-value`} className="hover:text-gray-600">{display}</Link>
        <span>/</span>
        <span className="text-gray-600 font-medium">News</span>
      </nav>

      <div className="mb-6">
        <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase mb-1">News & Filings</p>
        <h1 className="text-2xl sm:text-3xl font-black text-gray-900">{display} \u2014 Recent Activity</h1>
        <p className="text-gray-500 text-sm mt-1">{data.count} items in the last 14 days</p>
      </div>

      {/* AI Summary */}
      {data.ai_summary && (
        <div className="bg-blue-50 border border-blue-100 rounded-2xl p-5 mb-6">
          <p className="text-xs font-bold text-blue-700 uppercase tracking-wider mb-2">AI Summary</p>
          <p className="text-sm text-blue-900 leading-relaxed">{data.ai_summary}</p>
        </div>
      )}

      {data.items.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg font-semibold mb-1">No recent news for {display}</p>
          <p className="text-sm">Check back later \u2014 updated every hour from yfinance + BSE.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {data.items.map((item, i) => {
            const ib = importanceBadge(item.importance)
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
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border ${ib.cls}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${ib.dot}`}></span>
                      {ib.text}
                    </span>
                    <span className="text-[10px] text-gray-400 capitalize">{item.category}</span>
                    <span className="text-[10px] text-gray-400">&middot; {item.source}</span>
                  </div>
                  <span className="text-[10px] text-gray-400 flex-shrink-0">{timeAgo(item.published_at)}</span>
                </div>
                <p className="text-sm text-gray-900 font-medium leading-snug">{item.headline}</p>
                {item.summary && (
                  <p className="text-xs text-gray-500 mt-1 line-clamp-2">{item.summary}</p>
                )}
                {item.url && (
                  <p className="text-[10px] text-blue-600 mt-2">Click to open &rarr;</p>
                )}
              </a>
            )
          })}
        </div>
      )}

      {/* CTA */}
      <div className="mt-8 bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-6 text-center text-white">
        <h2 className="text-lg font-bold mb-1">Get alerts for important filings</h2>
        <p className="text-blue-100 text-sm mb-4">Add {display} to your watchlist for board meeting & dividend alerts.</p>
        <Link href={`/analysis/${ticker}`} className="inline-block bg-white text-blue-700 font-bold px-6 py-2.5 rounded-xl hover:bg-blue-50 transition text-sm">
          Open analysis &rarr;
        </Link>
      </div>

      <p className="text-[10px] text-gray-400 text-center mt-6">
        News from yfinance + BSE corporate announcements. Importance scoring is automated.
        YieldIQ is not registered with SEBI as an investment adviser.
      </p>
    </div>
  )
}
