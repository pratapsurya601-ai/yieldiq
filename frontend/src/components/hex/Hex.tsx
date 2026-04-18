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
 * Score → semantic color. We do this client-side (rather than trusting
 * the backend label) so the visual is consistent across locales and
 * even when `data_limited` axes degrade to grey.
 *
 *   >= 7.5 → success (green)
 *   >= 4.5 → warning (amber)
 *   else   → danger  (red)
 */
function scoreColor(score: number, limited?: boolean): string {
  if (limited) return "var(--color-caption)"
  if (score >= 7.5) return "var(--color-success)"
  if (score >= 4.5) return "var(--color-warning)"
  return "var(--color-danger)"
}

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
  // Leave room for axis labels + glow outside the hex.
  const maxRadius = size / 2 - 34

  const axes = HEX_AXIS_ORDER.map((key) => data.axes[key])
  const scores = axes.map((a) => Math.max(0, Math.min(10, a.score)))

  // Animate from 0 -> score on mount. Springy timing handled in CSS
  // via cubic-bezier on the polygon points & vertex positions.
  const [t, setT] = useState(0)
  useEffect(() => {
    const id = requestAnimationFrame(() => setT(1))
    return () => cancelAnimationFrame(id)
  }, [data.ticker])

  // Unique gradient IDs per instance so multiple hexes on one page
  // don't collide.
  const gid = useMemo(() => `hex-${data.ticker.replace(/[^a-z0-9]/gi, "")}`, [
    data.ticker,
  ])

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

  const mainPoints = scores
    .map((s, i) => {
      const r = (s / 10) * maxRadius * t
      return vertex(cx, cy, r, i).join(",")
    })
    .join(" ")

  const medianPoints = HEX_AXIS_ORDER.map((key, i) => {
    const m = Math.max(0, Math.min(10, data.sector_medians?.[key] ?? 0))
    const r = (m / 10) * maxRadius * t
    return vertex(cx, cy, r, i).join(",")
  }).join(" ")

  // Labels sit slightly outside the hex.
  const labels = HEX_AXIS_ORDER.map((key, i) => {
    const [x, y] = vertex(cx, cy, maxRadius + 20, i)
    return { key, x, y, text: AXIS_LABEL[key].toUpperCase() }
  })

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
      delayMs: i * 60,
    }
  })

  const overall = Math.max(0, Math.min(10, data.overall))
  const overallColor = scoreColor(overall)

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
        style={{ overflow: "visible" }}
      >
        <title>
          Hex score for {data.ticker}: {overall.toFixed(1)}/10
        </title>

        <defs>
          {/* Radial gradient for the main polygon fill — denser near centre. */}
          <radialGradient id={`${gid}-fill`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--color-brand)" stopOpacity="0.45" />
            <stop offset="70%" stopColor="var(--color-brand)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--color-brand)" stopOpacity="0.08" />
          </radialGradient>

          {/* Soft ambient glow behind the hex. */}
          <radialGradient id={`${gid}-glow`} cx="50%" cy="50%" r="55%">
            <stop offset="0%" stopColor="var(--color-brand)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--color-brand)" stopOpacity="0" />
          </radialGradient>

          {/* Drop-shadow-ish outer glow on the stroked polygon. */}
          <filter id={`${gid}-shadow`} x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="2.4" />
            <feOffset dx="0" dy="1" result="offsetblur" />
            <feComponentTransfer>
              <feFuncA type="linear" slope="0.45" />
            </feComponentTransfer>
            <feMerge>
              <feMergeNode />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>

          {/* Subtle glow under each vertex pill. */}
          <filter id={`${gid}-pill`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="1.8" />
            <feOffset dx="0" dy="1" />
            <feComponentTransfer>
              <feFuncA type="linear" slope="0.35" />
            </feComponentTransfer>
            <feMerge>
              <feMergeNode />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Ambient glow */}
        <circle
          cx={cx}
          cy={cy}
          r={maxRadius + 12}
          fill={`url(#${gid}-glow)`}
          style={{
            opacity: t,
            transition: "opacity 900ms ease-out",
          }}
        />

        {/* Grid rings — softer than before */}
        <g style={{ stroke: "var(--color-border)", fill: "none" }}>
          {gridPolys.map((g) => (
            <polygon
              key={g.score}
              points={g.pts}
              strokeWidth={1}
              strokeOpacity={
                g.score === 10 ? 0.8 : g.score === 2 ? 0.2 : 0.35
              }
            />
          ))}
        </g>

        {/* Spokes */}
        <g style={{ stroke: "var(--color-border)", strokeOpacity: 0.3 }}>
          {spokes.map((s, i) => (
            <line
              key={i}
              x1={cx}
              y1={cy}
              x2={s.x}
              y2={s.y}
              strokeWidth={1}
            />
          ))}
        </g>

        {/* Outer ring accent dots at each vertex */}
        <g>
          {spokes.map((s, i) => (
            <circle
              key={i}
              cx={s.x}
              cy={s.y}
              r={2}
              style={{
                fill: "var(--color-border)",
                opacity: 0.9,
              }}
            />
          ))}
        </g>

        {/* Sector median overlay */}
        {sectorOverlay && (
          <polygon
            points={medianPoints}
            fill="none"
            strokeDasharray="5 4"
            strokeWidth={1.5}
            style={{
              stroke: "var(--color-caption)",
              opacity: 0.75,
              transition:
                "all 800ms cubic-bezier(0.34, 1.56, 0.64, 1)",
            }}
          />
        )}

        {/* Main polygon — gradient-filled, shadow-stroked */}
        <polygon
          points={mainPoints}
          strokeWidth={2.5}
          filter={`url(#${gid}-shadow)`}
          style={{
            stroke: "var(--color-brand)",
            fill: `url(#${gid}-fill)`,
            transition:
              "all 800ms cubic-bezier(0.34, 1.56, 0.64, 1)",
            strokeLinejoin: "round",
          }}
        />

        {/* Axis labels — bolder, larger */}
        <g
          style={{
            fill: "var(--color-caption)",
            fontSize: 10.5,
            fontWeight: 700,
            letterSpacing: "0.1em",
            fontFamily:
              "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
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

        {/* Vertex pills — color-coded, shadowed, bigger */}
        <g>
          {vertexPills.map((p) => {
            const color = scoreColor(p.score, p.dataLimited)
            return (
              <g
                key={p.key}
                role="button"
                tabIndex={onAxisTap ? 0 : -1}
                aria-label={`${AXIS_LABEL[p.key]} score ${p.score.toFixed(1)} out of 10`}
                onClick={() => onAxisTap?.(p.key)}
                onKeyDown={(e) => {
                  if (
                    onAxisTap &&
                    (e.key === "Enter" || e.key === " ")
                  ) {
                    e.preventDefault()
                    onAxisTap(p.key)
                  }
                }}
                style={{
                  cursor: onAxisTap ? "pointer" : "default",
                  transition: `transform 800ms cubic-bezier(0.34, 1.56, 0.64, 1) ${p.delayMs}ms, opacity 400ms ease-out ${p.delayMs}ms`,
                  opacity: t,
                }}
              >
                {/* 44×44 tap area */}
                <rect
                  x={p.x - 22}
                  y={p.y - 22}
                  width={44}
                  height={44}
                  fill="transparent"
                />
                {/* Outer white halo ring so the pill pops off the polygon */}
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={14}
                  style={{
                    fill: "var(--color-surface)",
                    stroke: color,
                    strokeWidth: 2,
                    filter: `url(#${gid}-pill)`,
                    transition: "stroke 300ms ease",
                  }}
                />
                <text
                  x={p.x}
                  y={p.y}
                  textAnchor="middle"
                  dominantBaseline="central"
                  style={{
                    fill: color,
                    fontSize: 10.5,
                    fontWeight: 800,
                    fontFamily:
                      "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
                    transition: "fill 300ms ease",
                  }}
                >
                  {p.score.toFixed(1)}
                </text>
              </g>
            )
          })}
        </g>
      </svg>

      {/* Centre overall score — big, color-driven, micro-shimmer on mount */}
      <div
        className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none"
        aria-hidden="true"
        style={{
          opacity: t,
          transition: "opacity 700ms ease-out 200ms",
        }}
      >
        <span
          className="font-mono tabular-nums"
          style={{
            fontSize: Math.round(size * 0.17),
            fontWeight: 800,
            color: overallColor,
            lineHeight: 1,
            letterSpacing: "-0.02em",
            textShadow: `0 1px 12px color-mix(in srgb, ${overallColor} 35%, transparent)`,
            transition: "color 400ms ease",
          }}
        >
          {overall.toFixed(1)}
        </span>
        <span
          className="font-mono"
          style={{
            fontSize: Math.round(size * 0.05),
            color: "var(--color-caption)",
            fontWeight: 600,
            letterSpacing: "0.08em",
            marginTop: 4,
          }}
        >
          / 10
        </span>
      </div>
    </div>
  )
}
