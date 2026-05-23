import api from "@/lib/api"
import type { HexAxisKey } from "@/lib/hex"

/**
 * Day-99 (2026-05-22): industry-relative percentile rankings.
 *
 * No Indian competitor surfaces percentile context next to a pillar
 * score. This client wraps the public endpoint and the SEBI-safe
 * adjective bucketing used by AnalysisHero / Hex.
 */
export type IndustryPercentileResponse = {
  ticker: string
  industry: string | null
  cohort_size: number
  percentiles: Partial<Record<"score" | HexAxisKey, number | null>>
  caveat?: string
}

export async function fetchIndustryPercentile(
  ticker: string,
): Promise<IndustryPercentileResponse> {
  const res = await api.get(
    `/api/v1/public/percentile/${encodeURIComponent(ticker)}`,
  )
  return res.data
}

/**
 * Render the SEBI-safe one-line caption shown under the YieldIQ
 * Score. Buckets:
 *
 *   >= 75 → "Top quartile in {industry}"
 *   50-74 → "Above {industry} median"
 *   25-49 → "Below {industry} median"
 *   <  25 → "Bottom quartile in {industry}"
 *
 * Explicitly avoids the SEBI-banned vocabulary. See
 * backend/services/analysis/sebi_filter.py for the canonical
 * banned list this caption is designed against.
 */
export function percentileCaption(
  percentile: number | null | undefined,
  industry: string | null | undefined,
): string | null {
  if (typeof percentile !== "number" || !Number.isFinite(percentile)) {
    return null
  }
  if (!industry) return null
  const safeIndustry = industry.trim()
  if (!safeIndustry) return null
  if (percentile >= 75) return `Top quartile in ${safeIndustry}`
  if (percentile >= 50) return `Above ${safeIndustry} median`
  if (percentile >= 25) return `Below ${safeIndustry} median`
  return `Bottom quartile in ${safeIndustry}`
}

/**
 * Day-127 (2026-05-23): peer-count caption rendered under the
 * bucket caption so users know how big the cohort is. A "Top
 * quartile" label is far more informative against 40 peers than
 * against 3, and surfacing the count is the cheapest way to let
 * the user judge. Returns null when the cohort is missing or
 * empty so callers can hide the line entirely.
 */
export function peerCountCaption(
  cohortSize: number | null | undefined,
  industry: string | null | undefined,
): string | null {
  if (typeof cohortSize !== "number" || !Number.isFinite(cohortSize)) {
    return null
  }
  if (cohortSize <= 0) return null
  if (!industry) return null
  const safeIndustry = industry.trim()
  if (!safeIndustry) return null
  const noun = cohortSize === 1 ? "peer" : "peers"
  return `vs. ${cohortSize} ${noun} in ${safeIndustry}`
}
