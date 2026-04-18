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

/**
 * Fetch Prism data from backend. The server may return additional fields
 * (audit trail, model versions, etc.) — we extract only the subset the UI
 * needs so the component contract stays tight.
 */
export async function fetchPrism(ticker: string): Promise<PrismData> {
  const res = await api.get(`/api/v1/prism/${encodeURIComponent(ticker)}`)
  const d = res.data as Partial<PrismData> & Record<string, unknown>

  // Normalize to exactly-6 pillars in canonical order; tolerate missing
  // entries (data_limited fallback) so the UI never crashes on partial data.
  const byKey = new Map<PillarKey, Pillar>()
  const incoming = Array.isArray(d.pillars) ? (d.pillars as Pillar[]) : []
  for (const p of incoming) byKey.set(p.key, p)

  const pillars: Pillar[] = PRISM_PILLAR_ORDER.map((key) => {
    const p = byKey.get(key)
    if (p) return p
    return {
      key,
      score: null,
      label: "Neutral",
      why: "Data not available.",
      data_limited: true,
      weight: 1 / 6,
    }
  })

  return {
    ticker: String(d.ticker ?? ticker),
    company_name: String(d.company_name ?? ticker),
    verdict_band: (d.verdict_band as VerdictBand) ?? "fair",
    verdict_label: String(d.verdict_label ?? "Fair"),
    pillars,
    overall: typeof d.overall === "number" ? d.overall : 0,
    refraction_index:
      typeof d.refraction_index === "number"
        ? d.refraction_index
        : computeRefraction(pillars),
    pulse_velocity_hz:
      typeof d.pulse_velocity_hz === "number" && d.pulse_velocity_hz > 0
        ? d.pulse_velocity_hz
        : 0.5,
    sector_medians: d.sector_medians as PrismData["sector_medians"],
    disclaimer: String(
      d.disclaimer ??
        "Prism output is educational and not investment advice.",
    ),
  }
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
