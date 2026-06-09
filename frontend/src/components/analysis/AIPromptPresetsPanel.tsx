// frontend/src/components/analysis/AIPromptPresetsPanel.tsx
//
// Premium Feel R4 (2026-06-09) — AI prompt presets panel.
//
// AlphaSpread's killer move from the competitor audit at
// tmp/analysis_page_competitor_audit.md was a small grid of "preset
// question" cards on every analysis page that, on click, opens an
// AI answer to a stock-scoped question. This is our SEBI-safe take:
//
//   * The three cards are fetched from /api/v1/public/ai-explain/presets
//     so the wire copy comes from a single backend source of truth.
//   * On card click we POST { ticker, preset_id } to /ai-explain;
//     the panel renders the answer INLINE inside the card (no modal,
//     no chat thread, no follow-up turn — single Q -> A).
//   * Loading state shows a skeleton matching the eventual answer
//     shape (3 paragraph bars + 3 bullet bars).
//   * Error state shows a one-line retry CTA — never silently empty.
//   * Honest disclaimer is rendered beneath every answer, sourced
//     from the backend so the wording stays in sync.
//
// The component fetches presets ONCE on mount; the per-card answer
// only fires on click. Each preset has its own React Query so
// expanding multiple cards in sequence doesn't trash earlier
// answers — both cards stay expanded with their cached answers.

"use client"
import React, { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"

import {
  getAIPresets,
  postAIExplain,
  type AIExplainResponse,
  type AIPresetCard,
  type AIPresetsResponse,
} from "@/lib/api"

interface Props {
  ticker: string
}

// Single-character glyph per preset.icon token. The backend returns
// short SEBI-safe tokens (lens / dial / grid); the frontend picks the
// visual mark so designers can iterate on the look without backend
// deploys. Falls back to a neutral spark glyph for unknown tokens.
function iconGlyph(token: string): string {
  switch ((token || "").toLowerCase()) {
    case "lens":
      return "L"
    case "dial":
      return "D"
    case "grid":
      return "G"
    default:
      return "A"
  }
}

export default function AIPromptPresetsPanel({ ticker }: Props) {
  const presetsQuery = useQuery<AIPresetsResponse>({
    queryKey: ["ai-presets"],
    queryFn: getAIPresets,
    staleTime: 60 * 60 * 1000, // 1h — copy is hard-coded backend-side.
    refetchOnWindowFocus: false,
    retry: 1,
  })

  if (presetsQuery.isError) {
    // Render nothing when the catalogue endpoint is down — better
    // than a half-broken panel labelled "AI" that does nothing.
    return null
  }

  const isLoadingPresets = presetsQuery.isLoading && !presetsQuery.data
  const presets = presetsQuery.data?.presets ?? []
  const fallbackDisclaimer =
    presetsQuery.data?.disclaimer ??
    "AI-generated explanation, educational use only. Not investment advice."

  return (
    <section
      data-testid="ai-prompt-presets-panel"
      aria-label="Ask the model"
      className="rounded-2xl border border-border bg-bg dark:bg-surface p-5 md:p-6 space-y-4"
    >
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-brand-50 text-brand text-sm font-semibold"
          >
            AI
          </span>
          <h2 className="text-sm md:text-base font-semibold text-ink tracking-tight uppercase">
            Ask the model
          </h2>
        </div>
        <p className="text-[11px] text-caption">
          One-shot answers grounded in this stock&rsquo;s analysis
        </p>
      </header>

      {isLoadingPresets ? (
        <PresetsGridSkeleton />
      ) : presets.length === 0 ? null : (
        <div
          data-testid="ai-presets-grid"
          className="grid grid-cols-1 md:grid-cols-3 gap-3"
        >
          {presets.map((p) => (
            <PresetCard
              key={p.preset_id}
              ticker={ticker}
              preset={p}
              fallbackDisclaimer={fallbackDisclaimer}
            />
          ))}
        </div>
      )}
    </section>
  )
}


// ── Per-card sub-component ──────────────────────────────────────

interface PresetCardProps {
  ticker: string
  preset: AIPresetCard
  fallbackDisclaimer: string
}

function PresetCard({ ticker, preset, fallbackDisclaimer }: PresetCardProps) {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [answer, setAnswer] = useState<AIExplainResponse | null>(null)

  const queryKey = ["ai-explain", ticker, preset.preset_id]

  const runFetch = async () => {
    // Expand IMMEDIATELY so the skeleton paints inside the card while
    // the fetch is in flight. Setting expanded only after the promise
    // resolves left a "Thinking…" button next to a collapsed card —
    // the user got no visual feedback that anything was happening.
    setExpanded(true)
    setLoading(true)
    setError(null)
    try {
      const data = await queryClient.fetchQuery<AIExplainResponse>({
        queryKey,
        queryFn: () => postAIExplain(ticker, preset.preset_id),
        staleTime: 30 * 1000, // matches the backend's 30s cache.
      })
      setAnswer(data)
    } catch (err) {
      const msg =
        (err as { response?: { status?: number } })?.response?.status === 429
          ? "Daily AI limit reached. Upgrade for unlimited explanations."
          : "Could not generate explanation. Try again."
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const onCardClick = () => {
    // If already expanded with content, collapse instead of refetch.
    if (expanded && (answer || error)) {
      setExpanded(false)
      return
    }
    runFetch()
  }

  const onRetry = () => {
    setAnswer(null)
    setError(null)
    runFetch()
  }

  return (
    <article
      data-testid={`ai-preset-card-${preset.preset_id}`}
      data-preset-id={preset.preset_id}
      data-expanded={expanded ? "true" : "false"}
      className="rounded-xl border border-border bg-surface dark:bg-bg p-4 flex flex-col gap-3 transition-colors hover:border-brand/40"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-brand-50 text-brand text-xs font-mono font-bold shrink-0"
        >
          {iconGlyph(preset.icon)}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-ink leading-snug">
            {preset.title}
          </h3>
          <p className="text-[12px] text-caption leading-snug mt-1">
            {preset.preview}
          </p>
        </div>
      </div>

      <button
        type="button"
        onClick={onCardClick}
        disabled={loading}
        aria-busy={loading || undefined}
        aria-expanded={expanded}
        data-testid={`ai-preset-cta-${preset.preset_id}`}
        className="inline-flex items-center justify-center self-start px-3 py-1.5 min-h-[36px] rounded-lg bg-brand text-white text-xs font-semibold hover:opacity-90 active:scale-[0.98] disabled:opacity-60 transition"
      >
        {loading
          ? "Thinking…"
          : expanded && (answer || error)
            ? "Hide answer"
            : "Get the answer"}
      </button>

      {expanded && loading && (
        <AnswerSkeleton testid={`ai-answer-skeleton-${preset.preset_id}`} />
      )}

      {expanded && !loading && error && (
        <div
          role="alert"
          data-testid={`ai-answer-error-${preset.preset_id}`}
          className="rounded-lg border border-[color:var(--color-danger)]/30 bg-[color:var(--color-danger)]/5 p-3 text-xs text-ink space-y-2"
        >
          <p>{error}</p>
          <button
            type="button"
            onClick={onRetry}
            data-testid={`ai-answer-retry-${preset.preset_id}`}
            className="inline-flex items-center px-2.5 py-1 min-h-[32px] text-[11px] font-semibold text-brand bg-brand-50 rounded-md hover:opacity-90 transition"
          >
            Retry
          </button>
        </div>
      )}

      {expanded && !loading && !error && answer && (
        <div
          data-testid={`ai-answer-${preset.preset_id}`}
          className="space-y-3 text-sm text-ink leading-relaxed border-t border-border pt-3"
        >
          {answer.answer
            .split(/\n{2,}/)
            .map((para, i) => (
              <p key={i} className="whitespace-pre-line">
                {para}
              </p>
            ))}
          <p
            data-testid={`ai-answer-disclaimer-${preset.preset_id}`}
            className="text-[11px] text-caption pt-2 border-t border-border"
          >
            {answer.disclaimer || fallbackDisclaimer}
          </p>
        </div>
      )}
    </article>
  )
}


// ── Skeletons — match the SHAPE of the final layout ─────────────

function PresetsGridSkeleton() {
  return (
    <div
      data-testid="ai-presets-grid-skeleton"
      aria-busy="true"
      aria-label="Loading"
      className="grid grid-cols-1 md:grid-cols-3 gap-3"
    >
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="rounded-xl border border-border bg-surface dark:bg-bg p-4 flex flex-col gap-3"
          style={{ animationDelay: `${i * 60}ms` }}
        >
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-border/60 animate-pulse shrink-0" />
            <div className="flex-1 space-y-2">
              <div className="h-3.5 w-3/4 rounded bg-border/60 animate-pulse" />
              <div className="h-3 w-full rounded bg-border/60 animate-pulse" />
            </div>
          </div>
          <div className="h-8 w-28 rounded-lg bg-border/60 animate-pulse" />
        </div>
      ))}
    </div>
  )
}

