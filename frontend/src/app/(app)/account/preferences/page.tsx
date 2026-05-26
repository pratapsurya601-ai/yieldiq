"use client"
//
// /account/preferences — investing-style picker preferences page.
// Same five cards as the first-visit modal, with the currently-selected
// style highlighted. Picking a new style writes to localStorage and
// shows a toast. "Clear my preference" reverts to the default ordering.

import * as React from "react"
import Link from "next/link"
import {
  type InvestingStyle,
  STYLE_META,
  getStyleFromStorage,
  setStyleInStorage,
  clearStyle,
} from "@/lib/personalization"

const STYLES: InvestingStyle[] = ["value", "growth", "income", "beginner", "speculator"]

export default function PreferencesPage() {
  const [active, setActive] = React.useState<InvestingStyle | null>(null)
  const [toast, setToast] = React.useState<string | null>(null)

  React.useEffect(() => {
    setActive(getStyleFromStorage())
  }, [])

  const pick = (s: InvestingStyle) => {
    setStyleInStorage(s)
    setActive(s)
    setToast(`Preference updated to ${STYLE_META[s].label}.`)
    setTimeout(() => setToast(null), 2500)
  }

  const reset = () => {
    clearStyle()
    setActive(null)
    setToast("Preference cleared. The Summary tab will use the default ordering.")
    setTimeout(() => setToast(null), 2500)
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 pb-20">
      <nav className="text-xs text-caption mb-4">
        <Link href="/account" className="hover:text-ink">
          Account
        </Link>{" "}
        / <span className="text-ink">Preferences</span>
      </nav>
      <h1 className="font-display text-2xl md:text-3xl font-semibold text-ink">
        Reading preferences
      </h1>
      <p className="text-sm text-body mt-2 max-w-prose">
        Choose how you read a stock. We&rsquo;ll reorder the Summary tab so
        what matters to you lands first. This setting lives on this device
        only.
      </p>

      <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-3">
        {STYLES.map((s) => {
          const meta = STYLE_META[s]
          const isSel = active === s
          return (
            <button
              key={s}
              type="button"
              onClick={() => pick(s)}
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
                {isSel ? (
                  <span className="ml-auto text-[10px] font-bold uppercase tracking-wider text-brand">
                    Active
                  </span>
                ) : null}
              </div>
              <p className="text-xs text-caption mt-1.5 leading-snug">
                {meta.description}
              </p>
            </button>
          )
        })}
      </div>

      <div className="mt-6 flex items-center gap-3">
        <button
          type="button"
          onClick={reset}
          disabled={active === null}
          className="text-sm text-caption hover:text-ink disabled:opacity-40 disabled:cursor-not-allowed py-2 px-3 rounded-lg border border-border transition"
        >
          Clear my preference
        </button>
      </div>

      {toast ? (
        <div
          role="status"
          className="fixed bottom-20 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-sm font-medium px-4 py-2.5 rounded-lg shadow-lg z-50"
        >
          {toast}
        </div>
      ) : null}
    </div>
  )
}
