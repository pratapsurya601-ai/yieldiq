"use client"
import { useState, useEffect, useCallback } from "react"

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>
}

const DISMISS_KEY = "yieldiq_pwa_dismiss"
const VIEW_COUNT_KEY = "yieldiq_pwa_views"
const MIN_VIEWS = 3

export default function PWAInstallBanner() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null)
  const [show, setShow] = useState(false)

  useEffect(() => {
    // Don't show if already dismissed
    if (localStorage.getItem(DISMISS_KEY)) return

    // Track page views
    const views = parseInt(localStorage.getItem(VIEW_COUNT_KEY) || "0", 10) + 1
    localStorage.setItem(VIEW_COUNT_KEY, String(views))

    // Don't show until minimum views reached
    if (views < MIN_VIEWS) return

    // Don't show on desktop (only mobile browsers)
    const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent)
    if (!isMobile) return

    // Don't show if already installed as PWA
    if (window.matchMedia("(display-mode: standalone)").matches) return

    const handler = (e: Event) => {
      e.preventDefault()
      setDeferredPrompt(e as BeforeInstallPromptEvent)
      setShow(true)
    }

    window.addEventListener("beforeinstallprompt", handler)
    return () => window.removeEventListener("beforeinstallprompt", handler)
  }, [])

  const handleInstall = useCallback(async () => {
    if (!deferredPrompt) return
    await deferredPrompt.prompt()
    const choice = await deferredPrompt.userChoice
    if (choice.outcome === "accepted") {
      setShow(false)
    }
    setDeferredPrompt(null)
  }, [deferredPrompt])

  const handleDismiss = useCallback(() => {
    localStorage.setItem(DISMISS_KEY, "1")
    setShow(false)
  }, [])

  if (!show) return null

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 p-4 pb-safe">
      <div className="max-w-md mx-auto bg-white border border-gray-200 rounded-2xl shadow-lg p-4 flex items-center gap-3">
        <img src="/logo-new.svg" alt="YieldIQ" className="w-10 h-10 rounded-xl flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-900">Add YieldIQ to Home Screen</p>
          <p className="text-xs text-gray-500">Quick access to stock analysis</p>
        </div>
        <div className="flex gap-2 flex-shrink-0">
          <button
            onClick={handleDismiss}
            className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1"
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
