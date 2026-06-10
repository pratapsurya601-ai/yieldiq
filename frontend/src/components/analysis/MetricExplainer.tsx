"use client"

/**
 * MetricExplainer — Educational Content Layer modal.
 *
 * Surfaces a richer, multi-section finance mini-lesson when the user
 * clicks the "?" icon next to a metric. Sits on top of (not in place
 * of) the existing inline MetricTooltip — that primitive is the quick
 * hover popover; THIS one is the deeper "Learn finance" expander.
 *
 * Trigger:
 *   - A circular "?" icon button rendered inline with the metric label.
 *     Keyboard: Enter/Space toggles. Esc closes the modal.
 *
 * Modal contents (sourced from `lib/educational-content.ts`):
 *   - Title + subtitle + difficulty badge
 *   - "What is this?" definition paragraph
 *   - "Why does it matter?" paragraph
 *   - "Typical ranges" — table of band labels + descriptions
 *   - "Worked example" paragraph
 *   - Optional caveat row
 *   - "Continue reading" link to /learn/<slug>
 *
 * Accessibility:
 *   - Trigger is a real <button> with aria-label, focus ring.
 *   - Modal is role="dialog" aria-modal="true" with aria-labelledby
 *     pointing at the heading.
 *   - Focus moves into the modal on open and back to the trigger on
 *     close. Esc closes; click on backdrop closes.
 *   - Page scroll is locked while the modal is open.
 *
 * Dark mode: uses the same surface / ink / border tokens as the rest
 * of the analysis page. No hard-coded colors.
 *
 * No new dependencies — React 19 hooks only.
 */

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react"
import Link from "next/link"
import { cn } from "@/lib/utils"
import { resolveTopic, type EducationalTopic } from "@/lib/educational-content"

export interface MetricExplainerProps {
  /** Topic key — slug, alias, or metric-explainers key. */
  topic: string
  /**
   * Optional override for the visible label inside the "?" trigger's
   * aria-label, e.g. "Learn about ROE" vs the default "Learn more".
   */
  ariaLabel?: string
  /** Optional extra classes for the trigger button. */
  className?: string
  /**
   * When true, render only the trigger; when the modal opens we still
   * mount it via portal-less absolute positioning. (No portal because
   * Next.js 16's RSC streaming + late-portal hydration is twitchy with
   * focus management — we accept the slight z-index discipline
   * trade-off in exchange.)
   */
  inline?: boolean
}

