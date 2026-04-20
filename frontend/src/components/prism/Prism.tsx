"use client"

import { useCallback, useEffect, useId, useRef, useState } from "react"
import Signature from "./Signature"
import Spectrum from "./Spectrum"
import type { PillarKey, PrismData, PrismMode } from "./types"

interface PrismProps {
  data: PrismData
  /** Controlled mode. If provided, the internal toggle is hidden. */
  mode?: PrismMode
  /** Uncontrolled default. Ignored when `mode` is provided. */
  defaultMode?: PrismMode
  /** Pixel size of the square SVG frame. */
  size?: number
  onModeChange?: (m: PrismMode) => void
  onPillarTap?: (k: PillarKey) => void
  /** If false, skip entry animation. Used for warm sessions. */
  firstView?: boolean
  sectorOverlay?: boolean
  /**
   * Phase 2 (narration): when set, this pillar's vertex (Signature) or lens
   * (Spectrum) renders at full opacity while the others dim to ~30%. Null
   * or undefined means "no spotlight" — the default display.
   */
  highlightedPillar?: PillarKey | null
  className?: string
}

/**
 * cubic-bezier(0.34, 1.56, 0.64, 1) via a cheap approximation (no Framer).
 * We approximate the spring by sampling the bezier curve each frame using
 * De Casteljau's algorithm, since we only need a visually pleasing easing.
 */
function easeSpring(t: number): number {
  // Classic "back-out" from easings.net, matches cubic-bezier(0.34,1.56,0.64,1).
  const c1 = 1.70158
  const c3 = c1 + 1
  const x = t - 1
  return 1 + c3 * x * x * x + c1 * x * x
}

/**
 * `<Prism>` — the signature YieldIQ visual. Morphs between Signature (radial
 * hex) and Spectrum (linear lens stack) via a cross-fade driven by a RAF
 * loop. No animation library — vanilla requestAnimationFrame with a spring
 * easing, 800ms total.
 */
export default function Prism({
  data,
  mode,
  defaultMode = "signature",
  size = 320,
  onModeChange,
  onPillarTap,
  firstView = true,
  sectorOverlay,
  highlightedPillar,
  className,
}: PrismProps) {
  const isControlled = mode !== undefined
  const [internalMode, setInternalMode] = useState<PrismMode>(
    mode ?? defaultMode,
  )
  const activeMode = isControlled ? (mode as PrismMode) : internalMode

  // Keep internalMode in sync if caller flips from uncontrolled to controlled.
  useEffect(() => {
    if (isControlled && mode !== undefined) setInternalMode(mode)
  }, [isControlled, mode])

  // `t` is the morph progress: 0 = Signature, 1 = Spectrum.
  const [t, setT] = useState<number>(
    (mode ?? defaultMode) === "spectrum" ? 1 : 0,
  )
  const rafRef = useRef<number | null>(null)
  const startTimeRef = useRef<number>(0)
  const startTRef = useRef<number>(0)
  const targetTRef = useRef<number>(t)

  // Animate `t` toward the target whenever the mode prop flips.
  useEffect(() => {
    const target = activeMode === "spectrum" ? 1 : 0
    if (target === targetTRef.current && t === target) return

    targetTRef.current = target
    startTRef.current = t
    startTimeRef.current = performance.now()
    const duration = firstView ? 800 : 500

    const tick = (now: number) => {
      const elapsed = now - startTimeRef.current
      const raw = Math.min(1, elapsed / duration)
      const eased = easeSpring(raw)
      const next =
        startTRef.current + (targetTRef.current - startTRef.current) * eased
      setT(next)
      if (raw < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        setT(targetTRef.current)
        rafRef.current = null
      }
    }
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMode, firstView])

  const handleToggle = useCallback(
    (next: PrismMode) => {
      if (!isControlled) setInternalMode(next)
      onModeChange?.(next)
    },
    [isControlled, onModeChange],
  )

  const reactId = useId().replace(/:/g, "")
  const uid = `prism-${reactId}`

  const ariaLabel = `Prism for ${data.ticker}: composite ${
    data.overall != null ? data.overall.toFixed(1) : "\u2014"
  } of 10, verdict ${data.verdict_label}`

  // The mode toggle only renders when the component is uncontrolled OR
  // controlled but the consumer registered onModeChange — so the consumer
  // can opt out by providing `mode` without `onModeChange`.
  const showToggle = !isControlled || onModeChange !== undefined

  return (
    <div
      className={className}
      style={{
        position: "relative",
        width: size,
        height: size,
        // CSS custom property carrier for the Pulse breathing animation.
        ["--pulse-hz" as string]: `${(
          1 / Math.max(0.05, data.pulse_velocity_hz)
        ).toFixed(3)}s`,
      }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={ariaLabel}
        style={{ overflow: "visible" }}
      >
        <title>{ariaLabel}</title>
        {/* Cross-fade the two views using `t`. Each view short-circuits when
            its own visibility window is closed, so we don't pay for offscreen
            geometry during steady-state frames. */}
        <Signature
          pillars={data.pillars}
          overall={data.overall}
          pulseHz={data.pulse_velocity_hz}
          size={size}
          t={t}
          verdictBand={data.verdict_band}
          sectorOverlay={sectorOverlay}
          sectorMedians={data.sector_medians}
          onPillarTap={onPillarTap}
          highlightedPillar={highlightedPillar ?? null}
          uid={uid}
        />
        <Spectrum
          pillars={data.pillars}
          overall={data.overall}
          pulseHz={data.pulse_velocity_hz}
          size={size}
          t={t}
          verdictBand={data.verdict_band}
          verdictLabel={data.verdict_label}
          sectorOverlay={sectorOverlay}
          sectorMedians={data.sector_medians}
          onPillarTap={onPillarTap}
          highlightedPillar={highlightedPillar ?? null}
          uid={uid}
        />
      </svg>

      {showToggle && (
        <div
          style={{
            position: "absolute",
            top: 4,
            right: 4,
            display: "inline-flex",
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderRadius: 999,
            padding: 2,
            gap: 2,
          }}
          role="group"
          aria-label="Prism view mode"
        >
          {(["signature", "spectrum"] as PrismMode[]).map((m) => {
            const pressed = activeMode === m
            return (
              <button
                key={m}
                type="button"
                aria-pressed={pressed}
                onClick={() => handleToggle(m)}
                className="tap-target"
                style={{
                  minHeight: 28,
                  minWidth: 64,
                  padding: "4px 10px",
                  borderRadius: 999,
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  fontFamily:
                    "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
                  color: pressed ? "var(--color-bg)" : "var(--color-caption)",
                  background: pressed ? "var(--color-brand)" : "transparent",
                  border: "none",
                  cursor: "pointer",
                  transition: "background 200ms ease, color 200ms ease",
                }}
              >
                {m === "signature" ? "Signature" : "Spectrum"}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
