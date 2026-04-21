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
}: Props) {
  const cx = size / 2
  const cy = size / 2
  const maxRadius = size / 2 - 34

  // Signature fades out between t=0.0 and t=0.45 so Spectrum can take over.
  const vis = Math.max(0, 1 - t / 0.45)
  if (vis <= 0) return null

  const ordered = PRISM_PILLAR_ORDER.map(
    (k) => pillars.find((p) => p.key === k)!,
  )
  const scores = ordered.map((p) =>
    p.score == null ? 0 : Math.max(0, Math.min(10, p.score)),
  )

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

  const mainPoints = scores
    .map((s, i) => {
      const r = (s / 10) * maxRadius
      return signatureVertex(cx, cy, r, i).join(",")
    })
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
          Bumped to fontSize 12 + ink-color for first-time-user readability
          (audit feedback: caption-grey labels were hard to scan). */}
      <g
        style={{
          fill: "var(--color-ink)",
          fontSize: 12,
          fontWeight: 700,
          letterSpacing: "0.12em",
          fontFamily:
            "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
        }}
      >
        {ordered.map((p, i) => {
          const [x, y] = signatureVertex(cx, cy, maxRadius + 22, i)
          return (
            <text
              key={p.key}
              x={x}
              y={y}
              textAnchor="middle"
              dominantBaseline="middle"
            >
              {AXIS_LABEL[p.key]}
            </text>
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
          return (
            <g
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
              style={{
                cursor: onPillarTap ? "pointer" : "default",
                opacity: vertexOpacity,
                transition: "opacity 240ms ease",
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
              <circle
                cx={x}
                cy={y}
                r={14}
                style={{
                  fill: "var(--color-surface)",
                  stroke: color,
                  strokeWidth: 2,
                }}
              />
              <text
                x={x}
                y={y}
                textAnchor="middle"
                dominantBaseline="central"
                style={{
                  fill: color,
                  fontSize: 10.5,
                  fontWeight: 800,
                  fontFamily:
                    "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
                }}
              >
                {p.data_limited ? "n/a" : s.toFixed(1)}
              </text>
            </g>
          )
        })}
      </g>

      {/* Central composite score — only in Signature mode. */}
      <g aria-hidden="true">
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
            letterSpacing: "-0.02em",
          }}
        >
          {/* When ALL or majority of pillars are data_limited, the
              composite is misleading (a "5.0" derived from neutrals
              looks like a real score). Show "—" instead. */}
          {(() => {
            const limitedCount = pillars.filter((p) => p.data_limited).length
            if (limitedCount >= Math.ceil(pillars.length / 2)) return "—"
            return Number.isFinite(overall) ? overall.toFixed(1) : "—"
          })()}
        </text>
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
