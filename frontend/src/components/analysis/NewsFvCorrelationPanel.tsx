"use client"

// NewsFvCorrelationPanel — novel correlation surface that links material
// fair-value history deltas to news headlines published within ±7 days.
//
// Self-fetches /api/v1/public/news-fv-correlation/{ticker}. Renders a
// timeline of FV change events with the most plausible news drivers
// stacked underneath each. Pure read-only — never feeds FV / scoring.
//
// Empty states:
//   • No material moves in the lookback window -> "FV has been steady"
//   • Material moves exist but no clear driver -> "No clear headline driver"
//   • Network / API error -> render nothing (additive panel discipline)

import { useQuery } from "@tanstack/react-query"

interface LikelyDriver {
  news_id: string
  headline: string
  source: string
  url: string
  published_at: string
  sentiment_score?: number | null
  sentiment_label?: "positive" | "neutral" | "negative" | null
  importance?: string | null
  source_quality_tier?: "A" | "B" | "C" | null
  relevance_score: number
}

interface CorrelationItem {
  fv_change_date: string
  fv_before: number
  fv_after: number
  pct_change: number
  likely_drivers: LikelyDriver[]
}

interface CorrelationResponse {
  ticker: string
  display_ticker: string
  correlations: CorrelationItem[]
  summary: {
    total_material_moves: number
    moves_with_drivers: number
    window_days: number
    min_driver_score: number
    top_drivers_per_move: number
  }
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

async function fetchCorrelation(ticker: string): Promise<CorrelationResponse | null> {
  const clean = ticker.replace(".NS", "").replace(".BO", "")
  const res = await fetch(
    `${API_BASE}/api/v1/public/news-fv-correlation/${clean}?fv_change_threshold_pct=3.0&lookback_days=90`,
  )
  if (!res.ok) return null
  return res.json()
}

function formatDate(iso: string): string {
  if (!iso) return ""
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })
  } catch {
    return iso
  }
}

function formatRupees(v: number): string {
  if (!Number.isFinite(v)) return "—"
  if (v >= 100000) return `₹${(v / 100000).toFixed(2)}L`
  if (v >= 1000) return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
  return `₹${v.toFixed(2)}`
}

function pctBadgeCls(pct: number): string {
  if (pct >= 0) {
    return "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800"
  }
  return "bg-rose-50 dark:bg-rose-900/20 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800"
}

function sentimentGlyph(label?: string | null): { glyph: string; cls: string } | null {
  if (label === "positive") return { glyph: "↑", cls: "text-emerald-600 dark:text-emerald-400" }
  if (label === "negative") return { glyph: "↓", cls: "text-rose-600 dark:text-rose-400" }
  if (label === "neutral") return { glyph: "→", cls: "text-caption" }
  return null
}

interface Props {
  ticker: string
}

