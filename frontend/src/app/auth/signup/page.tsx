"use client"
import { useState, useEffect, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { signup } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { trackSignupCompleted } from "@/lib/analytics"
import Cookies from "js-cookie"
import Link from "next/link"

function SignupContent() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [referralCode, setReferralCode] = useState<string | null>(null)
  const router = useRouter()
  const searchParams = useSearchParams()

  useEffect(() => {
    const ref = searchParams.get("ref")
    if (ref) setReferralCode(ref)
  }, [searchParams])

  const { setAuth } = useAuthStore()

  const handleSignup = async () => {
    setError("")
    if (password.length < 6) { setError("Password must be at least 6 characters"); return }
    setLoading(true)
    try {
      const res = await signup(email, password, referralCode)
      Cookies.set("yieldiq_token", res.access_token, { expires: 7 })
      setAuth(
        res.access_token,
        res.user_id,
        res.email,
        res.tier,
        0,
        5,
        res.display_name ?? null,
        res.display_name_edits_remaining ?? 3,
        res.feature_flags ?? {},
      )
      // Reset onboarding state for new users — both the zustand-persisted
      // settings store AND the onboardingPreferences blob. This avoids a
      // previous user's completed-state lingering on a shared device.
      // (Backend is always the cross-device source of truth on login; this
      // just prevents a local-cache false-positive on the immediate
      // post-signup redirect, before we've called getOnboardingStatus.)
      try {
        const settingsStore = JSON.parse(localStorage.getItem("yieldiq-settings") || "{}")
        if (settingsStore.state) {
          settingsStore.state.onboardingComplete = false
          localStorage.setItem("yieldiq-settings", JSON.stringify(settingsStore))
        }
        localStorage.removeItem("yieldiq_prefs")
      } catch { /* localStorage disabled — fine, nothing to clear */ }
      // Honor ?next= redirect (from pricing page tier-aware CTAs, etc.)
      const next = searchParams.get("next")
      // GA4: signup_completed with source so we can split the funnel
      // (direct signups vs. pricing-driven vs. referral).
      const source = next?.startsWith("/account?upgrade=")
        ? "pricing_upgrade"
        : referralCode
          ? "referral"
          : "direct"
      trackSignupCompleted(source)
      router.push(next && next.startsWith("/") ? next : "/onboarding")
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Signup failed"
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    // [color-scheme:light] prevents dark-mode browsers from leaking light
    // grey input text on the white card. See login/page.tsx for context.
    <div className="min-h-screen flex items-center justify-center px-4 bg-gray-50 [color-scheme:light]">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <img src="/logo-new.svg" alt="YieldIQ" className="w-16 h-16 rounded-xl mx-auto mb-3" />
          <h1 className="text-2xl font-bold text-gray-900">YieldIQ</h1>
          <p className="text-sm text-gray-500 mt-1">Start analysing stocks in 60 seconds</p>
        </div>
        <div className="bg-white rounded-2xl border border-gray-100 p-6 space-y-4">
          <h2 className="text-lg font-semibold text-gray-900">Create account</h2>
          {referralCode && (
            <p className="text-xs text-green-700 bg-green-50 rounded-lg px-3 py-2">
              Referred by a friend! They will earn bonus analyses when you sign up.
            </p>
          )}
          {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="Email" className="w-full px-4 py-3 bg-white text-gray-900 placeholder:text-gray-400 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSignup()}
            placeholder="Password (min 6 characters)" className="w-full px-4 py-3 bg-white text-gray-900 placeholder:text-gray-400 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <button onClick={handleSignup} disabled={loading}
            className="w-full py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50">
            {loading ? "Creating account..." : "Create free account"}
          </button>
          <p className="text-center text-sm text-gray-500">
            Already have an account? <Link href="/auth/login" className="text-blue-600 font-medium hover:underline">Sign in</Link>
          </p>
        </div>
        <p className="text-[10px] text-gray-400 text-center">5 free analyses per day. No credit card required.</p>
        <div className="text-center pt-2 border-t border-gray-100">
          <p className="text-xs text-gray-500 mb-1">Not ready to sign up?</p>
          <Link
            href="/stocks/RELIANCE/fair-value"
            className="text-xs font-semibold text-blue-600 hover:text-blue-700"
          >
            Try a sample analysis first (Reliance) &rarr;
          </Link>
        </div>
      </div>
    </div>
  )
}

export default function SignupPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
      </div>
    }>
      <SignupContent />
    </Suspense>
  )
}
