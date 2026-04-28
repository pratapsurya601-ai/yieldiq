"use client"

/**
 * FvConfidenceBand — visual ±range under the headline Fair Value.
 *
 * Renders e.g. "± ₹520 (67% confidence)" beneath the FV figure on the
 * /analysis/[ticker] hero (and the visitor PublicAnalysis hero).
 *
 * Math: delta = fairValue * (1 - confidence/100) * 0.5
 *   confidence 67  → ±16.5% of FV
 *   confidence 90  → ±5%   of FV
 *   confidence 100 → ±0    (no band; we still render for completeness)
 *
 * Edge cases (caller is responsible for two of them; we handle the third):
 *   - confidence null/missing → caller passes nothing, we return null
 *   - data_limited === true   → caller suppresses (passes undefined)
 *   - confidence < 30         → low-confidence amber tint here
 *
 * Backend source: ValuationOutput.confidence_score (0–100). Plumbed as
 * `confidence` everywhere on the frontend hero surface so the two hero
 * call sites (EditorialHero, PublicAnalysis) stay symmetric.
 */

import { formatCurrency } from "@/lib/utils"

export interface FvConfidenceBandProps {
  /** Fair value in company currency. Must be > 0 to render. */
  fairValue: number
  /** Confidence score 0–100. Null/undefined → component renders nothing. */
  confidence: number | null | undefined
  /** ISO currency code (defaults to INR via formatCurrency). */
  currency?: string
}

export default function FvConfidenceBand({
  fairValue,
  confidence,
  currency,
}: FvConfidenceBandProps) {
  if (
    confidence === null ||
    confidence === undefined ||
    !Number.isFinite(confidence) ||
    !Number.isFinite(fairValue) ||
    fairValue <= 0
  ) {
    return null
  }

  // Clamp to [0, 100] so a stray out-of-range backend value can't produce
  // a negative band or one wider than the FV itself.
  const conf = Math.max(0, Math.min(100, confidence))
  const delta = fairValue * (1 - conf / 100) * 0.5
  const lowConfidence = conf < 30

  return (
    <p
      className={`mt-1 text-[11px] font-mono tabular-nums leading-snug ${
        lowConfidence ? "text-amber-600" : "text-caption"
      }`}
      aria-label={`Fair value range plus or minus ${formatCurrency(
        delta,
        currency,
      )} at ${Math.round(conf)} percent confidence`}
    >
      &plusmn; {formatCurrency(delta, currency)} ({Math.round(conf)}% confidence)
    </p>
  )
}
