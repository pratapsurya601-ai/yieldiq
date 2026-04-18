"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Prism from "./Prism"
import PrismScrubber from "./PrismScrubber"
import { fetchPrism } from "@/lib/prism"
import {
  type HistoryQuarter,
  fetchHexHistory,
  interpolateQuarter,
  quarterLabel,
  synthesizePrismData,
} from "@/lib/prismHistory"
import { capturePngFromSvg, isPngCaptureSupported } from "@/lib/gifExport"
import type { PrismData } from "./types"

interface PrismTimeMachineProps {
  ticker: string
  isOpen: boolean
  onClose: () => void
}

/** Cubic ease-in-out used for the auto-play sweep. Keeps the opening and
 *  closing "inhale/exhale" feel consistent with the rest of the Prism. */
function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

const PLAY_DURATION_MS = 8_000

/**
 * `<PrismTimeMachine>` — a modal that lets the user scrub or auto-play
 * through N quarters of Prism history. The Prism component is reused
 * as-is; all we do at this layer is:
 *
 *   1. Fetch the base PrismData once (for per-pillar metadata) in parallel
 *      with the history payload.
 *   2. On every animation tick, synthesize a PrismData from the base +
 *      interpolated history quarter and hand it to <Prism>.
 *   3. Offer a single-frame PNG export of whatever is currently rendered.
 *
 * The component is expected to be code-split by its consumer via
 * `next/dynamic({ ssr: false })` so the 12-quarter modal doesn't bloat the
 * initial analysis page bundle.
 */
