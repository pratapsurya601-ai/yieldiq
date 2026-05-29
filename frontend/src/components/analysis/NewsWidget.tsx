"use client"

// NewsWidget — recent per-ticker news + BSE filings strip rendered in
// the Summary tab on /analysis/[ticker]. Self-fetches /api/v1/public/news/{ticker}
// (additive, no auth, 1h server cache) so the widget stays additive
// to the StockSummary contract. Shows up to 5 items with a link out to
// the full /stocks/{ticker}/news page. Renders nothing on empty/error.

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

interface NewsItem {
  headline: string
  source: string
  url: string
  published_at: string
  category: string
  importance: string
  // Added by backend/services/news_filters.py — present on every
  // item once the filter overhaul ships. Optional here so the
  // widget keeps rendering against an older API rollout window.
  topic?: string
  tier?: number
  // Day-79: source-quality tier (A/B/C) + human label.
  source_quality_tier?: "A" | "B" | "C"
  source_tier_label?: string
  // Day-85: title-only sentiment score in [-1, 1] + bucketed label.
  sentiment_score?: number
  sentiment_label?: "positive" | "neutral" | "negative"
}

interface TickerNewsResponse {
  ticker: string
  display_ticker: string
  count: number
  items: NewsItem[]
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function timeAgo(iso: string): string {
  if (!iso) return ""
  try {
    const d = new Date(iso)
    const diff = Date.now() - d.getTime()
    if (!isFinite(diff) || diff < 0) return ""
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

function importanceBadge(level: string): { text: string; cls: string } | null {
  if (level === "critical") return { text: "Critical", cls: "bg-tone-bad-bg text-tone-bad-fg border-tone-bad-bd" }
  if (level === "high") return { text: "High", cls: "bg-tone-warn-bg text-tone-warn-fg border-tone-warn-bd" }
  return null
}

// Day-79: chip styling for source-quality tier. Tier A/B are neutral
// (bg-bg / surface tokens); Tier C uses an amber tint to visually
// deprioritize US-aggregator sources without hiding them entirely.
function sourceTierChip(tier?: string): string {
  if (tier === "C") {
    return "bg-tone-warn-bg dark:bg-amber-900/20 text-amber-800 dark:text-amber-200 border-tone-warn-bd dark:border-amber-800"
  }
  return "bg-bg dark:bg-surface text-ink border-border"
}

// Day-85: small up/right/down glyph + color tint for title sentiment.
// Kept deliberately neutral in copy (no advisory verbs) — just a
// directional hint on the editorial slant of the headline itself.
function sentimentGlyph(label?: string): { glyph: string; cls: string } | null {
  if (label === "positive") return { glyph: "↑", cls: "text-emerald-600 dark:text-emerald-400" }
  if (label === "negative") return { glyph: "↓", cls: "text-rose-600 dark:text-rose-400" }
  if (label === "neutral") return { glyph: "→", cls: "text-caption" }
  return null
}

async function fetchNews(ticker: string): Promise<TickerNewsResponse | null> {
  const clean = ticker.replace(".NS", "").replace(".BO", "")
  const res = await fetch(`${API_BASE}/api/v1/public/news/${clean}?days=14`)
  if (!res.ok) return null
  return res.json()
}

interface Props {
  ticker: string
}

export default function NewsWidget({ ticker }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["news", ticker],
    queryFn: () => fetchNews(ticker),
    enabled: !!ticker,
    // 30-min stale window — news doesn't move FV; refetching is wasteful.
    staleTime: 30 * 60 * 1000,
    retry: 1,
  })

  if (isLoading) {
    return (
      <div className="bg-bg rounded-2xl border border-border p-4">
        <div className="h-4 w-24 bg-surface rounded animate-pulse mb-3" />
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-10 bg-surface rounded animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  const items = (data?.items ?? []).slice(0, 5)
  if (items.length === 0) return null

  const cleanTicker = ticker.replace(".NS", "").replace(".BO", "")

  // Day-79: avoid visual noise on all-Tier-A lists (India-native
  // sources only) — the chip carries no additional signal then.
  const showTierChips = items.some(
    (it) => it.source_quality_tier && it.source_quality_tier !== "A",
  )

  return (
    <div className="bg-bg rounded-2xl border border-border p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-ink">Recent news &amp; filings</h2>
        <Link
          href={`/stocks/${cleanTicker}/news`}
          className="text-xs text-brand hover:underline"
        >
          See all news →
        </Link>
      </div>
      <ul className="space-y-2">
        {items.map((item, i) => {
          const badge = importanceBadge(item.importance)
          const hasUrl = !!item.url
          const sg = sentimentGlyph(item.sentiment_label)
          const tierChipCls = sourceTierChip(item.source_quality_tier)
          const inner = (
            <div className="flex items-start justify-between gap-3 py-2 border-b border-border last:border-0">
              <div className="min-w-0 flex-1">
                <p className="text-sm text-ink leading-snug line-clamp-2">
                  {sg && (
                    <span
                      aria-label={`Headline sentiment: ${item.sentiment_label}`}
                      className={`mr-1 font-bold ${sg.cls}`}
                    >
                      {sg.glyph}
                    </span>
                  )}
                  {item.headline}
                </p>
                <div className="mt-1 flex items-center gap-2 flex-wrap text-[10px] text-caption">
                  <span>{item.source}</span>
                  {showTierChips && item.source_tier_label && (
                    <span
                      className={`px-1.5 py-0.5 rounded-full border text-caption ${tierChipCls}`}
                      title={`Source quality: ${item.source_tier_label}`}
                    >
                      {item.source_tier_label}
                    </span>
                  )}
                  {item.topic && item.topic !== "general" && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span className="capitalize px-1.5 py-0.5 rounded-full bg-surface text-ink/80 border border-border">
                        {item.topic.replace("-", " ")}
                      </span>
                    </>
                  )}
                  {item.category && !item.topic && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span className="capitalize">{item.category}</span>
                    </>
                  )}
                  {badge && (
                    <span
                      className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${badge.cls}`}
                    >
                      {badge.text}
                    </span>
                  )}
                </div>
              </div>
              <span className="text-[10px] text-caption flex-shrink-0 whitespace-nowrap">
                {timeAgo(item.published_at)}
              </span>
            </div>
          )
          return (
            <li key={`${item.url || item.headline}-${i}`}>
              {hasUrl ? (
                <a
                  href={item.url}
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
    </div>
  )
}
