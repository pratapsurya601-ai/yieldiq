"use client"

/**
 * YIQScoreBreakdown — Tickertape-style transparent score composition.
 *
 * Sprint: feat/analysis-yiq-score-breakdown (2026-06-10).
 *
 * Problem statement
 * -----------------
 * The analysis page surfaces a YieldIQ Score in HonestHero's sticky rail
 * (rendered as "<score> / 100"). The composition of that score is
 * already exposed through `quality.score_breakdown` (the existing
 * 4-component / 100-pt Phase C.3 panel — Business Quality / Growth /
 * Valuation / Sentiment). What we did NOT have was a transparent reveal
 * of the FIVE Confidence pillars that gate the headline numbers —
 * data quality, model fit, FV stability, sensitivity, and composite
 * agreement. Those pillars feed verdict-intensity gating and explain
 * why two stocks at the same MoS can end up with a very different
 * trust posture on the page.
 *
 * Surface
 * -------
 * A "trust-score" composition out of 120 (25 + 25 + 25 + 25 + 20). The
 * 120 cap comes from the five pillar weights below, not a separately
 * computed number — each pillar is a 0-100 backend score, scaled to its
 * weight at render time. This keeps the component server-data-honest:
 * if the backend changes a pillar, this panel automatically reflects it.
 *
 *   Data Quality            +X / 25   data_quality_score        × 0.25
 *   Model Confidence        +X / 25   model_confidence_score    × 0.25
 *   Valuation Stability     +X / 25   valuation_stability_score × 0.25
 *   Sensitivity             +X / 25   confidence_sensitivity    × 0.25
 *   Composite Agreement     +X / 20   confidence_composite_agree× 0.20
 *
 * Sensitivity is null for holdcos + banks (residual-income shaped);
 * composite_agreement is null when only one estimator runs. When a
 * pillar is null we render "—" with a per-pillar caveat string and
 * exclude it from the cap. The visible cap line ("X of N applicable")
 * tells the user how many pillars contributed.
 *
 * Animation
 * ---------
 * Tickertape-style reveal — bars grow from 0 → target width on mount
 * using a single CSS transition (no framer-motion needed, keeps the
 * component server-mountable behind a "use client" boundary). Honors
 * `prefers-reduced-motion`: when set, the bars render at target width
 * immediately with no transition.
 *
 * SEBI lens: every label is descriptive ("Data Quality", "Model
 * Confidence", "Stability", "Sensitivity", "Agreement"). No imperative
 * verbs, no directive language. The 1-line explainer per pillar is
 * purely methodology — what the score measures, not any guidance.
 *
 * Accessibility: each bar carries an aria-valuenow/min/max via role
 * "meter" so screen readers announce e.g. "Data Quality 18 of 25".
 * The trigger summary surfaces the total as "X of 120 applicable
 * pillars" so AT users get the headline without traversing the table.
 */

import * as React from "react"

/* ------------------------------------------------------------------ */
/*  Public shape                                                       */
/* ------------------------------------------------------------------ */

export interface YIQConfidencePillars {
  /** completeness/freshness of financials inputs (0-100, null if N/A) */
  data_quality: number | null
  /** engine-fit-for-this-business (0-100, null if N/A) */
  model_confidence: number | null
  /** variance of FV over recent weeks (0-100, null if N/A) */
  valuation_stability: number | null
  /** Monte Carlo verdict-preservation (0-100, null for banks/holdcos) */
  sensitivity: number | null
  /** composite-IV estimator clustering (0-100, null on single estimator) */
  composite_agreement: number | null
}

export interface YIQScoreBreakdownProps {
  /** displayed-ticker for the section heading aria-label */
  ticker?: string
  pillars: YIQConfidencePillars
}

/* ------------------------------------------------------------------ */
/*  Pillar table (weight + one-line explainer)                         */
/* ------------------------------------------------------------------ */

interface PillarMeta {
  key: keyof YIQConfidencePillars
  label: string
  weight: number                // weight of this pillar (sums to 120)
  why: string                   // 1-sentence "why this score?" explainer
  naReason: string              // why this pillar can be null
}

