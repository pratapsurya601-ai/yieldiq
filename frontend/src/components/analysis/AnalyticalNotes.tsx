"use client"

/**
 * AnalyticalNotes — contextual disclaimers attached to every analysis.
 *
 * Source: backend/services/analytical_notes.py (PR #69). The backend emits
 * 0-5 AnalyticalNoteOutput entries on AnalysisResponse.analytical_notes
 * flagging structural DCF limitations for specific stock archetypes
 * (premium brand, conglomerate, regulated utility, cyclical trough,
 * post-merger, high-P/E growth, ADR / USD reporting).
 *
 * Rendering rules:
 *   - If the array is empty or undefined, render nothing (no heading,
 *     no empty state).
 *   - Each note is a card with a severity-coloured left border:
 *       info    -> brand blue
 *       caution -> amber/warning
 *   - Title in semibold; body in normal weight for readable prose.
 */

import { cn } from "@/lib/utils"
import type {
  AnalyticalNoteOutput,
  AnalyticalNoteSeverity,
} from "@/types/api"

interface AnalyticalNotesProps {
  notes: AnalyticalNoteOutput[] | undefined | null
  className?: string
}

// Tailwind class bundles keyed by severity. Kept as a static map so
// Tailwind's JIT can see the full class strings at build time — never
// interpolate class names from runtime data.
const SEVERITY_STYLES: Record<
  AnalyticalNoteSeverity,
  { border: string; dot: string; label: string }
> = {
  info: {
    border: "border-l-brand",
    dot: "bg-brand",
    label: "text-brand",
  },
  caution: {
    border: "border-l-warning",
    dot: "bg-warning",
    label: "text-warning",
  },
}

const SEVERITY_LABEL: Record<AnalyticalNoteSeverity, string> = {
  info: "Context",
  caution: "Caution",
}

export default function AnalyticalNotes({
  notes,
  className,
}: AnalyticalNotesProps) {
  if (!notes || notes.length === 0) return null

  return (
    <section
      className={cn("space-y-3", className)}
      aria-label="Analytical notes"
    >
      <h2 className="text-sm font-semibold text-ink">Analytical notes</h2>
      <ul className="space-y-2.5">
        {notes.map((note, idx) => {
          const styles =
            SEVERITY_STYLES[note.severity] ?? SEVERITY_STYLES.info
          return (
            <li
              key={`${note.kind}-${idx}`}
              className={cn(
                "bg-bg rounded-2xl border border-border border-l-4 px-4 py-3.5 sm:px-5 sm:py-4",
                styles.border,
              )}
            >
              <div className="flex items-center gap-2 mb-1">
                <span
                  aria-hidden
                  className={cn(
                    "inline-block h-1.5 w-1.5 rounded-full",
                    styles.dot,
                  )}
                />
                <span
                  className={cn(
                    "text-[0.68rem] font-semibold uppercase tracking-[0.08em]",
                    styles.label,
                  )}
                >
                  {SEVERITY_LABEL[note.severity] ?? "Context"}
                </span>
              </div>
              <p className="text-sm font-semibold text-ink leading-snug">
                {note.title}
              </p>
              <p className="mt-1 text-sm font-normal text-body leading-relaxed">
                {note.body}
              </p>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
