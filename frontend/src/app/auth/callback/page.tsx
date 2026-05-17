"use client"
/**
 * OAuth callback — lands here after Supabase finishes the Google round-trip.
 *
 * Supabase returns the Supabase access_token + id_token in the URL HASH
 * (not query string — hash fragments never hit the server). We parse the
 * Google id_token out of the hash, POST it to /api/v1/auth/google to
 * exchange for a YieldIQ JWT, then route the user:
 *   - new user           → /onboarding
 *   - returning user     → /home  (or the stashed ?next= if present)
 *
 * Error states (user cancelled, token missing, backend rejection) drop
 * the user back on /auth/login with a friendly message.
 */
import { Suspense, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Cookies from "js-cookie"
import { exchangeGoogleIdToken, getOnboardingStatus } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { trackSignupCompleted } from "@/lib/analytics"
import { pickGoogleIdToken } from "./pickGoogleIdToken"

function CallbackInner() {
  const router = useRouter()
  const { setAuth } = useAuthStore()
  const [message, setMessage] = useState("Finishing sign-in...")

  useEffect(() => {
    const run = async () => {
      try {
        // Supabase returns tokens in the URL hash, e.g.
        //   #access_token=…&expires_in=…&provider_token=…&id_token=…
        // For provider=google the Google ID token is the one we care about.
        const hash = (typeof window !== "undefined" ? window.location.hash : "") || ""
        const cleaned = hash.startsWith("#") ? hash.slice(1) : hash
        const params = new URLSearchParams(cleaned)

        // Surface any error Supabase reported (e.g. user denied consent).
        const errDesc = params.get("error_description") || params.get("error")
        if (errDesc) {
          throw new Error(errDesc)
        }

        // Prefer `provider_id_token` (Google's id_token JWT — verifiable via
        // tokeninfo). Fall back to Supabase's own `id_token` only when it is a
        // real 3-segment JWT. NEVER use `provider_token`: that's Google's
        // OPAQUE OAuth access_token, which tokeninfo rejects with HTTP 400
        // and surfaces as "Google rejected the sign-in token."
        const picked = pickGoogleIdToken(params)
        if (picked.fellBack) {
          console.warn(
            "[auth/callback] provider_id_token missing — falling back to Supabase id_token",
          )
        }
        if (!picked.idToken) {
          throw new Error("Google sign-in didn't return an ID token. Please try again.")
        }
        const idToken = picked.idToken

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

        const res = await exchangeGoogleIdToken(idToken, referralCode)

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
          // Google OAuth users are always verified — backend sets
          // email_verified=true in google_oauth_login_or_register.
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
