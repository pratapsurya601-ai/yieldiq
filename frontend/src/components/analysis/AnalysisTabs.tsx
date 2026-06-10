"use client"

import { useEffect, useState, type ReactNode } from "react"
import { AnimatePresence, motion, useReducedMotion } from "framer-motion"
import { cn } from "@/lib/utils"

export type AnalysisTabKey =
  | "summary"
  | "valuation"
  | "quality"
  | "financials"
  | "history"
  | "peers"

export interface AnalysisTabDef {
  key: AnalysisTabKey
  label: string
  content: ReactNode
}

interface AnalysisTabsProps {
  tabs: AnalysisTabDef[]
  initial?: AnalysisTabKey
  /**
   * Optional controlled tab — when set, AnalysisTabs syncs its internal
   * state to it on change. Lets external nav surfaces (e.g. the Premium
   * Feel R1 StickyAnalysisNav) drive tab switches without owning the
   * full state machine.
   */
  active?: AnalysisTabKey
  /** Fires on tab change — parent can defer expensive queries until their tab is opened. */
  onTabChange?: (key: AnalysisTabKey) => void
}

/**
 * Tabbed container for the analysis page.
 *
 * - Sticky tab bar at top of the content area (sticky top-0 z-10) so the
 *   tabs stay in view while the user scrolls within a long tab.
 * - Horizontally scrollable on mobile if tabs overflow.
 * - Only renders the active tab's content — inactive tabs are unmounted.
 * - No external dependency.
 */
export default function AnalysisTabs({ tabs, initial, active: controlledActive, onTabChange }: AnalysisTabsProps) {
  const [active, setActive] = useState<AnalysisTabKey>(
    initial ?? tabs[0]?.key ?? "summary"
  )
  // Sync to the controlled active prop. Lets the sticky pill-nav drive
  // tab switches without owning the local state machine. Defer the flip
  // through a microtask so the `react-hooks/set-state-in-effect` lint
  // rule (cascading-render warning) is satisfied — same pattern as the
  // useEffect microtask used in AnalysisBody for the personalization
  // style picker.
  useEffect(() => {
    if (controlledActive && controlledActive !== active) {
      queueMicrotask(() => setActive(controlledActive))
    }
  }, [controlledActive, active])
  const activeTab = tabs.find((t) => t.key === active) ?? tabs[0]

  const handleChange = (key: AnalysisTabKey) => {
    setActive(key)
    onTabChange?.(key)
  }

  return (
    <div>
      {/* Sticky tab bar */}
      <div
        className="sticky top-0 z-10 -mx-4 px-4 bg-bg/95 backdrop-blur border-b border-border"
        role="tablist"
        aria-label="Analysis sections"
      >
        <div className="flex gap-1 overflow-x-auto no-scrollbar md:gap-2">
          {tabs.map((t) => {
            const selected = t.key === active
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`tabpanel-${t.key}`}
                id={`tab-${t.key}`}
                onClick={() => handleChange(t.key)}
                className={cn(
                  "shrink-0 whitespace-nowrap px-3 py-2.5 text-sm font-medium min-h-[44px] border-b-2 -mb-px transition",
                  selected
                    ? "border-brand text-brand"
                    : "border-transparent text-caption hover:text-ink"
                )}
              >
                {t.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Panel — only active tab is mounted. The wrapping <section> also
          carries `id="section-<key>"` so the Premium Feel R1
          StickyAnalysisNav can `scrollIntoView` directly to the active
          tab content even when the tab swap re-mounts the children.

          Sprint B.2 (2026-06-10): wrap the active panel in an
          AnimatePresence so swapping between Summary / Valuation /
          Quality / Financials / History / Peers no longer hard-cuts.
          We fade + lift 6px and let the next panel fade in on top
          (mode="popLayout") so the page reads as one continuous
          surface, not 6 different products glued together. Honors
          prefers-reduced-motion via useReducedMotion. */}
      <PanelTransition tabKey={activeTab?.key ?? "summary"} content={activeTab?.content} />
    </div>
  )
}

interface PanelTransitionProps {
  tabKey: string
  content: ReactNode
}

function PanelTransition({ tabKey, content }: PanelTransitionProps) {
  const reduceMotion = useReducedMotion()
  // When the user prefers reduced motion, fall back to an instant swap —
  // a snap-cut is friendlier than a fade for the affected audience.
  if (reduceMotion) {
    return (
      <section
        id={`section-${tabKey}`}
        aria-labelledby={`tab-${tabKey}`}
        role="tabpanel"
        className="pt-4"
        key={tabKey}
        data-tabpanel-key={tabKey}
      >
        {content}
      </section>
    )
  }
  return (
    <AnimatePresence mode="popLayout" initial={false}>
      <motion.section
        id={`section-${tabKey}`}
        aria-labelledby={`tab-${tabKey}`}
        role="tabpanel"
        className="pt-4"
        key={tabKey}
        data-tabpanel-key={tabKey}
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.18, ease: [0.4, 0.0, 0.2, 1] }}
      >
        {content}
      </motion.section>
    </AnimatePresence>
  )
}
