import api from "@/lib/api"
import type {
  Pillar,
  PillarKey,
  PrismData,
  VerdictBand,
} from "@/components/prism/types"

/**
 * Canonical axis order for the Spectrum view: typically-strong → volatile.
 * Pulse first (our signature axis at the top), Value last (most volatile).
 */
export const PRISM_PILLAR_ORDER: PillarKey[] = [
  "pulse",
  "quality",
  "moat",
  "safety",
  "growth",
  "value",
]

// Default weights used by the backend hex_service. If the backend response
// omits per-pillar weights (current shape), reuse these so the composite
// math on the client matches the server.
const PILLAR_WEIGHTS: Record<PillarKey, number> = {
  pulse: 0.10, quality: 0.22, moat: 0.18, safety: 0.15, growth: 0.15, value: 0.20,
}

/**
 * Adapt the backend /api/v1/prism/{ticker} response (which nests the 6
 * axes under `hex.axes` keyed by pillar name, with `hex.overall` and
 * `hex.sector_medians`) into the flat PrismData shape the UI expects.
 *
 * Safe to call on any shape — always returns a valid PrismData. If the
 * response is completely empty, returns a data_limited Prism so the UI
 * renders greyed-out rather than crashing.
 */
export function adaptPrismResponse(raw: unknown, fallbackTicker = ""): PrismData {
  const r = (raw ?? {}) as Record<string, unknown>
  const hex = (r.hex as Record<string, unknown> | undefined) ?? {}
  const axes = (hex.axes as Record<string, Record<string, unknown>> | undefined) ?? {}

  const pillars: Pillar[] = PRISM_PILLAR_ORDER.map((key) => {
    const a = axes[key] ?? {}
    const rawScore = a.score
    const score = typeof rawScore === "number" && !Number.isNaN(rawScore) ? rawScore : null
    const limitedFlag = a.data_limited === true
    const isLimited = limitedFlag || score == null
    return {
      key,
      score: isLimited ? null : score,
      label: typeof a.label === "string" ? a.label : "Neutral",
      why: typeof a.why === "string" ? a.why : "Data not available.",
      data_limited: isLimited,
      weight: PILLAR_WEIGHTS[key],
    }
  })

  const overallRaw = typeof hex.overall === "number"
    ? hex.overall
    : typeof r.yieldiq_score_100 === "number"
      ? (r.yieldiq_score_100 as number) / 10
      : NaN
  const overall = Number.isFinite(overallRaw) ? (overallRaw as number) : 5

  const sectorMediansRaw = hex.sector_medians as Record<string, unknown> | undefined
  const sector_medians: Partial<Record<PillarKey, number>> = {}
  if (sectorMediansRaw) {
    for (const k of PRISM_PILLAR_ORDER) {
      const v = sectorMediansRaw[k]
      if (typeof v === "number") sector_medians[k] = v
    }
  }

  // Score history — optional array of numbers, 0..100, oldest → newest.
  // Backend emits `score_history_12m: []` when it doesn't have at least
  // three monthly samples. We keep empty arrays as-is so consumers can
  // render an "insufficient history" state.
  const rawHistory = r.score_history_12m
  const score_history_12m = Array.isArray(rawHistory)
    ? rawHistory.filter((n): n is number => typeof n === "number" && Number.isFinite(n))
    : []

  return {
    ticker: String(r.ticker ?? fallbackTicker),
    company_name: String(r.company_name ?? fallbackTicker),
    verdict_band: (r.verdict_band as VerdictBand) ?? "fair",
    verdict_label: String(r.verdict_label ?? "Fair value region"),
    pillars,
    overall,
    refraction_index: typeof r.refraction_index === "number" ? r.refraction_index : computeRefraction(pillars),
    pulse_velocity_hz: typeof r.pulse_velocity_hz === "number" && r.pulse_velocity_hz > 0 ? r.pulse_velocity_hz : 0.33,
    sector_medians,
    disclaimer: typeof r.disclaimer === "string" ? r.disclaimer : "Model estimate. Not investment advice.",
    score_history_12m,
  }
}

/**
 * Fetch Prism data from backend. The server may return additional fields
 * (audit trail, model versions, etc.) — we extract only the subset the UI
 * needs so the component contract stays tight.
 */
export async function fetchPrism(ticker: string): Promise<PrismData> {
  const res = await api.get(`/api/v1/prism/${encodeURIComponent(ticker)}`)
  return adaptPrismResponse(res.data, ticker)
}

/**
 * Client-side refraction fallback: standard deviation of non-null scores,
 * normalized by dividing by 3.5 and clamped to 0..5. Higher means pillars
 * disagree more — the light "refracts" more strongly.
 */
export function computeRefraction(pillars: Pillar[]): number {
  const scores = pillars
    .map((p) => p.score)
    .filter((s): s is number => typeof s === "number")
  if (scores.length < 2) return 0
  const mean = scores.reduce((a, b) => a + b, 0) / scores.length
  const variance =
    scores.reduce((a, b) => a + (b - mean) ** 2, 0) / scores.length
  const stddev = Math.sqrt(variance)
  const idx = stddev / 3.5
  return Math.max(0, Math.min(5, idx))
}

/**
 * Verdict → semantic color token. Undervaluation is treated as a positive
 * (green); overvaluation as caution (red). "Fair" sits in the warning lane
 * because fair-priced stocks are neither opportunity nor risk.
 */
export function verdictColor(band: VerdictBand): string {
  switch (band) {
    case "deepValue":
    case "undervalued":
      return "var(--color-success)"
    case "overvalued":
    case "expensive":
      return "var(--color-danger)"
    case "fair":
    default:
      return "var(--color-warning)"
  }
}

/**
 * Per-pillar color. Users learn the associations over time ("orange = Value"),
 * so these are stable and tokenized. Pulse stays on our brand blue since it
 * is the signature axis.
 */
export function pillarColor(key: PillarKey): string {
  switch (key) {
    case "pulse":
      return "var(--color-brand)"
    case "quality":
      return "var(--color-success)"
    case "moat":
      return "var(--prism-moat, #0d9488)"
    case "safety":
      return "var(--prism-safety, #3b82f6)"
    case "growth":
      return "var(--prism-growth, #eab308)"
    case "value":
      return "var(--prism-value, #f97316)"
  }
}
