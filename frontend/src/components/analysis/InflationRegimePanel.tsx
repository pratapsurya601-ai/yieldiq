// frontend/src/components/analysis/InflationRegimePanel.tsx
//
// Inflation-regime DCF adjustment (2026-06-10).
//
// Displays a side-by-side comparison of the nominal-terms DCF (the
// primary engine output) and the real-terms recompute, so the reader
// can see how much the headline CPI regime is distorting the fair
// value. Three bands of regime tone:
//
//   low / normal  -> neutral framing (nominal is canonical)
//   high          -> amber caution band, real-terms shown alongside
//   extreme       -> rose warning band, real-terms emphasised
//
// The component is pure presentation — every number comes from
// backend/services/inflation_regime_service.py via the
// AnalysisResponse.inflation_regime_adjustment field.
//
// SEBI-safe by construction: no advice vocabulary, only quantitative
// comparison and the operator-facing "model_note" tag which is
// always rendered as a label, never as a directive.

import React from "react"
import type { AnalysisResponse } from "@/types/api"

type Regime = "low" | "normal" | "high" | "extreme"
type ModelNote = "use_nominal" | "use_real" | "blended"

type AdjustmentBlock = NonNullable<AnalysisResponse["inflation_regime_adjustment"]>

interface Props {
  adjustment?: AdjustmentBlock | null
}

const REGIME_LABEL: Record<Regime, string> = {
  low: "Low inflation",
  normal: "Normal inflation",
  high: "High inflation",
  extreme: "Extreme inflation",
}

const REGIME_BLURB: Record<Regime, string> = {
  low:
    "Headline CPI sits below the 4% baseline our nominal DCF is calibrated against. Real-terms recompute is reported for completeness only.",
  normal:
    "Headline CPI sits inside the RBI 4–6% band — the nominal DCF reflects market reality and the real-terms recompute tracks closely.",
  high:
    "Headline CPI is materially above the calibration baseline. Compare the two valuations below; large gaps mean the nominal model is mis-pricing the cash-flow trajectory.",
  extreme:
    "Headline CPI is well outside the RBI tolerance band. Nominal-terms DCF is unreliable in this regime — the real-terms recompute is the more conservative anchor.",
}

const REGIME_TONE: Record<
  Regime,
  { panel: string; pill: string; pillBg: string }
> = {
  low: {
    panel:
      "border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-900/40",
    pill: "text-slate-700 dark:text-slate-300",
    pillBg: "bg-slate-200/70 dark:bg-slate-700/60",
  },
  normal: {
    panel:
      "border-sky-200 dark:border-sky-800 bg-sky-50/40 dark:bg-sky-950/30",
    pill: "text-sky-700 dark:text-sky-300",
    pillBg: "bg-sky-100 dark:bg-sky-900/50",
  },
  high: {
    panel:
      "border-amber-300 dark:border-amber-700 bg-amber-50/50 dark:bg-amber-950/30",
    pill: "text-amber-800 dark:text-amber-300",
    pillBg: "bg-amber-100 dark:bg-amber-900/40",
  },
  extreme: {
    panel:
      "border-rose-300 dark:border-rose-700 bg-rose-50/50 dark:bg-rose-950/30",
    pill: "text-rose-800 dark:text-rose-300",
    pillBg: "bg-rose-100 dark:bg-rose-900/40",
  },
}

const MODEL_NOTE_LABEL: Record<ModelNote, string> = {
  use_nominal: "Nominal model remains canonical",
  use_real: "Real-terms recompute is the more conservative anchor",
  blended: "Blend nominal and real-terms before reading the fair value",
}

function formatRupee(n: number | null): string {
  if (n == null || !Number.isFinite(n)) return "n/a"
  if (Math.abs(n) >= 100000) {
    return `Rs ${(n / 1000).toFixed(1)}k`
  }
  return `Rs ${n.toFixed(2)}`
}

function formatPct(n: number, digits = 2): string {
  if (!Number.isFinite(n)) return "n/a"
  return `${n.toFixed(digits)}%`
}

function signedPct(n: number): string {
  if (!Number.isFinite(n)) return "n/a"
  const sign = n > 0 ? "+" : ""
  return `${sign}${n.toFixed(2)}%`
}

