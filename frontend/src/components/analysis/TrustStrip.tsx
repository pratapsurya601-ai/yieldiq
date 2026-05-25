"use client"

// TrustStrip — Alpha-Spread-style horizontal stat row used above the
// numbered sections on the Summary tab (#ASD-restyle, 2026-05-25).
//
// Real-data-only: callers MUST pass already-resolved label/value pairs.
// If a field is null upstream, callers can pass "—" as the value
// (component renders it muted) or omit the card entirely. This is by
// policy — we do not pad with mock stars or fake accuracy metrics.
//
// Layout: 2–4 cards horizontally on >=sm, 2x2 grid on <sm. Each card is
// a small "LABEL" (uppercase, muted) + value (color-coded by accent).
//
// SEBI-safe: callers are responsible for the copy in `label` and `value`.
// The component itself emits no editorial language.

import * as React from "react"

export type TrustAccent = "green" | "red" | "neutral"

export interface TrustStat {
  label: string
  value: string
  accent?: TrustAccent
}

interface Props {
  stats: TrustStat[]
  /** Optional aria-label for the strip — defaults to "Key stats". */
  ariaLabel?: string
}

function accentClass(accent: TrustAccent | undefined): string {
  if (accent === "green") return "text-success"
  if (accent === "red") return "text-danger"
  return "text-ink"
}

export default function TrustStrip({ stats, ariaLabel = "Key stats" }: Props) {
  // Empty by policy → render nothing rather than an empty container.
  if (!stats || stats.length === 0) return null

  // Cap at 4 cards; defensive — callers pass 2–4 by convention.
  const cards = stats.slice(0, 4)

  // Tailwind safelist: grid-cols-2 sm:grid-cols-2 sm:grid-cols-3 sm:grid-cols-4
  const smColsClass =
    cards.length >= 4
      ? "sm:grid-cols-4"
      : cards.length === 3
        ? "sm:grid-cols-3"
        : "sm:grid-cols-2"

  return (
    <div
      data-testid="trust-strip"
      aria-label={ariaLabel}
      className={`grid grid-cols-2 ${smColsClass} gap-3 mb-4`}
    >
      {cards.map((stat, idx) => (
        <div
          key={`${stat.label}-${idx}`}
          data-testid="trust-strip-card"
          className="rounded-xl border border-border bg-surface px-4 py-3"
        >
          <p className="text-[10px] font-semibold uppercase tracking-wider text-caption mb-1">
            {stat.label}
          </p>
          <p
            data-accent={stat.accent ?? "neutral"}
            className={`text-base md:text-lg font-bold font-mono tabular-nums ${accentClass(stat.accent)}`}
          >
            {stat.value}
          </p>
        </div>
      ))}
    </div>
  )
}