const PILLARS: ReadonlyArray<PillarMeta> = [
  {
    key: "data_quality",
    label: "Data Quality",
    weight: 25,
    why: "How complete, fresh, and scale-clean the underlying financial inputs are.",
    naReason: "Not enough input coverage to score.",
  },
  {
    key: "model_confidence",
    label: "Model Confidence",
    weight: 25,
    why: "How well our valuation engine fits this kind of business (large-cap DCF, recent IPO, regulated, etc).",
    naReason: "Engine-fit signal unavailable.",
  },
  {
    key: "valuation_stability",
    label: "Valuation Stability",
    weight: 25,
    why: "How stable the fair-value time-series has been over the last few weeks — whippy FVs warn the model is over-reacting.",
    naReason: "Not enough FV history yet.",
  },
  {
    key: "sensitivity",
    label: "Sensitivity",
    weight: 25,
    why: "Share of perturbed Monte Carlo runs (WACC / FCF / TG / tax) that preserve the base verdict.",
    naReason: "Different engine shape — sensitivity not applicable (banks, holdcos).",
  },
  {
    key: "composite_agreement",
    label: "Composite Agreement",
    weight: 20,
    why: "How tightly the composite IV constituent estimators cluster — high score means the methods agree.",
    naReason: "Single-estimator path — no composite to cluster.",
  },
]

/** Sum of pillar weights — gives the headline denominator (120). */
const MAX_TOTAL: number = PILLARS.reduce((acc, p) => acc + p.weight, 0)

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Map a 0-100 pillar score to its weighted contribution, floored. */
function contributionFor(pillarScore: number | null, weight: number): number | null {
  if (pillarScore == null || Number.isNaN(pillarScore)) return null
  const clamped = Math.max(0, Math.min(100, pillarScore))
  // Floor (never round up) so a 78/100 doesn't appear as 20/25 — matches
  // the canonical YieldIQ Score's floor-not-round posture documented in
  // docs/diagnostics/phase-c-score-formula-2026-05-25.md.
  return Math.floor((clamped / 100) * weight)
}

/** Tone band per Confidence Framework convention (PR #340 +). */
function toneFor(pillarScore: number | null): "good" | "neutral" | "warn" | "muted" {
  if (pillarScore == null) return "muted"
  if (pillarScore >= 80) return "good"
  if (pillarScore >= 60) return "neutral"
  return "warn"
}

function barClass(tone: ReturnType<typeof toneFor>): string {
  switch (tone) {
    case "good":
      return "bg-emerald-500/80 dark:bg-emerald-400/80"
    case "neutral":
      return "bg-slate-500/70 dark:bg-slate-300/70"
    case "warn":
      return "bg-amber-500/80 dark:bg-amber-400/80"
    default:
      return "bg-slate-300/60 dark:bg-slate-700/60"
  }
}

function trackClass(): string {
  return "bg-slate-200/70 dark:bg-slate-800/60"
}

