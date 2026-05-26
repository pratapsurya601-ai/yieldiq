// frontend/src/components/analysis/HonestCard.tsx
//
// The Honest Card — Phase 3 (2026-05-25), Design Manifesto Rule 10:
// "Transparency is a feature, not a disclaimer." Single full-bleed
// panel that lists 4 sections:
//
//   1. What we are confident about        (audited facts)
//   2. Our best estimate                  (one-line headline)
//   3. Where we could be wrong            (uncertainty factors)
//   4. 3 things that would change verdict (invalidating conditions)
//
// Strings come from backend/services/analysis/honest_card_generator.py
// — pure rules, no LLM, SEBI-safe by construction. This component is
// pure presentation.

import React from "react"
import type { HonestCardOutput } from "@/types/api"
import { FadeStagger } from "@/components/anim"

interface Props {
  card?: HonestCardOutput | null
}

type SectionTone = "confident" | "estimate" | "uncertain" | "invalidating"

interface SectionConfig {
  tone: SectionTone
  heading: string
  icon: React.ReactNode
  iconColor: string
  headingColor: string
}

const ICON_PATHS: Record<SectionTone, React.ReactNode> = {
  confident: (
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M4.5 12.75l6 6 9-13.5"
    />
  ),
  estimate: (
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"
    />
  ),
  uncertain: (
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
    />
  ),
  invalidating: (
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M6 18L18 6M6 6l12 12"
    />
  ),
}

const TONE_COLORS: Record<SectionTone, { icon: string; heading: string }> = {
  confident: {
    icon: "text-emerald-600 dark:text-emerald-400",
    heading: "text-emerald-700 dark:text-emerald-300",
  },
  estimate: {
    icon: "text-sky-600 dark:text-sky-400",
    heading: "text-sky-700 dark:text-sky-300",
  },
  uncertain: {
    icon: "text-amber-600 dark:text-amber-400",
    heading: "text-amber-700 dark:text-amber-300",
  },
  invalidating: {
    icon: "text-rose-600 dark:text-rose-400",
    heading: "text-rose-700 dark:text-rose-300",
  },
}

function SectionHeader({
  tone,
  heading,
}: {
  tone: SectionTone
  heading: string
}) {
  const colors = TONE_COLORS[tone]
  return (
    <h3
      className={`flex items-center gap-2 text-xs font-semibold uppercase tracking-wide ${colors.heading} mb-3`}
    >
      <svg
        className={`w-4 h-4 shrink-0 ${colors.icon}`}
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
        aria-hidden="true"
      >
        {ICON_PATHS[tone]}
      </svg>
      {heading}
    </h3>
  )
}

function BulletList({ items }: { items: string[] }) {
  if (items.length === 0) return null
  // NOTE: FadeStagger's wrapper must have a real CSS box (not
  // `display: contents`) — IntersectionObserver only fires for elements
  // with layout, and `display: contents` collapses the box, so the
  // stagger animation would never trigger and children stayed at
  // opacity 0 forever (P0 regression on /analysis pages, 2026-05-26).
  return (
    <FadeStagger as="div" staggerMs={80} className="space-y-2">
      {items.map((line, i) => (
        <p
          key={i}
          className="text-base text-ink leading-relaxed max-w-prose"
        >
          <span className="text-caption mr-2" aria-hidden="true">
            •
          </span>
          {line}
        </p>
      ))}
    </FadeStagger>
  )
}

function NumberedList({ items }: { items: string[] }) {
  if (items.length === 0) return null
  // See BulletList NOTE — same `display: contents` regression applied
  // here (PR #651 shipped both with the same wrapper class).
  return (
    <FadeStagger as="div" staggerMs={80} className="space-y-2">
      {items.map((line, i) => (
        <p
          key={i}
          className="text-base text-ink leading-relaxed max-w-prose"
        >
          <span className="text-caption font-semibold mr-2 tabular-nums">
            {i + 1}.
          </span>
          {line}
        </p>
      ))}
    </FadeStagger>
  )
}

export default function HonestCard({ card }: Props) {
  if (!card) return null

  const hasAny =
    (card.confident_facts?.length ?? 0) > 0 ||
    !!card.best_estimate ||
    (card.uncertainty_factors?.length ?? 0) > 0 ||
    (card.invalidating_conditions?.length ?? 0) > 0
  if (!hasAny) return null

  return (
    <section
      data-testid="honest-card"
      className="rounded-2xl border border-border bg-slate-50 dark:bg-slate-900 p-5 md:p-6"
      aria-label="The Honest Card — transparency panel"
    >
      <header className="flex items-start justify-between gap-3 mb-5 pb-4 border-b border-border">
        <h2 className="text-base md:text-lg font-semibold text-ink tracking-tight">
          The Honest Card
        </h2>
        <p
          className="text-[11px] text-caption italic max-w-[60%] text-right leading-snug"
          title="We surface what we're sure about, our best estimate, where we could be wrong, and what would change our mind."
        >
          Why we do this: nobody else in retail finance shows their work
          this openly.
        </p>
      </header>

      <div className="space-y-6">
        {/* Section 1 — Confident facts */}
        {card.confident_facts.length > 0 && (
          <div>
            <SectionHeader
              tone="confident"
              heading="Here's what we're confident about"
            />
            <div className="space-y-2">
              <BulletList items={card.confident_facts} />
            </div>
          </div>
        )}

        {card.confident_facts.length > 0 && card.best_estimate && (
          <div className="h-px bg-border" aria-hidden="true" />
        )}

        {/* Section 2 — Best estimate */}
        {card.best_estimate && (
          <div>
            <SectionHeader
              tone="estimate"
              heading="Here's our best estimate"
            />
            <p className="text-base text-ink leading-relaxed max-w-prose font-medium">
              {card.best_estimate}
            </p>
          </div>
        )}

        {card.best_estimate && card.uncertainty_factors.length > 0 && (
          <div className="h-px bg-border" aria-hidden="true" />
        )}

        {/* Section 3 — Uncertainty factors */}
        {card.uncertainty_factors.length > 0 && (
          <div>
            <SectionHeader
              tone="uncertain"
              heading="Here's where we could be wrong"
            />
            <div className="space-y-2">
              <BulletList items={card.uncertainty_factors} />
            </div>
          </div>
        )}

        {card.uncertainty_factors.length > 0 &&
          card.invalidating_conditions.length > 0 && (
            <div className="h-px bg-border" aria-hidden="true" />
          )}

        {/* Section 4 — Invalidating conditions */}
        {card.invalidating_conditions.length > 0 && (
          <div>
            <SectionHeader
              tone="invalidating"
              heading={`${card.invalidating_conditions.length} things that would change our verdict`}
            />
            <div className="space-y-2">
              <NumberedList items={card.invalidating_conditions} />
            </div>
          </div>
        )}
      </div>

      <footer className="mt-5 pt-4 border-t border-border">
        <p className="text-[11px] text-caption italic leading-snug">
          Auto-generated. Computed at response time from publicly filed
          financials. Not investment advice.
        </p>
      </footer>
    </section>
  )
}
