"use client"

/**
 * NarrativeSummary — one-sentence AI conclusion rendered ABOVE the
 * Prism hex on /analysis/[ticker].
 *
 * Task brief (feat/ai-narrative-summary, 2026-04-21):
 *   Users currently have to interpret 6 ratio cards + the Prism hex +
 *   scenario cases to understand "should I buy?". This component
 *   surfaces the conclusion in ~2 seconds of reading.
 *
 * Content is generated server-side by AnalysisService.generate_narrative_summary
 * (Groq llama-3.3-70b-versatile) at analysis cold-compute time and
 * cached in the analysis_cache tiers. The frontend never triggers
 * generation — we simply read AnalysisResponse.ai_summary.
 *
 * Rendering rules:
 *   - If `summary` is null, empty, or whitespace-only, render nothing.
 *     NO loading skeleton, NO "generating…" placeholder, NO fallback
 *     copy. The absence is the UI.
 *   - Shown for ALL users, including tier-gated ones (this is a
 *     teaser, not gated content).
 */

import { cn } from "@/lib/utils"

interface NarrativeSummaryProps {
  summary: string | null | undefined
  className?: string
}

export default function NarrativeSummary({
  summary,
  className,
}: NarrativeSummaryProps) {
  const trimmed = (summary ?? "").trim()
  if (!trimmed) return null

  return (
    <div
      className={cn(
        // Subtle gradient accent border using before: pseudo via ring.
        // Rounded container that sits comfortably above the editorial hero.
        "relative rounded-2xl border border-border bg-gradient-to-br " +
          "from-[color:var(--color-brand-50)] via-surface to-surface " +
          "px-4 py-3.5 sm:px-5 sm:py-4",
        className,
      )}
      role="note"
      aria-label="AI-generated analysis summary"
    >
      <p className="font-editorial text-[0.95rem] sm:text-base leading-relaxed text-ink">
        {trimmed}
      </p>
      <div className="mt-2 flex items-center gap-1.5 text-[0.68rem] uppercase tracking-[0.08em] text-caption">
        <svg
          aria-hidden
          className="h-3 w-3 text-brand"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z"
          />
        </svg>
        <span className="font-medium">AI summary</span>
        <span aria-hidden>·</span>
        <span>Powered by Groq</span>
      </div>
    </div>
  )
}
