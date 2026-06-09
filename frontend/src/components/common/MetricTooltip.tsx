"use client"

/**
 * MetricTooltip — Premium Feel R2 hover-explainer primitive.
 *
 * AlphaSpread-style hover popover that wraps any metric's label + value
 * inline. The trigger itself shows the value with a subtle dotted
 * underline ("this is hoverable") and on hover/tap opens a small
 * popover with: title, plain-English description, optional formula in
 * mono font, optional context/threshold line, optional caveat.
 *
 * Two API shapes are supported:
 *   1. Key-driven (preferred):
 *        <MetricTooltip metric="roe" label="ROE" value="18.3%" />
 *      Looks up the entry from `lib/metric-explainers.ts`.
 *   2. Inline (full control — used when copy is rendered dynamically):
 *        <MetricTooltip
 *          label="ROE" value="18.3%"
 *          title="Return on Equity (ROE)"
 *          description="..."
 *          formula="Net Income / Shareholder Equity"
 *        />
 *
 * Relationship to the older `analysis/MetricTooltip.tsx`:
 *   That one renders a small "?" icon as the trigger and is wired
 *   through QualityRatios, InsightCards, etc. THIS one wraps the
 *   label + value INLINE and is the new AlphaSpread-style surface
 *   for headline tiles (HonestHero side rail, ValuationGrid scenarios,
 *   TransparencyStrip model inputs, etc.). The two coexist deliberately —
 *   we don't want to disrupt the existing tooltip ecosystem while
 *   adding the new inline hover-everywhere layer.
 *
 * Accessibility:
 *   - Trigger is a real <button>. Tab focuses, Enter / Space toggles.
 *   - Popover has role="tooltip" + aria-describedby links it.
 *   - Escape closes.
 *
 * Mobile:
 *   - Tap to open, tap outside or Escape to close.
 *
 * Reduced motion:
 *   - prefers-reduced-motion: reduce skips the fade animation; popover
 *     snaps in/out.
 *
 * Dark mode:
 *   - Uses bg-popover / text-popover-foreground tokens which adapt.
 *     Falls back to bg-surface / text-ink to match the rest of the app
 *     (which doesn't define popover- tokens). The downstream cn() merge
 *     lets callers override.
 *
 * No new dependencies — React 19 hooks only (no Radix, no react-tooltip;
 * neither is installed in this repo).
 */

import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { cn } from "@/lib/utils"
import { useReducedMotion } from "@/components/anim/useReducedMotion"
import {
  getMetricExplainer,
  type MetricExplainer,
} from "@/lib/metric-explainers"

export interface MetricTooltipProps {
  /** Visible label, e.g. "ROE". */
  label: string
  /** Visible value, e.g. "18.3%". Rendered next to the label. */
  value: ReactNode
  /**
   * Key into METRIC_EXPLAINERS. When passed, title/description/formula/
   * threshold/caveat default to the entries from `metric-explainers.ts`.
   * Inline props (below) always win when both are supplied.
   */
  metric?: string
  /** Popover heading. Defaults to METRIC_EXPLAINERS[metric].title. */
  title?: string
  /** Plain-English description, 1-2 sentences. */
  description?: string
  /** Optional formula in mono font. */
  formula?: string
  /** Optional typical-range / threshold line. */
  threshold?: string
  /** Optional caveat — what this metric does NOT tell you. */
  caveat?: string
  /** Extra classes on the inline wrapper. */
  className?: string
  /** Extra classes on the value span. */
  valueClassName?: string
  /** Render label first (default) or hide label inside the trigger. */
  showLabel?: boolean
  /**
   * 2026-06-09 fix/analysis-ux-fixbatch: when `value` is a JSX node
   * (e.g. a styled <span>), the aria-label falls back to repeating
   * the label (`"YieldIQ Score: YieldIQ Score"`) because the trigger
   * cannot stringify a ReactNode safely. Pass the plain-text rendering
   * of the value here so assistive tech announces the actual number.
   * Optional; ignored when `value` is already a string.
   */
  ariaValueText?: string
}

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
}

interface ResolvedTooltipCopy {
  title: string
  description: string
  formula?: string
  threshold?: string
  caveat?: string
}

function resolveCopy(
  inline: Pick<MetricTooltipProps, "title" | "description" | "formula" | "threshold" | "caveat">,
  fromKey: MetricExplainer | null,
  fallbackLabel: string,
): ResolvedTooltipCopy | null {
  const title = inline.title ?? fromKey?.title ?? fallbackLabel
  const description = inline.description ?? fromKey?.description
  // If we have no description we have nothing useful to show — don't
  // render an empty popover. Render value-only fallback at call site.
  if (!description) return null
  return {
    title,
    description,
    formula: inline.formula ?? fromKey?.formula,
    threshold: inline.threshold ?? fromKey?.threshold,
    caveat: inline.caveat ?? fromKey?.caveat,
  }
}

