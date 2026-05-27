"use client"

// CommunitySentiment — "How do you feel?" voting widget + aggregated
// community sentiment per ticker. Shipped Week-3 of the design manifesto
// (engagement loop). Calls three additive public endpoints:
//
//   GET  /api/v1/public/sentiment/{ticker}            — counts + your_vote
//   POST /api/v1/public/sentiment/{ticker}/vote       — upserts user vote
//   GET  /api/v1/public/sentiment/{ticker}/history    — 30d daily series
//
// SEBI safety: labels (Bearish/Neutral/Bullish) are not in
// backend/services/analysis/sebi_filter.py BANNED_WORDS. All copy is
// framed as a user view, never advisory.

import { useMemo, useState } from "react"
import Link from "next/link"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useAuthStore } from "@/store/authStore"
import { CountUp } from "@/components/anim"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

type Sentiment = "bearish" | "neutral" | "bullish"

interface AggregateResponse {
  ticker: string
  total_votes: number
  bullish_count: number
  neutral_count: number
  bearish_count: number
  bullish_pct: number
  neutral_pct: number
  bearish_pct: number
  your_vote: Sentiment | null
  as_of: string
}

interface HistoryPoint {
  date: string
  bullish: number
  neutral: number
  bearish: number
}

interface HistoryResponse {
  ticker: string
  days: number
  points: HistoryPoint[]
}

function cleanTicker(ticker: string): string {
  return ticker
    .toUpperCase()
    .replace(".NS", "")
    .replace(".BO", "")
    .replace(".BSE", "")
    .replace(".NSE", "")
}

