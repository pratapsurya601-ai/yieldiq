"use client"

// EarningsCallsWidget — recent earnings call / analyst-meet transcript filings
// from NSE corporate-announcements. Self-fetches the public endpoint
// /api/v1/public/transcripts/{ticker} (no auth, edge-cached) so the widget
// stays additive to the StockSummary contract. Renders the most recent 4
// transcripts with quarter label, filing-date relative time and a link out
// to the source PDF on NSE. Falls back to a small italic note when no
// transcripts are available — these come from the existing weekly NSE
// corporate-announcements cron, so coverage depends on what the cron has
// indexed for the ticker.

import { useQuery } from "@tanstack/react-query"

interface TranscriptItem {
  quarter_end: string | null
  filing_date: string | null
  pdf_url: string | null
  title: string
  source: string
}

interface TranscriptsResponse {
  ticker: string
  count: number
  transcripts: TranscriptItem[]
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function quarterLabel(quarterEnd: string | null): string {
  if (!quarterEnd) return ""
  try {
    const d = new Date(quarterEnd)
    if (!isFinite(d.getTime())) return ""
    const month = d.getMonth() + 1
    const fy = month <= 3 ? d.getFullYear() : d.getFullYear() + 1
    const q = month <= 3 ? "Q4" : month <= 6 ? "Q1" : month <= 9 ? "Q2" : "Q3"
    return `${q} FY${String(fy).slice(2)}`
  } catch {
    return ""
  }
}

function daysAgo(iso: string | null): string {
  if (!iso) return ""
  try {
    const d = new Date(iso)
    if (!isFinite(d.getTime())) return ""
    const diff = Date.now() - d.getTime()
    if (diff < 0) return ""
    const days = Math.floor(diff / (24 * 60 * 60 * 1000))
    if (days < 1) return "today"
    if (days === 1) return "1 day ago"
    if (days < 30) return `${days} days ago`
    if (days < 365) {
      const months = Math.floor(days / 30)
      return months === 1 ? "1 month ago" : `${months} months ago`
    }
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
  } catch {
    return ""
  }
}

async function fetchTranscripts(ticker: string): Promise<TranscriptsResponse | null> {
  const clean = ticker.replace(".NS", "").replace(".BO", "")
  const res = await fetch(`${API_BASE}/api/v1/public/transcripts/${clean}?limit=8`)
  if (!res.ok) return null
  return res.json()
}

interface Props {
  ticker: string
}

export default function EarningsCallsWidget({ ticker }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["transcripts", ticker],
    queryFn: () => fetchTranscripts(ticker),
    enabled: !!ticker,
    // Concall filings refresh weekly via cron — long stale window is fine.
    staleTime: 60 * 60 * 1000,
    retry: 1,
  })

  if (isLoading) {
    return (
      <div className="bg-bg rounded-2xl border border-border p-5">
        <div className="h-4 w-28 bg-surface rounded animate-pulse mb-3" />
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-10 bg-surface rounded animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  const items = (data?.transcripts ?? []).slice(0, 4)

  return (
    <div className="bg-bg rounded-2xl border border-border p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-ink">Earnings Calls</h2>
        <span className="text-[10px] text-caption uppercase tracking-wide">NSE filings</span>
      </div>

      {items.length === 0 ? (
        <p className="text-xs italic text-caption">
          Earnings call transcripts not available yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((t, i) => {
            const ql = quarterLabel(t.quarter_end)
            const ago = daysAgo(t.filing_date)
            const hasUrl = !!t.pdf_url
            const inner = (
              <div className="flex items-start justify-between gap-3 py-2 border-b border-border last:border-0">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    {ql && (
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full border bg-surface text-ink border-border">
                        {ql}
                      </span>
                    )}
                    <p className="text-sm text-ink leading-snug line-clamp-2">
                      {t.title}
                    </p>
                  </div>
                  <div className="mt-1 flex items-center gap-2 flex-wrap text-[10px] text-caption">
                    <span className="font-semibold">{t.source || "NSE"}</span>
                    {ago && (
                      <>
                        <span aria-hidden="true">·</span>
                        <span>{ago}</span>
                      </>
                    )}
                  </div>
                </div>
                {hasUrl && (
                  <span className="text-xs text-brand flex-shrink-0 whitespace-nowrap">→</span>
                )}
              </div>
            )
            return (
              <li key={`${t.pdf_url || t.title}-${i}`}>
                {hasUrl ? (
                  <a
                    href={t.pdf_url!}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="block hover:bg-surface/50 -mx-2 px-2 rounded-lg transition"
                  >
                    {inner}
                  </a>
                ) : (
                  inner
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
