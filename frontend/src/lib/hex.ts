import api from "@/lib/api"

export type HexAxisKey =
  | "value"
  | "quality"
  | "growth"
  | "moat"
  | "safety"
  | "pulse"

export type HexAxisLabel =
  | "Strong"
  | "Moderate"
  | "Weak"
  | "Positive"
  | "Neutral"
  | "Negative"

/**
 * Stage 2 (sector-percentile band) — see ValueBandChip.tsx.
 *
 * Backend computes the band per sector. These fields are present only
 * on the Value axis (and only after the Stage 2 backend deploys); the
 * UI must fall back to the legacy numeric score when `band` is absent.
 */
export type ValueBand =
  | "strong_discount"
  | "below_peers"
  | "in_range"
  | "above_peers"
  | "notably_overvalued"
  | "data_limited"

export type HexAxis = {
  score: number // 0..10
  label: HexAxisLabel | string
  why: string
  data_limited: boolean
  // NEW (Stage 2 — Value axis only, optional during rollout)
  band?: ValueBand
  percentile?: number | null
  sector_peers?: number
  sector_label?: string
  sector_median_mos?: number | null
  sector_median_pb?: number | null
  sector_median_rev_multiple?: number | null
}

export type HexResponse = {
  ticker: string
  sector_category: "general" | "bank" | "it"
  axes: {
    value: HexAxis
    quality: HexAxis
    growth: HexAxis
    moat: HexAxis
    safety: HexAxis
    pulse: HexAxis
  }
  overall: number
  sector_medians: Record<string, number>
  computed_at: string
  disclaimer: string
}

export type HexCompareResponse = {
  a: HexResponse
  b: HexResponse
}

/**
 * Ordered clockwise from the top vertex — matches Hex.tsx rendering order.
 * value (top), quality, growth, moat, safety, pulse.
 */
export const HEX_AXIS_ORDER: HexAxisKey[] = [
  "value",
  "quality",
  "growth",
  "moat",
  "safety",
  "pulse",
]

export const HEX_AXIS_BLURB: Record<HexAxisKey, string> = {
  value:
    "Value measures how the stock's price compares to its intrinsic worth. Higher means more discount to fair value.",
  quality:
    "Quality captures profitability, return on capital and earnings consistency. Higher means a better business.",
  growth:
    "Growth reflects revenue and earnings expansion over recent years. Higher means faster compounding.",
  moat:
    "Moat estimates durable competitive advantages — brand, scale, switching costs. Higher means more defensible.",
  safety:
    "Safety looks at balance-sheet quality, leverage and cash generation. Higher means lower financial risk.",
  pulse:
    "Pulse tracks recent momentum in price, analyst revisions and news sentiment. Higher means more positive near-term tailwinds.",
}

export async function fetchHex(ticker: string): Promise<HexResponse> {
  const res = await api.get(`/api/v1/hex/${encodeURIComponent(ticker)}`)
  return res.data
}

export type PortfolioHolding = { ticker: string; weight: number }

export type PortfolioHexResponse = HexResponse & {
  holdings?: Array<{ ticker: string; weight: number }>
  error?: string
  data_limited?: boolean
}

export async function fetchPortfolioHex(
  holdings: PortfolioHolding[],
): Promise<PortfolioHexResponse> {
  const res = await api.post("/api/v1/hex/portfolio", { holdings })
  return res.data
}

export async function fetchSectorMedian(
  category: "general" | "bank" | "it" = "general",
): Promise<{ category: string; medians: Record<string, number>; disclaimer: string }> {
  const res = await api.get(`/api/v1/hex/sector-median/${category}`)
  return res.data
}

export async function fetchHexCompare(
  t1: string,
  t2: string,
): Promise<HexCompareResponse> {
  const res = await api.get(`/api/v1/hex/compare`, {
    params: { t1, t2 },
  })
  return res.data
}
