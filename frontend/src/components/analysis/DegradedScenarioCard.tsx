"use client"

/**
 * DegradedScenarioCard — spec §2.1 / §2.2.
 *
 * Renders in place of the three-tile FVProjectionFan scenario row when
 * the WIPRO-class trigger fires: backend clamp marker present AND
 * bear/base/bull discounts collapse to identical values at/above the
 * ±200% display ceiling. Predicate lives in lib/scenarios.ts
 * (`isDegradedScenario`); this component is purely presentational —
 * it consumes the resolved state, never re-decides whether to render.
 *
 * Copy is verbatim from spec §2.2 (vocabulary-checked against the
 * SEBI ban list at spec time). The optional second paragraph fires
 * only when the value-trap structured flag is present OR
 * red_flags_structured.length >= 3 with moat = None — caller passes
 * `showValueTrapPara` to drive that.
 *
 * Visual treatment per spec §2.3:
 *   • Single card, full HonestHero width.
 *   • Left edge accent bar = caution amber (mirrors AnalyticalNotes).
 *   • Caption chip in card header: "CLAMP CEILING".
 *
 * SEBI lens: see CLAUDE.md and memory/feedback_yieldiq_discipline.md
 * for the banned vocabulary list. `Possible` is permitted (factual
 * hedge, not directive). `Acting` is operator-permitted in this
 * context (spec section 2.2 verbatim).
 */

import * as React from "react"
import { NarrativeCard } from "@/components/cards"
import { formatCurrency } from "@/lib/utils"

export interface DegradedScenarioCardProps {
  /** Ticker (for currency formatter ADR routing). */
  ticker: string
  /** Payload currency code (INR / USD). */
  currency: string
  /**
   * Raw, UNCLAMPED model fair value from the backend (the figure that
   * triggered the clamp). When null / non-finite the body omits the
   * "Rs.{raw}" reference and degrades to a copy-only caveat. We never
   * fabricate the figure — the spec phrases the body around the raw
   * number being available.
   */
  rawFairValue?: number | null
  /** Render the second optional paragraph (value-trap framing). */
  showValueTrapPara?: boolean
  /**
   * Red-flag count + moat label feed the second paragraph's slots.
   * Null/undefined → the slot copy falls back to a neutral phrase.
   */
  redFlagCount?: number | null
  moat?: string | null
}

export default function DegradedScenarioCard({
  ticker,
  currency,
  rawFairValue,
  showValueTrapPara = false,
  redFlagCount,
  moat,
}: DegradedScenarioCardProps) {
  const rawDisplay =
    rawFairValue != null && Number.isFinite(rawFairValue) && rawFairValue > 0
      ? formatCurrency(rawFairValue, currency, ticker)
      : null

  const flagsText =
    redFlagCount != null && Number.isFinite(redFlagCount) && redFlagCount > 0
      ? `${redFlagCount} red flag${redFlagCount === 1 ? "" : "s"}`
      : "several red flags"

  const moatText = moat && moat.trim().length > 0 ? moat : "no durable"

  return (
    <NarrativeCard
      // Left-edge accent bar — reuses the AnalyticalNotes caution amber
      // grammar (border-l-4 amber-400). The card-shell border stays for
      // the rest of the perimeter so it reads as one surface.
      className="border-l-4 border-l-amber-400 dark:border-l-amber-500"
      role="status"
      aria-label="Scenario spread exceeds display bounds"
      eyebrow={
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500"
          />
          CLAMP CEILING
        </span>
      }
    >
      <h3 className="text-ink text-base font-semibold mb-2 leading-snug">
        Scenario spread exceeds display bounds
      </h3>

      {/* Spec §2.2 verbatim body. The {raw} slot omits gracefully when
          we do not have the unclamped figure — "The raw model fair
          value sits more than 3x current price" remains true and
          non-misleading without the number. */}
      <p className="leading-[26px]">
        Bear, base and bull scenarios all collapse to the +200% clamp ceiling.
        The raw model fair value{rawDisplay ? ` (${rawDisplay})` : ""} sits
        more than 3x current price, which we cap at +200% for display. The
        three-way spread is unavailable for this payload. See valuation notes
        for clamp context.
      </p>

      {showValueTrapPara && (
        <p className="leading-[26px] mt-3">
          Possible value trap: the discount pairs with {flagsText}, a
          shrinking revenue trend, and {moatText} moat. The depth of the
          discount is itself a signal — read the Honest Card before acting
          on the headline figure.
        </p>
      )}
    </NarrativeCard>
  )
}
