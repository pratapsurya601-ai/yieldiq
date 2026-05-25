// frontend/src/components/analysis/BullsBearsPanel.tsx
//
// P0 #4 (2026-05-25) — Morningstar-style "Bulls Say / Bears Say"
// thesis panel. Two columns side-by-side on desktop (stacked on
// mobile); 3 bullets per side. Strings are generated server-side
// by backend/services/analysis/bulls_bears_generator.py and have
// already been SEBI-filtered. This component is pure presentation.
//
// Backwards compatibility: legacy cached payloads predate the
// backend field, so `bulls` / `bears` may be null/undefined/empty.
// We render the "Insufficient data" empty state per column rather
// than hiding the whole panel, so users still see the framing
// (and so the layout doesn't jump once the cache catches up).

import React from "react"

interface Props {
  bulls?: string[] | null
  bears?: string[] | null
}

function Column({
  tone,
  heading,
  bullets,
}: {
  tone: "bull" | "bear"
  heading: string
  bullets: string[]
}) {
  const isBull = tone === "bull"
  const dotColor = isBull
    ? "bg-success"
    : "bg-danger"
  const headingColor = isBull ? "text-success" : "text-danger"

  return (
    <div className="flex-1 min-w-0">
      <h3
        className={`text-sm font-semibold ${headingColor} mb-3 flex items-center gap-2`}
      >
        <span
          className={`inline-block w-2 h-2 rounded-full ${dotColor}`}
          aria-hidden="true"
        />
        {heading}
      </h3>
      {bullets.length === 0 ? (
        <p className="text-xs text-caption italic">
          Insufficient data for {isBull ? "bull" : "bear"} analysis
        </p>
      ) : (
        <ul className="space-y-2.5">
          {bullets.map((b, i) => (
            <li
              key={i}
              className="flex gap-2 text-sm text-ink leading-snug"
            >
              <span
                className={`mt-1.5 inline-block w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`}
                aria-hidden="true"
              />
              <span className="min-w-0">{b}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function BullsBearsPanel({ bulls, bears }: Props) {
  const safeBulls = Array.isArray(bulls) ? bulls : []
  const safeBears = Array.isArray(bears) ? bears : []

  // Render nothing only when BOTH sides are missing — keeps the
  // panel out of the way for pre-PR cached payloads where neither
  // field is populated yet. Once the cache catches up (≤ 24h via the
  // bulls_bears manifest entry), one or both sides will render.
  if (safeBulls.length === 0 && safeBears.length === 0) return null

  return (
    <section
      className="bg-bg rounded-2xl border border-border p-5"
      aria-label="Bulls and Bears thesis"
    >
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="text-sm font-semibold text-ink">
          Bulls vs Bears
        </h2>
        <p className="text-[11px] text-caption">
          Auto-generated from financials. Not investment advice.
        </p>
      </div>
      <div className="flex flex-col md:flex-row gap-6 md:gap-8">
        <Column tone="bull" heading="Bulls Say" bullets={safeBulls} />
        <div
          className="hidden md:block w-px bg-border self-stretch"
          aria-hidden="true"
        />
        <Column tone="bear" heading="Bears Say" bullets={safeBears} />
      </div>
    </section>
  )
}
