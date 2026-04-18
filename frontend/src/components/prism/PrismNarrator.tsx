"use client"

/**
 * PrismNarrator — Phase 2 of "The YieldIQ Prism".
 *
 * A compact play/pause control that fetches a Groq-generated 45-second
 * narration from `/api/v1/prism/<ticker>/narrate`, then plays it back as
 * a sequence of captions while highlighting each pillar on the Prism via
 * the `onHighlight` callback.
 *
 * Contract with the parent (EditorialHero):
 *   <PrismNarrator data={prism} onHighlight={setHighlightedPillar} />
 *   <Prism data={prism} highlightedPillar={highlightedPillar} />
 *
 * Accessibility:
 *   - The play/pause is a real <button> with aria-label + aria-pressed.
 *   - The active caption is announced via role="status" + aria-live="polite"
 *     so screen readers narrate each pillar as it becomes active.
 */

import { useCallback, useEffect, useRef, useState } from "react"

import type { PillarKey, PrismData } from "./types"
import {
  fetchNarration,
  type Narration,
} from "@/lib/prismNarration"

interface Props {
  data: PrismData
  onHighlight: (pillarKey: PillarKey | null) => void
  className?: string
}

type PlayState = "idle" | "loading" | "playing" | "paused" | "error"

interface Segment {
  kind: "intro" | "pillar" | "outro"
  pillar: PillarKey | null
  prose: string
  duration: number
}

function buildSegments(n: Narration): Segment[] {
  const segs: Segment[] = []
  if (n.intro) {
    segs.push({
      kind: "intro",
      pillar: null,
      prose: n.intro,
      duration: Number(n.intro_duration_ms ?? 4000),
    })
  }
  for (const p of n.pillars) {
    segs.push({
      kind: "pillar",
      pillar: p.key,
      prose: p.prose,
      duration: Number(p.duration_ms ?? 6500),
    })
  }
  if (n.outro) {
    segs.push({
      kind: "outro",
      pillar: null,
      prose: n.outro,
      duration: Number(n.outro_duration_ms ?? 4000),
    })
  }
  return segs
}

