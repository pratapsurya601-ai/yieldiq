"use client"

import { useEffect, useMemo, useState } from "react"
import { HEX_AXIS_ORDER, type HexResponse } from "@/lib/hex"

interface HexCompareProps {
  a: HexResponse
  b: HexResponse
  size?: number
}

// Fixed colors for the two overlays (brand blue for A, amber for B).
// Comparison requires two distinguishable hues — these map to brand + warning tokens.
const COLOR_A = "var(--color-brand)"
const COLOR_B = "var(--color-warning)"

function vertex(
  cx: number,
  cy: number,
  r: number,
  i: number,
  count = 6,
): [number, number] {
  const angle = -Math.PI / 2 + (i * 2 * Math.PI) / count
  return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)]
}

export default function HexCompare({ a, b, size = 280 }: HexCompareProps) {
  const cx = size / 2
  const cy = size / 2
  const maxRadius = size / 2 - 28

  const [t, setT] = useState(0)
  useEffect(() => {
    const id = requestAnimationFrame(() => setT(1))
    return () => cancelAnimationFrame(id)
  }, [a.ticker, b.ticker])

  const gridPolys = useMemo(() => {
    return [2, 4, 6, 8, 10].map((s) => {
      const r = (s / 10) * maxRadius
      const pts = Array.from({ length: 6 }, (_, i) =>
        vertex(cx, cy, r, i).join(","),
      ).join(" ")
      return { score: s, pts }
    })
  }, [cx, cy, maxRadius])

  const polyFor = (hex: HexResponse) =>
    HEX_AXIS_ORDER.map((key, i) => {
      const s = Math.max(0, Math.min(10, hex.axes[key].score))
      const r = (s / 10) * maxRadius * t
      return vertex(cx, cy, r, i).join(",")
    }).join(" ")

  const labels = HEX_AXIS_ORDER.map((key, i) => {
    const [x, y] = vertex(cx, cy, maxRadius + 16, i)
    return { key, x, y, text: key.toUpperCase() }
  })

  return (
    <div className="inline-flex flex-col items-center" style={{ width: size }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`Hex compare: ${a.ticker} vs ${b.ticker}`}
        style={{ overflow: "visible" }}
      >
        <title>
          Hex compare: {a.ticker} ({a.overall.toFixed(1)}) vs {b.ticker} (
          {b.overall.toFixed(1)})
        </title>

        <g style={{ stroke: "var(--color-border)", fill: "none" }}>
          {gridPolys.map((g) => (
            <polygon
              key={g.score}
              points={g.pts}
              strokeWidth={1}
              strokeOpacity={g.score === 10 ? 0.9 : 0.5}
            />
          ))}
        </g>

        <polygon
          points={polyFor(a)}
          strokeWidth={2}
          style={{
            stroke: COLOR_A,
            fill: COLOR_A,
            fillOpacity: 0.25,
            transition: "all 600ms ease-out",
          }}
        />
        <polygon
          points={polyFor(b)}
          strokeWidth={2}
          style={{
            stroke: COLOR_B,
            fill: COLOR_B,
            fillOpacity: 0.25,
            transition: "all 600ms ease-out",
          }}
        />

        <g
          className="font-mono"
          style={{
            fill: "var(--color-caption)",
            fontSize: 11,
            letterSpacing: "0.05em",
          }}
        >
          {labels.map((l) => (
            <text
              key={l.key}
              x={l.x}
              y={l.y}
              textAnchor="middle"
              dominantBaseline="middle"
            >
              {l.text}
            </text>
          ))}
        </g>
      </svg>

      <div
        className="mt-3 flex items-center gap-4"
        style={{ fontSize: 12, color: "var(--color-body)" }}
      >
        <LegendSwatch color={COLOR_A} label={a.ticker} score={a.overall} />
        <LegendSwatch color={COLOR_B} label={b.ticker} score={b.overall} />
      </div>
      <p
        className="mt-1 font-mono"
        style={{ fontSize: 10, color: "var(--color-caption)" }}
      >
        Model estimate
      </p>
    </div>
  )
}

function LegendSwatch({
  color,
  label,
  score,
}: {
  color: string
  label: string
  score: number
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        aria-hidden="true"
        style={{
          width: 12,
          height: 12,
          borderRadius: 3,
          background: color,
          opacity: 0.85,
        }}
      />
      <span className="font-semibold">{label}</span>
      <span
        className="font-mono tabular-nums"
        style={{ color: "var(--color-caption)" }}
      >
        {score.toFixed(1)}/10
      </span>
    </span>
  )
}
