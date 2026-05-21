"use client"
import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { login, getOnboardingStatus, completeOnboardingRemote } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { useSettingsStore } from "@/store/settingsStore"
import { markCompleted } from "@/lib/onboardingPreferences"
import Cookies from "js-cookie"
import Link from "next/link"
import { GoogleSignInButton, OAuthDivider } from "@/components/GoogleSignInButton"

function LoginContent() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const router = useRouter()
  const searchParams = useSearchParams()

  // Surface ?error= set by the OAuth callback when sign-in fails
  // (user denied consent, token verification failed, etc.). Without this,
  // /auth/callback bounces back here silently and the user sees a fresh
  // login form with no explanation of why Google didn't work.
  useEffect(() => {
    const err = searchParams.get("error")
    if (err) setError(err)
  }, [searchParams])
  const { setAuth } = useAuthStore()
  const completeOnboardingStore = useSettingsStore((s) => s.completeOnboarding)

  /**
   * Resolve whether this user has completed onboarding.
   *
   * Source of truth = backend (Supabase user_onboarding table). Backend is
   * cross-device; localStorage is per-device. If the backend check fails
   * or is degraded (source="default"), we fall back to localStorage so a
   * transient Supabase hiccup doesn't force onboarded users back through
   * the wizard on every login.
   *
   * Only redirect to /onboarding if BOTH signals say "not completed".
   */
  const resolveOnboardingDone = async (): Promise<boolean> => {
    // Fast-path: localStorage. If either the zustand store OR the
    // onboardingPreferences blob says completed, treat that as the floor.
    let localDone = false
    try {
      const settings = JSON.parse(localStorage.getItem("yieldiq-settings") || "{}")
      localDone = Boolean(settings?.state?.onboardingComplete)
    } catch { /* corrupt localStorage — treat as not done */ }
    try {
      const prefs = JSON.parse(localStorage.getItem("yieldiq_prefs") || "{}")
      if (prefs?.completed === true) localDone = true
    } catch { /* ignore */ }

    // Authoritative: backend.
    try {
      const status = await getOnboardingStatus()
      if (status.source === "db") {
        // Backend was reachable and authoritative.
        // If backend says completed, sync it into localStorage so future
        // page loads don't flash the wizard while the API call is in flight.
        if (status.completed) {
          try {
            markCompleted()
            completeOnboardingStore()
          } catch { /* localStorage disabled / SSR — ignore */ }
          return true
        }
        // Backend says NOT completed. If localStorage says completed
        // (user onboarded here previously), trust localStorage AND push
        // that state to the backend in the background so next login
        // across devices is consistent.
        if (localDone) {
          void completeOnboardingRemote({ last_step: 3 }).catch(() => { /* best-effort */ })
          return true
        }
        return false
      }
      // source="default" → backend call succeeded but couldn't reach DB.
      // Fall back to localStorage.
      return localDone
    } catch {
      // Network/API error → localStorage fallback.
      return localDone
    }
  }

  const handleLogin = async () => {
    setError("")
    setLoading(true)
    try {
      const res = await login(email, password)
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
        res.email_verified ?? true,
      )

      const onboardingDone = await resolveOnboardingDone()
      router.push(onboardingDone ? "/home" : "/onboarding")
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Login failed"
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    // The auth surfaces are intentionally light-mode-only (most users land
    // in light browsers and the brand assumes a light frame). Set
    // color-scheme: light at the page wrapper so the browser's dark-mode
    // UA stylesheet does NOT leak into form controls. Without this,
    // Chrome on a dark-mode OS renders <input> text in light grey on the
    // white background — invisible. Caught 2026-04-25.
    <div className="min-h-screen flex items-center justify-center px-4 bg-bg dark:bg-surface [color-scheme:light]">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <img src="/logo-new.svg" alt="YieldIQ" className="w-16 h-16 rounded-xl mx-auto mb-3" />
          <h1 className="text-2xl font-bold text-ink">YieldIQ</h1>
          <p className="text-sm text-caption mt-1">Fair-value estimates for Indian stocks</p>
        </div>

        <div className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 p-6 space-y-4">
          <h2 className="text-lg font-semibold text-ink">Sign in</h2>

          {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

          {/* Google OAuth above the email form (Google's suggested
              placement + UX audit finding). */}
          <GoogleSignInButton label="Continue with Google" />
          <OAuthDivider />

          {/* Belt-and-braces: explicit text/bg/placeholder colors on the
              inputs so even if [color-scheme:light] above is ignored by an
              old browser, the typed text stays dark on light. */}
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="Email" className="w-full px-4 py-3 bg-bg dark:bg-surface text-ink placeholder:text-gray-400 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleLogin()}
            placeholder="Password" className="w-full px-4 py-3 bg-bg dark:bg-surface text-ink placeholder:text-gray-400 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />

          {/* Day-29 (2026-05-20): added inline spinner so the in-flight
              state is visually obvious. Previously only the disabled
              opacity + text change conveyed loading — easy to miss on
              fast networks where the text flips for <100ms then the
              redirect lands, leaving users uncertain whether the click
              registered. */}
          <button
            onClick={handleLogin}
            disabled={loading}
            data-testid="login-submit-button"
            className="w-full py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {loading && (
              <span
                aria-hidden="true"
                className="inline-block h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin"
              />
            )}
            <span>{loading ? "Signing in…" : "Sign in"}</span>
          </button>

          <p className="text-center text-sm text-caption">
            <Link href="/auth/forgot-password" className="text-blue-600 font-medium hover:underline">Forgot password?</Link>
          </p>

          <p className="text-center text-sm text-caption">
            No account? <Link href="/auth/signup" className="text-blue-600 font-medium hover:underline">Create one</Link>
          </p>
        </div>
      </div>
    </div>
  )
}

export default function LoginPage() {
  // Suspense wrapper required for useSearchParams() in this Next build —
  // matches the pattern used on /auth/signup.
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
      </div>
    }>
      <LoginContent />
    </Suspense>
  )
}
