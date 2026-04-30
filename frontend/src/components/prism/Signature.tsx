"use client"

import { useEffect, useRef, useState } from "react"
import {
  animate,
  motion,
  useMotionValue,
  useReducedMotion,
  useTransform,
} from "framer-motion"
import type { Pillar, PillarKey, VerdictBand } from "./types"
import { pillarColor } from "@/lib/prism"
import { PRISM_PILLAR_ORDER } from "@/lib/prism"

interface Props {
  pillars: Pillar[]
  overall: number
  pulseHz: number
  size: number
  /** Morph progress: 0 = pure Signature, 1 = pure Spectrum. */
  t: number
  verdictBand: VerdictBand
  sectorOverlay?: boolean
  sectorMedians?: Partial<Record<PillarKey, number>>
  onPillarTap?: (key: PillarKey) => void
  /** Phase 2: dim every non-matching vertex to ~30% when set. */
  highlightedPillar?: PillarKey | null
  uid: string
  /**
   * When true, play the initial entrance animations (vertex sweep-in,
   * score count-up, springy vertex pills). When false (e.g. onboarding
   * demo, time-machine scrubber, portfolio grid) render instantly.
   */
  firstView?: boolean
}

const AXIS_LABEL: Record<PillarKey, string> = {
  value: "VALUE",
  quality: "QUALITY",
  growth: "GROWTH",
  moat: "MOAT",
  safety: "SAFETY",
  pulse: "PULSE",
}

export function signatureVertex(
  cx: number,
  cy: number,
  r: number,
  i: number,
): [number, number] {
  const a = -Math.PI / 2 + (i * Math.PI) / 3
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)]
}

/**
 * Axis-by-axis polygon sweep-in. Each of the 6 axes has its radius
 * driven by a spring-eased local clock, staggered 80ms. Shared polygon
 * points are recomputed from the per-axis progress so the outline
 * "blooms" from the centre outwards without 6 separate SVG elements.
 */
