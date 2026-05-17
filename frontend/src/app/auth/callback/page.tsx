"use client"
/**
 * OAuth callback — lands here after Supabase finishes the Google round-trip.
 *
 * Supabase returns its OWN session `access_token` (a 3-segment JWT signed
 * by Supabase) in the URL HASH alongside refresh_token / expires_in.
 * Google's `id_token` is NOT in the hash unless the Supabase project has
 * "Skip nonce checks" enabled — we don't rely on that toggle.
 *
 * We POST the Supabase session JWT to /api/v1/auth/supabase, which
 * validates it via the Supabase admin SDK (`auth.get_user`) and mints a
 * YieldIQ JWT. Then route the user:
 *   - new user           → /onboarding
 *   - returning user     → /home  (or the stashed ?next= if present)
 *
 * Error states (user cancelled, token missing, backend rejection) drop
 * the user back on /auth/login with a friendly message.
 */
import { Suspense, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Cookies from "js-cookie"
import { loginWithSupabaseSession, getOnboardingStatus } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { trackSignupCompleted } from "@/lib/analytics"
import { pickSupabaseAccessToken } from "./pickSupabaseAccessToken"

function CallbackInner() {
  const router = useRouter()
  const { setAuth } = useAuthStore()
  const [message, setMessage] = useState("Finishing sign-in...")

  useEffect(() => {
    const run = async () => {
      try {
        // Supabase returns tokens in the URL hash, e.g.
        //   #access_token=…&refresh_token=…&expires_in=…&token_type=bearer
        // The `access_token` IS Supabase's own session JWT, signed by Supabase.
        // We send it to the backend, which validates it via the admin SDK.
        const hash = (typeof window !== "undefined" ? window.location.hash : "") || ""
        const cleaned = hash.startsWith("#") ? hash.slice(1) : hash
        const params = new URLSearchParams(cleaned)

        // Surface any error Supabase reported (e.g. user denied consent).
        const errDesc = params.get("error_description") || params.get("error")
        if (errDesc) {
          throw new Error(errDesc)
        }

        const picked = pickSupabaseAccessToken(params)
        if (!picked.accessToken) {
          throw new Error("Sign-in didn't return a session token. Please try again.")
        }
        const accessToken = picked.accessToken

        // Carry through ?next= and ref code stashed by GoogleSignInButton.
        let next: string | null = null
        let referralCode: string | null = null
        try {
          next = sessionStorage.getItem("yieldiq_oauth_next")
          referralCode = sessionStorage.getItem("yieldiq_oauth_ref")
          sessionStorage.removeItem("yieldiq_oauth_next")
          sessionStorage.removeItem("yieldiq_oauth_ref")
        } catch {
          /* sessionStorage disabled */
        }

        const res = await loginWithSupabaseSession(accessToken, referralCode)

        Cookies.set("yieldiq_token", res.access_token, { expires: 7 })
        setAuth(
          res.access_token,
          res.user_id,
          res.email,
          res.tier,
          res.analyses_today,
          res.analysis_limit,
          res.display_name ?? null,
          res.display_name_edits_remaining ?? 3,
          res.feature_flags ?? {},
          // OAuth users are always verified — backend sets
          // email_verified=true in _oauth_login_or_register_from_verified.
          res.email_verified ?? true,
        )

        // Clear the hash so a refresh on /home doesn't re-trigger this page.
        try {
          if (typeof window !== "undefined") {
            window.history.replaceState({}, document.title, window.location.pathname)
          }
        } catch { /* ignore */ }

        if (res.is_new_user) {
          // Mirror the email-signup analytics + onboarding reset so the
          // funnel can split conversion by signup provider.
          try {
            trackSignupCompleted("google")
          } catch { /* ignore */ }
          try {
            const settingsStore = JSON.parse(localStorage.getItem("yieldiq-settings") || "{}")
            if (settingsStore.state) {
              settingsStore.state.onboardingComplete = false
              localStorage.setItem("yieldiq-settings", JSON.stringify(settingsStore))
            }
            localStorage.removeItem("yieldiq_prefs")
          } catch { /* localStorage disabled */ }
          router.push(next && next.startsWith("/") ? next : "/onboarding")
          return
        }

        // Returning user — check backend onboarding state before routing.
        let onboardingDone = false
        try {
          const status = await getOnboardingStatus()
          onboardingDone = status.source === "db" && status.completed
        } catch {
          /* network blip — default to /home so we don't drag returning users
             back through the wizard. */
          onboardingDone = true
        }
        const dest = next && next.startsWith("/") ? next : onboardingDone ? "/home" : "/onboarding"
        router.push(dest)
      } catch (err: unknown) {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          (err instanceof Error ? err.message : "Sign-in failed.")
        setMessage(msg)
        // Bounce back to /auth/login after a beat so the user can retry.
        setTimeout(() => {
          router.push(`/auth/login?error=${encodeURIComponent(msg)}`)
        }, 1800)
      }
    }
    void run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-gray-50 [color-scheme:light]">
      <div className="w-full max-w-sm text-center space-y-4">
        <div className="h-8 w-8 mx-auto animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        <p className="text-sm text-gray-600">{message}</p>
      </div>
    </div>
  )
}

export default function CallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      }
    >
      <CallbackInner />
    </Suspense>
  )
}
