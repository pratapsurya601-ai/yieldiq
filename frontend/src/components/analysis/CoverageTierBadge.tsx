"use client"

/**
 * CoverageTierBadge — A/B/C honest-framing pill.
 *
 * Renders next to the verdict pill in AnalysisHero. Shows the headline
 * tier (Tier A / B / C) with semantic color and the count "5 of 7 met".
 * Click expands an inline checklist of the seven rubric criteria so the
 * user can see exactly what's missing.
 *
 * Data flow:
 *   * Caller passes the optional `summary` already known from the
 *     payload (e.g. og-data hands `{tier, criteria_met}` for free).
 *   * On first expand we lazy-fetch the full rubric from
 *     /api/v1/coverage/{ticker}. Server caches it for 6h so this is
 *     low-cost on repeat opens.
 *
 * SEBI vocabulary: see scripts/check_sebi_words.py for the canonical banned-word list.
 * Use descriptive labels ("Modeled", "Coverage", "Limited"), not advisory or directional terms.
 *
 * Renders nothing if both `summary` and `ticker` are missing — keeps
 * the hero compact for legacy cached payloads predating the feature.
 */

import { useEffect, useState } from "react"
import { cn } from "@/lib/utils"
import { getCoverageTier } from "@/lib/api"
import type { CoverageTier, CoverageTierSummary } from "@/types/api"

interface CoverageTierBadgeProps {
  ticker?: string
  summary?: CoverageTierSummary | null
  size?: "sm" | "md"
}

const TIER_COPY = {
  A: {
    label: "Tier A",
    blurb: "Full-confidence modeling — deep history, broad cohort, clean data.",
  },
  B: {
    label: "Tier B",
    blurb: "Partial coverage — most inputs present, a few gaps or warnings.",
  },
  C: {
    label: "Tier C",
    blurb: "Limited coverage — recent listing, micro-cap, or thin data. Read with care.",
  },
} as const

const TIER_CLASSES = {
  A: "bg-emerald-50 text-emerald-700 border-emerald-200",
  B: "bg-amber-50 text-amber-700 border-amber-200",
  C: "bg-zinc-100 text-zinc-700 border-zinc-300",
} as const

const SIZE_CLASSES = {
  sm: "px-2 py-0.5 text-xs",
  md: "px-3 py-1 text-sm",
} as const

export default function CoverageTierBadge({
  ticker,
  summary,
  size = "md",
}: CoverageTierBadgeProps) {
  const [open, setOpen] = useState(false)
  const [full, setFull] = useState<CoverageTier | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || full || loading || !ticker) return
    setLoading(true)
    getCoverageTier(ticker)
      .then((data) => setFull(data))
      .catch(() => setError("Couldn’t load coverage details."))
      .finally(() => setLoading(false))
  }, [open, full, loading, ticker])

  // If we don't even have a summary tier *and* no ticker to fetch with,
  // don't render anything. This keeps the hero clean for cached payloads
  // from before the feature shipped.
  const tier = full?.tier ?? summary?.tier ?? null
  if (!tier && !ticker) return null

  // No summary yet? Still render a quiet "Coverage…" placeholder so the
  // layout is stable while we fetch on first open.
  const display = tier ?? "C"
  const copy = TIER_COPY[display]
  const tierClasses = TIER_CLASSES[display]
  const criteriaMet = full?.criteria_met ?? summary?.criteria_met ?? null

  return (
    <div className="inline-block align-top">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`${copy.label}: ${criteriaMet ?? "tap for details"}. ${copy.blurb}`}
        title={`${copy.label}${criteriaMet ? ` — ${criteriaMet} criteria met` : ""}. Click for details.`}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border font-medium transition hover:opacity-90",
          tierClasses,
          SIZE_CLASSES[size],
        )}
      >
        <span aria-hidden className="font-semibold">{copy.label}</span>
        {criteriaMet && (
          <span className="font-mono tabular-nums opacity-80">{criteriaMet}</span>
        )}
        <span aria-hidden className="text-[10px] opacity-60">
          {open ? "−" : "+"}
        </span>
      </button>

      {open && (
        <div
          className={cn(
            "mt-2 max-w-md rounded-xl border border-border bg-bg p-3 text-xs",
            "shadow-sm",
          )}
          role="region"
          aria-label="Coverage tier breakdown"
        >
          <p className="mb-2 text-caption">{copy.blurb}</p>

          {loading && <p className="text-caption">Loading rubric&hellip;</p>}
          {error && <p className="text-red-600">{error}</p>}

          {full?.rubric && full.rubric.length > 0 && (
            <ul className="space-y-1">
              {full.rubric.map((item) => (
                <li key={item.key} className="flex items-start gap-2">
                  <span
                    className={cn(
                      "mt-0.5 inline-block h-3 w-3 flex-shrink-0 rounded-full border",
                      item.passed
                        ? "bg-emerald-500 border-emerald-500"
                        : "bg-zinc-200 border-zinc-300",
                    )}
                    aria-hidden
                  />
                  <span className="flex-1">
                    <span className={cn(
                      "font-medium",
                      item.passed ? "text-ink" : "text-caption",
                    )}>
                      {item.label}
                    </span>
                    {item.value !== null && item.value !== undefined && (
                      <span className="ml-1 font-mono tabular-nums text-caption">
                        ({String(item.value)})
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <p className="mt-2 text-[10px] text-caption">
            <a href="/methodology/coverage" className="underline hover:no-underline">
              How we assign coverage tiers &rarr;
            </a>
          </p>
        </div>
      )}
    </div>
  )
}
