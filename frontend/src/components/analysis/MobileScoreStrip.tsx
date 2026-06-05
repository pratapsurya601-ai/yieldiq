"use client"

/**
 * MobileScoreStrip — spec §6.
 *
 * ORDER OF SACRIFICE (DO NOT REORDER WITHOUT REVIEW):
 *   1. Drop Score    (quality grade — duplicated in Quality tab)
 *   2. Drop Moat     (qualitative tag — duplicated in Quality tab)
 *   3. NEVER drop:   Verdict, FV, Discount, Worry
 * The brand promise is honesty about RISK and PRICE. Quality grading is
 * secondary. If the device is too narrow for 4 tiles, drop in the order
 * above and document the breakpoint.
 *
 * The 4 tiles (Verdict / FV / Discount / Worry) read from the SAME
 * resolved signal bag the desktop HonestHero side rail reads from
 * (`useHeroSignals`) so the two surfaces cannot drift. Spec §1 Fold 1
 * mandates this — the previous "Worry / Score / Moat / Flags" strip
 * was missing FV and Discount entirely, which the audit flagged as
 * the worst mobile regression today.
 *
 * SEBI lens: tile labels are descriptive metrics
 * (Verdict / Fair Value / Discount / Worry). No imperative verbs,
 * no targets. When a signal is missing the canonical empty state
 * is the em-dash glyph (—), never a fabricated zero.
 */

import * as React from "react"

import { cn, formatCurrency, formatPct } from "@/lib/utils"
import {
  VERDICT_COLORS,
  verdictTierFromMos,
  verdictTierLabel,
  type VerdictTier,
} from "@/lib/verdict-colors"
import type { HeroSignals } from "@/lib/useHeroSignals"

export interface MobileScoreStripProps {
  ticker: string
  currency: string
  signals: HeroSignals
  /**
   * Optional tap handler for the Worry tile — opens the full
   * WorryIndex panel per spec §6. When omitted the tile is non-
   * interactive (sane default during incremental rollout).
   */
  onWorryTap?: () => void
}

export default function MobileScoreStrip({
  ticker,
  currency,
  signals,
  onWorryTap,
}: MobileScoreStripProps) {
  const tier: VerdictTier = signals.dataLimited
    ? "data_limited"
    : verdictTierFromMos(signals.discount, signals.verdict)
  const palette = VERDICT_COLORS[tier]
  const verdictLabel = signals.verdictGated
    ? "Under Review"
    : verdictTierLabel(tier)

  const fvDisplay =
    signals.fairValue != null
      ? formatCurrency(signals.fairValue, currency, ticker)
      : "—"

  const discountDisplay = (() => {
    if (signals.degraded) return "+200% (clamp)"
    if (signals.discount == null) return "—"
    return formatPct(signals.discount)
  })()

  const worryLabel = worryTierLabel(signals.worry)

  const confTrail =
    signals.confidence != null && !signals.dataLimited
      ? `conf ${Math.round(signals.confidence)}%`
      : null

  return (
    <div
      className="lg:hidden -mx-4 px-4 py-2 bg-bg/95 border-b border-border"
      role="region"
      aria-label="Stock signals summary"
    >
      <div className="grid grid-cols-4 gap-2">
        {/* Verdict tile */}
        <Tile
          label="Verdict"
          value={verdictLabel}
          trail={confTrail}
          accentClass={palette.bar}
        />

        {/* FV tile */}
        <Tile
          label="Fair Value"
          value={fvDisplay}
          trail={
            signals.fairValueClamped && !signals.dataLimited
              ? "clamp"
              : signals.confidence != null && signals.confidence < 30 && !signals.dataLimited
                ? "low conf"
                : null
          }
        />

        {/* Discount tile */}
        <Tile
          label="Discount"
          value={discountDisplay}
          dot={signals.degraded ? "warn" : null}
        />

        {/* Worry tile */}
        <Tile
          label="Worry"
          value={worryLabel}
          onClick={onWorryTap}
        />
      </div>
    </div>
  )
}

function worryTierLabel(
  tier: HeroSignals["worry"] | null | undefined,
): string {
  switch (tier) {
    case "sleep_well":
      return "Sleep well"
    case "normal":
      return "Normal"
    case "watch_closely":
      return "Watch closely"
    case "read_bears":
      return "Read bears"
    case "significant_concerns":
      return "High"
    default:
      return "—"
  }
}

interface TileProps {
  label: string
  value: string
  /** Small trailing chip-style text under the main value (e.g. "conf 43%"). */
  trail?: string | null
  /** Optional warning dot before the value (degraded discount, etc.). */
  dot?: "warn" | null
  /** Tap target — when omitted the tile is non-interactive. */
  onClick?: () => void
  /** Verdict palette accent for the verdict tile. */
  accentClass?: string
}

function Tile({ label, value, trail, dot, onClick, accentClass }: TileProps) {
  const inner = (
    <div className="flex flex-col gap-0.5">
      <span className="text-[9px] uppercase tracking-wide text-caption leading-none">
        {label}
      </span>
      <span className="flex items-center gap-1 font-mono tabular-nums text-[12px] text-ink leading-tight truncate">
        {dot === "warn" && (
          <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
        )}
        {value}
      </span>
      {trail && (
        <span className="text-[10px] text-caption leading-none truncate">
          {trail}
        </span>
      )}
    </div>
  )
  // Tap target ≥ 40px (spec §10.4 a11y gate)
  const baseCls = "rounded-lg border border-border bg-bg dark:bg-surface px-2 py-2 min-h-[40px] overflow-hidden"
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={cn(baseCls, "text-left active:scale-[0.98] transition")}
      >
        {accentClass && (
          <span aria-hidden className={cn("block h-0.5 -mx-2 -mt-2 mb-1", accentClass)} />
        )}
        {inner}
      </button>
    )
  }
  return (
    <div className={baseCls}>
      {accentClass && (
        <span aria-hidden className={cn("block h-0.5 -mx-2 -mt-2 mb-1", accentClass)} />
      )}
      {inner}
    </div>
  )
}
