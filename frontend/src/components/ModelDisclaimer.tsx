/**
 * ModelDisclaimer
 *
 * SEBI-compliance footer/inline note. Renders on every screen that
 * surfaces a fair-value estimate so users see — at the same time as
 * the number — that the output is a model estimate, not investment
 * advice, and that YieldIQ is not a SEBI-registered investment adviser.
 *
 *   <ModelDisclaimer compact />   one-liner for cards / above tables
 *   <ModelDisclaimer />           full block for page footers
 */

import { cn } from "@/lib/utils"

export const MODEL_DISCLAIMER_TEXT =
  "Model estimate. Not investment advice. YieldIQ is not a SEBI-registered investment adviser. For research purposes only."

interface ModelDisclaimerProps {
  /** Compact one-liner variant. Defaults to false (full block). */
  compact?: boolean
  className?: string
}

export default function ModelDisclaimer({ compact = false, className }: ModelDisclaimerProps) {
  if (compact) {
    return (
      <p
        className={cn(
          "text-[11px] leading-snug text-gray-500 italic",
          className,
        )}
        data-testid="model-disclaimer-compact"
      >
        {MODEL_DISCLAIMER_TEXT}
      </p>
    )
  }

  return (
    <aside
      role="note"
      aria-label="Model disclaimer"
      data-testid="model-disclaimer"
      className={cn(
        "mt-8 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-xs leading-relaxed text-gray-600",
        className,
      )}
    >
      <p>
        <span className="font-semibold text-gray-700">Disclaimer.</span>{" "}
        {MODEL_DISCLAIMER_TEXT}
      </p>
    </aside>
  )
}
