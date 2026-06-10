"use client"
/**
 * CalibrationSectorsTable — client wrapper around the per-sector
 * calibration table that owns the row-stagger entrance + per-row
 * hover treatment.
 *
 * The legacy server-rendered table was extracted so its rows can
 * register inline reveal styles without exporting useState/useEffect
 * from a server component. The DOM produced here matches the
 * previous markup column-for-column — the only addition is the
 * per-row transition styles and the hover background tint.
 */
import Link from "next/link"
import { useInViewOnce } from "@/components/anim/useInViewOnce"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { DURATION, cssEase } from "@/lib/motion/timing"

type SectorStat = {
  sector: string
  ticker_count: number
  observation_count: number
  median_abs_error_pct: number
  median_signed_error_pct: number
  p90_abs_error_pct: number
  direction_accuracy_pct: number
  last_observation_date: string
}

// Same stagger constants as SectorTable — tight 25ms so a typical
// 6-12 sector list reads as one sweep, not a slow cascade.
const ROW_STAGGER_MS = 25
const ROW_STAGGER_LIMIT = 20

function sectorSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  return `${v.toFixed(1)}%`
}

export default function CalibrationSectorsTable({
  sectors,
}: {
  sectors: SectorStat[]
}) {
  const reduced = useReducedMotion()
  const { ref: animRef, inView } = useInViewOnce<HTMLDivElement>(0.1)
  const animVisible = reduced || inView
  const rowEase = cssEase("outExpo")

  return (
    <div
      ref={animRef}
      className="overflow-x-auto rounded-xl border border-[color:var(--color-border)]"
      data-anim="calibration-table"
    >
      <table className="w-full text-sm">
        <thead className="bg-[color:var(--color-surface)] text-[color:var(--color-caption)] text-xs uppercase tracking-wider">
          <tr>
            <th className="text-left px-4 py-3">Sector</th>
            <th className="text-right px-4 py-3">Tickers</th>
            <th className="text-right px-4 py-3">Observations</th>
            <th className="text-right px-4 py-3">Median |Error|</th>
            <th className="text-right px-4 py-3">P90 |Error|</th>
            <th className="text-right px-4 py-3">Direction Accuracy</th>
          </tr>
        </thead>
        <tbody className="bg-[color:var(--color-bg)]">
          {sectors.map((s, idx) => {
            // Brief calls for HoverCard + RevealStagger on sector
            // calibration "cards". We're a table, not a card grid, so
            // we lift the same intent onto <tr>: per-row stagger for
            // entrance, hover background tint for "this is clickable".
            const animate = idx < ROW_STAGGER_LIMIT
            const rowStyle: React.CSSProperties = animate
              ? {
                  opacity: animVisible ? 1 : 0,
                  transform: animVisible
                    ? "translate3d(0,0,0)"
                    : "translate3d(0,6px,0)",
                  transition: reduced
                    ? "none"
                    : `opacity ${DURATION.normal}ms ease-out ${idx * ROW_STAGGER_MS}ms, transform ${DURATION.normal}ms ${rowEase} ${idx * ROW_STAGGER_MS}ms`,
                  willChange: animVisible ? "auto" : "opacity, transform",
                }
              : {}
            return (
              <tr
                key={s.sector}
                className="border-t border-[color:var(--color-border)] hover:bg-[color:var(--color-surface)] transition-colors"
                style={rowStyle}
                data-stagger-index={animate ? idx : undefined}
              >
                <td className="px-4 py-3 text-[color:var(--color-ink)]">
                  <Link
                    href={`/calibration/${sectorSlug(s.sector)}`}
                    className="underline-offset-2 hover:underline"
                  >
                    {s.sector}
                  </Link>
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-[color:var(--color-body)]">
                  {s.ticker_count}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-[color:var(--color-body)]">
                  {s.observation_count}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-[color:var(--color-ink)]">
                  {fmtPct(s.median_abs_error_pct)}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-[color:var(--color-body)]">
                  {fmtPct(s.p90_abs_error_pct)}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-[color:var(--color-ink)]">
                  {fmtPct(s.direction_accuracy_pct)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