export default function PrismTimeMachine({
  ticker,
  isOpen,
  onClose,
}: PrismTimeMachineProps) {
  const [quarters, setQuarters] = useState<HistoryQuarter[] | null>(null)
  const [base, setBase] = useState<PrismData | null>(null)
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">(
    "idle",
  )
  const [value, setValue] = useState<number>(0)
  const [playing, setPlaying] = useState<boolean>(false)
  const [exporting, setExporting] = useState<boolean>(false)
  const [exportMsg, setExportMsg] = useState<string | null>(null)

  const prismHostRef = useRef<HTMLDivElement | null>(null)

  // Fetch history + base Prism data whenever the modal opens for the first
  // time or the ticker changes. We avoid refetching if the user reopens the
  // modal for the same ticker — quarterly data is, by definition, stable.
  useEffect(() => {
    if (!isOpen) return
    if (status === "loading" || status === "ready") return
    let cancelled = false
    setStatus("loading")
    ;(async () => {
      try {
        const [h, b] = await Promise.all([
          fetchHexHistory(ticker, 12),
          fetchPrism(ticker),
        ])
        if (cancelled) return
        if (!h || h.length === 0) {
          setStatus("error")
          return
        }
        setQuarters(h)
        setBase(b)
        setValue(h.length - 1) // Start on the most recent quarter.
        setStatus("ready")
      } catch {
        if (!cancelled) setStatus("error")
      }
    })()
    return () => {
      cancelled = true
    }
  }, [isOpen, ticker, status])

  // Esc to close. Only bound while the modal is open to avoid leaking the
  // listener when the consumer unmounts us lazily.
  useEffect(() => {
    if (!isOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [isOpen, onClose])

  // RAF-driven auto-play loop. We animate `value` from 0 → last over
  // PLAY_DURATION_MS with an ease-in-out curve. The loop tears itself down
  // cleanly if the user pauses mid-play or closes the modal.
  useEffect(() => {
    if (!playing || !quarters || quarters.length < 2) return
    const last = quarters.length - 1
    const start = performance.now()
    // If resuming from a partial position, bias the time origin so the
    // sweep feels continuous rather than jumping back to the first tick.
    const startValue = value >= last ? 0 : value
    const startProgress = startValue / last
    let raf = 0
    const step = (now: number) => {
      const elapsed = now - start
      const raw = Math.min(
        1,
        startProgress + elapsed / PLAY_DURATION_MS,
      )
      const eased = easeInOutCubic(raw)
      setValue(eased * last)
      if (raw < 1) {
        raf = requestAnimationFrame(step)
      } else {
        setPlaying(false)
      }
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, quarters])

  // Build the PrismData for the current scrubber position. Interpolates
  // between adjacent quarters whenever `value` sits sub-tick.
  const currentData: PrismData | null = useMemo(() => {
    if (!quarters || !base) return null
    const last = quarters.length - 1
    if (last < 0) return null
    const clamped = Math.max(0, Math.min(last, value))
    const lo = Math.floor(clamped)
    const hi = Math.min(last, lo + 1)
    const t = clamped - lo
    const q =
      lo === hi
        ? quarters[lo]
        : interpolateQuarter(quarters[lo], quarters[hi], t)
    return synthesizePrismData(base, q)
  }, [quarters, base, value])

  const currentQuarterLabel = useMemo(() => {
    if (!quarters) return ""
    const idx = Math.round(Math.max(0, Math.min(quarters.length - 1, value)))
    return quarters[idx] ? quarterLabel(quarters[idx].quarter_end) : ""
  }, [quarters, value])

  const handleRecord = useCallback(async () => {
    if (!prismHostRef.current) return
    setExporting(true)
    setExportMsg(null)
    try {
      const safeTicker = ticker.replace(/[^A-Za-z0-9_-]/g, "")
      const safeQuarter = currentQuarterLabel.replace(/[^A-Za-z0-9_-]/g, "-")
      await capturePngFromSvg(
        prismHostRef.current,
        `${safeTicker}-timeMachine-${safeQuarter || "frame"}.png`,
      )
      setExportMsg("Frame saved to downloads.")
    } catch {
      setExportMsg("Could not save frame on this browser.")
    } finally {
      setExporting(false)
      setTimeout(() => setExportMsg(null), 3_500)
    }
  }, [ticker, currentQuarterLabel])

  if (!isOpen) return null

  const canExport = isPngCaptureSupported()

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Prism time machine"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 backdrop-blur-sm p-0 sm:p-6"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="bg-bg w-full h-full sm:h-auto sm:max-w-xl sm:rounded-2xl border border-border shadow-2xl flex flex-col overflow-hidden"
      >
        {/* Header row: title + close */}
        <div className="flex items-start justify-between px-5 pt-5 pb-3 border-b border-border">
          <div className="min-w-0">
            <p className="font-display text-base font-semibold text-ink">
              Time Machine · {ticker.replace(".NS", "").replace(".BO", "")}
            </p>
            <p className="text-xs text-caption mt-0.5 truncate">
              {base
                ? `Watch ${base.company_name} evolve over ${
                    quarters?.length ?? 12
                  } quarters`
                : "Watch this stock evolve over 12 quarters"}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close time machine"
            onClick={onClose}
            className="inline-flex items-center justify-center w-11 h-11 -mr-2 -mt-2 rounded-lg text-caption hover:text-ink hover:bg-surface active:scale-95 transition shrink-0"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              aria-hidden
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
          {status === "loading" && (
            <div className="flex flex-col items-center justify-center py-10">
              <div className="w-[280px] h-[280px] rounded-full bg-surface animate-pulse" />
              <p className="mt-4 text-xs text-caption">Loading history…</p>
            </div>
          )}

          {status === "error" && (
            <div className="rounded-xl border border-border bg-surface p-5 text-center">
              <p className="text-sm font-medium text-ink">
                Time Machine data not available for this stock yet.
              </p>
              <p className="mt-2 text-xs text-caption leading-relaxed">
                Top 500 stocks by market cap get weekly history refresh.
                We&rsquo;re expanding coverage over the coming quarters.
              </p>
            </div>
          )}

          {status === "ready" && currentData && quarters && (
            <>
              <div className="flex items-center justify-center">
                <div ref={prismHostRef}>
                  <Prism
                    data={currentData}
                    defaultMode="signature"
                    size={320}
                    firstView={false}
                  />
                </div>
              </div>

              <PrismScrubber
                quarters={quarters}
                value={value}
                onChange={(v) => {
                  if (playing) setPlaying(false)
                  setValue(v)
                }}
                playing={playing}
                onPlayToggle={() => setPlaying((p) => !p)}
              />

              <div className="flex items-center justify-between gap-3">
                <div className="text-[11px] text-caption leading-tight">
                  Drag, use ←/→ arrows, or press Space to play.
                </div>
                {canExport && (
                  <button
                    type="button"
                    onClick={handleRecord}
                    disabled={exporting}
                    className="inline-flex items-center justify-center min-h-[44px] px-3 py-2 rounded-lg bg-surface border border-border text-xs font-semibold text-ink hover:bg-bg active:scale-[0.98] transition disabled:opacity-60"
                    aria-label="Save current frame as PNG"
                  >
                    {exporting ? "Saving…" : "Save frame"}
                  </button>
                )}
              </div>
              {exportMsg && (
                <p
                  role="status"
                  className="text-[11px] text-brand text-right -mt-2"
                >
                  {exportMsg}
                </p>
              )}
            </>
          )}

          <p className="text-[11px] text-caption text-center pt-2">
            Model estimate. Not investment advice.
          </p>
        </div>
      </div>
    </div>
  )
}
