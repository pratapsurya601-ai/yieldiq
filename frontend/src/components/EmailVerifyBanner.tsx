"use client"

// EmailVerifyBanner — top-of-page nudge shown to logged-in users with
// !emailVerified. Soft gate: it never blocks navigation or free
// analyses; the paid-upgrade / API-key / Pro-export buttons read the
// same flag and refuse to proceed without verification.
//
// Behaviour:
//   • Hidden when logged-out OR emailVerified=true OR sessionStorage
//     dismiss-flag is set.
//   • "Resend" button hits POST /api/v1/auth/verify/send.
//     - 200 → "We sent a new verification email."
//     - 429 → echoes the throttle message.
//     - 503 → "We can't send right now. Please try again in a few
//       minutes." (SendGrid not configured / outage.)
//   • "Dismiss" sets sessionStorage so the banner stays gone for the
//     rest of this tab session and returns on next page load / new tab.
//
// Mounted from frontend/src/app/(app)/layout.tsx so it shows on every
// in-app page (home, analysis, portfolio, account, …) but NOT on the
// marketing tree.

import { useEffect, useState } from "react"
import api from "@/lib/api"
import { useAuthStore } from "@/store/authStore"

const DISMISS_KEY = "yieldiq.emailVerifyBanner.dismissed"

export default function EmailVerifyBanner() {
  const token = useAuthStore((s) => s.token)
  const email = useAuthStore((s) => s.email)
  const emailVerified = useAuthStore((s) => s.emailVerified)
  const setEmailVerified = useAuthStore((s) => s.setEmailVerified)

  const [dismissed, setDismissed] = useState<boolean>(false)
  const [sending, setSending] = useState(false)
  const [msg, setMsg] = useState<{ text: string; tone: "ok" | "err" } | null>(null)

  // Read sessionStorage once on mount (avoids SSR hydration mismatch).
  useEffect(() => {
    if (typeof window === "undefined") return
    try {
      setDismissed(sessionStorage.getItem(DISMISS_KEY) === "1")
    } catch {
      // SecurityError in some embedded contexts — treat as not dismissed.
    }
  }, [])

  // Refresh the verified flag once per session by pulling /auth/me.
  // Cheap (cached on the backend) and keeps a stale persisted Zustand
  // value (e.g. from before the user verified in another tab) honest.
  useEffect(() => {
    if (!token) return
    let alive = true
    api
      .get("/api/v1/auth/me")
      .then((r) => {
        if (!alive) return
        const fresh = r.data?.email_verified
        if (typeof fresh === "boolean" && fresh !== emailVerified) {
          setEmailVerified(fresh)
        }
      })
      .catch(() => {
        // Silent — banner falls back to persisted state.
      })
    return () => {
      alive = false
    }
    // We only want this refresh on login transition, not on every
    // emailVerified flip — deps intentionally minimal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  if (!token || emailVerified || dismissed) return null

  const handleResend = async () => {
    setSending(true)
    setMsg(null)
    try {
      await api.post("/api/v1/auth/verify/send")
      setMsg({
        text: `We sent a verification link to ${email ?? "your inbox"}. Check spam if it doesn’t arrive in a minute.`,
        tone: "ok",
      })
    } catch (err: unknown) {
      const ax = err as {
        response?: { status?: number; data?: { detail?: string } }
      }
      const status = ax?.response?.status
      const detail = ax?.response?.data?.detail
      if (status === 503) {
        setMsg({
          text: "We can’t send right now. Please try again in a few minutes.",
          tone: "err",
        })
      } else if (status === 429 && typeof detail === "string") {
        setMsg({ text: detail, tone: "err" })
      } else {
        setMsg({
          text: typeof detail === "string" ? detail : "Couldn’t resend the email. Try again shortly.",
          tone: "err",
        })
      }
    } finally {
      setSending(false)
    }
  }

  const handleDismiss = () => {
    try {
      sessionStorage.setItem(DISMISS_KEY, "1")
    } catch {
      // ignore
    }
    setDismissed(true)
  }

  return (
    <div
      role="status"
      className="w-full bg-amber-50 dark:bg-amber-950/40 border-b border-amber-200 dark:border-amber-900"
    >
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="text-sm text-amber-900 dark:text-amber-100 flex-1 min-w-[16rem]">
          <span className="font-semibold">Verify your email</span>{" "}
          to unlock alerts, exports, and API access.
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleResend}
            disabled={sending}
            className="px-3 py-1.5 text-xs font-semibold rounded-md bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 transition"
          >
            {sending ? "Sending…" : "Resend verification"}
          </button>
          <button
            type="button"
            onClick={handleDismiss}
            aria-label="Dismiss verification banner"
            className="px-2 py-1 text-xs text-amber-800 dark:text-amber-200 hover:text-amber-900 dark:hover:text-amber-50"
          >
            Dismiss
          </button>
        </div>
        {msg && (
          <p
            className={
              "w-full text-xs " +
              (msg.tone === "ok"
                ? "text-amber-800 dark:text-amber-200"
                : "text-red-700 dark:text-red-300")
            }
            role={msg.tone === "err" ? "alert" : undefined}
          >
            {msg.text}
          </p>
        )}
      </div>
    </div>
  )
}
