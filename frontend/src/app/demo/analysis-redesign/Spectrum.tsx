"use client"

// C · The Spectrum (locked §7.2) — RAW beam → prism diamond → six
// refraction trapezoid bands (width = score/10) → centre thread → core
// number + region label. Unfold choreography is driven by the parent
// DecisionBox stage clock so the whole hero fires as one sequence.
import { useState } from "react"

import {
  SPECTRUM_AXES,
  SPECTRUM_OVERALL,
  SPECTRUM_REGION,
} from "./data"
import { backOut, seg } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"

const SCX = 300
const SMAXW = 360
const SBH = 26
const SROW0 = 78
const SGAP = 52
const CORE_Y = SROW0 + 5 * SGAP + SBH + 28 // 392

function rowY(i: number): number {
  return SROW0 + i * SGAP
}

function trap(cx: number, y: number, w: number): string {
  const bw = w * 0.82
  return `M${(cx - w / 2).toFixed(1)},${y.toFixed(1)} L${(cx + w / 2).toFixed(1)},${y.toFixed(1)} L${(cx + bw / 2).toFixed(1)},${(y + SBH).toFixed(1)} L${(cx - bw / 2).toFixed(1)},${(y + SBH).toFixed(1)} Z`
}

export default function Spectrum({
  elapsed,
  selected,
  onSelect,
  peerOn,
}: {
  elapsed: number
  selected: number | null
  onSelect: (i: number) => void
  peerOn: boolean
}) {
  const [hovered, setHovered] = useState<number | null>(null)

  // RAW beam draws in, then bands refract open top-to-bottom.
  const beamX2 = 60 + (SCX - 60) * seg(elapsed, 0, 450)

  // Centre thread stitches down band-by-band, then to the core.
  const lastBandY = rowY(5) + SBH + 10
  const p1 = seg(elapsed, 450, 1050)
  const p2 = seg(elapsed, 1900, 350)
  const threadY2 = p2 > 0 ? lastBandY + (CORE_Y - lastBandY) * p2 : 53 + (lastBandY - 53) * p1

  const coreCount = SPECTRUM_OVERALL * seg(elapsed, 1900, 600)
  const coreSettled = elapsed >= 2500

  const fillOpacity = (i: number): number => {
    if (hovered !== null) return hovered === i ? 0.8 : 0.32
    return selected === i ? 0.8 : 0.55
  }

  return (
    <svg
      viewBox="0 0 560 470"
      width="100%"
      style={{ maxWidth: 470 }}
      role="img"
      aria-label="Spectrum refraction: pulse 5.4, quality 7.2, moat 8.5, safety 7.9, growth 6.0, value 7.8, overall 7.2 in the value region."
      className="mx-auto block"
    >
      {/* RAW beam + prism diamond */}
      <line x1={60} y1={44} x2={beamX2} y2={44} stroke={TOKENS.border} strokeWidth={2.5} />
      <text x={60} y={34} fontSize={9.5} letterSpacing={2} fill={TOKENS.caption}>
        RAW
      </text>
      <rect
        x={SCX - 9}
        y={35}
        width={18}
        height={18}
        rx={3}
        transform={`rotate(45 ${SCX} 44)`}
        fill={TOKENS.surface}
        stroke={TOKENS.caption}
        strokeWidth={1.5}
      />

      {/* Centre thread */}
      <line x1={SCX} y1={53} x2={SCX} y2={Math.max(53, threadY2)} stroke={TOKENS.caption} strokeWidth={1.2} opacity={0.55} />

      {/* Peer overlay (dashed outline bands, one peer at a time) */}
      {SPECTRUM_AXES.map((a, i) => (
        <path
          key={`peer-${a.k}`}
          d={trap(SCX, rowY(i), (a.peer / 10) * SMAXW)}
          fill="none"
          stroke={TOKENS.caption}
          strokeWidth={1.2}
          strokeDasharray="4 3"
          opacity={peerOn ? 0.8 : 0}
          style={{ transition: "opacity .4s" }}
        />
      ))}

      {/* Refraction bands */}
      {SPECTRUM_AXES.map((a, i) => {
        const unfold = seg(elapsed, 450 + i * 150, 700, backOut)
        const settled = elapsed >= 450 + i * 150 + 700
        const w = settled ? (a.s / 10) * SMAXW : Math.max(0.5, (a.s / 10) * SMAXW * unfold)
        const labelOp = settled ? 1 : 0
        const medianX = SCX + ((a.m / 10) * SMAXW) / 2
        const breathing = i === 0 && hovered === null && selected !== 0
        return (
          <g key={a.k}>
            <path
              d={trap(SCX, rowY(i), w)}
              fill={a.c}
              fillOpacity={fillOpacity(i)}
              stroke={a.c}
              strokeWidth={selected === i ? 2.4 : 1.5}
              strokeLinejoin="round"
              className={breathing ? "demo-breathe" : undefined}
              style={{ cursor: "pointer", transition: "fill-opacity .2s" }}
              role="button"
              tabIndex={0}
              aria-label={`${a.k} ${a.s.toFixed(1)} out of 10 — tap to inspect`}
              onClick={() => onSelect(i)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  onSelect(i)
                }
              }}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
            >
              <title>{`${a.k} — sector median ${a.m.toFixed(1)}`}</title>
            </path>
            {/* sector-median tick (vertical, never slanted) */}
            <line
              x1={medianX}
              y1={rowY(i) + 3}
              x2={medianX}
              y2={rowY(i) + SBH - 3}
              stroke={TOKENS.caption}
              strokeWidth={2}
              opacity={settled ? 0.7 : 0}
              style={{ transition: "opacity .5s" }}
            />
            <text
              x={104}
              y={rowY(i) + SBH / 2 + 4}
              textAnchor="end"
              fontSize={11}
              letterSpacing={1.5}
              fontWeight={500}
              fill={a.d}
              opacity={labelOp}
              style={{ cursor: "pointer", transition: "opacity .4s" }}
              onClick={() => onSelect(i)}
            >
              {a.k}
            </text>
            <text
              x={498}
              y={rowY(i) + SBH / 2 + 4}
              fontSize={12.5}
              fontWeight={500}
              fill={TOKENS.ink}
              opacity={labelOp}
              className="num"
              style={{ transition: "opacity .4s" }}
            >
              {a.s.toFixed(1)} /10
            </text>
          </g>
        )
      })}

      {/* Core */}
      <circle cx={SCX} cy={CORE_Y} r={4} fill={DEMO_COLORS.teal} opacity={elapsed >= 2250 ? 1 : 0} style={{ transition: "opacity .4s" }} />
      <text x={SCX} y={CORE_Y + 36} textAnchor="middle" fontSize={30} fontWeight={500} fill={TOKENS.ink} className="num">
        {coreCount > 0 ? coreCount.toFixed(1) : ""}
      </text>
      <text
        x={SCX}
        y={CORE_Y + 56}
        textAnchor="middle"
        fontSize={11}
        letterSpacing={2.5}
        fontWeight={500}
        fill={DEMO_COLORS.tealDark}
        opacity={coreSettled ? 1 : 0}
        style={{ transition: "opacity .5s" }}
      >
        {SPECTRUM_REGION}
      </text>
    </svg>
  )
}
