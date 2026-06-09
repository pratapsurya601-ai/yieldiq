"use client"
import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"

export interface StickyAnalysisNavSection {
  /** Stable key used for the URL hash and data-testid. */
  id: string
  /** Pill label rendered in the nav. */
  label: string
}

export interface StickyAnalysisNavProps {
  /** Sections in display order. */
  sections: StickyAnalysisNavSection[]
  /**
   * Optional CSS selector for the hero element. The nav stays static
   * (top:auto) until the user scrolls past the hero, then snaps to
   * sticky top:0 with a glass background. When omitted, the nav is
   * sticky from first paint.
   */
  heroSelector?: string
  /**
   * Optional callback fired when the user clicks a pill OR when the
   * scroll-position-based active section changes. Lets a parent that
   * owns tabbed content (AnalysisTabs) switch tabs in lockstep.
   */
  onSelect?: (id: string) => void
  /** Section to highlight on first paint when no scroll has happened. */
  defaultActive?: string
  className?: string
}

/**
 * Premium-feel Round 1 — sticky horizontal pill nav for the analysis
 * page. Behaviour:
 *
 *   - Renders pills for each section in order. Active pill is
 *     highlighted in brand blue; inactive pills are caption-toned.
 *   - Pill click smooth-scrolls the section into view AND fires the
 *     onSelect callback so a tab container can swap content.
 *   - Active pill auto-tracks the scroll position: an
 *     IntersectionObserver watches each #section anchor and the most
 *     visible one wins.
 *   - The nav itself stays static-position until the user scrolls
 *     past the hero, then attaches a "is-sticky" class that turns
 *     on the glass background + bottom border. Avoids the nav
 *     hovering over the page from first paint, which would compete
 *     with the editorial hero.
 *   - Mobile: horizontally scrollable with overflow-x-auto so all
 *     pills are reachable even at 360px.
 *   - SSR-safe: no window access at render time, only inside effects.
 */