export default function MetricExplainer({
  topic,
  ariaLabel,
  className,
  inline = true,
}: MetricExplainerProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const titleId = useId()
  const resolvedTopic = resolveTopic(topic)

  const closeModal = useCallback(() => {
    setOpen(false)
    // Return focus to the trigger button so keyboard navigation
    // continues from where the user invoked the modal.
    queueMicrotask(() => triggerRef.current?.focus())
  }, [])

  // Esc to close, focus trap inside the dialog while open.
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation()
        closeModal()
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, closeModal])

  // Lock background scroll while modal is open. Restore on close /
  // unmount. Track the previous overflow so we don't clobber a value
  // someone else set.
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  // Move initial focus into the dialog when it opens.
  useEffect(() => {
    if (!open) return
    const node = dialogRef.current
    if (!node) return
    const focusable = node.querySelector<HTMLElement>(
      'button, a, [tabindex="0"]',
    )
    focusable?.focus()
  }, [open])

  // If the topic key is unknown the explainer silently no-ops. This
  // keeps call sites safe to wire on any metric without first checking
  // whether long-form copy exists.
  if (!resolvedTopic) return null

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-label={ariaLabel ?? `Learn about ${resolvedTopic.title}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation()
          setOpen(true)
        }}
        className={cn(
          "inline-flex items-center justify-center",
          "h-4 w-4 rounded-full",
          "text-[10px] font-semibold leading-none",
          "border border-border bg-bg/60 text-caption",
          "hover:bg-surface hover:text-ink hover:border-muted-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1",
          "transition-colors",
          inline && "ml-1 align-middle",
          className,
        )}
        data-testid={`metric-explainer-trigger-${resolvedTopic.slug}`}
      >
        ?
      </button>
      {open && (
        <ExplainerModal
          ref={dialogRef}
          titleId={titleId}
          topic={resolvedTopic}
          onClose={closeModal}
        />
      )}
    </>
  )
}

interface ExplainerModalProps {
  titleId: string
  topic: EducationalTopic
  onClose: () => void
}

// React 19 supports ref-as-prop on plain function components, so we
// accept it as a regular prop rather than reaching for forwardRef.
function ExplainerModal({
  ref,
  titleId,
  topic,
  onClose,
}: ExplainerModalProps & { ref: React.Ref<HTMLDivElement> }) {
  const onBackdropMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose()
  }
  const onDialogKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    // Light focus trap — Tab/Shift-Tab cycle within focusable
    // elements. Production-grade focus-trap libraries do more, but
    // for a content modal this is sufficient.
    if (e.key !== "Tab") return
    const node = e.currentTarget
    const focusable = Array.from(
      node.querySelectorAll<HTMLElement>(
        'button, a[href], [tabindex]:not([tabindex="-1"])',
      ),
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  return (
    <div
      className="fixed inset-0 z-[120] flex items-end sm:items-center justify-center bg-black/55 backdrop-blur-sm p-0 sm:p-6"
      onMouseDown={onBackdropMouseDown}
      data-testid="metric-explainer-backdrop"
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onDialogKey}
        className={cn(
          "relative w-full sm:max-w-2xl",
          "max-h-[88vh] overflow-y-auto",
          "bg-surface text-ink",
          "border border-border",
          "rounded-t-2xl sm:rounded-2xl",
          "shadow-2xl",
          "p-5 sm:p-7",
        )}
        data-testid="metric-explainer-modal"
      >
        <header className="mb-5 pr-10">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-caption">
              {topic.category}
            </span>
            <DifficultyBadge tier={topic.difficulty} />
          </div>
          <h2
            id={titleId}
            className="font-editorial text-xl sm:text-2xl font-semibold text-ink leading-tight"
          >
            {topic.title}
          </h2>
          <p className="text-sm text-body mt-1.5 leading-snug">
            {topic.subtitle}
          </p>
        </header>

        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className={cn(
            "absolute top-4 right-4 sm:top-5 sm:right-5",
            "h-8 w-8 inline-flex items-center justify-center",
            "rounded-full border border-border bg-bg/70 text-caption",
            "hover:bg-surface hover:text-ink",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand",
            "transition-colors text-base leading-none",
          )}
          data-testid="metric-explainer-close"
        >
          ×
        </button>

        <Section heading="What is this?">
          <p className="text-sm text-body leading-relaxed">{topic.definition}</p>
        </Section>

        <Section heading="Why does it matter?">
          <p className="text-sm text-body leading-relaxed">
            {topic.whyItMatters}
          </p>
        </Section>

        {topic.formula && (
          <Section heading="Formula">
            <p className="text-[13px] font-mono text-ink bg-bg/60 border border-border/60 rounded px-2.5 py-2 inline-block break-words">
              {topic.formula}
            </p>
          </Section>
        )}

        <Section heading="Typical ranges">
          <ul className="divide-y divide-border border border-border rounded-lg overflow-hidden">
            {topic.ranges.map((range) => (
              <li
                key={range.label}
                className="px-3.5 py-2.5 text-sm text-body flex flex-col sm:flex-row sm:items-baseline sm:gap-3"
              >
                <span className="font-semibold text-ink whitespace-nowrap sm:basis-44">
                  {range.label}
                </span>
                <span className="leading-snug">{range.description}</span>
              </li>
            ))}
          </ul>
        </Section>

        <Section heading="Worked example">
          <p className="text-sm text-body leading-relaxed">{topic.example}</p>
        </Section>

        {topic.caveat && (
          <Section heading="Note">
            <p className="text-sm text-caption leading-relaxed">
              {topic.caveat}
            </p>
          </Section>
        )}

        <footer className="mt-6 pt-4 border-t border-border flex flex-wrap items-center justify-between gap-3">
          <Link
            href={`/learn/${topic.slug}`}
            className="text-sm font-semibold text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm"
            data-testid="metric-explainer-continue-link"
          >
            Continue reading →
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-caption hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm px-2 py-1"
          >
            Close
          </button>
        </footer>
      </div>
    </div>
  )
}

function Section({
  heading,
  children,
}: {
  heading: string
  children: React.ReactNode
}) {
  return (
    <section className="mb-5 last:mb-0">
      <h3 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-caption mb-2">
        {heading}
      </h3>
      {children}
    </section>
  )
}

function DifficultyBadge({ tier }: { tier: EducationalTopic["difficulty"] }) {
  const copy =
    tier === "beginner"
      ? "Beginner"
      : tier === "intermediate"
        ? "Intermediate"
        : "Advanced"
  return (
    <span
      className={cn(
        "inline-flex items-center px-1.5 py-0.5 rounded-sm",
        "text-[10px] font-semibold uppercase tracking-wide",
        "border border-border bg-bg/60 text-caption",
      )}
    >
      {copy}
    </span>
  )
}
