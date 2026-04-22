export type PillarKey =
  | "value"
  | "quality"
  | "growth"
  | "moat"
  | "safety"
  | "pulse"

export type VerdictBand =
  | "deepValue"
  | "undervalued"
  | "fair"
  | "overvalued"
  | "expensive"

export type PrismMode = "signature" | "spectrum"

export interface Pillar {
  key: PillarKey
  /** 0..10, or null for data_limited. */
  score: number | null
  /** "Strong" | "Moderate" | "Weak" | "Positive" | "Neutral" | "Negative" */
  label: string
  /** Short explainer sentence. */
  why: string
  data_limited: boolean
  /** Relative weight in composite, 0..1. */
  weight: number
}

export interface PrismData {
  ticker: string
  company_name: string
  verdict_band: VerdictBand
  verdict_label: string
  /** Exactly 6 pillars. */
  pillars: Pillar[]
  /** Already-weighted composite, 0..10. */
  overall: number
  /** Dispersion metric, 0..5. */
  refraction_index: number
  /** Breathing rate (Hz) for the Pulse lens. */
  pulse_velocity_hz: number
  sector_medians?: Partial<Record<PillarKey, number>>
  disclaimer: string
  /**
   * ISO timestamp of when this Prism payload was computed on the
   * backend. Optional — some code paths (legacy snapshots, fixtures)
   * don't emit it. EditorialHero hides the "last refresh" badge when
   * this is missing rather than rendering a dash.
   */
  computed_at?: string
  /**
   * Last 12 monthly YieldIQ-score samples (oldest → newest, 0-100).
   * Backend returns `[]` when fewer than 3 monthly rows exist in
   * `fair_value_history`. Consumers should render an "insufficient
   * history" state rather than fake data when length < 2.
   */
  score_history_12m?: number[]
}
