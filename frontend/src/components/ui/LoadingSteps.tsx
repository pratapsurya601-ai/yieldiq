"use client"

/**
 * Analysis-page loading skeleton.
 *
 * Matches the shape of <EditorialHero/> + <InsightCards/> so the paint
 * feels like the app is almost done, not "thinking". Previously this
 * component animated a five-step progress list which read as slow work
 * rather than a near-finished render.
 *
 * Pieces:
 *   • Header skeleton — ticker name, price, MoS chip
 *   • Hex outline placeholder — dim hexagon with 6 dim axis circles
 *   • Ratio card grid — 6 shimmer cards, 2 shimmer lines each
 *
 * All shimmer uses Tailwind's `animate-pulse` over `bg-surface` / `bg-border`
 * tokens so it adapts to light/dark automatically.
 */

function hexPoints(cx: number, cy: number, r: number): string {
  const pts: string[] = []
  for (let i = 0; i < 6; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 3
    pts.push(`${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`)
  }
  return pts.join(" ")
}

function HexOutlineSkeleton({ size = 280 }: { size?: number }) {
  const cx = size / 2
  const cy = size / 2
  const r = size / 2 - 34
  return (
    <svg
      width="100%"
      height="100%"
      viewBox={`0 0 ${size} ${size}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
      className="animate-pulse"
    >
      {/* outer ring */}
      <polygon
        points={hexPoints(cx, cy, r)}
        fill="none"
        stroke="currentColor"
        strokeOpacity={0.25}
        strokeWidth={1.5}
      />
      {/* inner ring at 60% radius */}
      <polygon
        points={hexPoints(cx, cy, r * 0.6)}
        fill="none"
        stroke="currentColor"
        strokeOpacity={0.15}
        strokeWidth={1}
      />
      {/* spokes */}
      {Array.from({ length: 6 }, (_, i) => {
        const a = -Math.PI / 2 + (i * Math.PI) / 3
        return (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={cx + r * Math.cos(a)}
            y2={cy + r * Math.sin(a)}
            stroke="currentColor"
            strokeOpacity={0.12}
            strokeWidth={1}
          />
        )
      })}
      {/* 6 dim axis circles */}
      {Array.from({ length: 6 }, (_, i) => {
        const a = -Math.PI / 2 + (i * Math.PI) / 3
        const x = cx + r * 0.7 * Math.cos(a)
        const y = cy + r * 0.7 * Math.sin(a)
        return (
          <circle
            key={i}
            cx={x}
            cy={y}
            r={14}
            fill="currentColor"
            fillOpacity={0.08}
            stroke="currentColor"
            strokeOpacity={0.2}
            strokeWidth={1.5}
          />
        )
      })}
      {/* central score placeholder */}
      <rect
        x={cx - 28}
        y={cy - 14}
        width={56}
        height={18}
        rx={4}
        fill="currentColor"
        fillOpacity={0.12}
      />
    </svg>
  )
}

export default function LoadingSteps() {
  return (
    <div
      className="max-w-5xl mx-auto px-4 py-6 space-y-5"
      aria-busy="true"
      aria-label="Loading analysis"
    >
      {/* ─── Header skeleton — ticker name, price, MoS chip ───────────── */}
      <div className="flex items-center justify-between gap-3 animate-pulse">
        <div className="flex items-baseline gap-3 min-w-0">
          <div className="h-7 w-28 rounded-md bg-surface border border-border" />
          <div className="h-5 w-20 rounded bg-surface border border-border" />
        </div>
        <div className="h-7 w-24 rounded-full bg-surface border border-border" />
      </div>

      {/* ─── Hero row — hex + verdict + score card ────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Column 1 — verdict copy placeholder (desktop left, mobile below) */}
        <div className="lg:col-span-4 order-3 lg:order-1 space-y-3">
          <div className="h-4 w-20 rounded bg-surface border border-border animate-pulse" />
          <div className="h-8 w-48 rounded bg-surface border border-border animate-pulse" />
          <div className="grid grid-cols-2 gap-4 pt-1">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="space-y-1.5 animate-pulse">
                <div className="h-3 w-20 rounded bg-surface border border-border" />
                <div className="h-5 w-24 rounded bg-surface border border-border" />
              </div>
            ))}
          </div>
        </div>

        {/* Column 2 — hex placeholder */}
        <div className="lg:col-span-5 order-2 lg:order-2 flex flex-col items-center">
          <div className="w-full max-w-[340px] text-caption">
            <HexOutlineSkeleton size={340} />
          </div>
          <div className="mt-3 h-3 w-40 rounded bg-surface border border-border animate-pulse" />
        </div>

        {/* Column 3 — score card placeholder */}
        <div className="lg:col-span-3 order-1 lg:order-3">
          <div className="bg-ink/90 rounded-2xl p-5 space-y-3 animate-pulse">
            <div className="h-3 w-24 rounded bg-bg/20" />
            <div className="h-10 w-20 rounded bg-bg/20" />
            <div className="h-3 w-28 rounded bg-bg/20" />
            <div className="h-6 w-full rounded bg-bg/10" />
            <div className="h-3 w-32 rounded bg-bg/20" />
          </div>
        </div>
      </div>

      {/* ─── Ratio card grid — 6 shimmer cards ──────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 pt-2">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className="rounded-xl bg-surface border border-border border-l-[3px] border-l-border p-4 animate-pulse"
          >
            <div className="flex items-center gap-1.5 mb-2">
              <div className="h-4 w-4 rounded-full bg-bg border border-border" />
              <div className="h-3 w-20 rounded bg-bg border border-border" />
            </div>
            <div className="h-5 w-16 rounded bg-bg border border-border mb-1.5" />
            <div className="h-3 w-24 rounded bg-bg border border-border" />
          </div>
        ))}
      </div>

      {/* ─── Tab strip placeholder ──────────────────────────────────── */}
      <div className="flex gap-2 pt-2">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-8 w-20 rounded-full bg-surface border border-border animate-pulse"
          />
        ))}
      </div>

      <p className="sr-only">Loading analysis, one moment&hellip;</p>
    </div>
  )
}
