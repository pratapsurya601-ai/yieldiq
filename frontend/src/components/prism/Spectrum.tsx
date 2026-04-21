"use client"

import { motion, useReducedMotion } from "framer-motion"
import type { Pillar, PillarKey, VerdictBand } from "./types"
import { pillarColor, verdictColor, PRISM_PILLAR_ORDER } from "@/lib/prism"

interface Props {
  pillars: Pillar[]
  overall: number
  pulseHz: number
  size: number
  /** Morph progress: 0 = Signature, 1 = Spectrum. */
  t: number
  verdictBand: VerdictBand
  verdictLabel: string
  sectorOverlay?: boolean
  sectorMedians?: Partial<Record<PillarKey, number>>
  onPillarTap?: (key: PillarKey) => void
  /** Phase 2: dim every non-matching lens to ~30% when set. */
  highlightedPillar?: PillarKey | null
  uid: string
  /** When true, play initial entrance animations on mount. */
  firstView?: boolean
}

/**
 * For axis i (0..5, top-to-bottom), return the vertical center of its lens
 * on a canvas of `size`. We reserve top 12% for the input-beam caption and
 * bottom 18% for the convergence point, so lenses stack inside 70% of height.
 */
export function spectrumLensY(size: number, i: number): number {
  const top = size * 0.16
  const bottom = size * 0.78
  return top + ((bottom - top) * i) / 5
}

const AXIS_LABEL: Record<PillarKey, string> = {
  value: "VALUE",
  quality: "QUALITY",
  growth: "GROWTH",
  moat: "MOAT",
  safety: "SAFETY",
  pulse: "PULSE",
}

/**
 * Spectrum (linear prism) renderer. Fades IN between t=0.55 and t=1.0 so
 * it never overlaps visually with Signature during the morph window.
 */