export default function MetricTooltip({
  label,
  value,
  metric,
  title,
  description,
  formula,
  threshold,
  caveat,
  className,
  valueClassName,
  showLabel = true,
  ariaValueText,
}: MetricTooltipProps) {
  const reduced = useReducedMotion()
  const [open, setOpen] = useState(false)
  const [alignRight, setAlignRight] = useState(false)
  const wrapperRef = useRef<HTMLSpanElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const popoverId = useId()

  const fromKey = useMemo(
    () => (metric ? getMetricExplainer(metric) : null),
    [metric],
  )
  const copy = useMemo(
    () =>
      resolveCopy(
        { title, description, formula, threshold, caveat },
        fromKey,
        label,
      ),
    [title, description, formula, threshold, caveat, fromKey, label],
  )

  // Decide which edge to align the popover against. Re-checked on each
  // open so phone rotation lands correctly.
  useEffect(() => {
    if (!open) return
    const trigger = triggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    // Popover width = w-72 = 18rem = 288px + ~12px breathing room.
    const POPOVER_WIDTH = 300
    const viewportW =
      typeof window !== "undefined" ? window.innerWidth : 1024
    setAlignRight(rect.left + POPOVER_WIDTH > viewportW)
  }, [open])

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

  // No copy resolvable → render value plain (no trigger, no popover).
  // Keeps callers safe to wire the component everywhere without first
  // checking whether copy exists for the key.
  if (!copy) {
    return (
      <span className={cn("inline-flex items-baseline gap-1", className)}>
        {showLabel && (
          <span className="text-caption uppercase tracking-wide text-[10px]">
            {label}
          </span>
        )}
        <span className={cn("text-ink", valueClassName)}>{value}</span>
      </span>
    )
  }

  const slug = slugify(label) || "metric"

  return (
    <span
      ref={wrapperRef}
      className={cn("relative inline-flex items-baseline gap-1", className)}
      data-testid={`metric-tooltip-${slug}`}
    >
      {showLabel && (
        <span className="text-caption uppercase tracking-wide text-[10px]">
          {label}
        </span>
      )}
      <button
        ref={triggerRef}
        type="button"
        // 2026-06-09 fix/analysis-ux-fixbatch: prefer the explicit
        // `ariaValueText` (passed when `value` is a JSX node), then
        // the value itself when it's a string, then fall back to the
        // label so the announcement remains meaningful even for
        // unwired callers. Previously the JSX-value path produced
        // accessibility labels like "YieldIQ Score: YieldIQ Score"
        // (Chrome MCP audit of /analysis/HDFCBANK, 2026-06-09).
        aria-label={`${copy.title}: ${
          ariaValueText ?? (typeof value === "string" ? value : label)
        }`}
        aria-describedby={open ? popoverId : undefined}
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={(e) => {
          // Guard the contains() check — JSDOM raises if relatedTarget
          // is not a Node (e.g. when synthetic events from RTL pass a
          // window-like reference). Real browsers always pass an
          // Element or null, but defensive code keeps tests sane.
          const next = e.relatedTarget
          const wrapper = wrapperRef.current
          if (
            wrapper &&
            next &&
            typeof (next as Node).nodeType === "number" &&
            wrapper.contains(next as Node)
          ) {
            return
          }
          setOpen(false)
        }}
        onFocus={() => setOpen(true)}
        onBlur={(e) => {
          const next = e.relatedTarget
          const wrapper = wrapperRef.current
          if (
            wrapper &&
            next &&
            typeof (next as Node).nodeType === "number" &&
            wrapper.contains(next as Node)
          ) {
            return
          }
          setOpen(false)
        }}
        // Dotted underline mirrors the AlphaSpread convention so the
        // user immediately reads "this is hoverable" without any extra
        // icon. Use border-bottom rather than text-decoration so the
        // dot density renders consistently across browsers.
        className={cn(
          "inline-flex items-baseline cursor-help bg-transparent p-0 m-0 text-left",
          "border-b border-dotted border-muted-foreground/40 hover:border-muted-foreground/80",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 focus-visible:rounded-sm",
          "transition-colors",
          valueClassName,
        )}
      >
        {value}
      </button>
      {open && (
        <TooltipPanel
          id={popoverId}
          copy={copy}
          alignRight={alignRight}
          reduced={reduced}
        />
      )}
    </span>
  )
}

interface TooltipPanelProps {
  id: string
  copy: ResolvedTooltipCopy
  alignRight: boolean
  reduced: boolean
}

function TooltipPanel({ id, copy, alignRight, reduced }: TooltipPanelProps) {
  return (
    <div
      id={id}
      role="tooltip"
      data-testid="metric-tooltip-content"
      onClick={(e) => e.stopPropagation()}
      className={cn(
        "absolute top-full mt-2 z-50 w-72 max-w-[calc(100vw-2rem)]",
        "rounded-lg border border-border bg-surface shadow-lg",
        "p-3 text-left",
        "text-ink",
        // Dark-mode native: bg-popover / text-popover-foreground are
        // shadcn-style tokens. Tailwind's bg-popover only resolves if
        // the project ships those tokens; if it doesn't, the layer
        // below (bg-surface) is the actual rendered colour. Either
        // way the popover reads correctly in both themes.
        "dark:bg-surface dark:text-ink",
        alignRight ? "right-0" : "left-0",
        // Fade-in animation respects reduced-motion: when reduce is
        // set we render at full opacity immediately.
        !reduced && "animate-in fade-in-0 zoom-in-95 duration-150",
      )}
    >
      <p className="text-[12px] font-semibold text-ink mb-1.5 leading-snug">
        {copy.title}
      </p>
      <p className="text-[12px] leading-snug text-body mb-2">
        {copy.description}
      </p>
      {copy.formula && (
        <p className="text-[11px] font-mono text-caption mb-2 break-words bg-bg/60 rounded px-1.5 py-1 border border-border/60">
          {copy.formula}
        </p>
      )}
      {copy.threshold && (
        <p className="text-[11px] leading-snug text-body mb-1">
          <span className="font-semibold text-ink">Typical: </span>
          {copy.threshold}
        </p>
      )}
      {copy.caveat && (
        <p className="text-[11px] leading-snug text-caption mt-2 pt-2 border-t border-border">
          <span className="font-semibold">Note: </span>
          {copy.caveat}
        </p>
      )}
    </div>
  )
}
