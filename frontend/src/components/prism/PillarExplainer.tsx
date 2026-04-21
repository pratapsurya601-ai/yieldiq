"use client"

/**
 * PillarExplainer — bottom-sheet modal that explains a single Prism
 * vertex (Value / Quality / Moat / etc.) in one factual sentence.
 *
 * The backend already stamps each axis with a `why` caption (e.g.
 * "MoS 84%" for a Value-10 stock). This component surfaces it when
 * the user taps a vertex. No AI, no fabrication — we show the same
 * string the hex engine produced.
 *
 * SEBI-compliance note: copy is strictly factual. We never say "good"
 * or "bad" — just restate the pillar's score + the reason, and the
 * peer comparison when sector_medians is populated.
 */

import { useEffect } from "react"
import type { Pillar, PillarKey, PrismData } from "./types"

interface PillarExplainerProps {
  open: boolean
  axis: PillarKey | null
  data: PrismData
  onClose: () => void
}

const AXIS_LABEL: Record<PillarKey, string> = {
  value: "Value",
  quality: "Quality",
  growth: "Growth",
  moat: "Moat",
  safety: "Safety",
  pulse: "Pulse",
}

function toneColor(
  label: string,
): string {
  const up = label.toUpperCase()
  if (up === "STRONG" || up === "POSITIVE") return "var(--color-success)"
  if (up === "WEAK" || up === "NEGATIVE") return "var(--color-danger)"
  return "var(--color-caption)"
}

export default function PillarExplainer({
  open,
  axis,
  data,
  onClose,
}: PillarExplainerProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open || !axis) return null

  const pillar: Pillar | undefined = data.pillars.find((p) => p.key === axis)
  if (!pillar) return null

  const median = data.sector_medians?.[axis] ?? null
  const color = toneColor(pillar.label)

  // Peer comparison — only when median is present AND differs from the
  // neutral 5.0 default (so we don't claim "in line with peers" when
  // sector medians haven't been computed yet).
  const medianIsRealData = median !== null && median !== 5
  let comparison: string | null = null
  if (medianIsRealData && pillar.score != null) {
    const delta = pillar.score - (median as number)
    if (delta > 0.5) {
      comparison = `Above the sector median (${median!.toFixed(1)}).`
    } else if (delta < -0.5) {
      comparison = `Below the sector median (${median!.toFixed(1)}).`
    } else {
      comparison = `In line with the sector median (${median!.toFixed(1)}).`
    }
  }

  const scoreDisplay =
    pillar.data_limited || pillar.score == null
      ? "data collecting"
      : `${pillar.score.toFixed(1)} / 10`

  return (
    <div
      className="fixed inset-0 z-50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pillar-explainer-title"
    >
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      <div
        className="
          absolute left-0 right-0 bottom-0 max-h-[85vh] overflow-y-auto
          bg-surface border-t border-border rounded-t-2xl p-5
          md:left-auto md:right-0 md:top-0 md:bottom-0 md:max-h-none md:w-[420px]
          md:border-l md:rounded-t-none
          animate-in slide-in-from-bottom md:slide-in-from-right
        "
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p
              className="text-[10px] uppercase tracking-[0.15em] font-semibold"
              style={{ color }}
            >
              {pillar.label}
            </p>
            <h3
              id="pillar-explainer-title"
              className="text-xl font-semibold text-ink mt-0.5"
            >
              {AXIS_LABEL[axis]}
            </h3>
            <p className="font-mono tabular-nums text-2xl font-bold mt-2" style={{ color }}>
              {scoreDisplay}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="shrink-0 w-8 h-8 rounded-full hover:bg-bg flex items-center justify-center text-caption text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* The one factual sentence — exactly what the backend shipped. */}
        <div className="mt-5 pt-4 border-t border-border">
          <p className="text-[10px] uppercase tracking-[0.12em] text-caption font-semibold">
            Why this score
          </p>
          <p className="text-sm text-ink mt-1.5 leading-relaxed">
            {pillar.why}
          </p>
        </div>

        {comparison && (
          <div className="mt-4 pt-4 border-t border-border">
            <p className="text-[10px] uppercase tracking-[0.12em] text-caption font-semibold">
              vs. sector
            </p>
            <p className="text-sm text-ink mt-1.5">{comparison}</p>
          </div>
        )}

        <p className="text-[11px] text-caption leading-relaxed mt-5">
          Model estimate. Not investment advice.
        </p>
      </div>
    </div>
  )
}
