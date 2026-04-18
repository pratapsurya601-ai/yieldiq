"use client"

import { useEffect, useMemo, useState } from "react"
import {
  HEX_AXIS_ORDER,
  type HexAxisKey,
  type HexResponse,
} from "@/lib/hex"

interface HexProps {
  data: HexResponse
  size?: number
  sectorOverlay?: boolean
  onAxisTap?: (axis: HexAxisKey) => void
}

const AXIS_LABEL: Record<HexAxisKey, string> = {
  value: "Value",
  quality: "Quality",
  growth: "Growth",
  moat: "Moat",
  safety: "Safety",
  pulse: "Pulse",
}

/**
 * Return the [x, y] coordinate on a circle of radius `r` centred at
 * (cx, cy) for vertex index `i` (0 = top, clockwise).
 */
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

export default function Hex({
  data,
  size = 240,
  sectorOverlay = false,
  onAxisTap,
}: HexProps) {
  const cx = size / 2
  const cy = size / 2
  // Leave room for axis labels outside the hex.
  const maxRadius = size / 2 - 28

  const axes = HEX_AXIS_ORDER.map((key) => data.axes[key])
  const scores = axes.map((a) => Math.max(0, Math.min(10, a.score)))

  // Animate from 0 -> score on mount.
  const [t, setT] = useState(0)
  useEffect(() => {
    // Small delay so the transform transition can catch the change.
    const id = requestAnimationFrame(() => setT(1))
    return () => cancelAnimationFrame(id)
  }, [data.ticker])

  // Concentric grid rings at scores 2/4/6/8/10.
  const gridPolys = useMemo(() => {
    return [2, 4, 6, 8, 10].map((s) => {
      const r = (s / 10) * maxRadius
      const pts = Array.from({ length: 6 }, (_, i) =>
        vertex(cx, cy, r, i).join(","),
      ).join(" ")
      return { score: s, pts }
    })
  }, [cx, cy, maxRadius])

  // Spokes from centre to each outer vertex.
  const spokes = useMemo(() => {
    return Array.from({ length: 6 }, (_, i) => {
      const [x, y] = vertex(cx, cy, maxRadius, i)
      return { x, y }
    })
  }, [cx, cy, maxRadius])

  // Main polygon points (animated via `t`).
  const mainPoints = scores
    .map((s, i) => {
      const r = (s / 10) * maxRadius * t
      return vertex(cx, cy, r, i).join(",")
    })
    .join(" ")

  // Sector median polygon.
  const medianPoints = HEX_AXIS_ORDER.map((key, i) => {
    const m = Math.max(0, Math.min(10, data.sector_medians?.[key] ?? 0))
    const r = (m / 10) * maxRadius * t
    return vertex(cx, cy, r, i).join(",")
  }).join(" ")

  // Label positions (slightly outside the hex).
  const labels = HEX_AXIS_ORDER.map((key, i) => {
    const [x, y] = vertex(cx, cy, maxRadius + 16, i)
    return { key, x, y, text: AXIS_LABEL[key].toUpperCase() }
  })

  // Vertex pills.
  const vertexPills = HEX_AXIS_ORDER.map((key, i) => {
    const score = scores[i]
    const r = (score / 10) * maxRadius * t
    const [x, y] = vertex(cx, cy, r, i)
    return {
      key,
      x,
      y,
      score,
      dataLimited: data.axes[key].data_limited,
      delayMs: i * 50,
    }
  })

  const overall = Math.max(0, Math.min(10, data.overall))

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`Hex score for ${data.ticker}: ${overall.toFixed(1)}/10`}
        style={{
          overflow: "visible",
          transition: "opacity 600ms ease-out",
        }}
      >
        <title>
          Hex score for {data.ticker}: {overall.toFixed(1)}/10
        </title>

        {/* Grid rings */}
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

        {/* Spokes */}
        <g style={{ stroke: "var(--color-border)", strokeOpacity: 0.5 }}>
          {spokes.map((s, i) => (
            <line key={i} x1={cx} y1={cy} x2={s.x} y2={s.y} strokeWidth={1} />
          ))}
        </g>

        {/* Sector median overlay */}
        {sectorOverlay && (
          <polygon
            points={medianPoints}
            fill="none"
            strokeDasharray="4 3"
            strokeWidth={1.5}
            style={{
              stroke: "var(--color-caption)",
              transition: "all 600ms ease-out",
            }}
          />
        )}

        {/* Main polygon */}
        <polygon
          points={mainPoints}
          strokeWidth={2}
          style={{
            stroke: "var(--color-brand)",
            fill: "var(--color-brand)",
            fillOpacity: 0.15,
            transition: "all 600ms ease-out",
          }}
        />

        {/* Axis labels */}
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

        {/* Vertex pills (tap targets) */}
        <g>
          {vertexPills.map((p) => {
            const fill = p.dataLimited
              ? "var(--color-caption)"
              : "var(--color-brand)"
            return (
              <g
                key={p.key}
                role="button"
                tabIndex={onAxisTap ? 0 : -1}
                aria-label={`${AXIS_LABEL[p.key]} score ${p.score.toFixed(1)} out of 10`}
                onClick={() => onAxisTap?.(p.key)}
                onKeyDown={(e) => {
                  if (onAxisTap && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault()
                    onAxisTap(p.key)
                  }
                }}
                style={{
                  cursor: onAxisTap ? "pointer" : "default",
                  transition: `transform 600ms ease-out ${p.delayMs}ms`,
                }}
              >
                {/* Invisible 44×44 tap area for accessibility */}
                <rect
                  x={p.x - 22}
                  y={p.y - 22}
                  width={44}
                  height={44}
                  fill="transparent"
                />
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={11}
                  style={{ fill, transition: "fill 300ms ease" }}
                />
                <text
                  x={p.x}
                  y={p.y}
                  textAnchor="middle"
                  dominantBaseline="central"
                  className="font-mono"
                  style={{
                    fill: "#ffffff",
                    fontSize: 10,
                    fontWeight: 600,
                  }}
                >
                  {p.score.toFixed(1)}
                </text>
              </g>
            )
          })}
        </g>
      </svg>

      {/* Centre overall score */}
      <div
        className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none"
        aria-hidden="true"
      >
        <span
          className="font-mono tabular-nums font-bold"
          style={{ fontSize: 32, color: "var(--color-ink)", lineHeight: 1 }}
        >
          {overall.toFixed(1)}
        </span>
        <span
          className="font-mono"
          style={{ fontSize: 12, color: "var(--color-caption)", marginTop: 2 }}
        >
          /10
        </span>
      </div>
    </div>
  )
}