function AnswerSkeleton({ testid }: { testid: string }) {
  // Matches the eventual answer shape: 2-3 paragraph bars + a short
  // bullet list. Staggered animation-delay gives a premium shimmer.
  return (
    <div
      data-testid={testid}
      aria-busy="true"
      aria-label="Loading"
      className="space-y-3 border-t border-border pt-3"
    >
      <div className="space-y-1.5">
        <div className="h-3 w-full rounded bg-border/60 animate-pulse" />
        <div className="h-3 w-5/6 rounded bg-border/60 animate-pulse" style={{ animationDelay: "60ms" }} />
        <div className="h-3 w-4/6 rounded bg-border/60 animate-pulse" style={{ animationDelay: "120ms" }} />
      </div>
      <div className="space-y-1.5">
        <div className="h-3 w-full rounded bg-border/60 animate-pulse" style={{ animationDelay: "180ms" }} />
        <div className="h-3 w-3/4 rounded bg-border/60 animate-pulse" style={{ animationDelay: "240ms" }} />
      </div>
      <ul className="space-y-1.5 pl-3">
        {[0, 1, 2].map((i) => (
          <li key={i} className="flex items-center gap-2">
            <div className="w-1 h-1 rounded-full bg-border/60 animate-pulse shrink-0" />
            <div
              className="h-2.5 flex-1 rounded bg-border/60 animate-pulse"
              style={{ animationDelay: `${300 + i * 60}ms` }}
            />
          </li>
        ))}
      </ul>
    </div>
  )
}
