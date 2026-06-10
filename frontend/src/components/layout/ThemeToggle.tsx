"use client"

import { useEffect, useState, useCallback } from "react"
import PressScale from "@/components/motion/PressScale"

type Theme = "light" | "dark"
const STORAGE_KEY = "yieldiq_theme"
const DEFAULT_THEME: Theme = "dark"

/**
 * 2-way theme toggle (Light / Dark). Persists choice to localStorage
 * under `yieldiq_theme` and mirrors the resolved light/dark state onto
 * <html> as a `.dark` class (Tailwind v4 `@custom-variant` reads this).
 *
 * The anti-FOUC inline script in app/layout.tsx performs the *initial*
 * read on page load; this component only handles user interaction after
 * hydration.
 *
 * Migration (2026-06): dark is the premium-fintech default
 * (Bloomberg / Koyfin / TradingView / AlphaSpread). Any stored value
 * other than "light" — including the historical "system" sentinel,
 * the legacy "light" default that was rewritten on every load, or a
 * missing key — is normalised to "dark" on next load. An explicit
 * "light" set by a returning user is honoured as-is.
 */
function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark")
}

function readStoredTheme(): Theme {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === "light") return "light"
    // One-time migration: anything else (including "system" or null)
    // becomes "dark". Persist so we don't have to re-migrate on every
    // page load.
    if (raw !== "dark") {
      localStorage.setItem(STORAGE_KEY, DEFAULT_THEME)
    }
    return DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(DEFAULT_THEME)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setTheme(readStoredTheme())
    setMounted(true)
  }, [])

  const choose = useCallback((next: Theme) => {
    setTheme(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // localStorage may be unavailable (private mode, SSR edge cases)
    }
    applyTheme(next)
  }, [])

  // Render stable markup during SSR/pre-hydration to avoid mismatch.
  const current = mounted ? theme : DEFAULT_THEME

  return (
    <div
      role="group"
      aria-label="Theme"
      className="inline-flex items-center gap-0.5 rounded-full border border-border bg-surface p-0.5 text-caption"
    >
      {(["light", "dark"] as const).map((opt) => {
        const active = current === opt
        return (
          <PressScale key={opt} className="rounded-full" as="span">
            <button
              type="button"
              onClick={() => choose(opt)}
              aria-pressed={active}
              className={
                "rounded-full px-2.5 py-1 text-[11px] font-medium capitalize transition " +
                (active
                  ? "bg-brand text-white shadow-sm"
                  : "hover:text-ink")
              }
            >
              {opt}
            </button>
          </PressScale>
        )
      })}
    </div>
  )
}
