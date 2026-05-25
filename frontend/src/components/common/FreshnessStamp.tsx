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
  /**
   * Task #197 (feat/as-of-plumbing) — when true, derives a color tier
   * from the timestamp age and uses tier-specific prefixes. Maintains
   * SEBI honesty: "Live ~Xm ago" is only used when the source
   * (live_quotes) is genuinely <30m old, which is the bhavcopy cron's
   * refresh window. Tiers:
   *   - age <30m → green "Live ~Xm ago"
   *   - 30m–4h  → yellow "Delayed ~Xh ago"
   *   - >4h     → red "Stale — Xh ago"
   * `prefix` is ignored when `tiered` is true. `fallback` still applies
   * when the timestamp is null/unparsable.
   */
  tiered?: boolean
  /**
   * Convenience alias for callers that pass the backend `as_of`
   * field name directly. Equivalent to `timestamp` — last-write wins
   * if both are set, with `timestamp` taking precedence (since it's
   * the older, established prop). Optional.
   */
  asOf?: string | Date | null
}

interface TierResult {
  prefix: string
  phrase: string
  colorCls: string
}

/**
 * Pure helper exported for tests (FreshnessStamp.test.tsx asserts the
 * boundaries at <30m green, 30m-4h yellow, >4h red).
 */
export function computeTier(ageMs: number): TierResult {
  const m = Math.max(0, Math.floor(ageMs / 60000))
  const h = Math.floor(ageMs / 3600000)
  if (ageMs < 30 * 60 * 1000) {
    return {
      prefix: "Live",
      phrase: `~${Math.max(1, m)}m ago`,
      colorCls: "text-emerald-600 dark:text-emerald-400",
    }
  }
  if (ageMs < 4 * 3600 * 1000) {
    return {
      prefix: "Delayed",
      phrase: `~${Math.max(1, h)}h ago`,
      colorCls: "text-amber-600 dark:text-amber-400",
    }
  }
  return {
    prefix: "Stale —",
    phrase: `${Math.max(1, h)}h ago`,
    colorCls: "text-rose-600 dark:text-rose-400",
  }
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
  tiered = false,
  asOf,
}: FreshnessStampProps) {
  const d = parse(timestamp ?? asOf)
  const baseCls = "text-[11px] leading-snug"
  const defaultCls = `${baseCls} text-caption`

  if (!d) {
    if (!fallback) return null
    return (
      <span className={[defaultCls, className].filter(Boolean).join(" ")}>
        {fallback}
      </span>
    )
  }

  if (tiered) {
    const diffMs = Math.max(0, Date.now() - d.getTime())
    const tier = computeTier(diffMs)
    const cls = [baseCls, tier.colorCls, className].filter(Boolean).join(" ")
    return (
      <span className={cls} title={showTooltip ? d.toISOString() : undefined}>
        {`${tier.prefix} ${tier.phrase}`}
      </span>
    )
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
      className={[defaultCls, className].filter(Boolean).join(" ")}
      title={showTooltip ? d.toISOString() : undefined}
    >
      {body}
    </span>
  )
}
