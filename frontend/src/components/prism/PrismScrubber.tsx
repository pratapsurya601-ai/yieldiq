"use client"

import { useCallback, useEffect, useRef } from "react"
import type { HistoryQuarter } from "@/lib/prismHistory"
import { quarterLabel } from "@/lib/prismHistory"

interface PrismScrubberProps {
  quarters: HistoryQuarter[]
  /** Float index in [0, quarters.length-1] — sub-tick values drive
   *  interpolation between adjacent quarters. */
  value: number
  onChange: (index: number) => void
  playing: boolean
  onPlayToggle: () => void
}

/**
 * Horizontal scrubber with a draggable thumb, tick marks, and transport
 * controls. The thumb itself is a 44x44 CSS-only handle sitting over an
 * invisible `<input type="range">` that does all the pointer handling — this
 * gives us native keyboard support (←/→/Home/End) for free and avoids
 * reinventing touch-drag on mobile.
 *
 * The outer wrapper captures arrow keys + Space globally while focus is on
 * any scrubber child, so the user can play/pause without hunting for the
 * exact play button when the modal is busy.
 */
export default function PrismScrubber({
  quarters,
  value,
  onChange,
  playing,
  onPlayToggle,
}: PrismScrubberProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const last = quarters.length - 1
  const clamped = Math.max(0, Math.min(last, value))
  const pct = last <= 0 ? 0 : (clamped / last) * 100
  const currentIdx = Math.round(clamped)
  const currentQ = quarters[currentIdx]

  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (!wrapRef.current) return
      if (!wrapRef.current.contains(document.activeElement)) return
      if (e.key === "ArrowLeft") {
        e.preventDefault()
        onChange(Math.max(0, Math.round(clamped) - 1))
      } else if (e.key === "ArrowRight") {
        e.preventDefault()
        onChange(Math.min(last, Math.round(clamped) + 1))
      } else if (e.key === " " || e.code === "Space") {
        e.preventDefault()
        onPlayToggle()
      }
    },
    [clamped, last, onChange, onPlayToggle],
  )

  useEffect(() => {
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [handleKey])

  if (quarters.length === 0) return null

  return (
    <div ref={wrapRef} className="w-full select-none">
      <div className="flex items-center gap-3">
        {/* Play / pause transport. 44x44 tap target per the product spec. */}
        <button
          type="button"
          aria-label={playing ? "Pause time machine" : "Play time machine"}
          aria-pressed={playing}
          onClick={onPlayToggle}
          className="inline-flex items-center justify-center w-11 h-11 rounded-full bg-brand text-white hover:opacity-90 active:scale-95 transition shrink-0"
        >
          {playing ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
              <rect x="6" y="5" width="4" height="14" rx="1" />
              <rect x="14" y="5" width="4" height="14" rx="1" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
              <path d="M7 5v14l12-7z" />
            </svg>
          )}
        </button>

        {/* Track + thumb. The <input> is absolutely positioned to match the
            visual track; its thumb is styled transparent and replaced by a
            CSS-drawn circle for consistent cross-browser rendering. */}
        <div className="relative flex-1 h-11">
          {/* Current-quarter bubble floating above the thumb */}
          {currentQ && (
            <div
              className="absolute -top-1 -translate-x-1/2 px-2 py-0.5 rounded-md bg-ink text-bg text-[10px] font-mono font-semibold whitespace-nowrap pointer-events-none"
              style={{ left: `calc(${pct}% )` }}
            >
              {quarterLabel(currentQ.quarter_end)}
            </div>
          )}
          {/* Visual track */}
          <div className="absolute top-1/2 left-0 right-0 h-1 -translate-y-1/2 rounded-full bg-surface border border-border overflow-hidden">
            <div
              className="h-full bg-brand"
              style={{ width: `${pct}%` }}
            />
          </div>
          {/* Tick marks, one per quarter */}
          <div className="absolute top-1/2 left-0 right-0 h-2 -translate-y-1/2 pointer-events-none">
            {quarters.map((q, i) => {
              const tPct = last <= 0 ? 0 : (i / last) * 100
              return (
                <div
                  key={q.quarter_end + i}
                  className="absolute w-0.5 h-2 bg-border -translate-x-1/2 top-0"
                  style={{ left: `${tPct}%` }}
                />
              )
            })}
          </div>
          {/* Native range input for a11y + drag handling */}
          <input
            type="range"
            min={0}
            max={last}
            step={0.01}
            value={clamped}
            onChange={(e) => onChange(Number(e.target.value))}
            aria-label="Scrub through historical quarters"
            aria-valuemin={0}
            aria-valuemax={last}
            aria-valuenow={currentIdx}
            aria-valuetext={currentQ ? quarterLabel(currentQ.quarter_end) : undefined}
            className="prism-scrubber-range absolute inset-0 w-full h-full opacity-0 cursor-pointer touch-none"
          />
          {/* Rendered thumb (decorative, pointer-events none) */}
          <div
            className="absolute top-1/2 w-5 h-5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-bg border-2 border-brand shadow-sm pointer-events-none"
            style={{ left: `${pct}%` }}
          />
        </div>
      </div>

      {/* Quarter tick labels below the track — show first, middle, last to
          avoid overflow on narrow screens; full list is still reachable via
          the bubble as the user drags. */}
      <div className="mt-2 flex justify-between text-[10px] font-mono text-caption tabular-nums">
        <span>{quarters[0] && quarterLabel(quarters[0].quarter_end)}</span>
        {quarters.length >= 3 && (
          <span>
            {quarterLabel(quarters[Math.floor(quarters.length / 2)].quarter_end)}
          </span>
        )}
        <span>{quarters[last] && quarterLabel(quarters[last].quarter_end)}</span>
      </div>
    </div>
  )
}