export default function Spectrum({
  pillars,
  overall,
  size,
  t,
  verdictBand,
  verdictLabel,
  onPillarTap,
  highlightedPillar,
  firstView = false,
}: Props) {
  const cx = size / 2
  const lensMaxW = size - 100 // leave 50px margin each side for labels

  const prefersReducedMotion = useReducedMotion()
  const animationsEnabled = firstView && !prefersReducedMotion

  const vis = Math.max(0, (t - 0.55) / 0.45)
  if (vis <= 0) return null

  const ordered = PRISM_PILLAR_ORDER.map(
    (k) => pillars.find((p) => p.key === k)!,
  )

  const inputBeamY = size * 0.08
  const outputY = size * 0.9

  return (
    <g style={{ opacity: vis, transition: "opacity 200ms linear" }}>
      {/* Input beam — thin rect with caption. */}
      <rect
        x={cx - lensMaxW / 2}
        y={inputBeamY - 3}
        width={lensMaxW}
        height={3}
        fill="var(--color-caption)"
        opacity={0.4}
      />
      <text
        x={cx}
        y={inputBeamY - 8}
        textAnchor="middle"
        style={{
          fill: "var(--color-caption)",
          fontSize: 9,
          fontWeight: 600,
          letterSpacing: "0.12em",
          fontFamily:
            "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
        }}
      >
        RAW DATA
      </text>

      {/* Convergence rays — behind the lens trapezoids. */}
      <g>
        {ordered.map((p, i) => {
          if (p.score == null) return null
          const y = spectrumLensY(size, i)
          const startX = cx
          const startY = y + 8 // from lens bottom-center
          const strokeW = Math.max(0.8, p.weight * 10)
          // Curved ray toward output: simple quadratic bezier with control
          // point at the midway vertical line to create a gentle convergence.
          const midY = (startY + outputY) / 2
          const d = `M ${startX} ${startY} Q ${cx + (startX - cx) * 0.3} ${midY} ${cx} ${outputY}`
          return (
            <path
              key={p.key}
              d={d}
              fill="none"
              stroke={p.data_limited ? "var(--color-caption)" : pillarColor(p.key)}
              strokeWidth={strokeW}
              strokeOpacity={0.55}
              strokeLinecap="round"
            />
          )
        })}
      </g>

      {/* Lens trapezoids — width ∝ score. */}
      <g>
        {ordered.map((p, i) => {
          const y = spectrumLensY(size, i)
          const s = p.score == null ? 0 : Math.max(0, Math.min(10, p.score))
          const halfW = (s / 10) * (lensMaxW / 2)
          const color = p.data_limited
            ? "var(--color-caption)"
            : pillarColor(p.key)
          const isPulse = p.key === "pulse"
          const spotlightOn = highlightedPillar != null
          const isSpotlit = spotlightOn && highlightedPillar === p.key
          const lensOpacity = !spotlightOn || isSpotlit ? 1 : 0.3
          // Trapezoid: wider at top, narrower at bottom — light refracting.
          const path = `M ${cx - halfW} ${y - 8} L ${cx + halfW} ${y - 8} L ${cx + halfW * 0.75} ${y + 8} L ${cx - halfW * 0.75} ${y + 8} Z`
          // Subtle fade-in stagger for each lens row on first mount.
          const entrance = animationsEnabled
            ? {
                initial: { opacity: 0, y: 4 },
                animate: { opacity: lensOpacity, y: 0 },
                transition: {
                  delay: 0.1 + i * 0.05,
                  duration: 0.35,
                  ease: "easeOut" as const,
                },
              }
            : {
                initial: false as const,
                animate: { opacity: lensOpacity },
                transition: { duration: 0.24, ease: "easeOut" as const },
              }
          return (
            <motion.g
              key={p.key}
              role="button"
              tabIndex={onPillarTap ? 0 : -1}
              aria-label={`${p.key} score ${
                p.data_limited ? "not available" : s.toFixed(1)
              } out of 10`}
              onClick={() => onPillarTap?.(p.key)}
              onKeyDown={(e) => {
                if (onPillarTap && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault()
                  onPillarTap(p.key)
                }
              }}
              {...entrance}
              style={{
                cursor: onPillarTap ? "pointer" : "default",
              }}
              className={isPulse ? "prism-pulse-breathe" : undefined}
            >
              <path
                d={path}
                fill={color}
                fillOpacity={p.data_limited ? 0.25 : 0.65}
                stroke={color}
                strokeWidth={1.5}
              />
              {/* Pillar label — left, horizontal. */}
              <text
                x={cx - lensMaxW / 2 - 6}
                y={y}
                textAnchor="end"
                dominantBaseline="central"
                style={{
                  fill: color,
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.08em",
                  fontFamily:
                    "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
                }}
              >
                {AXIS_LABEL[p.key]}
              </text>
              {/* Score — right. */}
              <text
                x={cx + lensMaxW / 2 + 6}
                y={y}
                textAnchor="start"
                dominantBaseline="central"
                style={{
                  fill: p.data_limited ? "var(--color-caption)" : "var(--color-ink)",
                  fontSize: 10,
                  fontWeight: 800,
                  fontFamily:
                    "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
                }}
              >
                {p.data_limited ? "n/a" : `${s.toFixed(1)} /10`}
              </text>
            </motion.g>
          )
        })}
      </g>

      {/* Output composite + verdict pill.
          FIX (prism-five-five): render the score as three distinct
          <tspan>s (integer / U+002E / fraction) so the decimal point
          can never kern or font-substitute into something that reads
          as ":". Matches the central composite in Signature.tsx. */}
      <g>
        <circle
          cx={cx}
          cy={outputY}
          r={4}
          fill={verdictColor(verdictBand)}
        />
        <text
          x={cx}
          y={outputY + 18}
          textAnchor="middle"
          style={{
            fill: "var(--color-ink)",
            fontSize: Math.round(size * 0.08),
            fontWeight: 800,
            fontFamily:
              "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
          }}
        >
          {(() => {
            if (!Number.isFinite(overall)) return "\u2014"
            const clamped = Math.max(0, Math.min(10, overall))
            const rounded = Math.round(clamped * 10) / 10
            const whole = Math.floor(rounded)
            const frac = Math.round((rounded - whole) * 10)
            return (
              <>
                <tspan>{whole}</tspan>
                <tspan dx="0.02em">{"\u002E"}</tspan>
                <tspan dx="0.02em">{frac}</tspan>
              </>
            )
          })()}
        </text>
        <text
          x={cx}
          y={outputY + 18 + Math.round(size * 0.06)}
          textAnchor="middle"
          style={{
            fill: verdictColor(verdictBand),
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.12em",
            fontFamily:
              "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
          }}
        >
          {verdictLabel.toUpperCase()}
        </text>
      </g>
    </g>
  )
}
