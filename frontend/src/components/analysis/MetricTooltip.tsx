"use client"

/**
 * MetricTooltip — reusable hover/tap popover for metric labels.
 *
 * Usage:
 *   <MetricTooltip metricKey="roce">ROCE</MetricTooltip>
 *
 * Renders `children` followed by a subtle "?" icon. Hovering the icon
 * (desktop) or tapping it (mobile) reveals a small popover with a
 * plain-English explanation pulled from `metric_explanations.ts`.
 *
 * Accessibility:
 *   - Trigger is a real <button> with aria-describedby pointing at the
 *     popover.
 *   - Popover has role="tooltip".
 *   - Escape closes it. Tab moves focus as expected; focus-visible
 *     ring on the trigger.
 *
 * Mobile:
 *   - Tap-to-toggle. Tap outside (document listener) or the trigger
 *     again to close.
 *
 * Positioning:
 *   - Popover renders absolutely below the trigger. If it would
 *     overflow the right edge of the viewport we flip it to the left;
 *     we don't try to flip vertically (keeps the logic simple and
 *     avoids reflow jitter).
 *
 * No new dependencies — Tailwind utility classes + React state only.
 */

import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import {
  getExplanation,
  type MetricExplanation,
} from "@/lib/metric_explanations"
import { cn } from "@/lib/utils"

interface MetricTooltipProps {
  /** Key into METRIC_EXPLANATIONS (e.g. "roce", "debt_ebitda"). */
  metricKey: string
  /** Usually the metric label text — rendered before the "?" icon. */
  children: ReactNode
  /** Extra classes on the outer wrapper. */
  className?: string
  /** Optional override for the popover heading colour. */
  accentClassName?: string
}

function Popover({
  id,
  explanation,
  alignRight,
}: {
  id: string
  explanation: MetricExplanation
  alignRight: boolean
}) {
  return (
    <div
      id={id}
      role="tooltip"
      className={cn(
        "absolute top-full mt-2 z-50 w-72 max-w-[calc(100vw-2rem)]",
        "rounded-lg border border-border bg-surface shadow-lg",
        "p-3 text-left",
        // Normal text colours (inherit from .text-ink / .text-caption)
        "text-ink",
        alignRight ? "right-0" : "left-0",
      )}
      // Prevent pointer-events on the popover from bubbling into
      // document-level "tap outside" detection
      onClick={(e) => e.stopPropagation()}
    >
      <p className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1">
        {explanation.title}
      </p>
      <p className="text-[12px] leading-snug text-body mb-2">
        {explanation.oneLine}
      </p>
      {explanation.formula && (
        <p className="text-[11px] font-mono text-caption mb-2 break-words">
          {explanation.formula}
        </p>
      )}
      <p className="text-[12px] leading-snug text-body">
        <span className="font-semibold text-ink">Good: </span>
        {explanation.good}
      </p>
      {explanation.sectorNote && (
        <p className="text-[11px] leading-snug text-caption mt-2 pt-2 border-t border-border">
          <span className="font-semibold">Sector note: </span>
          {explanation.sectorNote}
        </p>
      )}
    </div>
  )
}

export default function MetricTooltip({
  metricKey,
  children,
  className,
  accentClassName,
}: MetricTooltipProps) {
  const explanation = getExplanation(metricKey)
  const [open, setOpen] = useState(false)
  const [alignRight, setAlignRight] = useState(false)
  const wrapperRef = useRef<HTMLSpanElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const popoverId = useId()

  // Decide which edge to align the popover against based on where the
  // trigger sits in the viewport. Runs once per open event — we don't
  // observe resize, but we do re-check on each open which covers the
  // phone-rotation case.
  useEffect(() => {
    if (!open) return
    const trigger = triggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    // Popover width = w-72 = 18rem = 288px (+ small margin)
    const POPOVER_WIDTH = 300
    const viewportW =
      typeof window !== "undefined" ? window.innerWidth : 1024
    // If the popover would spill over the right edge when left-aligned
    // to the trigger, flip to right-aligned instead.
    setAlignRight(rect.left + POPOVER_WIDTH > viewportW)
  }, [open])

  // Escape to close + tap-outside to close
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false)
    }
    function onDocClick(e: MouseEvent) {
      const node = wrapperRef.current
      if (!node) return
      if (!node.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("keydown", onKey)
    document.addEventListener("mousedown", onDocClick)
    return () => {
      document.removeEventListener("keydown", onKey)
      document.removeEventListener("mousedown", onDocClick)
    }
  }, [open])

  // Fall back to plain children when we have no copy for this key.
  // Better to hide the "?" than to show a useless empty popover.
  if (!explanation) {
    return <span className={className}>{children}</span>
  }

  return (
    <span
      ref={wrapperRef}
      className={cn("relative inline-flex items-center gap-1", className)}
    >
      {children}
      <button
        ref={triggerRef}
        type="button"
        aria-label={`What is ${explanation.title}?`}
        aria-describedby={open ? popoverId : undefined}
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={(e) => {
          // Only close on mouse leave if the pointer isn't entering
          // the popover itself (relatedTarget is inside the wrapper).
          const next = e.relatedTarget as Node | null
          if (next && wrapperRef.current?.contains(next)) return
          setOpen(false)
        }}
        onFocus={() => setOpen(true)}
        onBlur={(e) => {
          const next = e.relatedTarget as Node | null
          if (next && wrapperRef.current?.contains(next)) return
          setOpen(false)
        }}
        className={cn(
          "inline-flex items-center justify-center",
          "w-3.5 h-3.5 rounded-full text-[9px] font-bold leading-none",
          "border border-current",
          "text-caption hover:text-brand focus-visible:text-brand",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1",
          "transition-colors",
          accentClassName,
        )}
      >
        ?
      </button>
      {open && (
        <Popover
          id={popoverId}
          explanation={explanation}
          alignRight={alignRight}
        />
      )}
    </span>
  )
}
