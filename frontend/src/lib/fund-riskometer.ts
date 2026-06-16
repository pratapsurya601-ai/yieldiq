/**
 * fund-riskometer — token-based Riskometer tone map for the /funds hub.
 *
 * Replaces the duplicated raw-Tailwind-palette `RISKOMETER_COLORS`
 * (emerald-100 / red-800 / …) that the FundCard and detail page each
 * carry. The six SEBI Riskometer bands map onto the app's semantic tone
 * families (good → warn → bad), so the chips automatically follow dark
 * mode and the rest of the design system instead of hard-coding light-
 * only palette classes.
 *
 * Tone colours here are DECORATIVE — the band is a factual,
 * AMC-published label. Every consumer renders the `label` text too, so
 * colour is never the sole signal (a11y: §7).
 *
 * The detail page keeps its own copy for now (out of scope for the
 * funds-landing redesign); flag for a later dedupe pass.
 */
import type { FundRiskometerLevel } from "@/types/api"

export interface RiskometerTone {
  /** Tailwind classes: token-backed bg + fg for the chip. */
  cls: string
  /** Human label rendered inside the chip (never colour-only). */
  label: string
}

export const RISKOMETER_TONE: Record<FundRiskometerLevel, RiskometerTone> = {
  Low: { cls: "bg-tone-good-bg text-tone-good-fg", label: "Low" },
  LowToModerate: { cls: "bg-tone-good-bg text-tone-good-fg", label: "Low to Moderate" },
  Moderate: { cls: "bg-tone-warn-bg text-tone-warn-fg", label: "Moderate" },
  ModeratelyHigh: { cls: "bg-tone-warn-bg text-tone-warn-fg", label: "Moderately High" },
  High: { cls: "bg-tone-bad-bg text-tone-bad-fg", label: "High" },
  VeryHigh: { cls: "bg-tone-bad-bg text-tone-bad-fg", label: "Very High" },
}

/** Ordered list of the six bands, Low → Very High, for spectrum rails. */
export const RISKOMETER_ORDER: FundRiskometerLevel[] = [
  "Low",
  "LowToModerate",
  "Moderate",
  "ModeratelyHigh",
  "High",
  "VeryHigh",
]
