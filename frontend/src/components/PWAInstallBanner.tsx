"use client"
import { useState, useEffect, useCallback, useRef } from "react"
import { trackPwaEvent } from "@/lib/pwaAnalytics"

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>
}

const DISMISS_KEY = "yieldiq_pwa_dismiss"
const VIEW_COUNT_KEY = "yieldiq_pwa_views"
const MIN_VIEWS = 3
const DISMISS_TTL_MS = 30 * 864e5 // 30 days
const IOS_FALLBACK_DELAY_MS = 3000

// Day-100a: dismissal storage now holds a timestamp string. Older
// builds wrote "1" (non-numeric); we treat any non-finite parse as
// "dismissed long ago" and let the 30-day TTL re-show the banner.
function isDismissedWithinTtl(): boolean {
  const raw = localStorage.getItem(DISMISS_KEY)
  if (!raw) return false
  const ts = Number(raw)
  if (!Number.isFinite(ts)) return false
  return Date.now() - ts < DISMISS_TTL_MS
}

function isIosSafari(ua: string): boolean {
  return /iPhone|iPad|iPod/i.test(ua)
}

export default function PWAInstallBanner() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null)
  const [show, setShow] = useState(false)
  const [iosHint, setIosHint] = useState(false)
  // Guard so we only fire "prompted" once per mount even if React
  // re-runs effects (StrictMode dev double-invoke).
  const promptedRef = useRef(false)

  useEffect(() => {
    // Don't show if dismissed within the 30-day TTL
    if (isDismissedWithinTtl()) return

    // Track page views
    const views = parseInt(localStorage.getItem(VIEW_COUNT_KEY) || "0", 10) + 1
    localStorage.setItem(VIEW_COUNT_KEY, String(views))

    // Don't show until minimum views reached
    if (views < MIN_VIEWS) return

    // Don't show on desktop (only mobile browsers)
    const ua = navigator.userAgent
    const isMobile = /Android|iPhone|iPad|iPod/i.test(ua)
    if (!isMobile) return

    // Don't show if already installed as PWA (display-mode + iOS standalone)
    if (window.matchMedia("(display-mode: standalone)").matches) return
    const nav = navigator as Navigator & { standalone?: boolean }
    if (nav.standalone === true) return

    const handler = (e: Event) => {
      e.preventDefault()
      setDeferredPrompt(e as BeforeInstallPromptEvent)
      setShow(true)
    }

    window.addEventListener("beforeinstallprompt", handler)

    // iOS Safari never fires beforeinstallprompt. If we're on iOS and
    // 3s elapses without a prompt, fall back to the "Share → Add to
    // Home Screen" hint variant.
    let iosTimer: ReturnType<typeof setTimeout> | null = null
    if (isIosSafari(ua)) {
      iosTimer = setTimeout(() => {
        setIosHint((prev) => {
          // Only flip on if beforeinstallprompt hasn't claimed the slot
          if (prev) return prev
          return true
        })
        setShow((prev) => prev || true)
      }, IOS_FALLBACK_DELAY_MS)
    }

    return () => {
      window.removeEventListener("beforeinstallprompt", handler)
      if (iosTimer) clearTimeout(iosTimer)
    }
  }, [])

  // Fire the "prompted" / "ios_hint_shown" event exactly once when the
  // banner first becomes visible.
  useEffect(() => {
    if (!show || promptedRef.current) return
    promptedRef.current = true
    trackPwaEvent(iosHint ? "ios_hint_shown" : "prompted")
  }, [show, iosHint])

  const handleInstall = useCallback(async () => {
    if (!deferredPrompt) return
    await deferredPrompt.prompt()
    const choice = await deferredPrompt.userChoice
    if (choice.outcome === "accepted") {
      trackPwaEvent("installed")
      setShow(false)
    }
    setDeferredPrompt(null)
  }, [deferredPrompt])

  const handleDismiss = useCallback(() => {
    localStorage.setItem(DISMISS_KEY, String(Date.now()))
    trackPwaEvent("dismissed")
    setShow(false)
  }, [])

  if (!show) return null

  // Day-100a: iOS Safari variant — beforeinstallprompt is a Chromium-
  // only API, so on iPhone/iPad we coach the user through Share → Add
  // to Home Screen instead.
  if (iosHint) {
    return (
      <div className="fixed bottom-0 left-0 right-0 z-50 p-4 pb-safe">
        <div className="max-w-md mx-auto bg-bg dark:bg-surface border border-border rounded-2xl shadow-lg p-4 flex items-center gap-3">
          <img src="/logo-new.svg" alt="YieldIQ" loading="lazy" decoding="async" className="w-10 h-10 rounded-xl flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-ink">Add YieldIQ to Home Screen</p>
            <p className="text-xs text-caption flex items-center gap-1">
              Tap
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                className="inline-block w-3.5 h-3.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
                <polyline points="16 6 12 2 8 6" />
                <line x1="12" y1="2" x2="12" y2="15" />
              </svg>
              then Add to Home Screen
            </p>
          </div>
          <div className="flex gap-2 flex-shrink-0">
            <button
              onClick={handleDismiss}
              className="text-xs text-caption hover:text-ink px-2 py-1"
            >
              Not now
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    // Day-67 (2026-05-21): theme-aware tokens replace hardcoded
    // bg-white / text-gray. Same audit complaint that drove the
    // InstallPrompt.tsx changes above --- two PWA install components
    // exist in the codebase; this is the mobile-only one (300px,
    // <=3 views gate). Kept mobile-only positioning since this
    // component already self-gates on userAgent.
    <div className="fixed bottom-0 left-0 right-0 z-50 p-4 pb-safe">
      <div className="max-w-md mx-auto bg-bg dark:bg-surface border border-border rounded-2xl shadow-lg p-4 flex items-center gap-3">
        {/* loading="lazy" — this banner is conditional (mobile-only,
            3+ views), so the logo isn't above the fold and shouldn't
            trigger the "preloaded but unused" devtools warning. */}
        <img src="/logo-new.svg" alt="YieldIQ" loading="lazy" decoding="async" className="w-10 h-10 rounded-xl flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-ink">Add YieldIQ to Home Screen</p>
          <p className="text-xs text-caption">Quick access to stock analysis</p>
        </div>
        <div className="flex gap-2 flex-shrink-0">
          <button
            onClick={handleDismiss}
            className="text-xs text-caption hover:text-ink px-2 py-1"
          >
            Not now
          </button>
          <button
            onClick={handleInstall}
            className="text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition"
          >
            Install
          </button>
        </div>
      </div>
    </div>
  )
}
