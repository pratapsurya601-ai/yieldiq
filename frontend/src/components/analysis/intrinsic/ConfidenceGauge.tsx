"use client"

/**
 * ConfidenceGauge — compact circular confidence meter for
 * "1. INTRINSIC VALUE" (feat/intrinsic-value-thesis-redesign).
 *
 * Replaces the plain "conf 90%" text treatment with:
 *   - an SVG arc gauge (animated 800ms sweep, count-up center number),
 *   - three mini-bars beside it: Model confidence / Data quality /
 *     Valuation stability (the third pillar is valuation_stability_score
 *     — labelled by its real name; the Monte-Carlo sensitivity pillar is
 *     null for banks and holdcos so it is not surfaced here).
 *
 * The whole block links to the existing "Confidence and methodology"
 * disclosure (`#section-confidence`) and force-opens that <details>
 * element on activation.
 *
 * Self-hides when the overall score and every pillar are null — no
 * fabricated zeros. Reduced motion: the arc renders at its final sweep
 * and the number renders without the count-up.
 */

import * as React from "react"
import { motion } from "framer-motion"

import { NumberFlip } from "@/components/motion"
import { useInViewOnce } from "@/components/anim/useInViewOnce"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { cn } from "@/lib/utils"

export interface ConfidenceGaugePillars {
  model_confidence?: number | null
  data_quality?: number | null
  valuation_stability?: number | null
}

export interface ConfidenceGaugeProps {
  /** Overall model confidence 0-100 (valuation.confidence_score). */
  confidence?: number | null
  pillars?: ConfidenceGaugePillars | null
  className?: string
}

const num = (v: number | null | undefined): v is number =>
  v != null && Number.isFinite(v)

const clamp100 = (v: number) => Math.min(100, Math.max(0, v))

const R = 40
const CIRCUMFERENCE = 2 * Math.PI * R

const PILLAR_ROWS: Array<{
  key: keyof ConfidenceGaugePillars
  label: string
}> = [
  { key: "model_confidence", label: "Model confidence" },
  { key: "data_quality", label: "Data quality" },
  { key: "valuation_stability", label: "Valuation stability" },
]

export default function ConfidenceGauge({
  confidence,
  pillars,
  className,
}: ConfidenceGaugeProps) {
  const reduced = useReducedMotion()
  const { ref, inView } = useInViewOnce<HTMLAnchorElement>(0.2)

  const rows = PILLAR_ROWS.map((r) => ({
    ...r,
    value: num(pillars?.[r.key]) ? clamp100(pillars![r.key] as number) : null,
  })).filter((r) => r.value != null) as Array<{
    key: keyof ConfidenceGaugePillars
    label: string
    value: number
  }>

  const overall = num(confidence)
    ? clamp100(confidence)
    : rows.length > 0
      ? rows.reduce((s, r) => s + r.value, 0) / rows.length
      : null

  if (overall == null && rows.length === 0) return null

  const sweep = overall ?? 0
  const targetOffset = CIRCUMFERENCE * (1 - sweep / 100)
  const animateArc = !reduced && inView

  const openDisclosure = () => {
    if (typeof document === "undefined") return
    const el = document.getElementById("section-confidence")
    if (el instanceof HTMLDetailsElement) el.open = true
  }

  return (
    <a
      ref={ref}
      href="#section-confidence"
      onClick={openDisclosure}
      data-testid="iv-confidence-gauge"
      aria-label="Model confidence — open the confidence and methodology details"
      className={cn(
        "group flex items-center gap-4 rounded-xl border border-border bg-surface/60 p-4",
        "transition-shadow hover:shadow-md focus-visible:ring-2 focus-visible:ring-brand/50 outline-none",
        className,
      )}
    >
      {overall != null && (
        <div className="relative h-24 w-24 shrink-0">
          <svg viewBox="0 0 96 96" className="h-24 w-24 -rotate-90">
            <circle
              cx="48"
              cy="48"
              r={R}
              fill="none"
              strokeWidth="7"
              className="stroke-border/60"
            />
            <motion.circle
              data-testid="iv-confidence-arc"
              cx="48"
              cy="48"
              r={R}
              fill="none"
              strokeWidth="7"
              strokeLinecap="round"
              className="stroke-brand"
              strokeDasharray={CIRCUMFERENCE}
              initial={
                reduced ? false : { strokeDashoffset: CIRCUMFERENCE }
              }
              animate={{
                strokeDashoffset: animateArc ? targetOffset : reduced ? targetOffset : CIRCUMFERENCE,
              }}
              transition={
                reduced
                  ? { duration: 0 }
                  : { duration: 0.8, ease: [0.22, 1, 0.36, 1] }
              }
              style={reduced ? { strokeDashoffset: targetOffset } : undefined}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span
              data-testid="iv-confidence-overall"
              className="font-mono tabular-nums text-xl font-bold text-ink leading-none"
            >
              <NumberFlip
                value={Math.round(overall)}
                duration={0.8}
                format={(n) => `${Math.round(n)}`}
              />
            </span>
            <span className="text-[9px] uppercase tracking-[0.12em] text-caption">
              / 100
            </span>
          </div>
        </div>
      )}

      <div className="min-w-0 flex-1">
        <p className="text-[11px] uppercase tracking-[0.12em] text-caption">
          Model confidence
        </p>
        <div className="mt-2 space-y-1.5">
          {rows.map((r, i) => (
            <div key={r.key} data-testid={`iv-confidence-pillar-${r.key}`}>
              <div className="flex items-baseline justify-between gap-3 text-[11px]">
                <span className="text-body truncate">{r.label}</span>
                <span className="font-mono tabular-nums font-semibold text-ink shrink-0">
                  {Math.round(r.value)}
                </span>
              </div>
              <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-border/50">
                <motion.div
                  className="h-full rounded-full bg-brand"
                  initial={reduced ? false : { width: 0 }}
                  animate={{ width: `${r.value}%` }}
                  transition={
                    reduced
                      ? { duration: 0 }
                      : {
                          duration: 0.5,
                          ease: [0.22, 1, 0.36, 1],
                          delay: 0.2 + i * 0.08,
                        }
                  }
                  style={reduced ? { width: `${r.value}%` } : undefined}
                />
              </div>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[10px] text-caption group-hover:text-body transition-colors">
          Methodology details →
        </p>
      </div>
    </a>
  )
}
