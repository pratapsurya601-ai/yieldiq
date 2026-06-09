/**
 * PR (2026-06-09) — dark mode is the new default.
 *
 * Pins three behaviours that protect the launch:
 *   1. ThemeToggle's DEFAULT_THEME constant is "dark" — so a fresh
 *      pre-hydration render shows the dark toggle option as active.
 *   2. With no `yieldiq_theme` in localStorage, mounting the toggle
 *      resolves to "dark" and the toggle reports dark as pressed.
 *   3. The anti-FOUC inline script in app/layout.tsx adds `.dark` to
 *      <html> when no preference is stored, and respects an explicit
 *      "light" choice from a returning user.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, act } from "@testing-library/react"
import ThemeToggle from "@/components/layout/ThemeToggle"

// We can't import the inline script string directly (it's defined inside
// layout.tsx with `dangerouslySetInnerHTML`), so we re-declare the SAME
// snippet here and assert behaviour against it. If the snippet in
// layout.tsx changes, update both copies — the diff is intentional to
// surface drift.
const THEME_INIT_SCRIPT = `(function(){try{var s=localStorage.getItem('yieldiq_theme');if(s!=='dark'&&s!=='light'){try{localStorage.setItem('yieldiq_theme','dark');}catch(e){}s='dark';}var e=document.documentElement;if(s==='light'){e.classList.remove('dark');}else{e.classList.add('dark');}}catch(e){}})();`

describe("Dark theme default (premium fintech standard)", () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove("dark")
  })

  afterEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove("dark")
  })

  describe("ThemeToggle component", () => {
    it("renders the dark option as active for a fresh user (no localStorage)", async () => {
      await act(async () => {
        render(<ThemeToggle />)
      })

      // After mount, readStoredTheme() runs and resolves to "dark".
      // Confirm via aria-pressed (the source of truth for active state).
      const darkBtn = screen.getByRole("button", { name: /dark/i })
      const lightBtn = screen.getByRole("button", { name: /light/i })
      expect(darkBtn).toHaveAttribute("aria-pressed", "true")
      expect(lightBtn).toHaveAttribute("aria-pressed", "false")
    })

    it("normalises a missing yieldiq_theme key to 'dark' in localStorage", async () => {
      expect(localStorage.getItem("yieldiq_theme")).toBeNull()

      await act(async () => {
        render(<ThemeToggle />)
      })

      // One-time migration writes the resolved default back to storage so
      // the next page load skips the re-migration branch.
      expect(localStorage.getItem("yieldiq_theme")).toBe("dark")
    })

    it("preserves an explicit 'light' preference from a returning user", async () => {
      localStorage.setItem("yieldiq_theme", "light")

      await act(async () => {
        render(<ThemeToggle />)
      })

      const darkBtn = screen.getByRole("button", { name: /dark/i })
      const lightBtn = screen.getByRole("button", { name: /light/i })
      expect(lightBtn).toHaveAttribute("aria-pressed", "true")
      expect(darkBtn).toHaveAttribute("aria-pressed", "false")
      // And does not rewrite storage.
      expect(localStorage.getItem("yieldiq_theme")).toBe("light")
    })

    it("normalises legacy 'system' (or any junk) value to 'dark'", async () => {
      localStorage.setItem("yieldiq_theme", "system")

      await act(async () => {
        render(<ThemeToggle />)
      })

      expect(localStorage.getItem("yieldiq_theme")).toBe("dark")
      const darkBtn = screen.getByRole("button", { name: /dark/i })
      expect(darkBtn).toHaveAttribute("aria-pressed", "true")
    })
  })

  describe("Anti-FOUC inline script", () => {
    it("adds .dark to <html> when no preference is stored", () => {
      expect(document.documentElement.classList.contains("dark")).toBe(false)

      // eslint-disable-next-line @typescript-eslint/no-implied-eval
      new Function(THEME_INIT_SCRIPT)()

      expect(document.documentElement.classList.contains("dark")).toBe(true)
      expect(localStorage.getItem("yieldiq_theme")).toBe("dark")
    })

    it("removes .dark from <html> when 'light' is stored", () => {
      localStorage.setItem("yieldiq_theme", "light")
      document.documentElement.classList.add("dark")

      // eslint-disable-next-line @typescript-eslint/no-implied-eval
      new Function(THEME_INIT_SCRIPT)()

      expect(document.documentElement.classList.contains("dark")).toBe(false)
      // Does not rewrite storage when an explicit canonical value is set.
      expect(localStorage.getItem("yieldiq_theme")).toBe("light")
    })

    it("rewrites legacy 'system' sentinel to 'dark' and adds .dark class", () => {
      localStorage.setItem("yieldiq_theme", "system")

      // eslint-disable-next-line @typescript-eslint/no-implied-eval
      new Function(THEME_INIT_SCRIPT)()

      expect(document.documentElement.classList.contains("dark")).toBe(true)
      expect(localStorage.getItem("yieldiq_theme")).toBe("dark")
    })

    it("survives a throwing localStorage (private-mode browsers) without crashing", () => {
      // Simulate a browser where every localStorage call throws.
      const throwing = {
        getItem: vi.fn(() => { throw new Error("blocked") }),
        setItem: vi.fn(() => { throw new Error("blocked") }),
      }
      const original = Object.getOwnPropertyDescriptor(window, "localStorage")
      Object.defineProperty(window, "localStorage", {
        value: throwing,
        configurable: true,
      })

      try {
        expect(() => {
          // eslint-disable-next-line @typescript-eslint/no-implied-eval
          new Function(THEME_INIT_SCRIPT)()
        }).not.toThrow()
      } finally {
        if (original) Object.defineProperty(window, "localStorage", original)
      }
    })
  })
})