export default function StickyAnalysisNav({
  sections,
  heroSelector,
  onSelect,
  defaultActive,
  className,
}: StickyAnalysisNavProps) {
  const navRef = useRef<HTMLElement | null>(null)
  const pillRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const [active, setActive] = useState<string>(
    defaultActive ?? sections[0]?.id ?? "",
  )
  // Toggled true once the user scrolls past the hero. Drives the
  // glass-background "stuck" visual treatment so the nav reads as
  // chrome once it leaves the document flow.
  const [stuck, setStuck] = useState<boolean>(!heroSelector)
  // Internal flag — true while a click-driven smooth scroll is in
  // flight. Suppresses the IntersectionObserver-driven active
  // updates so the pill the user clicked stays highlighted instead
  // of flickering to whichever section happens to cross the
  // threshold mid-scroll.
  const clickScrollingRef = useRef<boolean>(false)
  const clickScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Hero-pass detection ─────────────────────────────────────────
  useEffect(() => {
    if (!heroSelector) return
    if (typeof window === "undefined") return
    const heroEl = document.querySelector(heroSelector)
    // Sync paths flow through queueMicrotask so the
    // `react-hooks/set-state-in-effect` lint rule (cascading-render
    // warning) stays clean. Same pattern useReducedMotion uses with
    // useSyncExternalStore-style indirection.
    if (!heroEl) {
      queueMicrotask(() => setStuck(true))
      return
    }
    if (typeof IntersectionObserver === "undefined") {
      queueMicrotask(() => setStuck(true))
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          // entry.isIntersecting is true while the hero is on screen.
          // We want the "stuck" glass treatment ONLY when the hero is
          // off-screen above the viewport.
          setStuck(!entry.isIntersecting)
        }
      },
      { threshold: 0, rootMargin: "0px 0px -90% 0px" },
    )
    observer.observe(heroEl)
    return () => observer.disconnect()
  }, [heroSelector])

  // ── Active-section tracking ─────────────────────────────────────
  useEffect(() => {
    if (typeof window === "undefined") return
    if (typeof IntersectionObserver === "undefined") return
    // Track which sections are visible and pick the topmost.
    const visibility = new Map<string, number>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.target.id
          if (!id) continue
          visibility.set(id, entry.isIntersecting ? entry.intersectionRatio : 0)
        }
        if (clickScrollingRef.current) return
        // Pick the section with highest intersection ratio (most
        // visible). Ties broken by section order.
        let bestId = ""
        let bestRatio = 0
        for (const sec of sections) {
          const r = visibility.get(sec.id) ?? 0
          if (r > bestRatio) {
            bestRatio = r
            bestId = sec.id
          }
        }
        if (bestId && bestId !== active) setActive(bestId)
      },
      {
        // -30% top -> the section currently sitting just below the
        // sticky nav wins, not the one that just scrolled off.
        rootMargin: "-30% 0px -55% 0px",
        threshold: [0, 0.15, 0.3, 0.6, 1],
      },
    )
    for (const sec of sections) {
      const el = document.getElementById(sec.id)
      if (el) observer.observe(el)
    }
    return () => observer.disconnect()
  }, [sections, active])

  // ── Keep the active pill scrolled into view on mobile ───────────
  useEffect(() => {
    const pill = pillRefs.current[active]
    if (!pill) return
    if (typeof pill.scrollIntoView !== "function") return
    // Only horizontal alignment — vertical "nearest" so the page
    // scroll never gets clobbered by the pill auto-scroll.
    pill.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" })
  }, [active])

  // ── Click handler ───────────────────────────────────────────────
  const handlePillClick = (id: string) => {
    setActive(id)
    onSelect?.(id)
    if (typeof window === "undefined") return
    // Lock the IO-driven active tracker for ~800ms so the clicked
    // pill stays highlighted while the page is mid-smooth-scroll.
    clickScrollingRef.current = true
    if (clickScrollTimerRef.current) clearTimeout(clickScrollTimerRef.current)
    clickScrollTimerRef.current = setTimeout(() => {
      clickScrollingRef.current = false
    }, 900)
    // Schedule the scroll on the next tick so any parent that just
    // swapped tabs (via onSelect) gets a chance to mount the target
    // before we ask the browser to scroll to it. requestAnimationFrame
    // beats setTimeout(0) here because it aligns with React commits.
    const targetEl = document.getElementById(id)
    if (targetEl) {
      requestAnimationFrame(() => {
        targetEl.scrollIntoView({ behavior: "smooth", block: "start" })
      })
      return
    }
    // Target didn't exist yet (parent tab hasn't mounted) — try once
    // more on the next animation frame so newly-rendered sections get
    // a chance to receive focus.
    requestAnimationFrame(() => {
      const lateEl = document.getElementById(id)
      if (lateEl) {
        lateEl.scrollIntoView({ behavior: "smooth", block: "start" })
      }
    })
  }

  return (
    <nav
      ref={navRef}
      data-testid="sticky-analysis-nav"
      data-stuck={stuck ? "true" : "false"}
      aria-label="Analysis sections"
      className={cn(
        "sticky top-0 z-20 -mx-4 px-4 transition-colors duration-200",
        stuck
          ? "bg-surface/80 backdrop-blur-md border-b border-border supports-[backdrop-filter]:bg-surface/70"
          : "bg-transparent border-b border-transparent",
        className,
      )}
    >
      <ul className="flex gap-1.5 md:gap-2 overflow-x-auto no-scrollbar py-2.5">
        {sections.map((sec) => {
          const isActive = sec.id === active
          return (
            <li key={sec.id} className="shrink-0">
              <button
                ref={(el) => {
                  pillRefs.current[sec.id] = el
                }}
                type="button"
                data-testid={`nav-pill-${sec.id}`}
                data-active={isActive ? "true" : "false"}
                onClick={() => handlePillClick(sec.id)}
                aria-current={isActive ? "true" : undefined}
                className={cn(
                  "inline-flex items-center whitespace-nowrap rounded-full px-3.5 py-1.5",
                  "text-xs font-medium transition-all duration-200 ease-out",
                  isActive
                    ? "bg-brand text-white shadow-sm hover:opacity-90"
                    : "text-caption hover:text-ink hover:bg-bg/70",
                )}
              >
                {sec.label}
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

export { StickyAnalysisNav }
