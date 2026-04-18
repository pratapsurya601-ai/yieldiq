"use client"

import { useState } from "react"
import type { InterestKey } from "@/lib/onboardingPreferences"

interface InterestCard {
  key: InterestKey
  title: string
  desc: string
  icon: string
}

const CARDS: InterestCard[] = [
  { key: "value", title: "Value", desc: "I buy stocks below intrinsic worth", icon: "◆" },
  { key: "quality", title: "Quality", desc: "I want profitable, low-debt compounders", icon: "◉" },
  { key: "growth", title: "Growth", desc: "I favor fast-expanding revenue / earnings", icon: "▲" },
  { key: "income", title: "Income", desc: "Dividends + yield matter to me", icon: "●" },
]

interface StepInterestsProps {
  initial?: InterestKey[]
  onContinue: (selected: InterestKey[]) => void
}

export default function StepInterests({ initial = [], onContinue }: StepInterestsProps) {
  const [selected, setSelected] = useState<InterestKey[]>(initial)

  const toggle = (key: InterestKey) => {
    setSelected((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    )
  }

  const canContinue = selected.length > 0

  return (
    <div className="flex flex-col min-h-[calc(100vh-56px)] px-5 pb-8">
      <header className="pt-6 pb-6">
        <h1 className="font-editorial text-3xl sm:text-4xl text-ink leading-tight">
          What matters to you?
        </h1>
        <p className="mt-2 text-base text-body">
          Pick one or more — we&apos;ll tune what we surface.
        </p>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 flex-1">
        {CARDS.map((c) => {
          const active = selected.includes(c.key)
          return (
            <button
              key={c.key}
              type="button"
              role="checkbox"
              aria-checked={active}
              aria-label={`${c.title}: ${c.desc}`}
              onClick={() => toggle(c.key)}
              className={
                "text-left rounded-2xl border p-4 min-h-[88px] transition-all duration-200 " +
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60 " +
                (active
                  ? "bg-brand/5 border-brand shadow-sm"
                  : "bg-surface border-border hover:border-ink/30")
              }
            >
              <div className="flex items-start gap-3">
                <span
                  aria-hidden="true"
                  className={
                    "flex items-center justify-center w-9 h-9 rounded-full text-lg flex-shrink-0 " +
                    (active ? "bg-brand text-white" : "bg-bg text-body")
                  }
                >
                  {c.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-semibold text-ink">{c.title}</p>
                    <span
                      aria-hidden="true"
                      className={
                        "w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 " +
                        (active ? "border-brand bg-brand" : "border-border")
                      }
                    >
                      {active ? (
                        <svg
                          viewBox="0 0 12 12"
                          className="w-3 h-3 text-white"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.5"
                        >
                          <path d="M2 6l2.5 2.5L10 3" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      ) : null}
                    </span>
                  </div>
                  <p className="text-sm text-body mt-0.5 leading-snug">{c.desc}</p>
                </div>
              </div>
            </button>
          )
        })}
      </div>

      <div className="pt-6 sticky bottom-0 bg-bg">
        <button
          type="button"
          disabled={!canContinue}
          onClick={() => onContinue(selected)}
          className={
            "w-full min-h-[52px] rounded-full font-semibold text-base transition-all " +
            (canContinue
              ? "bg-ink text-bg hover:opacity-90 active:scale-[0.99]"
              : "bg-border text-caption cursor-not-allowed")
          }
        >
          Continue
        </button>
        <p className="text-center text-xs text-caption mt-3">
          {selected.length === 0
            ? "Select at least one to continue"
            : `${selected.length} selected`}
        </p>
      </div>
    </div>
  )
}
