"use client"
/**
 * StickyTableOfContents — premium-feel sidebar navigator for the
 * analysis page. Sprint B.2 (2026-06-10).
 *
 * Behaviour:
 *   - Desktop (>= 1280px): right-rail vertical list of every major
 *     section. A thin vertical guide line on the left edge marks the
 *     active item with a brand-colored dot + bolder label.
 *   - Desktop (768-1279px): hidden — the existing horizontal sticky
 *     pill nav still owns navigation in this range.
 *   - Mobile (< 768px): hidden by default. A floating "≡ Sections"
 *     button sits bottom-right; tapping it opens a slide-in panel
 *     listing every section. Tapping a section closes the panel and
 *     scrolls to the target.
 *
 *   - Active-section tracking: a single IntersectionObserver with a
 *     thin "activation band" (top:-30%, bottom:-65%) marks whichever
 *     section's top is currently inside the band. Topmost-in-order
 *     wins ties. When no section is in the band, the previous active
 *     item is preserved (no flicker).
 *
 *   - Sections are discovered via `document.querySelectorAll(
 *     '[data-toc-section]')`. Each section component is expected to
 *     add `data-toc-section="<label>"` and a stable `id` to its
 *     outermost wrapper. The component re-reads the section list on
 *     mount; if a tab swap inserts new sections, callers can dispatch
 *     a `toc-sections-changed` window event to force a re-scan.
 *
 *   - SSR-safe: no window access during render.
 */
import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"

export interface TocSection {
  id: string
  label: string
}

export interface StickyTableOfContentsProps {
  /**
   * Optional explicit section list. When omitted, the component
   * scans the DOM for `[data-toc-section]` elements on mount.
   */
  sections?: TocSection[]
  className?: string
}

const ACTIVE_BAND_ROOT_MARGIN = "-30% 0px -65% 0px"

function discoverSectionsFromDOM(): TocSection[] {
  if (typeof document === "undefined") return []
  const els = Array.from(
    document.querySelectorAll<HTMLElement>("[data-toc-section]"),
  )
  const seen = new Set<string>()
  const out: TocSection[] = []
  for (const el of els) {
    const id = el.id || el.getAttribute("data-toc-id") || ""
    const label =
      el.getAttribute("data-toc-section") || el.getAttribute("aria-label") || ""
    if (!id || !label) continue
    if (seen.has(id)) continue
    seen.add(id)
    out.push({ id, label })
  }
  return out
}

