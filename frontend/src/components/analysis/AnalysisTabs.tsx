"use client"

import { useState, type ReactNode } from "react"
import { cn } from "@/lib/utils"

// TODO: swap to design tokens (bg-bg / bg-surface / text-ink / etc.) once Agent 1 lands

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
export default function AnalysisTabs({ tabs, initial, onTabChange }: AnalysisTabsProps) {
  const [active, setActive] = useState<AnalysisTabKey>(
    initial ?? tabs[0]?.key ?? "summary"
  )
  const activeTab = tabs.find((t) => t.key === active) ?? tabs[0]

  const handleChange = (key: AnalysisTabKey) => {
    setActive(key)
    onTabChange?.(key)
  }

  return (
    <div>
      {/* Sticky tab bar */}
      <div
        className="sticky top-0 z-10 -mx-4 px-4 bg-white/95 backdrop-blur border-b border-gray-100"
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
                    ? "border-blue-600 text-blue-700"
                    : "border-transparent text-gray-500 hover:text-gray-800"
                )}
              >
                {t.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Panel — only active tab is mounted */}
      <div
        id={`tabpanel-${activeTab?.key ?? "summary"}`}
        role="tabpanel"
        aria-labelledby={`tab-${activeTab?.key ?? "summary"}`}
        className="pt-4"
        key={activeTab?.key}
      >
        {activeTab?.content}
      </div>
    </div>
  )
}