export default function PrismNarrator({ data, onHighlight, className }: Props) {
  const [state, setState] = useState<PlayState>("idle")
  const [narration, setNarration] = useState<Narration | null>(null)
  const [segIndex, setSegIndex] = useState<number>(-1)
  const [segProgress, setSegProgress] = useState<number>(0) // 0..1 current seg
  const [elapsedBefore, setElapsedBefore] = useState<number>(0) // ms before current seg

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rafRef = useRef<number | null>(null)
  const segStartRef = useRef<number>(0) // performance.now() at seg start
  const pausedAtRef = useRef<number | null>(null) // ms elapsed into current seg when paused

  const segments = narration ? buildSegments(narration) : []
  const totalMs = narration?.total_duration_ms ?? 0

  const clearTimers = useCallback(() => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }, [])

  const reset = useCallback(() => {
    clearTimers()
    pausedAtRef.current = null
    setSegIndex(-1)
    setSegProgress(0)
    setElapsedBefore(0)
    onHighlight(null)
  }, [clearTimers, onHighlight])

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      clearTimers()
      onHighlight(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Drive a single segment from `startOffsetMs` (how many ms we're already
  // into it — non-zero only when resuming from pause). Schedules the next
  // segment via setTimeout, progress bar via RAF.
  const playSegment = useCallback(
    (idx: number, startOffsetMs: number) => {
      const seg = segments[idx]
      if (!seg) {
        // End of reel.
        clearTimers()
        onHighlight(null)
        setState("idle")
        setSegIndex(-1)
        setSegProgress(0)
        setElapsedBefore(0)
        return
      }

      onHighlight(seg.pillar)
      segStartRef.current = performance.now() - startOffsetMs

      const tick = () => {
        const now = performance.now()
        const elapsed = Math.min(seg.duration, now - segStartRef.current)
        setSegProgress(elapsed / Math.max(1, seg.duration))
        if (elapsed < seg.duration) {
          rafRef.current = requestAnimationFrame(tick)
        }
      }
      rafRef.current = requestAnimationFrame(tick)

      const remaining = Math.max(0, seg.duration - startOffsetMs)
      timerRef.current = setTimeout(() => {
        // Advance: add THIS segment's full duration to elapsedBefore, then next.
        setElapsedBefore((prev) => prev + seg.duration)
        const nextIdx = idx + 1
        setSegIndex(nextIdx)
        setSegProgress(0)
        playSegment(nextIdx, 0)
      }, remaining)
    },
    // segments is recomputed from narration each render; but we only read
    // it inside the callback synchronously at call time — safe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [onHighlight, clearTimers, narration],
  )

  const start = useCallback(async () => {
    if (state === "playing" || state === "loading") return

    let nar = narration
    if (!nar) {
      setState("loading")
      try {
        nar = await fetchNarration(data.ticker)
        setNarration(nar)
      } catch (err) {
        console.warn("PrismNarrator: fetchNarration failed", err)
        setState("error")
        // Revert to idle after a short beat so the button stays usable.
        setTimeout(() => setState("idle"), 1500)
        return
      }
    }

    setState("playing")
    setSegIndex(0)
    setSegProgress(0)
    setElapsedBefore(0)
    pausedAtRef.current = null
    playSegment(0, 0)
  }, [data.ticker, narration, state, playSegment])

  const pause = useCallback(() => {
    if (state !== "playing" || segIndex < 0) return
    const seg = segments[segIndex]
    if (!seg) return
    const elapsedIntoSeg = Math.min(
      seg.duration,
      performance.now() - segStartRef.current,
    )
    pausedAtRef.current = elapsedIntoSeg
    clearTimers()
    setState("paused")
  }, [state, segIndex, segments, clearTimers])

  const resume = useCallback(() => {
    if (state !== "paused" || segIndex < 0) return
    const offset = pausedAtRef.current ?? 0
    pausedAtRef.current = null
    setState("playing")
    playSegment(segIndex, offset)
  }, [state, segIndex, playSegment])

  const stop = useCallback(() => {
    reset()
    setState("idle")
  }, [reset])

  // Composite progress across the whole narration (0..1).
  const currentSeg = segIndex >= 0 ? segments[segIndex] : null
  const currentMs = currentSeg ? currentSeg.duration * segProgress : 0
  const overallPct =
    totalMs > 0
      ? Math.min(1, (elapsedBefore + currentMs) / totalMs) * 100
      : 0

  const caption =
    segIndex >= 0 && segments[segIndex]
      ? segments[segIndex].prose
      : state === "loading"
        ? "Preparing the story…"
        : state === "error"
          ? "Narration unavailable. Try again in a moment."
          : ""

  const isActive = state === "playing" || state === "paused"

  return (
    <div
      className={className}
      style={{ display: "flex", flexDirection: "column", gap: 10, width: "100%" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {!isActive && (
          <button
            type="button"
            aria-label="Play the Prism narration"
            onClick={start}
            disabled={state === "loading"}
            className="tap-target"
            style={{
              minHeight: 44,
              padding: "10px 18px",
              borderRadius: 999,
              background: "var(--color-brand)",
              color: "var(--color-bg)",
              border: "none",
              fontSize: 13,
              fontWeight: 700,
              letterSpacing: "0.04em",
              fontFamily:
                "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
              cursor: state === "loading" ? "progress" : "pointer",
              opacity: state === "loading" ? 0.75 : 1,
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            {state === "loading" ? (
              <>
                <span
                  aria-hidden
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: "50%",
                    border: "2px solid currentColor",
                    borderTopColor: "transparent",
                    animation: "prism-narrator-spin 0.8s linear infinite",
                  }}
                />
                Loading…
              </>
            ) : (
              <>▶ Tell me the story</>
            )}
          </button>
        )}

        {isActive && (
          <>
            <button
              type="button"
              aria-label={state === "playing" ? "Pause narration" : "Resume narration"}
              aria-pressed={state === "paused"}
              onClick={state === "playing" ? pause : resume}
              className="tap-target"
              style={{
                minHeight: 44,
                padding: "10px 16px",
                borderRadius: 999,
                background: "var(--color-brand)",
                color: "var(--color-bg)",
                border: "none",
                fontSize: 13,
                fontWeight: 700,
                letterSpacing: "0.04em",
                fontFamily:
                  "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
                cursor: "pointer",
              }}
            >
              {state === "playing" ? "⏸ Pause" : "▶ Resume"}
            </button>
            <button
              type="button"
              aria-label="Stop narration"
              onClick={stop}
              className="tap-target"
              style={{
                minHeight: 44,
                padding: "10px 14px",
                borderRadius: 999,
                background: "transparent",
                color: "var(--color-caption)",
                border: "1px solid var(--color-border)",
                fontSize: 12,
                fontWeight: 600,
                letterSpacing: "0.04em",
                fontFamily:
                  "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
                cursor: "pointer",
              }}
            >
              ■ Stop
            </button>
          </>
        )}
      </div>

      {/* Caption — announced via aria-live so screen readers keep up. */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        style={{
          minHeight: 48,
          fontSize: 15,
          lineHeight: 1.45,
          color: "var(--color-ink)",
          fontFamily:
            "var(--font-editorial), Georgia, 'Times New Roman', serif",
        }}
      >
        {caption}
      </div>

      {/* Progress bar — only visible while a reel is active. */}
      {isActive && (
        <div
          aria-hidden
          style={{
            position: "relative",
            width: "100%",
            height: 3,
            background: "var(--color-border)",
            borderRadius: 999,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              width: `${overallPct}%`,
              background: "var(--color-brand)",
              transition: "width 120ms linear",
            }}
          />
        </div>
      )}

      <style>{`
        @keyframes prism-narrator-spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
