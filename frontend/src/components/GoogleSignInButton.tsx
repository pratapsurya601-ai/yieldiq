"use client"
/**
 * Continue-with-Google button — shared between /auth/signup and /auth/login.
 *
 * On click we ask the backend for the Supabase-hosted OAuth consent URL
 * and hard-redirect the browser there. Supabase handles the Google
 * round-trip and bounces back to /auth/callback with the id_token in
 * the URL hash; the callback page exchanges it for a YieldIQ JWT.
 *
 * Per Google's branding guidelines the official "G" mark is rendered
 * inline as SVG so we don't pull in an extra asset request on a page
 * that needs to be conversion-fast.
 */
import { useState } from "react"
import { getGoogleOAuthUrl } from "@/lib/api"

interface Props {
  label?: string
  // Optional override; defaults to window.location.origin + /auth/callback
  // so preview deploys + localhost work without configuration.
  redirectTo?: string
}

export function GoogleSignInButton({ label = "Continue with Google", redirectTo }: Props) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleClick = async () => {
    setError(null)
    setLoading(true)
    try {
      // Default to the current origin's /auth/callback. The backend
      // enforces a soft allowlist (yieldiq.in + localhost) so this is safe.
      const cb =
        redirectTo ||
        (typeof window !== "undefined" ? `${window.location.origin}/auth/callback` : undefined)
      const { url } = await getGoogleOAuthUrl(cb)
      // Preserve any ?next= from the current URL through the OAuth dance
      // by stashing it in sessionStorage — survives the cross-origin hop
      // back from Supabase. The callback page reads + clears it.
      try {
        if (typeof window !== "undefined") {
          const next = new URLSearchParams(window.location.search).get("next")
          if (next) sessionStorage.setItem("yieldiq_oauth_next", next)
          const ref = new URLSearchParams(window.location.search).get("ref")
          if (ref) sessionStorage.setItem("yieldiq_oauth_ref", ref)
        }
      } catch {
        /* sessionStorage disabled — non-fatal, user just lands on /home */
      }
      window.location.href = url
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Could not start Google sign-in. Please try again."
      setError(msg)
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        aria-label={label}
        className="w-full flex items-center justify-center gap-3 py-3 bg-white text-gray-700 border border-gray-300 rounded-xl text-sm font-medium hover:bg-gray-50 transition disabled:opacity-50"
      >
        {/* Official Google "G" mark — colours per Google branding guidance.
            Inline SVG so it ships in the same HTML payload as the button. */}
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
          <path
            fill="#4285F4"
            d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"
          />
          <path
            fill="#34A853"
            d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.71H.957v2.332A8.997 8.997 0 009 18z"
          />
          <path
            fill="#FBBC05"
            d="M3.964 10.707A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.707V4.961H.957A8.997 8.997 0 000 9c0 1.452.348 2.827.957 4.039l3.007-2.332z"
          />
          <path
            fill="#EA4335"
            d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.961L3.964 7.293C4.672 5.166 6.656 3.58 9 3.58z"
          />
        </svg>
        <span>{loading ? "Redirecting to Google..." : label}</span>
      </button>
      {error && (
        <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
      )}
    </div>
  )
}

/**
 * Small "or" divider — placed between the Google button and the
 * email/password form to clearly separate the two pathways.
 */
export function OAuthDivider() {
  return (
    <div className="flex items-center gap-3 py-1" aria-hidden="true">
      <div className="h-px flex-1 bg-gray-200" />
      <span className="text-xs uppercase tracking-wide text-gray-400">or</span>
      <div className="h-px flex-1 bg-gray-200" />
    </div>
  )
}
