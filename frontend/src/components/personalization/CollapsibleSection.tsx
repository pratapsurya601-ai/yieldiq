"use client"
//
// CollapsibleSection — Phase 4 personalization wrapper.
//
// Wraps each Summary-tab section in a <details>-like collapsible. Behaviour
// rules (must not regress for legacy users):
//
//   • If `defaultExpanded` is true (no style picked, or this key is in the
//     active style's defaultExpanded list) → renders fully expanded on
//     mount, equivalent to today's UX.
//   • If false → renders collapsed; click header to toggle.
//   • Beginner mode passes an `explainer` string → a small "ⓘ What this
//     means" sub-expander shows above the children when the section is open.
//   • Accent classes apply only to the numeric prefix + a thin divider
//     under the header. Children render exactly as before.
//
// IMPORTANT: this wrapper deliberately does NOT remount its children
// on collapse — we use CSS hide (display:none equivalent via aria + a
// max-height transition) so heavy components like CompoundedGrowthPanel
// keep their react-query cache hydrated. Closing/reopening must be free.

import * as React from "react"
import type { SectionKey, PersonalizationConfig } from "@/lib/personalization"
import { SECTION_TITLES, ACCENT_CLASSES } from "@/lib/personalization"

interface Props {
  sectionKey: SectionKey
  number: number
  defaultExpanded: boolean
  accentHue?: PersonalizationConfig["accentHue"]
  explainer?: string | null
  children: React.ReactNode
}

export default function CollapsibleSection({
  sectionKey,
  number,
  defaultExpanded,
  accentHue,
  explainer,
  children,
}: Props) {
  const [open, setOpen] = React.useState(defaultExpanded)
  const [explainerOpen, setExplainerOpen] = React.useState(false)
  const { title, caption } = SECTION_TITLES[sectionKey]
  const accent = accentHue ? ACCENT_CLASSES[accentHue] : null
  const sectionId = `section-${sectionKey}`

  // Keep state in sync if the parent flips defaultExpanded (rare — only
  // when style changes mid-session via preferences page in another tab).
  React.useEffect(() => {
    setOpen(defaultExpanded)
  }, [defaultExpanded])

  return (
    <section aria-labelledby={`${sectionId}-heading`} className="scroll-mt-16">
      <header
        className={`mt-12 mb-4 ${
          accent ? `border-b ${accent.divider} pb-3` : ""
        }`}
      >
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={`${sectionId}-body`}
          className="w-full text-left flex items-start justify-between gap-3 group"
        >
          <div className="min-w-0">
            <h2
              id={`${sectionId}-heading`}
              className="text-2xl md:text-3xl font-bold uppercase tracking-tight text-ink"
            >
              <span
                className={
                  accent ? accent.numeral : "text-caption opacity-60"
                }
              >
                {number}.
              </span>{" "}
              {title}
            </h2>
            <p className="text-sm text-caption max-w-prose mt-2">{caption}</p>
          </div>
          <span
            aria-hidden
            className="shrink-0 mt-2 text-caption group-hover:text-ink transition"
          >
            <svg
              className={`w-5 h-5 transition-transform ${open ? "rotate-180" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M19.5 8.25l-7.5 7.5-7.5-7.5"
              />
            </svg>
          </span>
        </button>

        {open && explainer ? (
          <div className="mt-3">
            <button
              type="button"
              onClick={() => setExplainerOpen((v) => !v)}
              aria-expanded={explainerOpen}
              className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full transition ${
                accent ? accent.chip : "bg-surface text-caption"
              }`}
            >
              <span aria-hidden>ⓘ</span>
              {explainerOpen ? "Hide explainer" : "What this means"}
            </button>
            {explainerOpen ? (
              <p className="text-sm text-body mt-2 max-w-prose leading-relaxed">
                {explainer}
              </p>
            ) : null}
          </div>
        ) : null}
      </header>

      {/* We keep children mounted but hide them when collapsed so heavy
          child components (CompoundedGrowthPanel, NewsWidget, etc.) keep
          their react-query state alive across open/close toggles. */}
      <div
        id={`${sectionId}-body`}
        hidden={!open}
        aria-hidden={!open}
      >
        {children}
      </div>
    </section>
  )
}
