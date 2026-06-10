"use client"

// ConcallsPanel — ticker-level earnings call library with cached AI
// summaries. Day-103a closes the depth gap flagged in the Day-102
// competitive audit (Screener.in carries 28+ transcripts going back
// to 2018). The panel sits inside the analysis page Financials tab,
// just below the FinancialStatements block.
//
// Data: GET /api/v1/public/concalls/{ticker} → newest-first list of
// { period, date, source_url, ai_summary, has_full_transcript }.
// The endpoint always returns 200 with an empty list when coverage
// isn't there yet, so this component renders a friendly empty state
// instead of an error.

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"

interface ConcallItem {
  period: string
  date: string
  source_url: string
  ai_summary: string
  has_full_transcript: boolean
}

interface ConcallsResponse {
  ticker: string
  count: number
  concalls: ConcallItem[]
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

async function fetchConcalls(ticker: string): Promise<ConcallsResponse | null> {
  const t = (ticker || "").trim().toUpperCase()
  if (!t) return null
  const res = await fetch(`${API_BASE}/api/v1/public/concalls/${encodeURIComponent(t)}?limit=12`)
  if (!res.ok) return null
  return res.json()
}

function formatDate(iso: string): string {
  if (!iso) return ""
  try {
    const d = new Date(iso)
    if (!isFinite(d.getTime())) return ""
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
  } catch {
    return ""
  }
}

// ROOT CAUSE #10 (2026-06-11): backend sentinels that mean the
// populate path tried and failed (or was withheld). They are NOT real
// summary content — render them as the failure copy line instead of
// showing them as a single bullet.
const _SUMMARY_UNAVAILABLE = "(summary unavailable)"
const _SUMMARY_FAILED = "(summary generation failed — see transcript)"
const _SUMMARY_WITHHELD = "(summary withheld pending review)"

function isPlaceholderSummary(text: string | null | undefined): boolean {
  const s = (text || "").trim()
  return (
    s === _SUMMARY_UNAVAILABLE ||
    s === _SUMMARY_FAILED ||
    s === _SUMMARY_WITHHELD
  )
}

function summaryBullets(text: string): string[] {
  if (!text) return []
  if (isPlaceholderSummary(text)) return []
  return text
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*[-*•]\s*/, "").trim())
    .filter((line) => line.length > 0)
}

interface Props {
  ticker: string
}

export default function ConcallsPanel({ ticker }: Props) {
  const [expanded, setExpanded] = useState(false)
  const { data, isLoading } = useQuery({
    queryKey: ["concalls", ticker],
    queryFn: () => fetchConcalls(ticker),
    enabled: !!ticker,
    // Library refreshes at most once per quarter — long stale window is fine.
    staleTime: 60 * 60 * 1000,
    retry: 1,
  })

  const items = useMemo(() => data?.concalls ?? [], [data])
  const visible = expanded ? items.slice(0, 12) : items.slice(0, 4)

  if (isLoading) {
    return (
      <div className="bg-bg rounded-2xl border border-border p-4">
        <div className="h-4 w-32 bg-surface rounded animate-pulse mb-4" />
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-20 bg-surface rounded animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="bg-bg rounded-2xl border border-border p-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">Concall Transcripts</h2>
          <p className="text-[11px] text-caption mt-0.5">
            Quarterly earnings call library with AI-generated summaries.
          </p>
        </div>
        <span className="text-[10px] text-caption uppercase tracking-wide">
          {items.length > 0 ? `${items.length} call${items.length === 1 ? "" : "s"}` : "library"}
        </span>
      </div>

      {items.length === 0 ? (
        <p className="text-xs italic text-caption">
          Concall transcripts coming soon for this ticker.
        </p>
      ) : (
        <>
          <ul className="space-y-4">
            {visible.map((c, i) => {
              const bullets = summaryBullets(c.ai_summary)
              return (
                <li
                  key={`${c.period}-${i}`}
                  className="border border-border rounded-xl p-4 bg-surface/40"
                >
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-accent/10 text-accent">
                        {c.period}
                      </span>
                      {c.date && (
                        <span className="text-[11px] text-caption">{formatDate(c.date)}</span>
                      )}
                    </div>
                    {c.source_url && (
                      <a
                        href={c.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[11px] font-medium text-accent hover:underline whitespace-nowrap"
                      >
                        Open transcript ↗
                      </a>
                    )}
                  </div>

                  {bullets.length > 0 ? (
                    <ul className="space-y-1.5 list-disc list-outside pl-5">
                      {bullets.slice(0, 5).map((b, bi) => (
                        <li key={bi} className="text-xs text-ink leading-relaxed">
                          {b}
                        </li>
                      ))}
                    </ul>
                  ) : c.ai_summary === _SUMMARY_FAILED ? (
                    <p
                      className="text-xs italic text-caption"
                      data-testid="concall-summary-failed"
                    >
                      Summary generation failed — see the source transcript
                      for the full call.
                    </p>
                  ) : c.ai_summary === _SUMMARY_WITHHELD ? (
                    <p className="text-xs italic text-caption">
                      Summary withheld pending review.
                    </p>
                  ) : (
                    <p className="text-xs italic text-caption">
                      Summary not generated yet. Open the source transcript for the full call.
                    </p>
                  )}
                </li>
              )
            })}
          </ul>

          {items.length > 4 && (
            <button
              type="button"
              onClick={() => setExpanded((e) => !e)}
              className="mt-4 text-xs font-medium text-accent hover:underline"
            >
              {expanded ? "Show fewer" : `Show all ${Math.min(items.length, 12)}`}
            </button>
          )}

          <p className="mt-4 text-[10px] text-caption leading-relaxed">
            Summaries are AI-generated from management commentary. They describe
            what management said and are not investment advice.
          </p>
        </>
      )}
    </div>
  )
}
