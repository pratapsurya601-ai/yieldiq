import api from "@/lib/api"
import type {
  Pillar,
  PillarKey,
  PrismData,
  VerdictBand,
} from "@/components/prism/types"
import { PRISM_PILLAR_ORDER, computeRefraction } from "@/lib/prism"

/**
 * A compact historical snapshot of a stock's Prism state. The `axes` map is
 * sparse — any pillar we lack data for is omitted (or null). Pulse is almost
 * always absent for past quarters because our pulse engine only runs on live
 * data. The consumer is expected to render a data_limited lens in that case.
 */
export interface HistoryQuarter {
  /** ISO date of the quarter-end (e.g. "2023-06-30"). */
  quarter_end: string
  axes: Partial<Record<PillarKey, number | null>>
  overall: number
  refraction_index: number
  verdict_band: VerdictBand
}

interface HistoryResponse {
  ticker: string
  quarters: HistoryQuarter[]
}

/**
 * Pull N quarters of Prism history for a single ticker. The backend (Agent
 * Ψ1) guarantees chronological order — oldest first, newest last — so the
 * scrubber's index axis maps directly to time without a client-side sort.
 *
 * Throws on any non-2xx; the Time Machine modal catches to render its empty
 * state. We deliberately do NOT fabricate a fallback history client-side,
 * because showing fake pillar scores would violate SEBI guidance.
 */
export async function fetchHexHistory(
  ticker: string,
  quarters = 12,
): Promise<HistoryQuarter[]> {
  const res = await api.get(
    `/api/v1/prism/${encodeURIComponent(ticker)}/history`,
    { params: { quarters } },
  )
  const d = res.data as Partial<HistoryResponse> & Record<string, unknown>
  const list = Array.isArray(d.quarters) ? (d.quarters as HistoryQuarter[]) : []
  return list.map((q) => ({
    quarter_end: String(q.quarter_end ?? ""),
    axes: (q.axes ?? {}) as Partial<Record<PillarKey, number | null>>,
    overall: typeof q.overall === "number" ? q.overall : 0,
    refraction_index:
      typeof q.refraction_index === "number" ? q.refraction_index : 0,
    verdict_band: (q.verdict_band as VerdictBand) ?? "fair",
  }))
}

/** Simple numeric lerp, nullable-safe (null + anything = null — we never
 * invent data by filling in missing axes from the neighbouring quarter). */
function lerp(a: number | null | undefined, b: number | null | undefined, t: number): number | null {
  if (a == null || b == null) return null
  return a + (b - a) * t
}

/**
 * Interpolate between two consecutive quarters for sub-tick scrubbing.
 * `t` ∈ [0,1], where 0 == a and 1 == b. We carry the later quarter's
 * verdict_band forward past t=0 so the lens colour flips crisply rather than
 * cross-fading through a visually muddy intermediate.
 */
export function interpolateQuarter(
  a: HistoryQuarter,
  b: HistoryQuarter,
  t: number,
): HistoryQuarter {
  const tc = Math.max(0, Math.min(1, t))
  const keys = new Set<PillarKey>([
    ...(Object.keys(a.axes) as PillarKey[]),
    ...(Object.keys(b.axes) as PillarKey[]),
  ])
  const axes: Partial<Record<PillarKey, number | null>> = {}
  for (const k of keys) {
    axes[k] = lerp(a.axes[k], b.axes[k], tc)
  }
  return {
    quarter_end: tc < 0.5 ? a.quarter_end : b.quarter_end,
    axes,
    overall: (lerp(a.overall, b.overall, tc) as number) ?? 0,
    refraction_index:
      (lerp(a.refraction_index, b.refraction_index, tc) as number) ?? 0,
    verdict_band: tc < 0.5 ? a.verdict_band : b.verdict_band,
  }
}

/**
 * Format a calendar-quarter abbreviation like "Q2'23" for tick labels on the
 * scrubber. Accepts any ISO-ish date; falls back to the raw string if
 * parsing fails so the UI never shows "NaN".
 */
export function quarterLabel(isoDate: string): string {
  const d = new Date(isoDate)
  if (Number.isNaN(d.getTime())) return isoDate
  const month = d.getUTCMonth() + 1
  const q = Math.floor((month - 1) / 3) + 1
  const yy = String(d.getUTCFullYear()).slice(-2)
  return `Q${q}'${yy}`
}

/**
 * Maps a verdict band to the short human-readable label the Prism component
 * surfaces in Spectrum mode. The backend `history` endpoint only ships the
 * band, so we derive the label client-side to keep the wire payload tight.
 */
export function verdictBandLabel(band: VerdictBand): string {
  switch (band) {
    case "deepValue":
      return "Deep Value"
    case "undervalued":
      return "Undervalued"
    case "overvalued":
      return "Overvalued"
    case "expensive":
      return "Expensive"
    case "fair":
    default:
      return "Fair"
  }
}

/**
 * Fuse a live PrismData (used for per-pillar metadata like label, why,
 * weight) with a HistoryQuarter snapshot to produce a PrismData that the
 * existing `<Prism>` component can render unchanged. Any axis missing from
 * the historical quarter is marked data_limited — crucial for Pulse, which
 * we never have backfill for.
 */
export function synthesizePrismData(
  base: PrismData,
  q: HistoryQuarter,
): PrismData {
  const pillars: Pillar[] = PRISM_PILLAR_ORDER.map((key) => {
    const basePillar = base.pillars.find((p) => p.key === key)
    const score = q.axes[key]
    const hasScore = typeof score === "number" && Number.isFinite(score)
    if (hasScore && basePillar) {
      return {
        ...basePillar,
        score: score as number,
        data_limited: false,
      }
    }
    // No historical score for this axis — render as data_limited (grey lens
    // with "n/a"), preserving the base pillar's metadata so tooltips still
    // render a coherent "why" string.
    return {
      key,
      score: null,
      label: basePillar?.label ?? "Neutral",
      why: basePillar?.why ?? "Data not available for this quarter.",
      data_limited: true,
      weight: basePillar?.weight ?? 1 / 6,
    }
  })

  return {
    ticker: base.ticker,
    company_name: base.company_name,
    verdict_band: q.verdict_band,
    verdict_label: verdictBandLabel(q.verdict_band),
    pillars,
    overall: q.overall,
    refraction_index:
      Number.isFinite(q.refraction_index) && q.refraction_index > 0
        ? q.refraction_index
        : computeRefraction(pillars),
    // Hold the live breathing cadence — historical breath rate would require
    // a matching historical pulse score, which we don't have.
    pulse_velocity_hz: base.pulse_velocity_hz,
    sector_medians: base.sector_medians,
    disclaimer: base.disclaimer,
  }
}