export default function InflationRegimePanel({ adjustment }: Props) {
  if (!adjustment) return null

  const regime = adjustment.regime as Regime
  const model_note = adjustment.model_note as ModelNote
  const tone = REGIME_TONE[regime] ?? REGIME_TONE.normal

  return (
    <section
      data-testid="inflation-regime-panel"
      className={`rounded-2xl border ${tone.panel} px-5 py-5 sm:px-6 sm:py-6 mt-6 mb-6`}
      aria-label="Inflation regime DCF adjustment"
    >
      <header className="flex items-start justify-between gap-3 flex-wrap mb-4">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-200">
            Inflation regime DCF check
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Nominal vs real-terms valuation under the current CPI band.
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium ${tone.pill} ${tone.pillBg}`}
        >
          <span className="inline-block w-2 h-2 rounded-full bg-current opacity-70" />
          {REGIME_LABEL[regime]} ({formatPct(adjustment.current_cpi_pct, 1)})
        </span>
      </header>

      <p className="text-sm text-slate-700 dark:text-slate-300 mb-5">
        {REGIME_BLURB[regime]}
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-5">
        <ValuationCard
          label="Nominal-terms FV"
          subLabel="Headline DCF"
          rate={`WACC ${formatPct(
            adjustment.real_wacc_pct + adjustment.current_cpi_pct,
            2,
          )} | g ${formatPct(
            adjustment.real_growth_pct + adjustment.current_cpi_pct,
            2,
          )}`}
          value={adjustment.nominal_fv}
        />
        <ValuationCard
          label="Real-terms FV"
          subLabel="CPI-stripped recompute"
          rate={`real WACC ${formatPct(adjustment.real_wacc_pct, 2)} | real g ${formatPct(
            adjustment.real_growth_pct,
            2,
          )}`}
          value={adjustment.real_terms_fv}
          emphasised={regime === "extreme"}
        />
      </div>

      <DistortionStrip
        distortionPct={adjustment.fv_distortion_pct}
        nominalFv={adjustment.nominal_fv}
        realFv={adjustment.real_terms_fv}
      />

      <div className="mt-5 pt-4 border-t border-slate-200 dark:border-slate-700/60">
        <p className="text-xs uppercase tracking-wide font-semibold text-slate-500 dark:text-slate-400 mb-1">
          Model note
        </p>
        <p className="text-sm text-slate-700 dark:text-slate-300">
          {MODEL_NOTE_LABEL[model_note]}.
        </p>
      </div>
    </section>
  )
}

interface ValuationCardProps {
  label: string
  subLabel: string
  rate: string
  value: number | null
  emphasised?: boolean
}

function ValuationCard({
  label,
  subLabel,
  rate,
  value,
  emphasised = false,
}: ValuationCardProps) {
  return (
    <div
      className={`rounded-xl border px-4 py-4 ${
        emphasised
          ? "border-rose-300 dark:border-rose-700 bg-white/60 dark:bg-slate-900/60"
          : "border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/40"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2 mb-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">
          {label}
        </p>
        <p className="text-[11px] text-slate-500 dark:text-slate-400">
          {subLabel}
        </p>
      </div>
      <p
        className={`num text-2xl font-semibold tabular-nums ${
          emphasised
            ? "text-rose-700 dark:text-rose-300"
            : "text-slate-900 dark:text-slate-100"
        }`}
      >
        {formatRupee(value)}
      </p>
      <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{rate}</p>
    </div>
  )
}

interface DistortionStripProps {
  distortionPct: number
  nominalFv: number | null
  realFv: number | null
}

function DistortionStrip({
  distortionPct,
  nominalFv,
  realFv,
}: DistortionStripProps) {
  // Hide the strip entirely when either side is missing — there is no
  // meaningful comparison to render.
  if (nominalFv == null || realFv == null) {
    return (
      <p className="text-xs text-slate-500 dark:text-slate-400 italic">
        Real-terms recompute not available for this ticker — the spread
        between nominal WACC and growth is too narrow in this regime to
        return a stable Gordon-model value.
      </p>
    )
  }

  const abs = Math.abs(distortionPct)
  let bandClass = "bg-slate-200 dark:bg-slate-700"
  let textClass = "text-slate-700 dark:text-slate-300"
  if (abs >= 20) {
    bandClass = "bg-rose-200 dark:bg-rose-900/60"
    textClass = "text-rose-800 dark:text-rose-300"
  } else if (abs >= 10) {
    bandClass = "bg-amber-200 dark:bg-amber-900/60"
    textClass = "text-amber-800 dark:text-amber-300"
  } else if (abs >= 3) {
    bandClass = "bg-sky-100 dark:bg-sky-900/40"
    textClass = "text-sky-800 dark:text-sky-300"
  }

  return (
    <div className={`rounded-lg px-3 py-2 ${bandClass}`}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className={`text-xs font-semibold uppercase tracking-wide ${textClass}`}>
          Real vs nominal gap
        </p>
        <p className={`text-base font-semibold tabular-nums ${textClass}`}>
          {signedPct(distortionPct)}
        </p>
      </div>
      <p className="text-xs text-slate-700 dark:text-slate-300 mt-1">
        Real-terms FV is {signedPct(distortionPct)} relative to the nominal
        DCF. Gaps under 10% are noise; 10–20% indicates meaningful regime
        drag; 20%+ means the nominal model is structurally mis-pricing the
        cash-flow trajectory.
      </p>
    </div>
  )
}
