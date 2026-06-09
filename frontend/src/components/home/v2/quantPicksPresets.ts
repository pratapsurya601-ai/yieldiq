// Quant-picks preset registry — shared by QuantPicksGrid and the
// TodaysMovers "Worth a look" fallback so both surfaces (a) reuse the
// same fetcher functions, (b) share React Query cache slots (identical
// queryKey shape), and (c) stay in sync when a preset is added or
// retired. Pulled out as its own module rather than re-exported from
// QuantPicksGrid.tsx because that component is dynamic()-imported and
// importing it for the config would round-trip a JS chunk for no reason.

import { runPreset, runScreener } from "@/lib/api"
import type { ScreenerResponse } from "@/types/api"

export type QuantPresetKey =
  | "buffett"
  | "deep_value"
  | "growth_quality"
  | "quality_discount"

export interface QuantPresetConfig {
  key: QuantPresetKey
  title: string
  blurb: string
  fetcher: () => Promise<ScreenerResponse>
  href: string
}

// href values intentionally use frontend SCREENER_PRESETS keys (from
// frontend/src/lib/screenerFilters.ts) rather than the backend preset
// names used by the fetcher above. The screener page reads `?preset=<key>`
// on mount via applyPreset, which looks up the frontend preset library;
// the backend preset names (buffett / deep-value / growth-quality) are
// only honored via the alias map in screener/page.tsx. By writing the
// canonical frontend key here we skip the alias hop entirely.
//
// The 4th tile's previous href used `?min_score=...&min_mos=...` loose
// query params that the screener page never read (it expects a
// serialized DSL string in `?filters=`), so the link was a dead-end by
// construction — fixed here to point at the closest frontend preset.
export const QUANT_PRESETS: QuantPresetConfig[] = [
  {
    key: "buffett",
    title: "Wide-Moat at Discount",
    blurb: "Score ≥ 60 · Wide moat · MoS ≥ 0",
    fetcher: () => runPreset("buffett"),
    href: "/screener?preset=high_quality",
  },
  {
    key: "deep_value",
    title: "Deep Value",
    blurb: "MoS ≥ 30%",
    fetcher: () => runPreset("deep-value"),
    href: "/screener?preset=deep_value",
  },
  {
    key: "growth_quality",
    title: "High-Margin Growers",
    blurb: "Revenue + margin filters",
    fetcher: () => runPreset("growth-quality"),
    href: "/screener?preset=high_quality",
  },
  {
    key: "quality_discount",
    title: "Quality at a Discount",
    blurb: "Score ≥ 65 · MoS ≥ 20%",
    fetcher: () => runScreener({ min_score: 65, min_mos: 20, page_size: 25 }),
    href: "/screener?preset=high_quality",
  },
]

/**
 * Stable React Query key for a quant-picks tile. MUST match the shape
 * used by QuantPicksGrid.tsx so both consumers share the same cache
 * slot — when both render on /home, the second component reads from
 * cache instead of issuing a duplicate round-trip.
 */
export const quantPresetQueryKey = (key: QuantPresetKey) => [
  "quant-tile",
  key,
]
