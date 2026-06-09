// frontend/src/components/analysis/ELI15ThesisPanel.tsx
//
// "Why the model sees it this way" — the ELI15 (explain-like-I'm-15)
// 3-bullet plain-English thesis panel. Lives directly below the
// hero band / verdict pill and above the DCF / valuation summary
// panels on the analysis page — this is what a non-expert reads
// AFTER seeing the verdict but BEFORE wading into the deep-dive
// numbers.
//
// Bullets are produced by GET /api/v1/analysis/{ticker}/eli15-thesis
// — Claude-generated, SEBI-post-filtered server-side, cached per
// (ticker, day). This component is pure presentation: it never
// massages the bullet text. If the backend returns an empty
// bullets array (or 503s), the panel hides itself rather than
// rendering a "AI failed" message — looks bad on a research page.
//
// States:
//   Loading: 3 shimmer-skeleton lines (matches the eventual layout)
//   Error:   render nothing
//   Empty:   render nothing (backend already returned a fallback
//            template if Claude was unreachable, so empty here means
//            something genuinely went wrong upstream)
//   Loaded:  3 bullets + dated disclaimer + "Adjust assumptions" link

import React from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"

import { getELI15Thesis, type ELI15ThesisResponse } from "@/lib/api"

interface Props {
  ticker: string
  // SSR-friendly prefetched payload. When supplied, the panel
  // renders immediately and the useQuery only re-validates in the
  // background. Optional — most callers pass nothing and let the
  // query run on mount.
  initialData?: ELI15ThesisResponse | null
}

export default function ELI15ThesisPanel({ ticker, initialData }: Props) {
  const { data, isLoading, isError } = useQuery<ELI15ThesisResponse>({
    queryKey: ["eli15-thesis", ticker],
    queryFn: () => getELI15Thesis(ticker),
    // Refetch at most once per day — the backend caches per IST day.
    staleTime: 60 * 60 * 1000,  // 1h
    refetchOnWindowFocus: false,
    retry: 1,
    initialData: initialData ?? undefined,
  })

  // Hide entirely on error — never show a broken-AI surface.
  if (isError) return null

  if (isLoading && !data) {
    return <ELI15ThesisSkeleton />
  }

  if (!data || !data.bullets || data.bullets.length === 0) {
    return null
  }

  // Defensive: never render more than 3 bullets (server-side is
  // also clamped, but belt-and-braces).
  const bullets = data.bullets.slice(0, 3)

  return (
    <section
      data-testid="eli15-thesis-panel"
      aria-label="Why the model sees it this way"
      className="rounded-2xl border border-border bg-bg dark:bg-surface p-5 md:p-6 space-y-3"
    >
      <header className="flex items-center gap-2">
        <span
          aria-hidden
          className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-brand-50 text-brand text-sm font-semibold"
        >
          AI
        </span>
        <h2 className="text-sm md:text-base font-semibold text-ink tracking-tight uppercase">
          Why the model sees it this way
        </h2>
      </header>

      <ul className="space-y-2.5 pt-1">
        {bullets.map((b, i) => (
          <li
            key={i}
            className="flex gap-2.5 text-sm md:text-[15px] text-ink leading-relaxed"
          >
            <span
              aria-hidden
              className="mt-2 inline-block w-1.5 h-1.5 rounded-full shrink-0 bg-brand"
            />
            <span className="min-w-0">{b}</span>
          </li>
        ))}
      </ul>

      <footer className="pt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-caption border-t border-border mt-3">
        <span>{data.disclaimer}</span>
        <Link
          href={`/analysis/${ticker}/playground`}
          className="text-brand hover:underline font-medium"
        >
          Adjust assumptions
          <span aria-hidden> →</span>
        </Link>
      </footer>
    </section>
  )
}


function ELI15ThesisSkeleton() {
  return (
    <div
      data-testid="eli15-thesis-skeleton"
      aria-busy="true"
      aria-label="Loading model thesis"
      className="rounded-2xl border border-border bg-bg dark:bg-surface p-5 md:p-6 space-y-3"
    >
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-full bg-surface animate-pulse" />
        <div className="h-4 w-64 rounded bg-surface animate-pulse" />
      </div>
      <ul className="space-y-2.5 pt-1">
        {[0, 1, 2].map((i) => (
          <li key={i} className="flex gap-2.5">
            <div className="mt-2 w-1.5 h-1.5 rounded-full bg-surface animate-pulse shrink-0" />
            <div className="flex-1 space-y-1.5">
              <div className="h-3.5 w-full rounded bg-surface animate-pulse" />
              <div className="h-3.5 w-5/6 rounded bg-surface animate-pulse" />
            </div>
          </li>
        ))}
      </ul>
      <div className="pt-2 border-t border-border mt-3">
        <div className="h-3 w-80 rounded bg-surface animate-pulse" />
      </div>
    </div>
  )
}
