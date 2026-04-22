"use client"
// ─────────────────────────────────────────────────────────────
// /auth/forgot-password — minimal password-reset trigger.
// Calls POST /api/v1/auth/forgot-password which asks Supabase to
// send a recovery email via the configured SMTP (SendGrid).
// Response is always success regardless of whether the email is
// registered (anti-enumeration on the backend); the user sees a
// "check your inbox" state either way.
// ─────────────────────────────────────────────────────────────
import { useState } from "react"
import Link from "next/link"
import api from "@/lib/api"

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("")
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState("")

  const handleSubmit = async () => {
    setError("")
    if (!email.trim() || !email.includes("@")) {
      setError("Enter a valid email address.")
      return
    }
    setLoading(true)
    try {
      await api.post("/api/v1/auth/forgot-password", { email: email.trim().toLowerCase() })
      setSent(true)
    } catch (err: unknown) {
      // Backend always returns 200 to prevent enumeration — a real
      // error here means the request itself failed (network, CORS, etc.)
      const msg = (err as { message?: string })?.message || "Couldn't send reset email. Try again."
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-gray-50">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <img src="/logo-new.svg" alt="YieldIQ" className="w-16 h-16 rounded-xl mx-auto mb-3" />
          <h1 className="text-2xl font-bold text-gray-900">YieldIQ</h1>
          <p className="text-sm text-gray-500 mt-1">Reset your password</p>
        </div>

        <div className="bg-white rounded-2xl border border-gray-100 p-6 space-y-4">
          {sent ? (
            <>
              <h2 className="text-lg font-semibold text-gray-900">Check your inbox</h2>
              <p className="text-sm text-gray-600">
                If an account with <strong className="font-semibold text-gray-900">{email}</strong>{" "}
                exists, we&rsquo;ve sent a password-reset link. Open the email
                and click the link to set a new password.
              </p>
              <p className="text-xs text-gray-400">
                No email in 1&ndash;2 minutes? Check your spam folder. Still nothing,{" "}
                <button
                  type="button"
                  onClick={() => { setSent(false); setEmail("") }}
                  className="text-blue-600 hover:underline"
                >
                  try again
                </button>
                .
              </p>
              <Link
                href="/auth/login"
                className="block w-full py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition text-center"
              >
                Back to sign in
              </Link>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-gray-900">Forgot password</h2>
              <p className="text-sm text-gray-500">
                Enter the email you signed up with. We&rsquo;ll send you a
                link to set a new password.
              </p>

              {error && (
                <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
                  {error}
                </p>
              )}

              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                placeholder="Email"
                className="w-full px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />

              <button
                onClick={handleSubmit}
                disabled={loading}
                className="w-full py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50"
              >
                {loading ? "Sending\u2026" : "Send reset link"}
              </button>

              <p className="text-center text-sm text-gray-500">
                Remembered it?{" "}
                <Link href="/auth/login" className="text-blue-600 font-medium hover:underline">
                  Sign in
                </Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
