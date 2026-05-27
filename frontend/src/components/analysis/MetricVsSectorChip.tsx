// frontend/src/components/analysis/MetricVsSectorChip.tsx
//
// Inline "metric vs sector median" chip — Tickertape density trick #2
// (audit .audit/tickertape-deep-walk-2026-05-27.md, gap: 0 chips above
// the fold). Renders the form:
//
//     ROE 22.4% · Sector 18.0%   [+24% vs sector]
//
// The delta chip is colour-coded by the `format` prop. PE / PB are
// "better-lower" (a value below the sector median renders green); ROE,
// dividend yield, operating margin are "better-higher" (above-median
// renders green). The chip is SEBI-safe by construction — copy is
// purely descriptive ("vs sector"), no advisory verbs.
//
// Self-hides when either `value` or `sectorMedian` is null/non-finite,
// so the caller can pass through raw API fields without conditional
// wrapping at every call site.

import React from "react"

export type ChipFormat = "better-lower" | "better-higher"
export type ChipUnit = "x" | "%" | "₹"

interface Props {
  /** Short label rendered before the value, e.g. "ROE", "P/E", "Yield". */
  label: string
  /** Raw metric value. null / NaN hides the chip entirely. */
  value: number | null | undefined
  /** Unit suffix appended to value and sector-median numbers. */
  unit?: ChipUnit
  /** Sector cohort median. null / NaN hides the chip entirely. */
  sectorMedian: number | null | undefined
  /**
   * Direction of "good" for this metric. PE/PB are better-lower;
   * ROE / yield / margins are better-higher. Drives the colour on
   * the trailing delta pill only — never the headline number.
   */
  format?: ChipFormat
  /** Optional className for layout overrides on the outer span. */
  className?: string
}

// One decimal for percentages and multiples (matches the rest of the
// analysis page); zero decimals for rupee amounts since those are
// typically large enough that decimals add noise.
function formatNumber(value: number, unit: ChipUnit | undefined): string {
  if (unit === "₹") {
    return value >= 100 ? value.toFixed(0) : value.toFixed(1)
  }
  return value.toFixed(1)
}

function formatWithUnit(value: number, unit: ChipUnit | undefined): string {
  const n = formatNumber(value, unit)
  if (unit === "%") return `${n}%`
  if (unit === "x") return `${n}x`
  if (unit === "₹") return `₹${n}`
  return n
}

function formatDeltaPct(deltaPct: number): string {
  // Always show a sign so "+22% vs sector" reads cleanly. The minus
  // sign already prefixes negative numbers via toFixed(); we add a
  // plus for non-negative to match Bloomberg/Tickertape convention.
  const rounded = Math.round(deltaPct)
  if (rounded > 0) return `+${rounded}%`
  if (rounded < 0) return `${rounded}%`
  return "0%"
}

function isUsableNumber(v: number | null | undefined): v is number {
  return v !== null && v !== undefined && Number.isFinite(v)
}

export default function MetricVsSectorChip({
  label,
  value,
  unit = "%",
  sectorMedian,
  format = "better-higher",
  className = "",
}: Props) {
  // Hide the chip entirely when either side is missing — never render
  // "vs sector —" (per spec).
  if (!isUsableNumber(value) || !isUsableNumber(sectorMedian)) return null

  // Delta math: percentage difference vs the sector median. Guard
  // against a zero median (very rare in practice but would otherwise
  // produce Infinity / NaN — we collapse to a neutral "—" delta and
  // still render the headline pair so the user gets the context).
  let deltaLabel: string | null = null
  let deltaTone: "green" | "red" | "neutral" = "neutral"
  if (sectorMedian !== 0) {
    const deltaPct = ((value - sectorMedian) / Math.abs(sectorMedian)) * 100
    deltaLabel = `${formatDeltaPct(deltaPct)} vs sector`
    // Direction of "good" for this metric.
    const valueAbove = value > sectorMedian
    if (format === "better-lower") {
      deltaTone = valueAbove ? "red" : "green"
    } else {
      deltaTone = valueAbove ? "green" : "red"
    }
    // A near-zero delta (< 2% absolute) is reported neutrally so we
    // don't paint trivial differences as wins / losses.
    if (Math.abs(deltaPct) < 2) deltaTone = "neutral"
  }

  const toneClass =
    deltaTone === "green"
      ? "text-emerald-700 bg-emerald-50 dark:text-emerald-300 dark:bg-emerald-950"
      : deltaTone === "red"
        ? "text-rose-700 bg-rose-50 dark:text-rose-300 dark:bg-rose-950"
        : "text-caption bg-surface"

  return (
    <span
      className={`inline-flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs ${className}`}
      aria-label={`${label} ${formatWithUnit(value, unit)} versus sector median ${formatWithUnit(sectorMedian, unit)}`}
      data-testid="metric-vs-sector-chip"
    >
      <span className="text-ink font-medium tabular-nums">
        {label} {formatWithUnit(value, unit)}
      </span>
      <span className="text-caption" aria-hidden="true">
        ·
      </span>
      <span className="text-caption tabular-nums">
        Sector {formatWithUnit(sectorMedian, unit)}
      </span>
      {deltaLabel && (
        <span
          className={`ml-1 rounded-full px-2 py-[1px] text-[10px] font-medium tabular-nums ${toneClass}`}
        >
          {deltaLabel}
        </span>
      )}
    </span>
  )
}
