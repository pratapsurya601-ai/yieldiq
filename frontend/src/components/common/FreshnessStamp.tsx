"use client"

/**
 * FreshnessStamp — the generalised "last updated" caption used across
 * analysis surfaces. Where PriceTimestamp is specifically for the
 * delayed "as of HH:MM IST" caption under a live quote, this component
 * covers every other kind of freshness hint: "Latest filing: Mar 2024",
 * "Recomputed 4h ago", "Last dividend: Jan 16, 2025", etc.
 *
 * Design rules (2026-04-24, feat/freshness-stamps):
 *   - Text-only. No icons, no emoji — matches the descriptive-only
 *     tone the rest of the analysis surface uses.
 *   - Tiny, muted: `text-[11px] text-caption`. Never competes with
 *     the primary metric it annotates.
 *   - Always renders something when a `fallback` is provided, even
 *     for null timestamps — the caller can decide whether to bake in
 *     a "data freshness unknown" line or render nothing.
 *   - Hover surfaces the full ISO via `title=""`, never a floating UI.
 *     Preserves copy-paste & accessibility; no z-index wars.
 *
 * SEBI/language discipline:
 *   - Never call a price "Live". Prefer "Delayed" for real quotes, or
 *     "As of <HH:MM>" when the exact time is meaningful. The prefix
 *     is caller-controlled so that discipline is enforced at each
 *     wiring site, not hidden inside this component.
 */

import { formatRelativeTime, formatAbsoluteShort } from "@/lib/utils"

export interface FreshnessStampProps {
  /** ISO-8601 string or Date. Null/undefined triggers the fallback. */
  timestamp?: string | Date | null
  /**
   * Word(s) that precede the time phrase. "Updated" is the safest
   * default and the most neutral across SEBI concerns. Other common
   * values: "As of", "Latest filing", "Recomputed", "Last dividend",
   * "Delayed", "Prices".
   */
  prefix?: string
  /**
   * Rendered when `timestamp` is null/undefined/unparsable. When
   * omitted the component renders nothing in that case — useful when
   * the caller only wants the stamp if data is actually available.
   */
  fallback?: string
  /** Whether to expose the full ISO on hover via the title attribute. Default true. */
  showTooltip?: boolean
  /** Extra classes for positioning/layout. */
  className?: string
}

function parse(input: string | Date | null | undefined): Date | null {
  if (!input) return null
  const d = input instanceof Date ? input : new Date(input)
  return Number.isFinite(d.getTime()) ? d : null
}

export default function FreshnessStamp({
  timestamp,
  prefix = "Updated",
  fallback,
  showTooltip = true,
  className,
}: FreshnessStampProps) {
  const d = parse(timestamp)
  const cls = [
    "text-[11px] leading-snug text-caption",
    className,
  ].filter(Boolean).join(" ")

  if (!d) {
    if (!fallback) return null
    return <span className={cls}>{fallback}</span>
  }

  const now = Date.now()
  const diffMs = now - d.getTime()
  const sevenDaysMs = 7 * 24 * 60 * 60 * 1000
  const isAbsolute = diffMs >= sevenDaysMs || diffMs < 0
  const phrase = isAbsolute ? formatAbsoluteShort(d) : formatRelativeTime(d)

  // "Latest filing: Mar 2024" — use a colon when the phrase is an
  // absolute date label. "Updated 5m ago" reads better without punctuation.
  const body = isAbsolute ? `${prefix}: ${phrase}` : `${prefix} ${phrase}`

  return (
    <span
      className={cls}
      title={showTooltip ? d.toISOString() : undefined}
    >
      {body}
    </span>
  )
}