function useSweepInRadii(
  targetScores: number[],
  enabled: boolean,
  maxRadius: number,
): number[] {
  const [radii, setRadii] = useState<number[]>(() =>
    enabled
      ? targetScores.map(() => 0)
      : targetScores.map((s) => (s / 10) * maxRadius),
  )

  // Only the initial mount plays the sweep-in. Subsequent score updates
  // jump to the new target without re-animating (prevents jitter when
  // data refreshes or a parent re-renders).
  const didMountRef = useRef(false)

  useEffect(() => {
    if (!enabled) {
      setRadii(targetScores.map((s) => (s / 10) * maxRadius))
      return
    }

    if (didMountRef.current) {
      setRadii(targetScores.map((s) => (s / 10) * maxRadius))
      return
    }
    didMountRef.current = true

    const start = performance.now()
    const duration = 600
    const stagger = 80
    // cubic-bezier(0.2, 0.8, 0.2, 1) — calm ease-out without overshoot.
    const ease = (t: number) => {
      const clamped = Math.max(0, Math.min(1, t))
      // Approximation via cubic-bezier sampling: quick-enough for 60fps.
      const u = 1 - clamped
      return (
        3 * u * u * clamped * 0.8 +
        3 * u * clamped * clamped * (1 - 0.2) +
        clamped * clamped * clamped
      )
    }

    let raf = 0
    const tick = () => {
      const now = performance.now()
      const next = targetScores.map((s, i) => {
        const local = (now - start - i * stagger) / duration
        const eased = ease(local)
        return (s / 10) * maxRadius * eased
      })
      setRadii(next)
      const lastLocal =
        (now - start - (targetScores.length - 1) * stagger) / duration
      if (lastLocal < 1) {
        raf = requestAnimationFrame(tick)
      } else {
        setRadii(targetScores.map((s) => (s / 10) * maxRadius))
      }
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // We intentionally exclude targetScores/maxRadius from deps — the
    // sweep-in runs exactly once on mount. Changes after mount jump to
    // the new values via the `didMountRef` branch above on the next
    // render of this effect's sibling state path.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, maxRadius])

  // Keep steady-state in sync when scores change post-mount.
  useEffect(() => {
    if (!didMountRef.current) return
    setRadii(targetScores.map((s) => (s / 10) * maxRadius))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetScores.join(","), maxRadius])

  return radii
}

/**
 * Animated count-up text for a single score. Animates from 0 → target
 * over 500ms on first mount; after that, subsequent target changes are
 * applied instantly to avoid jitter on hover / data refresh.
 */
function CountUpText({
  x,
  y,
  target,
  color,
  fontSize,
  enabled,
  label,
}: {
  x: number
  y: number
  target: number
  color: string
  fontSize: number
  enabled: boolean
  label: string
}) {
  const mv = useMotionValue(enabled ? 0 : target)
  const rounded = useTransform(mv, (latest) => latest.toFixed(1))
  const didAnimateRef = useRef(false)

  useEffect(() => {
    if (!enabled) {
      mv.set(target)
      return
    }
    if (didAnimateRef.current) {
      mv.set(target)
      return
    }
    didAnimateRef.current = true
    const controls = animate(mv, target, {
      duration: 0.5,
      ease: "easeOut",
    })
    return () => controls.stop()
  }, [enabled, target, mv])

  // PR-prism-zero-fix: render an em-dash placeholder (with a "Below cohort
  // range" tooltip) instead of the developer-y "n/a" string. The product
  // surface should never show "n/a" or "0.0" — both read as broken to a
  // first-time visitor. The em-dash + <title> combo communicates "value
  // exists but is outside the displayable cohort percentile range".
  if (label === "n/a" || label === "—" || label === "•••") {
    return (
      <text
        x={x}
        y={y}
        textAnchor="middle"
        dominantBaseline="central"
        style={{
          fill: color,
          fontSize,
          fontWeight: 800,
          fontFamily:
            "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
        }}
        aria-label="Below cohort range"
      >
        <title>Below cohort range</title>
        {"—"}
      </text>
    )
  }

  return (
    <motion.text
      x={x}
      y={y}
      textAnchor="middle"
      dominantBaseline="central"
      style={{
        fill: color,
        fontSize,
        fontWeight: 800,
        fontFamily:
          "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
      }}
    >
      {rounded}
    </motion.text>
  )
}

/**
 * Count-up for the central composite score. Renders the fractional part
 * as discrete <tspan>s (integer / U+002E / fraction) so the decimal
 * separator can never kern or font-substitute into a colon — same fix
 * as the pre-animation version. Animated on first mount only; uses
 * motion values + useTransform (no setState in effect) so the tspans
 * update directly off the animated motion value.
 */
function CompositeCountUp({
  cx,
  cy,
  target,
  size,
  enabled,
}: {
  cx: number
  cy: number
  target: number
  size: number
  enabled: boolean
}) {
  const mv = useMotionValue(enabled ? 0 : target)
  const didAnimateRef = useRef(false)
  const wholeMv = useTransform(mv, (v) => {
    const clamped = Math.max(0, Math.min(10, v))
    const rounded = Math.round(clamped * 10) / 10
    return String(Math.floor(rounded))
  })
  const fracMv = useTransform(mv, (v) => {
    const clamped = Math.max(0, Math.min(10, v))
    const rounded = Math.round(clamped * 10) / 10
    const whole = Math.floor(rounded)
    return String(Math.round((rounded - whole) * 10))
  })

  useEffect(() => {
    if (!enabled) {
      mv.set(target)
      return
    }
    if (didAnimateRef.current) {
      mv.set(target)
      return
    }
    didAnimateRef.current = true
    const controls = animate(mv, target, {
      duration: 0.5,
      ease: "easeOut",
    })
    return () => controls.stop()
  }, [enabled, target, mv])

  return (
    <motion.text
      x={cx}
      y={cy - 2}
      textAnchor="middle"
      dominantBaseline="central"
      style={{
        fill: "var(--color-ink)",
        fontSize: Math.round(size * 0.17),
        fontWeight: 800,
        fontFamily:
          "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
      }}
    >
      <motion.tspan>{wholeMv}</motion.tspan>
      <tspan dx="0.02em" dy="0" style={{ letterSpacing: "0" }}>
        {"\u002E"}
      </tspan>
      <motion.tspan dx="0.02em">{fracMv}</motion.tspan>
    </motion.text>
  )
}

/**
 * Signature (radial hex) renderer — returns `<g>` contents so the parent
 * `<Prism>` can interleave the Spectrum layer and animate shared children.
 * Visibility is driven by `t`: at t=0 we render fully, fading out by t=0.5.
 */
export default function Signature({
  pillars,
  overall,
  pulseHz,
  size,
  t,
  sectorOverlay,
  sectorMedians,
  onPillarTap,
  highlightedPillar,
  uid,
  firstView = false,
}: Props) {
  const cx = size / 2
  const cy = size / 2
  const maxRadius = size / 2 - 34

  const prefersReducedMotion = useReducedMotion()
  const animationsEnabled = firstView && !prefersReducedMotion

  // Axis hover state. Tracks the hovered axis key so we can scale +
  // glow the corresponding vertex pill. Independent from `onPillarTap`.
  const [hoveredAxis, setHoveredAxis] = useState<PillarKey | null>(null)

  // Signature fades out between t=0.0 and t=0.45 so Spectrum can take over.
  const vis = Math.max(0, 1 - t / 0.45)

  const ordered = PRISM_PILLAR_ORDER.map(
    (k) => pillars.find((p) => p.key === k)!,
  )
  const scores = ordered.map((p) =>
    p.score == null ? 0 : Math.max(0, Math.min(10, p.score)),
  )

  // Per-axis animated radii. Only the main polygon's radii animate; the
  // grid rings and spokes are static (they're background chrome).
  const animatedRadii = useSweepInRadii(scores, animationsEnabled, maxRadius)

  if (vis <= 0) return null

  const gridRings = [2, 4, 6, 8, 10].map((s) => {
    const r = (s / 10) * maxRadius
    const pts = Array.from({ length: 6 }, (_, i) =>
      signatureVertex(cx, cy, r, i).join(","),
    ).join(" ")
    return { score: s, pts }
  })

  const spokes = Array.from({ length: 6 }, (_, i) =>
    signatureVertex(cx, cy, maxRadius, i),
  )

  const mainPoints = animatedRadii
    .map((r, i) => signatureVertex(cx, cy, r, i).join(","))
    .join(" ")

  const medianPoints = ordered
    .map((p, i) => {
      const m = Math.max(
        0,
        Math.min(10, sectorMedians?.[p.key] ?? 0),
      )
      const r = (m / 10) * maxRadius
      return signatureVertex(cx, cy, r, i).join(",")
    })
    .join(" ")

  return (
    <g style={{ opacity: vis, transition: "opacity 200ms linear" }}>
      <defs>
        <radialGradient id={`${uid}-sig-fill`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--color-brand)" stopOpacity="0.45" />
          <stop offset="70%" stopColor="var(--color-brand)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--color-brand)" stopOpacity="0.08" />
        </radialGradient>
        <radialGradient id={`${uid}-sig-glow`} cx="50%" cy="50%" r="55%">
          <stop offset="0%" stopColor="var(--color-brand)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--color-brand)" stopOpacity="0" />
        </radialGradient>
      </defs>

      <circle
        cx={cx}
        cy={cy}
        r={maxRadius + 12}
        fill={`url(#${uid}-sig-glow)`}
      />

      {/* PR-ANON-POSITIONING: subtle fill of the full outer hex so that a
          median-score polygon (all pillars ~5/10) still reads as "data
          present, median values" instead of "empty / tool broken". The
          fill is intentionally very light (2.5% ink) — invisible against
          strong polygons, but provides visual anchor when the main
          polygon is tiny and centred. Fades with the grid rings. */}
      <polygon
        points={gridRings[gridRings.length - 1].pts}
        style={{
          fill: "var(--color-ink)",
          fillOpacity: 0.025,
          opacity: Math.max(0, 1 - t / 0.3),
        }}
      />

      {/* Grid rings fade out first so the main polygon reads clean during morph. */}
      <g
        style={{
          stroke: "var(--color-border)",
          fill: "none",
          opacity: Math.max(0, 1 - t / 0.3),
        }}
      >
        {gridRings.map((g) => (
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

      <g
        style={{
          stroke: "var(--color-border)",
          strokeOpacity: 0.3,
          opacity: Math.max(0, 1 - t / 0.3),
        }}
      >
        {spokes.map(([x, y], i) => (
          <line key={i} x1={cx} y1={cy} x2={x} y2={y} strokeWidth={1} />
        ))}
      </g>

      {sectorOverlay && sectorMedians && (
        <polygon
          points={medianPoints}
          fill="none"
          strokeDasharray="5 4"
          strokeWidth={1.5}
          style={{ stroke: "var(--color-caption)", opacity: 0.75 }}
        />
      )}

      <polygon
        points={mainPoints}
        strokeWidth={2.5}
        style={{
          stroke: "var(--color-brand)",
          fill: `url(#${uid}-sig-fill)`,
          strokeLinejoin: "round",
        }}
      />

      {/* Axis labels — polar placement just outside the outer ring.
          Label font is tied to `size` (SVG viewBox units) so the label
          stays legible when the SVG is scaled down on mobile: at size=240
          the label is ~13px, at size=340 it is ~15px. Previously a hard-
          coded 12 produced sub-10px labels on a 240 viewport scaled to
          the width of a 375px device. Minimum floor of 12 keeps the
          text above WCAG small-text threshold. */}
      <g
        style={{
          fill: "var(--color-ink)",
          fontSize: Math.max(12, Math.round(size * 0.045)),
          fontWeight: 700,
          letterSpacing: "0.12em",
          fontFamily:
            "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
        }}
      >
        {ordered.map((p, i) => {
          // FIX day2-#13: fall back to PRISM_PILLAR_ORDER[i] if p is
          // missing/malformed so the axis label (e.g. "PULSE") always
          // renders — never "—" or blank — regardless of whether the
          // backend axis payload is data_limited or partially missing.
          const pillarKey = (p?.key ?? PRISM_PILLAR_ORDER[i]) as PillarKey
          const [x, y] = signatureVertex(cx, cy, maxRadius + 22, i)
          return (
            <motion.text
              key={pillarKey}
              x={x}
              y={y}
              textAnchor="middle"
              dominantBaseline="middle"
              onHoverStart={() => setHoveredAxis(pillarKey)}
              onHoverEnd={() =>
                setHoveredAxis((prev) => (prev === pillarKey ? null : prev))
              }
              whileHover={
                prefersReducedMotion
                  ? undefined
                  : { scale: 1.05, transition: { duration: 0.15 } }
              }
              style={{
                cursor: "default",
                transformOrigin: `${x}px ${y}px`,
              }}
            >
              {AXIS_LABEL[pillarKey]}
            </motion.text>
          )
        })}
      </g>

      {/* Vertex pills — color-coded per pillar so users learn the palette.
          A data_limited pillar with score 0 would otherwise place its
          "n/a" badge exactly on (cx,cy) and visually collide with the
          central composite score (e.g. "4.9"). Pin those to a minimum
          radius so the n/a stays on the spoke, never on top of the
          centre. */}
      <g>
        {ordered.map((p, i) => {
          const s = scores[i]
          // PR-PRISM-OVERLAP: when MANY pillars are data_limited (e.g.
          // a Portfolio Prism with 5/6 n/a), all the n/a pills used to
          // collide with the central composite text. Push minR further
          // out (32% of maxRadius) so the n/a pills sit clearly outside
          // the score's typographic footprint (~17% of size = ~21% of
          // maxRadius once axis-label margin is accounted for).
          const minR = maxRadius * 0.32
          // Only nudge data_limited pills outward — real score-0 vertices
          // belong on the polygon at the centre.
          const pillR = p.data_limited ? minR : (s / 10) * maxRadius
          const [x, y] = signatureVertex(cx, cy, pillR, i)
          const color = p.data_limited ? "var(--color-caption)" : pillarColor(p.key)
          const isPulse = p.key === "pulse"
          const spotlightOn = highlightedPillar != null
          const isSpotlit = spotlightOn && highlightedPillar === p.key
          const vertexOpacity = !spotlightOn || isSpotlit ? 1 : 0.3
          const isHovered = hoveredAxis === p.key
          // Springy entrance for the vertex circles on first mount only.
          // Stagger by axis index so the pills "pop in" in order.
          const entrance = animationsEnabled
            ? {
                initial: { scale: 0, opacity: 0 },
                animate: { scale: 1, opacity: vertexOpacity },
                transition: {
                  delay: 0.15 + i * 0.06,
                  type: "spring" as const,
                  stiffness: 320,
                  damping: 22,
                  opacity: { duration: 0.2 },
                },
              }
            : {
                initial: false as const,
                animate: { scale: 1, opacity: vertexOpacity },
                transition: { duration: 0.24, ease: "easeOut" as const },
              }
          return (
            <motion.g
              key={p.key}
              role="button"
              tabIndex={onPillarTap ? 0 : -1}
              aria-label={`${p.key} score ${
                p.data_limited ? "below cohort range" : s.toFixed(1)
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
                transformOrigin: `${x}px ${y}px`,
              }}
              className={isPulse ? "prism-pulse-breathe" : undefined}
            >
              <rect
                x={x - 22}
                y={y - 22}
                width={44}
                height={44}
                fill="transparent"
              />
              <motion.circle
                cx={x}
                cy={y}
                r={14}
                animate={
                  prefersReducedMotion
                    ? undefined
                    : {
                        scale: isHovered ? 1.08 : 1,
                        filter: isHovered
                          ? `drop-shadow(0 0 6px ${color})`
                          : "drop-shadow(0 0 0px rgba(0,0,0,0))",
                      }
                }
                transition={{ duration: 0.18, ease: "easeOut" }}
                style={{
                  fill: "var(--color-surface)",
                  stroke: color,
                  strokeWidth: 2,
                  transformOrigin: `${x}px ${y}px`,
                }}
              />
              <CountUpText
                x={x}
                y={y}
                target={s}
                color={color}
                fontSize={Math.max(10, Math.round(size * 0.038))}
                enabled={animationsEnabled && !p.data_limited}
                label={p.data_limited ? "—" : s.toFixed(1)}
              />
            </motion.g>
          )
        })}
      </g>

      {/* Central composite score — only in Signature mode.
          FIX (prism-five-five): the decimal point was rendering as ":"
          on some devices/fonts. Cause: `letterSpacing: -0.02em` at
          ~17% of size (≈58px) in a heavy (weight 800) mono font pulled
          the 3 glyphs "5.5" so close that the tiny bottom-aligned "."
          visually merged with the adjacent "5" above its vertical
          centre, reading as a colon. Fix:
            1. Drop the negative letterSpacing (kerning is already tight
               in mono faces; the squeeze was purely cosmetic).
            2. Render the integer / separator / fraction as three
               distinct <tspan>s so the browser never substitutes or
               kerns the separator into something else, and pin the
               separator to the digits' baseline for unambiguous visual
               positioning. We use U+002E FULL STOP explicitly so no
               locale string conversion can swap in U+066B / U+2024
               / U+003A etc. */}
      <g aria-hidden="true">
        {(() => {
          const limitedCount = pillars.filter((p) => p.data_limited).length
          // When ALL or majority of pillars are data_limited, the
          // composite is misleading (a "5.0" derived from neutrals
          // looks like a real score). Show "—" instead.
          if (limitedCount >= Math.ceil(pillars.length / 2)) {
            return (
              <text
                x={cx}
                y={cy - 2}
                textAnchor="middle"
                dominantBaseline="central"
                style={{
                  fill: "var(--color-ink)",
                  fontSize: Math.round(size * 0.17),
                  fontWeight: 800,
                  fontFamily:
                    "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
                }}
              >
                —
              </text>
            )
          }
          if (!Number.isFinite(overall)) {
            return (
              <text
                x={cx}
                y={cy - 2}
                textAnchor="middle"
                dominantBaseline="central"
                style={{
                  fill: "var(--color-ink)",
                  fontSize: Math.round(size * 0.17),
                  fontWeight: 800,
                  fontFamily:
                    "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
                }}
              >
                —
              </text>
            )
          }
          return (
            <CompositeCountUp
              cx={cx}
              cy={cy}
              target={overall}
              size={size}
              enabled={animationsEnabled}
            />
          )
        })()}
        <text
          x={cx}
          y={cy + Math.round(size * 0.11)}
          textAnchor="middle"
          dominantBaseline="central"
          style={{
            fill: "var(--color-caption)",
            fontSize: Math.round(size * 0.05),
            fontWeight: 600,
            letterSpacing: "0.08em",
            fontFamily:
              "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
          }}
        >
          / 10
        </text>
        {/* Tiny verdict-band hint under the score so first-time
            visitors immediately know what 6.3 means without scrolling. */}
        <text
          x={cx}
          y={cy + Math.round(size * 0.18)}
          textAnchor="middle"
          dominantBaseline="central"
          style={{
            fill: "var(--color-caption)",
            fontSize: Math.round(size * 0.035),
            fontWeight: 700,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            fontFamily:
              "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
          }}
        >
          composite
        </text>
      </g>

      {/* Injected CSS custom property carrier for --pulse-hz. */}
      <style>{`#${uid}-sig-root { --pulse-hz: ${(1 / Math.max(0.05, pulseHz)).toFixed(3)}s; }`}</style>
      <g id={`${uid}-sig-root`} />
    </g>
  )
}
