"use client"

/**
 * FundDetailTabs — the tab shell for the /funds/[scheme_code] Asset Page.
 *
 * A premium, sticky, horizontally-scrollable tab bar with an animated
 * underline, full keyboard support, and ARIA tablist semantics. Each
 * tab's content is supplied as a `ReactNode` by the server page (so the
 * server can pre-render every panel's data); only the ACTIVE panel is
 * mounted, matching the existing analysis/AnalysisTabs convention.
 *
 * URL-hash persistence (deep-linkable + back-button friendly) is done by
 * reading and writing `window.location.hash` directly — deliberately NOT
 * `useSearchParams`, which triggers the Next.js Suspense-bailout
 * prerender bug this app already hit on /search (see root CLAUDE.md
 * "Vercel preview build — /search page Suspense bailout").
 *
 * Accessibility:
 *   - role="tablist" with aria-label; each tab is role="tab" with
 *     aria-selected + aria-controls; panels are role="tabpanel" with
 *     aria-labelledby.
 *   - Roving tabindex: only the active tab is in the tab order; Arrow
 *     Left/Right (Home/End) move focus AND selection, wrapping at ends.
 *
 * Motion: the active-tab underline animates via framer-motion's shared
 * layoutId (matching the rest of the app). Respects reduced-motion.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { motion, useReducedMotion } from "framer-motion"

import { cn } from "@/lib/utils"

export interface FundTabDef {
  /** Stable key — also the URL hash fragment (e.g. "risk" → #risk). */
  key: string
  label: string
  content: ReactNode
}

interface Props {
  tabs: FundTabDef[]
  /** Default tab when no (or an unknown) hash is present. */
  initialKey?: string
}

/** Read the active tab key from the current URL hash, validated against
 *  the known tab keys. Returns null when the hash matches no tab. */
function keyFromHash(validKeys: string[]): string | null {
  if (typeof window === "undefined") return null
  const raw = window.location.hash.replace(/^#/, "").trim().toLowerCase()
  return validKeys.includes(raw) ? raw : null
}

export default function FundDetailTabs({ tabs, initialKey }: Props) {
  const reduced = useReducedMotion()
  const validKeys = tabs.map((t) => t.key)
  const fallback = initialKey && validKeys.includes(initialKey)
    ? initialKey
    : tabs[0]?.key ?? ""

  // Start from the fallback so server and first-paint client markup match
  // (no hydration mismatch); reconcile to the hash in an effect.
  const [active, setActive] = useState<string>(fallback)
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  // On mount + on hashchange (back/forward), sync the active tab to the
  // URL hash. Deep links like /funds/123#risk open straight on Risk.
  useEffect(() => {
    const sync = () => {
      const fromHash = keyFromHash(validKeys)
      if (fromHash) setActive(fromHash)
    }
    sync()
    window.addEventListener("hashchange", sync)
    return () => window.removeEventListener("hashchange", sync)
    // validKeys is derived from the static tabs prop; intentionally not a dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const select = useCallback(
    (key: string, opts?: { focus?: boolean }) => {
      setActive(key)
      // Write the hash without scrolling the page (replaceState keeps the
      // back button pointed at the previous PAGE, not every tab flip;
      // browser back across tabs still works via the previous page entry,
      // and the hashchange listener restores the tab on history nav).
      if (typeof window !== "undefined") {
        const url = `${window.location.pathname}${window.location.search}#${key}`
        window.history.replaceState(null, "", url)
      }
      if (opts?.focus) tabRefs.current[key]?.focus()
    },
    [],
  )

  // Roving keyboard navigation across the tab strip.
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent, idx: number) => {
      let next = -1
      switch (e.key) {
        case "ArrowRight":
        case "ArrowDown":
          next = (idx + 1) % tabs.length
          break
        case "ArrowLeft":
        case "ArrowUp":
          next = (idx - 1 + tabs.length) % tabs.length
          break
        case "Home":
          next = 0
          break
        case "End":
          next = tabs.length - 1
          break
        default:
          return
      }
      e.preventDefault()
      const key = tabs[next]?.key
      if (key) select(key, { focus: true })
    },
    [tabs, select],
  )

  const activeTab = tabs.find((t) => t.key === active) ?? tabs[0]

  return (
    <div>
      {/* Sticky, horizontally-scrollable tab bar */}
      <div
        className="sticky top-0 z-10 -mx-4 mb-2 border-b border-border bg-bg/95 px-4 backdrop-blur sm:-mx-6 sm:px-6"
        role="tablist"
        aria-label="Fund sections"
      >
        <div className="flex gap-1 overflow-x-auto no-scrollbar md:gap-2">
          {tabs.map((t, idx) => {
            const selected = t.key === active
            return (
              <button
                key={t.key}
                ref={(el) => {
                  tabRefs.current[t.key] = el
                }}
                type="button"
                role="tab"
                id={`fundtab-${t.key}`}
                aria-selected={selected}
                aria-controls={`fundpanel-${t.key}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => select(t.key)}
                onKeyDown={(e) => onKeyDown(e, idx)}
                className={cn(
                  "relative -mb-px shrink-0 whitespace-nowrap px-3 py-2.5 text-sm font-medium min-h-[44px] transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 focus-visible:rounded-sm",
                  selected
                    ? "text-brand"
                    : "text-caption hover:text-ink",
                )}
              >
                {t.label}
                {selected ? (
                  reduced ? (
                    <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand" />
                  ) : (
                    <motion.span
                      layoutId="fund-tab-underline"
                      className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand"
                      transition={{ type: "spring", stiffness: 480, damping: 38 }}
                    />
                  )
                ) : null}
              </button>
            )
          })}
        </div>
      </div>

      {/* Only the active panel is mounted. */}
      <section
        key={activeTab?.key}
        id={`fundpanel-${activeTab?.key}`}
        role="tabpanel"
        aria-labelledby={`fundtab-${activeTab?.key}`}
        tabIndex={0}
        className="pt-4 focus-visible:outline-none"
      >
        {activeTab?.content}
      </section>
    </div>
  )
}
