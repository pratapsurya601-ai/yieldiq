/**
 * NumberContext — tiny muted caption that anchors a metric to a
 * reference the reader already understands:
 *
 *     "vs sector median 10.9%" · "5y avg 17.2%" · "vs price ₹746"
 *
 * Part of the page-wide number-comprehension standard (2026-06-11):
 * a number without context is a quiz; a number with context is a
 * sentence. The component only RENDERS context the caller already has
 * in the payload (peer medians, historical averages) — it never
 * derives or invents reference data itself.
 *
 * RSC-safe: no hooks, no "use client". Self-hides when the value is
 * missing so call sites can pass formatter output straight through
 * (formatters in lib/formatNumbers return "—" for unusable input,
 * which this component treats as absent).
 *
 * SEBI lens: the copy is purely descriptive ("vs", "avg", "median").
 * Callers must not pass directional or advisory label text.
 */

import { cn } from "@/lib/utils"

export interface NumberContextProps {
  /** Reference phrase, e.g. "vs sector median", "5y avg", "vs price". */
  label: string
  /**
   * Pre-formatted reference value ("10.9%", "₹746"). Null, empty, or
   * the em-dash fallback ("—") hides the caption entirely.
   */
  value: string | null | undefined
  className?: string
}

export default function NumberContext({
  label,
  value,
  className,
}: NumberContextProps) {
  if (value == null || value === "" || value === "—") return null
  return (
    <span
      data-testid="number-context"
      className={cn(
        "text-[11px] text-caption tabular-nums whitespace-nowrap",
        className,
      )}
    >
      {label} {value}
    </span>
  )
}
