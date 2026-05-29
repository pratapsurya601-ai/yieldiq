"use client"
//
// StylePickerModal — first-visit picker that asks "How do you analyse?"
//
// Trigger rule: AnalysisBody mounts → if hasUserSeenPicker() is false,
// open this modal exactly once. User picks one of five styles or skips;
// either way we write to localStorage so we never re-prompt.
//
// SEBI-safe: labels are reading-style preferences, not recommendations.

import * as React from "react"
import {
  type InvestingStyle,
  STYLE_META,
  setStyleInStorage,
  markPickerSkipped,
} from "@/lib/personalization"

interface Props {
  open: boolean
  onClose: (picked: InvestingStyle | null) => void
}

const STYLES: InvestingStyle[] = ["value", "growth", "income", "beginner", "speculator"]

export default function StylePickerModal({ open, onClose }: Props) {
  const [selected, setSelected] = React.useState<InvestingStyle | null>(null)

  // Trap Esc → skip path.
  React.useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        markPickerSkipped()
        onClose(null)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open) return null

  const handleSave = () => {
    if (!selected) return
    setStyleInStorage(selected)
    onClose(selected)
  }

  const handleSkip = () => {
    markPickerSkipped()
    onClose(null)
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="style-picker-title"
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4 bg-black/50"
    >
      <div className="bg-bg w-full sm:max-w-2xl max-h-[92vh] overflow-y-auto rounded-t-2xl sm:rounded-2xl border border-border shadow-2xl">
        <div className="p-4 sm:p-6">
          <h2
            id="style-picker-title"
            className="font-display text-xl sm:text-2xl font-semibold text-ink"
          >
            How do you read a stock?
          </h2>
          <p className="text-sm text-caption mt-1.5 max-w-prose">
            Pick the lens that fits you best. We&rsquo;ll reorder the Summary
            tab so what matters to you lands first. You can change this any
            time in Preferences.
          </p>

          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
            {STYLES.map((s) => {
              const meta = STYLE_META[s]
              const isSel = selected === s
              return (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSelected(s)}
                  aria-pressed={isSel}
                  className={`text-left rounded-xl border p-4 transition active:scale-[0.99] ${
                    isSel
                      ? "border-brand bg-brand-50 ring-2 ring-brand"
                      : "border-border bg-surface hover:border-ink/40"
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <span className="text-2xl" aria-hidden>
                      {meta.emoji}
                    </span>
                    <span className="font-semibold text-ink">{meta.label}</span>
                  </div>
                  <p className="text-xs text-caption mt-1.5 leading-snug">
                    {meta.description}
                  </p>
                </button>
              )
            })}
          </div>

          <div className="mt-6 flex flex-col-reverse sm:flex-row items-stretch sm:items-center justify-between gap-2">
            <button
              type="button"
              onClick={handleSkip}
              className="text-sm text-caption hover:text-ink py-2.5 px-3 rounded-lg transition"
            >
              Skip &mdash; I&rsquo;ll decide later
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!selected}
              className="bg-brand text-white text-sm font-semibold px-4 py-2.5 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 transition"
            >
              Save my preference
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
