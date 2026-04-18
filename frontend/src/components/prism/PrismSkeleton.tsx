/**
 * Static SSR-safe placeholder for Prism. Zero JS, zero animation — a plain
 * hex outline sized to match the final component so layout doesn't shift
 * when real data arrives.
 */
interface Props {
  size?: number
  className?: string
}

function hexPoints(cx: number, cy: number, r: number): string {
  const pts: string[] = []
  for (let i = 0; i < 6; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 3
    pts.push(`${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`)
  }
  return pts.join(" ")
}

export default function PrismSkeleton({ size = 320, className }: Props) {
  const cx = size / 2
  const cy = size / 2
  const r = size / 2 - 34
  return (
    <div
      className={className}
      style={{ width: size, height: size, position: "relative" }}
      aria-busy="true"
      aria-label="Loading Prism"
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <polygon
          points={hexPoints(cx, cy, r)}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={1.5}
        />
        <text
          x={cx}
          y={cy}
          textAnchor="middle"
          dominantBaseline="central"
          fill="var(--color-caption)"
          fontSize={Math.round(size * 0.17)}
          fontFamily="var(--font-mono), ui-monospace, monospace"
          fontWeight={800}
        >
          —
        </text>
      </svg>
    </div>
  )
}