export default function NewsFvCorrelationPanel({ ticker }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["news-fv-correlation", ticker],
    queryFn: () => fetchCorrelation(ticker),
    enabled: !!ticker,
    staleTime: 30 * 60 * 1000,
    retry: 1,
  })

  if (isLoading) {
    return (
      <section
        aria-label="News drove fair value"
        className="bg-bg rounded-2xl border border-border p-5"
      >
        <div className="h-5 w-48 bg-surface rounded animate-pulse mb-2" />
        <div className="h-3 w-64 bg-surface rounded animate-pulse mb-5" />
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-20 bg-surface rounded animate-pulse" />
          ))}
        </div>
      </section>
    )
  }

  if (isError || !data) return null

  const items = data.correlations ?? []

  // Empty-state: no material moves found in the window.
  if (items.length === 0) {
    return (
      <section
        aria-label="News drove fair value"
        className="bg-bg rounded-2xl border border-border p-5"
      >
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-base font-semibold text-ink">
            News &amp; fair value
          </h2>
          <span className="text-[10px] text-caption uppercase tracking-wide">
            ±{data.summary.window_days}d window
          </span>
        </div>
        <p className="text-xs text-caption">
          Fair value has been steady for {data.display_ticker} over the
          last 90 days — no material moves (≥3%) recorded. We&apos;ll
          surface a headline-linked timeline here the next time fair
          value shifts.
        </p>
      </section>
    )
  }

  return (
    <section
      aria-label="News drove fair value"
      className="bg-bg rounded-2xl border border-border p-5"
    >
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-base font-semibold text-ink">
          News &amp; fair value
        </h2>
        <span className="text-[10px] text-caption uppercase tracking-wide">
          ±{data.summary.window_days}d window
        </span>
      </div>
      <p className="text-xs text-caption mb-5">
        Every material fair-value move (≥3%) over the last 90 days, with
        the news items published within {data.summary.window_days} days
        that may have driven it.
      </p>

      <ol className="space-y-5">
        {items.map((item) => {
          const direction = item.pct_change >= 0 ? "rose" : "fell"
          const sign = item.pct_change >= 0 ? "+" : ""
          const drivers = item.likely_drivers ?? []
          return (
            <li
              key={`${item.fv_change_date}-${item.fv_after}`}
              className="border-l-2 border-border pl-4 relative"
            >
              <div className="absolute -left-[5px] top-1.5 h-2 w-2 rounded-full bg-brand" />
              <div className="flex flex-wrap items-baseline justify-between gap-2 mb-1">
                <div className="text-sm font-medium text-ink">
                  {formatDate(item.fv_change_date)}
                </div>
                <span
                  className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${pctBadgeCls(
                    item.pct_change,
                  )}`}
                >
                  {sign}
                  {item.pct_change.toFixed(2)}%
                </span>
              </div>
              <p className="text-sm text-ink/90 leading-snug mb-2">
                Fair value {direction} from{" "}
                <span className="num tabular-nums font-medium">
                  {formatRupees(item.fv_before)}
                </span>{" "}
                to{" "}
                <span className="num tabular-nums font-medium">
                  {formatRupees(item.fv_after)}
                </span>
                {drivers.length > 0 ? (
                  <>
                    {" "}— likely linked to:
                  </>
                ) : (
                  <span className="text-caption">
                    {" "}— no clear headline driver in the news window.
                  </span>
                )}
              </p>
              {drivers.length > 0 && (
                <ul className="space-y-2 mt-2">
                  {drivers.map((d, di) => {
                    const sg = sentimentGlyph(d.sentiment_label)
                    const body = (
                      <div className="rounded-lg border border-border bg-surface/40 hover:bg-surface/70 transition px-3 py-2">
                        <p className="text-sm text-ink leading-snug">
                          {sg && (
                            <span
                              aria-label={`Headline sentiment: ${d.sentiment_label}`}
                              className={`mr-1.5 font-bold ${sg.cls}`}
                            >
                              {sg.glyph}
                            </span>
                          )}
                          {d.headline}
                        </p>
                        <div className="mt-1 flex items-center gap-2 flex-wrap text-[10px] text-caption">
                          <span>{d.source || "Unknown source"}</span>
                          {d.published_at && (
                            <>
                              <span aria-hidden="true">·</span>
                              <span>{formatDate(d.published_at)}</span>
                            </>
                          )}
                          {d.importance && d.importance !== "low" && (
                            <>
                              <span aria-hidden="true">·</span>
                              <span className="capitalize">
                                {d.importance}
                              </span>
                            </>
                          )}
                          <span aria-hidden="true">·</span>
                          <span
                            title="Composite relevance: recency + sentiment alignment + importance + source quality"
                          >
                            relevance {(d.relevance_score * 100).toFixed(0)}
                          </span>
                        </div>
                      </div>
                    )
                    return (
                      <li key={`${d.news_id}-${di}`}>
                        {d.url ? (
                          <a
                            href={d.url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="block"
                          >
                            {body}
                          </a>
                        ) : (
                          body
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
            </li>
          )
        })}
      </ol>

      <p className="mt-5 text-[10px] text-caption">
        Correlation only — these headlines were published near the fair
        value change, not proven to have caused it. Fair value is a
        model output; news is one of many possible inputs that move it.
      </p>
    </section>
  )
}
