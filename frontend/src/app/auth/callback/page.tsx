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
 *
 * Two subtle bugs this file guards against (fix/oauth-cookie-domain-and-hash-timing):
 *
 *   1. Cookie domain mismatch — if the user starts on `yieldiq.in` and the
 *      OAuth round-trip bounces them to `www.yieldiq.in` (or vice versa),
 *      a host-only cookie won't follow. We set `domain=.yieldiq.in` so the
 *      cookie spans apex + www. Skipped on localhost.
 *
 *   2. Hash-cleared-too-early remount — the previous code wiped the URL
 *      hash BEFORE the auth POST resolved. Any remount (StrictMode, Next
 *      prefetch warm-up, hot nav) would re-run the effect, find no hash,
 *      and bounce the user to /auth/login?error=… We now: (a) write a
 *      sessionStorage idempotency key keyed on the token fingerprint
 *      before consuming, (b) skip the POST on remount if the same token
 *      has already been consumed, (c) only replaceState-clear the hash
 *      AFTER the auth POST resolves successfully.
 */
import { Suspense, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Cookies from "js-cookie"
import { loginWithSupabaseSession, getOnboardingStatus } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { trackSignupCompleted } from "@/lib/analytics"
import { pickSupabaseAccessToken } from "./pickSupabaseAccessToken"
import {
  tokenFingerprint,
  isLocalHost,
  cookieDomainForHost,
} from "./oauthCallbackHelpers"

const CONSUMED_KEY = "yieldiq_oauth_consumed"

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

        // Idempotency: if this exact token has already been consumed by a
        // prior mount (StrictMode / prefetch / hot-nav), skip the POST and
        // route based on existing auth state instead of bouncing to login.
        let consumedToken: string | null = null
        try {
          consumedToken = sessionStorage.getItem(CONSUMED_KEY)
        } catch {
          /* sessionStorage disabled */
        }

        if (!picked.accessToken) {
          // No hash token. If we already consumed one this session and the
          // auth store has a token, route the user instead of erroring.
          const existingToken =
            useAuthStore.getState().token || Cookies.get("yieldiq_token") || null
          if (consumedToken && existingToken) {
            router.push("/home")
            return
          }
          throw new Error("Sign-in didn't return a session token. Please try again.")
        }

        const accessToken = picked.accessToken
        const fp = tokenFingerprint(accessToken)

        if (consumedToken === fp) {
          // Same token already exchanged — don't double-POST. Route based
          // on whatever auth state already exists.
          const existingToken =
            useAuthStore.getState().token || Cookies.get("yieldiq_token") || null
          if (existingToken) {
            // Clear the hash now that we know the prior consumption stuck.
            try {
              if (typeof window !== "undefined") {
                window.history.replaceState({}, document.title, window.location.pathname)
              }
            } catch { /* ignore */ }
            router.push("/home")
            return
          }
          // Fall through — prior consumption never persisted, retry below.
        }

        // Mark as in-flight BEFORE the POST so a concurrent remount sees
        // the fingerprint and bails out. We accept the (tiny) risk that a
        // failed POST leaves the key set — the next sign-in attempt will
        // generate a different fingerprint.
        try {
          sessionStorage.setItem(CONSUMED_KEY, fp)
        } catch {
          /* sessionStorage disabled */
        }

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

        // Cookie domain fix: scope to `.yieldiq.in` so the cookie survives
        // an apex↔www bounce on the return trip. Localhost stays host-only.
        const host = typeof window !== "undefined" ? window.location.hostname : ""
        const cookieOpts: Cookies.CookieAttributes = {
          expires: 7,
          sameSite: "lax",
          secure: !isLocalHost(host),
        }
        const domain = cookieDomainForHost(host)
        if (domain) cookieOpts.domain = domain
        Cookies.set("yieldiq_token", res.access_token, cookieOpts)

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

        // Clear the hash ONLY after the auth POST succeeded and we have a
        // token in the store. If we cleared earlier, a remount would lose
        // the hash and bounce the user to /auth/login.
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