/** Hook: detect prefers-reduced-motion safely on SSR / client. */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = React.useState<boolean>(false)
  React.useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)")
    setReduced(mql.matches)
    const handler = (ev: MediaQueryListEvent) => setReduced(ev.matches)
    // Older Safari only supports addListener
    if (mql.addEventListener) {
      mql.addEventListener("change", handler)
      return () => mql.removeEventListener("change", handler)
    }
    mql.addListener(handler)
    return () => mql.removeListener(handler)
  }, [])
  return reduced
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function YIQScoreBreakdown({
  ticker,
  pillars,
}: YIQScoreBreakdownProps) {
  const reducedMotion = usePrefersReducedMotion()

  // On mount: bars grow from 0 → target width unless reduced motion is on.
  // We use a single mounted flag so the transition fires exactly once.
  const [mounted, setMounted] = React.useState<boolean>(false)
  React.useEffect(() => {
    if (reducedMotion) {
      setMounted(true)
      return
    }
    // Defer one frame so the initial 0% paints before transition to target.
    const id = window.requestAnimationFrame(() => setMounted(true))
    return () => window.cancelAnimationFrame(id)
  }, [reducedMotion])

  // Pre-compute the contribution rows + the headline numerator/denominator.
  const rows = React.useMemo(() => {
    return PILLARS.map((p) => {
      const raw = pillars[p.key]
      const contribution = contributionFor(raw, p.weight)
      return {
        meta: p,
        raw,
        contribution,
        applicable: contribution != null,
      }
    })
  }, [pillars])

  const applicable = rows.filter((r) => r.applicable)
  const numerator = applicable.reduce((acc, r) => acc + (r.contribution ?? 0), 0)
  // Headline denominator stays fixed at 120 so users see the same scale
  // every time; the "applicable" tail tells them how many pillars
  // contributed. This is the Tickertape posture — total never moves
  // even when one row is N/A.
  const denominator = MAX_TOTAL

  // Empty state: every pillar is null — render nothing rather than a
  // misleading "0 of 120".
  if (applicable.length === 0) return null

  const sectionId = `yiq-score-breakdown${ticker ? `-${ticker.toLowerCase().replace(/[^a-z0-9]/g, "")}` : ""}`

  return (
    <section
      aria-labelledby={`${sectionId}-heading`}
      className="rounded-2xl border border-line bg-bg p-4 text-ink"
      data-testid="yiq-score-breakdown"
    >
      {/* ── Header row ─────────────────────────────────────────── */}
      <header className="flex items-baseline justify-between gap-3">
        <div>
          <h3
            id={`${sectionId}-heading`}
            className="text-[11px] font-semibold uppercase tracking-[0.18em] text-caption"
          >
            YieldIQ Score Breakdown
          </h3>
          <p className="mt-0.5 text-[11px] text-caption">
            {applicable.length} of {PILLARS.length} pillars applicable
          </p>
        </div>
        <div className="text-right">
          <div
            className="font-mono tabular-nums text-3xl font-semibold text-ink"
            aria-label={`Total trust score: ${numerator} of ${denominator}`}
          >
            <span data-testid="yiq-score-breakdown-numerator">{numerator}</span>
            <span className="text-base text-caption font-normal">
              {" / "}
              {denominator}
            </span>
          </div>
          <p className="mt-0.5 text-[10px] uppercase tracking-[0.15em] text-caption">
            Trust composition
          </p>
        </div>
      </header>

      {/* ── Bar list ───────────────────────────────────────────── */}
      <ol className="mt-4 flex flex-col gap-3" aria-label="Pillar contributions">
        {rows.map((row) => {
          const tone = toneFor(row.raw)
          // Width is contribution / weight, expressed as a percent of the
          // pillar's own track (not the global 120 cap). This keeps short
          // bars visually meaningful — a 20/25 reads as 80% full, not 17%.
          const targetPct = row.applicable
            ? Math.max(0, Math.min(100, ((row.contribution ?? 0) / row.meta.weight) * 100))
            : 0
          const renderedPct = mounted ? targetPct : 0

          return (
            <li key={row.meta.key} className="flex flex-col gap-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[12px] font-medium text-ink">
                  {row.meta.label}
                </span>
                <span
                  className="font-mono tabular-nums text-[12px] text-ink"
                  data-testid={`yiq-pillar-${row.meta.key}-value`}
                >
                  {row.applicable ? (
                    <>
                      <span>+{row.contribution}</span>
                      <span className="text-caption"> / {row.meta.weight}</span>
                    </>
                  ) : (
                    <span className="text-caption">— / {row.meta.weight}</span>
                  )}
                </span>
              </div>

              <div
                className={`h-2 w-full overflow-hidden rounded-full ${trackClass()}`}
                role="meter"
                aria-valuemin={0}
                aria-valuemax={row.meta.weight}
                aria-valuenow={row.applicable ? row.contribution ?? 0 : 0}
                aria-valuetext={
                  row.applicable
                    ? `${row.contribution} of ${row.meta.weight}`
                    : "Not applicable"
                }
                aria-label={`${row.meta.label} contribution`}
              >
                <div
                  className={`h-full rounded-full ${barClass(tone)}`}
                  style={{
                    width: `${renderedPct}%`,
                    transition: reducedMotion
                      ? "none"
                      : "width 720ms cubic-bezier(0.22, 1, 0.36, 1)",
                  }}
                  data-testid={`yiq-pillar-${row.meta.key}-bar`}
                />
              </div>

              <p className="text-[11px] leading-snug text-caption">
                {row.applicable ? row.meta.why : row.meta.naReason}
              </p>
            </li>
          )
        })}
      </ol>

      {/* ── Footer disclaimer ─────────────────────────────────── */}
      <p className="mt-4 text-[10px] leading-snug text-caption">
        Each pillar is scored 0-100 by our confidence engine and weighted into
        a {denominator}-point trust composition. Contributions are floored, not
        rounded. A non-applicable pillar (banks, holdcos, single-estimator
        paths) is excluded from the cap rather than scored zero.
      </p>
    </section>
  )
}
