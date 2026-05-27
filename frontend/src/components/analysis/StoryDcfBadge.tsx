/**
 * Story-DCF badge.
 *
 * Fires when the DCF-collapse safety net's third rung rescued the
 * fair value using ``backend/services/story_dcf_engine.py`` — a
 * Damodaran narrative + numbers model whose parameters are operator-
 * curated in ``config/story_dcf_overrides.json``.
 *
 * The frontend must make it visible that this is a STORY, not a
 * fact. Confidence is hard-capped at 50 (vs 65 for Platform P/S,
 * 75 for Tier 2, 70-90 for DCF). The tooltip explains why.
 *
 * The two engine strings we accept here mirror the backend:
 *   - "story_dcf"                       — direct invocation (rare;
 *                                         currently always via the
 *                                         safety net)
 *   - "story_dcf_after_dcf_collapse"    — set by
 *                                         dcf_collapse_safety_net.py
 *                                         when the 3rd rung fires.
 *
 * If the backend later adds more story-DCF variants, extend
 * ``isStoryDcfEngine`` rather than splattering string equality
 * checks across the codebase.
 */

const STORY_DCF_ENGINES: ReadonlyArray<string> = [
  "story_dcf",
  "story_dcf_after_dcf_collapse",
]

export function isStoryDcfEngine(engine?: string | null): boolean {
  return engine != null && STORY_DCF_ENGINES.includes(engine)
}

export interface StoryDcfBadgeProps {
  valuationEngineUsed?: string | null
  /** Optional confidence score from the valuation payload. Surfaces
   * in the tooltip so the user sees the exact cap that fired. */
  confidenceScore?: number | null
}

export default function StoryDcfBadge({
  valuationEngineUsed,
  confidenceScore,
}: StoryDcfBadgeProps) {
  if (!isStoryDcfEngine(valuationEngineUsed)) return null

  const confLine =
    typeof confidenceScore === "number"
      ? ` Current confidence: ${confidenceScore}/100.`
      : ""

  const title =
    "Narrative valuation — operator-curated revenue growth, margin " +
    "convergence, and reinvestment trajectory drive this fair value. " +
    "Confidence is capped at 50 because story-DCFs are inherently less " +
    "anchored than peer-relative or asset-backed methods. Inputs live " +
    "in config/story_dcf_overrides.json." +
    confLine

  return (
    <span
      data-testid="story-dcf-badge"
      data-engine={valuationEngineUsed ?? ""}
      className="inline-flex items-center rounded-full border border-amber-500/40 bg-tone-warn-bg px-2 py-0.5 text-[11px] font-medium text-tone-warn-fg dark:bg-amber-950/30 dark:text-amber-300"
      title={title}
    >
      Story-DCF — narrative valuation (confidence cap 50)
    </span>
  )
}