export default function StickyTableOfContents({
  sections: explicitSections,
  className,
}: StickyTableOfContentsProps) {
  const [discovered, setDiscovered] = useState<TocSection[]>(
    explicitSections ?? [],
  )
  const [active, setActive] = useState<string>("")
  const [mobileOpen, setMobileOpen] = useState<boolean>(false)
  const clickScrollingRef = useRef<boolean>(false)
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const sections = explicitSections ?? discovered

  // ── DOM-driven section discovery ────────────────────────────────
  useEffect(() => {
    if (explicitSections && explicitSections.length > 0) return
    if (typeof window === "undefined") return
    const rescan = () => {
      const next = discoverSectionsFromDOM()
      setDiscovered((prev) => {
        if (
          prev.length === next.length &&
          prev.every((p, i) => p.id === next[i]?.id && p.label === next[i]?.label)
        ) {
          return prev
        }
        return next
      })
    }
    // Initial scan deferred through a microtask so any sibling Reveal /
    // tab content has a tick to mount its anchors.
    queueMicrotask(rescan)
    window.addEventListener("toc-sections-changed", rescan)
    return () => window.removeEventListener("toc-sections-changed", rescan)
  }, [explicitSections])

  // Default-active = first section on first paint, so the highlight
  // always lands somewhere visible even before the user scrolls.
  useEffect(() => {
    if (!active && sections[0]?.id) setActive(sections[0].id)
  }, [sections, active])

  // ── IntersectionObserver-driven active-section tracking ──────────
  useEffect(() => {
    if (typeof window === "undefined") return
    if (typeof IntersectionObserver === "undefined") return
    if (sections.length === 0) return
    const inBand = new Set<string>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = (entry.target as HTMLElement).id
          if (!id) continue
          if (entry.isIntersecting) inBand.add(id)
          else inBand.delete(id)
        }
        if (clickScrollingRef.current) return
        if (inBand.size === 0) return
        for (const sec of sections) {
          if (inBand.has(sec.id)) {
            setActive((prev) => (prev === sec.id ? prev : sec.id))
            break
          }
        }
      },
      { rootMargin: ACTIVE_BAND_ROOT_MARGIN, threshold: 0 },
    )
    for (const sec of sections) {
      const el = document.getElementById(sec.id)
      if (el) observer.observe(el)
    }
    return () => observer.disconnect()
  }, [sections])

  const handleClick = (id: string) => {
    setActive(id)
    setMobileOpen(false)
    if (typeof window === "undefined") return
    clickScrollingRef.current = true
    if (clickTimerRef.current) clearTimeout(clickTimerRef.current)
    clickTimerRef.current = setTimeout(() => {
      clickScrollingRef.current = false
    }, 900)
    const targetEl = document.getElementById(id)
    if (!targetEl) return
    requestAnimationFrame(() => {
      targetEl.scrollIntoView({ behavior: "smooth", block: "start" })
    })
  }

  if (sections.length === 0) return null

  return (
    <>
      {/* ── Desktop right rail (>= xl/1280px) ────────────────────── */}
      <aside
        data-testid="sticky-toc-desktop"
        aria-label="Page sections"
        className={cn(
          "hidden xl:block",
          "fixed top-32 right-6 z-20",
          "w-52 max-h-[70vh] overflow-y-auto",
          // Thin vertical line on the left edge of the rail. No card
          // chrome — blends with the page.
          "border-l border-border/60 pl-3 py-1",
          className,
        )}
      >
        <p className="text-[10px] uppercase tracking-[0.12em] font-semibold text-caption mb-2">
          On this page
        </p>
        <ul className="space-y-0.5">
          {sections.map((sec) => {
            const isActive = sec.id === active
            return (
              <li key={sec.id}>
                <button
                  type="button"
                  data-testid={`toc-item-${sec.id}`}
                  data-active={isActive ? "true" : "false"}
                  onClick={() => handleClick(sec.id)}
                  aria-current={isActive ? "true" : undefined}
                  className={cn(
                    "group relative block w-full text-left text-[12px] leading-snug",
                    "py-1 pl-2 pr-1 transition-colors duration-150 ease-out rounded",
                    isActive
                      ? "text-ink font-semibold"
                      : "text-caption hover:text-ink",
                  )}
                >
                  <span
                    aria-hidden
                    className={cn(
                      "absolute -left-3 top-1/2 -translate-y-1/2 h-1.5 w-1.5 rounded-full transition-all duration-150",
                      isActive
                        ? "bg-brand scale-100"
                        : "bg-transparent scale-75 group-hover:bg-border",
                    )}
                  />
                  {sec.label}
                </button>
              </li>
            )
          })}
        </ul>
      </aside>

      {/* ── Mobile floating button (< md/768px) ──────────────────── */}
      <button
        type="button"
        data-testid="sticky-toc-mobile-button"
        aria-label={mobileOpen ? "Close section navigator" : "Open section navigator"}
        aria-expanded={mobileOpen}
        onClick={() => setMobileOpen((v) => !v)}
        className={cn(
          "md:hidden fixed bottom-20 right-4 z-30",
          "inline-flex items-center justify-center gap-1.5",
          "h-11 px-3.5 rounded-full",
          "bg-ink text-bg shadow-lg",
          "text-xs font-semibold",
          "active:scale-95 transition-transform",
        )}
      >
        <svg
          className="w-4 h-4"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4 6h16M4 12h16M4 18h16"
          />
        </svg>
        Sections
      </button>

      {/* ── Mobile slide-in panel ────────────────────────────────── */}
      {mobileOpen && (
        <div
          data-testid="sticky-toc-mobile-panel"
          role="dialog"
          aria-modal="true"
          aria-label="Page sections"
          className="md:hidden fixed inset-0 z-40"
        >
          <div
            aria-hidden
            onClick={() => setMobileOpen(false)}
            className="absolute inset-0 bg-ink/40"
          />
          <div className="absolute right-0 top-0 bottom-0 w-72 max-w-[85vw] bg-bg shadow-xl flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <p className="text-sm font-semibold text-ink">Sections</p>
              <button
                type="button"
                onClick={() => setMobileOpen(false)}
                aria-label="Close"
                className="w-8 h-8 inline-flex items-center justify-center rounded text-caption hover:text-ink hover:bg-surface"
              >
                <svg
                  className="w-4 h-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                  aria-hidden
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>
            <ul className="flex-1 overflow-y-auto py-2">
              {sections.map((sec) => {
                const isActive = sec.id === active
                return (
                  <li key={sec.id}>
                    <button
                      type="button"
                      data-testid={`toc-mobile-item-${sec.id}`}
                      data-active={isActive ? "true" : "false"}
                      onClick={() => handleClick(sec.id)}
                      className={cn(
                        "w-full text-left text-sm py-2.5 px-4 transition-colors",
                        isActive
                          ? "text-ink font-semibold bg-surface"
                          : "text-body hover:bg-surface",
                      )}
                    >
                      {sec.label}
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        </div>
      )}
    </>
  )
}

export { StickyTableOfContents }
