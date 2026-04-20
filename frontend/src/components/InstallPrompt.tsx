"use client"

/**
 * InstallPrompt — PWA "Add to Home Screen" banner.
 *
 * Covers the three mobile install paths:
 *   1. Android Chrome / Edge: catch the `beforeinstallprompt` event and
 *      expose a button that calls `prompt()`.
 *   2. iOS Safari: no programmatic install API; show a one-time how-to
 *      card ("tap Share → Add to Home Screen").
 *   3. Already installed / standalone: render nothing.
 *
 * Suppresses itself for 30 days via localStorage after the user
 * dismisses it, so we're never annoying.
 */
import { useEffect, useState } from "react"

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>
}

const DISMISS_KEY = "yieldiq.installPrompt.dismissedAt"
const DISMISS_WINDOW_DAYS = 30

function wasRecentlyDismissed(): boolean {
  if (typeof window === "undefined") return false
  const raw = window.localStorage.getItem(DISMISS_KEY)
  if (!raw) return false
  const ts = parseInt(raw, 10)
  if (!Number.isFinite(ts)) return false
  const ageMs = Date.now() - ts
  return ageMs < DISMISS_WINDOW_DAYS * 86_400_000
}

function isStandalone(): boolean {
  if (typeof window === "undefined") return false
  // Chrome, Edge, Android: window.matchMedia
  if (window.matchMedia("(display-mode: standalone)").matches) return true
  // iOS Safari: legacy navigator.standalone
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  if ((window.navigator as any).standalone) return true
  return false
}

function isIOS(): boolean {
  if (typeof navigator === "undefined") return false
  // iPhone/iPad/iPod — modern iPads sometimes report MacIntel + touch
  const ua = navigator.userAgent
  if (/iPhone|iPad|iPod/.test(ua)) return true
  if (ua.includes("Mac") && "ontouchend" in document) return true
  return false
}

export default function InstallPrompt() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null)
  const [show, setShow] = useState(false)
  const [iosHelper, setIosHelper] = useState(false)

  useEffect(() => {
    if (isStandalone()) return
    if (wasRecentlyDismissed()) return

    // Android / Chrome path
    const onBip = (e: Event) => {
      e.preventDefault()
      setDeferred(e as BeforeInstallPromptEvent)
      setShow(true)
    }
    window.addEventListener("beforeinstallprompt", onBip)

    // iOS path — no event, so we just show the helper after 10s of
    // engagement. Only if the browser is Safari on iOS.
    let iosTimer: number | undefined
    if (isIOS()) {
      iosTimer = window.setTimeout(() => {
        if (!wasRecentlyDismissed()) {
          setIosHelper(true)
          setShow(true)
        }
      }, 10_000)
    }

    return () => {
      window.removeEventListener("beforeinstallprompt", onBip)
      if (iosTimer) window.clearTimeout(iosTimer)
    }
  }, [])

  const dismiss = () => {
    window.localStorage.setItem(DISMISS_KEY, String(Date.now()))
    setShow(false)
  }

  const install = async () => {
    if (!deferred) return
    await deferred.prompt()
    const choice = await deferred.userChoice
    if (choice.outcome === "accepted") {
      setShow(false)
    } else {
      dismiss()
    }
  }

  if (!show) return null

  return (
    <div
      role="dialog"
      aria-labelledby="install-prompt-title"
      className="fixed bottom-4 left-4 right-4 z-50 mx-auto max-w-sm rounded-2xl border border-gray-200 bg-white p-4 shadow-lg sm:right-auto sm:left-4"
    >
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 flex-none rounded-xl bg-blue-600 text-white font-bold grid place-items-center">
          Y
        </div>
        <div className="flex-1 min-w-0">
          <p id="install-prompt-title" className="text-sm font-semibold text-gray-900">
            Install YieldIQ
          </p>
          {iosHelper ? (
            <p className="mt-1 text-xs text-gray-600">
              Tap the Share icon &rarr; Add to Home Screen to install.
            </p>
          ) : (
            <p className="mt-1 text-xs text-gray-600">
              Get the app experience &mdash; fast launch, offline reads, home-screen icon.
            </p>
          )}
          <div className="mt-3 flex items-center gap-2">
            {!iosHelper && deferred && (
              <button
                onClick={install}
                className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700"
              >
                Install
              </button>
            )}
            <button
              onClick={dismiss}
              className="rounded-lg px-3 py-1.5 text-xs font-medium text-gray-500 hover:text-gray-700"
            >
              Not now
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
