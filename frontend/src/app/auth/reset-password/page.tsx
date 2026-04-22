"use client"
// ─────────────────────────────────────────────────────────────
// /auth/reset-password — password recovery final step.
//
// Supabase sends a recovery email with a link pointing HERE (see
// backend/routers/auth.py::forgot_password redirect_to). Supabase
// appends the session token to the URL hash in the shape:
//
//   /auth/reset-password#access_token=...&refresh_token=...&type=recovery
//
// The hash never reaches the server — it lives purely client-side.
// We parse it here, show a "set new password" form, then POST the
// token + new password to /api/v1/auth/update-password. That backend
// endpoint calls Supabase's REST API with the token as Bearer auth
// and updates the user's password.
//
// On success, redirect to /auth/login with a short-lived success
// state so the user knows what happened.
// ─────────────────────────────────────────────────────────────
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import api from "@/lib/api"

type TokenState =
  | { status: "loading" }
  | { status: "ready"; accessToken: string }
  | { status: "invalid"; reason: string }

export default function ResetPasswordPage() {
  const router = useRouter()
  const [tokenState, setTokenState] = useState<TokenState>({ status: "loading" })
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const [done, setDone] = useState(false)

  // Parse the URL hash once on mount. Supabase puts the recovery
  // token in the hash (not query) so we can't read it server-side.
  useEffect(() => {
    if (typeof window === "undefined") return
    const hash = window.location.hash.startsWith("#")
      ? window.location.hash.slice(1)
      : window.location.hash
    const params = new URLSearchParams(hash)
    const accessToken = params.get("access_token") || ""
    const type = params.get("type") || ""
    // Supabase sets type=recovery for password-reset flows. Other flows
    // (magiclink, signup confirm) would land here too if misconfigured
    // — reject anything that isn't recovery so we don't overwrite a
    // user's password during a different auth step.
    if (!accessToken) {
      setTokenState({
        status: "invalid",
        reason:
          "This page expected a password-reset link but didn\u2019t get one. Request a new link below.",
      })
      return
    }
    if (type && type !== "recovery") {
      setTokenState({
        status: "invalid",
        reason:
          "This link is for a different action, not a password reset. Request a new reset link.",
      })
      return
    }
    setTokenState({ status: "ready", accessToken })
  }, [])

  const handleSubmit = async () => {
    if (tokenState.status !== "ready") return
    setError("")
    if (password.length < 8) {
      setError("Password must be at least 8 characters.")
      return
    }
    if (password !== confirm) {
      setError("Passwords don\u2019t match.")
      return
    }
    setSubmitting(true)
    try {
      await api.post("/api/v1/auth/update-password", {
        access_token: tokenState.accessToken,
        new_password: password,
      })
      setDone(true)
      // Brief pause so the user sees the success state, then redirect
      // to login. We strip the hash first so their token isn\u2019t left
      // sitting in the URL bar.
      setTimeout(() => {
        if (typeof window !== "undefined") {
          window.history.replaceState(null, "", "/auth/reset-password")
        }
        router.push("/auth/login")
      }, 1800)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Couldn\u2019t set your password. Try a new reset link."
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-gray-50">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <img src="/logo-new.svg" alt="YieldIQ" className="w-16 h-16 rounded-xl mx-auto mb-3" />
          <h1 className="text-2xl font-bold text-gray-900">YieldIQ</h1>
          <p className="text-sm text-gray-500 mt-1">Set a new password</p>
        </div>

        <div className="bg-white rounded-2xl border border-gray-100 p-6 space-y-4">
          {tokenState.status === "loading" && (
            <p className="text-sm text-gray-500">Checking your reset link\u2026</p>
          )}

          {tokenState.status === "invalid" && (
            <>
              <h2 className="text-lg font-semibold text-gray-900">
                Reset link invalid
              </h2>
              <p className="text-sm text-gray-600">{tokenState.reason}</p>
              <Link
                href="/auth/forgot-password"
                className="block w-full py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition text-center"
              >
                Request a new reset link
              </Link>
              <p className="text-center text-sm text-gray-500">
                <Link href="/auth/login" className="text-blue-600 hover:underline">
                  Back to sign in
                </Link>
              </p>
            </>
          )}

          {tokenState.status === "ready" && !done && (
            <>
              <h2 className="text-lg font-semibold text-gray-900">Set new password</h2>
              <p className="text-sm text-gray-500">
                Enter a new password for your account. At least 8 characters.
              </p>

              {error && (
                <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
                  {error}
                </p>
              )}

              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="New password"
                autoComplete="new-password"
                className="w-full px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                placeholder="Confirm new password"
                autoComplete="new-password"
                className="w-full px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />

              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="w-full py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50"
              >
                {submitting ? "Saving\u2026" : "Set new password"}
              </button>
            </>
          )}

          {done && (
            <>
              <h2 className="text-lg font-semibold text-gray-900">Password updated</h2>
              <p className="text-sm text-gray-600">
                You can sign in with your new password now. Redirecting\u2026
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