async function fetchAggregate(
  ticker: string,
  token: string | null,
): Promise<AggregateResponse> {
  const clean = cleanTicker(ticker)
  const res = await fetch(`${API_BASE}/api/v1/public/sentiment/${clean}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  if (!res.ok) throw new Error("aggregate fetch failed")
  return res.json()
}

async function fetchHistory(ticker: string): Promise<HistoryResponse> {
  const clean = cleanTicker(ticker)
  const res = await fetch(
    `${API_BASE}/api/v1/public/sentiment/${clean}/history?days=30`,
  )
  if (!res.ok) throw new Error("history fetch failed")
  return res.json()
}

async function postVote(
  ticker: string,
  sentiment: Sentiment,
  token: string,
): Promise<AggregateResponse> {
  const clean = cleanTicker(ticker)
  const res = await fetch(
    `${API_BASE}/api/v1/public/sentiment/${clean}/vote`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ sentiment }),
    },
  )
  if (!res.ok) {
    const txt = await res.text().catch(() => "")
    throw new Error(`vote failed: ${res.status} ${txt}`)
  }
  return res.json()
}

// Lean-direction copy is descriptive, not advisory. Uses only SEBI-safe
// vocabulary; mirrors the same words shown on the buttons.
function leaningCopy(agg: AggregateResponse | undefined): string {
  if (!agg || agg.total_votes === 0) {
    return "No community votes yet. Cast yours to start the conversation."
  }
  const { bullish_pct, neutral_pct, bearish_pct } = agg
  const max = Math.max(bullish_pct, neutral_pct, bearish_pct)
  if (max === bullish_pct) return "Community is leaning bullish."
  if (max === bearish_pct) return "Community is leaning bearish."
  return "Community sits at neutral."
}

interface VoteButtonProps {
  label: string
  glyph: string
  active: boolean
  busy: boolean
  baseTint: string
  activeTint: string
  onClick: () => void
}

function VoteButton({
  label,
  glyph,
  active,
  busy,
  baseTint,
  activeTint,
  onClick,
}: VoteButtonProps) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={busy}
      onClick={onClick}
      className={[
        "flex-1 min-w-0 rounded-2xl border px-3 py-3 sm:px-4 sm:py-4",
        "flex flex-col items-center justify-center gap-1",
        "transition-all duration-150 ease-out",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
        "focus-visible:ring-offset-bg",
        active ? activeTint : baseTint,
        active ? "ring-2 ring-offset-2 ring-offset-bg" : "",
        busy ? "opacity-60 cursor-wait" : "hover:scale-[1.01] cursor-pointer",
      ].join(" ")}
    >
      <span className="text-2xl sm:text-3xl leading-none" aria-hidden>
        {glyph}
      </span>
      <span className="text-sm font-semibold tracking-wide">{label}</span>
    </button>
  )
}

// 30-day stacked-area-ish sparkline. Plain SVG, no external dep —
// keeps the bundle from growing for a single 200x40 chart. Bullish on
// top (emerald), neutral middle (slate), bearish bottom (rose).
function Sparkline({ history }: { history: HistoryResponse | undefined }) {
  const points = history?.points ?? []
  if (points.length < 2) {
    return (
      <p className="text-xs text-caption italic">
        30-day trend will show once we have a few days of votes.
      </p>
    )
  }
  const W = 220
  const H = 36
  const totals = points.map((p) => p.bullish + p.neutral + p.bearish)
  const xs = points.map((_, i) => (i / (points.length - 1)) * W)
  const bullishPath = points
    .map((p, i) => {
      const t = totals[i] || 1
      const y = H - (p.bullish / t) * H
      return `${i === 0 ? "M" : "L"} ${xs[i].toFixed(1)} ${y.toFixed(1)}`
    })
    .join(" ")
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height={H}
      aria-label="30-day community sentiment trend"
      role="img"
      className="overflow-visible"
    >
      {/* Baseline */}
      <line
        x1={0}
        x2={W}
        y1={H}
        y2={H}
        className="stroke-border"
        strokeWidth={1}
      />
      <path
        d={bullishPath}
        fill="none"
        className="stroke-emerald-500 dark:stroke-emerald-400"
        strokeWidth={1.5}
      />
    </svg>
  )
}

interface Props {
  ticker: string
  companyName?: string
}

export default function CommunitySentiment({ ticker, companyName }: Props) {
  const token = useAuthStore((s) => s.token)
  const queryClient = useQueryClient()
  const [showLoginPrompt, setShowLoginPrompt] = useState(false)
  const [pendingChoice, setPendingChoice] = useState<Sentiment | null>(null)

  const aggKey = useMemo(
    () => ["community-sentiment", cleanTicker(ticker)],
    [ticker],
  )
  const histKey = useMemo(
    () => ["community-sentiment-history", cleanTicker(ticker)],
    [ticker],
  )

  const aggQuery = useQuery({
    queryKey: aggKey,
    queryFn: () => fetchAggregate(ticker, token),
    enabled: !!ticker,
    staleTime: 60 * 1000,
    retry: 1,
  })

  const historyQuery = useQuery({
    queryKey: histKey,
    queryFn: () => fetchHistory(ticker),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const voteMutation = useMutation({
    mutationFn: async (sentiment: Sentiment) => {
      if (!token) throw new Error("not_authenticated")
      return postVote(ticker, sentiment, token)
    },
    onMutate: async (sentiment) => {
      setPendingChoice(sentiment)
      await queryClient.cancelQueries({ queryKey: aggKey })
      const prev = queryClient.getQueryData<AggregateResponse>(aggKey)
      if (prev) {
        const next: AggregateResponse = { ...prev }
        // Decrement old vote if user is changing their mind.
        if (prev.your_vote && prev.your_vote !== sentiment) {
          const oldKey = `${prev.your_vote}_count` as keyof AggregateResponse
          ;(next[oldKey] as number) = Math.max(
            0,
            (prev[oldKey] as number) - 1,
          )
        }
        // Increment new vote (only if it's not already your vote).
        if (prev.your_vote !== sentiment) {
          const newKey = `${sentiment}_count` as keyof AggregateResponse
          ;(next[newKey] as number) = (prev[newKey] as number) + 1
          if (!prev.your_vote) next.total_votes = prev.total_votes + 1
        }
        next.your_vote = sentiment
        const total = next.total_votes || 1
        next.bullish_pct = Math.round((next.bullish_count / total) * 1000) / 10
        next.neutral_pct = Math.round((next.neutral_count / total) * 1000) / 10
        next.bearish_pct = Math.round((next.bearish_count / total) * 1000) / 10
        queryClient.setQueryData(aggKey, next)
      }
      return { prev }
    },
    onError: (_err, _sent, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(aggKey, ctx.prev)
    },
    onSuccess: (data) => {
      queryClient.setQueryData(aggKey, data)
      queryClient.invalidateQueries({ queryKey: histKey })
    },
    onSettled: () => {
      setPendingChoice(null)
    },
  })

  const handleVote = (sentiment: Sentiment) => {
    if (!token) {
      setShowLoginPrompt(true)
      return
    }
    voteMutation.mutate(sentiment)
  }

  const agg = aggQuery.data
  const yourVote = agg?.your_vote ?? null
  const busy = voteMutation.isPending
  const target = companyName || cleanTicker(ticker)

  return (
    <div className="bg-bg rounded-2xl border border-border p-4 sm:p-6 space-y-4">
      {/* Prompt */}
      <div>
        <h3 className="text-sm sm:text-base font-semibold tracking-wide uppercase text-ink">
          How do you feel about {target}?
        </h3>
        <p className="text-xs text-caption italic mt-1 max-w-prose">
          Your view, not investment advice. We aggregate anonymously to
          show how the YieldIQ community is reading the same numbers.
        </p>
      </div>

      {/* Vote buttons */}
      <div className="flex gap-2 sm:gap-3">
        <VoteButton
          label="Bearish"
          glyph="🐻"
          active={yourVote === "bearish"}
          busy={busy && pendingChoice === "bearish"}
          baseTint="bg-surface border-border text-ink hover:border-rose-300"
          activeTint="bg-rose-50 dark:bg-rose-900/20 border-rose-300 dark:border-rose-700 text-rose-700 dark:text-rose-300 ring-rose-400"
          onClick={() => handleVote("bearish")}
        />
        <VoteButton
          label="Neutral"
          glyph="🟦"
          active={yourVote === "neutral"}
          busy={busy && pendingChoice === "neutral"}
          baseTint="bg-surface border-border text-ink hover:border-slate-400"
          activeTint="bg-slate-100 dark:bg-slate-800 border-slate-400 dark:border-slate-500 text-ink ring-slate-400"
          onClick={() => handleVote("neutral")}
        />
        <VoteButton
          label="Bullish"
          glyph="🟢"
          active={yourVote === "bullish"}
          busy={busy && pendingChoice === "bullish"}
          baseTint="bg-surface border-border text-ink hover:border-emerald-300"
          activeTint="bg-tone-good-bg dark:bg-emerald-900/20 border-emerald-300 dark:border-emerald-700 text-tone-good-fg dark:text-emerald-300 ring-emerald-400"
          onClick={() => handleVote("bullish")}
        />
      </div>

      {/* Sign-in prompt — inline, dismissable */}
      {showLoginPrompt && !token ? (
        <div
          role="alert"
          className="rounded-xl border border-tone-warn-bd dark:border-amber-800 bg-tone-warn-bg dark:bg-amber-900/20 p-3 text-sm text-amber-900 dark:text-amber-200 flex items-start gap-3"
        >
          <span aria-hidden>🔒</span>
          <div className="flex-1 min-w-0">
            <p className="font-medium">Sign in to share your view.</p>
            <p className="text-xs mt-1">
              We use your account to make sure each vote counts once.
            </p>
          </div>
          <div className="flex flex-col gap-1 shrink-0">
            <Link
              href="/login"
              className="text-xs font-semibold underline underline-offset-2"
            >
              Sign in
            </Link>
            <button
              type="button"
              className="text-xs text-caption hover:text-ink"
              onClick={() => setShowLoginPrompt(false)}
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      <hr className="border-border" />

      {/* Aggregated breakdown */}
      <div>
        <p className="text-xs uppercase tracking-wide text-caption font-semibold">
          Community sentiment{" "}
          <span className="text-ink">
            (
            <CountUp to={agg?.total_votes ?? 0} duration={0.8} decimals={0} />
            {" "}
            {agg?.total_votes === 1 ? "vote" : "votes"})
          </span>
        </p>

        <div className="mt-3 space-y-2">
          <SentimentBar
            label="Bullish"
            glyph="🟢"
            pct={agg?.bullish_pct ?? 0}
            barClass="bg-emerald-500 dark:bg-emerald-400"
            loading={aggQuery.isLoading}
          />
          <SentimentBar
            label="Neutral"
            glyph="🟦"
            pct={agg?.neutral_pct ?? 0}
            barClass="bg-slate-400 dark:bg-slate-500"
            loading={aggQuery.isLoading}
          />
          <SentimentBar
            label="Bearish"
            glyph="🐻"
            pct={agg?.bearish_pct ?? 0}
            barClass="bg-rose-500 dark:bg-rose-400"
            loading={aggQuery.isLoading}
          />
        </div>

        <p className="mt-4 text-sm text-ink italic">{leaningCopy(agg)}</p>
      </div>

      {/* 30-day trend */}
      <div>
        <p className="text-xs uppercase tracking-wide text-caption font-semibold mb-1">
          30-day bullish share trend
        </p>
        <Sparkline history={historyQuery.data} />
      </div>
    </div>
  )
}

interface SentimentBarProps {
  label: string
  glyph: string
  pct: number
  barClass: string
  loading: boolean
}

function SentimentBar({ label, glyph, pct, barClass, loading }: SentimentBarProps) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-20 sm:w-24 flex items-center gap-1.5 text-ink shrink-0">
        <span aria-hidden>{glyph}</span>
        <span>{label}</span>
      </span>
      <span className="w-12 text-right tabular-nums font-semibold text-ink">
        {loading ? (
          "—"
        ) : (
          <>
            <CountUp to={pct} duration={1.0} decimals={0} />%
          </>
        )}
      </span>
      <div
        className="flex-1 h-2.5 rounded-full bg-surface overflow-hidden"
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label} share`}
      >
        <div
          className={`h-full ${barClass} transition-[width] duration-700 ease-out`}
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
        />
      </div>
    </div>
  )
}
