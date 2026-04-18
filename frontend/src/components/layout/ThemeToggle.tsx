"use client"

import { useEffect, useState, useCallback } from "react"

type Theme = "light" | "dark" | "system"
const STORAGE_KEY = "yieldiq_theme"

/**
 * 3-way theme toggle. Persists choice to localStorage under
 * `yieldiq_theme` and mirrors the resolved light/dark state onto
 * <html> as a `.dark` class (Tailwind v4 `@custom-variant` reads
 * this). The anti-FOUC inline script in app/layout.tsx performs
 * the *initial* read on page load; this component only handles
 * user interaction + media-query sync after hydration.
 */
function applyTheme(theme: Theme) {
  const isDark =
    theme === "dark" ||
    (theme === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches)
  document.documentElement.classList.toggle("dark", isDark)
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("system")
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    const stored = (localStorage.getItem(STORAGE_KEY) as Theme | null) ?? "system"
    setTheme(stored)
    setMounted(true)
  }, [])

  // When the user picks "system", keep the class in sync with OS
  // theme changes while the page is open.
  useEffect(() => {
    if (!mounted || theme !== "system") return
    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const handler = () => applyTheme("system")
    mq.addEventListener("change", handler)
    return () => mq.removeEventListener("change", handler)
  }, [mounted, theme])

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
  const current = mounted ? theme : "system"

  return (
    <div
      role="group"
      aria-label="Theme"
      className="inline-flex items-center gap-0.5 rounded-full border border-border bg-surface p-0.5 text-caption"
    >
      {(["light", "system", "dark"] as const).map((opt) => {
        const active = current === opt
        return (
          <button
            key={opt}
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
        )
      })}
    </div>
  )
}
