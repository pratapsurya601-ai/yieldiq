/**
 * ScoreVerdictReconcilerCaption — ROOT CAUSE #6 (2026-06-10).
 *
 * Problem
 * -------
 * The analysis page surfaces two trust signals that answer different
 * questions:
 *
 *   - YIQ Score / Grade (side-rail) is a business-quality blend.
 *     Question: "Is this a quality business to own?"
 *
 *   - Verdict pill (hero) is a price-vs-intrinsic-value reading.
 *     Question: "Is the price below intrinsic value today?"
 *
 * For HDFCBANK 2026-06 these point opposite directions: YIQ 40
 * (Grade C, post-merger ROE 8.8% vs 16% historical) AND verdict
 * "Undervalued" at 90% confidence (composite IV ~Rs.1,147 vs price
 * Rs.746). Both readings are correct; the page presented them
 * without explaining they measure different things, reading as a
 * contradiction.
 *
 * This component
 * --------------
 * Renders a one-paragraph descriptive caption when (and only when)
 * the backend marks the two signals as divergent. The trigger is a
 * server-side decision stamped in
 * ``AnalysisResponse.score_verdict_divergence.diverges`` — the rule
 * lives in backend/services/score_verdict_divergence.py. This file
 * never derives "diverges" on its own; it only renders.
 *
 * Self-hides when:
 *   - the field is absent on legacy cached payloads, or
 *   - ``diverges`` is false (signals align), or
 *   - the explanation string is missing.
 *
 * Inserted in AnalysisBody.tsx between <HonestHero> and the
 * <CrossConfirmationChip> so the caption sits visually adjacent to
 * BOTH the side-rail YIQ Score (on the right) AND the verdict pill
 * (above-left) the user just saw.
 *
 * SEBI lens
 * ---------
 * Every label and copy string is descriptive. No imperative verbs
 * ("buy" / "sell" / "hold" / "should" / "recommend"), no
 * value-judgement adjectives ("attractive" / "expensive" / "cheap").
 * Backend stamps the explanation; frontend does not splice user
 * verdict words into the wrapper copy. See ``scripts/check_sebi_words.py``
 * for the full banlist.
 */

import * as React from "react"

/* ------------------------------------------------------------------ */
/*  Public shape                                                       */
/* ------------------------------------------------------------------ */

/**
 * Mirror of the ``score_verdict_divergence`` dict the backend stamps
 * on ``AnalysisResponse``. All fields optional so legacy payloads
 * remain valid.
 */
export interface ScoreVerdictDivergence {
  score_percentile?: number | null
  verdict_signal?: string | null
  diverges?: boolean | null
  explanation?: string | null
}

export interface ScoreVerdictReconcilerCaptionProps {
  /** Stamped by backend; null/undefined on legacy cached payloads. */
  divergence: ScoreVerdictDivergence | null | undefined
  /** Optional className passthrough for layout. */
  className?: string
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ScoreVerdictReconcilerCaption({
  divergence,
  className,
}: ScoreVerdictReconcilerCaptionProps) {
  // Self-hide branch: absent field, aligned signals, or missing copy.
  if (!divergence) return null
  if (divergence.diverges !== true) return null
  const explanation = (divergence.explanation ?? "").trim()
  if (!explanation) return null

  return (
    <aside
      role="note"
      aria-label="Score and verdict signals point in different directions"
      data-testid="score-verdict-reconciler-caption"
      data-diverges="true"
      className={`mt-3 rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-3 text-[12px] leading-snug text-slate-700 dark:border-slate-700/70 dark:bg-slate-900/40 dark:text-slate-300 ${className ?? ""}`}
    >
      <header className="flex items-baseline justify-between gap-3 mb-1">
        <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
          Two readings, two questions
        </span>
        {typeof divergence.score_percentile === "number" && (
          <span
            className="font-mono tabular-nums text-[11px] text-slate-500 dark:text-slate-400"
            data-testid="score-verdict-reconciler-caption-score"
          >
            Score {divergence.score_percentile} / 100
          </span>
        )}
      </header>

      <p data-testid="score-verdict-reconciler-caption-explanation">
        {explanation}
      </p>
    </aside>
  )
}
