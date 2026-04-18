import api from "@/lib/api"
import type { PillarKey } from "@/components/prism/types"

export interface NarrationPillar {
  key: PillarKey
  prose: string
  duration_ms: number
}

export interface Narration {
  ticker: string
  intro: string
  pillars: NarrationPillar[]
  outro: string
  total_duration_ms: number
  intro_duration_ms?: number
  outro_duration_ms?: number
  disclaimer?: string
  source?: string
  cached?: boolean
}

/**
 * Fetch the 45-second Prism narration for a ticker. The backend caches for
 * 24h and falls back to a deterministic templated narration if Groq fails,
 * so this call essentially never throws a 5xx — we only surface the axios
 * error to the caller so the play button can revert to its idle state.
 */
export async function fetchNarration(ticker: string): Promise<Narration> {
  const res = await api.post(
    `/api/v1/prism/${encodeURIComponent(ticker)}/narrate`,
  )
  const d = res.data as Partial<Narration> & Record<string, unknown>

  const pillars: NarrationPillar[] = Array.isArray(d.pillars)
    ? (d.pillars as NarrationPillar[]).map((p) => ({
        key: p.key,
        prose: String(p.prose ?? ""),
        duration_ms: Number(p.duration_ms ?? 6500),
      }))
    : []

  return {
    ticker: String(d.ticker ?? ticker),
    intro: String(d.intro ?? ""),
    pillars,
    outro: String(d.outro ?? ""),
    total_duration_ms: Number(d.total_duration_ms ?? 45000),
    intro_duration_ms: Number(d.intro_duration_ms ?? 4000),
    outro_duration_ms: Number(d.outro_duration_ms ?? 4000),
    disclaimer:
      typeof d.disclaimer === "string" ? (d.disclaimer as string) : undefined,
    source: typeof d.source === "string" ? (d.source as string) : undefined,
    cached: Boolean(d.cached),
  }
}
